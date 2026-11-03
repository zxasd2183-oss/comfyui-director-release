#!/usr/bin/env python3
"""Read-only V3 local MCP check and optional Cloudflare Quick Tunnel setup."""
import argparse, json, os, re, shutil, subprocess, time
from pathlib import Path
from urllib.request import Request, urlopen

def read(url, body=None):
    headers={"Accept":"application/json"}
    if body is not None: headers["Content-Type"]="application/json"
    req=Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with urlopen(req,timeout=5) as response:
        return json.loads(response.read(131072))

def main():
    ap=argparse.ArgumentParser(description="Test ComfyUI Director V3 (read only)")
    ap.add_argument("--install-root",default=str(Path.home()/".comfyui-director"))
    ap.add_argument("--tunnel",action="store_true",help="Start a new HTTPS Quick Tunnel to Director V3")
    args=ap.parse_args()
    root=Path(args.install_root).expanduser().resolve()
    config=json.loads((root/"config.json").read_text(encoding="utf-8"))
    port=config.get("port",8765)
    path=config.get("mcp_path")
    if not isinstance(port,int) or not 1<=port<=65535:
        raise SystemExit("ERROR: invalid port in config.json")
    if not isinstance(path,str) or not path.startswith("/mcp/") or len(path)<32:
        raise SystemExit("ERROR: invalid private MCP path in config.json")
    base=f"http://127.0.0.1:{port}"
    try:
        health=read(base+"/health")
        rpc=read(base+path,{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})
    except Exception as exc:
        raise SystemExit(f"ERROR: cannot connect to Director port {port}: {type(exc).__name__}")
    names=sorted(t["name"] for t in rpc.get("result",{}).get("tools",[]) if "name" in t)
    print("Director:", {"ok":health.get("ok"),"version":health.get("version"),"port":port})
    print("Tools:",len(names))
    for name in names: print(" -",name)
    if health.get("version")!="0.3.0" or len(names)<8 or "get_upgrade_readiness" not in names:
        raise SystemExit("ERROR: expected Director V3 with 8 tools; do not register")
    print("PASS: 8 read-only V3 tools verified locally.")
    if not args.tunnel:
        print("Use --tunnel to create a fresh public HTTPS MCP URL.")
        return
    binary=shutil.which("cloudflared")
    if not binary:
        raise SystemExit("cloudflared not installed. Install it or configure your HTTPS proxy for "+base)
    log=root/"v3-quick-tunnel.log"
    fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        proc=subprocess.Popen([binary,"tunnel","--url",base],stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    (root/"v3-quick-tunnel.pid").write_text(str(proc.pid),encoding="ascii")
    public=None
    for _ in range(40):
        if proc.poll() is not None: break
        m=re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",
                    log.read_text(encoding="utf-8",errors="replace"))
        if m: public=m.group(0); break
        time.sleep(.5)
    if not public:
        raise SystemExit("Tunnel address not found. Check "+str(log)+" locally.")
    try:
        check=read(public+"/health")
        if check.get("version")!="0.3.0": raise ValueError("not V3")
    except Exception:
        raise SystemExit("Public HTTPS tunnel health check failed; inspect log and retry.")
    print("\n=== PRIVATE MCP SERVER URL: COPY ONLY INTO CHATGPT PLUGIN SETTINGS ===")
    print(public+path)
    print("=== NEVER POST OR SHARE THIS FULL URL ===")
    print("Name: ComfyUI Director V3 | Connection: Server URL | Auth: None")
    print("Tunnel PID:",proc.pid,"; remains running until stopped or GPU shuts down.")
    print("This is a temporary read-only bearer-URL connection; use stronger auth for production.")

if __name__=="__main__":
    main()
