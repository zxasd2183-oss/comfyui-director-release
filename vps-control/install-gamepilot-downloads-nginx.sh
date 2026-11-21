#!/usr/bin/env bash
# One-time *authorized* Nginx change for GamePilot's two READ-ONLY paths.
# Existing Glacier route/certs/worker/config lines remain unchanged.
# Runs on the OWNER'S VPS as root; no SSH execution is implied by this file.
set -Eeuo pipefail
umask 077

repo="/home/ubuntu/comfyui-director-release"
host_snippet="/etc/nginx/snippets/glacier-preview-downloads.conf"
gp_snippet="/etc/nginx/snippets/gamepilot-downloads.conf"
gp_source="$repo/vps-control/nginx-gamepilot-downloads.conf"
directory="/var/lib/glacier-preview-downloads"
zip="GamePilot-mac-arm64-v0.4.2.zip"
canonical_sha256="7807d927bef6c8f7e343cdcf5ed86eeabfdbf9b95ebe57c1362e0a54e4e1da6c"
canonical_size="2674810"
include_line='include /etc/nginx/snippets/gamepilot-downloads.conf;'
url="https://sync.borealos.cn/downloads/$zip"

die() { echo "REFUSED: $*" >&2; exit 2; }
[[ "$(id -u)" -eq 0 ]] || die "Use sudo bash on the Ubuntu VPS; do not run on your Mac."
[[ "$(git -C "$repo" branch --show-current)" == main ]] || die "VPS checkout is not on reviewed main."
[[ -f "$host_snippet" && ! -L "$host_snippet" ]] || die "Existing Nginx snippet not a regular file."
[[ -f "$gp_source" && ! -L "$gp_source" ]] || die "Reviewed GamePilot Nginx fragment missing."
[[ -d "$directory" && ! -L "$directory" ]] || die "Existing mirror directory missing or symlinked."
[[ -f "$directory/$zip" && ! -L "$directory/$zip" ]] || die "Canonical GamePilot ZIP not staged."
[[ "$(stat -c %s "$directory/$zip")" == "$canonical_size" ]] || die "Wrong canonical GamePilot ZIP size."
echo "$canonical_sha256  $directory/$zip" | sha256sum --check --status ||
  die "GamePilot ZIP differs from immutable GitHub Release."

# Do not guess at a new public virtual host. This script ONLY extends
# the previously inspected snippet in the already-enabled HTTPS vhost.
grep -Fq '/downloads/macos-arm64.json' "$host_snippet" ||
  die "This does not appear to be the known Glacier downloads snippet."
grep -Fq 'GlacierBrowser-' "$host_snippet" ||
  die "Expected existing Glacier downloads route not found."
nginx -t || die "Existing Nginx config does not pass validation."
nginx_dump="$(nginx -T 2>&1)"
[[ "$nginx_dump" == *"# configuration file $host_snippet:"* ]] ||
  die "Target snippet is not loaded in the active Nginx configuration."
unset nginx_dump

# Idempotent and fail closed if anyone changed the isolated fragment.
if [[ -L "$gp_snippet" ]]; then
  die "GamePilot route fragment is unexpectedly a symlink."
elif [[ -e "$gp_snippet" ]]; then
  cmp -s "$gp_source" "$gp_snippet" ||
    die "GamePilot route fragment already exists but differs from reviewed source."
fi

backup="$(mktemp "$host_snippet.gamepilot.XXXXXXXX.backup")"
cp -p -- "$host_snippet" "$backup"
created=0
modified=0
probe=""
rollback() {
  local reason="$1"
  trap - ERR
  echo "ERROR: $reason — reverting ONLY GamePilot Nginx changes" >&2
  if [[ "$modified" == 1 ]]; then
    cp -p -- "$backup" "$host_snippet" || true
  fi
  if [[ "$created" == 1 ]]; then
    rm -f -- "$gp_snippet" || true
  fi
  if nginx -t; then
    systemctl reload nginx || true
  fi
  echo "Backup retained at $backup" >&2
  exit 3
}
trap 'rollback "Command failed near line $LINENO"' ERR
trap '[[ -z "$probe" ]] || rm -f -- "$probe"' EXIT

if [[ ! -e "$gp_snippet" ]]; then
  install -o root -g root -m 0644 "$gp_source" "$gp_snippet"
  created=1
fi
if ! grep -Fqx "$include_line" "$host_snippet"; then
  # Preserve existing file ownership and permissions; edit via atomic rename.
  candidate="$(mktemp "$host_snippet.gamepilot.XXXXXXXX.next")"
  cp -p -- "$host_snippet" "$candidate"
  {
    printf '\n# GamePilot Mac read-only Ed25519-signed downloads (isolated)\n'
    printf '%s\n' "$include_line"
  } >> "$candidate"
  mv -f -- "$candidate" "$host_snippet"
  modified=1
fi

if ! nginx -t; then rollback "nginx -t failed"; fi
if ! systemctl reload nginx; then rollback "Nginx reload failed"; fi

# Prove the actual public-facing HTTPS route serves original release bytes.
probe="$(mktemp)"
if ! curl --fail --silent --show-error --max-redirs 0 \
      --connect-timeout 10 --max-time 90 --output "$probe" "$url"; then
  rollback "GamePilot public ZIP route is not HTTP 200"
fi
if [[ "$(stat -c %s "$probe")" != "$canonical_size" ]] ||
   [[ "$(sha256sum "$probe" | awk '{print $1}')" != "$canonical_sha256" ]]; then
  rollback "GamePilot HTTPS ZIP content failed SHA-256 validation"
fi
echo "PASS: GamePilot ZIP HTTPS served all $canonical_size bytes; SHA-256 matched."
echo "PASS: nginx -t and nginx reload succeeded. Existing Glacier rules untouched."
echo "GamePilot signed appcast will be published by GitHub Actions, never signed on VPS."
echo "Nginx original backup: $backup"
