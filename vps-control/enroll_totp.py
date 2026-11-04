#!/usr/bin/env python3
"""Enroll Director VPS owner TOTP in a phone authenticator.

Local-terminal tool only. Never sends or prints a 6-digit OTP. Its QR
contains the existing secret, so show it only in a trusted private SSH session.
No request is created and no GPU power APIs are called.
"""
from __future__ import annotations
import argparse
import base64
import getpass
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import quote

from power_v03 import totp_step

SEED_PATH = "/etc/comfyui-director-otp.seed"


def load_seed(path: str = SEED_PATH, *, required_uid: int = 0) -> str:
    file = Path(path)
    if file.is_symlink():
        raise RuntimeError("OTP seed must not be a symlink")
    info = file.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != required_uid
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise RuntimeError("OTP seed must be a regular root-owned 0600 file")
    value = file.read_text(encoding="ascii").strip().upper()
    if not re.fullmatch(r"[A-Z2-7]{32,}", value):
        raise RuntimeError("OTP seed has an invalid format")
    raw = base64.b32decode(value + "=" * (-len(value) % 8), casefold=False)
    if len(raw) < 20:
        raise RuntimeError("OTP seed is too short")
    return value


def build_totp_uri(secret: str) -> str:
    label = quote("Director VPS:GPU", safe="")
    issuer = quote("Director VPS", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
            "&algorithm=SHA1&digits=6&period=30")


def qr_to_terminal(uri: str) -> bool:
    if not shutil.which("qrencode"):
        return False
    # Send URI via stdin, NOT on the process command line or shell history.
    subprocess.run(["qrencode", "-t", "ANSIUTF8"], input=uri,
                   text=True, check=True, timeout=10)
    return True


def verify_locally(secret: str, code: str, *, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    return totp_step(secret, code, current) is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Local TOTP phone enrollment; never starts the GPU")
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify the code without showing the secret QR")
    args = parser.parse_args()

    if os.geteuid() != 0 or not sys.stdin.isatty():
        print("Use sudo from an interactive, private VPS terminal.", file=sys.stderr)
        return 2
    try:
        secret = load_seed()
    except (OSError, ValueError, RuntimeError):
        print("TOTP seed file invalid or unreadable; credentials were not displayed.",
              file=sys.stderr)
        return 3

    print("Director VPS phone authenticator. GPU will stay OFF.")
    if not args.verify_only:
        print("This QR contains a secret. Do not screenshot or share it.")
        try:
            if not qr_to_terminal(build_totp_uri(secret)):
                print("qrencode is unavailable. Install: sudo apt-get install -y qrencode")
                return 4
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            print("QR display failed; check terminal or qrencode installation.")
            return 5
        print("Scan with a TOTP-capable authenticator: 6 digits / every 30 seconds.")

    try:
        code = getpass.getpass("Enter the current 6-digit code privately (not shown): ")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. No approval or GPU action was created.")
        return 1

    if verify_locally(secret, code):
        print("SUCCESS: phone TOTP code verified locally.")
        print("No power application or GPU action was performed.")
        return 0

    print("Code did not match. Check phone/VPS time synchronization.")
    print("No power application or GPU action was performed.")
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
