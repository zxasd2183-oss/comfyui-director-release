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
echo 'Refreshing the existing signed mirror from uncached GitHub v2 feeds...'
if ! sudo systemctl start glacier-signed-mirror.service; then
  sudo journalctl -u glacier-signed-mirror.service -n 35 --no-pager
  echo 'Glacier signed mirror failed; existing signed files remain untouched.' >&2
  exit 2
fi

dir=/var/lib/glacier-preview-downloads
echo '089985713c0f16148d3ce17db00310b837072b8ed69435205a18428874cecfc8  '${dir}'/GlacierBrowser-v0.20.11-Windows-Setup-x64.exe' | sha256sum -c -
echo 'e681b86246084e813b735229369f2baed950414fe2b4a0c2953ab4a89dd44584  '${dir}'/GlacierBrowser-v0.20.11-macOS-AppleSilicon.dmg' | sha256sum -c -

python3 - <<'PY'
import importlib.util
import json
from pathlib import Path
root=Path("vps-control/sync-glacier-signed-releases.py")
spec=importlib.util.spec_from_file_location("glacier_signed_mirror",root)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
files=Path("/var/lib/glacier-preview-downloads")
for channel in ("windows-x64","macos-arm64"):
    doc=json.loads((files/(channel+".json")).read_text(encoding="utf-8"))
    module.verify(doc,channel)  # Pinned key verifies unchanged Ed25519 signature
    if doc["version"]!="0.20.11":
        raise RuntimeError(channel+" signed feed still at "+doc["version"])
    print(channel+": v0.20.11 pinned signature verified; "+doc["url"])
PY
for file in GlacierBrowser-v0.20.11-Windows-Setup-x64.exe GlacierBrowser-v0.20.11-macOS-AppleSilicon.dmg; do
  curl --fail --silent --show-error --head --max-time 20 "https://sync.borealos.cn/downloads/$file" > /dev/null
done
echo 'SUCCESS: v0.20.11 paired installers and signed feeds verified on existing VPS. No Nginx or preview changes.'
