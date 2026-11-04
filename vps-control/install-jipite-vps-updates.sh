#!/usr/bin/env bash
# One-time, guarded Jipite APK mirror installation on the owner's VPS.
# Does NOT modify the GPU controller, approval API service or Microsoft secrets.
set -euo pipefail
umask 027

if [[ "$EUID" -ne 0 ]]; then
  echo "Please run with sudo on your own VPS." >&2
  exit 2
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="/var/lib/jipite-updates"
CODE="/opt/jipite-updates"
MOBILE_SNIPPET="/etc/nginx/snippets/jipite-mobile.conf"
UPDATES_SNIPPET="/etc/nginx/snippets/jipite-android-updates.conf"
INCLUDE="include $UPDATES_SNIPPET;"
SRC_SNIPPET="$HERE/nginx-alidns/jipite-android-updates.conf"

echo "[1/4] Checking the existing Jipite HTTPS and approval environment..."
for command in nginx systemctl curl python3 cmp; do command -v "$command" >/dev/null; done
nginx -t
systemctl is-active --quiet director-mobile-v06 || {
  echo "ABORT: mobile approval API isn't active. Existing services unchanged." >&2; exit 3;
}
systemctl is-active --quiet director-power-approval || {
  echo "ABORT: TOTP fallback isn't active. Existing services unchanged." >&2; exit 3;
}
[[ -f "$MOBILE_SNIPPET" && ! -L "$MOBILE_SNIPPET" ]] || {
  echo "ABORT: expected existing mobile Nginx snippet is missing or symlinked." >&2; exit 3;
}
grep -Fq 'location ^~ /api/v1/mobile/' "$MOBILE_SNIPPET" || {
  echo "ABORT: original mobile API route is missing. No Nginx modifications." >&2; exit 3;
}
[[ -f "$SRC_SNIPPET" ]] || { echo "Missing update Nginx snippet" >&2; exit 3; }

echo "[2/4] Configuring least-privileged hourly GitHub-to-VPS APK mirror..."
if ! id -u jipiteupdate >/dev/null 2>&1; then
  useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin jipiteupdate
fi
install -d -m 0755 -o jipiteupdate -g jipiteupdate "$ROOT"
install -d -m 0755 -o root -g root "$CODE"
install -m 0644 -o root -g root "$HERE/sync-jipite-updates.py" "$CODE/sync-jipite-updates.py"
install -m 0644 -o root -g root "$HERE/jipite-android-update-sync.service" \
  /etc/systemd/system/jipite-android-update-sync.service
install -m 0644 -o root -g root "$HERE/jipite-android-update-sync.timer" \
  /etc/systemd/system/jipite-android-update-sync.timer
systemctl daemon-reload
# Run once before exposing the route. If the VPS cannot reach GitHub,
# leave the existing public Nginx config completely untouched.
if ! systemctl start jipite-android-update-sync.service; then
  echo "ABORT: initial release sync failed. See:" >&2
  echo "  sudo journalctl -u jipite-android-update-sync.service -n 40 --no-pager" >&2
  exit 4
fi
[[ -s "$ROOT/latest.json" ]] || {
  echo "ABORT: no verified update manifest was generated." >&2; exit 4;
}

echo "[3/4] Adding public read-only static download route (with rollback)..."
if [[ -L "$UPDATES_SNIPPET" ]]; then
  echo "ABORT: Nginx update snippet is a symlink" >&2
  exit 5
fi
if [[ -e "$UPDATES_SNIPPET" ]] && ! cmp -s "$UPDATES_SNIPPET" "$SRC_SNIPPET"; then
  echo "ABORT: existing VPS update snippet differs. Please review manually." >&2
  exit 5
fi
includes="$(grep -Fc "$INCLUDE" "$MOBILE_SNIPPET" || true)"
if [[ "$includes" -gt 1 ]]; then
  echo "ABORT: duplicate updates include in mobile Nginx snippet." >&2
  exit 5
fi
backup="$(mktemp /etc/nginx/snippets/.jipite-mobile-updates-backup.XXXXXX)"
cp -a "$MOBILE_SNIPPET" "$backup"
was_new=0
committed=0
rollback() {
  if [[ "$committed" -ne 1 ]]; then
    cp -a "$backup" "$MOBILE_SNIPPET"
    if [[ "$was_new" -eq 1 ]]; then rm -f "$UPDATES_SNIPPET"; fi
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
    echo "Nginx update route reverted; original mobile approval route preserved." >&2
  fi
}
trap rollback EXIT
if [[ ! -e "$UPDATES_SNIPPET" ]]; then
  install -o root -g root -m 0644 "$SRC_SNIPPET" "$UPDATES_SNIPPET"
  was_new=1
fi
if [[ "$includes" -eq 0 ]]; then
  printf '\n%s\n' "$INCLUDE" >> "$MOBILE_SNIPPET"
fi
nginx -t
systemctl reload nginx
committed=1
trap - EXIT

echo "[4/4] Enabling hourly mirroring and verifying HTTPS download access..."
systemctl enable --now jipite-android-update-sync.timer
http_code="$(curl --silent --show-error --max-time 12 --output /dev/null \
  --write-out '%{http_code}' https://jipite.borealos.cn/app-updates/latest.json)" || http_code=unreachable
echo "VPS APK mirror health: HTTP $http_code (expected 200)"
cat "$ROOT/latest.json"
echo
echo "Backup of original Nginx snippet: $backup"
echo "Hourly timer: $(systemctl is-active jipite-android-update-sync.timer)"
echo "Microsoft approval API, old TOTP fallback, and GPU controls were not altered."
if [[ "$http_code" != 200 ]]; then
  echo "WARNING: APK files synced locally, but public HTTPS route needs checking." >&2
fi
