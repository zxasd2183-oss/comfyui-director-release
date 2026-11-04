#!/usr/bin/env bash
# Upgrade an already-working Jipite VPS APK mirror to publish-on-release.
# Only installs a loopback OIDC receiver + one isolated Nginx location.
# No GitHub shared secret, SSH key, Microsoft token, TOTP or GPU permissions.
set -euo pipefail
umask 077

if [[ "$EUID" -ne 0 ]]; then
  echo "Run only on your own VPS: sudo bash vps-control/install-jipite-immediate-sync.sh" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE=/opt/jipite-updates
STATE=/var/lib/jipite-updates
MOBILE=/etc/nginx/snippets/jipite-mobile.conf
SNIPPET=/etc/nginx/snippets/jipite-immediate-notify.conf
UNIT=/etc/systemd/system/jipite-immediate-notify.service
SRC_SNIPPET="$HERE/nginx-alidns/jipite-immediate-notify.conf"
INCLUDE="include $SNIPPET;"

echo "[1/4] Checking existing Jipite, TOTP, update timer and Nginx..."
for c in python3 openssl nginx curl systemctl; do command -v "$c" >/dev/null; done
nginx -t
for unit in director-mobile-v06 director-power-approval jipite-android-update-sync.timer; do
  systemctl is-active --quiet "$unit" || {
    echo "ABORT: prerequisite $unit is not active; no Nginx changes" >&2
    exit 3
  }
done
id jipiteupdate >/dev/null 2>&1
[[ -d "$CODE" && -d "$STATE" ]] || { echo "ABORT: VPS mirror not installed" >&2; exit 3; }
[[ -f "$MOBILE" && ! -L "$MOBILE" ]] || {
  echo "ABORT: mobile HTTPS snippet missing or symlinked" >&2; exit 3;
}
grep -Fq "location ^~ /api/v1/mobile/" "$MOBILE" || {
  echo "ABORT: original Microsoft-gated API route missing" >&2; exit 3;
}
grep -Fq "include /etc/nginx/snippets/jipite-android-updates.conf;" "$MOBILE" || {
  echo "ABORT: existing APK mirror route missing" >&2; exit 3;
}
[[ -f "$SRC_SNIPPET" ]] || exit 3
[[ ! -L "$UNIT" && ! -L "$SNIPPET" ]] || {
  echo "ABORT: refusing to overwrite symlinked system configs" >&2; exit 3;
}

echo "[2/4] Installing unprivileged GitHub OIDC verifier and loopback receiver..."
install -o root -g root -m 0644 "$HERE/jipite_oidc.py" "$CODE/jipite_oidc.py"
install -o root -g root -m 0644 "$HERE/jipite-immediate-notify.py" "$CODE/jipite-immediate-notify.py"
install -o root -g root -m 0644 "$HERE/jipite-immediate-notify.service" "$UNIT"
python3 -m py_compile "$CODE/jipite_oidc.py" "$CODE/jipite-immediate-notify.py"
systemctl daemon-reload
systemctl enable --now jipite-immediate-notify.service
systemctl restart jipite-immediate-notify.service
# The service can be active before it binds 127.0.0.1:8896.
ready=0
for i in $(seq 1 20); do
  code="$(curl -sS --max-time 2 --output /dev/null -w '%{http_code}' \
    http://127.0.0.1:8896/notify 2>/dev/null)" || code=""
  if [[ "$code" == 405 ]]; then ready=1; break; fi
  sleep 0.5
done
[[ "$ready" -eq 1 ]] || {
  echo "ABORT: local OIDC notifier is not ready; Nginx unchanged" >&2
  echo "  sudo journalctl -u jipite-immediate-notify.service -n 40 --no-pager" >&2
  exit 4
}

echo "[3/4] Adding only the authenticated /app-updates/notify HTTPS route..."
if [[ -e "$SNIPPET" ]] && ! cmp -s "$SNIPPET" "$SRC_SNIPPET"; then
  echo "ABORT: existing VPS notify snippet differs, manual review needed" >&2
  exit 5
fi
includes="$(grep -Fc "$INCLUDE" "$MOBILE" || true)"
if [[ "$includes" -gt 1 ]]; then
  echo "ABORT: duplicate includes found; no Nginx changes" >&2
  exit 5
fi
backup="$(mktemp /etc/nginx/snippets/.jipite-notify-backup.XXXXXXXX)"
cp -p "$MOBILE" "$backup"
created=0
success=0
rollback() {
  if [[ "$success" == 0 ]]; then
    cp -p "$backup" "$MOBILE"
    if [[ "$created" == 1 ]]; then rm -f "$SNIPPET"; fi
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
    echo "Rolled back HTTPS notification route; approval and APK downloads unchanged." >&2
  fi
}
trap rollback EXIT
if [[ ! -e "$SNIPPET" ]]; then
  install -o root -g root -m 0644 "$SRC_SNIPPET" "$SNIPPET"
  created=1
fi
if [[ "$includes" == 0 ]]; then
  printf '\n%s\n' "$INCLUDE" >> "$MOBILE"
fi
nginx -t
systemctl reload nginx
success=1
trap - EXIT

echo "[4/4] Checking public endpoints and synchronizing the already published release..."
status_notify="$(curl -sS --max-time 10 -X POST \
  -H 'Content-Type: application/json' --data '{}' \
  -o /dev/null -w '%{http_code}' \
  https://jipite.borealos.cn/app-updates/notify)" || status_notify="unreachable"
status_api="$(curl -sS --max-time 10 -X POST \
  -H 'Content-Type: application/json' --data '{}' \
  -o /dev/null -w '%{http_code}' \
  https://jipite.borealos.cn/api/v1/mobile/pending)" || status_api="unreachable"
status_manifest="$(curl -sS --max-time 10 \
  -o /dev/null -w '%{http_code}' \
  https://jipite.borealos.cn/app-updates/latest.json)" || status_manifest="unreachable"
echo "Unauthenticated immediate trigger: HTTP $status_notify (expected 401)"
echo "Microsoft approval API: HTTP $status_api (expected 401)"
echo "Public update manifest: HTTP $status_manifest (expected 200)"
if [[ "$status_notify" != 401 || "$status_api" != 401 || "$status_manifest" != 200 ]]; then
  echo "WARNING: a public route is not returning the expected status; inspect before relying on immediate sync." >&2
fi
# Safe immediate refresh of the *already published* version. Future Releases
# will trigger OIDC automatically, while the hourly timer stays active.
systemctl start jipite-android-update-sync.service
echo "Current published VPS version:"
python3 -c 'import json;print(json.load(open("/var/lib/jipite-updates/latest.json"))["version"])'
echo "OIDC notification service: $(systemctl is-active jipite-immediate-notify.service)"
echo "Hourly fallback: $(systemctl is-active jipite-android-update-sync.timer)"
echo "Nginx backup: $backup"
echo "No GPU permission, pairing code, Microsoft token or signing key was modified."
