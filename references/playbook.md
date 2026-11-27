# Kubernetes 故障演练排查手册（新人版）

> 一条口令注入，按本手册排查。节点命令中的 `<node>` 替换为实际演练节点；
> SSH 支持 `NODE_SSH_MODE=direct`（本机直连）或 `jump`（跳板机），见 setup.md。
>
> 统一入口：`~/k8s-fault-lab/faultlab list` / `faultlab guide <场景>`。
> 每个场景都带自动恢复或明确的手动恢复命令；先看现象，再看日志，最后恢复。

## 通用黄金 5 分钟

```bash
# 1. 集群/节点总览
kubectl get nodes -o wide
kubectl describe node <node> | sed -n '/Conditions:/,/Addresses:/p'

# 2. 异常 Pod 与事件（按时间倒序）
kubectl get pods -A -o wide | grep -vE 'Running|Completed'
kubectl get events -A --sort-by=.lastTimestamp | tail -30

# 3. 节点上的 Pod
kubectl get pods -A -o wide --field-selector spec.nodeName=<node>

# 4. 资源
kubectl top node
kubectl top pods -n training-lab

# 5. 节点日志（最常用）
ssh root@<node>
tail -200 /var/log/messages
dmesg -T | tail -100
journalctl -u kubelet --since '10 min ago' --no-pager
```

排查顺序：**先判断是节点问题还是 K8s 配置问题**，再进对应章节。
不要一上来就重启/删除；先保存现场（`kubectl describe`、日志、时间点）。

## net-delay

**现象**：`lab-client` 日志的 `elapsed_ms` 从个位数升到数百毫秒，HTTP 仍可能是 200。

**快速确认**：
```bash
kubectl logs deploy/lab-client -n training-lab --tail=20
kubectl get networkchaos -n training-lab
kubectl describe networkchaos smoke-network-delay -n training-lab
```

**根因定位**：NetworkChaos 的 delay/loss 配置；确认 selector 命中的是 lab-client 到 lab-web。

**恢复**：`faultlab recover net-delay`，或等待 duration 到期。

## cpu-stress

**现象**：`kubectl top pod` 中 lab-web CPU 升高，客户端偶发慢请求或 5xx。

**快速确认**：
```bash
kubectl top pod -n training-lab
kubectl get stresschaos -n training-lab
kubectl describe pod -l app=lab-web -n training-lab | grep -A5 'Limits'
```

**根因定位**：StressChaos 的 workers/load 与容器 CPU limit；区分节点 CPU 高和容器限流。

**恢复**：`faultlab recover cpu-stress`，或等待 duration 到期。

## pod-kill

**现象**：lab-web Pod 被删除重建，客户端出现短暂 `URLError`，随后恢复 200。

**快速确认**：
```bash
kubectl get pod -l app=lab-web -n training-lab -w
kubectl get podchaos -n training-lab
kubectl get events -n training-lab --sort-by=.lastTimestamp | tail
```

**根因定位**：确认是 pod-kill 而非 CrashLoop；看 Deployment 副本数与重启次数。

**恢复**：Deployment 自愈；`faultlab recover pod-kill` 清理 Chaos CR。

## pod-failure

**现象**：lab-web 容器被替换为 pause，客户端持续 `URLError`，Pod 仍显示 Running。

**快速确认**：
```bash
kubectl get pod -l app=lab-web -n training-lab
kubectl describe pod -l app=lab-web -n training-lab | grep -A3 'Image:'
kubectl get podchaos -n training-lab
```

**根因定位**：PodChaos action=pod-failure；区分 pause 替换与业务自身崩溃。

**恢复**：`faultlab recover pod-failure`，或等待 duration 到期。

## dns-error

**现象**：lab-client 解析 `lab-web.training-lab.svc.cluster.local` 失败，日志立即 `URLError`。

**快速确认**：
```bash
kubectl logs deploy/lab-client -n training-lab --tail=20
kubectl get dnschaos -n training-lab
kubectl exec deploy/lab-client -n training-lab -- cat /etc/resolv.conf
```

**根因定位**：DNSChaos patterns 是否命中服务域名；区分 CoreDNS 故障与应用解析错误。

**恢复**：`faultlab recover dns-error`，或等待 duration 到期。

## service-selector

**现象**：Service 的 Endpoints/EndpointSlice 为空，客户端连接失败；Pod 本身 Running。

**快速确认**：
```bash
kubectl get svc lab-web -n training-lab -o yaml | grep -A5 selector
kubectl get endpointslice -n training-lab -l kubernetes.io/service-name=lab-web
kubectl get pod -n training-lab --show-labels
```

**根因定位**：Service selector 与 Pod label 不匹配；对照注入前保存的 selector。

**恢复**：`faultlab recover service-selector`。

## finalizer

**现象**：Pod 一直处于 Terminating，`deletionTimestamp` 有值，`finalizers` 非空。

**快速确认**：
```bash
kubectl get pod smoke-finalizer -n training-lab -o yaml | grep -A3 'finalizers\|deletionTimestamp'
kubectl describe pod smoke-finalizer -n training-lab
```

**根因定位**：实验专用 finalizer `training.example.com/manual-cleanup` 未被移除。

**恢复**：`faultlab recover finalizer`（脚本会先 test 再 remove，不强清其他 finalizer）。

## node-cpu

**现象**：节点 load 升高，`kubectl top node` CPU 接近 100%，业务 Pod 延迟升高；
Pod 本身不一定重启。

**快速确认**：
```bash
uptime                       # load average 1/5/15 分钟
top -b -n1 | head -20
vmstat 1 5                   # r 列（运行队列）持续 > CPU 核数
ps -eo pid,ppid,stat,pcpu,pmem,cmd --sort=-pcpu | head -15
kubectl top node
kubectl describe node <node> | grep -A8 'Allocated resources'
```

