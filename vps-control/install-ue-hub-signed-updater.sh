#!/usr/bin/env bash
# ONE-TIME VPS root bootstrap. The installed updater only PULLS signed UE Hub
# releases; no remote command, server login, new listening socket or GPU action.
set -Eeuo pipefail
umask 077
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 2; }
(( EUID == 0 )) || die 'Use sudo/root'
(( $# == 1 )) || die 'Usage: install-ue-hub-signed-updater.sh <64-hex-Ed25519-PUBLIC-key>'
PUB="$1"
[[ "$PUB" =~ ^[a-f0-9]{64}$ ]] || die 'Public key must be lowercase 64 hex'
SRC="$(cd "$(dirname "$0")" && pwd)"
PY="/opt/comfyui-director-control/.venv/bin/python"
APP="/opt/comfyui-director-hub"
CODE="/opt/director-ue-hub-signed-updater"
STATE="/var/lib/director-ue-hub-updater"
KEY="/etc/director-ue-hub-update.pub"
SVC="/etc/systemd/system/director-ue-hub-signed-update.service"
TIMER="/etc/systemd/system/director-ue-hub-signed-update.timer"
[[ -f "$SRC/ue_hub_signed_updater.py" && ! -L "$SRC/ue_hub_signed_updater.py" ]] || die 'Trusted updater code missing'
[[ -x "$PY" && -d "$APP" && ! -L "$APP" ]] || die 'Existing VPS Hub missing'
for f in hub_app.py ue_worker_rpc.py; do
  [[ -f "$APP/$f" && ! -L "$APP/$f" ]] || die "Live Hub $f missing/unsafe"
done
systemctl is-active --quiet director-hub-mcp.service || die 'Existing Hub inactive'
systemctl is-active --quiet director-hub-bridge.service || die 'Existing private bridge inactive'
"$PY" -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' ||
  die 'Existing VPS Python venv needs cryptography (install via trusted package manager first)'
"$PY" -m py_compile "$SRC/ue_hub_signed_updater.py" || die 'Updater syntax invalid'
if [[ -e "$KEY" || -e "$SVC" || -e "$TIMER" || -e "$CODE" || -e "$STATE" ]]; then
  die 'Existing trust installation detected. Refusing to overwrite key, timer or update state.'
fi
install -d -m 0700 "$CODE" "$STATE"
install -m 0600 "$SRC/ue_hub_signed_updater.py" "$CODE/ue_hub_signed_updater.py"
printf '%s' "$PUB" > "$KEY"
chmod 0600 "$KEY"
# Legacy Hub is not signed yet. Subsequent releases must monotonically
# increase above this baseline. Worker must report active_job_id.
printf '%s' '0.5.1' > "$STATE/installed-version.txt"
cat > "$SVC" <<'UNIT'
[Unit]
Description=Director Hub pinned signed UE API updater (2 fixed Python files)
Wants=network-online.target
After=network-online.target director-hub-mcp.service

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
# The Python downloader pins this same loopback proxy explicitly: ambient
# proxy variables cannot redirect privileged release verification elsewhere.
Environment=HTTPS_PROXY=http://127.0.0.1:1081
Environment=NO_PROXY=127.0.0.1,localhost
ExecStart=/opt/comfyui-director-control/.venv/bin/python /opt/director-ue-hub-signed-updater/ue_hub_signed_updater.py
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=/opt/comfyui-director-hub /var/lib/director-ue-hub-updater
TimeoutStartSec=110
UNIT
cat > "$TIMER" <<'UNIT'
[Unit]
Description=Check for signed Director Hub UE API updates

[Timer]
OnBootSec=3min
OnUnitInactiveSec=5min
RandomizedDelaySec=25s
Persistent=true
Unit=director-ue-hub-signed-update.service

[Install]
WantedBy=timers.target
UNIT
chmod 0644 "$SVC" "$TIMER"
systemctl daemon-reload
systemctl enable --now director-ue-hub-signed-update.timer
systemctl is-enabled --quiet director-ue-hub-signed-update.timer ||
  die 'Updater timer not enabled'
echo 'SUCCESS: root-owned signed UE Hub updater timer installed; no Hub restart or code changes performed.'
echo 'Pinned key stored root-only; update check every 5 min. Updates require released Ed25519-signed main-branch artifacts.'
