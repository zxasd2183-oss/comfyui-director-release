#!/usr/bin/env bash
# One-time VPS mirror setup for Glacier Mac updates; does not touch Jipite approval APIs.
# Review before running on user's own jipite.borealos.cn VPS.
set -euo pipefail
umask 027
[[ "${EUID}" -eq 0 ]] || { echo "Run as sudo on the VPS" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="/var/lib/glacier-macos-updates"
CODE="/opt/glacier-macos-updates"
MOBILE="/etc/nginx/snippets/jipite-mobile.conf"
SNIPPET="/etc/nginx/snippets/glacier-macos-updates.conf"
SOURCE="$HERE/nginx-alidns/glacier-macos-updates.conf"
INCLUDE="include $SNIPPET;"

for command in nginx systemctl python3 curl cmp; do
  command -v "$command" >/dev/null
done
echo "[1/4] Preflight: verify active Nginx and existing Jipite mobile routes"
nginx -t
[[ -f "$MOBILE" && ! -L "$MOBILE" ]] || {
  echo "Original Jipite mobile snippet missing: aborting" >&2; exit 3;
}
grep -Fq 'location ^~ /api/v1/mobile/' "$MOBILE" || {
  echo "Original Jipite mobile API route missing: aborting" >&2; exit 3;
}
[[ -f "$SOURCE" && ! -L "$SOURCE" ]] || {
  echo "Glacier Nginx snippet missing or symlinked: aborting" >&2; exit 3;
}
[[ ! -L "$SNIPPET" ]] || {
  echo "Refusing to replace a symlinked Nginx snippet" >&2; exit 3;
}
if [[ -f "$SNIPPET" ]] && ! cmp -s "$SNIPPET" "$SOURCE"; then
  echo "Existing Glacier snippet differs; review it before installation" >&2; exit 3;
fi
includes="$(grep -Fc "$INCLUDE" "$MOBILE" || true)"
[[ "$includes" -le 1 ]] || { echo "Duplicate Glacier include, aborting" >&2; exit 3; }

echo "[2/4] Create separate read-only download account and timer"
if ! id -u glacierupdate >/dev/null 2>&1; then
  useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin glacierupdate
fi
install -d -m 0755 -o glacierupdate -g glacierupdate "$ROOT"
install -d -m 0755 -o root -g root "$CODE"
install -m 0644 -o root -g root "$HERE/sync-glacier-macos-updates.py" "$CODE/sync-glacier-macos-updates.py"
if [[ ! -x "$CODE/venv/bin/python" ]]; then
  python3 -m venv --system-site-packages "$CODE/venv"
fi
if ! "$CODE/venv/bin/python" -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey" 2>/dev/null; then
  "$CODE/venv/bin/python" -m pip install --only-binary=:all: 'cryptography>=43,<47'
fi
install -m 0644 -o root -g root "$HERE/glacier-macos-update-sync.service" \
  /etc/systemd/system/glacier-macos-update-sync.service
install -m 0644 -o root -g root "$HERE/glacier-macos-update-sync.timer" \
  /etc/systemd/system/glacier-macos-update-sync.timer
systemctl daemon-reload
# Fail closed if the VPS cannot download and verify the signed release.
if ! systemctl start glacier-macos-update-sync.service; then
  echo "Initial authenticated DMG sync failed; Nginx stays unchanged." >&2
  echo "Inspect: sudo journalctl -u glacier-macos-update-sync.service -n 40 --no-pager" >&2
  exit 4
fi
[[ -s "$ROOT/macos-arm64.json" ]] || {
  echo "No signed release manifest available; Nginx remains unchanged" >&2; exit 4;
}
shopt -s nullglob
dmgs=("$ROOT"/GlacierBrowser-v*-macOS-AppleSilicon.dmg)
[[ "${#dmgs[@]}" -gt 0 ]] || {
  echo "No authenticated DMG available; Nginx remains unchanged" >&2; exit 4;
}

echo "[3/4] Add an isolated static /glacier-updates/ route with rollback"
backup="$(mktemp /etc/nginx/snippets/.glacier-mobile-backup.XXXXXX)"
cp -a "$MOBILE" "$backup"
snippet_created=0
committed=0
rollback() {
  if [[ "$committed" -ne 1 ]]; then
    cp -a "$backup" "$MOBILE"
    if [[ "$snippet_created" -eq 1 ]]; then rm -f "$SNIPPET"; fi
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
    echo "Nginx rollback performed; existing Jipite routes preserved" >&2
  fi
}
trap rollback EXIT
if [[ ! -e "$SNIPPET" ]]; then
  install -m 0644 -o root -g root "$SOURCE" "$SNIPPET"
  snippet_created=1
fi
if [[ "$includes" -eq 0 ]]; then
  printf '\n%s\n' "$INCLUDE" >> "$MOBILE"
fi
nginx -t
systemctl reload nginx
committed=1
trap - EXIT

echo "[4/4] Enable twice-hourly VPS mirroring and check HTTPS endpoint"
systemctl enable --now glacier-macos-update-sync.timer
code="$(curl --silent --show-error --max-time 18 -o /dev/null -w '%{http_code}' \
  'https://jipite.borealos.cn/glacier-updates/macos-arm64.json')" || code=unreachable
echo "VPS signed Mac feed HTTPS: $code (expected HTTP 200)"
echo "Mac download URL base: https://jipite.borealos.cn/glacier-updates/"
echo "Nginx backup: $backup"
echo "Timer: $(systemctl is-active glacier-macos-update-sync.timer)"
echo "Jipite approval, Android updater, GPU control and Microsoft secrets unchanged"
if [[ "$code" != 200 ]]; then
  echo "WARNING: nginx route must be checked externally before releasing Mac updates" >&2
fi