**根因定位**：
- `ps` 里找到吃 CPU 的进程（演练时是 `stress --cpu`）。
- 看是容器内还是宿主机进程：`crictl ps`、`systemd-cgroup`。
- `/var/log/messages` 一般不会有 OOM，但可能有 kubelet 的 `PLEG is not healthy` 或
  `Node ... status is now: NodeHasSufficientCPU` 之类事件。
- 业务侧看 `kubectl logs` 延迟、`kubectl top` 和节点负载。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-cpu
# 或等 stress 的 timeout 自动退出
```

**新人要点**：load 高不等于 CPU 高；`wa` 高是 IO，`sy` 高看内核/网络，`us` 高看应用。

## node-mem

**现象**：节点可用内存下降，`free -m` 的 available 变小；可能触发 kubelet 驱逐
（`MemoryPressure`），但不一定 OOM。

**快速确认**：
```bash
free -m
cat /proc/meminfo | grep -E 'MemAvailable|MemFree|Swap'
systemd-cgtop -m --iterations=1
ps -eo pid,stat,rss,cmd --sort=-rss | head -15
kubectl describe node <node> | grep -A3 'MemoryPressure'
```

**根因定位**：
- 演练用 `systemd-run -p MemoryMax=... stress --vm`，内存被限制在 cgroup 内。
- 看 `systemd-cgtop` 里 `training-mem-*` 的占用。
- `/var/log/messages` 搜 `oom`；如果只是压力未触发 OOM，可能没有记录。
- `journalctl -u kubelet | grep -i evict` 看是否触发驱逐。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-mem
```

## node-oom

**现象**：进程被内核 OOM Killer 杀掉；`dmesg`/`/var/log/messages` 出现
`Memory cgroup out of memory: Killed process ...`；容器可能 `OOMKilled` 后重启。

**快速确认（节点）**：
```bash
dmesg -T | grep -iE 'oom|killed process|out of memory' | tail -20
grep -iE 'oom|killed process|out of memory' /var/log/messages | tail -20
journalctl -k --since '10 min ago' --no-pager | grep -iE 'oom|killed process'
```

**快速确认（Pod）**：
```bash
kubectl get pod -n training-lab -o wide
kubectl describe pod <pod> -n training-lab | grep -A6 'Last State'
kubectl get pod <pod> -n training-lab -o jsonpath='{.status.containerStatuses[*].lastState.terminated.reason}'
```

**根因定位**：
- 先看是 **cgroup OOM**（容器 memory limit 太小）还是 **节点 OOM**（整机内存不足）。
- cgroup OOM 关键字：`Memory cgroup out of memory: Killed process ... (python3)`，
  对应 Pod 的 `lastState.terminated.reason=OOMKilled`。
- 节点 OOM 关键字：`Out of memory: Killed process ...`，可能杀的是非容器进程。
- 对照 `kubectl describe pod` 的 `Limits.memory` 与进程实际 RSS。
- 容器内看 `/sys/fs/cgroup/memory.events`（v2）或 `memory.oom_control`（v1）。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-oom
# 业务 Pod 由 Deployment 自动重建；确认新 Pod Running 且无反复 OOM
```

**新人要点**：`OOMKilled` 是容器限制问题；节点 `Out of memory` 是整机问题。
两者日志关键字不同，别混。

## node-disk

**现象**：`df -h` 使用率升高；严重时 kubelet 报 `DiskPressure`、镜像/日志写入失败。

**快速确认**：
```bash
df -h /
df -i /
du -sh /tmp/training-* 2>/dev/null
ls -lh /tmp/training-fill-*.img 2>/dev/null
kubectl describe node <node> | grep -A3 'DiskPressure'
```

**根因定位**：
- 演练用 `fallocate` 在 `/tmp` 占位，文件名为 `training-fill-*.img`。
- 真实场景重点看：`/var/lib/containerd`（镜像/容器层）、`/var/log`（日志）、
  `/var/lib/kubelet`（Pod 日志/emptyDir）。
- `du -x -h --max-depth=2 /var/lib/containerd | sort -h | tail`。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-disk
```

## node-io

**现象**：`iostat`/`vmstat` 的 `wa` 很高，应用读写变慢；CPU 可能不高，但请求延迟大。

**快速确认**：
```bash
vmstat 1 5                 # wa 列
iostat -x 1 3              # %util、await
ps -eo pid,stat,cmd | grep -E '[s]tress|training-io'
iotop -o -b -n1 2>/dev/null | head -20
```

**根因定位**：
- 演练用 `stress --hdd` 在 `/tmp/training-io-*` 写文件。
- 真实场景看是容器写日志、数据库刷盘，还是节点上的镜像/日志写入。
- `dmesg -T | grep -iE 'blocked for more than|hung task|I/O error'` 看是否 IO 卡死。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-io
```

## node-kubelet-stop

**现象**：节点约 40 秒后 `NotReady`，`kubectl get pods -o wide` 状态不再更新；
该节点上的业务 Pod 通常不会立即重启（kubelet 停但容器还在跑）。

**快速确认**：
```bash
kubectl get node <node> -o wide
kubectl describe node <node> | grep -A6 'Conditions:'
# 节点上
systemctl status kubelet --no-pager
journalctl -u kubelet --since '10 min ago' --no-pager | tail -50
```

**根因定位**：
- kubelet 停止后，`/var/log/messages` 里可能看到 `kubelet` 退出、PLEG 相关错误。
- 如果 kubelet 反复重启，看 `systemctl status kubelet` 的 exit code 与
  `journalctl -u kubelet` 的证书/CRI 连接错误。
- 区分「kubelet 挂了」和「容器运行时挂了」：`systemctl status containerd`，
  `crictl ps` 是否可用。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-kubelet-stop
# 脚本会自动 systemctl start kubelet；确认节点 Ready
```

## node-hang

