#!/usr/bin/env bash
# 把通用 K8s 故障演练工具箱安装到演练目录（默认 ~/k8s-fault-lab）。
# 用法:
#   ./install.sh                 # 复制脚本 + 生成证书
#   ./install.sh --baseline      # 安装后部署 training-lab 基线
#   ./install.sh --chaos         # 安装 Chaos Mesh 2.8.8（会改集群，需确认）
#   ./install.sh --guardian      # 安装 systemd user timer（仅默认目录）
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${LAB_HOME:-$HOME/k8s-fault-lab}"
WITH_BASELINE=0
WITH_CHAOS=0
WITH_GUARDIAN=0

for arg in "$@"; do
  case "$arg" in
    --baseline) WITH_BASELINE=1 ;;
    --chaos) WITH_CHAOS=1 ;;
    --guardian) WITH_GUARDIAN=1 ;;
    -h|--help)
      sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$DEST/runs" "$DEST/logs" "$DEST/certs" "$DEST/ml-src"
cp -f "$SRC"/faultlab "$SRC"/lab "$SRC"/lab-adv "$SRC"/ml-lab "$DEST"/
cp -f "$SRC"/node_lab.py "$SRC"/prepare-chaos.py "$SRC"/chaos-guardian.py "$SRC"/install-guardian-units.py "$DEST"/
cp -f "$SRC"/lab.env.example "$DEST"/lab.env.example
cp -f "$SRC"/chaos-mesh-values.yaml "$SRC"/01-namespaces.yaml "$SRC"/04-baseline.yaml "$DEST"/
cp -f "$SRC"/06-network-delay.yaml "$SRC"/07-cpu-stress.yaml "$SRC"/08-finalizer-pod.yaml "$DEST"/
cp -f "$SRC"/09-pod-kill.yaml "$SRC"/10-pod-failure.yaml "$SRC"/11-dns-error.yaml "$DEST"/
cp -f "$SRC"/certs/gen_certs.py "$DEST/certs/"
cp -f "$SRC"/ml-src/train.py "$SRC"/ml-src/serve.py "$DEST/ml-src/"
cp -f "$SRC"/../references/playbook.md "$DEST/PLAYBOOK.md"
chmod +x "$DEST/faultlab" "$DEST/lab" "$DEST/lab-adv" "$DEST/ml-lab" "$DEST/node_lab.py"

if [ ! -f "$DEST/certs/server.crt" ]; then
  python3 "$DEST/certs/gen_certs.py" >/dev/null
fi

if [ "$WITH_CHAOS" = 1 ]; then
  command -v helm >/dev/null || { echo "缺少 helm，无法安装 Chaos Mesh" >&2; exit 1; }
  helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1 || true
  helm repo update >/dev/null
  helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
    -n chaos-mesh --create-namespace --version 2.8.8 \
    -f "$DEST/chaos-mesh-values.yaml"
fi

if [ "$WITH_BASELINE" = 1 ]; then
  "$DEST/lab" baseline
fi

if [ "$WITH_GUARDIAN" = 1 ]; then
  if [ "$DEST" != "$HOME/k8s-fault-lab" ]; then
    echo "跳过 guardian：install-guardian-units.py 只支持默认目录 ~/k8s-fault-lab" >&2
  else
    LAB_HOME="$DEST" python3 "$DEST/install-guardian-units.py"
    systemctl --user daemon-reload || true
    systemctl --user enable --now k8s-fault-guardian.timer || true
  fi
fi

cat <<EOF
安装完成: $DEST

下一步:
  1) 准备 kubeconfig，确认: kubectl get nodes
  2) 配置节点 SSH: cp "$DEST/lab.env.example" "$DEST/lab.env"
     - 有跳板机: NODE_SSH_MODE=jump + JUMP_HOST/JUMP_PORT/JUMP_KEY
     - 无跳板机: NODE_SSH_MODE=direct + NODE_SSH_KEY/NODE_SSH_PORT/NODE_SSH_USER
     然后: set -a; source "$DEST/lab.env"; set +a
  3) 安装 Chaos Mesh（如未安装）:
     helm repo add chaos-mesh https://charts.chaos-mesh.org
     helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \\
       -n chaos-mesh --create-namespace --version 2.8.8 \\
       -f "$DEST/chaos-mesh-values.yaml"
  4) 部署基线并自检:
     export LAB_HOME="$DEST"
     "$DEST/lab" baseline
     "$DEST/faultlab" status
     "$DEST/faultlab" list
     "$DEST/faultlab" run net-delay 60
     "$DEST/faultlab" recover all

可选: 本脚本加 --chaos 会自动执行第 3 步；--baseline 会自动执行第 4 步。
EOF
