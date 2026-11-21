#!/usr/bin/env bash
# Enable GamePilot on the existing Glacier signed mirror after pulling reviewed main.
# Does not add any routes, services, root permissions, secrets, or signing keys.
set -Eeuo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
worker="$repo/vps-control/sync-glacier-signed-releases.py"
addon="$repo/vps-control/gamepilot_signed_mirror.py"
unit="glacier-signed-mirror.service"
folder="/var/lib/glacier-preview-downloads"

[[ "$(git -C "$repo" branch --show-current)" == "main" ]] || {
  echo "VPS checkout must be on main" >&2; exit 2;
}
[[ -f "$worker" && ! -L "$worker" && -f "$addon" && ! -L "$addon" ]] || {
  echo "Reviewed GamePilot mirror source missing" >&2; exit 2;
}
grep -Fq 'from gamepilot_signed_mirror import sync as sync_gamepilot' "$worker" || {
  echo "Installed Glacier worker does not call isolated GamePilot mirror" >&2; exit 2;
}
[[ -d "$folder" && ! -L "$folder" ]] || {
  echo "Existing VPS download directory absent or symlinked" >&2; exit 2;
}
[[ "$(systemctl show -p LoadState --value "$unit")" == "loaded" ]] || {
  echo "Existing signed mirror unit is not installed" >&2; exit 2;
}
systemctl cat "$unit" | grep -Fq "$worker" || {
  echo "Existing mirror unit uses another executable" >&2; exit 2;
}
case "$(systemctl show -p NoNewPrivileges --value "$unit")" in
  yes|true|1) ;;
  *) echo "Existing mirror NoNewPrivileges guard is unexpectedly off" >&2; exit 2 ;;
esac
systemctl is-active --quiet glacier-signed-mirror.timer || {
  echo "Existing 30-minute signed mirror timer is inactive" >&2; exit 2;
}

python3 -m py_compile "$worker" "$addon"
(cd "$repo/vps-control" && python3 -m unittest -v test_gamepilot_signed_mirror.py)

# Existing audited unit reads the updated checkout. It will also refresh the
# two unchanged Glacier signed channels. The GamePilot path is optional and
# catches its own failure to preserve Glacier availability.
sudo systemctl start "$unit"

# v0.4.1's official signed appcast still references GitHub: its ZIP may be
# staged, but ONLY a later, VPS-origin signed appcast is made public here.
# The current published version may advance while GitHub Actions and this
# VPS activation run. Check what the verified mirror actually staged.
mapfile -t packages < <(
  find "$folder" -maxdepth 1 -type f -name 'GamePilot-mac-arm64-v*.zip' -printf '%f\\n' | sort
)
[[ "${#packages[@]}" -gt 0 ]] || {
  echo "No verified GamePilot ZIP is staged yet; inspect the mirror unit log" >&2; exit 3;
}
for filename in "${packages[@]}"; do
  curl --fail --silent --show-error --location --head \\
    --connect-timeout 8 --max-time 20 \\
    "https://sync.borealos.cn/downloads/$filename" >/dev/null || {
      echo "VPS HTTPS file route not ready for $filename" >&2; exit 3;
    }
  echo "Confirmed HTTPS serving $filename"
done
echo "PASS: permanent, separately verified GamePilot ZIP mirroring enabled."
echo "Glacier channels, existing OIDC receiver and systemd units unchanged."
echo "A v0.4.2 signed VPS feed is required before GamePilot auto-update is usable."