**现象**：节点看起来「假死」：SSH 可能还通，但 `kubectl` 对该节点的操作超时，
节点 `NotReady/Unknown`，`kubectl exec/logs` 失败。

**快速确认**：
```bash
kubectl get node <node> -o wide
# 节点上
ps -eo pid,stat,comm | grep -E 'kubelet|containerd'   # STAT 为 T 表示被暂停
uptime
cat /proc/loadavg
dmesg -T | grep -iE 'hung task|blocked for more than' | tail
journalctl -u kubelet --since '10 min ago' --no-pager | tail -30
```

**根因定位**：
- 演练用 `kill -STOP` 冻结 kubelet/containerd，`STAT=T` 就是证据；
  脚本到期会自动 `kill -CONT`。
- 真实 hang 重点看：`dmesg` 的 `task ... blocked for more than 120 seconds`、
  `hung_task`、`Kernel panic`；带外管理看实例状态/串口日志。
- 如果 SSH 也进不去，只能走带外管理 VNC/串口，或重启实例。

**恢复**：
```bash
~/k8s-fault-lab/faultlab recover node-hang
# 会先 SIGCONT kubelet/containerd，再清理 training-* unit
```

**新人要点**：hang 和宕机的区别是「进程还在但不动」。先看 `STAT=T/D`、
`hung task`，不要直接重启，先留现场。

## node-reboot

**现象**：节点重启，`kubectl get node` 短时 `NotReady`，节点上的 Pod 中断后重建；
`uptime` 归零，`last reboot` 有记录。

**快速确认**：
```bash
kubectl get node <node> -o wide
ssh root@<node> 'uptime; last reboot | head -3'
journalctl --list-boots | tail -5
```

**根因定位**：
- 看 `/var/log/messages` 重启前后的日志，区分「正常重启」和「内核 panic 重启」。
- `journalctl -k -b -1 | tail -100` 看上一次启动末尾是否有 panic/OOM。
- 带外管理看实例操作记录（谁重启的）。

**恢复**：等待节点 Ready；业务 Pod 由控制器重建。演练脚本会轮询 Ready。

## node-crash

**现象**：节点内核 crash/宕机，SSH 断开，`kubectl get node` 变为 `Unknown`；
带外管理可能显示实例重启中。

**快速确认**：
```bash
kubectl get node <node> -o wide
# 节点恢复后
journalctl -k -b -1 | grep -iE 'panic|Oops|BUG:' | tail -30
grep -iE 'panic|Oops|BUG:' /var/log/messages | tail -30
last reboot | head -3
```

**根因定位**：
- 演练用 `sysrq-trigger` 主动 crash；真实场景看 panic 调用栈、
  `Kernel panic - not syncing`、硬件 MCE 日志。
- 带外管理看实例状态、重启记录、串口日志。

**恢复**：等待云厂商自动重启/手动启动；确认节点 Ready、系统组件恢复。
演练脚本会轮询 Ready。

## ingress-backend

**现象**：访问 Ingress 返回 `503 Service Unavailable`；Pod 本身 Running，
Service 也有 Endpoints，但端口对不上。

**快速确认**：
```bash
kubectl get ingress -n training-lab
kubectl describe ingress lab-ingress-bad -n training-lab
kubectl get svc lab-web -n training-lab -o yaml | grep -A5 ports
kubectl get endpointslice -n training-lab -l kubernetes.io/service-name=lab-web
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller --tail=100 | grep lab-ingress-bad
# 绕过公网 LB，直接打 ingress-nginx
kubectl port-forward -n kube-system svc/ingress-nginx-controller 18080:80 &
curl -v -H 'Host: lab-bad.training.local' http://127.0.0.1:18080/
```

**根因定位**：
- Ingress `backend.service.port.number` 与 Service `port` 不一致（演练是 9999 vs 80）。
- 看 ingress-nginx 日志：`connect() failed`、`no endpoints available`。
- 区分 503（后端不可达）与 404（Host/Path 不匹配）。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover ingress-backend
```

## ingress-class

**现象**：Ingress 创建成功，但 `ADDRESS` 为空，访问返回 404；Pod/Service 本身正常。
常见于 `ingressClassName` 拼错、集群没有对应 IngressClass 或控制器未监听该类。

**快速确认**：
```bash
kubectl get ingressclass
kubectl get ingress lab-ingress-class -n training-lab -o yaml | grep -A2 ingressClassName
kubectl describe ingress lab-ingress-class -n training-lab
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller --tail=100 | grep -i 'class\|lab-ingress-class'
kubectl port-forward -n kube-system svc/ingress-nginx-controller 18080:80 &
curl -v -H 'Host: lab-class.training.local' http://127.0.0.1:18080/
```

**根因定位**：
- `spec.ingressClassName` 与 `kubectl get ingressclass` 中的名称不一致。
- 没有控制器监听该 IngressClass，或控制器只监听带特定 class 注解的 Ingress。
- 区分「Ingress 没生效」（ADDRESS 空/404）与「后端 503」（有地址但后端不可达）。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover ingress-class
```

## ingress-tls

**现象**：正常 TLS Ingress，用于和证书异常场景做对照；浏览器/curl 校验通过。

**快速确认**：
```bash
kubectl get ingress lab-tls -n training-lab
kubectl get secret lab-tls -n training-lab
kubectl port-forward -n kube-system svc/ingress-nginx-controller 18443:443 &
curl -v --cacert ~/k8s-fault-lab/certs/ca.crt \
  --resolve lab-tls.training.local:18443:127.0.0.1 \
  https://lab-tls.training.local:18443/
```

**新人要点**：先确认「正常路径」能通，再对比异常场景，避免把环境问题当成故障。

## cert-bad

**现象**：HTTPS 握手证书域名不匹配；ingress-nginx 可能拒绝加载并回退到
Fake Certificate，curl 报 `certificate is valid for wrong.example.com, not
lab-tls.training.local`。

