#!/usr/bin/env bash
# One-time owner-executed, no-signing, read-only HTTPS mirror activation.
# Downloads THREE immutable FOSS WineCX/DXMT assets over existing local VPS
# proxy, verifies full upstream SHA256, and adds exact-match Nginx paths.
# Existing Glacier / GamePilot appcast / GPU / auth routes stay unchanged.
set -Eeuo pipefail
umask 077

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
src="$repo/vps-control/nginx-gamepilot-dxmt-downloads.conf"
host="/etc/nginx/snippets/glacier-preview-downloads.conf"
route="/etc/nginx/snippets/gamepilot-dxmt-downloads.conf"
include_line="include /etc/nginx/snippets/gamepilot-dxmt-downloads.conf;"
base="/var/lib/glacier-preview-downloads"
dest="$base/gamepilot-dxmt"
proxy="http://127.0.0.1:1081"
public="https://sync.borealos.cn/downloads/gamepilot-dxmt"
backup=""
added=0
created=0
probe=""

fail() { echo "REFUSED: $*" >&2; exit 3; }
on_exit() {
  code=$?
  [[ -z "$probe" ]] || rm -f -- "$probe"
  if [[ "$code" -ne 0 && -n "$backup" ]]; then
    trap - EXIT
    echo "Rolling back ONLY the GamePilot DXMT Nginx route (verified files remain cached)" >&2
    if [[ "$added" -eq 1 ]]; then cp -p -- "$backup" "$host" || true; fi
    if [[ "$created" -eq 1 ]]; then rm -f -- "$route" || true; fi
    if nginx -t >/dev/null 2>&1; then systemctl reload nginx || true; fi
    echo "Nginx original preserved at: $backup" >&2
  fi
}
trap on_exit EXIT
[[ "$(id -u)" -eq 0 ]] || fail "Run as sudo bash on owner Ubuntu VPS"
[[ -f "$src" && ! -L "$src" ]] || fail "Reviewed source snippet missing"
[[ -f "$host" && ! -L "$host" ]] || fail "Existing HTTPS Nginx snippet unavailable"
[[ -d "$base" && ! -L "$base" ]] || fail "Existing signed downloads directory unavailable"
[[ -f /etc/nginx/snippets/gamepilot-downloads.conf ]] || fail "GamePilot signed download route not installed"
grep -Fqx "include /etc/nginx/snippets/gamepilot-downloads.conf;" "$host" ||
  fail "Expected existing GamePilot include missing"
grep -Fq 'GlacierBrowser-' "$host" || fail "Expected Glacier routes missing"
branch="$(git -c safe.directory="$repo" -C "$repo" branch --show-current)"
[[ "$branch" == "main" ]] || fail "Reviewed VPS repo must be on main, got $branch"
command -v nginx >/dev/null && command -v sha256sum >/dev/null || fail "Missing Nginx / SHA256 tools"
nginx -t || fail "Existing Nginx config invalid; refusing change"
[[ ! -L "$route" ]] || fail "Route snippet is a symlink"
if [[ -e "$route" ]]; then
  cmp -s -- "$src" "$route" || fail "Existing DXMT route differs from reviewed source; no overwrite"
fi
mkdir -p -- "$dest"
[[ -d "$dest" && ! -L "$dest" ]] || fail "Invalid DXMT mirror destination"
chmod 0755 "$dest"
# Never download through public internet as an open proxy service; outbound
# HTTPS is made only by the Ubuntu owner through existing loopback proxy.
# Preflight is intentionally a local loopback connection, not a public port.
timeout 3 bash -c 'exec 3<>/dev/tcp/127.0.0.1/1081' 2>/dev/null ||
  fail "111's existing HTTP proxy 127.0.0.1:1081 is not responding"

valid() {
  file="$1" bytes="$2" digest="$3"
  [[ -f "$file" && ! -L "$file" ]] || return 1
  [[ "$(stat -c %s "$file")" == "$bytes" ]] || return 1
  [[ "$(sha256sum "$file" | awk '{print $1}')" == "$digest" ]]
}
mirror_one() {
  name="$1" upstream="$2" bytes="$3" digest="$4"
  target="$dest/$name"
  if valid "$target" "$bytes" "$digest"; then
    echo "CACHE PASS: $name ($bytes bytes) SHA256"
    return
  fi
  [[ ! -e "$target" && ! -L "$target" ]] ||
    fail "Existing $name does not match pinned digest; refuse unsafe overwrite"
  temp="$(mktemp "$dest/.gamepilot-dxmt.XXXXXXXX.tmp")"
  echo "Proxy download: $name ($bytes bytes)"
  if ! curl --fail --location --silent --show-error \
      --retry 4 --retry-delay 2 --connect-timeout 15 --max-time 1800 \
      --proto '=https' --proto-redir '=https' --proxy "$proxy" \
      --output "$temp" "$upstream"; then
    rm -f -- "$temp"
    fail "Cannot fetch $name via local owner VPS proxy"
  fi
  if ! valid "$temp" "$bytes" "$digest"; then
    rm -f -- "$temp"
    fail "SHA256 or byte-size mismatch for $name; rejecting downloaded bytes"
  fi
  chmod 0644 "$temp"
  mv -n -- "$temp" "$target"
  [[ ! -e "$temp" ]] || fail "Destination collision for $name"
  valid "$target" "$bytes" "$digest" || fail "Post-stage checksum mismatch for $name"
  echo "STAGED PASS: $name SHA256"
}

