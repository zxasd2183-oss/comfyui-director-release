"""One-action bridge from VERIFIED Glacier OIDC notify to signed VPS mirror.

Import and invoke `queue_signed_mirror()` ONLY in the existing receiver's
already-authorized OIDC request handler. This module does not verify OIDC,
does not expose an HTTP endpoint, and takes no user-controlled arguments.
The old preview sync call stays untouched for legacy clients.
"""
from __future__ import annotations
import subprocess


SYSTEMCTL_COMMAND = (
    "/usr/bin/sudo", "-n", "/usr/bin/systemctl",
    "start", "--no-block", "glacier-signed-mirror.service"
)


def queue_signed_mirror() -> None:
    """Queue only the existing signed mirror unit; fail if sudoers is not ready."""
    subprocess.run(
        SYSTEMCTL_COMMAND, check=True, timeout=10,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
