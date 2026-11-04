#!/usr/bin/env bash
# Enable an independent OIDC-only immediate notify endpoint for Glacier Mac.
# Existing Jipite OIDC/APK endpoints, MSAL approvals, GPU and Nginx static
# release mirrors are left in place. No SSH secrets or signing keys involved.
set -euo pipefail
umask 077
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root using sudo on the VPS" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE=/opt/glacier-macos-updates
DATA=/var/lib/glacier-macos-updates
MOBILE=/etc/nginx/snippets/jipite-mobile.conf
SNIPPET=/etc/nginx/snippets/glacier-macos-immediate-notify.conf
SOURCE="$HERE/nginx-alidns/glacier-macos-immediate-notify.conf"
UNIT=/etc/systemd/system/glacier-macos-immediate-notify.service
UNIT_SRC="$HERE/glacier-macos-immediate-notify.service"
INCLUDE="include $SNIPPET;"

for c in nginx python3 openssl systemctl curl cmp install; do
  command -v "$c" >/dev/null || { echo "Missing $c" >&2; exit 3; }
done
echo "[1/4] Verify existing read-only Glacier mirror and other service boundaries"
nginx -t
id glacierupdate >/dev/null
for f in "$CODE/venv/bin/python" "$CODE/sync-glacier-macos-updates.py" "$DATA/macos-arm64.json"; do
  [[ -f "$f" && ! -L "$f" ]] || { echo "Required preinstalled file missing: $f" >&2; exit 3; }
done
systemctl is-active --quiet glacier-macos-update-sync.timer || {
  echo "Mac 30-minute fallback timer not active, refusing to alter routes" >&2; exit 3;
}
[[ -f "$MOBILE" && ! -L "$MOBILE" ]] || {
  echo "Existing mobile HTTPS snippet missing/unsafe" >&2; exit 3;
}
grep -Fq 'location ^~ /api/v1/mobile/' "$MOBILE" || {
  echo "Original authenticated mobile API missing; refusing" >&2; exit 3;
}
grep -Fq 'include /etc/nginx/snippets/glacier-macos-updates.conf;' "$MOBILE" || {
  echo "Original Glacier HTTPS mirror location missing; refusing" >&2; exit 3;
}
[[ -f "$SOURCE" && -f "$UNIT_SRC" ]] || {
  echo "Local OIDC service/snippet files missing" >&2; exit 3;
}
for f in "$UNIT" "$SNIPPET"; do
  [[ ! -L "$f" ]] || { echo "Refusing to replace symlink $f" >&2; exit 3; }
done
if [[ -f "$SNIPPET" ]] && ! cmp -s "$SNIPPET" "$SOURCE"; then
  echo "Existing notify Nginx snippet differs; manual review required" >&2; exit 3;
fi
if [[ -f "$UNIT" ]] && ! cmp -s "$UNIT" "$UNIT_SRC"; then
  echo "Existing notification systemd service differs; manual review required" >&2; exit 3;
fi
matches="$(grep -Fxc "$INCLUDE" "$MOBILE" || true)"
[[ "$matches" -le 1 ]] || { echo "Duplicate notify include; refusing" >&2; exit 3; }

echo "[2/4] Install loopback-only unprivileged OIDC receiver"
install -m 0644 -o root -g root "$HERE/glacier_oidc.py" "$CODE/glacier_oidc.py"
install -m 0644 -o root -g root "$HERE/glacier-macos-immediate-notify.py" "$CODE/glacier-macos-immediate-notify.py"
install -m 0644 -o root -g root "$UNIT_SRC" "$UNIT"
"$CODE/venv/bin/python" -m py_compile "$CODE/glacier_oidc.py" "$CODE/glacier-macos-immediate-notify.py"
systemctl daemon-reload
systemctl enable --now glacier-macos-immediate-notify.service
systemctl restart glacier-macos-immediate-notify.service
ready=0
for i in $(seq 1 30); do
  status="$(curl -sS --connect-timeout 1 --max-time 2 -o /dev/null -w '%{http_code}' \
    'http://127.0.0.1:8897/notify' 2>/dev/null)" || status=""
  if [[ "$status" = 405 ]]; then ready=1; break; fi
  sleep 0.5
done
[[ "$ready" -eq 1 ]] || {
  echo "Loopback OIDC receiver not ready; Nginx unchanged" >&2; exit 4;
}

echo "[3/4] Configure only exact-match /glacier-updates/notify HTTPS route"
backup="$(mktemp /etc/nginx/snippets/.glacier-notify-backup.XXXXXXXX)"
cp -p "$MOBILE" "$backup"
created=0
committed=0
rollback() {
  if [[ "$committed" != 1 ]]; then
    cp -p "$backup" "$MOBILE"
    [[ "$created" = 1 ]] && rm -f "$SNIPPET"
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
    echo "Nginx restored; static Mac, Jipite and GPU routes unchanged" >&2
  fi
}
trap rollback EXIT
if [[ ! -f "$SNIPPET" ]]; then
  install -m 0644 -o root -g root "$SOURCE" "$SNIPPET"
  created=1
fi
if [[ "$matches" -eq 0 ]]; then
  printf '\n%s\n' "$INCLUDE" >> "$MOBILE"
fi
nginx -t
systemctl reload nginx

echo "[4/4] Verify unauthenticated notify is denied and public feeds remain healthy"
http() {
  curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$@" || true
}
glacier_notify="$(http -X POST -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/glacier-updates/notify)"
jipite_notify="$(http -X POST -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/app-updates/notify)"
glacier_feed="$(http https://jipite.borealos.cn/glacier-updates/macos-arm64.json)"
jipite_feed="$(http https://jipite.borealos.cn/app-updates/latest.json)"
mobile_api="$(http -X POST -H 'Content-Type: application/json' --data '{}' \
  https://jipite.borealos.cn/api/v1/mobile/pending)"
echo "Unauthenticated Glacier OIDC POST: $glacier_notify (expected 401)"
echo "Unauthenticated Jipite OIDC POST: $jipite_notify (expected 401)"
echo "Glacier static update feed: $glacier_feed (expected 200)"
echo "Jipite static update feed: $jipite_feed (expected 200)"
echo "Mobile approval API without token: $mobile_api (expected 401)"
if [[ "$glacier_notify" != 401 || "$jipite_notify" != 401 ||
      "$glacier_feed" != 200 || "$jipite_feed" != 200 || "$mobile_api" != 401 ]]; then
  echo "Public health check failed; rolling back new Nginx route" >&2; exit 5;
fi
committed=1
trap - EXIT
echo "Glacier Mac OIDC immediate notify: active $(systemctl is-active glacier-macos-immediate-notify.service)"
echo "30-minute existing Glacier fallback remains active."
echo "Nginx backup: $backup"
echo "No GitHub SSH secrets, signing private keys or Jipite/GPU permissions needed."
