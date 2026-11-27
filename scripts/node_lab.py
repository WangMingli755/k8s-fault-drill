#!/usr/bin/env python3
"""节点级故障注入工具：支持跳板机或本机直连两种 SSH 模式。

模式选择（NODE_SSH_MODE）：
  - direct：本机 -> 目标节点（无跳板机时使用，默认）
  - jump  ：本机 -> 跳板机 -> 目标节点（需配置 JUMP_HOST）
未显式设置时：配置了 JUMP_HOST 走 jump，否则走 direct。

必须用 --node 或 TRAIN_NODE 指定目标节点；操作非 TRAIN_NODE 节点需 --allow-other。
危险动作（kubelet 停止、重启、crash）必须加对应确认参数。
"""
import argparse
import base64
import os
import subprocess
import sys
import time

SSH_MODE = os.environ.get("NODE_SSH_MODE", "").strip().lower()
JUMP = os.environ.get("JUMP_HOST", "").strip()
JUMP_PORT = os.environ.get("JUMP_PORT", "22")
JUMP_USER = os.environ.get("JUMP_USER", "root")
JUMP_KEY = os.path.expanduser(os.environ.get("JUMP_KEY", "~/.ssh/id_rsa"))
TRAIN_NODE = os.environ.get("TRAIN_NODE", "").strip()
NODE_USER = os.environ.get("NODE_SSH_USER", "root")
NODE_PORT = os.environ.get("NODE_SSH_PORT", "22")
NODE_KEY = os.path.expanduser(
    os.environ.get("NODE_SSH_KEY", os.environ.get("JUMP_KEY", "~/.ssh/id_rsa"))
)


def log(msg: str) -> None:
    print(msg, flush=True)


def ssh_mode() -> str:
    if SSH_MODE in ("jump", "direct"):
        return SSH_MODE
    return "jump" if JUMP else "direct"


def ssh_node(node: str, script: str, timeout: int | None = 120, check: bool = True) -> subprocess.CompletedProcess:
    """执行远端脚本；base64 传输，避免多层引号问题。"""
    b64 = base64.b64encode(script.encode()).decode()
    remote = f"echo {b64} | base64 -d | bash"
    common = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
    if ssh_mode() == "jump":
        if not JUMP:
            raise SystemExit("NODE_SSH_MODE=jump 但未配置 JUMP_HOST")
        hop = (
            f"ssh -p {NODE_PORT} -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=8 "
            f"{NODE_USER}@{node} '{remote}'"
        )
        cmd = ["ssh", "-i", JUMP_KEY, "-p", JUMP_PORT, *common, f"{JUMP_USER}@{JUMP}", hop]
    else:
        cmd = ["ssh", "-i", NODE_KEY, "-p", NODE_PORT, *common, f"{NODE_USER}@{node}", remote]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)
    except subprocess.CalledProcessError as e:
        return subprocess.CompletedProcess(e.cmd, e.returncode, e.stdout or "", e.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return subprocess.CompletedProcess(cmd, 124, out, f"SSH 超时（{timeout}s）")
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 255, "", f"SSH 失败: {e}")


def print_result(r: subprocess.CompletedProcess) -> None:
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)


def ensure_node(args) -> str:
    node = args.node or TRAIN_NODE
    if not node:
        log("未指定目标节点：请加 --node <ip>，或 export TRAIN_NODE=<ip>。")
        sys.exit(2)
    if TRAIN_NODE and node != TRAIN_NODE and not getattr(args, "allow_other", False):
        log(f"拒绝操作非演练节点 {node}。如确认要操作，请加 --allow-other。")
        sys.exit(2)
    if TRAIN_NODE and node != TRAIN_NODE:
        log(f"⚠️  目标不是默认演练节点：{node}，可能承载业务，请确认影响面。")
    return node


