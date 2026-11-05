#!/usr/bin/env python3
"""One-time Glacier Browser Ed25519 update-key migration, on OWNER'S PC ONLY.

Never run inside GitHub Actions, on a VPS, or in ChatGPT. This tool generates
a new key on the owner's trusted computer, stores a local backup restricted to
that user, uploads ONLY the private key to GitHub Actions encrypted Secrets,
and stores the public key in GitHub Actions Variables for v0.18 builds.
The private key is never printed, placed in the repository, or sent to a model.
"""
from __future__ import annotations
import base64
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "zxasd2183-oss/comfyui-director-release"
SECRET = "GLACIER_UPDATE_SIGNING_PRIVATE_HEX"
VARIABLE = "GLACIER_UPDATE_SIGNING_PUBLIC_HEX"
LEGACY_PUBLIC = "7c375bfd04b4941a662a9a66e9c3f980653cb01b9e5df286ec651eca84e26dab"
HOME = Path.home() / ".config" / "glacier-browser" / "signing-v2"
KEY_FILE = HOME / "update-private-key.hex"
PUBLIC_FILE = HOME / "update-public-key.hex"


def gh(*args, input_data=None, allow_missing=False):
    # gh api has explicit REST endpoint URLs and does not support -R.
    command = ["gh", *args]
    if args[0] != "api":
        command.extend(["-R", REPO])
    p = subprocess.run(
        command,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode and not allow_missing:
        # Avoid leaking tokens or private values through CLI stderr.
        raise RuntimeError("GitHub CLI command failed: " + " ".join(args[:2]))
    return p


def private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        HOME.chmod(0o700)
    if KEY_FILE.exists():
        raw = KEY_FILE.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
            raise RuntimeError("Existing local private key is malformed; refusing replacement")
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))
    else:
        if PUBLIC_FILE.exists():
            raise RuntimeError("Public key backup exists but private key is missing; refusing rotation")
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        ).hex()
        fd = os.open(str(KEY_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as dest:
            dest.write(raw + "\n")
    if os.name != "nt":
        KEY_FILE.chmod(0o600)
    pub = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    if pub == LEGACY_PUBLIC:
        raise RuntimeError("Unexpected legacy update public key; aborting")
    if PUBLIC_FILE.exists() and PUBLIC_FILE.read_text().strip() != pub:
        raise RuntimeError("Existing public key backup does not match private key")
    if not PUBLIC_FILE.exists():
        PUBLIC_FILE.write_text(pub + "\n", encoding="ascii")
    return raw, pub


def trigger_bootstrap_builds(pub):
    """Trigger ONLY v0.18 branch builds using public fingerprint markers."""
    fingerprint = hashlib.sha256(bytes.fromhex(pub)).hexdigest()[:24]
    branch = "build/glacier-browser-v0-18-key-migration"
    for folder in ("glacier-macos", "glacier-windows"):
        filename = f"{folder}/.migration-v018-{fingerprint}.txt"
        endpoint = f"repos/{REPO}/contents/{filename}"
        check = gh("api", endpoint + "?ref=" + branch, allow_missing=True)
        if check.returncode == 0:
            print(folder + ": bootstrap marker already exists; existing build may be inspected.")
            continue
        payload = base64.b64encode(
            ("Glacier v0.18 signing public key fingerprint: " + fingerprint + "\n")
            .encode("ascii")
        ).decode("ascii")
        gh(
            "api", "--method", "PUT", endpoint,
            "-f", "message=build(glacier-v0.18): start verified key-migration release",
            "-f", "content=" + payload,
            "-f", "branch=" + branch,
        )
        print(folder + ": verified public-key build triggered.")


def main():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        _ = Ed25519PrivateKey
    except ImportError:
        raise RuntimeError("Install dependency first: python -m pip install cryptography")
    p = gh("repo", "view", "--json", "nameWithOwner")
    if REPO.encode() not in p.stdout:
        raise RuntimeError("Authenticated GitHub access to the expected repository is required")

    # Detect a stale/foreign variable first; never silently rotate an existing
    # v2 trust root once one is published.
    original = gh("variable", "get", VARIABLE, allow_missing=True)
    previous_public = original.stdout.decode("ascii", errors="ignore").strip()
    if original.returncode == 0 and not re.fullmatch(r"[0-9a-fA-F]{64}", previous_public):
        raise RuntimeError("Existing GitHub public variable is malformed; correct it manually")
    if original.returncode != 0 and original.stdout.strip():
        raise RuntimeError("Unable to inspect existing public variable")

    raw, pub = private_key()
    if previous_public and previous_public.lower() != pub.lower():
        raise RuntimeError(
            "GitHub has a DIFFERENT v2 public key. Refusing accidental re-rotation."
        )
    # The private key passes via process stdin, NEVER command arguments or logs.
    gh("secret", "set", SECRET, input_data=raw.encode("ascii"))
    gh("variable", "set", VARIABLE, "--body", pub)
    trigger_bootstrap_builds(pub)
    print("Glacier signing v2 installed for the Windows/macOS migration.")
    print("Public key SHA-256 fingerprint:", hashlib.sha256(bytes.fromhex(pub)).hexdigest()[:24])
    print("Local backup directory:", HOME)
    print("IMPORTANT: Keep the private-key backup safe and never share it.")
    print("New v0.18 builds must pin this public key. Do not publish using legacy key.")
    print("Both platform builds have been triggered. Check GitHub Actions and Releases.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("Glacier key migration stopped: " + str(exc), file=sys.stderr)
        sys.exit(2)
