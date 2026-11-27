# 环境模板（按实际集群填写）

本 skill 不绑定任何云厂商或固定集群。把下面各项替换成你的环境事实，写进
`lab.env` 或本文件，后续排查会更快。

## 集群

| 项 | 值 |
|-|-|
| kubeconfig | `~/.kube/config`（或 `ADMIN_KUBECONFIG`） |
| context | `<kubectl config current-context>` |
| Kubernetes 版本 | `<kubectl version>` |
| 容器运行时 | containerd / Docker / CRI-O |
| 演练命名空间 | `training-lab` |
| Chaos Mesh | `chaos-mesh` 命名空间，2.8.8 |
| Ingress 控制器 | `ingress-nginx` / 其他（`INGRESS_NS`、`INGRESS_SVC`） |

## 节点

| 节点 | 角色 | 备注 |
|-|-|-|
| `<node-1>` | worker | 默认演练节点 `TRAIN_NODE` |
| `<node-2>` | worker | 可选，操作需 `--allow-other` |
| `<虚拟节点>` | serverless | 通常不可 SSH，不能做节点级故障 |

节点需要：`stress`、`systemd-run`、`fallocate`、`iostat`/`vmstat`、`journalctl`。
如果节点是托管/Serverless 节点，节点级场景直接跳过。

## 镜像

| 用途 | 默认 | 覆盖变量 |
|-|-|-|
| 基线 / ML | `python:3.10-slim` | `LAB_IMAGE` |
| pause | `registry.k8s.io/pause:3.9` | `LAB_PAUSE_IMAGE` |
| Chaos Mesh | `ghcr.io/chaos-mesh/*:v2.8.8` | 修改 `chaos-mesh-values.yaml` |
| 镜像仓库 | `docker.io` | `LAB_REGISTRY` |

如果集群不能访问 docker.io/ghcr.io，先把镜像同步到内部仓库，再设置变量。

## SSH

| 模式 | 变量 |
|-|-|
| direct（默认） | `NODE_SSH_KEY`、`NODE_SSH_PORT`、`NODE_SSH_USER`、`TRAIN_NODE` |
| jump | `JUMP_HOST`、`JUMP_PORT`、`JUMP_USER`、`JUMP_KEY`、`TRAIN_NODE` |

未设置 `NODE_SSH_MODE` 时：配置了 `JUMP_HOST` 走 jump，否则 direct。
`TRAIN_NODE` 是默认演练节点；其他节点必须 `--allow-other`。

## 覆盖变量

| 变量 | 作用 |
|-|-|
| `LAB_HOME` | 工具箱目录，默认 `~/k8s-fault-lab` |
| `ADMIN_KUBECONFIG` | kubeconfig 路径 |
| `ADMIN_CONTEXT` | 集群 context |
| `KUBECTL_BIN` | kubectl 路径 |
| `LAB_IMAGE` | 基线与 ML 镜像 |
| `LAB_PAUSE_IMAGE` | PodFailure/finalizer pause 镜像 |
| `LAB_REGISTRY` | 镜像仓库域名 |
| `INGRESS_NS` / `INGRESS_SVC` | ingress-nginx 位置 |
| `LAB_TLS_IP` | registry-tls 场景使用的 HTTPS 入口 IP |

## 安全边界

- 默认只操作 `training-lab`；不碰业务命名空间。
- 节点级默认只操作 `TRAIN_NODE`；其他节点必须 `--allow-other`。
- `node-kubelet-stop` 需要 `--yes`；`node-hang`/`node-reboot`/`node-crash`
  需要 `--confirm`。
- 不读取/打印 kubeconfig Token、Secret；不 `delete --all`、不删 Namespace、
  不强清 finalizer。
- 注入后必须验证故障真实成立；恢复后必须复核基线。
