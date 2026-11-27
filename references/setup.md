# 新集群接入

本 skill 不绑定任何云厂商。只需要一个可用的 Kubernetes 集群、kubeconfig，
以及可选的节点 SSH（做节点级故障时）。

## 1. 前置条件

| 项 | 要求 |
|-|-|
| Kubernetes | v1.20+，能创建 Namespace/Deployment/Service/Ingress/Pod |
| kubectl | 与集群版本相差不超过 1 个 minor |
| Helm | v3.x（安装 Chaos Mesh 用） |
| 权限 | 安装 Chaos Mesh 需要集群级权限；只做业务层演练需要 `training-lab` 读写 |
| 容器运行时 | Chaos Mesh 默认 containerd；Docker 运行时需改 values |
| Ingress | `lab-adv` 的 Ingress/证书场景需要 ingress-nginx（可选） |

## 2. kubeconfig

```bash
kubectl config get-contexts
kubectl config use-context <目标 context>
kubectl get nodes
kubectl auth can-i create pods -n training-lab
kubectl auth can-i create chaosengines.chaos-mesh.org
```

非默认 kubeconfig/context：

```bash
export ADMIN_KUBECONFIG=/path/to/kubeconfig
export ADMIN_CONTEXT=<context>
```

## 3. 安装 Chaos Mesh

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  -n chaos-mesh --create-namespace --version 2.8.8 \
  -f ~/k8s-fault-lab/chaos-mesh-values.yaml
kubectl get pods -n chaos-mesh
```

如果集群无法访问 `ghcr.io`，先把三个镜像同步到内部仓库，再修改
`chaos-mesh-values.yaml` 的 `images.registry`。Docker 运行时：

```bash
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  -n chaos-mesh --create-namespace --version 2.8.8 \
  -f ~/k8s-fault-lab/chaos-mesh-values.yaml \
  --set chaosDaemon.runtime=docker \
  --set chaosDaemon.socketPath=/var/run/docker.sock
```

## 4. 镜像

默认使用公开镜像：

| 用途 | 默认 |
|-|-|
| 基线业务 / ML | `python:3.10-slim` |
| PodFailure / finalizer pause | `registry.k8s.io/pause:3.9` |

集群不能访问 docker.io 时，把镜像同步到内部仓库，并设置：

```bash
export LAB_IMAGE=<内部仓库>/python:3.10-slim
export LAB_PAUSE_IMAGE=<内部仓库>/pause:3.9
export LAB_REGISTRY=<内部仓库>
```

`lab baseline` 会渲染基线镜像；`lab-adv` / `ml-lab` 直接读取 `LAB_IMAGE`。

## 5. 节点 SSH（节点级故障）

节点级故障需要登录真实节点；托管集群的虚拟节点/Serverless 节点通常不可登录。

| 模式 | 适用环境 | 变量 |
|-|-|-|
| `direct`（默认） | 本机能直接 SSH 所有节点 | `NODE_SSH_KEY` / `NODE_SSH_PORT` / `NODE_SSH_USER` / `TRAIN_NODE` |
| `jump` | 本机不能直连，需要跳板机 | `JUMP_HOST` / `JUMP_PORT` / `JUMP_USER` / `JUMP_KEY` / `TRAIN_NODE` |

直连示例：

```bash
export NODE_SSH_MODE=direct
export NODE_SSH_KEY=$HOME/.ssh/id_rsa
export NODE_SSH_PORT=22
export NODE_SSH_USER=root
export TRAIN_NODE=10.0.0.10

chmod 600 "$NODE_SSH_KEY"
ssh -i "$NODE_SSH_KEY" -p "$NODE_SSH_PORT" "$NODE_SSH_USER@$TRAIN_NODE" hostname
```

跳板机示例：

```bash
export NODE_SSH_MODE=jump
export JUMP_HOST=203.0.113.10
export JUMP_PORT=22
export JUMP_USER=root
export JUMP_KEY=$HOME/.ssh/id_rsa
export TRAIN_NODE=10.0.0.10

ssh -i "$JUMP_KEY" -p "$JUMP_PORT" "$JUMP_USER@$JUMP_HOST"
# 跳板机内验证
ssh "$NODE_SSH_USER@$TRAIN_NODE" hostname
```

节点需要：`stress`、`systemd-run`、`fallocate`、`iostat`/`vmstat`、`journalctl`。
没有 `stress` 时先安装（Debian/Ubuntu: `apt install stress sysstat`）。

## 6. 统一环境文件

```bash
cp ~/k8s-fault-lab/lab.env.example ~/k8s-fault-lab/lab.env
vim ~/k8s-fault-lab/lab.env
set -a; source ~/k8s-fault-lab/lab.env; set +a
```

## 7. 安装与自检

```bash
bash ~/.trae/skills/k8s-fault-drill/scripts/install.sh --baseline
~/k8s-fault-lab/faultlab status
~/k8s-fault-lab/faultlab list
```

节点级自检：

```bash
~/k8s-fault-lab/faultlab run node-cpu 10
~/k8s-fault-lab/faultlab recover node-cpu
```

## 8. 可选：ingress-nginx

Ingress/证书场景需要 ingress-nginx：

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  -n ingress-nginx --create-namespace
```

如果控制器在其他命名空间，设置 `INGRESS_NS` / `INGRESS_SVC`。