**快速确认**：
```bash
kubectl get secret lab-tls -n training-lab -o jsonpath='{.data.tls\.crt}' \
  | base64 -d | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller --tail=100 | grep -i 'lab-tls\|x509'
openssl s_client -connect 127.0.0.1:18443 -servername lab-tls.training.local \
  -CAfile ~/k8s-fault-lab/certs/ca.crt </dev/null 2>&1 | grep -E 'subject=|Verify return code'
```

**根因定位**：
- 证书 SAN/CN 与 Ingress `tls.hosts` 不一致。
- ingress-nginx 日志关键字：`x509: certificate is valid for ...`、`Using default certificate`。
- 注意：证书被拒绝时，实际下发的是 ingress-nginx 的 Fake Certificate。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover cert-bad
```

## cert-expired

**现象**：证书已过期；浏览器告警，curl 报 `certificate has expired`；
ingress-nginx 仍可能正常下发该证书（它不校验证书有效期）。

**快速确认**：
```bash
kubectl get secret lab-tls -n training-lab -o jsonpath='{.data.tls\.crt}' \
  | base64 -d | openssl x509 -noout -subject -dates
curl -v --cacert ~/k8s-fault-lab/certs/ca.crt \
  --resolve lab-tls.training.local:18443:127.0.0.1 \
  https://lab-tls.training.local:18443/ 2>&1 | grep -E 'expired|SSL certificate'
```

**根因定位**：
- `notAfter` 早于当前时间；对比 `date -u`。
- 看证书链：`openssl s_client ... -showcerts`，确认是叶子证书还是中间证书过期。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover cert-expired
```

## cert-missing

**现象**：Ingress 引用的 TLS Secret 不存在；ingress-nginx 回退到默认 Fake Certificate，
curl 报证书不受信任/域名不匹配。

**快速确认**：
```bash
kubectl get ingress lab-tls -n training-lab -o yaml | grep -A3 tls
kubectl get secret -n training-lab
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller --tail=100 | grep -i 'secret\|default certificate'
```

**根因定位**：
- `spec.tls[].secretName` 与 Secret 名称/命名空间不一致。
- Secret 类型应为 `kubernetes.io/tls`，且包含 `tls.crt`/`tls.key`。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover cert-missing
```

## registry-unreachable

**现象**：Pod `ImagePullBackOff`，事件里是 `connection refused` / `failed to resolve`；
节点上 `crictl pull` 也失败。

**快速确认**：
```bash
kubectl describe pod smoke-registry -n training-lab | tail -25
kubectl get events -n training-lab --sort-by=.lastTimestamp | tail -10
# 节点上
crictl images | grep training
curl -v http://127.0.0.1:5000/v2/ 2>&1 | head
journalctl -u containerd --since '10 min ago' --no-pager | tail -30
```

**根因定位**：
- 镜像仓库地址/端口错误、仓库未启动、网络不通、证书不受信。
- 区分 `connection refused`（端口没开）、`no such host`（DNS）、
  `x509`（仓库证书）、`401`（鉴权）。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover registry-unreachable
```

## pullsecret-missing

**现象**：Pod `ImagePullBackOff`，事件明确写
`FailedToRetrieveImagePullSecret` 或 `401 Unauthorized`。

**快速确认**：
```bash
kubectl describe pod smoke-pullsecret -n training-lab | tail -25
kubectl get pod smoke-pullsecret -n training-lab -o jsonpath='{.spec.imagePullSecrets}'
kubectl get secret -n training-lab
# 节点上
crictl pull <镜像地址>
```

**根因定位**：
- `imagePullSecrets` 名称拼错、Secret 不在同命名空间、Secret 类型/内容不对。
- 私有仓库需要 `kubernetes.io/dockerconfigjson`。
- 不要打印 Secret 内容；只看是否存在、类型、命名空间。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover pullsecret-missing
```

镜像拉取失败先按事件关键字分流：`not found` 是镜像/tag/digest 问题，
`401` 是鉴权，`x509` 是证书，`no such host` 是 DNS，`connection timed out` 是网络，
`InvalidImageName` 是镜像名格式。不要一上来就重启节点。

## image-not-found

**现象**：Pod `ErrImagePull` / `ImagePullBackOff`，事件里是
`not found` 或 `manifest unknown`；仓库域名可解析、TLS 和鉴权都正常。

**快速确认**：
```bash
kubectl describe pod smoke-image-404 -n training-lab | tail -25
kubectl get events -n training-lab --sort-by=.lastTimestamp | tail -10
# 节点上直接拉一次
crictl pull python:no-such-tag-xyz
```

**根因定位**：
- Tag 拼错、镜像还没推上来、流水线只推了 digest、仓库路径大小写不一致。
- 用 `crictl images` 确认本机是否有同名镜像；`imagePullPolicy: Always` 会绕过本地缓存。
- 事件是 `not found` 而不是 `401`/`x509`/`no such host`，说明问题在镜像名本身。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover image-not-found
```

## image-bad-digest

**现象**：Pod `ErrImagePull`，事件里镜像引用是
`repo@sha256:0000...`，返回 `not found`。

**快速确认**：
```bash
kubectl describe pod smoke-image-digest -n training-lab | tail -25
kubectl get pod smoke-image-digest -n training-lab -o jsonpath='{.spec.containers[0].image}'
# 节点上
crictl pull <完整镜像引用>
```

