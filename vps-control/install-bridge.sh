#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
  echo 'Use: sudo bash install-bridge.sh' >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="/opt/comfyui-director-control"
TOKEN_FILE="/etc/comfyui-director-bridge.token"
if [[ ! -f "$TARGET/app.py" ]]; then
  echo 'Install VPS control center first, then install bridge.' >&2
  exit 1
fi
id directorctl >/dev/null 2>&1 || { echo 'directorctl system user missing'; exit 1; }
install -o root -g root -m 0644 "$SCRIPT_DIR/bridge.py" "$TARGET/bridge.py"
if [[ ! -e "$TOKEN_FILE" ]]; then
  python3 - "$TOKEN_FILE" <<'PY'
import os, secrets, sys
path=sys.argv[1]
fd=os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
with os.fdopen(fd,'w',encoding='ascii') as out:
    out.write(secrets.token_hex(32)+'\n')
PY
fi
chown root:directorctl "$TOKEN_FILE"
chmod 0640 "$TOKEN_FILE"
install -o root -g root -m 0644 "$SCRIPT_DIR/director-vps-bridge.service" /etc/systemd/system/director-vps-bridge.service
systemctl daemon-reload
systemctl enable --now director-vps-bridge
systemctl restart director-vps-bridge
echo "Bridge installed and running on VPS localhost:8891"
echo "Test with: sudo systemctl status director-vps-bridge --no-pager"
echo "For testing, start an HTTPS tunnel to http://127.0.0.1:8891"
echo "To obtain the URL suffix, locally run: sudo cat /etc/comfyui-director-bridge.token"
echo "Do not paste the token, its URL, or the .env file into ChatGPT."
