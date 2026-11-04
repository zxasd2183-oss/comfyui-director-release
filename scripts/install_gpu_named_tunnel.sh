#!/usr/bin/env bash
# Run ONCE inside the CompShare GPU container (not the Guangzhou VPS).
# Installs only a Named Tunnel secret and the documented /start.d startup hook.
# It cannot create a Cloudflare tunnel/DNS record and never powers GPU on/off.
set -euo pipefail
umask 077
if [[ "$EUID" != 0 ]]; then
  echo "Run as root in CompShare GPU container; e.g. sudo bash scripts/install_gpu_named_tunnel.sh" >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
command -v cloudflared >/dev/null || { echo "cloudflared not installed"; exit 2; }
command -v python3 >/dev/null || { echo "python3 not installed"; exit 2; }
VERSION_OUTPUT="$(cloudflared --version 2>/dev/null)"
if ! python3 - "$VERSION_OUTPUT" <<'PY'
import re, sys
match=re.search(r"version\s+(\d{4})\.(\d+)\.(\d+)",sys.argv[1],flags=re.I)
raise SystemExit(0 if match and tuple(map(int,match.groups())) >= (2025,4,0) else 1)
PY
then
  echo "cloudflared 2025.4.0+ needed for secure --token-file; upgrade first" >&2
  exit 2
fi
OWNER_HOME="/root"
if [[ ! -f "$OWNER_HOME/.comfyui-director/config.json" ]] || \
   [[ ! -f "$OWNER_HOME/.comfyui-director/controller/start.sh" ]]; then
  echo "Expected existing Director V3 in /root/.comfyui-director; nothing installed" >&2
  exit 3
fi
[[ -f "$SCRIPT_DIR/gpu-named-tunnel-boot.sh" ]] || { echo "Boot script missing"; exit 3; }
install -d -o root -g root -m 0700 /etc/comfyui-director
TOKEN_FILE="/etc/comfyui-director/gpu-named-tunnel.token"
if [[ -e "$TOKEN_FILE" ]]; then
  [[ ! -L "$TOKEN_FILE" ]] || { echo "Refuse symlink token"; exit 4; }
  chmod 0600 "$TOKEN_FILE"
  chown root:root "$TOKEN_FILE"
  echo "Existing tunnel credential kept (never silently rotated)"
else
  echo "Paste the GPU Named Tunnel token from Cloudflare Dashboard ONLY here."
  IFS= read -r -s -p "GPU Tunnel token (hidden): " TOKEN
  echo
  if [[ ! "$TOKEN" =~ ^[A-Za-z0-9._-]{64,8192}$ ]]; then
    unset TOKEN
    echo "Invalid tunnel token format; nothing installed" >&2
    exit 4
  fi
  (umask 077; printf '%s\n' "$TOKEN" > "$TOKEN_FILE")
  unset TOKEN
  chown root:root "$TOKEN_FILE"
  chmod 0600 "$TOKEN_FILE"
fi
printf '%s\n' "$OWNER_HOME" > /etc/comfyui-director/installed-home
chmod 0644 /etc/comfyui-director/installed-home
install -d -o root -g root -m 0755 /start.d
install -o root -g root -m 0755 "$SCRIPT_DIR/gpu-named-tunnel-boot.sh" \
  /start.d/90-comfyui-director-v3.sh
echo "GPU Named Tunnel startup installed in /start.d."
echo "To test the hook NOW, run: sudo bash /start.d/90-comfyui-director-v3.sh"
echo "Cloudflare hostname must already be mapped to localhost:8790."
echo "No GPU power, ComfyUI tasks, or cloud provider API calls occurred."
