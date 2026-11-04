#!/usr/bin/env python3
"""Fail-closed Nginx mobile API routing installer on the owner's VPS.

Edits ONLY the unambiguous existing HTTPS server block for
jipite.borealos.cn. Preserves certificates, HTTP redirect, other virtual hosts
and the root location. Backs up the exact modified file and restores it if
nginx -t or nginx reload fails.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

DOMAIN = "jipite.borealos.cn"
SNIPPET = Path("/etc/nginx/snippets/jipite-mobile.conf")
SOURCE_SNIPPET = Path(__file__).resolve().parent / "nginx-alidns/jipite-mobile.conf"
MARKER = f"include {SNIPPET};"
DOMAIN_RE = re.compile(r"\bserver_name\s+([^;]+);")
LISTEN_TLS_RE = re.compile(r"\blisten\s+[^;]*\bssl\b[^;]*;|\bssl_certificate\s+[^;]+;", re.I)
# Some installations use an SSL reverse proxy on the nonstandard port 8443.
LISTEN_PORT_RE = re.compile(r"\blisten\s+(?:[0-9.]+:|\[::\]:)?(?:443|8443)\s*;", re.I)
SECTION_RE = re.compile(r"(?m)^# configuration file ([^\n]+):\s*$")
SERVER_RE = re.compile(r"\bserver\s*\{")


def masked_nginx(source: str) -> str:
    """Replace Nginx comments/quoted literals by blanks; retain brace offsets."""
    result = list(source)
    quoted = ""
    escaped = False
    comment = False
    for i, char in enumerate(source):
        if comment:
            if char == "\n":
                comment = False
            else:
                result[i] = " "
        elif quoted:
            result[i] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quoted:
                quoted = ""
        elif char == "#":
            comment = True
            result[i] = " "
        elif char in ("'", '"'):
            quoted = char
            result[i] = " "
    return "".join(result)


def server_blocks(source: str):
    masked = masked_nginx(source)
    for match in SERVER_RE.finditer(masked):
        opening = masked.index("{", match.start())
        depth = 1
        closing = opening + 1
        while closing < len(masked) and depth:
            if masked[closing] == "{":
                depth += 1
            elif masked[closing] == "}":
                depth -= 1
            closing += 1
        if depth:
            raise RuntimeError("Unbalanced nginx server block")
        yield (match.start(), closing - 1, masked[match.start():closing])


def sections(dump: str):
    matches = list(SECTION_RE.finditer(dump))
    for index, marker in enumerate(matches):
        name = marker.group(1).strip()
        start = marker.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(dump)
        yield name, dump[start:end]


def locate_https_vhost(dump: str):
    found = []
    for filename, raw in sections(dump):
        for _, _, block in server_blocks(raw):
            hosts = set()
            for names in DOMAIN_RE.findall(block):
                hosts.update(names.split())
            if DOMAIN not in hosts:
                continue
            if LISTEN_TLS_RE.search(block) or LISTEN_PORT_RE.search(block):
                found.append(filename)
    unique = set(found)
    if len(found) != 1 or len(unique) != 1:
        raise RuntimeError(
            "Expected exactly one HTTPS jipite.borealos.cn server block; "
            f"found {len(found)}. Not editing any Nginx file."
        )
    target = Path(found[0]).resolve(strict=True)
    if not target.is_file() or not target.is_relative_to("/etc/nginx"):
        raise RuntimeError("Target is not a regular file under /etc/nginx")
    return target


def insert_route(source: str) -> str:
    candidates = []
    for _, end, block in server_blocks(source):
        names = set()
        for group in DOMAIN_RE.findall(block):
            names.update(group.split())
        if DOMAIN in names and (LISTEN_TLS_RE.search(block) or LISTEN_PORT_RE.search(block)):
            candidates.append((end, block))
    if len(candidates) != 1:
        raise RuntimeError("Cannot uniquely locate HTTPS block in physical Nginx file")
    closing, block = candidates[0]
    if MARKER in source or re.search(r"\blocation\s+[^\n{]*?/api/v1/mobile/", block):
        raise RuntimeError("Mobile route may already exist; refusing duplicate or override")
    # Inserting before the final server } is independent of nested locations.
    return source[:closing] + "\n    " + MARKER + "\n" + source[closing:]


def run_check(*args):
    return subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True)


def apply():
    if os.geteuid() != 0:
        raise RuntimeError("Run as root with sudo")
    run_check("nginx", "-t")
    dump = subprocess.run(["nginx", "-T"], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout
    target = locate_https_vhost(dump)
    original = target.read_bytes()
    patched = insert_route(original.decode("utf-8")).encode("utf-8")
    snippet = SOURCE_SNIPPET.read_bytes()
    if SNIPPET.is_symlink():
        raise RuntimeError("Refusing to overwrite a symlink in /etc/nginx/snippets")
    snippet_existed = SNIPPET.exists()
    if snippet_existed and SNIPPET.read_bytes() != snippet:
        raise RuntimeError("Existing mobile Nginx snippet differs; manual review required")
    SNIPPET.parent.mkdir(parents=True, exist_ok=True)
    fd, backup = tempfile.mkstemp(prefix=".jipite-mobile-backup-", dir=str(target.parent))
    os.close(fd)
    shutil.copy2(target, backup)
    snippet_created = False
    try:
        if not snippet_existed:
            fd = os.open(SNIPPET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as stream:
                stream.write(snippet)
            snippet_created = True
        target.write_bytes(patched)
        run_check("nginx", "-t")
        run_check("systemctl", "reload", "nginx")
    except Exception:
        target.write_bytes(original)
        if snippet_created:
            SNIPPET.unlink(missing_ok=True)
        try:
            run_check("nginx", "-t")
            run_check("systemctl", "reload", "nginx")
        except Exception:
            pass
        raise
    print(f"Nginx route installed in: {target}")
    print(f"Backup: {backup} (root-only; keep for rollback)")
    print("Nginx syntax validated and service reloaded; GPU power settings unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually install route")
    args = parser.parse_args()
    if not args.apply:
        print("Read-only: use --apply to install the Nginx route.")
        return 0
    try:
        apply()
        return 0
    except (RuntimeError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print("ERROR: cannot safely configure Jipite Nginx route: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
