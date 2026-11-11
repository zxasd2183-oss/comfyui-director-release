#!/usr/bin/env bash
# One-time root bootstrap for read-only network PULL of signed Studio code.
# No arbitrary commands, no new port, no edits to Studio DB or login config.
set -Eeuo pipefail
umask 077
die(){ echo "ERROR: $*" >&2; exit 2; }
(( EUID == 0 )) || die "Run this installer with sudo on the existing VPS"
(( $# == 0 )) || die "No arguments accepted"
SRC="$(cd "$(dirname "$0")" && pwd)"
PY=/opt/comfyui-director-control/.venv/bin/python
STUDIO=/opt/director-studio
UPDATER=/opt/director-studio-signed-updater
STATE=/var/lib/director-studio-signed-updater
PUB=/etc/director-ue-hub-update.pub
SVC=/etc/systemd/system/director-studio-signed-update.service
TIMER=/etc/systemd/system/director-studio-signed-update.timer
[[ -x "$PY" && -d "$STUDIO" && ! -L "$STUDIO" ]] || die "Existing Studio and trusted Python venv required"
[[ -f "$STUDIO/studio_server.py" && ! -L "$STUDIO/studio_server.py" ]] || die "Existing Studio server missing/unsafe"
systemctl is-active --quiet director-studio.service || die "Studio must already be active"
[[ -f "$PUB" && ! -L "$PUB" && "$(stat -c %s "$PUB")" -eq 64 ]] || die "Existing pinned Hub public trust key required"
grep -Eq '^[0-9a-f]{64}$' "$PUB" || die "Trust key invalid"
[[ -f "$SRC/studio_signed_updater.py" && ! -L "$SRC/studio_signed_updater.py" ]] || die "Missing reviewed updater"
"$PY" -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' || die "Pinned Ed25519 verifier unavailable"
"$PY" -m py_compile "$SRC/studio_signed_updater.py"
for target in "$UPDATER" "$STATE" "$SVC" "$TIMER"; do
  [[ ! -e "$target" && ! -L "$target" ]] || die "Updater already installed or partial installation detected; refuse overwrite: $target"
done
install -d -o root -g root -m 0700 "$UPDATER" "$STATE"
install -o root -g root -m 0600 "$SRC/studio_signed_updater.py" "$UPDATER/studio_signed_updater.py"
# The existing Studio is V0.9.0. Signed releases must monotonically increase.
printf '%s' '0.9.0' > "$STATE/installed-version.txt"
cat > "$SVC" <<'UNIT'
[Unit]
Description=Director Studio pinned Ed25519 signed updater (fixed application files)
Wants=network-online.target
After=network-online.target director-studio.service

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
Environment=HTTPS_PROXY=http://127.0.0.1:1081
Environment=NO_PROXY=127.0.0.1,localhost
ExecStart=/opt/comfyui-director-control/.venv/bin/python /opt/director-studio-signed-updater/studio_signed_updater.py
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=/opt/director-studio /var/lib/director-studio-signed-updater
TimeoutStartSec=120
UNIT
cat > "$TIMER" <<'UNIT'
[Unit]
Description=Poll verified Director Studio releases (no user action needed)

[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
RandomizedDelaySec=20s
Persistent=true
Unit=director-studio-signed-update.service

[Install]
WantedBy=timers.target
UNIT
chmod 0644 "$SVC" "$TIMER"
systemctl daemon-reload
systemctl enable --now director-studio-signed-update.timer
systemctl is-enabled --quiet director-studio-signed-update.timer || die "Update timer not enabled"
echo "SUCCESS: Studio signed update timer bootstrapped; current Studio unchanged."
echo "Only immutable main-branch Ed25519 signed code updates install automatically."
echo "Rollback retains original code. Studio DB, media, sessions, nginx, power controls untouched."
