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
import time
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


class BackendStarting(RuntimeError):
    """Transient local startup/restart race; never bypass the SSO gate."""


def _probe_backend_once(opener=None):
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect())
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
        if exc.code in (502,503,504):
            raise BackendStarting("studio_gate_initializing") from None
        if exc.code!=401:
            raise RuntimeError("Studio did not deny anonymous API access")
    req=urllib.request.Request(base+"/auth/start",headers=headers)
    try:
        opener.open(req,timeout=10)
        raise RuntimeError("Microsoft authorization redirect absent")
    except urllib.error.HTTPError as exc:
        if exc.code in (502,503,504):
            raise BackendStarting("studio_login_initializing") from None
        redirect=exc.headers.get("Location","")
        trusted=(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?",
            "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/oauth2/v2.0/authorize?",
        )
        if exc.code!=302 or not any(redirect.startswith(prefix) for prefix in trusted):
            raise RuntimeError("Microsoft authorization flow not available")


def probe_backend(*, attempts=9, delay=0.5, opener=None, sleep=time.sleep):
    """Retry only temporary local transport/startup failures, fail closed.

    Every successful probe must still confirm BOTH HTTP 401 (anonymous
    production API) and a 302 redirect to the pinned Microsoft endpoint.
    Errors from unexpected 200/403/other redirects are never retried.
    """
    if not isinstance(attempts,int) or not 1<=attempts<=12:
        raise ValueError("invalid_probe_attempts")
    for index in range(attempts):
        try:
            _probe_backend_once(opener=opener)
            if index:
                print("PASS: Microsoft auth gate ready after startup retries")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                BackendStarting) as exc:
            if index+1==attempts:
                raise RuntimeError(
                    "studio_auth_gate_not_ready_after_retries") from None
            sleep(min(delay * (index+1),2.0))


def promote():
    if os.geteuid()!=0:
        raise RuntimeError("sudo_required")
    if not SNIPPET.is_file() or SNIPPET.is_symlink():
        raise RuntimeError("existing_basic_studio_nginx_required")
    basic=BASIC_TEMPLATE.read_bytes()
    modern=MS_TEMPLATE.read_bytes()
    current=SNIPPET.read_bytes()
    if current==modern:
        # Idempotent re-use: do not mutate the existing protected Nginx route.
        # Still require a healthy fail-closed identity backend before success.
        probe_backend()
        print("PASS: existing Microsoft Studio route retained; gate verified")
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
