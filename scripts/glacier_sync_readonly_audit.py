#!/usr/bin/env python3
"""Read-only Glacier Sync backend reconnaissance for the actual owner VPS.

No registration, changes, secret reading, logs, HTTP response bodies, process
arguments, environment variables, or configuration contents.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

HOST = "sync.borealos.cn"
BASES = (f"https://{HOST}", f"https://{HOST}:8443")
PATHS = ("/health", "/v1/session", "/v1/register")
PORTS = frozenset((80, 443, 8443))
UNIT_NAME = re.compile(
    r"(?:glacier[._-]?sync|glacier[._-]?(?:auth|account)|sync[._-]?glacier)", re.I
)


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def probe(url: str, *, opener=None, timeout: float = 4.0) -> dict[str, object]:
    """GET public paths without credentials/redirects/body read."""
    if opener is None:
        opener = urllib.request.build_opener(RejectRedirects())
    req = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "GlacierSyncReadOnlyAudit/1.0"}
    )
    try:
        with opener.open(req, timeout=timeout) as response:
            return {"status": int(response.status)}
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        exc.close()
        return {"status": status}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # No exception messages: proxy URLs or request details may be sensitive.
        return {"error_type": type(exc).__name__}


def run_local_command(args: list[str]) -> str | None:
    try:
        p = subprocess.run(
            args, capture_output=True, text=True, timeout=4, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout[:90000] if p.returncode == 0 else None


def list_services() -> list[str]:
    stdout = run_local_command([
        "systemctl", "list-units", "--all", "--type=service",
        "--plain", "--no-pager", "--no-legend",
    ])
    if stdout is None:
        return []
    names: set[str] = set()
    for line in stdout.splitlines():
        word = line.strip().split(maxsplit=1)[0] if line.strip() else ""
        if word.endswith(".service") and UNIT_NAME.search(word):
            names.add(word[:128])
    return sorted(names)[:20]


def listening_ports() -> list[int]:
    stdout = run_local_command(["ss", "-H", "-ltn"])
    if stdout is None:
        return []
    found: set[int] = set()
    for line in stdout.splitlines():
        fields = line.split()
        if not fields or fields[0] != "LISTEN":
            continue
        for candidate in fields[3:4]:
            m = re.search(r":(\d+)$", candidate)
            if m and int(m.group(1)) in PORTS:
                found.add(int(m.group(1)))
    return sorted(found)


def audit(*, local: bool = True, timeout: float = 4.0) -> dict[str, object]:
    result: dict[str, object] = {
        "target": HOST,
        "note": "Read-only. No tokens, credentials, bodies, or registration attempts.",
        "http": {},
        "local_services": [],
        "local_listening_ports": [],
        "auth_backend_verified": False,
        "invite_issued": False,
        "eight_character_server_policy_verified": False,
    }
    for base in BASES:
        checks = {}
        for path in PATHS:
            checks[path] = probe(base + path, timeout=timeout)
        result["http"][base] = checks
    if local:
        result["local_services"] = list_services()
        result["local_listening_ports"] = listening_ports()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Glacier Sync readonly server audit")
    parser.add_argument("--network-only", action="store_true",
                        help="Skip systemd/socket inventory")
    parser.add_argument("--timeout", type=float, default=4.0,
                        help="Per-URL timeout in seconds")
    args = parser.parse_args(argv)
    if not 0.25 <= args.timeout <= 8:
        parser.error("timeout must be 0.25 to 8 seconds")
    print(json.dumps(
        audit(local=not args.network_only, timeout=args.timeout),
        indent=2, ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
