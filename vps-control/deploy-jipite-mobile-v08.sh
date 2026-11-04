#!/usr/bin/env bash
# One-command, fail-closed deployment of the Jipite mobile approval API.
# Does NOT change GPU provider power permission, original TOTP approval, or TLS certs.
set -euo pipefail
umask 077

[[ "${EUID}" -eq 0 ]] || { echo "Use sudo bash deploy-jipite-mobile-v08.sh" >&2; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_ID="76fb73a5-fc82-4217-893a-6070eedd16be"
CLIENT_PATH="/etc/comfyui-director-mobile-clientid"

echo "[1/4] Checking existing TOTP approval, Nginx and VPS prerequisites"
systemctl is-active --quiet director-power-approval || {
  echo "ABORT: existing TOTP approval is not active; restore it before installing mobile approval." >&2
  exit 3
}
command -v nginx >/dev/null
command -v curl >/dev/null
command -v python3 >/dev/null
nginx -t
[[ -x /opt/comfyui-director-control/.venv/bin/python &&
   -f /etc/comfyui-director-control.env ]] || {
  echo "ABORT: V0.3 controller prerequisites are missing; existing services untouched." >&2
  exit 3
}

echo "[2/4] Configuring publicly registered Microsoft client ID and installing loopback API"
if [[ -e "$CLIENT_PATH" || -L "$CLIENT_PATH" ]]; then
  [[ -f "$CLIENT_PATH" && ! -L "$CLIENT_PATH" ]] || {
    echo "ABORT: existing client ID file is not a normal file" >&2; exit 4;
  }
  existing_id="$(tr -d '\r\n' < "$CLIENT_PATH")"
  [[ "$existing_id" == "$CLIENT_ID" ]] || {
    echo "ABORT: existing Microsoft client ID differs; refusing to switch accounts." >&2; exit 4;
  }
else
  install -o root -g root -m 0600 /dev/null "$CLIENT_PATH"
  printf '%s\n' "$CLIENT_ID" > "$CLIENT_PATH"
fi
bash "$HERE/install-mobile-v06.sh"

echo "[3/4] Checking the mobile API before exposing HTTPS routing"
systemctl is-active --quiet director-mobile-v06 || {
  echo "Mobile API did not start. Inspect: sudo journalctl -u director-mobile-v06 -n 50 --no-pager" >&2
  exit 5
}
# Service can be 'active' before the Python HTTP server binds to 8895.
# Retry for up to 20 attempts; reject unexpected health JSON immediately.
bash "$HERE/wait-jipite-mobile-health.sh"

echo "[4/4] Installing ONLY the jipite HTTPS virtual-host route"
python3 "$HERE/configure_jipite_mobile_nginx.py" --apply

echo
echo "Deployment finished. Verifying unauthenticated public API (no tokens or secrets):"
status="$(curl --silent --show-error --max-time 12 --output /dev/null \
  --write-out '%{http_code}' -X POST -H 'Content-Type: application/json' \
  --data '{}' https://jipite.borealos.cn/api/v1/mobile/pending)" || status="unreachable"
echo "Public HTTPS status: $status (expected HTTP 401)"
if [[ "$status" != "401" ]]; then
  echo "WARNING: HTTPS check is not yet 401. Confirm public proxy/DNS/SNI separately." >&2
fi
echo "GPU power control was not enabled or modified. Existing TOTP approval was preserved."
echo "Do NOT share VPS pairing secrets or Microsoft tokens in chat."
