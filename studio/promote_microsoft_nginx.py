#!/usr/bin/env python3
"""One-way audited /studio/ Basic->Microsoft auth nginx promotion.

Changes ONLY the already installed /etc/nginx/snippets/director-studio.conf,
provided it exactly matches our reviewed Basic Auth template. Never edits
other locations, never touches Jipite mobile/power or TLS cert configuration.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"vps-control"))
from configure_jipite_mobile_nginx import (
    DOMAIN_RE, LISTEN_TLS_RE, LISTEN_PORT_RE, locate_https_vhost,
    run_check, server_blocks,
)

SNIPPET = Path("/etc/nginx/snippets/director-studio.conf")
BASIC_TEMPLATE = Path(__file__).resolve().parent/"nginx-jipite-studio.conf"
MS_TEMPLATE = Path(__file__).resolve().parent/"nginx-jipite-studio-microsoft.conf"
EXPECTED_INCLUDE = "include /etc/nginx/snippets/director-studio.conf;"


def verify_target_vhost(dump):
    found=[]
    for file,raw in _sections(dump):
        for _,_,block in server_blocks(raw):
            hosts=set()
            for item in DOMAIN_RE.findall(block):
                hosts.update(item.split())
            if "jipite.borealos.cn" in hosts and (
                LISTEN_TLS_RE.search(block) or LISTEN_PORT_RE.search(block)):
                found.append((file,block))
    if len(found)!=1 or found[0][1].count(EXPECTED_INCLUDE)!=1:
        raise RuntimeError("Studio include not uniquely found inside Jipite TLS host")


def _sections(dump):
    import re
    headings=list(re.finditer(r"(?m)^# configuration file ([^\n]+):\s*$",dump))
    for i,head in enumerate(headings):
        end=headings[i+1].start() if i+1<len(headings) else len(dump)
        yield head.group(1).strip(),dump[head.end():end]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None


def probe_backend():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    headers={
        "Host":"127.0.0.1:8900",
        "X-Forwarded-Proto":"https",
        "X-Forwarded-Host":"jipite.borealos.cn",
        "X-Director-Studio-Auth-Mode":"microsoft",
    }
    base="http://127.0.0.1:8900"
    req=urllib.request.Request(base+"/api/v1/production",headers=headers)
    try:
        opener.open(req,timeout=8)
        raise RuntimeError("Studio allowed anonymous read; refusing to remove Basic Auth")
    except urllib.error.HTTPError as exc:
        if exc.code!=401:
            raise RuntimeError("Studio did not deny anonymous API access")
    req=urllib.request.Request(base+"/auth/start",headers=headers)
    try:
        opener.open(req,timeout=10)
        raise RuntimeError("Microsoft authorization redirect absent")
    except urllib.error.HTTPError as exc:
        if exc.code!=302 or not exc.headers.get("Location","").startswith(
                "https://login.microsoftonline.com/consumers/"):
            raise RuntimeError("Microsoft authorization flow not available")


def promote():
    if os.geteuid()!=0:
        raise RuntimeError("sudo_required")
    if not SNIPPET.is_file() or SNIPPET.is_symlink():
        raise RuntimeError("existing_basic_studio_nginx_required")
    basic=BASIC_TEMPLATE.read_bytes()
    modern=MS_TEMPLATE.read_bytes()
    current=SNIPPET.read_bytes()
    if current==modern:
        print("Studio Microsoft route already configured; verified backend gate")
        probe_backend()
        return
    if current!=basic:
        raise RuntimeError("unexpected_studio_nginx_configuration_refusing_override")
    run_check("nginx","-t")
    dump=subprocess.run(["nginx","-T"],check=True,stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,text=True).stdout
    verify_target_vhost(dump)
    if str(locate_https_vhost(dump)).startswith("/etc/nginx") is False:
        raise RuntimeError("unexpected_nginx_vhost")
    probe_backend()
    fd,backup=tempfile.mkstemp(prefix=".director-studio-pre-ms-",
                              dir=str(SNIPPET.parent))
    os.chmod(backup,0o600)
    with os.fdopen(fd,"wb") as out:
        out.write(current)
    try:
        SNIPPET.write_bytes(modern)
        run_check("nginx","-t")
        run_check("systemctl","reload","nginx")
    except Exception:
        SNIPPET.write_bytes(current)
        try:
            run_check("nginx","-t")
            run_check("systemctl","reload","nginx")
        except Exception:
            pass
        raise
    print("PASS: Microsoft owner-only auth now protects /studio/ publicly")
    print("Basic auth retired ONLY on /studio/. Private backup:",backup)
    print("Mobile/API/MCP/update routes and VPS/GPU power: unchanged")


if __name__=="__main__":
    try:
        promote()
    except Exception as exc:
        print("Studio Microsoft promotion blocked: "+type(exc).__name__,
              file=sys.stderr)
        raise SystemExit(2)
