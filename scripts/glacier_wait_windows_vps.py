#!/usr/bin/env python3
"""Wait for exact canonical Windows EXE on owner VPS, then verify all bytes.

No VPS token: GitHub Actions polls its public download endpoint after the
existing OIDC notify. A completed 200 HEAD is a hint, never proof: only the
full installer SHA-256/size gate permits Ed25519 publication.

Network/transient 404/502/503/504 are retried within a *bounded* deadline.
Wrong redirect, endpoint, asset size or SHA-256 fails closed immediately.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from source.scripts.glacier_publish_windows_signed import (
    newest_windows, make_windows_payload,
)
from source.scripts.glacier_vps_mirror_gate import NoRedirect, verify_installer

RETRYABLE = {404, 408, 429, 500, 502, 503, 504}


def probe_ready(url, expected_size):
    """Return False only when the mirrored asset isn't publicly ready yet."""
    if not url.startswith("https://sync.borealos.cn/downloads/"):
        raise ValueError("Refusing non-owner VPS download URL")
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": "Glacier-Windows-VPS-Ready/1"},
    )
    try:
        with opener.open(request, timeout=16) as reply:
            if reply.status != 200 or reply.geturl() != url:
                raise ValueError("Unexpected VPS response or redirect")
            advertised = reply.headers.get("Content-Length")
            if advertised is not None:
                if int(advertised) != expected_size:
                    raise ValueError("VPS content length disagrees with canonical Release")
            return True
    except urllib.error.HTTPError as exc:
        if exc.code in RETRYABLE:
            return False
        raise
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLError):
            raise ValueError("VPS TLS certificate validation failed") from exc
        return False
    except TimeoutError:
        return False


def wait_and_verify(payload, timeout_seconds=700, poll_seconds=6, *,
                    probe=probe_ready, verify=verify_installer,
                    clock=time.monotonic, sleep=time.sleep):
    """Retry only readiness; never retry a digest mismatch or redirect."""
    if not 0 <= timeout_seconds <= 720:
        raise ValueError("Invalid bounded timeout")
    if not 1 <= poll_seconds <= 60:
        raise ValueError("Invalid readiness probe interval")
    start = clock()
    attempts = 0
    while True:
        attempts += 1
        if probe(payload["url"], payload["size"]):
            # Cryptographic gate: reads the WHOLE file, not its HEAD metadata.
            verify(payload["url"], payload["size"], payload["sha256"])
            return attempts
        elapsed = clock() - start
        if elapsed >= timeout_seconds:
            raise TimeoutError(
                "Owner VPS installer not ready within bounded window; "
                "nothing signed, scheduled retry remains active")
        wait = min(poll_seconds, timeout_seconds - elapsed)
        print(f"VPS EXE pending: attempt {attempts}, waiting {wait:g}s", flush=True)
        sleep(wait)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--releases", default="releases.json")
    parser.add_argument("--timeout-seconds", type=int, default=700)
    parser.add_argument("--poll-seconds", type=int, default=6)
    args = parser.parse_args(argv)
    releases = json.loads(Path(args.releases).read_text(encoding="utf-8"))
    candidate = newest_windows(releases)
    if candidate is None:
        raise ValueError("No published canonical Windows Release available")
    version, release = candidate
    payload = make_windows_payload(version, release)
    attempts = wait_and_verify(
        payload, timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(
        f"Windows VPS v{version} FULL SHA256/size verified on "
        f"attempt {attempts}; safe to sign.", flush=True,
    )
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("ready=1\n")


if __name__ == "__main__":
    main()
