#!/usr/bin/env bash
# ONE-TIME migration to permanent version-independent Glacier release mirroring.
# After this, existing OIDC notify and signed-mirror timer discover every future
# canonical Windows Release automatically; no per-version VPS actions.
set -Eeuo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
script="$repo/vps-control/sync-glacier-signed-releases.py"
unit="glacier-signed-mirror.service"

[[ "$(git -C "$repo" branch --show-current)" == "main" ]] || {
  echo "Deploy from reviewed main checkout only; refusing non-main branch" >&2; exit 2;
}
[[ -f "$script" && ! -L "$script" ]] || {
  echo "Missing or symlinked Glacier mirror source" >&2; exit 2;
}
grep -Fq 'def stage_latest_windows(directory, expected_version=None):' "$script" || {
  echo "Windows release auto-discovery is missing; update repo checkout first" >&2; exit 2;
}
[[ "$(systemctl show -p LoadState --value "$unit")" == "loaded" ]] || {
  echo "Existing signed mirror systemd unit not installed" >&2; exit 2;
}
systemctl cat "$unit" | grep -Fq "$script" || {
  echo "Service points to an unexpected mirror script" >&2; exit 2;
}
systemctl is-active --quiet glacier-signed-mirror.timer || {
  echo "The existing signed-mirror retry timer must be active" >&2; exit 2;
}
systemctl is-active --quiet glacier-preview-notify.service || {
  echo "The existing OIDC notification receiver must be active" >&2; exit 2;
}
policy="$(systemctl show -p NoNewPrivileges --value "$unit")"
case "$policy" in
  yes|true|1) ;;
  *) echo "Mirror sandbox guard unexpectedly disabled; refusing deployment" >&2; exit 2 ;;
esac

python3 -m py_compile "$script"
python3 -m unittest -v "$repo/vps-control/test_glacier_signed_mirror.py"

# The existing systemd service is deliberately reused unchanged.
# This starts one normal cycle; future releases are handled by the existing
# verified OIDC receiver and the already-enabled timer.
sudo systemctl start "$unit"

# Use the same proxy used by the installed mirror service for public API/HEAD.
[[ -n "$(printenv HTTPS_PROXY || true)" ]] ||
  export HTTPS_PROXY=http://127.0.0.1:1081
[[ -n "$(printenv HTTP_PROXY || true)" ]] ||
  export HTTP_PROXY=http://127.0.0.1:1081

python3 - "$repo" <<'PY'
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path

repo = Path(sys.argv[1])
source = repo / "vps-control/sync-glacier-signed-releases.py"
spec = importlib.util.spec_from_file_location("glacier_permanent_mirror", source)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)
version, release = mirror._latest_release_for("windows-x64")
name = f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
size, digest = mirror._verified_release_asset(release, name)
directory = Path("/var/lib/glacier-preview-downloads")
target = directory / name
if (not target.is_file() or target.is_symlink()
        or target.stat().st_size != size or mirror.sha256(target) != digest):
    raise SystemExit("FAILED: latest Windows Release was not independently mirrored")
url = "https://sync.borealos.cn/downloads/" + name
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("VPS redirect is forbidden")
opener = urllib.request.build_opener(NoRedirect())
with opener.open(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
    if response.status not in (200, 206) or response.geturl() != url:
        raise SystemExit("FAILED: public owner-VPS download unavailable")
for channel in ("windows-x64", "macos-arm64"):
    signed_file = directory / (channel + ".json")
    doc = json.loads(signed_file.read_text(encoding="utf-8"), object_pairs_hook=mirror.unique)
    mirror.verify(doc, channel)
print(f"SUCCESS: evergreen Windows VPS mirror active; canonical latest v{version}")
print(f"Public installer: {url}")
print(f"SHA256: {digest}")
print("Both signed channels remain Ed25519-verified; existing OIDC/timer enabled.")
PY
