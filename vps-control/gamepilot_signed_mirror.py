#!/usr/bin/env python3
"""Stage only verified, immutable GamePilot Mac releases in the existing VPS downloads directory.

Deliberately separate from Glacier's signer, channels and key. The public
GitHub Release digest pins the ZIP; GamePilot's independent Ed25519 key
authenticates BOTH the appcast and the exact ZIP bytes before publishing
the mirrored feed. No private keys, tokens, or new HTTP write endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import plistlib
import re
import stat
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = "zxasd2183-oss/comfyui-director-release"
API = "https://api.github.com/repos/" + REPO
FEED_PATH = "updates/gamepilot-macos-arm64.xml"
FEED_NAME = "gamepilot-macos-arm64.xml"
PUBLIC_KEY_B64 = "Gh0zCRJjri1AzmBBRcNOQBZ7rQmd6UReqz25/m8JPwM="
PUB = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64, validate=True))
SPARKLE_NS = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
SIGNED_MARKER = b"<!-- sparkle-signatures:\n"
HOSTS = frozenset({
    "api.github.com", "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
})
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
MAX_ZIP = 200 * 1024 * 1024
MAX_FEED = 64 * 1024


def version_num(text):
    if not isinstance(text, str) or not VERSION.fullmatch(text):
        raise ValueError("Unsafe GamePilot version")
    return tuple(map(int, text.split(".")))


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or
            parsed.port not in (None, 443) or parsed.username or parsed.password or
            parsed.fragment):
        raise ValueError("Untrusted GitHub release origin or redirect")


class AllowedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(AllowedRedirect())


def fetch(url, limit):
    allowed_url(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": "GamePilot-Signed-VPS-Mirror/1",
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
    })
    with OPENER.open(request, timeout=70) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Oversize GitHub metadata")
    return raw


def api_json(endpoint, max_bytes=2_000_000):
    return json.loads(fetch(API + endpoint, max_bytes).decode("utf-8"))


def latest_release():
    listing = api_json("/releases?per_page=100", max_bytes=8_000_000)
    if not isinstance(listing, list):
        raise ValueError("Unexpected GitHub Release index")
    matches = {}
    for item in listing:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease") or not item.get("published_at"):
            continue
        tag = item.get("tag_name", "")
        m = re.fullmatch(r"gamepilot-mac-v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))", tag)
        if m:
            ver = m.group(1)
            if ver in matches:
                raise ValueError("Duplicate immutable GamePilot release")
            matches[ver] = item
    if not matches:
        return None
    ver = max(matches, key=version_num)
    release = matches[ver]
    filename = f"GamePilot-mac-arm64-v{ver}.zip"
    assets = [a for a in release.get("assets", []) if isinstance(a, dict) and a.get("name") == filename]
    if len(assets) != 1:
        raise ValueError("Canonical GamePilot ZIP is missing or duplicated")
    asset = assets[0]
    digest = asset.get("digest", "")
    size = asset.get("size")
    if (asset.get("state") != "uploaded" or
            not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or
            type(size) is not int or not 10_000 <= size <= MAX_ZIP):
        raise ValueError("Invalid canonical ZIP digest or size")
    return ver, filename, size, digest.split(":", 1)[1]


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def validate_zip(path, version):
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if len(names) != len(archive.namelist()):
            raise ValueError("Duplicate ZIP member")
        for info in archive.infolist():
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise ValueError("ZIP must not include symlinks")
            name = info.filename
            parts = name.split("/")
            if (name.startswith("/") or "\\" in name or
                    any(p in ("..", ".") for p in parts)):
                raise ValueError("Unsafe ZIP path")
        meta = plistlib.loads(archive.read("GamePilot.app/Contents/Info.plist"))
        if (meta.get("CFBundleIdentifier") != "cn.gamepilot.unified.mac" or
                meta.get("CFBundleVersion") != version or
                meta.get("SUPublicEDKey") != PUBLIC_KEY_B64 or
                meta.get("SURequireSignedFeed") is not True):
            raise ValueError("GamePilot ZIP identity or update key differs")
        if not any(n.startswith("GamePilot.app/Contents/Frameworks/Sparkle.framework/") for n in names):
            raise ValueError("Signed ZIP contains no Sparkle framework")


def save_atomic(target, raw):
    if target.is_symlink():
        raise ValueError("Symlinked update destination refused")
    fd, temporary = tempfile.mkstemp(prefix=".gamepilot-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def stage_zip(directory, version, filename, size, digest):
    target = directory / filename
    if target.is_symlink():
        raise ValueError("Symlinked GamePilot ZIP destination")
    if target.is_file():
        if target.stat().st_size != size or sha256_file(target) != digest:
            raise ValueError("Refusing replacement of altered immutable ZIP")
        validate_zip(target, version)
        return target
    fd, tmp = tempfile.mkstemp(prefix=".gamepilot-download-", dir=directory)
    try:
        source_url = f"https://github.com/{REPO}/releases/download/gamepilot-mac-v{version}/{filename}"
        allowed_url(source_url)
        request = urllib.request.Request(source_url, headers={"User-Agent": "GamePilot-Signed-VPS-Mirror/1"})
        total = 0
        actual = hashlib.sha256()
        with os.fdopen(fd, "wb") as output, OPENER.open(request, timeout=90) as source:
            while piece := source.read(1024 * 1024):
                total += len(piece)
                if total > size:
                    raise ValueError("GamePilot ZIP exceeds canonical size")
                actual.update(piece)
                output.write(piece)
            output.flush()
            os.fsync(output.fileno())
        if total != size or actual.hexdigest() != digest:
            raise ValueError("Canonical GitHub Release ZIP SHA256 mismatch")
        validate_zip(Path(tmp), version)
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return target


def signed_feed(xml):
    if not xml or len(xml) > MAX_FEED:
        raise ValueError("GamePilot signed XML missing or oversized")
    content, marker, suffix = xml.partition(SIGNED_MARKER)
    if not marker:
        raise ValueError("Unsigned GamePilot appcast rejected")
    match = re.fullmatch(
        rb"edSignature: ([A-Za-z0-9+/=]+)\nlength: ([0-9]+)\n-->\n?", suffix
    )
    if not match or int(match.group(2)) != len(content):
        raise ValueError("Invalid signed appcast envelope")
    signature = base64.b64decode(match.group(1), validate=True)
    if len(signature) != 64:
        raise ValueError("Invalid appcast signature length")
    PUB.verify(signature, content)
    root = ET.fromstring(content)
    if root.tag != "rss":
        raise ValueError("Invalid appcast root")
    items = root.findall("./channel/item")
    if len(items) != 1:
        raise ValueError("Exactly one signed GamePilot release is required")
    enclosures = items[0].findall("./enclosure")
    if len(enclosures) != 1:
        raise ValueError("Ambiguous signed update ZIP")
    entry = enclosures[0].attrib
    version = entry.get(SPARKLE_NS + "version", "")
    version_num(version)
    name = f"GamePilot-mac-arm64-v{version}.zip"
    url = entry.get("url")
    expected = f"https://sync.borealos.cn/downloads/{name}"
    if url != expected:
        # v0.4.1 is a legitimate signed legacy feed but still points to
        # GitHub. Stage the ZIP only; never expose this broken VPS feed.
        raise ValueError("Not yet a VPS-origin signed GamePilot update")
    try:
        size = int(entry.get("length", ""))
    except ValueError:
        raise ValueError("Non-numeric signed ZIP length") from None
    if not 10_000 <= size <= MAX_ZIP:
        raise ValueError("Unsafe signed ZIP size")
    sig = base64.b64decode(entry.get(SPARKLE_NS + "edSignature", ""), validate=True)
    if len(sig) != 64:
        raise ValueError("Invalid signed ZIP signature")
    return version, name, size, sig


def fetch_appcast():
    doc = api_json("/contents/" + FEED_PATH + "?ref=main", max_bytes=150_000)
    if doc.get("encoding") != "base64":
        raise ValueError("Unsupported GitHub appcast representation")
    return base64.b64decode(doc["content"], validate=False)


def sync(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("GamePilot mirror directory missing or symlinked")
    release = latest_release()
    if release is None:
        print("GamePilot: no published stable release", flush=True)
        return False
    version, filename, size, digest = release
    zip_path = stage_zip(directory, version, filename, size, digest)
    print(f"GamePilot {version}: canonical ZIP SHA256 verified", flush=True)
    try:
        xml = fetch_appcast()
        feed_version, feed_filename, feed_size, zip_signature = signed_feed(xml)
    except ValueError as exc:
        print(f"GamePilot feed not yet VPS-ready: {exc}", flush=True)
        return False
    if (feed_version != version or feed_filename != filename or feed_size != size):
        print("GamePilot: release staged, waiting for matching signed VPS feed", flush=True)
        return False
    # Verify the archive signature against the exact independently hashed bytes.
    PUB.verify(zip_signature, zip_path.read_bytes())
    feed_file = directory / FEED_NAME
    if feed_file.is_symlink():
        raise ValueError("Symlinked GamePilot feed destination refused")
    if feed_file.exists():
        old = feed_file.read_bytes()
        old_version, _, _, _ = signed_feed(old)
        if version_num(feed_version) < version_num(old_version):
            raise ValueError("GamePilot signed rollback refused")
        if feed_version == old_version and old != xml:
            raise ValueError("GamePilot same-version signed feed replacement refused")
        if old == xml:
            return True
    save_atomic(feed_file, xml)
    print(f"GamePilot {version}: signed VPS XML and ZIP published", flush=True)
    return True


if __name__ == "__main__":
    import sys
    try:
        sync(Path("/var/lib/glacier-preview-downloads"))
    except Exception as exc:
        print(f"GamePilot verified mirror refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
