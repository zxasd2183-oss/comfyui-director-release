#!/usr/bin/env python3
"""Stage official Glacier preview installers on the owner's own VPS.

GitHub Actions builds and publishes immutable releases; this *VPS-only* job
fetches them, verifies each release's SHA-256 sidecar, and atomically publishes
a small metadata manifest and installers. No GitHub download URL is ever sent
to browser clients. Unsigned preview metadata is informational ONLY: clients
must not execute or auto-install an asset from it.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "zxasd2183-oss/comfyui-director-release"
RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
GITHUB_BASE = f"https://github.com/{REPO}/releases/download/"
PUBLIC = "https://sync.borealos.cn/downloads/"
TAG = {
    "windows": re.compile(r"^glacier-v(\d+\.\d+\.\d+)-sync-v1-([0-9a-f]{7})$"),
    "macos-arm64": re.compile(r"^glacier-macos-v(\d+\.\d+\.\d+)-sync-v1-([0-9a-f]{7})$"),
}
FILENAME = {
    "windows": "GlacierBrowser-v{}-Windows-Setup-x64.exe",
    "macos-arm64": "GlacierBrowser-v{}-macOS-AppleSilicon.dmg",
}
ALLOW_REDIRECT = frozenset((
    "api.github.com", "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
))
MAX_INSTALLER = 900_000_000
MAX_METADATA = 512_000


def validate_https(url):
    value = urllib.parse.urlsplit(url)
    if (value.scheme != "https" or value.hostname not in ALLOW_REDIRECT
            or value.port not in (None, 443) or value.username or value.password
            or value.fragment):
        raise ValueError("Refused unsafe GitHub release URL/redirect")


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_https(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


HTTP = urllib.request.build_opener(RestrictedRedirect())


def get(url, timeout=30):
    """Retry temporary upstream errors; never retry forbidden redirects/URLs.

    Caller owns the returned response object, so retries occur only while
    establishing the request. Incomplete streams fail closed and are retried
    on the next sync invocation, without publishing partial assets.
    """
    validate_https(url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Glacier-VPS-Release-Mirror/1",
                      "Accept": "application/vnd.github+json"})
    for attempt in range(5):
        try:
            return HTTP.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("Unreachable retry state")


def version_key(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid Glacier version")
    return tuple(map(int, version.split(".")))


def select(releases, platform):
    if not isinstance(releases, list) or len(releases) > 30:
        raise ValueError("Invalid releases index")
    candidates = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") or not item.get("prerelease"):
            continue
        tag = item.get("tag_name", "")
        match = TAG[platform].fullmatch(tag) if isinstance(tag, str) else None
        if not match or item.get("html_url") != (
                f"https://github.com/{REPO}/releases/tag/" + tag):
            continue
        version = match.group(1)
        filename = FILENAME[platform].format(version)
        assets = item.get("assets", [])
        if not isinstance(assets, list) or len(assets) > 30:
            continue
        found = {a.get("name"): a for a in assets if isinstance(a, dict)}
        package = found.get(filename)
        sidecar = found.get(filename + ".sha256")
        if not package or not sidecar:
            continue
        size = package.get("size")
        if type(size) is not int or not 10_000_000 <= size <= MAX_INSTALLER:
            continue
        if (package.get("browser_download_url") != GITHUB_BASE + tag + "/" + filename
                or sidecar.get("browser_download_url")
                != GITHUB_BASE + tag + "/" + filename + ".sha256"):
            continue
        candidates.append((version_key(version), tag, version, filename, size))
    if not candidates:
        return None
    _, tag, version, filename, size = max(candidates)
    return {"platform": platform, "version": version, "tag": tag,
            "filename": filename, "size": size}


def read_checksum(tag, name):
    with get(GITHUB_BASE + tag + "/" + name + ".sha256") as response:
        raw = response.read(1025)
    if len(raw) > 1024:
        raise ValueError("SHA sidecar is too large")
    line = raw.decode("ascii").strip()
    pattern = re.compile(r"^([0-9a-fA-F]{64})\s+\*?" + re.escape(name) + r"$")
    match = pattern.fullmatch(line)
    if not match:
        raise ValueError("Unexpected SHA sidecar")
    return match.group(1).lower()


def sha256_file(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def atomically_write(path, payload):
    fd, name = tempfile.mkstemp(prefix=".glacier-stage-", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, 0o644)
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def mirror_one(directory, record):
    name, size = record["filename"], record["size"]
    expected = read_checksum(record["tag"], name)
    target = directory / name
    if target.is_symlink():
        raise ValueError("Refusing symlink installer target")
    valid = (target.is_file() and target.stat().st_size == size
             and sha256_file(target) == expected)
    if not valid:
        fd, name_temp = tempfile.mkstemp(prefix=".glacier-download-", dir=directory)
        staged = Path(name_temp)
        try:
            digest = hashlib.sha256()
            count = 0
            with os.fdopen(fd, "wb") as output, get(
                    GITHUB_BASE + record["tag"] + "/" + name, 90) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > size:
                        raise ValueError("Download exceeds expected release size")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != size or digest.hexdigest() != expected:
                raise ValueError("Installer checksum mismatch")
            os.chmod(staged, 0o644)
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    return {
        "platform": record["platform"], "version": record["version"],
        "size": size, "sha256": expected,
        "url": PUBLIC + name, "channel": "preview-manual",
    }


def mirror(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Mirror destination must be a real directory")
    fd = os.open(str(directory / ".mirror.lock"),
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with get(RELEASES) as response:
            raw = response.read(MAX_METADATA + 1)
        if len(raw) > MAX_METADATA:
            raise ValueError("GitHub release metadata too large")
        releases = json.loads(raw)
        for platform in ("windows", "macos-arm64"):
            chosen = select(releases, platform)
            if chosen is None:
                print("No supported preview release for", platform)
                continue
            manifest = directory / (platform + "-preview.json")
            if manifest.is_symlink():
                raise ValueError("Refusing symlink manifest")
            if manifest.exists():
                previous = json.loads(manifest.read_text("utf-8"))
                if version_key(chosen["version"]) < version_key(previous["version"]):
                    raise ValueError("Refusing preview version rollback")
            published = mirror_one(directory, chosen)
            atomically_write(manifest, json.dumps(
                published, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            print("Mirrored", platform, chosen["version"], published["url"], flush=True)
    finally:
        os.close(fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path,
                        default=Path("/var/lib/glacier-preview-downloads"))
    args = parser.parse_args()
    try:
        mirror(args.directory)
    except Exception as exc:
        print("Glacier VPS preview mirror refused publishing: " + str(exc),
              file=sys.stderr)
        sys.exit(2)
