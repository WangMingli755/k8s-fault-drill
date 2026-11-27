---
name: k8s-fault-drill
description: 在任意 Kubernetes 集群做端到端故障演练：环境盘点 → 分层故障注入 → 现象验证 → 恢复复核 → 输出新人排查手册。覆盖 Chaos Mesh（网络延迟、CPU、Pod kill/failure、DNS）、高级 K8s（Ingress、TLS 证书、镜像仓库、调度、配额、探针）、机器学习训练/推理（OOM、崩溃、卡住、checkpoint 损坏、磁盘满、GPU 调度、推理超时）和节点级（SSH 直连或跳板机，制造 CPU/内存/OOM/磁盘/IO、kubelet 停止、节点 hang/重启/宕机）。不依赖任何云厂商 API。当用户说“K8s 故障演练、模拟故障、注入故障、一条口令制造故障、让新人排查、训练/推理异常、镜像拉不到、证书过期、节点 OOM/hang/宕机”时使用。
---

# Kubernetes 故障演练

在任意 K8s 集群的 `training-lab` 命名空间和节点上，用一条命令制造**可观测、可恢复**的故障，并给出新人能照着执行的排查路径。本包不含任何云厂商 API，适合通用 K8s 环境。

## 安全边界（先读）

1. 默认只操作 `training-lab`；不碰业务命名空间和系统组件。
2. 节点级默认只操作 `TRAIN_NODE`；其他节点必须 `--allow-other`，且先说明影响面。
3. `node-kubelet-stop` 必须 `--yes`；`node-hang` / `node-reboot` / `node-crash` 必须 `--confirm`。
4. 不读取或打印 kubeconfig Token、Secret；不 `delete --all`、不删 Namespace、不强清 finalizer。
5. 注入后必须验证“故障真实成立”（事件/日志/指标），不能把 apply 成功当结论。
6. 恢复后必须实测基线（`lab-client` 连续 `http=200`），并确认 Chaos CR、`training-*` unit、临时文件都已清理。
7. 没有真实 GPU 时，ML 场景只能 CPU 模拟；`gpu-unschedulable` 只演示调度 Pending。

## 工作流

### 1. 环境盘点

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl get pods -n training-lab
helm list -n chaos-mesh
```

确认集群可达、Chaos Mesh 已安装、`training-lab` 没有未恢复的旧实验。环境模板见 `references/environment.md`。

### 2. 新集群接入

详见 `references/setup.md`。核心步骤：

- kubeconfig 放到 `~/.kube/config`，`kubectl get nodes` 可用；非默认路径用 `ADMIN_KUBECONFIG` / `ADMIN_CONTEXT`。
- 安装 Chaos Mesh 2.8.8（`helm`，values 见 `scripts/chaos-mesh-values.yaml`）。
- 节点 SSH 两种模式：`NODE_SSH_MODE=direct`（本机直连，默认）或 `jump`（跳板机）。
- 镜像默认 `python:3.10-slim` / `registry.k8s.io/pause:3.9`，可用 `LAB_IMAGE` / `LAB_PAUSE_IMAGE` 覆盖。

### 3. 安装工具箱

```bash
bash ~/.trae/skills/k8s-fault-drill/scripts/install.sh --baseline
```

脚本把工具箱复制到 `~/k8s-fault-lab`，生成证书，并可选部署基线。已有环境可跳过；非默认目录用 `LAB_HOME` 指定。加 `--chaos` 会安装 Chaos Mesh（会改集群，需确认）。

### 4. 选择层级注入

```bash
~/k8s-fault-lab/faultlab list
~/k8s-fault-lab/faultlab run <场景> [参数...]
```

| 层 | 适用故障 | 执行器 |
|-|-|-|
| k8s | 网络延迟、CPU 压力、Pod kill/failure、DNS、Service selector、finalizer | `lab` |
| adv | Ingress、TLS 证书、镜像仓库、调度、配额、探针、配置缺失 | `lab-adv` |
| ml | 训练/推理 OOM、崩溃、卡住、坏 checkpoint、磁盘满、GPU 调度、推理超时 | `ml-lab` |
| node | 节点 CPU/内存/OOM/磁盘/IO、kubelet 停止、hang、重启、宕机 | `node_lab.py` |

完整场景、参数、现象和恢复方式见 `references/fault-catalog.md`。

### 5. 验证故障真实成立

- k8s / adv / ml：`kubectl -n training-lab get pod,event`、`describe`、`logs --previous`、`get endpoints`。
- node：按 SSH 模式登录节点，看 `dmesg -T`、`/var/log/messages`、`journalctl -u kubelet`、`ps -eo pid,stat,comm`、`vmstat`。

验收样例、判读标准和已知坑见 `references/verification.md`。

### 6. 恢复并复核

```bash
~/k8s-fault-lab/faultlab recover <场景|all>
```

恢复后重跑 `faultlab status`，确认基线 `http=200`、无残留 CR/unit/临时目录。

### 7. 输出排查手册

```bash
~/k8s-fault-lab/faultlab guide <场景>    # 或 guide all
```

把现象、关键命令、判读结论发给用户。新增场景时同步更新 `references/playbook.md` 和场景目录。

## 新增场景 checklist

1. 在对应执行器（`lab` / `lab-adv` / `ml-lab` / `node_lab.py`）增加注入与 `recover` 分支。
2. 把场景名加入 `faultlab list` 路由和 `references/fault-catalog.md`。
3. 在 `references/playbook.md` 增加同名 `## <场景>` 排查章节。
4. 实测“注入 → 取证现象 → 恢复 → 基线复核”，把结果写入 `references/verification.md`。
5. 确认无跨命名空间、无真实业务影响、无凭证泄露。

## 参考文件

- `README.md`：给人看的安装/接入说明（kubeconfig、直连/跳板机、自检）
- `references/setup.md`：新集群 kubeconfig、Chaos Mesh、镜像、SSH 直连/跳板机
- `references/environment.md`：环境模板（集群、节点、镜像、变量、安全边界）
- `references/fault-catalog.md`：四层场景、命令、现象、恢复
- `references/playbook.md`：51 个场景的新人排查手册（`faultlab guide` 的数据源）
- `references/verification.md`：验收记录、判读标准、已知坑
- `scripts/`：全部执行器、Chaos 清单、证书生成、ML 源码、安装脚本
