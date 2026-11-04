#!/usr/bin/env python3
"""Mirror the owner's immutable, signed Jipite GitHub Releases to the owned VPS.

No secrets, OAuth, GPU APIs, approval operations or arbitrary download URLs.
Only exact Jipite release tags and assets from the configured repository are
considered. All files and the manifest are written atomically.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

REPO = "zxasd2183-oss/comfyui-director-release"
API = "https://api.github.com/repos/" + REPO + "/releases?per_page=40"
RELEASE_BASE = "https://github.com/" + REPO + "/releases/download/"
PUBLIC_BASE = "https://jipite.borealos.cn/app-updates/"
ALLOWED_HOSTS = {
    "api.github.com", "github.com",
    "release-assets.githubusercontent.com", "objects.githubusercontent.com",
}
TAG_RE = re.compile(r"^jipite-v([0-9]+\.[0-9]+\.[0-9]+)$")
DIGEST_RE = re.compile(r"^sha256:([a-fA-F0-9]{64})$")
MIN_BYTES, MAX_BYTES = 100_000, 100_000_000


class StrictRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme != "https" or target.hostname not in ALLOWED_HOSTS:
            raise ValueError("Release redirect escaped the pinned HTTPS allowlist")
        if target.port not in (None, 443) or target.username or target.password:
            raise ValueError("Release redirect URL has an unsupported authority")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(StrictRedirects())


def open_trusted(url: str, timeout: int = 25):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Only trusted HTTPS GitHub release sources are allowed")
    if parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise ValueError("Untrusted HTTPS authority")
    request = urllib.request.Request(url, headers={
        "User-Agent": "Jipite-VPS-Release-Mirror/1.0",
        "Accept": "application/vnd.github+json" if parsed.hostname == "api.github.com"
                  else "application/octet-stream",
    })
    return OPENER.open(request, timeout=timeout)


def select_release(releases):
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        match = TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if not match:
            continue
        version = match.group(1)
        asset_name = f"Jipite-v{version}-Microsoft-connected.apk"
        for asset in release.get("assets", []):
            if not isinstance(asset, dict):
                continue
            url = RELEASE_BASE + tag + "/" + asset_name
            digest = asset.get("digest")
            digest_match = DIGEST_RE.fullmatch(digest) if isinstance(digest, str) else None
            if (asset.get("name") != asset_name or asset.get("state") != "uploaded"
                    or asset.get("browser_download_url") != url or not digest_match
                    or not isinstance(asset.get("size"), int)
                    or not MIN_BYTES <= asset["size"] <= MAX_BYTES):
                continue
            candidates.append({
                "version": version, "asset": asset_name, "source": url,
                "size": asset["size"], "sha256": digest_match.group(1).lower(),
            })
    if not candidates:
        raise RuntimeError("No suitable signed Jipite GitHub Release asset found")
    return max(candidates, key=lambda x: tuple(int(v) for v in x["version"].split(".")))


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mirror(directory: Path):
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("The update state directory must be a real directory")
    lock_path = directory / ".sync.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open_trusted(API) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise RuntimeError("GitHub release metadata response exceeds limit")
        release = select_release(json.loads(raw))
        existing_manifest = directory / "latest.json"
        if existing_manifest.is_file() and not existing_manifest.is_symlink():
            try:
                old_version = json.loads(existing_manifest.read_text())["version"]
                if TAG_RE.fullmatch("jipite-v" + old_version) and (
                    tuple(map(int, release["version"].split("."))) <
                    tuple(map(int, old_version.split(".")))
                ):
                    raise RuntimeError("Refusing a version rollback on the VPS")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise RuntimeError("Existing update manifest is invalid; inspect manually")
        target = directory / release["asset"]
        if target.is_symlink():
            raise RuntimeError("Target APK path is a symlink")
        valid = (target.is_file() and target.stat().st_size == release["size"] and
                 digest_file(target) == release["sha256"])
        if not valid:
            temp_fd, temp_name = tempfile.mkstemp(prefix=".download-", dir=directory)
            temp = Path(temp_name)
            try:
                hasher = hashlib.sha256()
                count = 0
                with os.fdopen(temp_fd, "wb") as output, open_trusted(release["source"]) as source:
                    while True:
                        chunk = source.read(128 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > release["size"] or count > MAX_BYTES:
                            raise RuntimeError("Downloaded APK exceeds the release asset size")
                        output.write(chunk)
                        hasher.update(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if count != release["size"] or hasher.hexdigest() != release["sha256"]:
                    raise RuntimeError("Release APK size or SHA-256 mismatch")
                os.chmod(temp, 0o644)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
        manifest = {
            "schema": 1,
            "version": release["version"],
            "asset": release["asset"],
            "size": release["size"],
            "sha256": release["sha256"],
        }
        data = (json.dumps(manifest, separators=(",", ":")) + "\n").encode("utf-8")
        temp_fd, temp_name = tempfile.mkstemp(prefix=".manifest-", dir=directory)
        temp = Path(temp_name)
        try:
            with os.fdopen(temp_fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp, 0o644)
            os.replace(temp, existing_manifest)
        finally:
            temp.unlink(missing_ok=True)
        print("Jipite mirror ready:", release["version"])
        print("APK:", PUBLIC_BASE + release["asset"])
        print("Manifest:", PUBLIC_BASE + "latest.json")
        print("SHA-256:", release["sha256"])
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("/var/lib/jipite-updates"))
    args = parser.parse_args()
    try:
        mirror(args.directory)
    except Exception as error:
        print("Mirror failed safely: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
