#!/usr/bin/env python3
"""Publish signed Glacier update manifests after BOTH platform Releases exist.

This script is intentionally unable to create or rotate a trust key. The
preexisting Ed25519 private key must be provisioned separately as an Actions
Secret, and its derived public key MUST match the pinned client key.

Input: GitHub releases API JSON. Output: two Ed25519-signed channel JSON files.
It does not contact a network, change the VPS, or install software.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

LEGACY_KEY_ID = "cf9452226375ff7d"
LEGACY_PUBLIC = bytes.fromhex(
    "7c375bfd04b4941a662a9a66e9c3f980653cb01b9e5df286ec651eca84e26dab"
)
NEW_PUBLIC_HEX = os.environ.get("GLACIER_UPDATE_SIGNING_PUBLIC_HEX", "")
if NEW_PUBLIC_HEX:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", NEW_PUBLIC_HEX):
        raise ValueError("New Glacier public key variable has invalid format")
    PUBLIC = bytes.fromhex(NEW_PUBLIC_HEX)
    if PUBLIC == LEGACY_PUBLIC:
        raise ValueError("Refusing reuse of lost legacy Glacier signing key")
    KEY_ID = "v2-" + hashlib.sha256(PUBLIC).hexdigest()[:16]
else:
    PUBLIC = LEGACY_PUBLIC
    KEY_ID = LEGACY_KEY_ID
OWNER_REPO = "zxasd2183-oss/comfyui-director-release"
WIN_PATTERN = re.compile(r"^glacier-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MAC_PATTERN = re.compile(r"^glacier-macos-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
HEX_SHA = re.compile(r"^sha256:([0-9a-f]{64})$")
FIELDS = {
    "channel", "version", "url", "sha256", "size", "notes", "key_id", "signature"
}


def version_tuple(version):
    if not isinstance(version, str) or not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version
    ):
        raise ValueError("Invalid semantic version")
    return tuple(int(x) for x in version.split("."))


def canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def signing_key(raw=None):
    if raw is None:
        raw = os.environ.get("GLACIER_UPDATE_SIGNING_PRIVATE_HEX", "")
    if not raw:
        raise ValueError(
            "GLACIER_UPDATE_SIGNING_PRIVATE_HEX is missing. "
            "Do not create a replacement signing key."
        )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        raise ValueError(
            "GLACIER_UPDATE_SIGNING_PRIVATE_HEX has an invalid format: "
            "expected the original 32-byte Ed25519 private key encoded as "
            "exactly 64 hexadecimal characters, with no prefix, quotes or spaces. "
            "Do not paste the public key or generate a new private key."
        )
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))
    derived = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if derived != PUBLIC:
        raise ValueError("Signing key does NOT match pinned Glacier public key")
    return key


def read_unique(path):
    def unique(pairs):
        out = {}
        for k, val in pairs:
            if k in out:
                raise ValueError("Duplicate JSON key")
            out[k] = val
        return out
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique)


def release_index(releases):
    if not isinstance(releases, list):
        raise ValueError("GitHub release metadata is not an array")
    windows, macs = {}, {}
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if not release.get("published_at"):
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str):
            continue
        for pattern, target in ((WIN_PATTERN, windows), (MAC_PATTERN, macs)):
            m = pattern.fullmatch(tag)
            if m:
                version = ".".join(m.groups())
                if version in target:
                    raise ValueError("Duplicate release version")
                target[version] = release
    common = set(windows).intersection(macs)
    if not common:
        return None
    latest = max(common, key=version_tuple)
    return latest, windows[latest], macs[latest]


def exact_asset(release, expected, max_size):
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Release asset list missing")
    matches = [
        a for a in assets if isinstance(a, dict) and a.get("name") == expected
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one verified release asset: " + expected)
    asset = matches[0]
    match = HEX_SHA.fullmatch(str(asset.get("digest", "")))
    size = asset.get("size")
    if (asset.get("state") != "uploaded" or match is None
            or type(size) is not int or not 1_000_000 <= size <= max_size):
        raise ValueError("Release asset digest, state, or size invalid")
    return size, match.group(1)


def make_payloads(version, windows, mac):
    version_tuple(version)
    win_tag = "glacier-v" + version
    mac_tag = "glacier-macos-v" + version
    if windows.get("tag_name") != win_tag or mac.get("tag_name") != mac_tag:
        raise ValueError("Release version mismatch")
    win_name = f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
    mac_name = f"GlacierBrowser-v{version}-macOS-AppleSilicon.dmg"
    win_size, win_sha = exact_asset(windows, win_name, 1_073_741_824)
    mac_size, mac_sha = exact_asset(mac, mac_name, 1_073_741_824)
    description = (
        "：全新轻量浏览器界面、紧凑标签栏、统一工具中心与纯净新标签页。"
        if version_tuple(version) >= (0, 20, 0) else
        "：标签右键菜单、下载中心搜索筛选、工作区恢复标签自动保存。"
        if version_tuple(version) >= (0, 19, 0) else
        "：双端工作区、标签分组、增强下载管理。"
    )
    notes = f"Glacier Browser v{version}" + description + "双端自动测试通过。"
    # Transitional v0.20.9 remains GitHub-origin so installed v0.20.8
    # clients can authenticate and install the bridge. Later releases may
    # use VPS-origin signed URLs, only after both updaters trust that origin.
    vps_origin = version_tuple(version) >= (0, 20, 10)
    windows_doc = {
        "channel": "windows-x64", "version": version,
        "url": (
            f"https://sync.borealos.cn/downloads/{win_name}" if vps_origin else
            f"https://github.com/{OWNER_REPO}/releases/download/{win_tag}/{win_name}"
        ),
        "sha256": win_sha, "size": win_size,
        "notes": notes,
        "key_id": KEY_ID,
    }
    mac_doc = {
        "channel": "macos-arm64", "version": version,
        "url": (
            f"https://sync.borealos.cn/downloads/{mac_name}" if vps_origin else
            f"https://github.com/{OWNER_REPO}/releases/download/{mac_tag}/{mac_name}"
        ),
        "sha256": mac_sha, "size": mac_size,
        "notes": notes,
        "key_id": KEY_ID,
    }
    return {"windows-x64": windows_doc, "macos-arm64": mac_doc}


def verify_signed_doc(document):
    if not isinstance(document, dict) or set(document) != FIELDS:
        raise ValueError("Unrecognized existing signed manifest fields")
    candidate_key_id = document.get("key_id")
    if candidate_key_id == KEY_ID:
        verify_public = PUBLIC
    elif candidate_key_id == LEGACY_KEY_ID and KEY_ID != LEGACY_KEY_ID:
        # The old key is allowed only to VERIFY the previous signed feed.
        # Only the newly provisioned key signs future v0.18+ releases.
        verify_public = LEGACY_PUBLIC
    else:
        raise ValueError("Existing manifest signing key is unrecognized")
    signature_b64 = document["signature"]
    if not isinstance(signature_b64, str):
        raise ValueError("Manifest signature is not a string")
    signature = base64.b64decode(signature_b64, validate=True)
    if len(signature) != 64:
        raise ValueError("Invalid signature size")
    payload = {k: value for k, value in document.items()
               if k != "signature"}
    Ed25519PublicKey.from_public_bytes(verify_public).verify(
        signature, canonical(payload))
    return payload



def needs_new_signed_release(releases, directory):
    """Preflight immutable signed feeds without trusting reused Release tags.

    An existing signed version MUST NOT be re-signed from a GitHub Release
    whose assets were replaced in place. There is nothing to publish unless
    a strictly newer canonical *paired* Windows+Mac release exists. This
    preflight never edits a feed and still verifies both existing signatures.
    """
    pair = release_index(releases)
    if pair is None:
        return False
    latest, _, _ = pair
    output = Path(directory)
    versions = []
    for channel in ("windows-x64", "macos-arm64"):
        existing = output / (channel + ".json")
        if not existing.is_file():
            if (version_tuple(latest) >= (0, 20, 10)
                    and os.environ.get("GLACIER_VPS_MIGRATION_READY") != "1"):
                print("VPS-origin signing blocked: no verified mirrored installers.")
                return False
            return True
        verified = verify_signed_doc(read_unique(existing))
        if verified.get("channel") != channel:
            raise ValueError("Existing feed channel mismatch")
        versions.append(verified["version"])
    if versions[0] != versions[1]:
        raise ValueError("Existing dual-platform signed feed versions differ")
    if version_tuple(latest) < version_tuple(versions[0]):
        raise ValueError("Refusing signed feed rollback")
    if version_tuple(latest) == version_tuple(versions[0]):
        # Do not trust potentially replaced GitHub assets under the old tag.
        # Stable clients retain the previously signed and pinned payload.
        print("No newer canonical dual-platform release; signed feeds remain immutable.")
        return False
    if (version_tuple(latest) >= (0, 20, 10)
            and os.environ.get("GLACIER_VPS_MIGRATION_READY") != "1"):
        print("VPS-origin signing blocked: paired installer hash preflight incomplete.")
        return False
    return True


def render_manifests(releases, directory, key):
    pair = release_index(releases)
    if pair is None:
        print("No matching dual-platform release; signed feed unchanged.")
        return False
    version, windows, mac = pair
    if (version_tuple(version) >= (0, 20, 10)
            and os.environ.get("GLACIER_VPS_MIGRATION_READY") != "1"):
        raise ValueError("VPS signed release requires explicit bridge-migration approval")
    if NEW_PUBLIC_HEX and version_tuple(version) < (0, 18, 0):
        print("Waiting for BOTH v0.18.0 key-migration installers; old feeds unchanged.")
        return False
    payloads = make_payloads(version, windows, mac)
    output = Path(directory)
    planned = {}
    for channel, payload in payloads.items():
        path = output / (channel + ".json")
        if path.exists():
            previous = verify_signed_doc(read_unique(path))
            if previous.get("channel") != channel:
                raise ValueError("Existing feed channel mismatch")
            ordering = (version_tuple(payload["version"]) >
                        version_tuple(previous["version"]))
            if not ordering:
                if (payload["version"] == previous["version"]
                        and payload["sha256"] == previous["sha256"]
                        and payload["size"] == previous["size"]
                        and payload["url"] == previous["url"]):
                    continue
                raise ValueError("Refusing rollback or same-version asset replacement")
        signed = dict(payload)
        signed["signature"] = base64.b64encode(
            key.sign(canonical(payload))
        ).decode("ascii")
        verify_signed_doc(signed)
        planned[path] = json.dumps(
            signed, sort_keys=True, indent=2, ensure_ascii=False
        ) + "\n"

    if not planned:
        print("Signed update feeds already match latest joint release.")
        return False
    # Validate both manifests BEFORE altering either channel.
    for path, contents in planned.items():
        if path.parent != output:
            raise ValueError("Unexpected signed manifest destination")
        parsed = json.loads(contents)
        verify_signed_doc(parsed)
    output.mkdir(parents=True, exist_ok=True)
    for path, contents in planned.items():
        path.write_text(contents, encoding="utf-8")
    print("Signed Glacier feeds prepared for verified version", version)
    return True


def main(argv):
    if len(argv) != 3:
        raise ValueError("Usage: glacier_publish_signed_updates.py releases.json feed/channels")
    key = signing_key()
    releases = read_unique(argv[1])
    render_manifests(releases, argv[2], key)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as exc:
        print("Glacier signed update publication blocked: " +
              type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(2)
