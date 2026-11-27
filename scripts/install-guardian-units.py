#!/usr/bin/env python3
"""生成 systemd 用户级 guardian service/timer 文件（不自动 enable）。"""
import os
import pathlib
import shutil

HOME = pathlib.Path.home()
LAB = pathlib.Path(os.environ.get("LAB_HOME", HOME / "k8s-fault-lab"))
UNIT_DIR = HOME / ".config/systemd/user"
KUBECTL = shutil.which("kubectl") or str(HOME / ".local" / "bin" / "kubectl")
PYTHON = shutil.which("python3") or "/usr/bin/python3"
NS = os.environ.get("LAB_NS", "training-lab")

SERVICE = f"""[Unit]
Description=K8s fault drill chaos guardian (expired Chaos CR reaper)
After=network-online.target

[Service]
Type=oneshot
Environment=LAB_NS={NS}
Environment=GUARDIAN_KUBECONFIG={HOME}/.kube/config
Environment=KUBECTL_BIN={KUBECTL}
ExecStart={PYTHON} {LAB}/chaos-guardian.py --execute
Nice=10
"""

TIMER = """[Unit]
Description=Run K8s fault drill chaos guardian every minute

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=5s
Unit=k8s-fault-guardian.service

[Install]
WantedBy=timers.target
"""


def main() -> None:
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (UNIT_DIR / "k8s-fault-guardian.service").write_text(SERVICE, encoding="utf-8")
    (UNIT_DIR / "k8s-fault-guardian.timer").write_text(TIMER, encoding="utf-8")
    print(UNIT_DIR / "k8s-fault-guardian.service")
    print(UNIT_DIR / "k8s-fault-guardian.timer")


if __name__ == "__main__":
    main()