**根因定位**：
- digest 抄错/截断，或 manifest 已被删除；digest 是不可变引用，写错不会回退到 tag。
- 对比发布单里的 digest 与仓库页面；用 `crictl inspecti <image>` 看本地镜像 ID。
- 不要把 digest 和 tag 混用；生产发布建议 tag + digest 双校验。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover image-bad-digest
```

## registry-dns

**现象**：`ImagePullBackOff`，事件里是
`dial tcp: lookup registry.training.local ... no such host`。

**快速确认**：
```bash
kubectl describe pod smoke-registry-dns -n training-lab | tail -25
# 节点上
cat /etc/resolv.conf
nslookup registry.training.local
getent hosts registry.training.local
journalctl -u containerd --since '10 min ago' --no-pager | tail -30
```

**根因定位**：
- 仓库域名写错、私有 DNS/内网域名未配置、CoreDNS 异常、上游 DNS 不通。
- 区分「节点 DNS 失败」和「集群内 CoreDNS 失败」：节点上 `nslookup` 能过、
  Pod 内过不了，才是 CoreDNS/NetworkPolicy 问题。
- 仓库域名变更后，老 YAML/Helm values 没同步。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover registry-dns
```

## registry-auth

**现象**：`ImagePullBackOff`，事件里是
`401 Unauthorized` / `failed to authorize` / `failed to fetch anonymous token`。

**快速确认**：
```bash
kubectl describe pod smoke-registry-auth -n training-lab | tail -25
kubectl get pod smoke-registry-auth -n training-lab -o jsonpath='{.spec.imagePullSecrets}'
kubectl get secret -n training-lab
kubectl get secret <secret> -n training-lab -o jsonpath='{.type}'
# 节点上（不带凭证）
crictl pull <私有仓库>/training/private-demo:1.0
```

**根因定位**：
- 仓库是私有的，Pod 没带 `imagePullSecrets`，或 Secret 不在同命名空间、类型不对。
- 仓库账号/命名空间权限不足、临时 token 过期、鉴权策略变更。
- 不要打印 Secret 内容；只看存在性、类型、命名空间和事件里的 401。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover registry-auth
```

## registry-tls

**现象**：`ImagePullBackOff`，事件里是
`x509: cannot validate certificate for <IP> because it doesn't contain any IP SANs`
或 `certificate has expired` / `unknown authority`。

**快速确认**：
```bash
kubectl describe pod smoke-registry-tls -n training-lab | tail -25
# 节点上
openssl s_client -connect <registry>:443 -servername <registry-domain> </dev/null 2>&1 | head -20
curl -vk https://<registry>/v2/ 2>&1 | head -30
```

**根因定位**：
- 用 IP 直接访问仓库，证书只签了域名；或证书过期、自签 CA 未加入节点信任链。
- 镜像地址应使用证书里的域名，不要用 IP；私有仓库要确认 CA 已下发到节点。
- 注意区分 TLS 失败和 401：TLS 失败时请求还没到鉴权阶段。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover registry-tls
```

## registry-timeout

**现象**：`ImagePullBackOff`，事件里是
`dial tcp <IP>:443: connect: connection timed out`；首次失败通常要等 20-30 秒。

**快速确认**：
```bash
kubectl describe pod smoke-registry-timeout -n training-lab | tail -25
# 节点上
time curl -vk --connect-timeout 5 https://10.255.255.1/v2/
timeout 10 crictl pull 10.255.255.1/training/app:1.0
ip route
```

**根因定位**：
- 仓库地址不可路由、防火墙/网络策略未放行、路由/对等连接不通、仓库端口没监听。
- `connection timed out` 是 SYN 无响应；`connection refused` 是端口没开，两者排查方向不同。
- 先 `curl`/`nc` 验证四层连通性，再看仓库进程和证书。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover registry-timeout
```

## image-invalid-ref

**现象**：Pod `InvalidImageName`，事件里是
`couldn't parse image name ... invalid reference format`。

**快速确认**：
```bash
kubectl get pod smoke-image-invalid -n training-lab
kubectl describe pod smoke-image-invalid -n training-lab | tail -20
kubectl get pod smoke-image-invalid -n training-lab -o jsonpath='{.spec.containers[0].image}'
```

**根因定位**：
- 仓库名含大写字母、Tag 含空格/非法字符、镜像名缺字段、变量替换后为空。
- 这类错误不会真的去拉镜像，事件是 `InspectFailed` + `InvalidImageName`。
- 检查 Helm values/CI 变量渲染后的最终 image 字符串。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover image-invalid-ref
```

## oom-killed

**现象**：Pod 反复重启，`kubectl describe pod` 的 `Last State` 为 `OOMKilled`，
`RESTARTS` 增长。

**快速确认**：
```bash
kubectl get pod smoke-oom -n training-lab
kubectl describe pod smoke-oom -n training-lab | grep -A8 'Last State'
kubectl get pod smoke-oom -n training-lab -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'
# 节点上（cgroup OOM 证据）
dmesg -T | grep -iE 'oom|killed process' | tail -10
grep -iE 'oom|killed process' /var/log/messages | tail -10
```

**根因定位**：
- 容器 `limits.memory` 小于进程实际申请量。
- 看 `lastState.terminated.reason=OOMKilled`、`exitCode=137`。
- 节点 cgroup 日志里的进程名应与容器主进程一致。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover oom-killed
```

## crashloop

**现象**：Pod `CrashLoopBackOff`，`RESTARTS` 持续增长，容器启动后很快退出。

**快速确认**：
```bash
kubectl get pod smoke-crashloop -n training-lab
kubectl logs smoke-crashloop -n training-lab --previous
kubectl describe pod smoke-crashloop -n training-lab | grep -A8 'Last State'
kubectl get events -n training-lab --sort-by=.lastTimestamp | tail -15
```

