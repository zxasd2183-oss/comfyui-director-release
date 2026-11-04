"""Offline tests for the Jipite owner-controlled VPS release mirror.

No GitHub requests, no GPU operations, no credentials, no privileged file writes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "sync-jipite-updates.py"
spec = importlib.util.spec_from_file_location("jipite_release_mirror", SOURCE)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


def fixture(version: str, contents: bytes, digest: str | None = None):
    tag = "jipite-v" + version
    name = "Jipite-v" + version + "-Microsoft-connected.apk"
    return [{
        "tag_name": tag,
        "draft": False,
        "assets": [{
            "name": name, "state": "uploaded",
            "browser_download_url": mirror.RELEASE_BASE + tag + "/" + name,
            "size": len(contents),
            "digest": "sha256:" + (digest or hashlib.sha256(contents).hexdigest()),
        }],
    }]


class ReleaseMirrorTests(unittest.TestCase):
    def test_selects_latest_valid_semver_not_lexical(self):
        binary = b"APK!" * 30_000
        releases = (
            fixture("0.9.4", binary) + fixture("0.10.1", binary) +
            [{"tag_name": "glacier-v9.9.9", "assets": []}]
        )
        selected = mirror.select_release(releases)
        self.assertEqual(selected["version"], "0.10.1")

    def test_rejects_redirected_asset_or_digestless_release(self):
        binary = b"APK!" * 30_000
        releases = fixture("0.9.4", binary)
        releases[0]["assets"][0]["browser_download_url"] = "https://evil.example/apk"
        with self.assertRaises(RuntimeError):
            mirror.select_release(releases)
        releases = fixture("0.9.4", binary)
        releases[0]["assets"][0]["digest"] = None
        with self.assertRaises(RuntimeError):
            mirror.select_release(releases)

    def test_mirrors_sha256_and_manifest_atomically(self):
        apk = b"APK!" * 30_000
        payload = json.dumps(fixture("0.9.3", apk)).encode()
        calls = []
        def fake_open(url, timeout=25):
            calls.append(url)
            return io.BytesIO(payload if url == mirror.API else apk)
        with tempfile.TemporaryDirectory() as temp, patch.object(
            mirror, "open_trusted", fake_open
        ):
            directory = Path(temp)
            mirror.mirror(directory)
            manifest = json.loads((directory / "latest.json").read_text())
            self.assertEqual(manifest["schema"], 1)
            self.assertEqual(manifest["version"], "0.9.3")
            self.assertEqual(manifest["size"], len(apk))
            self.assertEqual(manifest["sha256"], hashlib.sha256(apk).hexdigest())
            self.assertEqual((directory / manifest["asset"]).read_bytes(), apk)
            self.assertEqual(len(calls), 2)
            # Repeated sync is idempotent and avoids downloading the same APK.
            mirror.mirror(directory)
            self.assertEqual(len(calls), 3)

    def test_wrong_apk_bytes_do_not_publish_manifest(self):
        apk = b"APK!" * 30_000
        releases = json.dumps(fixture("0.9.3", apk)).encode()
        def fake_open(url, timeout=25):
            return io.BytesIO(releases if url == mirror.API else b"tampered" * 20_000)
        with tempfile.TemporaryDirectory() as temp, patch.object(
            mirror, "open_trusted", fake_open
        ):
            directory = Path(temp)
            with self.assertRaises(RuntimeError):
                mirror.mirror(directory)
            self.assertFalse((directory / "latest.json").exists())
            self.assertFalse(list(directory.glob("*.apk")))

    def test_refuses_downgrade_and_keeps_previous_manifest(self):
        new = b"APK!" * 30_000
        old = b"APK?" * 30_000
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch.object(mirror, "open_trusted",
                lambda url, timeout=25: io.BytesIO(
                    json.dumps(fixture("0.9.5", new)).encode()
                    if url == mirror.API else new
                )):
                mirror.mirror(directory)
            saved = (directory / "latest.json").read_bytes()
            with patch.object(mirror, "open_trusted",
                lambda url, timeout=25: io.BytesIO(
                    json.dumps(fixture("0.9.4", old)).encode()
                    if url == mirror.API else old
                )):
                with self.assertRaises(RuntimeError):
                    mirror.mirror(directory)
            self.assertEqual((directory / "latest.json").read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
