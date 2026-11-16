"""Read-only: compare live Glacier VPS feeds to immutable GitHub signed channels.

No OIDC, no VPS mutation, no credentials or cookies. Requires GH_TOKEN only for
GitHub's REST API. Exits nonzero if a channel is stale, rolled back or modified.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from typing import Any

REPO = "zxasd2183-oss/comfyui-director-release"
API = "https://api.github.com/repos/" + REPO + "/"
VPS = "https://sync.borealos.cn/downloads/"
KEY_ID = "v2-259ea4a7b9da4bea"
CHANNELS = (
    ("windows-x64", "glacier-v", "Windows-Setup-x64.exe"),
    ("macos-arm64", "glacier-macos-v", "macOS-AppleSilicon.dmg"),
)
VERSION = re.compile(r"^(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}$")


def version_tuple(value: str):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise RuntimeError("Invalid public version")
    return tuple(map(int, value.split(".")))


def fetch_json(url: str, *, github=False) -> dict[str, Any] | list:
    headers = {"User-Agent": "Glacier-Independent-Public-Feed-Audit/1",
               "Accept": "application/vnd.github+json" if github else "application/json",
               "Cache-Control": "no-cache", "Pragma": "no-cache"}
    if github:
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise RuntimeError("GitHub API token missing")
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(1000001)
    if len(payload) > 1000000:
        raise RuntimeError("Oversized public metadata")
    return json.loads(payload.decode("utf-8"))


def latest_release(releases, prefix):
    candidates = []
    for release in releases:
        if (not isinstance(release, dict) or release.get("draft")
                or release.get("prerelease") or not release.get("published_at")):
            continue
        tag = release.get("tag_name", "")
        if not isinstance(tag, str) or not tag.startswith(prefix):
            continue
        version = tag[len(prefix):]
        try:
            number = version_tuple(version)
        except RuntimeError:
            continue
        candidates.append((number, version, release))
    if not candidates:
        raise RuntimeError("No immutable public Glacier Release for " + prefix)
    return max(candidates, key=lambda row: row[0])[1:]


def validate_feed(channel, version, release, suffix, canonical, live):
    if not isinstance(canonical, dict) or not isinstance(live, dict):
        raise RuntimeError(channel + " invalid feed body")
    if canonical != live:
        raise RuntimeError(channel + " VPS feed differs from pinned canonical source")
    if canonical.get("channel") != channel or canonical.get("key_id") != KEY_ID:
        raise RuntimeError(channel + " signed channel identity mismatch")
    if canonical.get("version") != version:
        raise RuntimeError(channel + " stale or rolled-back desktop version")
    expected_name = "GlacierBrowser-v" + version + "-" + suffix
    expected_url = VPS + expected_name
    if canonical.get("url") != expected_url:
        raise RuntimeError(channel + " installer URL is not expected VPS path")
    signature = canonical.get("signature")
    if not isinstance(signature, str):
        raise RuntimeError(channel + " missing Ed25519 signature")
    try:
        raw_sig = base64.b64decode(signature, validate=True)
    except ValueError as exc:
        raise RuntimeError(channel + " malformed Ed25519 signature") from exc
    if len(raw_sig) != 64:
        raise RuntimeError(channel + " invalid signature byte length")
    assets = [a for a in release.get("assets", []) if a.get("name") == expected_name]
    if len(assets) != 1:
        raise RuntimeError(channel + " missing unique official binary")
    asset = assets[0]
    if (not isinstance(canonical.get("size"), int)
            or canonical.get("size") != asset.get("size")
            or canonical.get("sha256") !=
            str(asset.get("digest", "")).removeprefix("sha256:")):
        raise RuntimeError(channel + " official file size or SHA256 differs")
    return canonical["sha256"]


def verify():
    releases = fetch_json(API + "releases?per_page=100", github=True)
    branch = fetch_json(API + "git/ref/heads/glacier-browser-updates-v2", github=True)
    sha = branch["object"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("Bad pinned signer commit")
    print("Pinned signed feed source", sha[:12], flush=True)
    for channel, prefix, suffix in CHANNELS:
        version, release = latest_release(releases, prefix)
        doc = fetch_json(
            API + "contents/channels/" + channel + ".json?ref=" + sha, github=True)
        if doc.get("encoding") != "base64":
            raise RuntimeError("Unsupported signed GitHub content encoding")
        encoded = doc["content"].replace("\n", "")
        canonical = json.loads(base64.b64decode(encoded, validate=True))
        # Wait briefly for the read-only web cache to converge; never
        # re-sign, reset, publish or POST anything to the VPS.
        for attempt in range(4):
            live = fetch_json(VPS + channel + ".json?nonce=" + str(time.time_ns()))
            if live == canonical:
                break
            if attempt == 3:
                raise RuntimeError(channel + " VPS has not reached latest signed feed")
            time.sleep(4)
        digest = validate_feed(channel, version, release, suffix, canonical, live)
        print("PASS", channel, "v" + version, "VPS == pinned Ed25519 feed;",
              "official installer SHA256", digest, flush=True)


if __name__ == "__main__":
    try:
        verify()
    except Exception as error:
        # No token, account, cookie or HTTP body is written to logs.
        print("FAIL Glacier public feed audit:", type(error).__name__,
              str(error)[:160], file=sys.stderr)
        sys.exit(1)
