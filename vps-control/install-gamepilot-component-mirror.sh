#!/usr/bin/env bash
# One-time 111 VPS setup for pre-cached GamePilot optional components.
# 111 downloads through its EXISTING loopback proxy, verifies original SHA256,
# and serves ONLY allowlisted immutable files via existing HTTPS vhost.
# Nothing here is a public HTTP proxy or a client-controlled URL fetcher.
set -Eeuo pipefail
umask 077

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
source_nginx="$repo/vps-control/nginx-gamepilot-components.conf"
host="/etc/nginx/snippets/glacier-preview-downloads.conf"
route="/etc/nginx/snippets/gamepilot-components.conf"
include_line="include /etc/nginx/snippets/gamepilot-components.conf;"
folder="/var/lib/glacier-preview-downloads/gamepilot-components"
proxy="http://127.0.0.1:1081"
base="https://sync.borealos.cn/downloads/gamepilot-components"
original=""
include_added=0
route_created=0
probe=""

refuse() { echo "GAMEPILOT VPS REFUSED: $*" >&2; exit 2; }
cleanup() {
  code=$?
  [[ -z "$probe" ]] || rm -f -- "$probe"
  if [[ "$code" != 0 && -n "$original" ]]; then
    echo "Reverting only GamePilot-components Nginx include; verified cache kept" >&2
    (( include_added == 0 )) || cp -p -- "$original" "$host" || true
    (( route_created == 0 )) || rm -f -- "$route" || true
    nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
  fi
}
trap cleanup EXIT

[[ "$(id -u)" == 0 ]] || refuse "Run sudo bash on your 111 Ubuntu VPS"
[[ -f "$source_nginx" && ! -L "$source_nginx" ]] || refuse "Reviewed source Nginx file missing"
[[ -f "$host" && ! -L "$host" ]] || refuse "Existing GamePilot HTTPS host snippet missing"
[[ -d /var/lib/glacier-preview-downloads &&
   ! -L /var/lib/glacier-preview-downloads ]] || refuse "Existing HTTPS downloads directory missing"
[[ -f /etc/nginx/snippets/gamepilot-dxmt-downloads.conf ]] ||
  refuse "Existing verified GamePilot DXMT mirror not installed"
grep -Fqx 'include /etc/nginx/snippets/gamepilot-dxmt-downloads.conf;' "$host" ||
  refuse "Existing DXMT include not found; no broad nginx changes"
[[ "$(git -c safe.directory="$repo" -C "$repo" branch --show-current)" == main ]] ||
  refuse "VPS repo must be on reviewed main"
command -v curl >/dev/null && command -v nginx >/dev/null &&
  command -v sha256sum >/dev/null && command -v stat >/dev/null ||
  refuse "Missing system tools"
nginx -t || refuse "Existing nginx -t failed"
timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/1081' 2>/dev/null ||
  refuse "111 loopback proxy 127.0.0.1:1081 is unavailable"
[[ ! -L "$route" ]] || refuse "Route is a symlink"
if [[ -e "$route" ]]; then
  cmp -s "$source_nginx" "$route" ||
    refuse "Existing route differs from reviewed source; won't overwrite"
fi
mkdir -p -- "$folder"
[[ -d "$folder" && ! -L "$folder" ]] || refuse "Bad component cache directory"
chmod 0755 "$folder"

fetch_via_111_proxy() {
  local url="$1" output="$2"
  # This HTTPS request goes through 111's local proxy; clients never contact
  # these upstream hosts. No proxy config/secrets are sent to macOS.
  curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --connect-timeout 20 --max-time 3600 --max-filesize 300000000 \
    --proto '=https' --proto-redir '=https' --proxy "$proxy" \
    --output "$output" "$url"
}
file_digest() { sha256sum "$1" | awk '{print $1}'; }
verify_sha() {
  local file="$1" expected="$2"
  [[ -f "$file" && ! -L "$file" ]] &&
    [[ "$(file_digest "$file")" == "$expected" ]]
}
mirror_pinned() {
  local name="$1" url="$2" digest="$3"
  local target="$folder/$name" tmp
  if verify_sha "$target" "$digest"; then
    echo "111 CACHE PASS: $name SHA256"
    return 0
  fi
  [[ ! -e "$target" && ! -L "$target" ]] ||
    refuse "Immutable component exists with bad checksum: $name"
  tmp="$(mktemp "$folder/.gamepilot-component.XXXXXXXX.tmp")"
  echo "111 proxy prefetch: $name"
  if ! fetch_via_111_proxy "$url" "$tmp"; then
    rm -f -- "$tmp"
    refuse "111 proxy could not prefetch $name; Mac must NOT fall back to foreign source"
  fi
  if ! verify_sha "$tmp" "$digest"; then
    rm -f -- "$tmp"
    refuse "Original SHA256 mismatch: $name"
  fi
  chmod 0644 "$tmp"
  mv -n -- "$tmp" "$target"
  [[ ! -e "$tmp" ]] || refuse "Collision while staging $name"
  verify_sha "$target" "$digest" || refuse "Post-stage SHA256 mismatch: $name"
  echo "111 STAGED PASS: $name SHA256"
}

