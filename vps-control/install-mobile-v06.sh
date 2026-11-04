#!/usr/bin/env bash
# Install V0.6 API on the OWNED Guangzhou VPS. Never changes GPU power.
# Existing V0.3 MCP, browser TOTP backup, certificates and tunnels stay intact.
set -euo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Run via sudo on your own VPS" >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="/opt/comfyui-director-power"
VENV="/opt/comfyui-director-control/.venv"
CLIENT="/etc/comfyui-director-mobile-clientid"
PAIR="/etc/comfyui-director-mobile-pairing"
FCM="/etc/comfyui-director-firebase-service-account.json"
XIAOMI="/etc/comfyui-director-xiaomi-appsecret"
XIAOMI_CONFIG="/etc/comfyui-director-xiaomi-channel.json"

[[ -x "$VENV/bin/python" && -f /etc/comfyui-director-control.env ]] || {
  echo "V0.3 controller must be installed first" >&2; exit 2;
}
systemctl is-active --quiet director-power-approval || {
  echo "Existing TOTP backup must be healthy before V0.6 installation" >&2; exit 2;
}
[[ -f "$HERE/mobile_v06_core.py" && -f "$HERE/mobile_v06_api.py" && -f "$HERE/mobile_v06_xiaomi.py" ]] || {
  echo "Missing new V0.6 source files" >&2; exit 2;
}

if [[ ! -e "$CLIENT" ]]; then
  read -r -p "Microsoft Android App Registration Client ID (UUID, public): " CLIENT_ID
  if ! python3 - "$CLIENT_ID" <<'PY'
import re,sys
raise SystemExit(0 if re.fullmatch(r"[a-fA-F0-9]{8}-(?:[a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12}",sys.argv[1]) else 1)
PY
  then
    echo "Client ID invalid" >&2; exit 3;
  fi
  install -o root -g root -m 0600 /dev/null "$CLIENT"
  printf '%s\n' "$CLIENT_ID" > "$CLIENT"
  unset CLIENT_ID
fi
if [[ ! -e "$PAIR" ]]; then
  python3 - "$PAIR" <<'PY'
import os,secrets,sys
fd=os.open(sys.argv[1],os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,"w",encoding="ascii") as f:
    f.write(secrets.token_urlsafe(32)+"\n")
PY
fi
for path in "$CLIENT" "$PAIR"; do
  [[ -f "$path" && ! -L "$path" ]] || { echo "Credential file is invalid" >&2; exit 4; }
  chown root:root "$path"
  chmod 0600 "$path"
done

"$VENV/bin/python" -m pip install --disable-pip-version-check 'PyJWT[crypto]>=2.9,<3'
# firebase-admin is optional: install only after user configures FCM service account.
if [[ -s "$FCM" ]]; then
  [[ ! -L "$FCM" ]] || { echo "Refusing Firebase symlink" >&2; exit 4; }
  chown root:root "$FCM"; chmod 0600 "$FCM"
  "$VENV/bin/python" -m pip install --disable-pip-version-check 'firebase-admin>=6.6,<8'
fi
for name in mobile_v06_core.py mobile_v06_api.py mobile_v06_xiaomi.py; do
  install -o root -g root -m 0644 "$HERE/$name" "$APP/$name"
done
install -o root -g root -m 0644 "$HERE/director-mobile-v06.service" \
  /etc/systemd/system/director-mobile-v06.service
install -d -o root -g root -m 0755 /etc/systemd/system/director-mobile-v06.service.d
if [[ -s "$FCM" ]]; then
  printf '[Service]\nLoadCredential=firebase:%s\n' "$FCM" \
    > /etc/systemd/system/director-mobile-v06.service.d/firebase.conf
else
  rm -f /etc/systemd/system/director-mobile-v06.service.d/firebase.conf
  echo "FCM credential not installed. App polling works; automatic push is disabled."
fi
if [[ -e "$XIAOMI" && -e "$XIAOMI_CONFIG" ]]; then
  for secretfile in "$XIAOMI" "$XIAOMI_CONFIG"; do
    [[ -f "$secretfile" && ! -L "$secretfile" ]] || {
      echo "Refusing unsafe Xiaomi credential file"; exit 4;
    }
    chown root:root "$secretfile"; chmod 0600 "$secretfile"
  done
  python3 - "$XIAOMI_CONFIG" <<'PY'
import json,re,sys
with open(sys.argv[1], encoding="utf-8") as file:
    data=json.load(file)
if set(data) != {"channel_id", "template_id"} or any(
    not isinstance(data[k],str) or not re.fullmatch(r"[0-9]{1,20}",data[k])
    for k in ("channel_id","template_id")):
    raise SystemExit("Invalid Xiaomi channel/template configuration")
PY
  printf '[Service]\nLoadCredential=xiaomi:%s\nLoadCredential=xiaomicfg:%s\n' \
    "$XIAOMI" "$XIAOMI_CONFIG" \
    > /etc/systemd/system/director-mobile-v06.service.d/xiaomi.conf
  echo "Mi Push enabled ONLY using approved no-variable template and channel."
else
  rm -f /etc/systemd/system/director-mobile-v06.service.d/xiaomi.conf
  echo "Mi Push disabled until both AppSecret and approved channel/template exist."
fi
systemctl daemon-reload
systemctl enable --now director-mobile-v06
systemctl restart director-mobile-v06
systemctl is-active --quiet director-mobile-v06
echo "V0.6 mobile API active on 127.0.0.1:8895 only."
echo "Pairing secret is in $PAIR: read it ONLY on a private VPS terminal."
echo "Do not send pairing secret, Microsoft ID token or Firebase JSON to ChatGPT."
echo "Original independent TOTP approval and cloud power safeguards unchanged."
