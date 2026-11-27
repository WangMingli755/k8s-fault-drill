# 故障场景目录

统一入口：

```bash
~/k8s-fault-lab/faultlab list
~/k8s-fault-lab/faultlab run <场景> [参数...]
~/k8s-fault-lab/faultlab recover <场景|all>
~/k8s-fault-lab/faultlab guide <场景>
```

默认命名空间 `training-lab`；默认镜像 `python:3.10-slim`，可用 `LAB_IMAGE` 覆盖。

## k8s：Chaos Mesh（training-lab，自动到期）

| 场景 | 命令 | 现象 | 恢复 |
|-|-|-|-|
| 网络延迟 | `run net-delay 120` | lab-client 延迟从个位数升到约 400ms | 到期自动恢复 |
| CPU 压力 | `run cpu-stress 60` | lab-web CPU 升高，偶发慢请求 | 到期自动恢复 |
| Pod kill | `run pod-kill` | lab-web Pod 重建，客户端短暂 URLError | Deployment 自愈 |
| Pod failure | `run pod-failure 60` | 容器替换为 pause，持续不可用 | 到期恢复原镜像 |
| DNS 错误 | `run dns-error 60` | lab-client 立即 URLError（解析失败） | 到期恢复 |
| Service selector | `run service-selector` | EndpointSlice 为空，客户端 URLError | `lab recover service-selector` |
| finalizer | `run finalizer` | Pod 删除卡在 deletionTimestamp | `lab recover finalizer` |

## adv：高级 K8s 配置类（lab-adv）

| 场景 | 命令 | 现象 |
|-|-|-|
| Ingress 后端端口错 | `run ingress-backend` | 503 |
| IngressClass 不存在 | `run ingress-class` | Ingress 创建成功但不生效 |
| 正常 TLS Ingress | `run ingress-tls` | 对照组，证书正常 |
| 证书域名不匹配 | `run cert-bad` | ingress-nginx 回退 Fake Certificate |
| 证书过期 | `run cert-expired` | curl 报 `certificate has expired` |
| 删除 TLS Secret | `run cert-missing` | 回退默认证书 |
| 仓库不可达 | `run registry-unreachable` | ImagePullBackOff |
| 镜像 Tag 不存在 | `run image-not-found` | 事件 `not found` |
| digest 写错 | `run image-bad-digest` | 事件 `not found` |
| 仓库 DNS 失败 | `run registry-dns` | `no such host` |
| 私有仓库未授权 | `run registry-auth` | `401 Unauthorized`（需 `LAB_PRIVATE_IMAGE`） |
| 仓库证书错误 | `run registry-tls` | `x509 ... no IP SANs`（需 `LAB_TLS_IP`） |
| 仓库连接超时 | `run registry-timeout` | `connection timed out` |
| 镜像名非法 | `run image-invalid-ref` | `InvalidImageName` |
| imagePullSecrets 缺失 | `run pullsecret-missing` | 401 / ImagePullBackOff |
| 容器 OOM | `run oom-killed` | OOMKilled / exit 137 |
| 启动即退出 | `run crashloop` | CrashLoopBackOff |
| StorageClass 不存在 | `run pvc-pending` | PVC/Pod Pending |
| 超配额 | `run quota-exceeded` | 事件 `exceeded quota` |
| 节点选择器无匹配 | `run unschedulable` | Pending，`didn't match node selector` |
| ConfigMap 缺失 | `run configmap-missing` | ContainerCreating |
| Service targetPort 错 | `run service-port` | 连接拒绝 |
| 就绪探针失败 | `run readiness-fail` | Endpoints 为空 |

恢复：`lab-adv recover <场景|all>`。Ingress/证书类场景会创建
`training-*` 资源，恢复时一并清理。Ingress 场景需要 ingress-nginx；
控制器不在 `ingress-nginx` 命名空间时设置 `INGRESS_NS` / `INGRESS_SVC`。

## ml：机器学习（training-lab，CPU 模拟）

| 场景 | 命令 | 现象 |
|-|-|-|
| 训练 OOM | `run train-oom` | OOMKilled / exit 137 |
| 训练崩溃 | `run train-crash` | 缺失数据集，Job Failed |
| 训练卡住 | `run train-hang` | Running 但日志不再前进、CPU 为 0 |
| checkpoint 损坏 | `run train-ckpt-corrupt` | `JSONDecodeError` |
| 磁盘写满 | `run train-disk-full` | `No space left on device` |
| 权重下载失败 | `run train-download-fail` | Init:Error，DNS 失败 |
| GPU 不可调度 | `run gpu-unschedulable` | Pending，`Insufficient nvidia.com/gpu` |
| 推理未就绪 | `run infer-readiness` | `/healthz` 503、Endpoints 为空 |
| 模型文件缺失 | `run infer-model-missing` | 启动即 CrashLoopBackOff |
| 推理 OOM | `run infer-oom` | CrashLoopBackOff / OOMKilled |
| 推理延迟 | `run infer-latency` | 客户端 `TimeoutError elapsed=1.00s` |
| 版本不匹配 | `run infer-version-mismatch` | `format_version` RuntimeError |

恢复：`ml-lab recover <场景|all>`。CPU 模拟，不需要 GPU；`gpu-unschedulable`
只演示调度失败，不占用真实 GPU。

## node：节点级（SSH 直连或跳板机）

| 场景 | 命令 | 现象 | 恢复 |
|-|-|-|-|
| CPU 高负载 | `run node-cpu 60` | load 升高，top 可见 stress | 60s 自动退出 |
| 内存压力 | `run node-mem 512 60` | available 下降，cgroup 限流 | 60s 自动退出 |
| OOM | `run node-oom 256 30` | `dmesg`/messages 出现 `Killed process` | 30s 自动退出 |
| 磁盘填充 | `run node-disk 1 60` | `df -h` 使用率升高 | 60s 删除文件 |
| 磁盘 IO | `run node-io 60` | `vmstat` 的 `wa` 升高 | 60s 退出并删目录 |
| kubelet 停止 | `run node-kubelet-stop 30 --yes` | 约 40s 后节点 NotReady | 30s 自动 start |
| 节点 hang | `run node-hang 60 --confirm` | kubelet/containerd `STAT=T`，节点假死 | 60s 自动 SIGCONT |
| 节点重启 | `run node-reboot --confirm` | 节点重启，Pod 中断 | 等待 Ready |
| 内核 crash | `run node-crash --confirm` | SSH 断开，节点 Unknown | 带外管理/自动重启 |

其他节点必须加 `--allow-other`。`node-hang` 用 `kill -STOP` 冻结
kubelet/containerd，由 systemd 定时 `kill -CONT`；`recover` 会先 SIGCONT
再清理 `training-*` unit。

## 一条口令示例

```bash
~/k8s-fault-lab/faultlab run net-delay 120
~/k8s-fault-lab/faultlab run image-not-found
~/k8s-fault-lab/faultlab run train-oom
~/k8s-fault-lab/faultlab run node-oom 256 30
~/k8s-fault-lab/faultlab run node-hang 60 --confirm
~/k8s-fault-lab/faultlab recover all
```
