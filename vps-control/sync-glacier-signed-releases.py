#!/usr/bin/env python3
"""Mirror the existing Ed25519-signed Glacier channels and their checked installers.

Never rewrite a signed URL: old clients must continue to verify the original
signature, and new VPS-origin URLs require a NEW signed client release.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = "zxasd2183-oss/comfyui-director-release"
PUB = bytes.fromhex("de5b1b9ebe06382d44528e5b4fae18ef8a71a0f7057bd6c29356b3ce8d4f8995")
KEY_ID = "v2-" + hashlib.sha256(PUB).hexdigest()[:16]
BASE = "https://raw.githubusercontent.com/" + REPO + "/glacier-browser-updates-v2/channels/"
PLATFORMS = {
    "windows-x64": ("glacier-v", "Windows-Setup-x64.exe"),
    "macos-arm64": ("glacier-macos-v", "macOS-AppleSilicon.dmg"),
}
FIELDS = {"channel", "version", "url", "sha256", "size", "notes", "key_id", "signature"}
HOSTS = {"github.com", "api.github.com", "raw.githubusercontent.com", "release-assets.githubusercontent.com",
         "objects.githubusercontent.com", "github-releases.githubusercontent.com"}

def unique(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("duplicate signed JSON field")
        d[k] = v
    return d

def semver(v):
    if not isinstance(v, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", v):
        raise ValueError("invalid semantic version")
    return tuple(map(int, v.split(".")))

def verify(doc, channel):
    if not isinstance(doc, dict) or set(doc) != FIELDS:
        raise ValueError("invalid manifest fields")
    if doc["channel"] != channel or doc["key_id"] != KEY_ID:
        raise ValueError("wrong signing channel/key")
    sig = base64.b64decode(doc["signature"], validate=True)
    if len(sig) != 64:
        raise ValueError("invalid signature length")
    payload = {k: v for k, v in doc.items() if k != "signature"}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode()
    Ed25519PublicKey.from_public_bytes(PUB).verify(sig, raw)
    v = doc["version"]
    semver(v)
    tag, suffix = PLATFORMS[channel]
    name = f"GlacierBrowser-v{v}-{suffix}"
    expected = f"https://github.com/{REPO}/releases/download/{tag}{v}/{name}"
    vps_expected = f"https://sync.borealos.cn/downloads/{name}"
    permitted = expected if semver(v) <= (0, 20, 9) else vps_expected
    if doc["url"] != permitted:
        raise ValueError("noncanonical signed asset URL")
    if not isinstance(doc["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", doc["sha256"]):
        raise ValueError("invalid checksum")
    if type(doc["size"]) is not int or not 1_000_000 <= doc["size"] <= 900_000_000:
        raise ValueError("invalid installer size")
    return name

class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        validate_url(url)
        return super().redirect_request(req, fp, code, msg, headers, url)

def validate_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname not in HOSTS or p.port not in (None, 443) or p.username or p.password or p.fragment:
        raise ValueError("untrusted release origin/redirect")

OPENER = urllib.request.build_opener(HTTPSRedirect())

def fetch(url):
    validate_url(url)
    return OPENER.open(urllib.request.Request(url, headers={"User-Agent": "Glacier-Signed-VPS-Mirror/1",
                                                        "Cache-Control": "no-cache",
                                                        "Pragma": "no-cache"}), timeout=90)

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def save_atomic(target, data):
    fd, temp = tempfile.mkstemp(prefix=".glacier-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)

def signed_manifest_url(channel):
    """Bypass intermediary cache for a fast signed-channel promotion.

    Trust still comes only from the unchanged Ed25519 signature and pinned
    public key, never from the nonce or the unsigned HTTP response.
    """
    if channel not in PLATFORMS:
        raise ValueError("unsupported signed update channel")
    return BASE + channel + ".json?nonce=" + secrets.token_hex(12)


def sync_one(directory, channel):
    with fetch(signed_manifest_url(channel)) as r:
        raw = r.read(65537)
    if len(raw) > 65536:
        raise ValueError("oversize signed manifest")
    doc = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)
    filename = verify(doc, channel)
    target = directory / filename
    manifest = directory / (channel + ".json")
    if target.is_symlink() or manifest.is_symlink():
        raise ValueError("symlink destination forbidden")
    if manifest.exists():
        previous = json.loads(manifest.read_text("utf-8"), object_pairs_hook=unique)
        verify(previous, channel)
        if semver(doc["version"]) < semver(previous["version"]):
            raise ValueError("signed rollback refused")
        if semver(doc["version"]) == semver(previous["version"]) and doc != previous:
            raise ValueError("signed same-version replacement refused")
    if not target.is_file() or target.stat().st_size != doc["size"] or sha256(target) != doc["sha256"]:
        fd, tmp = tempfile.mkstemp(prefix=".glacier-download-", dir=directory)
        try:
            amount, h = 0, hashlib.sha256()
            # The signed public URL may be the VPS itself. Always fetch
            # the immutable upstream release instead; never fetch our own
            # mirror URL (which could be stale or partially staged).
            tag, _ = PLATFORMS[channel]
            upstream = f"https://github.com/{REPO}/releases/download/{tag}{doc['version']}/{filename}"
            with os.fdopen(fd, "wb") as output, fetch(upstream) as source:
                while True:
                    data = source.read(1024 * 1024)
                    if not data:
                        break
                    amount += len(data)
                    if amount > doc["size"]:
                        raise ValueError("oversize installer")
                    h.update(data)
                    output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if amount != doc["size"] or h.hexdigest() != doc["sha256"]:
                raise ValueError("installer SHA-256/size mismatch")
            os.chmod(tmp, 0o644)
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)
    save_atomic(manifest, raw)
    print(f"{channel} {doc['version']} verified: {target}", flush=True)

def _canonical_release_pair():
    """Discover the newest jointly published immutable platform pair.

    Staging unsigned metadata never changes the signed client feed. Each staged
    installer still has to match its canonical GitHub Release asset digest.
    """
    url = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
    with fetch(url) as source:
        raw = source.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("oversized GitHub Releases index")
    releases = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(releases, list):
        raise ValueError("invalid GitHub Releases index")
    by_platform = {channel: {} for channel in PLATFORMS}
    patterns = {
        "windows-x64": re.compile(r"^glacier-v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"),
        "macos-arm64": re.compile(r"^glacier-macos-v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"),
    }
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        if not release.get("published_at"):
            continue
        tag_name = release.get("tag_name")
        if not isinstance(tag_name, str):
            continue
        for channel, pattern in patterns.items():
            match = pattern.fullmatch(tag_name)
            if match:
                version = match.group(1)
                if version in by_platform[channel]:
                    raise ValueError("duplicate canonical release version")
                by_platform[channel][version] = release
    matched = set.intersection(*(set(found) for found in by_platform.values()))
    if not matched:
        return None
    version = max(matched, key=semver)
    return version, {channel: entries[version] for channel, entries in by_platform.items()}


def _verified_release_asset(release, filename):
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("missing GitHub Release assets")
    matches = [asset for asset in assets
               if isinstance(asset, dict) and asset.get("name") == filename]
    if len(matches) != 1:
        raise ValueError("ambiguous canonical release installer")
    asset = matches[0]
    raw_digest = asset.get("digest")
    size = asset.get("size")
    if (asset.get("state") != "uploaded" or not isinstance(raw_digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", raw_digest)
            or type(size) is not int or not 1_000_000 <= size <= 900_000_000):
        raise ValueError("invalid GitHub Release asset SHA-256 or size")
    return size, raw_digest.removeprefix("sha256:")


def _stage_verified_asset(directory, channel, version, release):
    tag, suffix = PLATFORMS[channel]
    filename = f"GlacierBrowser-v{version}-{suffix}"
    size, expected_sha256 = _verified_release_asset(release, filename)
    target = directory / filename
    if target.is_symlink():
        raise ValueError("symlinked installer destination forbidden")
    if target.is_file():
        if target.stat().st_size == size and sha256(target) == expected_sha256:
            print(f"Staged {channel} {version} already verified", flush=True)
            return
        raise ValueError("refusing same-version replacement of staged installer")
    fd, tmp = tempfile.mkstemp(prefix=".glacier-stage-", dir=directory)
    try:
        url = f"https://github.com/{REPO}/releases/download/{tag}{version}/{filename}"
        amount, digest = 0, hashlib.sha256()
        with os.fdopen(fd, "wb") as output, fetch(url) as source:
            while True:
                part = source.read(1024 * 1024)
                if not part:
                    break
                amount += len(part)
                if amount > size:
                    raise ValueError("staged installer larger than release metadata")
                digest.update(part)
                output.write(part)
            output.flush()
            os.fsync(output.fileno())
        if amount != size or digest.hexdigest() != expected_sha256:
            raise ValueError("staged installer hash/size mismatch")
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
        print(f"Staged {channel} {version}: {target}", flush=True)
    finally:
        Path(tmp).unlink(missing_ok=True)


def stage_latest_pair(directory):
    """Pre-download BOTH installers while keeping existing signed manifests intact."""
    pair = _canonical_release_pair()
    if pair is None:
        print("No paired GitHub releases to stage", flush=True)
        return
    version, releases = pair
    # Only stage the VPS migration release and later. Older signed feeds are
    # already mirrored by sync_one; do not rewrite their origin metadata.
    if semver(version) < (0, 20, 10):
        return
    for channel in PLATFORMS:
        _stage_verified_asset(directory, channel, version, releases[channel])


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("/var/lib/glacier-preview-downloads"))
    parser.add_argument("--stage-only", action="store_true",
                        help="Stage the latest paired releases without changing signed metadata")
    args = parser.parse_args()
    directory = args.directory
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("missing or symlinked distribution directory")
    try:
        stage_latest_pair(directory)
    except Exception as exc:
        if args.stage_only:
            raise
        print("Glacier pre-stage deferred: " + str(exc), file=sys.stderr)
    if not args.stage_only:
        for channel in PLATFORMS:
            sync_one(directory, channel)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Glacier signed VPS mirror failed: " + str(exc), file=sys.stderr)
        sys.exit(2)
