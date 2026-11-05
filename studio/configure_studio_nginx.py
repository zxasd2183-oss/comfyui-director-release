#!/usr/bin/env python3
"""Attach Director Studio to the existing Jipite TLS vhost with fail-closed auth.

Requires V0.8 Studio to be live on localhost:8900. Uses strong temporary basic
authentication until an approved Microsoft Web OIDC flow is available.
Never opens 8900 publicly, changes Jipite mobile/MCP/update locations, handles
provider credentials, or modifies GPU power.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vps-control"))
from configure_jipite_mobile_nginx import (  # noqa: E402
    DOMAIN_RE, LISTEN_TLS_RE, LISTEN_PORT_RE, locate_https_vhost, run_check,
    server_blocks,
)

DOMAIN = "jipite.borealos.cn"
SNIPPET = Path("/etc/nginx/snippets/director-studio.conf")
SOURCE = Path(__file__).resolve().parent / "nginx-jipite-studio.conf"
AUTH = Path("/etc/nginx/.director-studio-htpasswd")
FIRST_LOGIN = Path("/root/.director-studio-first-login")
MARKER = f"include {SNIPPET};"


def patch(source):
    selected = []
    for _, close, block in server_blocks(source):
        names = set()
        for group in DOMAIN_RE.findall(block):
            names.update(group.split())
        if DOMAIN in names and (LISTEN_TLS_RE.search(block) or LISTEN_PORT_RE.search(block)):
            selected.append((close, block))
    if len(selected) != 1:
        raise RuntimeError("Ambiguous Jipite HTTPS virtual host; no changes")
    close, block = selected[0]
    if source.count(MARKER) > 1:
        raise RuntimeError("Duplicate Studio route includes")
    if MARKER in source:
        if MARKER not in block:
            raise RuntimeError("Studio route installed in wrong virtual host")
        return source, False
    # A Studio location anywhere in the actual vhost requires human review.
    if re.search(r"\blocation\s+(?:\^~\s+|=\s+|~\*?\s+)?[^\s{]*studio", block, re.I):
        raise RuntimeError("Existing /studio route; refusing to override")
    if MARKER in source:
        raise RuntimeError("Studio include outside Jipite virtual host")
    return source[:close] + "\n    " + MARKER + "\n" + source[close:], True


def worker_gid(nginx_dump):
    matches = re.findall(r"(?m)^\s*user\s+([a-z_][a-z0-9_-]*)\s*(?:[a-z_][a-z0-9_-]*)?\s*;", nginx_dump)
    if len(matches) != 1:
        raise RuntimeError("Cannot determine unique Nginx worker user; no changes")
    return pwd.getpwnam(matches[0]).pw_gid


def create_auth(gid):
    if AUTH.exists() or AUTH.is_symlink():
        if (AUTH.is_symlink() or not AUTH.is_file() or AUTH.stat().st_uid != 0
                or stat.S_IMODE(AUTH.stat().st_mode) & 0o007):
            raise RuntimeError("Existing Studio auth file is unsafe")
        return False
    if FIRST_LOGIN.exists() or FIRST_LOGIN.is_symlink():
        raise RuntimeError("Stale first-login file; manually review before installation")
    if shutil.which("htpasswd") is None:
        raise RuntimeError("Missing htpasswd (install apache2-utils first)")
    password = secrets.token_urlsafe(33)
    result = subprocess.run(
        ["htpasswd", "-n", "-B", "-i", "studioowner"],
        input=password + "\n", text=True, capture_output=True, check=True,
        timeout=20,
    )
    hashed = result.stdout.strip()
    if not hashed.startswith("studioowner:$2") or len(hashed) > 250:
        raise RuntimeError("Unexpected htpasswd output")
    # Create both credentials with O_EXCL; passwords are NEVER logged or
    # returned to the GitHub runner, nginx or ChatGPT.
    try:
        fd = os.open(AUTH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(hashed + "\n")
        os.chown(AUTH, 0, gid)
        fd = os.open(FIRST_LOGIN, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write("username: studioowner\npassword: " + password + "\n")
    except BaseException:
        AUTH.unlink(missing_ok=True)
        FIRST_LOGIN.unlink(missing_ok=True)
        raise
    return True


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request("http://127.0.0.1:8900/api/v1/snapshot", headers={
        "Host": "127.0.0.1:8900"
    })
    with opener.open(req, timeout=5) as stream:
        raw = stream.read(65537)
    if len(raw) > 65536 or json.loads(raw).get("mode") != "operator_ledger_only":
        raise RuntimeError("Unexpected Studio backend; no Nginx changes")


def apply():
    if os.geteuid() != 0:
        raise RuntimeError("Run with sudo on VPS")
    if not SOURCE.is_file() or SOURCE.is_symlink():
        raise RuntimeError("Trusted Studio snippet missing")
    run_check("nginx", "-t")
    health()
    dump = subprocess.run(["nginx", "-T"], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout
    target = locate_https_vhost(dump)
    original = target.read_bytes()
    patched, changed = patch(original.decode("utf-8"))
    auth_was_present = AUTH.exists()
    gid = worker_gid(dump)
    if SNIPPET.is_symlink() or (SNIPPET.exists() and SNIPPET.read_bytes() != SOURCE.read_bytes()):
        raise RuntimeError("Installed Studio snippet differs; no changes")
    if not changed:
        if not SNIPPET.is_file() or not auth_was_present:
            raise RuntimeError("Studio include exists but auth/snippet missing")
        print("Director Studio HTTPS route already installed; no changes")
        return

    backup_fd, backup = tempfile.mkstemp(
        prefix=".director-studio-vhost-backup-", dir=str(target.parent))
    os.close(backup_fd)
    shutil.copy2(target, backup)
    os.chmod(backup, 0o600)
    snippet_created = False
    auth_created = False
    try:
        auth_created = create_auth(gid)
        if not SNIPPET.exists():
            SNIPPET.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            fd = os.open(SNIPPET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as stream:
                stream.write(SOURCE.read_bytes())
            snippet_created = True
        target.write_text(patched, encoding="utf-8")
        run_check("nginx", "-t")
        run_check("systemctl", "reload", "nginx")
    except BaseException:
        target.write_bytes(original)
        if snippet_created:
            SNIPPET.unlink(missing_ok=True)
        if auth_created:
            AUTH.unlink(missing_ok=True)
            FIRST_LOGIN.unlink(missing_ok=True)
        try:
            run_check("nginx", "-t")
            run_check("systemctl", "reload", "nginx")
        except Exception:
            pass
        raise

    print("SUCCESS: /studio/ installed only in Jipite TLS vhost; nginx verified")
    print("Existing /mcp/, mobile APIs, APK/DMG feeds: unchanged")
    print("Private backup: " + backup)
    if auth_created:
        print("Temporary Studio login created; password NOT printed or sent to ChatGPT.")
        print("View one time LOCALLY on VPS: sudo cat /root/.director-studio-first-login")
        print("After saving into a password manager: sudo rm /root/.director-studio-first-login")
    else:
        print("Existing temporary Studio password retained (not rotated).")
    print("Verify from outside: /studio/ should be HTTP 401 without credentials")
    print("Until Microsoft OIDC is deployed, this is HTTPS Basic Auth, NOT Microsoft login")


if __name__ == "__main__":
    try:
        apply()
    except Exception as exc:
        # No passwords, sensitive Nginx snippets or credentials are printed.
        print("Studio HTTPS install refused; inspect server locally: " +
              type(exc).__name__, file=sys.stderr)
        raise SystemExit(2)
