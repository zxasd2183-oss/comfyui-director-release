#!/usr/bin/env bash
# Guangzhou VPS: one-time service for remotely managed Cloudflare Named Tunnel.
# Never opens local inbound ports or invokes the cloud GPU provider API.
set -euo pipefail
umask 077
if [[ "$EUID" != 0 ]]; then
  echo "Run with sudo bash install-vps-named-tunnel.sh" >&2
  exit 1
fi
CLOUDFLARED="$(command -v cloudflared || true)"
[[ -n "$CLOUDFLARED" ]] || { echo "cloudflared is not installed"; exit 2; }
VERSION_OUTPUT="$("$CLOUDFLARED" --version 2>/dev/null)"
if ! python3 - "$VERSION_OUTPUT" <<'PY'
import re, sys
match=re.search(r"version\s+(\d{4})\.(\d+)\.(\d+)", sys.argv[1], re.I)
raise SystemExit(0 if match and tuple(map(int,match.groups())) >= (2025,4,0) else 1)
PY
then
  echo "cloudflared 2025.4.0+ needed for --token-file" >&2
  exit 2
fi
for name in director-vps-control director-vps-bridge director-power-mcp \
            director-power-approval director-power-bridge; do
  systemctl is-active --quiet "$name" || {
    echo "V0.1/V0.3 service $name is not active; refusing to install tunnel" >&2
    exit 3
  }
done
install -d -o root -g root -m 0700 /etc/comfyui-director
TOKEN_FILE=/etc/comfyui-director/vps-named-tunnel.token
if [[ -e "$TOKEN_FILE" ]]; then
  [[ ! -L "$TOKEN_FILE" ]] || { echo "Refuse token symlink"; exit 4; }
  chown root:root "$TOKEN_FILE"
  chmod 0600 "$TOKEN_FILE"
  echo "Existing VPS tunnel token preserved"
else
  echo "Paste token for the VPS Named Tunnel (not the GPU token)."
  IFS= read -r -s -p "VPS Tunnel token (hidden): " TOKEN
  echo
  if [[ ! "$TOKEN" =~ ^[A-Za-z0-9._-]{64,8192}$ ]]; then
    unset TOKEN
    echo "Invalid token format; nothing installed" >&2
    exit 4
  fi
  (umask 077; printf '%s\n' "$TOKEN" > "$TOKEN_FILE")
  unset TOKEN
  chown root:root "$TOKEN_FILE"
  chmod 0600 "$TOKEN_FILE"
fi
cat > /etc/systemd/system/director-vps-named-tunnel.service <<EOF
[Unit]
Description=Director Guangzhou VPS Cloudflare Named Tunnel
After=network-online.target director-vps-bridge.service director-power-bridge.service
Wants=network-online.target
Requires=director-vps-bridge.service director-power-bridge.service

[Service]
Type=simple
User=root
Group=root
ExecStart=$CLOUDFLARED tunnel --no-autoupdate run --token-file $TOKEN_FILE
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 /etc/systemd/system/director-vps-named-tunnel.service
systemctl daemon-reload
systemctl enable --now director-vps-named-tunnel.service
systemctl is-active director-vps-named-tunnel.service
echo "Named Tunnel enabled as a persistent VPS systemd service."
echo "Cloudflare routes to configure: status->127.0.0.1:8891, power->8894, approve->8893"
echo "Old read-only and approval services are not altered."
echo "No GPU power operation was performed."
