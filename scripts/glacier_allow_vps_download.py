#!/usr/bin/env python3
"""Build-time, fail-closed Windows downloader compatibility patch.

The source update_core.py is decoded from the repository's existing compressed
module by the Windows build workflow. Keep GitHub origin validation intact and
allow only an exact, versioned Glacier Windows installer path on the owner VPS.
"""
from pathlib import Path
import sys

def patch_core(path):
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    begin = source.index("def validate_release_url(url):")
    end = source.index("def validate_redirect_url(url):", begin)
    before = source[begin:end]
    old_origin = """    if (p.scheme != 'https' or p.hostname != 'github.com' or p.port not in (None, 443)
            or p.username or p.password or p.fragment):"""
    new_origin = """    vps = (
        p.hostname == 'sync.borealos.cn'
        and re.fullmatch(
            r'/downloads/GlacierBrowser-v[0-9]+\.[0-9]+\.[0-9]+-Windows-Setup-x64\.exe',
            p.path,
        ) is not None
    )
    if (p.scheme != 'https' or (p.hostname != 'github.com' and not vps)
            or p.port not in (None, 443) or p.username or p.password
            or p.fragment or p.query):"""
    old_path = """    if not p.path.startswith(RELEASE_PATH_PREFIX) or not p.path.lower().endswith('.exe'):"""
    new_path = """    if not vps and (not p.path.startswith(RELEASE_PATH_PREFIX) or not p.path.lower().endswith('.exe')):"""
    if before.count(old_origin) != 1 or before.count(old_path) != 1:
        raise ValueError("Windows updater source policy changed; refusing unsafe patch")
    after = before.replace(old_origin, new_origin).replace(old_path, new_path)
    if after == before:
        raise ValueError("Updater policy patch not applied")
    p.write_text(source[:begin] + after + source[end:], encoding="utf-8")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: glacier_allow_vps_download.py update_core.py")
    patch_core(sys.argv[1])
