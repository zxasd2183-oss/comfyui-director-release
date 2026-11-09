#!/usr/bin/env bash
# VPS 111: add read-only browser installer mirror to existing sync.borealos.cn
# Does not edit the six TLS vhosts or replace the Glacier account API.
set -Eeuo pipefail
[ "${EUID}" -eq 0 ] || { echo "Run via sudo" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=/var/lib/glacier-preview-downloads
CODE=/opt/glacier-preview-downloads
EXISTING=/etc/nginx/snippets/glacier-sync.conf
SNIPPET=/etc/nginx/snippets/glacier-preview-downloads.conf
SOURCE="$HERE/nginx-alidns/glacier-preview-downloads.conf"
INCLUDE="include $SNIPPET;"
for cmd in nginx python3 curl systemctl; do command -v "$cmd" >/dev/null; done
[ -f "$EXISTING" ] && [ ! -L "$EXISTING" ] || {
  echo "Missing expected Glacier Sync API snippet. Refusing deploy." >&2; exit 2;
}
grep -Fq '127.0.0.1:18991' "$EXISTING" || {
  echo "Glacier account API upstream absent; refusing deploy." >&2; exit 2;
}
[ -f "$SOURCE" ] && [ ! -L "$SOURCE" ] || exit 2
[ ! -L "$SNIPPET" ] || exit 2
if [ -f "$SNIPPET" ] && ! cmp -s "$SNIPPET" "$SOURCE"; then
  echo "An existing mirror snippet differs. Refusing overwrite." >&2; exit 2;
fi
nginx -t
if ! id glacierpreview >/dev/null 2>&1; then
  useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin glacierpreview
fi
install -d -m 0755 -o glacierpreview -g glacierpreview "$ROOT"
install -d -m 0755 -o root -g root "$CODE"
install -m 0644 "$HERE/sync-glacier-preview-releases.py" "$CODE/sync-glacier-preview-releases.py"
for kind in service timer; do
  install -m 0644 "$HERE/glacier-preview-update-sync.$kind" \
    "/etc/systemd/system/glacier-preview-update-sync.$kind"
done
systemctl daemon-reload

# No routing changes until BOTH real asset binaries have been downloaded,
# SHA256 checked against their immutable release sidecars and indexed.
systemctl start glacier-preview-update-sync.service
for platform in windows macos-arm64; do
  test -s "$ROOT/$platform-preview.json" || {
    echo "Missing verified $platform preview; no Nginx changes made." >&2; exit 3;
  }
done

if [ ! -e "$SNIPPET" ]; then
  install -m 0644 "$SOURCE" "$SNIPPET"
fi
if ! grep -Fq "$INCLUDE" "$EXISTING"; then
  backup="$EXISTING.glacier-preview.$(date +%Y%m%d%H%M%S)"
  cp -p "$EXISTING" "$backup"
  printf '\n%s\n' "$INCLUDE" >> "$EXISTING"
  if ! nginx -t; then
    cp -p "$backup" "$EXISTING"
    nginx -t || true
    echo "Nginx failed validation; account API snippet restored." >&2
    exit 4
  fi
  systemctl reload nginx
fi
systemctl enable --now glacier-preview-update-sync.timer
echo "Glacier VPS preview mirroring installed; signed formal updater untouched."
for platform in windows macos-arm64; do
  if curl --fail --silent --show-error --max-time 15 \
      "https://sync.borealos.cn/downloads/$platform-preview.json" | grep -q '"preview-manual"'; then
    echo "VPS HTTPS $platform preview manifest: OK"
  else
    echo "WARNING: $platform mirror HTTPS not confirmed" >&2
    exit 5
  fi
done
echo "Account health endpoint must remain reachable at https://sync.borealos.cn/health"
