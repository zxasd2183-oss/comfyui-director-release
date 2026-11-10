#!/usr/bin/env bash
# One-time repair for a missing Glacier Browser v0.20.15 signed-release VPS staging.
# Run on the existing owner VPS as its normal sudo-enabled login user.
# Does NOT modify signed feed JSON, Nginx, OIDC, GPU power, or other services.
set -Eeuo pipefail

repo=/home/ubuntu/comfyui-director-release
directory=/var/lib/glacier-preview-downloads
win="GlacierBrowser-v0.20.15-Windows-Setup-x64.exe"
mac="GlacierBrowser-v0.20.15-macOS-AppleSilicon.dmg"
win_size=175906134
mac_size=285877568
win_sha=5ce607e5600e8c24ca0c11ef12533d2ed101b792bb42621672e804da8a9e81e3
mac_sha=6a080df34b6d8852ed7c2d17a4e6fde913a3475c2675689fd58e43a2d388056d

[[ "${EUID}" -ne 0 ]] || { echo "Run as the normal VPS login user, not root" >&2; exit 2; }
[[ -d "${repo}/.git" ]] || { echo "Existing VPS repository checkout missing" >&2; exit 2; }
[[ -d "${directory}" && ! -L "${directory}" ]] || { echo "Existing mirror directory unavailable" >&2; exit 2; }
cd "${repo}"
[[ "$(git branch --show-current)" == main ]] || { echo "VPS checkout is not main" >&2; exit 2; }
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "VPS checkout has uncommitted tracked edits; refusing pull" >&2; exit 2; }
systemctl cat glacier-signed-mirror.service >/dev/null
systemctl is-enabled --quiet glacier-signed-mirror.timer || { echo "Signed mirror timer not enabled" >&2; exit 2; }

# Keep to the existing VPS's configured local network proxy. Fail closed if unavailable.
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:1081}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:1081}"
git pull --ff-only

python3 -m unittest -v vps-control/test_glacier_signed_mirror.py

echo "Starting installed signed mirror oneshot (may download both release assets)..."
if ! sudo systemctl start glacier-signed-mirror.service; then
    sudo journalctl -u glacier-signed-mirror.service -n 40 --no-pager
    echo "Signed mirror service failed; old signed channels left intact" >&2
    exit 2
fi

# The service can defer pre-staging while still successfully syncing the old feed.
# Hence these explicit immutable release-hash checks are mandatory.
for file in "${win}" "${mac}"; do
    [[ -f "${directory}/${file}" && ! -L "${directory}/${file}" ]] || {
        echo "Missing staged v0.20.15 file: ${file}" >&2
        sudo journalctl -u glacier-signed-mirror.service -n 45 --no-pager
        exit 2
    }
done
[[ "$(stat -c '%s' "${directory}/${win}")" == "${win_size}" ]]
[[ "$(stat -c '%s' "${directory}/${mac}")" == "${mac_size}" ]]
printf '%s  %s\n' "${win_sha}" "${directory}/${win}" "${mac_sha}" "${directory}/${mac}" | sha256sum -c -

python3 - <<'PY'
import importlib.util
import json
from pathlib import Path

module_path = Path("vps-control/sync-glacier-signed-releases.py")
spec = importlib.util.spec_from_file_location("glacier_signed_mirror", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
directory = Path("/var/lib/glacier-preview-downloads")
for channel in ("windows-x64", "macos-arm64"):
    doc = json.loads((directory / (channel + ".json")).read_text(encoding="utf-8"))
    module.verify(doc, channel)
    if module.semver(doc["version"]) < (0, 20, 12):
        raise RuntimeError(channel + ": signed feed unexpectedly old")
    print(channel, "existing Ed25519 signed feed verified: v" + doc["version"])
PY

for file in "${win}" "${mac}"; do
    code="$(curl --silent --show-error --head --output /dev/null --write-out '%{http_code}' --max-time 30 "https://sync.borealos.cn/downloads/${file}" || true)"
    [[ "${code}" == 200 || "${code}" == 206 ]] || { echo "Public HTTPS mirror not ready for ${file}: HTTP ${code}" >&2; exit 2; }
    echo "Public HTTPS staging ready: ${file} HTTP ${code}"
done

echo "SUCCESS: paired v0.20.15 installers mirrored, exact sizes and canonical GitHub Release SHA-256 verified."
echo "Signed channel JSON was not changed; GitHub's independent signed publisher can now promote v0.20.15."
