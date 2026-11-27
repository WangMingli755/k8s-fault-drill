#!/usr/bin/env python3
"""限时回收器：扫描演练命名空间中带 training.example.com/expires-at 注解、
已到期的 Chaos CR，提交删除请求。

它不是通用恢复器：不恢复配置类、管理组件、节点服务，也不移除 finalizer。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

KINDS = [
    "networkchaos",
    "stresschaos",
    "podchaos",
    "dnschaos",
    "httpchaos",
    "iochaos",
    "timechaos",
]
ANNOTATION = "training.example.com/expires-at"
NAMESPACE = os.environ.get("LAB_NS", "training-lab")


def kubectl(args: list[str], kubeconfig: str | None, context: str | None) -> subprocess.CompletedProcess:
    cmd = [os.environ.get("KUBECTL_BIN", "kubectl")]
    if kubeconfig:
        cmd += ["--kubeconfig", kubeconfig]
    if context:
        cmd += ["--context", context]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def parse_expiry(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true", help="真正提交删除；默认只预览")
    p.add_argument("--kubeconfig", default=os.environ.get("GUARDIAN_KUBECONFIG") or os.path.expanduser("~/.kube/config"))
    p.add_argument("--context", default=os.environ.get("GUARDIAN_CONTEXT"))
    a = p.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    found = 0
    expired = 0
    errors = 0

    for kind in KINDS:
        r = kubectl(["get", kind, "-n", NAMESPACE, "-o", "json"], a.kubeconfig, a.context)
        if r.returncode != 0:
            if "not found" in (r.stderr or "").lower() or "server doesn't have a resource" in (r.stderr or "").lower():
                continue
            print(f"ERROR get {kind}: {r.stderr.strip()[:300]}")
            errors += 1
            continue

        try:
            items = json.loads(r.stdout).get("items", [])
        except json.JSONDecodeError:
            print(f"ERROR parse {kind}: invalid json")
            errors += 1
            continue

        for item in items:
            found += 1
            meta = item.get("metadata", {})
            name = meta.get("name", "?")
            ann = (meta.get("annotations") or {}).get(ANNOTATION)
            if not ann:
                continue
            expiry = parse_expiry(ann)
            if expiry is None:
                print(f"SKIP {kind}/{name}: 无法解析到期时间 {ann!r}")
                continue
            if expiry > now:
                print(f"WAIT {kind}/{name}: 到期 {expiry.isoformat()}")
                continue
            expired += 1
            if not a.execute:
                print(f"WOULD_DELETE {kind}/{name}: 已到期 {expiry.isoformat()}")
                continue
            d = kubectl(["delete", kind, name, "-n", NAMESPACE, "--wait=false"], a.kubeconfig, a.context)
            if d.returncode == 0:
                print(f"DELETE_REQUESTED {kind}/{name}")
            else:
                print(f"DELETE_FAILED {kind}/{name}: {d.stderr.strip()[:300]}")
                errors += 1

    print(f"SUMMARY found={found} expired={expired} errors={errors} execute={a.execute}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
