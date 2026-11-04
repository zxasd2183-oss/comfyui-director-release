#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Use: sudo bash install-powerctl.sh" >&2
  exit 1
fi

BASE="/opt/comfyui-director-control"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ ! -f "$BASE/app.py" || ! -x "$BASE/.venv/bin/python" ]]; then
  echo "VPS control center must be installed first." >&2
  exit 1
fi
if [[ ! -f /etc/comfyui-director-control.env ]]; then
  echo "Missing /etc/comfyui-director-control.env" >&2
  exit 1
fi
install -o root -g root -m 0644 "$SCRIPT_DIR/power_ops.py" "$BASE/power_ops.py"
install -o root -g root -m 0644 "$SCRIPT_DIR/powerctl.py" "$BASE/powerctl.py"

cat >/usr/local/sbin/director-powerctl <<'SH'
#!/usr/bin/env sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Requires sudo (interactive operator only)" >&2
    exit 1
fi
exec /opt/comfyui-director-control/.venv/bin/python /opt/comfyui-director-control/powerctl.py "$@"
SH
chmod 0755 /usr/local/sbin/director-powerctl
chown root:root /usr/local/sbin/director-powerctl

echo "Installed local-only Director Powerctl."
echo "No MCP write tools were enabled and no GPU power operation was performed."
echo ""
echo "Read status:          sudo director-powerctl status"
echo "Preview start:        sudo director-powerctl plan-start"
echo "Preview stop:         sudo director-powerctl plan-stop"
echo "Start with approval:  sudo director-powerctl apply-start"
echo "Stop with approval:   sudo director-powerctl apply-stop"
echo ""
echo "Stopping is fail-closed unless a trusted GPU queue endpoint is configured."
echo "Configure DIRECTOR_GPU_MCP_URL in /etc/comfyui-director-control.env"
echo "with the existing H3 Director V3 read-only HTTPS MCP URL (keep it secret)."
echo "Do not paste private URLs or credentials into GitHub or the chat."
