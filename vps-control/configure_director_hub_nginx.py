#!/usr/bin/env python3
"""Install exactly one Director Hub /mcp/ route into the existing Jipite TLS vhost.

Fails closed on ambiguous configs; backups and rolls back after failed nginx
validation/reload. Leaves all Android APIs and existing Director hosts alone.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from configure_jipite_mobile_nginx import (
    DOMAIN, DOMAIN_RE, LISTEN_TLS_RE, LISTEN_PORT_RE,
    locate_https_vhost, run_check, server_blocks,
)

SNIPPET = Path("/etc/nginx/snippets/jipite-hub.conf")
SOURCE_SNIPPET = Path(__file__).resolve().parent / "nginx-alidns/jipite-hub.conf"
MARKER = f"include {SNIPPET};"
MCP_INLINE = re.compile(r"\blocation\s+[^{]+/mcp/[^{}]*\{", re.S)


def _selected(source):
    results = []
    for _, closing, block in server_blocks(source):
        names = set()
        for part in DOMAIN_RE.findall(block):
            names.update(part.split())
        if DOMAIN in names and (LISTEN_TLS_RE.search(block) or
                                LISTEN_PORT_RE.search(block)):
            results.append((closing, block))
    if len(results) != 1:
        raise RuntimeError("Exactly one Jipite HTTPS server block is required")
    return results[0]


def patch(source):
    closing, block = _selected(source)
    if MCP_INLINE.search(block):
        raise RuntimeError("Existing inline MCP route: cannot safely override")
    if block.count(MARKER) > 1 or source.count(MARKER) > 1:
        raise RuntimeError("Duplicate Director Hub snippet include")
    if MARKER in source:
        if MARKER not in block:
            raise RuntimeError("Hub include is outside correct TLS virtual host")
        return source, False
    return source[:closing] + "\n    " + MARKER + "\n" + source[closing:], True


def apply():
    if os.geteuid() != 0:
        raise RuntimeError("sudo is required")
    run_check("nginx", "-t")
    dump = subprocess.run(
        ["nginx", "-T"], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True
    ).stdout
    target = locate_https_vhost(dump)
    original = target.read_bytes()
    patched, changed = patch(original.decode("utf-8"))
    snippet = SOURCE_SNIPPET.read_bytes()
    if SNIPPET.is_symlink():
        raise RuntimeError("Refuse symlinked Hub snippet")
    exists = SNIPPET.exists()
    if exists and SNIPPET.read_bytes() != snippet:
        raise RuntimeError("Existing Hub snippet differs; manual review required")
    if not changed:
        if not exists:
            raise RuntimeError("Hub include exists but snippet is absent")
        print("Director Hub route already configured; unchanged")
        return
    SNIPPET.parent.mkdir(parents=True, exist_ok=True)
    backup_fd, backup = tempfile.mkstemp(
        prefix=".hub-vhost-backup-", dir=str(target.parent)
    )
    os.close(backup_fd)
    shutil.copy2(target, backup)
    created = False
    try:
        if not exists:
            fd = os.open(SNIPPET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as output:
                output.write(snippet)
            created = True
        target.write_text(patched, encoding="utf-8")
        run_check("nginx", "-t")
        run_check("systemctl", "reload", "nginx")
    except Exception:
        target.write_bytes(original)
        if created:
            SNIPPET.unlink(missing_ok=True)
        try:
            run_check("nginx", "-t")
            run_check("systemctl", "reload", "nginx")
        except Exception:
            pass
        raise
    print("Hub HTTPS route configured on", DOMAIN)
    print("Nginx target:", str(target))
    print("Backup:", backup)
    print("Other MCP and mobile routes preserved")


if __name__ == "__main__":
    try:
        apply()
    except (RuntimeError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print("Hub route rejected: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
