#!/usr/bin/env python3
"""Independent, fail-closed Ed25519 signer for the EXISTING macOS v2 feed.

The canonical GitHub Release DMG must have been fully downloaded and matched
to its GitHub digest/size by CI before GLACIER_MACOS_RELEASE_VERIFIED=1.
Never rewrites the Windows feed or signs a replaced same-version asset.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

from source.scripts import glacier_publish_signed_updates as signed


def newest_macos(releases):
    if not isinstance(releases, list):
        raise ValueError("GitHub Releases must be a list")
    found = {}
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease") or not release.get("published_at"):
            continue
        tag = release.get("tag_name")
        match = signed.MAC_PATTERN.fullmatch(tag) if isinstance(tag, str) else None
        if match:
            version = ".".join(match.groups())
            if version in found:
                raise ValueError("Duplicate immutable macOS Release version")
            found[version] = release
    if not found:
        return None
    version = max(found, key=signed.version_tuple)
    return version, found[version]


def make_macos_payload(version, release):
    if release.get("tag_name") != "glacier-macos-v" + version:
        raise ValueError("Noncanonical macOS Release tag")
    if signed.version_tuple(version) < (0, 20, 10):
        raise ValueError("Independent macOS signer requires VPS-origin client")
    name = f"GlacierBrowser-v{version}-macOS-AppleSilicon.dmg"
    size, digest = signed.exact_asset(release, name, 900_000_000)
    if not signed.KEY_ID.startswith("v2-") or signed.PUBLIC == signed.LEGACY_PUBLIC:
        raise ValueError("Independent macOS signer requires pinned existing v2 key")
    return {
        "channel": "macos-arm64",
        "version": version,
        "url": "https://sync.borealos.cn/downloads/" + name,
        "sha256": digest,
        "size": size,
        "notes": f"Glacier Browser v{version}：macOS Apple Silicon 独立签名更新；安装前确认。",
        "key_id": signed.KEY_ID,
    }


def _read_existing(folder):
    path = Path(folder) / "macos-arm64.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Existing macOS signed feed missing or unsafe; refusing")
    verified = signed.verify_signed_doc(signed.read_unique(path))
    if verified.get("channel") != "macos-arm64":
        raise ValueError("Existing macOS signed feed channel mismatch")
    return path, verified


def pending_macos(releases, directory):
    candidate = newest_macos(releases)
    if candidate is None:
        return False
    version, release = candidate
    path, previous = _read_existing(directory)
    old = signed.version_tuple(previous["version"])
    new = signed.version_tuple(version)
    if new < old:
        return False
    payload = make_macos_payload(version, release)
    if new == old:
        for field in ("url", "size", "sha256", "channel", "key_id"):
            if previous[field] != payload[field]:
                raise ValueError("Refusing same-version signed DMG replacement")
        return False
    return True


def render_macos(releases, directory, key):
    if not pending_macos(releases, directory):
        return False
    if os.environ.get("GLACIER_MACOS_RELEASE_VERIFIED") != "1":
        raise ValueError("macOS full canonical DMG SHA256 verification missing")
    version, release = newest_macos(releases)
    payload = make_macos_payload(version, release)
    path, old = _read_existing(directory)
    if signed.version_tuple(payload["version"]) <= signed.version_tuple(old["version"]):
        raise ValueError("Refusing signed macOS rollback")
    result = dict(payload)
    result["signature"] = base64.b64encode(key.sign(signed.canonical(payload))).decode("ascii")
    signed.verify_signed_doc(result)
    data = json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, prefix=".glacier-mac-signed-",
            encoding="utf-8", delete=False
        ) as handle:
            tmp = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        signed.verify_signed_doc(signed.read_unique(tmp))
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    print(f"macOS-only v{version} Ed25519 feed prepared; Windows feed untouched.")
    return True


def main():
    import sys
    if len(sys.argv) != 3:
        raise ValueError("Usage: glacier_publish_macos_signed.py releases.json feed/channels")
    releases = signed.read_unique(sys.argv[1])
    if not pending_macos(releases, sys.argv[2]):
        print("macOS signed channel already current; no changes.")
        return
    key = signed.signing_key()
    render_macos(releases, sys.argv[2], key)


if __name__ == "__main__":
    import sys
    try:
        main()
    except Exception as exc:
        print("Glacier macOS-only signed update blocked: " +
              type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(2)
