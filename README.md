# K8s 故障演练工具箱（通用版）

目标：在**任意 Kubernetes 集群**上用一条口令制造可观测、可恢复的故障，
并给出新人可照着做的排查路径。不依赖任何云厂商 API。

统一入口：

```bash
~/k8s-fault-lab/faultlab list
~/k8s-fault-lab/faultlab status
~/k8s-fault-lab/faultlab run <场景> [参数...]
~/k8s-fault-lab/faultlab recover <场景|all>
~/k8s-fault-lab/faultlab guide <场景|all>
```

## 分层能力

| 层 | 执行器 | 范围 | 恢复方式 |
|-|-|-|-|
| Chaos Mesh | `lab` | `training-lab` 内的网络/CPU/Pod/DNS 故障 | duration + guardian 自动回收 |
| 高级 K8s | `lab-adv` | Ingress/证书/镜像/调度/配额/探针等配置类故障 | 手动 `recover` |
| 机器学习 | `ml-lab` | `training-lab` 内训练/推理故障（CPU 模拟） | 手动 `recover` |
| 节点级 | `node_lab.py` | 本机直连或经跳板机 SSH 到节点 | 定时自动恢复 + `recover` |

共 51 个场景：Chaos 7 + 高级 K8s 23 + 机器学习 12 + 节点 9。

## 新机器准备（kubeconfig / SSH）

新机器不会自带集群凭据和节点 SSH 配置，先完成下面两步。

### 1. kubeconfig

1. 从集群管理员或控制台获取具备 `training-lab` 操作权限的 kubeconfig。
2. 放到 `~/.kube/config`；如果本机已有其他集群配置，先合并再切换：

```bash
KUBECONFIG=~/.kube/config:./new-kubeconfig kubectl config view --flatten > /tmp/merged
mv /tmp/merged ~/.kube/config
kubectl config get-contexts
kubectl config use-context <目标 context>
```

3. 验证：

```bash
kubectl get nodes
kubectl auth can-i create pods -n training-lab
kubectl auth can-i create chaosengines.chaos-mesh.org
```

安装 Chaos Mesh、创建命名空间和 CRD 需要集群级权限；只做业务层演练时，
至少需要 `training-lab` 的读写权限。没有权限时不要强行安装，先找集群管理员。
kubeconfig 不在默认路径时，用 `ADMIN_KUBECONFIG` / `ADMIN_CONTEXT` 指定；
`kubectl` 不在 `PATH` 时用 `KUBECTL_BIN` 指定。

### 2. 节点 SSH（两种模式）

节点级故障需要 SSH 到真实节点（虚拟节点/Serverless 节点无法登录，不要选）。
按环境选择一种模式，写进 `~/k8s-fault-lab/lab.env` 后 `source` 再执行命令：

```bash
cp ~/k8s-fault-lab/lab.env.example ~/k8s-fault-lab/lab.env
vim ~/k8s-fault-lab/lab.env
set -a; source ~/k8s-fault-lab/lab.env; set +a
```

**模式 A：本机直连所有节点（无跳板机，默认）**

适用于当前电脑能直接 SSH 到集群所有节点的环境。

```bash
NODE_SSH_MODE=direct
NODE_SSH_KEY=$HOME/.ssh/id_rsa
NODE_SSH_PORT=22
NODE_SSH_USER=root
TRAIN_NODE=10.0.0.10
# JUMP_HOST 留空
```

```bash
chmod 600 ~/.ssh/id_rsa
ssh -i ~/.ssh/id_rsa -p 22 root@10.0.0.10 hostname
# 逐台验证
for n in 10.0.0.10 10.0.0.11 10.0.0.12; do
  ssh -i ~/.ssh/id_rsa -p 22 -o BatchMode=yes root@$n hostname || echo "FAIL $n"
done
```

**模式 B：经跳板机**

适用于本机不能直连节点、只能先登录跳板机的环境。

```bash
NODE_SSH_MODE=jump
JUMP_HOST=203.0.113.10
JUMP_PORT=60011
JUMP_USER=root
JUMP_KEY=$HOME/.ssh/jump.pem
TRAIN_NODE=10.0.0.10
```

```bash
chmod 600 ~/.ssh/jump.pem
ssh -i ~/.ssh/jump.pem -p 60011 root@203.0.113.10
# 跳板机内验证免密
ssh root@10.0.0.10 hostname
```

`node_lab.py` 的模式选择规则：显式设置 `NODE_SSH_MODE` 优先；未设置时，
配置了 `JUMP_HOST` 走跳板机，否则走直连。`TRAIN_NODE` 是默认演练节点，
操作其他节点必须加 `--allow-other`。目标节点需要 `stress`、`systemd-run`、
`fallocate`、`iostat`/`vmstat` 等工具；没有的话先在节点上安装。

## 安装与自检

```bash
bash ~/.trae/skills/k8s-fault-drill/scripts/install.sh --baseline
~/k8s-fault-lab/faultlab status
```

`install.sh` 会把工具箱复制到 `~/k8s-fault-lab`、生成证书，可选部署基线。
非默认目录用 `LAB_HOME` 指定；加 `--chaos` 安装 Chaos Mesh（会改集群，需确认）。

自检清单：

- `kubectl get nodes` 全部 Ready；
- `helm list -n chaos-mesh` 有 release（只做业务层可跳过）；
- `faultlab status` 显示基线 Pod/Service 正常；
- `faultlab guide net-delay` 能输出排查步骤；
- 节点 SSH 按所选模式能 `hostname` 成功。

## 常用命令

```bash
~/k8s-fault-lab/faultlab list
~/k8s-fault-lab/faultlab run net-delay --delay 3s
~/k8s-fault-lab/faultlab guide net-delay
~/k8s-fault-lab/faultlab recover net-delay
~/k8s-fault-lab/faultlab run node-oom --node 10.0.0.10
```

节点 hang/重启/宕机必须加 `--confirm`，停止 kubelet 必须加 `--yes`；
默认只动 `training-lab` 和 `TRAIN_NODE`。

## 目录

```text
k8s-fault-drill/
├── SKILL.md                 # 技能入口（给 AI 的工作流）
├── README.md                # 本文
├── agents/openai.yaml
├── references/
│   ├── setup.md             # 新机器接入、Chaos Mesh、镜像、SSH
│   ├── environment.md       # 环境盘点模板
│   ├── fault-catalog.md     # 51 个场景总表
│   ├── playbook.md          # 新人排查手册
│   └── verification.md      # 验收与已知坑
└── scripts/                 # install.sh、faultlab、lab、lab-adv、ml-lab、node_lab.py 等
```
