#!/usr/bin/env bash
# Install Director Hub V0.5 beside the existing three services on Guangzhou VPS.
# Never requests, starts or stops any GPU. Existing MCP/plugin routes remain.
set -euo pipefail
umask 077

fail() { echo "ERROR: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || fail "Run with sudo on your Guangzhou VPS"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/comfyui-director-hub
PYTHON=/opt/comfyui-director-control/.venv/bin/python
ENV=/etc/comfyui-director-control.env
GPU_PATH=/etc/comfyui-director-hub-gpu-path
TOKEN=/etc/comfyui-director-hub.token

[[ -x "$PYTHON" && -f "$ENV" ]] || fail "Original VPS controller missing"
id directorpower >/dev/null || fail "Existing directorpower service account missing"
for name in director-vps-control director-power-mcp director-mobile-v06; do
    systemctl is-active --quiet "$name" || fail "Required service $name is not active"
done
for name in hub_rpc.py hub_brain.py hub_app.py hub_bridge.py bridge.py \
            director-hub-mcp.service director-hub-bridge.service \
            configure_director_hub_nginx.py nginx-alidns/jipite-hub.conf; do
    [[ -f "$SRC/$name" && ! -L "$SRC/$name" ]] || fail "Missing trusted source: $name"
done

# No provider private key is copied to the Hub. Extract only the existing
# random GPU Director MCP route from the original root-owned configuration.
python3 - "$ENV" "$GPU_PATH" <<'PY'
import os, re, stat, sys
from pathlib import Path
from urllib.parse import urlsplit
source, target = map(Path, sys.argv[1:])
s = source.lstat()
if (not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or
        stat.S_IMODE(s.st_mode) & 0o077):
    raise SystemExit("Source provider env must be root-owned, mode 0600")
values = []
for line in source.read_text(encoding="utf-8").splitlines():
    if line.startswith("DIRECTOR_GPU_MCP_URL="):
        val = line.split("=", 1)[1].strip().strip('"').strip("'")
        values.append(val)
if len(values) != 1:
    raise SystemExit("DIRECTOR_GPU_MCP_URL is missing or duplicated")
parsed = urlsplit(values[0])
path = parsed.path
if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
        parsed.password or parsed.query or parsed.fragment or
        not re.fullmatch(r"/mcp/[A-Za-z0-9_-]{40,160}", path)):
    raise SystemExit("Configured GPU MCP private path is invalid")
# Do not silently rotate/update live GPU route. A mismatch needs operator
# review to avoid exposing a wrong or stale GPU Director token.
if target.exists() or target.is_symlink():
    if target.is_symlink() or not target.is_file() or target.read_text().strip() != path:
        raise SystemExit("Existing Hub GPU path differs; review before changing")
    if stat.S_IMODE(target.stat().st_mode) & 0o007:
        raise SystemExit("Hub GPU path has unsafe permissions")
else:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(path + "\n")
    import grp
    os.chown(target, 0, grp.getgrnam("directorpower").gr_gid)
print("Existing GPU private route path imported without exposing token")
PY

python3 - "$TOKEN" <<'PY'
import grp, os, re, secrets, stat, sys
from pathlib import Path
f = Path(sys.argv[1])
if f.exists() or f.is_symlink():
    if f.is_symlink() or not f.is_file():
        raise SystemExit("Hub token path is unsafe")
    if not re.fullmatch(r"[0-9a-f]{64}", f.read_text().strip()):
        raise SystemExit("Existing Hub token invalid; refusing rotation")
    if stat.S_IMODE(f.stat().st_mode) & 0o007:
        raise SystemExit("Existing Hub token world readable")
else:
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(secrets.token_hex(32) + "\n")
    os.chown(f, 0, grp.getgrnam("directorpower").gr_gid)
print("Stable Hub MCP private path token ready; value not logged")
PY

[[ ! -L "$DEST" ]] || fail "Hub install path cannot be a symlink"
install -d -o root -g root -m 0755 "$DEST"
for name in hub_rpc.py hub_brain.py hub_app.py hub_bridge.py bridge.py; do
    install -o root -g root -m 0644 "$SRC/$name" "$DEST/$name"
done
"$PYTHON" -m py_compile "$DEST"/hub_*.py "$DEST"/bridge.py

for name in director-hub-mcp director-hub-bridge; do
    install -o root -g root -m 0644 "$SRC/$name.service" \
        "/etc/systemd/system/$name.service"
done
systemctl daemon-reload
systemctl enable --now director-hub-mcp director-hub-bridge
systemctl restart director-hub-mcp director-hub-bridge
systemctl is-active --quiet director-hub-mcp director-hub-bridge \
    || fail "Hub MCP or bridge service failed; inspect journalctl locally"

# Verify the LOCAL 13-tool registry, not an external route or power request.
"$PYTHON" - <<'PY'
import json
from urllib.request import Request, urlopen
data = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}).encode()
req = Request("http://127.0.0.1:8898/mcp", data=data, method="POST", headers={
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Mcp-Protocol-Version": "2025-03-26",
})
with urlopen(req, timeout=12) as response:
    result = json.load(response)
names = {entry["name"] for entry in result["result"]["tools"]}
expected = {
    "get_studio_status","get_queue_summary","list_h3_nodes",
    "list_h3_workflows","get_h3_workflow_structure",
    "audit_h3_workflow","get_h3_node_inputs","get_upgrade_readiness",
    "get_control_center_status","get_gpu_power_status",
    "request_gpu_start","request_gpu_stop","get_power_request_status",
    "get_production_dashboard","get_production_episode",
    "create_production_project","create_production_episode",
    "add_production_shot","save_production_outline",
}
if names != expected:
    raise SystemExit("Hub MCP registry mismatch; expected exactly 13 tools")
print("Hub MCP tools/list: 19/19 declared, NO POWER OPERATION")
PY

# Nginx routing is applied only if target HTTPS vhost is unambiguous.
python3 "$SRC/configure_director_hub_nginx.py"
echo "Director Hub installed on VPS loopback (8898/8897)."
echo "Existing GPU / VPS / mobile approval services unchanged."
echo "Retrieve private connection URL ONLY in VPS private SSH terminal:"
echo "sudo sh -c 'printf https://jipite.borealos.cn/mcp/; cat /etc/comfyui-director-hub.token'"
echo "Do not post that full URL or its token in ChatGPT, GitHub or screenshots."
