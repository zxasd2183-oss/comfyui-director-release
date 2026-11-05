#!/usr/bin/env bash
# Director Studio V0.9.3: Hub <-> Studio authenticated brain link.
# Safe owner-invoked VPS deployment. Never starts GPU, ComfyUI, or power ops.
set -Eeuo pipefail
umask 077
die(){ echo "ERROR: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || die "Run with sudo on your trusted VPS"
SRC="$(cd "$(dirname "$0")" && pwd)"
VPS="$(cd "$SRC/../vps-control" && pwd)"
HUB=/opt/comfyui-director-hub
STUDIO=/opt/director-studio
PYTHON=/opt/comfyui-director-control/.venv/bin/python
KEY=/etc/director-studio/brain-link.key
SDROP=/etc/systemd/system/director-studio.service.d/brain-link.conf
HDROP=/etc/systemd/system/director-hub-mcp.service.d/brain-link.conf
# Never replace the live bridge with code targeting 8899 while Nginx still
# routes /mcp/ to a different bridge. Do not mutate Nginx here.
HUB_SNIPPET=/etc/nginx/snippets/jipite-hub.conf
[[ -f "$HUB_SNIPPET" && ! -L "$HUB_SNIPPET" ]] ||
    die "Hub Nginx snippet missing or symlinked; review without changing ports"
grep -Fq 'proxy_pass http://127.0.0.1:8899;' "$HUB_SNIPPET" ||
    die "Hub Nginx upstream is not 8899; do not overwrite a working bridge"
grep -Fq 'proxy_set_header Host 127.0.0.1:8899;' "$HUB_SNIPPET" ||
    die "Hub Nginx Host header is not 8899; review before upgrade"

for name in director-studio director-hub-mcp director-hub-bridge director-power-mcp director-mobile-v06 nginx; do
    systemctl is-active --quiet "$name" || die "Required service not active: $name"
done
[[ -x "$PYTHON" && -d "$HUB" && ! -L "$HUB" && -d "$STUDIO" && ! -L "$STUDIO" ]] \
  || die "Hub/Studio installation missing or unsafe"
[[ -f /etc/systemd/system/director-studio.service.d/microsoft.conf ]] \
  || die "Microsoft owner SSO must be installed before enabling ChatGPT brain link"
cmp -s /etc/nginx/snippets/director-studio.conf \
    "$SRC/nginx-jipite-studio-microsoft.conf" \
    || die "Studio Nginx auth gate does not match the reviewed Microsoft template"
[[ -f "$SRC/studio_brain.py" && -f "$SRC/production_core.py" &&
   -f "$VPS/hub_rpc.py" && -f "$VPS/hub_brain.py" &&
   -f "$VPS/hub_app.py" && -f "$VPS/hub_bridge.py" && -f "$SRC/brain-link-studio.service.conf" &&
   -f "$VPS/brain-link-hub.service.conf" ]] || die "Brain-link source files missing"
for f in "$HUB/hub_rpc.py" "$HUB/hub_app.py" "$HUB/hub_bridge.py"; do
    [[ -f "$f" && ! -L "$f" ]] || die "Installed Hub file unsafe: $f"
done
for target in "$SDROP" "$HDROP"; do
    [[ ! -L "$target" ]] || die "Symlinked service credential dropin refused"
done
if [[ -f "$SDROP" ]]; then
    cmp -s "$SDROP" "$SRC/brain-link-studio.service.conf" \
      || die "Existing Studio brain unit differs; refusing override"
fi
if [[ -f "$HDROP" ]]; then
    cmp -s "$HDROP" "$VPS/brain-link-hub.service.conf" \
      || die "Existing Hub brain unit differs; refusing override"
fi

# Studio safety tests and targeted Hub signing tests run locally. The
# complete VPS GPU/power suite is already exercised in GitHub CI, not as root
# against a production VPS. Never issue provider start/stop calls in preflight.
python3 -m unittest discover -s "$SRC/tests" -p 'test_*.py' -q
"$PYTHON" "$VPS/tests/test_studio_brain_route.py" -q
"$PYTHON" -m py_compile "$VPS/hub_app.py" "$VPS/hub_bridge.py" "$VPS/hub_rpc.py" \
    "$VPS/hub_brain.py" "$SRC/studio_server.py" "$SRC/studio_brain.py"

# Studio uses its existing backup+rollback installer. This may invalidate
# existing browser sessions when systemd restarts the service.
echo "STEP: verifying/upgrading existing Microsoft Studio route (no changes to GPU)"
if ! bash "$SRC/install-microsoft-web.sh"; then
    die "Microsoft Studio sub-installer failed; Hub remains untouched. Check Studio gate diagnostics."
fi
systemctl is-active --quiet director-studio || die "Studio upgrade completed but Studio is inactive"

# Key lives ONLY in /etc/director-studio, root-owned and mode 0600.
python3 - "$KEY" <<'PY'
import os,secrets,stat,sys
from pathlib import Path
p=Path(sys.argv[1]);d=p.parent
s=d.lstat()
if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)&0o077:
    raise SystemExit("Unsafe Studio credential directory")
