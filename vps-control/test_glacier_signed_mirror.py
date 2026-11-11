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
    def test_current_signed_manifest_request_bypasses_intermediary_cache(self):
        a = mirror.signed_manifest_url("windows-x64")
        b = mirror.signed_manifest_url("windows-x64")
        self.assertTrue(a.startswith(mirror.BASE+"windows-x64.json?nonce="))
        self.assertNotEqual(a, b)
        mirror.validate_url(a)
        with self.assertRaises(ValueError):
            mirror.signed_manifest_url("preview-unsigned")

    def test_legacy_signed_urls_are_not_altered(self):
        self.assertTrue(mirror.BASE.startswith("https://raw.githubusercontent.com/"))
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

    def test_windows_stages_newer_unpaired_release_but_not_signed_feed(self):
        """Windows can download v0.20.18 even when macOS latest is 0.20.16."""
        version = "0.20.18"
        data = b"W" * 1_100_000
        releases = [
            {
                "tag_name": "glacier-v0.20.18",
                "published_at": "2026-11-11T01:56:53Z",
                "draft": False, "prerelease": False,
                "assets": [asset(version, "windows-x64", data)],
            },
            {
                "tag_name": "glacier-macos-v0.20.16",
                "published_at": "2026-11-10T15:06:03Z",
                "draft": False, "prerelease": False,
                "assets": [asset("0.20.16", "macos-arm64", data)],
            },
        ]
        requested = []
        def fake_fetch(url):
            requested.append(url)
            if url.endswith("/releases?per_page=100"):
                return io.BytesIO(json.dumps(releases).encode())
            if url.endswith("/GlacierBrowser-v0.20.18-Windows-Setup-x64.exe"):
                return io.BytesIO(data)
            raise AssertionError("Unexpected fetch URL: " + url)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            signed_windows = folder / "windows-x64.json"
            signed_mac = folder / "macos-arm64.json"
            signed_windows.write_bytes(b"previous-signed-windows")
            signed_mac.write_bytes(b"previous-signed-mac")
            with patch.object(mirror, "fetch", side_effect=fake_fetch):
                self.assertEqual(mirror.stage_latest_windows(folder), version)
                self.assertEqual(mirror.stage_latest_windows(folder, version), version)
            target = folder / asset(version, "windows-x64", data)["name"]
            self.assertEqual(target.stat().st_size, len(data))
            self.assertEqual(mirror.sha256(target), hashlib.sha256(data).hexdigest())
            self.assertEqual(signed_windows.read_bytes(), b"previous-signed-windows")
            self.assertEqual(signed_mac.read_bytes(), b"previous-signed-mac")
            self.assertEqual(len([x for x in requested if x.endswith(".exe")]), 1)

    def test_windows_pin_fails_closed_without_requested_canonical_version(self):
        data = b"W" * 1_100_000
        releases = [{
            "tag_name": "glacier-v0.20.18",
            "published_at": "2026-11-11T01:56:53Z",
            "draft": False, "prerelease": False,
            "assets": [asset("0.20.18", "windows-x64", data)],
        }]
        with patch.object(mirror, "fetch",
                          return_value=io.BytesIO(json.dumps(releases).encode())):
            with tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                with self.assertRaisesRegex(ValueError, "requested canonical release"):
                    mirror.stage_latest_windows(folder, "0.20.19")
                self.assertEqual(list(folder.iterdir()), [])

    def test_standalone_windows_rejects_corrupt_release_digest(self):
        version = "0.20.18"
        bad = asset(version, "windows-x64", b"W" * 1_100_000)
        bad["digest"] = "sha256:" + "x" * 64
        releases = [{
            "tag_name": "glacier-v0.20.18",
            "published_at": "2026-11-11T01:56:53Z",
            "draft": False, "prerelease": False, "assets": [bad],
        }]
        with patch.object(mirror, "fetch",
                          return_value=io.BytesIO(json.dumps(releases).encode())):
            with tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    mirror.stage_latest_windows(folder, version)
                self.assertEqual(list(folder.iterdir()), [])

    def test_standalone_windows_does_not_accept_prerelease_or_duplicate(self):
        version = "0.20.18"
        release = {
            "tag_name": "glacier-v0.20.18",
            "published_at": "2026-11-11T01:56:53Z",
            "draft": False, "prerelease": False,
            "assets": [asset(version, "windows-x64", b"W" * 1_100_000)],
        }
        for sample, expected in [
            ([dict(release, prerelease=True)], "no independently"),
            ([release, release], "duplicate canonical"),
        ]:
            with patch.object(mirror, "fetch",
                              return_value=io.BytesIO(json.dumps(sample).encode())):
                with tempfile.TemporaryDirectory() as temp:
                    with self.assertRaisesRegex(ValueError, expected):
                        mirror.stage_latest_windows(Path(temp))
                    self.assertEqual(list(Path(temp).iterdir()), [])

    def test_untrusted_release_digest_and_replaced_versions_fail(self):
        item = asset()
        item["digest"] = "sha256:" + "bad"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            mirror._verified_release_asset({"assets":[item]}, item["name"])


if __name__ == "__main__":
    unittest.main()
