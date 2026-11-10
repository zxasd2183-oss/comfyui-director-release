#!/usr/bin/env bash
# Persist the signed-mirror sudo compatibility fix across base-unit redeploys.
# Only the existing Glacier OIDC receiver is restarted; do not touch GPU, Nginx,
# signing keys, legacy preview jobs, or the signed mirror service sandbox.
set -Eeuo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit="glacier-preview-notify.service"
target_dir="/etc/systemd/system/${unit}.d"
target="${target_dir}/10-signed-mirror-sudo.conf"
source="${repo}/vps-control/glacier-preview-notify.service.d/10-signed-mirror-sudo.conf"
expected_sudoers="${repo}/vps-control/glacier-signed-mirror-notify.sudoers"
installed_sudoers="/etc/sudoers.d/glacier-signed-mirror-notify"

[[ "${EUID}" -ne 0 ]] || { echo "Run as the normal sudo-enabled VPS operator, not root" >&2; exit 2; }
[[ -f "${source}" && -f "${expected_sudoers}" ]] || { echo "Missing repo-owned Glacier service files" >&2; exit 2; }
[[ "$(systemctl show --property=LoadState --value "${unit}")" == "loaded" ]] || {
  echo "Glacier notification receiver unit is not installed" >&2; exit 2;
}
[[ "$(systemctl show --property=User --value "${unit}")" == "glacierpreview" ]] || {
  echo "Unexpected OIDC receiver service user; refusing privilege change" >&2; exit 2;
}
systemctl is-active --quiet "${unit}" || { echo "OIDC receiver is not active" >&2; exit 2; }
[[ "$(systemctl show --property=LoadState --value glacier-signed-mirror.service)" == "loaded" ]] || {
  echo "Signed mirror service not installed" >&2; exit 2;
}
sudo test -f "${installed_sudoers}" || { echo "Exact signed-mirror sudoers policy missing" >&2; exit 2; }
sudo visudo -cf "${installed_sudoers}" >/dev/null
sudo cmp -s "${expected_sudoers}" "${installed_sudoers}" || {
  echo "Installed sudoers differs from the reviewed, one-command allowlist" >&2; exit 2;
}

sudo install -d -o root -g root -m 0755 "${target_dir}"
if sudo test -f "${target}" && ! sudo cmp -s "${source}" "${target}"; then
  suffix="$(date -u +%Y%m%dT%H%M%SZ)"
  sudo cp -p "${target}" "${target}.bak-${suffix}"
fi
sudo install -o root -g root -m 0644 "${source}" "${target}"
sudo systemctl daemon-reload
sudo systemctl restart "${unit}"

systemctl is-active --quiet "${unit}" || { echo "Glacier receiver did not restart" >&2; exit 2; }
actual="$(systemctl show --property=NoNewPrivileges --value "${unit}")"
case "${actual}" in
  no|false|0) ;;
  *) echo "Receiver sandbox still prevents sudo: NoNewPrivileges=${actual}" >&2; exit 2 ;;
esac
echo "Glacier OIDC receiver active with scoped signed-mirror sudo compatibility."
echo "Mirror's own NoNewPrivileges=true remains unchanged; OIDC end-to-end still needs a real GitHub event."