if p.is_symlink():
    raise SystemExit("Brain credential symlink refused")
if p.exists():
    s=p.stat()
    if (not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or
            stat.S_IMODE(s.st_mode)!=0o600 or s.st_size>128):
        raise SystemExit("Unsafe existing brain credential")
    import re
    if not re.fullmatch(r"[0-9a-f]{64}\n?",p.read_text(encoding="ascii")):
        raise SystemExit("Brain credential invalid; refusing to rotate")
    print("PASS: existing brain credential retained, never displayed")
else:
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w",encoding="ascii") as f:
        f.write(secrets.token_hex(32)+"\n")
    print("PASS: root-only brain credential created, never displayed")
PY

BACKUP="$(mktemp -d /var/tmp/director-brain-link-backup-XXXXXXXX)"
chmod 0700 "$BACKUP"
cp -p "$HUB/hub_app.py" "$BACKUP/hub_app.py"
cp -p "$HUB/hub_rpc.py" "$BACKUP/hub_rpc.py"
cp -p "$HUB/hub_bridge.py" "$BACKUP/hub_bridge.py"
HAD_HUB_BRAIN=0
if [[ -f "$HUB/hub_brain.py" && ! -L "$HUB/hub_brain.py" ]]; then
    HAD_HUB_BRAIN=1
    cp -p "$HUB/hub_brain.py" "$BACKUP/hub_brain.py"
fi
HAD_SD=0; HAD_HD=0
[[ -f "$SDROP" ]] && HAD_SD=1
[[ -f "$HDROP" ]] && HAD_HD=1
COMMITTED=0
restore(){
    local rc="$1"
    trap - EXIT
    if (( ! COMMITTED )); then
        echo "Brain-link deployment blocked; attempting to restore previous Hub." >&2
        cp -p "$BACKUP/hub_app.py" "$HUB/hub_app.py" || :
        cp -p "$BACKUP/hub_rpc.py" "$HUB/hub_rpc.py" || :
        cp -p "$BACKUP/hub_bridge.py" "$HUB/hub_bridge.py" || :
        if (( HAD_HUB_BRAIN )); then
            cp -p "$BACKUP/hub_brain.py" "$HUB/hub_brain.py" || :
        else
            rm -f "$HUB/hub_brain.py" || :
        fi
        (( HAD_SD )) || rm -f "$SDROP"
        (( HAD_HD )) || rm -f "$HDROP"
        systemctl daemon-reload || :
        systemctl restart director-studio || :
        systemctl restart director-hub-mcp || :
        systemctl restart director-hub-bridge || :
        echo "Private backup: $BACKUP" >&2
    fi
    exit "$rc"
}
trap 'restore $?' EXIT

