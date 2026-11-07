#!/usr/bin/env bash
# Installs separately gated V0.3 *request* and approval services on Ubuntu.
# This script NEVER invokes StartCompShareInstance or StopCompShareInstance.
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
  echo 'Run with: sudo bash install-power-v03.sh' >&2
  exit 1
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
APP="/opt/comfyui-director-power"
BRIDGE="/opt/comfyui-director-control/bridge.py"

if [[ ! -f "/etc/comfyui-director-control.env" || ! -x "/opt/comfyui-director-control/.venv/bin/python" ]]; then
  echo "Install and configure V0.1/V0.2 VPS controller first." >&2
  exit 1
fi
if [[ ! -f "$SRC/power_v03.py" || ! -f "$SRC/power_write_mcp.py" || ! -f "$SRC/power_approval_http.py" ]]; then
  echo "Missing V0.3 sources; run git pull --ff-only first." >&2
  exit 1
fi
id directorctl >/dev/null 2>&1 || { echo "directorctl account missing"; exit 1; }
id directorpower >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin directorpower

mkdir -p "$APP"
for name in power_ops.py power_v03.py power_direct.py power_write_mcp.py power_approval_http.py; do
  install -o root -g root -m 0644 "$SRC/$name" "$APP/$name"
done
install -o root -g root -m 0644 "$SRC/bridge.py" "$BRIDGE"

# Files are generated only once; rerunning installer does not rotate keys.
python3 - <<'PY'
import base64, os, secrets
configs=[
    ("/etc/comfyui-director-otp.seed",
      base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")+"\n"),
    ("/etc/comfyui-director-approval-route",secrets.token_hex(32)+"\n"),
    ("/etc/comfyui-director-power-mcp.token",secrets.token_hex(32)+"\n"),
]
for path,value in configs:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        continue
    with os.fdopen(fd,"w",encoding="ascii") as stream:
        stream.write(value)
PY
chmod 0600 /etc/comfyui-director-otp.seed /etc/comfyui-director-approval-route
chown root:root /etc/comfyui-director-otp.seed /etc/comfyui-director-approval-route
chown root:directorctl /etc/comfyui-director-power-mcp.token
chmod 0640 /etc/comfyui-director-power-mcp.token

for name in director-power-mcp director-power-approval director-power-bridge; do
  install -o root -g root -m 0644 "$SRC/$name.service" "/etc/systemd/system/$name.service"
done
systemctl daemon-reload
systemctl enable --now director-power-mcp director-power-approval director-power-bridge
systemctl restart director-power-mcp director-power-approval director-power-bridge

echo "V0.3 STAGING SERVICES INSTALLED (loopback-only):"
echo " - power request MCP: 127.0.0.1:8892 (private, don't expose)"
echo " - owner approval UI: 127.0.0.1:8893 (private, don't expose)"
echo " - power request private bridge: 127.0.0.1:8894 (private)"
echo " - original read-only 8890/8891 services unchanged"
echo ""
echo "NO GPU POWER OPERATION WAS PERFORMED."
echo "Check: sudo systemctl is-active director-power-mcp director-power-approval director-power-bridge"
echo "TOTP enrollment and authenticated HTTPS tunnel steps are in POWER_V03.md."