**根因定位**：
- 看退出码：`1` 应用错误、`137` OOM/SIGKILL、`143` SIGTERM、`127` 命令不存在。
- 看 `--previous` 日志的最后几行。
- 配置/依赖/探针都可能导致重启，先看日志再看探针。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover crashloop
```

## pvc-pending

**现象**：PVC `Pending`，Pod 卡在 `ContainerCreating`；事件里
`storageclass.storage.k8s.io "no-such-sc" not found` 或 `waiting for a volume to be created`。

**快速确认**：
```bash
kubectl get pvc -n training-lab
kubectl describe pvc smoke-pvc -n training-lab
kubectl get storageclass
kubectl describe pod smoke-pvc -n training-lab | tail -20
```

**根因定位**：
- StorageClass 名称不存在、未设置 default、Provisioner 异常、容量/可用区不匹配。
- 看 PVC 事件 `ProvisioningFailed` 的具体原因。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover pvc-pending
```

## quota-exceeded

**现象**：Pod 创建失败或 Pending，事件 `exceeded quota: training-lab-quota, requested: ...`。

**快速确认**：
```bash
kubectl get resourcequota -n training-lab
kubectl describe resourcequota training-lab-quota -n training-lab
kubectl describe pod smoke-quota -n training-lab | tail -20
```

**根因定位**：
- `requests.cpu/memory`、`limits.*`、`pods`、`services` 等某一项达到上限。
- 对照 `Used` 与 `Hard`，看是哪一项超了。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover quota-exceeded
```

## unschedulable

**现象**：Pod `Pending`，事件 `0/3 nodes are available: ... node(s) didn't match Pod's node affinity/selector`。

**快速确认**：
```bash
kubectl describe pod smoke-unschedulable -n training-lab | tail -20
kubectl get nodes --show-labels
kubectl describe node <node> | grep -A5 Taints
```

**根因定位**：
- `nodeSelector`/`nodeAffinity`/taints/tolerations 不匹配，或资源不足。
- 看事件里的具体过滤原因（node(s) didn't match / insufficient cpu / taint）。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover unschedulable
```

## configmap-missing

**现象**：Pod 卡在 `ContainerCreating`，事件
`MountVolume.SetUp failed for volume "cfg" : configmap "missing-cm" not found`。

**快速确认**：
```bash
kubectl get configmap -n training-lab
kubectl describe pod smoke-configmap -n training-lab | tail -20
kubectl get events -n training-lab --sort-by=.lastTimestamp | tail -10
```

**根因定位**：
- ConfigMap 名称/命名空间拼错，或尚未创建。
- 区分 volume 挂载失败与 envFrom 失败，事件关键字不同。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover configmap-missing
```

## service-port

**现象**：Service 有 ClusterIP，但访问连接拒绝/超时；Endpoints 可能为空或端口不对。

**快速确认**：
```bash
kubectl get svc lab-web -n training-lab -o yaml | grep -A8 ports
kubectl get endpointslice -n training-lab -l kubernetes.io/service-name=lab-web -o yaml
kubectl describe svc lab-web -n training-lab
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -qO- http://lab-web.training-lab:80/ || true
```

**根因定位**：
- `targetPort` 与容器实际监听端口不一致（演练常见）。
- `selector` 与 Pod 标签不匹配会导致 Endpoints 为空。
- 区分「Endpoints 为空」与「Endpoints 有但端口错」。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover service-port
```

## readiness-fail

**现象**：Pod `Running` 但 `READY 0/1`，Endpoints 为空，Service 访问失败；
事件 `Readiness probe failed: HTTP probe failed with statuscode: 404`。

**快速确认**：
```bash
kubectl get pod -n training-lab -l app=lab-web
kubectl describe pod <pod> -n training-lab | grep -A5 Readiness
kubectl get endpointslice -n training-lab -l kubernetes.io/service-name=lab-web
kubectl logs <pod> -n training-lab --tail=30
```

**根因定位**：
- 探针路径/端口/初始延迟配置错误，或应用确实未就绪。
- 区分 liveness（会重启）与 readiness（只摘流量，不重启）。

**恢复**：
```bash
~/k8s-fault-lab/lab-adv recover readiness-fail
```

机器学习场景全部用 CPU 和节点已缓存的 Python 镜像模拟，不需要 GPU、不拉公网镜像。
先看 Pod 状态（OOMKilled / Error / Pending / CrashLoopBackOff），再看日志最后 30 行。

## train-oom

**现象**：训练 Job `Failed`，Pod 状态 `OOMKilled`，`exitCode=137`；
日志在 `step=20`、`checkpoint saved` 之后出现 `allocated 32MB/64MB/96MB`。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-train-oom -n training-lab
kubectl describe pod -l training.example.com/scenario=ml-train-oom -n training-lab | grep -A8 'Last State\|Reason:       OOMKilled'
kubectl logs -l training.example.com/scenario=ml-train-oom -n training-lab --tail=20
# 节点上
dmesg -T | grep -iE 'oom|killed process' | tail
grep -iE 'oom|killed process' /var/log/messages | tail
```

**根因定位**：
- 容器 `limits.memory` 小于 batch/模型/缓存实际占用；也可能是内存泄漏或 dataloader worker 太多。
- `reason=OOMKilled` 是容器 cgroup OOM；节点 OOM 会在 `dmesg/messages` 看到整节点进程被杀。
- 先降 batch/加 gradient accumulation，再评估加 limit 或换更大规格。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover train-oom
```

## train-crash

**现象**：训练 Job `Failed`，Pod `Error`，日志最后是
`FileNotFoundError: [Errno 2] No such file or directory: '/data/train.csv'`。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-train-crash -n training-lab
kubectl logs -l training.example.com/scenario=ml-train-crash -n training-lab --tail=30
kubectl describe pod -l training.example.com/scenario=ml-train-crash -n training-lab | tail -20
kubectl get job ml-train-crash -n training-lab -o jsonpath='{.status.conditions}'
```

**根因定位**：
- 数据集路径写错、PVC/对象存储没挂上、权限不足、代码异常。
- 看 traceback 最后一行和退出码：`1` 应用错误、`137` OOM/SIGKILL、`143` SIGTERM。
- 先确认 `/data` 里到底有什么：`kubectl exec ... -- ls -l /data`。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover train-crash
```

