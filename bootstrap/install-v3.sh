#!/usr/bin/env bash
set -euo pipefail

# One-time, user-run bootstrap for ComfyUI Director V3 (read-only).
# This script never changes running ComfyUI, GPU power, queues, or V1 gateway.
BASE="https://raw.githubusercontent.com/zxasd2183-oss/comfyui-director-release/main"
SHA256="a4ceaf17af06c09a0ef3b18a568e6d100f196d9519701c4d31cffc104f84f204"
DEST="${HOME}/director-v3-bootstrap"
command -v python3 >/dev/null || { echo "Python 3 required"; exit 1; }
command -v curl >/dev/null || { echo "curl required"; exit 1; }
command -v tar >/dev/null || { echo "tar required"; exit 1; }
command -v base64 >/dev/null || { echo "base64 required"; exit 1; }
mkdir -p "$DEST"
chmod 700 "$DEST"
cd "$DEST"
echo "Downloading pinned bootstrap bundle from GitHub ..."
curl --proto '=https' --tlsv1.2 -fsSL \
  "$BASE/bootstrap/director-v0.3.0-bootstrap.tar.gz.b64" \
  -o director.tar.gz.b64
base64 --decode director.tar.gz.b64 > director.tar.gz
python3 - "$SHA256" <<'PY'
from pathlib import Path
import hashlib,sys
data=Path("director.tar.gz").read_bytes()
got=hashlib.sha256(data).hexdigest()
if got!=sys.argv[1]:
    raise SystemExit("SHA256 MISMATCH: refusing to unpack. Expected "+sys.argv[1]+" got "+got)
print("Verified SHA256:",got)
PY
echo "Unpacking verified package (does not start a server) ..."
mkdir -p src
tar -tzf director.tar.gz | while IFS= read -r path; do
  case "/$path" in
    *"/../"*|*"/./"*|*"/.."|*"/.") echo "Unsafe archive entry"; exit 1 ;;
  esac
done
tar -xzf director.tar.gz -C src --no-same-owner --no-same-permissions
cd src
if ! python3 -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey' >/dev/null 2>&1; then
  echo "NOTE: Signed AUTO-UPDATES need the Python cryptography package."
  echo "Install it into this Python environment before enabling updates:"
  echo "  python3 -m pip install cryptography"
fi
echo "Running offline tests ..."
python3 -m unittest discover -s tests -q
echo "Installing files without stopping existing V1 or changing the GPU ..."
python3 install.py
echo ""
echo "V3 files installed. Your current V1 tunnel remains untouched."
echo "To switch later: stop old V1 Python gateway, then run:"
echo "  ~/.comfyui-director/controller/start.sh"
echo "Configure the signed release source and public key separately before expecting auto updates."