# Immutable upstream URLs and GitHub Release API SHA256 digests were verified
# in the original GamePilot Mac integration. No caller-supplied URL or names.
while IFS='|' read -r name upstream bytes digest; do
  [[ -n "$name" ]] || continue
  mirror_one "$name" "$upstream" "$bytes" "$digest"
done <<'ASSETS'
winecx-24.0.7_7.tar.xz|https://github.com/Sikarugir-App/Engines/releases/download/v1.0/WS12WineCX24.0.7_7.tar.xz|172348356|203f9e9fd6c2cc77e6525d798a434ced326145db34a356355e05659d3445fd1c
dxmt-0.74-builtin.tar.gz|https://github.com/3Shain/dxmt/releases/download/v0.74/dxmt-v0.74-builtin.tar.gz|18990005|2598981a8b725653773e277470a95dda4253b8a14d36e0dc96dce0e3800f0ceb
wine-stable-11.0_1-libs.tar.xz|https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.0_1/wine-stable-11.0_1-osx64.tar.xz|185303032|b50dc50ec7f41d58b115a6b685d4d1315ba3c797bd3aa0f49213f2703cb82388
ASSETS

# Only after all three files have been fully verified may the exact Nginx
# read-only routes be activated. Changes are backed up and reverted on errors.
backup="$(mktemp "$host.dxmt.XXXXXXXX.backup")"
cp -p -- "$host" "$backup"
if [[ ! -e "$route" ]]; then
  install -o root -g root -m 0644 "$src" "$route"
  created=1
fi
if ! grep -Fqx "$include_line" "$host"; then
  candidate="$(mktemp "$host.dxmt.XXXXXXXX.next")"
  cp -p -- "$host" "$candidate"
  printf '\n# Three fixed pinned GamePilot FOSS DXMT files, read-only\n%s\n' \
    "$include_line" >> "$candidate"
  mv -f -- "$candidate" "$host"
  added=1
fi
nginx -t || fail "Nginx rejected DXMT isolated locations"
systemctl reload nginx || fail "Nginx reload failed"

# Work around old Nginx workers briefly serving the prior /downloads/ 404.
# Hash the actual public HTTPS bytes, not merely the local staged file.
while IFS='|' read -r name bytes digest; do
  [[ -n "$name" ]] || continue
  probe="$(mktemp)"
  ready=0
  for attempt in 1 2 3 4 5 6 7 8; do
    if curl --fail --silent --show-error --max-redirs 0 \
        --connect-timeout 10 --max-time 240 --noproxy '*' \
        --output "$probe" "$public/$name"; then
      ready=1
      break
    fi
    if [[ "$attempt" -lt 8 ]]; then sleep 1; fi
  done
  [[ "$ready" == 1 ]] || fail "VPS public HTTPS not serving $name after bounded retry"
  valid "$probe" "$bytes" "$digest" || fail "VPS public HTTPS SHA256 mismatch for $name"
  rm -f -- "$probe"
  probe=""
  echo "HTTPS PASS: $name ($bytes bytes) SHA256"
done <<'CHECKS'
winecx-24.0.7_7.tar.xz|172348356|203f9e9fd6c2cc77e6525d798a434ced326145db34a356355e05659d3445fd1c
dxmt-0.74-builtin.tar.gz|18990005|2598981a8b725653773e277470a95dda4253b8a14d36e0dc96dce0e3800f0ceb
wine-stable-11.0_1-libs.tar.xz|185303032|b50dc50ec7f41d58b115a6b685d4d1315ba3c797bd3aa0f49213f2703cb82388
CHECKS
echo "PASS: Three immutable FOSS DXMT assets available via existing owner VPS HTTPS, every byte SHA256 checked."
echo "PASS: Original GamePilot signed appcast, Glacier routes and all VPS authorization unchanged."
echo "Nginx backup: $backup"
