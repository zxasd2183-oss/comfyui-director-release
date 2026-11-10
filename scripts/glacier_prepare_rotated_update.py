#!/usr/bin/env python3
"""Patch v0.18 binaries' pinned Glacier updater key at build time.

Use only after the owner configures GLACIER_UPDATE_SIGNING_PUBLIC_HEX.
Missing/stale/malformed variables intentionally BLOCK release builds.
No private key is needed or ever available to Windows/Mac build workflows.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

OLD_PUBLIC = "7c375bfd04b4941a662a9a66e9c3f980653cb01b9e5df286ec651eca84e26dab"
OLD_KEY_ID = "cf9452226375ff7d"
VERSION = "0.20.13"


def validate_public(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", raw):
        raise ValueError("GLACIER_UPDATE_SIGNING_PUBLIC_HEX missing or malformed")
    public = raw.lower()
    if public == OLD_PUBLIC or public == "0" * 64:
        raise ValueError("Glacier v0.18 must use a NEW Ed25519 public key")
    return public


def derived_key_id(public):
    return "v2-" + hashlib.sha256(bytes.fromhex(validate_public(public))).hexdigest()[:16]


def rewrite_source(source, platform, public):
    public = validate_public(public)
    kid = derived_key_id(public)
    if platform not in ("windows", "macos"):
        raise ValueError("Unsupported release platform")
    key_quote = "'" if platform == "windows" else '"'
    old_value = f"PUBLIC_KEY = bytes.fromhex({key_quote}{OLD_PUBLIC}{key_quote})"
    new_value = f"PUBLIC_KEY = bytes.fromhex({key_quote}{public}{key_quote})"
    old_id = f"KEY_ID = {key_quote}{OLD_KEY_ID}{key_quote}"
    new_id = f"KEY_ID = {key_quote}{kid}{key_quote}"
    if source.count(old_value) != 1 or source.count(old_id) != 1:
        raise ValueError("Old updater trust root differs from expected: abort build")
    return source.replace(old_value, new_value).replace(old_id, new_id)


def prepare(base, platform, public):
    root = Path(base)
    path = root / ("secure_update.py" if platform == "windows"
                   else "mac_update_core.py")
    source = path.read_text(encoding="utf-8")
    quote = "'" if platform == "windows" else '"'
    if f"CURRENT_VERSION = {quote}{VERSION}{quote}" not in source:
        raise ValueError("Not a Glacier v0.18.0 release source")
    transformed = rewrite_source(source, platform, public)
    if platform == "windows":
        # Keep older Windows installations on the LEGACY channel. Only the
        # manually installed v0.18 client may trust the new v2 feed.
        feed = root / "update_core.py"
        feed_text = feed.read_text(encoding="utf-8")
        legacy = "glacier-browser-updates/channels/windows-x64.json"
        if feed_text.count(legacy) != 1:
            raise ValueError("Windows updater source must point to the expected legacy feed")
        feed.write_text(
            feed_text.replace(legacy,
                              "glacier-browser-updates-v2/channels/windows-x64.json"),
            encoding="utf-8",
        )
    path.write_text(transformed, encoding="utf-8")
    print("Glacier v0.18 updater trust root installed:",
          platform, derived_key_id(public))
    print("Public fingerprint (non-secret):",
          hashlib.sha256(bytes.fromhex(public)).hexdigest()[:24])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: glacier_prepare_rotated_update.py <windows|macos> <source-directory>")
    try:
        prepare(sys.argv[2], sys.argv[1],
                os.environ.get("GLACIER_UPDATE_SIGNING_PUBLIC_HEX", ""))
    except (ValueError, OSError) as exc:
        raise SystemExit("Glacier v0.20 build safely blocked: " + str(exc))
