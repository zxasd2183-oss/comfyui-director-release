#!/usr/bin/env python3
"""Fail-closed release promotion gate: independently hash both VPS installers.

Public VPS blobs must match the immutable GitHub Releases API digests before
the existing Ed25519 key may sign VPS-origin update URLs. No deployment access
or signing keys are handled by this file.
"""
import hashlib
import json
import os
import urllib.request
from pathlib import Path

from source.scripts.glacier_publish_signed_updates import (
    make_payloads, release_index, version_tuple,
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("VPS installer unexpectedly redirected")


def verify_installer(url, size, expected_sha):
    if not url.startswith("https://sync.borealos.cn/downloads/"):
        raise ValueError("unexpected VPS download URL")
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "Glacier-VPS-Gate/1"})
    total, digest = 0, hashlib.sha256()
    with opener.open(request, timeout=60) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("untrusted VPS installer response")
        advertised = response.headers.get("Content-Length")
        if advertised is not None and int(advertised) != size:
            raise ValueError("VPS installer Content-Length mismatch")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > size:
                raise ValueError("VPS installer exceeds signed release size")
            digest.update(chunk)
    if total != size or digest.hexdigest() != expected_sha:
        raise ValueError("VPS installer SHA-256/size mismatch")


def check(releases):
    pair = release_index(releases)
    if pair is None:
        return False
    version, windows, macos = pair
    if version_tuple(version) < (0, 20, 10):
        return False
    for channel, doc in make_payloads(version, windows, macos).items():
        verify_installer(doc["url"], doc["size"], doc["sha256"])
        print(f"{channel} v{version}: independent VPS SHA-256 verified", flush=True)
    return True


def main():
    releases = json.loads(Path("releases.json").read_text(encoding="utf-8"))
    ready = False
    try:
        ready = check(releases)
    except Exception as exc:
        # A missing/slow/stale VPS must never cause an unverified signed update.
        print(f"::warning::VPS migration not promoted: {type(exc).__name__}: {exc}", flush=True)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("ready=" + ("1" if ready else "0") + "\n")
    if not ready:
        print("VPS origin signing remains blocked; existing 0.20.9 signed feeds unchanged.")
    else:
        print("Both VPS installers independently hashed; VPS origin signing allowed.")


if __name__ == "__main__":
    main()