## train-hang

**现象**：训练 Pod 一直 `Running`，日志停在
`waiting for next batch from dataloader (rank 0)...`，CPU 接近 0，没有新 step。

**快速确认**：
```bash
kubectl logs -l training.example.com/scenario=ml-train-hang -n training-lab --timestamps --tail=20
kubectl top pod -l training.example.com/scenario=ml-train-hang -n training-lab
POD=$(kubectl get pod -l training.example.com/scenario=ml-train-hang -n training-lab -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n training-lab $POD -- ps -o pid,stat,pcpu,etime,cmd -C python3
kubectl exec -n training-lab $POD -- cat /proc/1/wchan
```

**根因定位**：
- dataloader 死锁、NAS/对象存储卡住、NCCL 等通信超时、代码死循环。
- `STAT=D` 是不可中断 IO（存储/网络），`STAT=S` 且 CPU 0 多半在等锁/等数据。
- 不要直接删 Pod；先保存日志、进程栈、挂载和存储侧指标，再决定重启。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover train-hang
```

## train-ckpt-corrupt

**现象**：训练 Job `Failed`，日志最后是
`json.decoder.JSONDecodeError: Expecting ',' delimiter`；
init 容器日志为 `wrote-truncated-checkpoint`。

**快速确认**：
```bash
kubectl logs -l training.example.com/scenario=ml-train-ckpt -n training-lab --tail=30
POD=$(kubectl get pod -l training.example.com/scenario=ml-train-ckpt -n training-lab -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n training-lab $POD -- sh -c 'wc -c /ckpt/model.json; head -c 200 /ckpt/model.json'
kubectl logs -n training-lab -l training.example.com/scenario=ml-train-ckpt -c seed-checkpoint
```

**根因定位**：
- 训练中断时直接覆盖写 checkpoint、磁盘满、上传不完整、版本不兼容。
- 正确做法：写临时文件 + `fsync` + 原子 `rename`，并记录 step/sha256/格式版本。
- 恢复训练前先校验 checkpoint 可解析，再决定从哪个 step 续跑。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover train-ckpt-corrupt
```

## train-disk-full

**现象**：训练 Pod `Error`，日志最后是
`OSError: [Errno 28] No space left on device`；
checkpoint 目录是一个 64Mi 的 tmpfs，写到第 9 个 8MB 分片时失败。

**快速确认**：
```bash
kubectl get pod ml-train-disk -n training-lab
kubectl logs ml-train-disk -n training-lab --tail=30
kubectl describe pod ml-train-disk -n training-lab | tail -25
kubectl get pod ml-train-disk -n training-lab -o jsonpath='{.status.containerStatuses[*].state.terminated}'
```

**根因定位**：
- checkpoint 保留策略没清理、日志/临时文件写本地盘、`emptyDir.sizeLimit` 太小。
- 生产上更常见的是 PVC/本地盘写满；容器日志可能被驱逐后取不到，优先看事件和 `describe`。
- 训练任务应把 checkpoint 写 PVC/对象存储，并设置保留数量和容量告警。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover train-disk-full
```

## train-download-fail

**现象**：Pod `Init:Error`，下载容器日志最后是
`urllib.error.URLError: <urlopen error [Errno -2] Name or service not known>`。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-train-download -n training-lab
kubectl logs -l training.example.com/scenario=ml-train-download -n training-lab -c download-model --tail=30
kubectl describe pod -l training.example.com/scenario=ml-train-download -n training-lab | tail -25
```

**根因定位**：
- 模型/数据集下载域名解析失败、对象存储 endpoint 写错、内网端点不通。
- 代理/网络策略、临时凭证过期、bucket 权限不足（403）。
- 先分清 DNS、四层连通性、TLS、鉴权四层，再改 initContainer。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover train-download-fail
```

## gpu-unschedulable

**现象**：Pod 一直 `Pending`，事件为
`0/N nodes are available: ... Insufficient nvidia.com/gpu, ... untolerated taint`。

**快速确认**：
```bash
kubectl describe pod ml-gpu-pending -n training-lab | tail -20
kubectl get nodes -o custom-columns='NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu,TAINTS:.spec.taints'
kubectl get ds -n kube-system | grep -iE 'nvidia|gpu|device'
kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
```

**根因定位**：
- 节点池没有 GPU 机型、GPU 设备插件未就绪、虚拟节点有污点需要 toleration。
- `requests` 和 `limits` 都要写 `nvidia.com/gpu`，且不能只写 requests。
- 还要看 GPU 型号/显存标签、节点池伸缩状态和配额。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover gpu-unschedulable
```

## infer-readiness

**现象**：推理 Deployment `0/1`，Pod `Running` 但 `Ready=False`，
Endpoints 为空；容器内 `/healthz` 返回 `503 model_not_loaded`。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-infer-readiness -n training-lab
kubectl describe pod -l training.example.com/scenario=ml-infer-readiness -n training-lab | grep -A6 -i readiness
POD=$(kubectl get pod -l training.example.com/scenario=ml-infer-readiness -n training-lab -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n training-lab $POD -- python3 -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/healthz').read())"
kubectl get endpoints ml-infer-readiness -n training-lab
```

**根因定位**：
- 模型没挂载/路径不对、模型加载失败、依赖服务不可用、探针初始延迟太短。
- readiness 失败只摘流量不重启；liveness 失败才会重启，先分清探针类型。
- 大模型冷启动慢时，用 `startupProbe` 保护，不要一味加大 readiness 重试。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover infer-readiness
```

## infer-model-missing

**现象**：推理 Pod `CrashLoopBackOff`，日志最后是
`FileNotFoundError: model file not found: /models/model.json`。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-infer-missing -n training-lab
kubectl logs -l training.example.com/scenario=ml-infer-missing -n training-lab --previous --tail=30
kubectl describe pod -l training.example.com/scenario=ml-infer-missing -n training-lab | grep -A8 'Last State'
```

**根因定位**：
- 模型制品没打进镜像、PVC/对象存储没挂载、initContainer 下载失败、路径拼写错误。
- 区分「模型文件缺失」和「模型加载失败」：前者 `FileNotFoundError`，后者常见格式/版本/显存错误。
- 检查 Deployment 的 volumeMounts 与 initContainer 是否都成功。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover infer-model-missing
```

## infer-oom

**现象**：推理 Pod `CrashLoopBackOff`，`Last State` 为 `OOMKilled`，
`exitCode=137`，日志在 `allocating 256MB for model weights` 后中断。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-infer-oom -n training-lab
kubectl describe pod -l training.example.com/scenario=ml-infer-oom -n training-lab | grep -A8 'Last State'
kubectl logs -l training.example.com/scenario=ml-infer-oom -n training-lab --previous --tail=20
kubectl top pod -l training.example.com/scenario=ml-infer-oom -n training-lab
```

**根因定位**：
- 模型权重/激活值超出 limit、batch 太大、并发太高、未量化/未分片。
- 容器 OOM 看 `reason=OOMKilled`；节点 OOM 还要看 `dmesg/messages`。
- 先降 batch/并发，再考虑量化、分片、换大显存规格。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover infer-oom
```

## infer-latency

**现象**：推理服务 `1/1 Running`，但客户端 `TimeoutError`，
`elapsed≈1.00s`；服务端日志显示 `/predict` 请求耗时 3s。

**快速确认**：
```bash
kubectl logs -l training.example.com/scenario=ml-infer-latency -n training-lab --tail=30
kubectl top pod -l training.example.com/scenario=ml-infer-latency -n training-lab
kubectl describe pod -l training.example.com/scenario=ml-infer-latency -n training-lab | grep -A5 -i limits
# 从 lab-client 手动测
kubectl exec deploy/lab-client -n training-lab -- python3 -c "import time,urllib.request;t=time.time();print(urllib.request.urlopen(urllib.request.Request('http://ml-infer-latency/predict',data=b'{}',method='POST'),timeout=5).status, time.time()-t)"
```

**根因定位**：
- 单请求耗时高（模型大/batch 大）、CPU 被 limit 节流、并发排队、冷启动、下游依赖慢。
- 看 `container_cpu_cfs_throttled_seconds_total`、P99、队列长度，再决定扩容/HPA。
- 客户端超时值要大于服务端 P99，否则会把正常慢请求误判为故障。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover infer-latency
```

## infer-version-mismatch

**现象**：推理 Pod `CrashLoopBackOff`，日志最后是
`RuntimeError: unsupported model format_version=1, expected 2`。

**快速确认**：
```bash
kubectl get pod -l training.example.com/scenario=ml-infer-version -n training-lab
kubectl logs -l training.example.com/scenario=ml-infer-version -n training-lab --previous --tail=30
kubectl describe pod -l training.example.com/scenario=ml-infer-version -n training-lab | grep -A8 'Last State'
```

**根因定位**：
- 模型与推理镜像版本不匹配、导出格式变更、特征预处理版本不一致。
- 模型制品应带 `format_version`/commit，推理服务启动时校验并拒绝不兼容版本。
- 发布时用 canary/灰度先验证模型加载，再全量。

**恢复**：
```bash
~/k8s-fault-lab/ml-lab recover infer-version-mismatch
```

## 日志速查表

| 目标 | 命令 |
|-|-|
| 节点内核 OOM | `dmesg -T \| grep -iE 'oom\|killed process'` |
| 节点内核 OOM（持久） | `grep -iE 'oom\|killed process' /var/log/messages` |
| 内核 hung task | `dmesg -T \| grep -iE 'hung task\|blocked for more than'` |
| 内核 panic | `journalctl -k -b -1 \| grep -iE 'panic\|Oops\|BUG:'` |
| kubelet | `journalctl -u kubelet --since '10 min ago' --no-pager` |
| containerd | `journalctl -u containerd --since '10 min ago' --no-pager` |
| 节点启动记录 | `last reboot \| head; journalctl --list-boots` |
| Pod 事件 | `kubectl describe pod <pod> -n training-lab` |
| 集群事件 | `kubectl get events -A --sort-by=.lastTimestamp \| tail -30` |
| Ingress 控制器 | `kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller --tail=100` |
| 证书 | `openssl x509 -in cert.crt -noout -subject -issuer -dates -ext subjectAltName` |
| TLS 握手 | `openssl s_client -connect host:443 -servername host -CAfile ca.crt` |
| 容器运行时 | `crictl ps; crictl images; crictl pull <image>` |
| 镜像拉取失败 | `kubectl describe pod <pod> \| grep -A3 'Failed to pull'`；`crictl pull <image>` |
| ML 训练失败 | `kubectl logs <pod> --previous --tail=50`；看 `OOMKilled/JSONDecodeError/No space left` |
| ML 推理未就绪 | `kubectl exec <pod> -- curl -s localhost:8080/healthz`；`kubectl get endpoints` |
| 节点资源 | `free -m; df -h; vmstat 1 5; iostat -x 1 3` |

## 恢复与安全

```bash
# 本地各层一次性恢复（Chaos / 高级 K8s / ML / 节点）
~/k8s-fault-lab/faultlab recover all

# 单场景恢复
~/k8s-fault-lab/faultlab recover node-hang
~/k8s-fault-lab/faultlab recover train-oom
~/k8s-fault-lab/lab-adv recover cert-bad

```

- 不删除命名空间、不 `delete --all`、不强清 finalizer。
- 不读取/打印 kubeconfig Token、Secret 内容。
- 节点级故障默认只动 `<node>`；其他节点需 `--allow-other`，且可能承载业务。
- 注入前先 `faultlab status`，确认没有未恢复的旧实验。
