#!/usr/bin/env python3
"""Setup signed ComfyUI Director updates ON YOUR TRUSTED COMPUTER, NOT THE GPU.

Requires authenticated GitHub CLI (gh) and Python cryptography. The Ed25519
private key remains on your computer and goes only to an encrypted GitHub
Actions repository secret; the public verification key is committed openly.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = "zxasd2183-oss/comfyui-director-release"
OWNER = "zxasd2183-oss"
KEY_DIR = Path.home() / ".config" / "comfyui-director" / "release-signing"
PRIVATE = KEY_DIR / "director_signing.hex"
PUBLIC = KEY_DIR / "director_signing.pub.hex"
PUB_PATH = "bootstrap/trusted_public_key.hex"

def gh(*args, data=None, optional=False):
    p = subprocess.run(["gh", *args], input=data, capture_output=True)
    if p.returncode and not optional:
        err = p.stderr.decode(errors="replace").strip()
        raise RuntimeError("GitHub command failed: " + " ".join(args[:3]) + ": " + err[-350:])
    return p

def create_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    KEY_DIR.chmod(0o700)
    if PRIVATE.exists() != PUBLIC.exists():
        raise RuntimeError("One signing key file missing. Restore the existing key pair; do not rotate silently.")
    if PRIVATE.exists():
        raw = bytes.fromhex(PRIVATE.read_text().strip())
        if len(raw) != 32:
            raise RuntimeError("Invalid private key file")
        key = Ed25519PrivateKey.from_private_bytes(raw)
    else:
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
        fd = os.open(PRIVATE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(raw.hex() + "\n")
    PRIVATE.chmod(0o600)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                          serialization.PublicFormat.Raw).hex()
    if PUBLIC.exists() and PUBLIC.read_text().strip() != pub:
        raise RuntimeError("Public key mismatch; refusing to continue")
    if not PUBLIC.exists():
        PUBLIC.write_text(pub + "\n")
        PUBLIC.chmod(0o644)
    return pub

def commit_public_key(pub):
    endpoint = "repos/" + REPO + "/contents/" + PUB_PATH
    old = gh("api", endpoint, optional=True)
    if not old.returncode:
        existing = base64.b64decode(json.loads(old.stdout)["content"]).decode().strip()
        if existing != pub:
            raise RuntimeError("GitHub already has a DIFFERENT public key. Manual key rotation required.")
        print("Pinned public key already matches GitHub.")
        return
    if "404" not in old.stderr.decode(errors="replace"):
        raise RuntimeError("Cannot read existing public key: " + old.stderr.decode(errors="replace")[-300:])
    encoded = base64.b64encode((pub + "\n").encode()).decode()
    gh("api", "--method", "PUT", endpoint,
       "-f", "message=chore: publish Director public signing key",
       "-f", "content=" + encoded)
    print("Public key committed to repository.")

def configure_pages():
    endpoint = "repos/" + REPO + "/pages"
    old = gh("api", endpoint, optional=True)
    if old.returncode:
        if "404" not in old.stderr.decode(errors="replace"):
            raise RuntimeError("Unable to check Pages: " + old.stderr.decode(errors="replace")[-300:])
        gh("api", "--method", "POST", endpoint, "-f", "build_type=workflow")
        print("GitHub Pages enabled.")
    elif json.loads(old.stdout).get("build_type") != "workflow":
        gh("api", "--method", "PUT", endpoint, "-f", "build_type=workflow")
        print("GitHub Pages switched to Actions.")
    else:
        print("GitHub Pages already configured.")

def main():
    if gh("auth", "status", optional=True).returncode:
        raise RuntimeError("Sign in first with: gh auth login")
    login = gh("api", "user", "--jq", ".login").stdout.decode().strip()
    if login.lower() != OWNER:
        raise RuntimeError("GitHub CLI signed in as " + repr(login) + "; expected " + OWNER)
    gh("repo", "view", REPO, "--json", "name", "--jq", ".name")
    pub = create_keys()
    print("Public key fingerprint:", hashlib.sha256(bytes.fromhex(pub)).hexdigest()[:24])
    gh("secret", "set", "DIRECTOR_SIGNING_PRIVATE_HEX", "-R", REPO,
       data=PRIVATE.read_bytes().strip())
    print("Private key securely installed as Actions Secret; it was NOT displayed.")
    commit_public_key(pub)
    configure_pages()
    gh("workflow", "run", "publish.yml", "-R", REPO, "--ref", "main", "-f", "version=0.3.0")
    print("Release requested. Check: https://github.com/" + REPO + "/actions/workflows/publish.yml")
    print("Public key URL: https://raw.githubusercontent.com/" + REPO + "/main/" + PUB_PATH)
    print("Signed manifest URL: https://zxasd2183-oss.github.io/comfyui-director-release/manifest.json")
    print("Keep private key file safe:", PRIVATE, "(never send to ChatGPT or GPU)")

if __name__ == "__main__":
    try:
        main()
    except ImportError:
        sys.exit("Missing cryptography: install it on your OWN computer: python3 -m pip install cryptography")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit("Setup stopped safely: " + str(error))
