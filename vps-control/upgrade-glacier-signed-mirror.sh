#!/usr/bin/env bash
# One-time upgrade of the ALREADY INSTALLED Glacier VPS mirror.
# Does not touch nginx, old preview URLs, user data, GPU or authentication.
set -Eeuo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"
[[ "${EUID}" -ne 0 ]] || { echo 'Run as normal VPS login user (uses sudo only for systemd).' >&2; exit 2; }
[[ -d .git ]] || { echo 'Existing Git checkout required.' >&2; exit 2; }
[[ "$(git branch --show-current)" == main ]] || { echo 'Expected main branch.' >&2; exit 2; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || {
  echo 'Tracked modifications detected: refusing to overwrite VPS changes.' >&2; exit 2;
}
[[ -d /var/lib/glacier-preview-downloads ]] || {
  echo 'Existing Glacier download directory missing; will not reconfigure nginx.' >&2; exit 2;
}
systemctl is-enabled --quiet glacier-signed-mirror.timer || {
  echo 'Existing signed mirror timer not installed; refusing to replace infrastructure.' >&2; exit 2;
}

echo 'Updating existing Glacier mirror code by fast-forward only...'
HTTPS_PROXY=http://127.0.0.1:1081 HTTP_PROXY=http://127.0.0.1:1081 git pull --ff-only
python3 -m unittest -v vps-control/test_glacier_signed_mirror.py
sudo install -o root -g root -m 0644 vps-control/glacier-signed-mirror.service /etc/systemd/system/glacier-signed-mirror.service
sudo install -o root -g root -m 0644 vps-control/glacier-signed-mirror.timer /etc/systemd/system/glacier-signed-mirror.timer
sudo systemctl daemon-reload
sudo systemctl enable --now glacier-signed-mirror.timer
echo 'Staging both immutable v0.20.10 installers (signed feed remains 0.20.9 until independently promoted)...'
sudo systemctl start glacier-signed-mirror.service

dir=/var/lib/glacier-preview-downloads
echo '8aeb73bcaf1a00e489c512a4c69152efda6141fc402365c7b3165cce02ef8be1  '${dir}'/GlacierBrowser-v0.20.10-Windows-Setup-x64.exe' | sha256sum -c -
echo '3d3175c051e2cbba4864b0fc17f4b5e5def6fdc57880f8b2294f228f392549b0  '${dir}'/GlacierBrowser-v0.20.10-macOS-AppleSilicon.dmg' | sha256sum -c -

curl --fail --silent --show-error --head --max-time 20   https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.10-Windows-Setup-x64.exe > /dev/null
curl --fail --silent --show-error --head --max-time 20   https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.10-macOS-AppleSilicon.dmg > /dev/null
echo 'SUCCESS: v0.20.10 paired release assets are mirrored and hash-verified. Nginx and signed feed unchanged.'