def kubectl_cmd(*args: str) -> list[str]:
    cmd = [os.environ.get("KUBECTL_BIN", "kubectl")]
    if os.environ.get("ADMIN_KUBECONFIG"):
        cmd += ["--kubeconfig", os.environ["ADMIN_KUBECONFIG"]]
    if os.environ.get("ADMIN_CONTEXT"):
        cmd += ["--context", os.environ["ADMIN_CONTEXT"]]
    return cmd + list(args)


def kubectl_node_status(node: str) -> None:
    try:
        r = subprocess.run(
            kubectl_cmd("get", "node", node, "-o",
                        "jsonpath={.status.conditions[*].type}={.status.conditions[*].status}{\"\\n\"}"),
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            print(f"kubectl node conditions: {r.stdout.strip()}")
        r2 = subprocess.run(
            kubectl_cmd("get", "pods", "-A", "--field-selector", f"spec.nodeName={node}",
                        "--no-headers"),
            capture_output=True, text=True, timeout=20,
        )
        if r2.returncode == 0:
            print(f"该节点 Pod 数: {len(r2.stdout.splitlines())}")
    except Exception as e:
        print(f"kubectl 查询失败: {e}")


def cmd_status(args) -> None:
    node = ensure_node(args)
    log(f"SSH 模式: {ssh_mode()}；目标节点: {node}")
    script = r"""
echo "== host =="
hostname
uptime
echo "== memory =="
free -m | head -2
echo "== disk =="
df -h / | tail -1
echo "== kubelet =="
systemctl is-active kubelet
echo "== load / iowait =="
uptime
vmstat 1 2 2>/dev/null | tail -1
echo "== 被暂停(T)的进程 =="
ps -eo pid,stat,comm | awk '$2 ~ /^T/ {print}' | head -10 || true
echo "== stress/临时文件 =="
ps -eo pid,etimes,cmd | grep -E '/usr/bin/stress|training-(io|cpu|mem|oom|fill|kubelet|hang)' | grep -v grep || true
ls -lh /tmp/training-* 2>/dev/null || true
echo "== systemd 临时单元 =="
systemctl list-units --plain --no-legend 'training-*' 2>/dev/null || true
echo "== messages 最近告警 =="
grep -iE 'oom|killed process|out of memory' /var/log/messages 2>/dev/null | tail -5 || true
"""
    print_result(ssh_node(node, script))
    kubectl_node_status(node)


def cmd_cpu(args) -> None:
    node = ensure_node(args)
    dur, workers = max(1, min(args.seconds, 900)), max(1, min(args.workers, 16))
    script = f"""
TS=$(date +%s)
LOG=/tmp/training-cpu-$TS.log
setsid /usr/bin/timeout {dur} /usr/bin/stress --cpu {workers} >$LOG 2>&1 < /dev/null &
echo "已启动 CPU 压力: {workers} workers, {dur}s, 日志 $LOG"
echo "观察: ssh 到节点后执行 top / uptime；或 kubectl top node"
"""
    print_result(ssh_node(node, script))
    log(f"自动恢复: {dur}s 后 stress 自行退出；提前恢复: node-lab recover")


def cmd_mem(args) -> None:
    node = ensure_node(args)
    mb = max(64, min(args.mb, 8192))
    dur = max(5, min(args.seconds, 900))
    limit = mb * 2  # 留出余量，制造内存压力但不一定 OOM
    ts = int(time.time())
    unit = f"training-mem-{ts}"
    script = f"""
systemd-run --unit={unit} -p MemoryMax={limit}M -p MemorySwapMax=0 \
  /bin/bash -c '/usr/bin/timeout {dur} /usr/bin/stress --vm 1 --vm-bytes {mb}M --vm-keep || true' 
echo "已启动内存压力: {mb}MB, cgroup 上限 {limit}MB, {dur}s, unit={unit}"
echo "观察: free -m; systemd-cgtop; journalctl -k | grep -i oom"
"""
    print_result(ssh_node(node, script))
    log(f"自动恢复: {dur}s 后退出；提前恢复: node-lab recover（会 stop {unit}）")


def cmd_oom(args) -> None:
    node = ensure_node(args)
    mb = max(64, min(args.mb, 4096))
    dur = max(5, min(args.seconds, 300))
    ts = int(time.time())
    unit = f"training-oom-{ts}"
    script = f"""
systemd-run --unit={unit} -p MemoryMax={mb}M -p MemorySwapMax=0 \
  /bin/bash -c '/usr/bin/timeout {dur} /usr/bin/stress --vm 1 --vm-bytes {mb * 2}M --vm-keep || true' 
echo "已启动 OOM 演示: 申请 {mb * 2}MB, cgroup 上限 {mb}MB, unit={unit}"
echo "预计 stress 进程被 OOM Kill；观察:"
echo "  dmesg -T | grep -i -E 'oom|killed process'"
echo "  grep -i -E 'oom|killed process' /var/log/messages | tail"
"""
    print_result(ssh_node(node, script))
    log(f"自动恢复: {dur}s 后退出；提前恢复: node-lab recover")


def cmd_disk(args) -> None:
    node = ensure_node(args)
    gb = max(1, min(args.gb, 10))
    dur = max(5, min(args.seconds, 900))
    ts = int(time.time())
    script = f"""
AVAIL=$(df --output=avail -BG /tmp | tail -1 | tr -dc '0-9')
if [ "$AVAIL" -lt $(( {gb} + 5 )) ]; then
  echo "拒绝：/tmp 可用 ${{AVAIL}}G，低于 {gb}G+5G 安全线"; exit 1
fi
F=/tmp/training-fill-{ts}.img
fallocate -l {gb}G "$F"
setsid bash -c "sleep {dur}; rm -f $F" >/dev/null 2>&1 < /dev/null &
echo "已占用 {gb}G: $F, {dur}s 后自动删除"
echo "观察: df -h /tmp; du -sh /tmp/training-fill-*.img"
"""
    r = ssh_node(node, script, check=False)
    print_result(r)
    if r.returncode != 0:
        sys.exit(r.returncode)


def cmd_kubelet_stop(args) -> None:
    node = ensure_node(args)
    if not args.yes:
        log("拒绝：停止 kubelet 会让节点 NotReady，可能影响该节点上的 coredns/kube-system 组件。")
        log("确认执行请加 --yes，并建议先和业务方约定窗口。")
        sys.exit(2)
    dur = max(5, min(args.seconds, 300))
    ts = int(time.time())
    script = f"""
LOG=/tmp/training-kubelet-{ts}.log
setsid bash -c 'systemctl stop kubelet; sleep {dur}; systemctl start kubelet; echo recovered $(date -Is)' >$LOG 2>&1 < /dev/null &
echo "kubelet 将在 1 秒内停止，{dur}s 后自动启动；日志 $LOG"
echo "观察: kubectl get node（NotReady）; kubectl get pods -A -o wide | grep {node}"
"""
    print_result(ssh_node(node, script))
    log(f"自动恢复: {dur}s 后 kubelet 自动 start；提前恢复: node-lab recover")


def cmd_reboot(args) -> None:
    node = ensure_node(args)
    if not args.confirm:
        log("拒绝：重启节点会驱逐/中断该节点所有 Pod。确认请加 --confirm。")
        sys.exit(2)
    print_result(ssh_node(node, "setsid bash -c 'sleep 1; systemctl reboot' >/dev/null 2>&1 < /dev/null & echo rebooting", check=False))
    log("已下发重启。等待节点 Ready ...")
    for _ in range(60):
        time.sleep(10)
        r = subprocess.run(
            kubectl_cmd("get", "node", node, "-o", "jsonpath={.status.conditions[?(@.type==\"Ready\")].status}"),
            capture_output=True, text=True, timeout=20,
        )
        if r.stdout.strip() == "True":
            log(f"节点 {node} 已 Ready")
            return
    log("等待超时，请手动检查节点状态")


def cmd_crash(args) -> None:
    node = ensure_node(args)
    if not args.confirm:
        log("拒绝：crash 会触发内核 panic/重启，节点上所有 Pod 中断，且可能影响该节点上的 kube-system 组件。")
        log("确认请加 --confirm，并确保有带外管理或自动重启兜底。")
        sys.exit(2)
    script = r"""
echo 1 > /proc/sys/kernel/sysrq
echo c > /proc/sysrq-trigger
"""
    r = ssh_node(node, script, timeout=15, check=False)
    print_result(r)
    log("已触发 crash（连接中断属预期）。等待节点恢复 ...")
    for _ in range(60):
        time.sleep(10)
        r = subprocess.run(
            kubectl_cmd("get", "node", node, "-o", "jsonpath={.status.conditions[?(@.type==\"Ready\")].status}"),
            capture_output=True, text=True, timeout=20,
        )
        if r.stdout.strip() == "True":
            log(f"节点 {node} 已 Ready")
            return
    log("等待超时，请通过带外管理检查实例状态")


def cmd_io(args) -> None:
    node = ensure_node(args)
    dur, workers = max(5, min(args.seconds, 900)), max(1, min(args.workers, 8))
    ts = int(time.time())
    script = f"""
D=/tmp/training-io-{ts}
mkdir -p "$D"
setsid bash -c 'cd /tmp/training-io-{ts}; /usr/bin/timeout {dur} /usr/bin/stress --hdd {workers} --hdd-bytes 128M; cd /; rm -rf /tmp/training-io-{ts}' \
  >"$D/stress.log" 2>&1 < /dev/null &
echo "已启动磁盘 IO 压力: {workers} workers, 128M/次, {dur}s, 目录 $D"
echo "观察: ssh 到节点后 iostat -x 1 / vmstat 1（wa 升高）；kubectl top node"
echo "日志: $D/stress.log（结束后目录自动删除）"
"""
    print_result(ssh_node(node, script))
    log(f"自动恢复: {dur}s 后 stress 退出并删除临时目录；提前恢复: node-lab recover")


def cmd_hang(args) -> None:
    node = ensure_node(args)
    if not args.confirm:
        log("拒绝：冻结 kubelet/containerd 会让节点在约 40s 后 NotReady/Unknown，")
        log("      该节点上的 Pod 状态不再更新，kubectl exec/logs 可能失败。")
        log("确认执行请加 --confirm；脚本会自带定时 SIGCONT 自动恢复。")
        sys.exit(2)
    dur = max(15, min(args.seconds, 300))
    ts = int(time.time())
    unit = f"training-hang-{ts}"
    script = f"""
KB=$(pidof kubelet); CT=$(pidof containerd)
if [ -z "$KB" ] || [ -z "$CT" ]; then echo "找不到 kubelet/containerd 进程，拒绝执行"; exit 1; fi
systemd-run --unit={unit} /bin/bash -c "sleep {dur}; kill -CONT $KB $CT 2>/dev/null || true" \
  || {{ echo "定时恢复单元创建失败，拒绝冻结"; exit 1; }}
kill -STOP $KB $CT
echo "已冻结 kubelet($KB) 与 containerd($CT)，{dur}s 后自动 SIGCONT"
echo "观察: kubectl get node（约 40s 后 NotReady/Unknown）"
echo "      节点上: ps -eo pid,stat,comm | grep -E 'kubelet|containerd'（STAT 应为 T）"
echo "提前恢复: node-lab recover（会先 SIGCONT 再清理 unit）"
"""
    print_result(ssh_node(node, script))
    log(f"自动恢复: {dur}s 后 SIGCONT；若节点失联，可从跳板机/带外控制台 ssh 进去执行 node-lab recover")


def cmd_recover(args) -> None:
    node = ensure_node(args)
    script = r"""
pkill -CONT -x kubelet 2>/dev/null || true
pkill -CONT -x containerd 2>/dev/null || true
pkill -f '/usr/bin/stress' 2>/dev/null || true
for u in $(systemctl list-units --plain --no-legend 'training-*' 2>/dev/null | awk '{print $1}'); do
  systemctl stop "$u" 2>/dev/null || true
done
systemctl reset-failed 'training-*' 2>/dev/null || true
rm -rf /tmp/training-* 2>/dev/null || true
systemctl start kubelet 2>/dev/null || true
echo "已 SIGCONT kubelet/containerd、清理 stress / 临时 unit / IO 与填充文件，并确保 kubelet 为 active:"
systemctl is-active kubelet
ps -eo pid,stat,comm | awk '$2 ~ /^T/ {print}' | head -5 || true
ps -eo pid,cmd | grep -E '[s]tress' || echo "无 stress 进程"
ls -lh /tmp/training-* 2>/dev/null || echo "无训练临时文件"
"""
    print_result(ssh_node(node, script))
    kubectl_node_status(node)


def cmd_logs(args) -> None:
    node = ensure_node(args)
    script = r"""
echo "== dmesg OOM/异常 =="
dmesg -T 2>/dev/null | grep -iE 'oom|killed process|out of memory|panic|hung task' | tail -30 || true
echo "== /var/log/messages =="
grep -iE 'oom|killed process|kubelet|error|fail' /var/log/messages 2>/dev/null | tail -30 || true
echo "== kubelet journal =="
journalctl -u kubelet -n 30 --no-pager 2>/dev/null | tail -30 || true
"""
    print_result(ssh_node(node, script, timeout=60))


def main() -> None:
    p = argparse.ArgumentParser(description="节点级故障注入（跳板机或直连）")
    p.add_argument("--node", help=f"目标节点，默认 {TRAIN_NODE or '必须指定'}")
    p.add_argument("--allow-other", action="store_true", help="允许操作非默认演练节点")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="节点状态/负载/kubelet/临时任务")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("cpu", help="CPU 压力")
    s.add_argument("seconds", nargs="?", type=int, default=60)
    s.add_argument("--workers", type=int, default=4)
    s.set_defaults(func=cmd_cpu)

    s = sub.add_parser("mem", help="内存压力（cgroup 限流，不保证 OOM）")
    s.add_argument("mb", nargs="?", type=int, default=512)
    s.add_argument("seconds", nargs="?", type=int, default=60)
    s.set_defaults(func=cmd_mem)

    s = sub.add_parser("oom", help="OOM Kill 演示（cgroup 上限小于申请量）")
    s.add_argument("mb", nargs="?", type=int, default=256)
    s.add_argument("seconds", nargs="?", type=int, default=30)
    s.set_defaults(func=cmd_oom)

    s = sub.add_parser("disk", help="磁盘填充")
    s.add_argument("gb", nargs="?", type=int, default=1)
    s.add_argument("seconds", nargs="?", type=int, default=60)
    s.set_defaults(func=cmd_disk)

    s = sub.add_parser("io", help="磁盘 IO 压力（高 iowait）")
    s.add_argument("seconds", nargs="?", type=int, default=60)
    s.add_argument("--workers", type=int, default=2)
    s.set_defaults(func=cmd_io)

    s = sub.add_parser("hang", help="冻结 kubelet/containerd 模拟节点 hang（危险）")
    s.add_argument("seconds", nargs="?", type=int, default=60)
    s.add_argument("--confirm", action="store_true")
    s.set_defaults(func=cmd_hang)

    s = sub.add_parser("kubelet-stop", help="停止 kubelet 模拟 NotReady（危险）")
    s.add_argument("seconds", nargs="?", type=int, default=30)
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_kubelet_stop)

    s = sub.add_parser("reboot", help="重启节点（危险）")
    s.add_argument("--confirm", action="store_true")
    s.set_defaults(func=cmd_reboot)

    s = sub.add_parser("crash", help="内核 crash/宕机（高危）")
    s.add_argument("--confirm", action="store_true")
    s.set_defaults(func=cmd_crash)

    s = sub.add_parser("recover", help="清理所有节点级实验")
    s.set_defaults(func=cmd_recover)

    s = sub.add_parser("logs", help="查看 OOM/kubelet/messages 日志")
    s.set_defaults(func=cmd_logs)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
