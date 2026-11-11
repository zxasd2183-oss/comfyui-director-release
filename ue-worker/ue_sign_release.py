"""Offline trusted release signer for the constrained Windows UE Worker updater.

Release code is treated as bytes, NEVER imported or executed by this signer.
The Ed25519 private key is supplied only via a protected CI secret.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ue_signed_updater import (
    FILES, FORMAT, HEX64, MAX_ARCHIVE, MAX_MEMBER,
    UpdateError, canonical, version_tuple,
)


def build_release(version, source, destination, private_hex, public_hex):
    version_tuple(version)
    if (not isinstance(private_hex, str) or not HEX64.fullmatch(private_hex) or
            not isinstance(public_hex, str) or not HEX64.fullmatch(public_hex)):
        raise UpdateError("release_signing_keys_not_provisioned")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    derived = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    ).hex()
    if derived != public_hex:
        raise UpdateError("signing_key_does_not_match_pinned_public_key")
    source = Path(source)
    target = Path(destination)
    if not source.is_dir() or target.exists():
        raise UpdateError("release_source_missing_or_output_exists")
    prepared = {}
    for filename in FILES:
        path = source / filename
        if path.is_symlink() or not path.is_file():
            raise UpdateError("release_input_missing_" + filename)
        content = path.read_bytes()
        if not 1 <= len(content) <= MAX_MEMBER:
            raise UpdateError("release_script_too_large")
        compile(content, filename, "exec", dont_inherit=True)
        prepared[filename] = content
    if prepared["agent.py"].decode("utf-8").count(
        '"worker_version": "' + version + '"'
    ) != 1:
        raise UpdateError("release_version_does_not_match_worker")

    target.mkdir(parents=True)
    archive_name = "ue-worker-v" + version + ".zip"
    archive_file = target / archive_name
    with zipfile.ZipFile(
        archive_file, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for filename in FILES:
            info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, prepared[filename], compress_type=zipfile.ZIP_DEFLATED)
    data = archive_file.read_bytes()
    if len(data) > MAX_ARCHIVE:
        raise UpdateError("release_archive_too_large")
    payload = {
        "format": FORMAT,
        "version": version,
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "archive_size": len(data),
    }
    document = dict(payload)
    document["signature"] = key.sign(canonical(payload)).hex()
    (target / "channel.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return {
        "version": version,
        "archive_name": archive_name,
        "archive_sha256": payload["archive_sha256"],
        "archive_size": payload["archive_size"],
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        raise SystemExit(
            "usage: python ue_sign_release.py <x.y.z> <trusted_source_dir> <empty_output_dir>"
        )
    result = build_release(
        argv[0], argv[1], argv[2],
        os.environ.get("DIRECTOR_UE_SIGNING_PRIVATE_HEX", ""),
        os.environ.get("DIRECTOR_UE_SIGNING_PUBLIC_HEX", ""),
    )
    # Print hashes and sizes, never the secret signing key.
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
