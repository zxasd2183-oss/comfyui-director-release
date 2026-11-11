#!/usr/bin/env python3
"""Independently publish the newest Windows Ed25519 update channel.

GitHub Releases supply immutable canonical installers; the signed manifest's
download URL ALWAYS points to the owner VPS. The separate CI gate must first
GET the complete VPS installer and independently verify size + SHA256.

Does not modify the macOS channel, rotate keys, deploy to VPS or bypass the
installed Windows client's pinned v2 Ed25519 trust root.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from source.scripts import glacier_publish_signed_updates as signed


def newest_windows(releases):
    if not isinstance(releases, list):
        raise ValueError("GitHub Releases index is not an array")
    found = {}
    for release in releases:
        if (not isinstance(release, dict) or release.get("draft")
                or release.get("prerelease") or not release.get("published_at")):
            continue
        tag = release.get("tag_name")
        match = signed.WIN_PATTERN.fullmatch(tag) if isinstance(tag, str) else None
        if not match:
            continue
        version = ".".join(match.groups())
        if version in found:
            raise ValueError("Duplicate immutable Windows Release version")
        found[version] = release
    if not found:
        return None
    version = max(found, key=signed.version_tuple)
    return version, found[version]


def make_windows_payload(version, release):
    if release.get("tag_name") != "glacier-v" + version:
        raise ValueError("Noncanonical Windows release tag")
    if signed.version_tuple(version) < (0, 20, 10):
        raise ValueError("Independent Windows signing requires VPS-origin client")
    name = f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
    size, digest = signed.exact_asset(release, name, 900_000_000)
    if not signed.KEY_ID.startswith("v2-") or signed.PUBLIC == signed.LEGACY_PUBLIC:
        raise ValueError("Independent Windows signing requires existing v2 key")
    return {
        "channel": "windows-x64",
        "version": version,
        "url": "https://sync.borealos.cn/downloads/" + name,
        "sha256": digest,
        "size": size,
        "notes": f"Glacier Browser v{version}：Windows 独立签名更新；安装前确认。",
        "key_id": signed.KEY_ID,
    }


def _read_existing(folder):
    file = Path(folder) / "windows-x64.json"
    if not file.exists():
        raise ValueError("Existing Windows signed feed missing; refusing migration")
    verified = signed.verify_signed_doc(signed.read_unique(file))
    if verified["channel"] != "windows-x64":
        raise ValueError("Existing signed feed channel mismatch")
    return file, verified


def pending_windows(releases, directory):
    item = newest_windows(releases)
    if item is None:
        return False
    version, release = item
    file, previous = _read_existing(directory)
    old_version = signed.version_tuple(previous["version"])
    new_version = signed.version_tuple(version)
    if new_version < old_version:
        return False
    candidate = make_windows_payload(version, release)
    if new_version == old_version:
        # Reused mutable Release tags cannot silently replace a signed EXE.
        for field in ("url", "size", "sha256", "channel", "key_id"):
            if candidate[field] != previous[field]:
                raise ValueError("Refusing same-version signed asset replacement")
        return False
    return True


def render_windows(releases, directory, key):
    if not pending_windows(releases, directory):
        return False
    if os.environ.get("GLACIER_WINDOWS_VPS_VERIFIED") != "1":
        raise ValueError("Windows VPS complete SHA256 verification not granted")
    version, release = newest_windows(releases)
    payload = make_windows_payload(version, release)
    file, previous = _read_existing(directory)
    if signed.version_tuple(payload["version"]) <= signed.version_tuple(previous["version"]):
        raise ValueError("Refusing Windows signed feed rollback")
    result = dict(payload)
    result["signature"] = base64.b64encode(
        key.sign(signed.canonical(payload))
    ).decode("ascii")
    signed.verify_signed_doc(result)
    content = json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    # Place and validate the complete signed document before replacing anything.
    if file.is_symlink():
        raise ValueError("Symlinked signed feed is forbidden")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", dir=file.parent, prefix=".glacier-win-signed-",
                encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        signed.verify_signed_doc(signed.read_unique(temporary))
        os.replace(temporary, file)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Windows-only signed VPS channel v{version} prepared; Mac untouched.")
    return True


def main():
    import sys
    if len(sys.argv) != 3:
        raise ValueError("Usage: glacier_publish_windows_signed.py releases.json feed/channels")
    releases = signed.read_unique(sys.argv[1])
    if not pending_windows(releases, sys.argv[2]):
        print("Windows signed channel already current; no changes.")
        return
    key = signed.signing_key()
    render_windows(releases, sys.argv[2], key)


if __name__ == "__main__":
    import sys
    try:
        main()
    except Exception as exc:
        print("Glacier Windows-only signed update blocked: " +
              type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(2)