gst_name="gstreamer-1.0-1.26.11-universal.pkg"
gst_upstream="https://gstreamer.freedesktop.org/data/pkg/osx/1.26.11"
gst_sum="$gst_name.sha256sum"
sum_target="$folder/$gst_sum"
sum_tmp=""
if [[ -f "$sum_target" && ! -L "$sum_target" ]]; then
  sum_tmp="$sum_target"
else
  [[ ! -e "$sum_target" && ! -L "$sum_target" ]] ||
    refuse "Existing checksum path is invalid"
  sum_tmp="$(mktemp "$folder/.gamepilot-checksum.XXXXXXXX.tmp")"
  fetch_via_111_proxy "$gst_upstream/$gst_sum" "$sum_tmp" ||
    refuse "Could not fetch original GStreamer checksum via 111 proxy"
fi
# Accept exactly one official checksum line for this exact fixed filename.
gst_sha="$(awk -v n="$gst_name" '
  NF==2 && $2==n && $1~/^[[:xdigit:]]+$/ && length($1)==64 {
    count++; digest=tolower($1)
  }
  END {if (NR==1 && count==1) print digest}
' "$sum_tmp")"
[[ "$gst_sha" =~ ^[a-f0-9]{64}$ ]] ||
  refuse "Official GStreamer checksum manifest is invalid"
if [[ "$sum_tmp" != "$sum_target" ]]; then
  chmod 0644 "$sum_tmp"
  mv -n -- "$sum_tmp" "$sum_target"
  [[ ! -e "$sum_tmp" ]] || refuse "GStreamer checksum destination collision"
fi
mirror_pinned "$gst_name" "$gst_upstream/$gst_name" "$gst_sha"

# These are immutable, already published official Release hashes, NOT
# mutable metadata provided by a client or by the local 111 mirror.
mirror_pinned "wine-devel-11.18-osx64.tar.xz" \
  "https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.18/wine-devel-11.18-osx64.tar.xz" \
  "aa0ea4c82e636ae7bca2076387cb0a5affa26509ad13f119ecd0d62bd7ba6f82"
mirror_pinned "gamepilot-wine1118-video-overlay.tar.gz" \
  "https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/gamepilot-wine-video-v0.1/gamepilot-wine1118-video-overlay.tar.gz" \
  "1f9ed57524069df115269c2d95bc4ce3f3cfcde6f3947a770ab61dbfe8eb1699"

original="$(mktemp "$host.components.XXXXXXXX.backup")"
cp -p -- "$host" "$original"
if [[ ! -e "$route" ]]; then
  install -o root -g root -m 0644 "$source_nginx" "$route"
  route_created=1
fi
if ! grep -Fqx "$include_line" "$host"; then
  next="$(mktemp "$host.components.XXXXXXXX.next")"
  cp -p -- "$host" "$next"
  printf '\n# Four verified immutable GamePilot component files; read-only HTTPS\n%s\n' \
    "$include_line" >> "$next"
  mv -f -- "$next" "$host"
  include_added=1
fi
nginx -t || refuse "GamePilot component Nginx include is invalid"
systemctl reload nginx || refuse "Nginx reload failed"

# Verify full public HTTPS bytes; no HEAD-only success claims.
for name in "$gst_sum" "$gst_name" "wine-devel-11.18-osx64.tar.xz" \
            "gamepilot-wine1118-video-overlay.tar.gz"; do
  local_target="$folder/$name"
  expected="$(file_digest "$local_target")"
  probe="$(mktemp)"
  ready=0
  for attempt in 1 2 3 4 5 6 7 8; do
    if curl --fail --silent --show-error --max-redirs 0 \
      --connect-timeout 10 --max-time 300 --noproxy '*' \
      --output "$probe" "$base/$name"; then
      ready=1
      break
    fi
    if [[ "$attempt" -lt 8 ]]; then sleep 1; fi
  done
  [[ "$ready" == 1 ]] || refuse "111 public HTTPS not ready for $name"
  [[ "$(stat -c %s "$probe")" == "$(stat -c %s "$local_target")" ]] ||
    refuse "111 public HTTPS size differs for $name"
  verify_sha "$probe" "$expected" || refuse "111 public HTTPS SHA256 differs for $name"
  echo "111 HTTPS PASS: $name ($(stat -c %s "$probe") bytes) SHA256"
  rm -f -- "$probe"
  probe=""
done
echo "PASS 111 has proxy-prefetched ALL GamePilot optional components; Mac downloads ONLY from 111."
echo "Original GamePilot signed update ZIP, DXMT routes, Glacier, and GPU unchanged."
echo "Nginx backup: $original"
