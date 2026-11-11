#!/usr/bin/env bash
# Stage and independently verify the canonical Windows v0.20.18 installer
# through the EXISTING owner VPS mirror. Never modifies signed JSON or Mac.
set -Eeuo pipefail

version="0.20.18"
name="GlacierBrowser-v${version}-Windows-Setup-x64.exe"
file="/var/lib/glacier-preview-downloads/${name}"
url="https://sync.borealos.cn/downloads/${name}"
expected_size="175907184"
expected_hash="9292482af0f96d347363b332c664311efb774c2521d97631b86e7dbcce871371"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ "$(systemctl show --property=LoadState --value glacier-signed-mirror.service)" == "loaded" ]] || {
  echo "Glacier signed mirror service is not installed" >&2; exit 2;
}
# Ensure the installed service will execute the updated, reviewed repo script.
systemctl cat glacier-signed-mirror.service | grep -Fq \
  "${script_dir}/sync-glacier-signed-releases.py" || {
    echo "Installed mirror unit points to another script; refusing blind sync" >&2
    exit 2
  }
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' \
  "${script_dir}/sync-glacier-signed-releases.py"
grep -Fq 'def stage_latest_windows(directory, expected_version=None):' \
  "${script_dir}/sync-glacier-signed-releases.py" || {
    echo "Standalone Windows staging code is missing; pull latest main first" >&2
    exit 2
  }

echo "Starting existing VPS signed mirror: standalone Windows staging, paired feeds unchanged"
sudo systemctl start glacier-signed-mirror.service

[[ -f "$file" && ! -L "$file" ]] || {
  echo "Canonical Windows v${version} EXE not staged by service" >&2
  sudo journalctl -u glacier-signed-mirror.service -n 25 --no-pager >&2 || true
  exit 2
}
actual_size="$(stat -c %s "$file")"
actual_hash="$(sha256sum "$file" | awk '{print $1}')"
[[ "$actual_size" == "$expected_size" && "$actual_hash" == "$expected_hash" ]] || {
  echo "Windows installer SHA-256/size mismatch: refusing acceptance" >&2; exit 2;
}
http="$(curl --silent --show-error --head --location --max-time 25 \
  --output /dev/null --write-out '%{http_code}' "$url")"
[[ "$http" == 200 || "$http" == 206 ]] || {
  echo "Public VPS download URL unavailable: HTTP $http" >&2; exit 2;
}
echo "SUCCESS Windows v${version} mirrored on owner VPS"
echo "Public HTTPS: $url (HTTP $http)"
echo "SHA256 verified: $actual_hash"
echo "Canonical size: $actual_size bytes"
echo "Existing signed Windows/macOS manifests remain controlled by Ed25519 publisher."