install -o root -g root -m 0644 "$VPS/hub_rpc.py" "$HUB/hub_rpc.py"
install -o root -g root -m 0644 "$VPS/hub_brain.py" "$HUB/hub_brain.py"
install -o root -g root -m 0644 "$VPS/hub_app.py" "$HUB/hub_app.py"
install -o root -g root -m 0644 "$VPS/hub_bridge.py" "$HUB/hub_bridge.py"
mkdir -p "$(dirname "$SDROP")" "$(dirname "$HDROP")"
install -o root -g root -m 0644 "$SRC/brain-link-studio.service.conf" "$SDROP"
install -o root -g root -m 0644 "$VPS/brain-link-hub.service.conf" "$HDROP"
systemctl daemon-reload
systemctl restart director-studio
systemctl restart director-hub-mcp
# Port 8899 bridge proxies into Hub MCP 8898; reload its upstream only
# after the new Hub is active, never touch the unrelated 8896 OIDC service.
systemctl is-active --quiet director-hub-mcp || die "Hub MCP did not recover"
systemctl restart director-hub-bridge
for name in director-studio director-hub-mcp director-hub-bridge director-power-mcp director-mobile-v06; do
    systemctl is-active --quiet "$name" || die "Service did not recover: $name"
done

# Local read-only handshake. Do not print project names or credential bytes.
"$PYTHON" - "$KEY" <<'PY'
import json,secrets,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,"/opt/comfyui-director-hub")
import hub_brain
key=bytes.fromhex(Path(sys.argv[1]).read_text(encoding="ascii").strip())
body=json.dumps({"tool":"get_production_dashboard","arguments":{}},
                separators=(",",":")).encode()
stamp=str(int(time.time()));nonce=secrets.token_hex(16)
req=urllib.request.Request(hub_brain.STUDIO_URL,data=body,method="POST",
    headers={"Host":"127.0.0.1:8900","Content-Type":"application/json",
             "X-Director-Brain-Time":stamp,
             "X-Director-Brain-Nonce":nonce,
             "X-Director-Brain-Signature":hub_brain.sign(key,body,stamp,nonce)})
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(req,timeout=8) as response:
    result=json.load(response)
if result.get("ok") is not True or result.get("audit_chain_verified") is not True:
    raise SystemExit("Brain handshake failed or production audit invalid")
print("PASS: signed Hub-to-Studio production read; audit chain valid")
PY

"$PYTHON" - <<'PY'
import json,time,urllib.request
from urllib.request import Request,build_opener,ProxyHandler
opener=build_opener(ProxyHandler({}))
req=Request("http://127.0.0.1:8898/mcp",method="POST",
    data=json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}).encode(),
    headers={"Host":"127.0.0.1:8898","Content-Type":"application/json",
             "Accept":"application/json, text/event-stream",
             "Mcp-Protocol-Version":"2025-03-26"})
for attempt in range(8):
    try:
        with opener.open(req,timeout=8) as response:
            body=json.load(response)
        names={t["name"] for t in body["result"]["tools"]}
        expected={
            "get_studio_status","get_queue_summary","list_h3_nodes",
            "list_h3_workflows","get_h3_workflow_structure",
            "audit_h3_workflow","get_h3_node_inputs","get_upgrade_readiness",
            "get_control_center_status","get_gpu_power_status",
            "request_gpu_start","request_gpu_stop","get_power_request_status",
            "get_production_dashboard","get_production_episode",
            "create_production_project","create_production_episode",
            "add_production_shot","save_production_outline",
        }
        if names!=expected:
            raise RuntimeError("Hub MCP registry mismatch")
        print("PASS: Hub 19 tools registered; existing GPU/power tools preserved")
        break
    except Exception:
        if attempt==7: raise
        time.sleep(1)
PY

COMMITTED=1
echo "SUCCESS: Director Studio Brain Link deployed. Six new Studio tools in Hub."
echo "The ChatGPT connector may need refresh/reconnect to discover new tools."
echo "Studio: https://jipite.borealos.cn/studio/"
echo "No GPU start/stop, approval bypass, video tasks or Microsoft secret changes."
echo "Private Hub backup: $BACKUP"
