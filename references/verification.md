# 验证与验收

## 原则

一次合格的演练必须有三段证据：

1. **注入前基线**：`lab-client` 持续 `http=200`，目标资源 Ready。
2. **故障现象**：事件、日志、指标或客户端错误能直接对应到注入动作。
3. **恢复后基线**：故障消失，`http=200` 连续恢复，无残留资源。

只看 `kubectl apply` 成功不算验证；只看 Pod 状态也不算，必须找到故障语义
（`OOMKilled`、`401`、`x509`、`no such host`、`Killed process` 等）。

## 分层取证命令

### k8s / adv / ml

```bash
kubectl -n training-lab get pod,svc,endpoints -o wide
kubectl -n training-lab get events --sort-by=.lastTimestamp | tail -30
kubectl -n training-lab describe pod <pod>
kubectl -n training-lab logs <pod> --previous --tail=50
kubectl -n training-lab get chaos -A 2>/dev/null || true
```

| 现象 | 关键证据 |
|-|-|
| 网络延迟 | `lab-client` 日志 `elapsed_ms` 从个位数升到约 400 |
| CPU 压力 | `kubectl top pod` CPU 升高；客户端偶发慢请求 |
| Pod kill | Pod AGE 重置、RESTARTS 变化、客户端短时 URLError |
| Pod failure | 容器镜像被替换为 pause，客户端连续 URLError |
| DNS | 客户端 `URLError`，`getent hosts` 失败 |
| OOM | `Last State: Terminated, Reason: OOMKilled, Exit Code: 137` |
| CrashLoop | `Back-off restarting failed container` |
| 镜像 404 | 事件 `Failed to pull image ... not found` |
| 镜像 401 | 事件 `401 Unauthorized` |
| 仓库 DNS | 事件 `no such host` |
| 仓库 TLS | 事件 `x509: cannot validate certificate ... no IP SANs` |
| 仓库超时 | 事件 `connection timed out` |
| 非法镜像名 | 事件 `InvalidImageName` |
| Ingress 503 | `curl` 返回 503，ingress-nginx 日志 upstream 错误 |
| 证书错误 | `curl -vk` 显示 `certificate has expired` 或域名不匹配 |
| 探针失败 | `Readiness probe failed`，Endpoints 为空 |

### node

```bash
# 按 NODE_SSH_MODE 配置的直连或跳板机方式登录 <node>
ssh <user>@<node>
```

| 场景 | 命令与关键字 |
|-|-|
| CPU / 内存 | `uptime`、`top`、`free -m`、`systemd-cgtop` |
| OOM | `dmesg -T \| grep -iE 'oom\|killed process'`；`grep -iE 'oom\|killed process' /var/log/messages` |
| 磁盘 | `df -h`、`du -sh /tmp/training-*` |
| IO | `vmstat 1`、`iostat -x 1`，看 `wa` / `%util` |
| kubelet 停止 | `systemctl status kubelet`；`kubectl get node <node>` 变 NotReady |
| 节点 hang | `ps -eo pid,stat,comm \| grep -E 'kubelet\|containerd'` 出现 `T`；`dmesg -T \| grep -iE 'hung task\|blocked for more than'` |
| 重启/宕机 | SSH 断开、`kubectl get node` 变 Unknown |

## 参考验收记录

以下结果来自参考环境（单节点、containerd、Chaos Mesh 2.8.8），新集群应按同样
方法自测，不要直接当作本集群结论。

| 场景 | 注入现象 | 恢复 |
|-|-|-|
| net-delay 60s | 延迟从 2ms 升到约 400ms | 到期恢复 |
| cpu-stress 30s | lab-web CPU 明显升高 | 到期恢复 |
| pod-kill | lab-web 重建，客户端短时 URLError | Deployment 自愈 |
| pod-failure 60s | 容器替换为 pause，客户端连续 URLError | 到期恢复 |
| dns-error 30s | 客户端立即 URLError | 到期恢复 |
| service-selector | EndpointSlice 为空 | `lab recover` |
| finalizer | Pod 卡 deletionTimestamp | `lab recover` |
| 23 个 adv 场景 | 全部注入并验证（含 7 个镜像仓库场景） | `lab-adv recover all` |
| node io 10s | `training-io-*` 生成，stress 退出 | 自动清理 |
| node hang 20s | kubelet/containerd `STAT=T` | 20s 后 SIGCONT，节点 Ready |
| 12 个 ML 场景 | 训练 OOM/崩溃/卡住/坏 checkpoint/磁盘满/下载失败/GPU Pending；推理缺失/未就绪/OOM/延迟/版本不匹配 | `ml-lab recover all` |

## 已知坑

1. **`train-disk-full` 用内存 emptyDir**：`medium: Memory, sizeLimit: 64Mi`，
   写第 9 个 8MB 分片时稳定报 `No space left on device`。磁盘型 emptyDir 曾导致
   Pod 驱逐不稳定，不要改回。
2. **`infer-readiness` 健康检查用 heredoc**：`kubectl exec -i ... -- python3 - <<'PY'`。
   用 `python3 -c` 加字面 `\n` 会 SyntaxError。
3. **镜像仓库错误要分清**：`not found`（404）、`401`、`x509`、`no such host`、
   `connection timed out`、`InvalidImageName` 是不同根因，排查路径不同。
4. **ML 场景是 CPU 模拟**：没有真实 GPU，不能声称可做 CUDA OOM、NCCL 超时、
   GPU 掉卡；`gpu-unschedulable` 只演示调度 Pending。
5. **镜像必须可达**：默认 `python:3.10-slim`；集群不能访问 docker.io 时用
   `LAB_IMAGE` 指向内部仓库。
6. **Service IP 可能变化**：`lab-web` ClusterIP 以实际 `get svc` 为准，不要写死。
7. **guardian 只回收 Chaos CR**：配置类、节点级必须显式 `recover`。
8. **节点重启/宕机**：必须确认有带外管理或自动重启兜底，并先说明影响面。
9. **恢复后检查残留**：Chaos CR、`training-*` systemd unit、`/tmp/training-*`、
   `training-*` Ingress/Secret/ConfigMap 都应清空。

## 新场景验收清单

- [ ] 注入前 `faultlab status` 干净，基线 `http=200`
- [ ] 注入命令成功，且目标资源确实发生变化
- [ ] 找到至少一条故障语义证据（事件/日志/指标/客户端错误）
- [ ] `recover` 后故障消失
- [ ] 基线连续 `http=200`
- [ ] 无 Chaos CR、`training-*` unit、临时文件残留
- [ ] `PLAYBOOK.md` 有同名 `## <场景>` 章节
- [ ] `faultlab list` 与 `fault-catalog.md` 已收录
