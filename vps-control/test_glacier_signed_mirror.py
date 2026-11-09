"""Offline regressions: stage immutable releases without publishing unsigned metadata."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FILE = Path(__file__).with_name("sync-glacier-signed-releases.py")
spec = importlib.util.spec_from_file_location("glacier_signed_mirror", FILE)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


def asset(version="0.20.10", channel="macos-arm64", data=b"x" * 100_001):
    tag, suffix = mirror.PLATFORMS[channel]
    return {
        "name": f"GlacierBrowser-v{version}-{suffix}",
        "size": len(data), "state": "uploaded",
        "digest": "sha256:" + hashlib.sha256(data).hexdigest()
    }


class GlacierStageTests(unittest.TestCase):
    def test_legacy_signed_urls_are_not_altered(self):
        self.assertIn("github.com", mirror.BASE)
        self.assertEqual(mirror.semver("0.20.10"), (0, 20, 10))

    def test_canonical_release_pair_selects_highest_shared_version(self):
        releases = []
        for version, channel in (("0.20.9", "windows-x64"),
                                 ("0.20.10", "windows-x64"),
                                 ("0.20.10", "macos-arm64"),
                                 ("0.20.11", "windows-x64")):
            tag, _ = mirror.PLATFORMS[channel]
            releases.append({
                "tag_name": tag + version, "published_at": "2026-11-09T00:00:00Z",
                "draft": False, "prerelease": False, "assets": [asset(version,channel)]
            })
        with patch.object(mirror, "fetch", return_value=io.BytesIO(json.dumps(releases).encode())):
            version, pair = mirror._canonical_release_pair()
        self.assertEqual(version, "0.20.10")
        self.assertEqual(set(pair), set(mirror.PLATFORMS))

    def test_staged_dmg_is_sha256_verified_and_does_not_write_signed_feed(self):
        version = "0.20.10"
        data = b"G" * 1_100_000
        release = {"assets": [asset(version,data=data)]}
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with patch.object(mirror, "fetch", return_value=io.BytesIO(data)):
                mirror._stage_verified_asset(folder, "macos-arm64", version, release)
            actual = folder / asset(version)["name"]
            self.assertEqual(actual.read_bytes(), data)
            self.assertFalse((folder / "macos-arm64.json").exists())
            with patch.object(mirror, "fetch", side_effect=AssertionError("unexpected redownload")):
                mirror._stage_verified_asset(folder, "macos-arm64", version, release)
            with self.assertRaisesRegex(ValueError, "same-version replacement"):
                mirror._stage_verified_asset(folder, "macos-arm64", version,
                    {"assets":[asset(version,data=b"Z"*1_100_000)]})

    def test_mismatched_download_is_never_published(self):
        version = "0.20.10"
        data = b"G"*1_100_000
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            with patch.object(mirror, "fetch", return_value=io.BytesIO(b"B"*1_100_000)):
                with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
                    mirror._stage_verified_asset(folder, "macos-arm64", version,
                                                 {"assets": [asset(version,data=data)]})
            self.assertEqual(list(folder.iterdir()), [])

    def test_untrusted_release_digest_and_replaced_versions_fail(self):
        item = asset()
        item["digest"] = "sha256:" + "bad"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            mirror._verified_release_asset({"assets":[item]}, item["name"])


if __name__ == "__main__":
    unittest.main()
