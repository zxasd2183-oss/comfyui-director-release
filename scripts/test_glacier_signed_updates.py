"""Regression tests for the offline-key-preserving Glacier update publisher."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from source.scripts import glacier_publish_signed_updates as publisher


def fixture(version="0.17.0"):
    win = {
        "tag_name": f"glacier-v{version}", "published_at": "2026-11-05",
        "assets": [{
            "name": f"GlacierBrowser-v{version}-Windows-Setup-x64.exe",
            "state": "uploaded", "size": 173205726,
            "digest": "sha256:" + "a" * 64,
        }]
    }
    mac = {
        "tag_name": f"glacier-macos-v{version}", "published_at": "2026-11-05",
        "assets": [{
            "name": f"GlacierBrowser-v{version}-macOS-AppleSilicon.dmg",
            "state": "uploaded", "size": 278178200,
            "digest": "sha256:" + "b" * 64,
        }]
    }
    return win, mac


class SignedFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.patch = patch.object(publisher, "PUBLIC", self.pub)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_both_platforms_publish_together_and_are_verified(self):
        windows, mac = fixture()
        self.assertTrue(publisher.render_manifests(
            [mac, windows], self.root, self.key))
        w = json.loads((self.root / "windows-x64.json").read_text())
        m = json.loads((self.root / "macos-arm64.json").read_text())
        self.assertEqual(w["version"], m["version"])
        self.assertEqual(w["channel"], "windows-x64")
        self.assertEqual(m["channel"], "macos-arm64")
        self.assertTrue(w["url"].startswith("https://github.com/"))
        self.assertTrue(m["url"].startswith(
            "https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/glacier-macos-v"))
        self.assertEqual(w["sha256"], "a" * 64)
        self.assertEqual(m["sha256"], "b" * 64)
        self.assertEqual(
            publisher.verify_signed_doc(w)["version"], "0.17.0")
        self.assertFalse(publisher.render_manifests(
            [windows, mac], self.root, self.key))

    def test_one_platform_never_publishes_partial_update(self):
        windows, _ = fixture()
        self.assertFalse(publisher.render_manifests(
            [windows], self.root, self.key))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_newer_version_wins_regardless_of_release_list_order(self):
        first = fixture("0.16.0")
        later = fixture("0.17.0")
        version, _, _ = publisher.release_index([
            later[1], first[0], later[0], first[1]])
        self.assertEqual(version, "0.17.0")

    def test_existing_signed_feed_cannot_be_rolled_back(self):
        win17, mac17 = fixture("0.17.0")
        self.assertTrue(publisher.render_manifests(
            [win17, mac17], self.root, self.key))
        win16, mac16 = fixture("0.16.0")
        with self.assertRaisesRegex(ValueError, "rollback"):
            publisher.render_manifests(
                [win16, mac16], self.root, self.key)

    def test_same_version_different_digest_does_not_replace(self):
        win, mac = fixture()
        publisher.render_manifests([win, mac], self.root, self.key)
        changed_win, changed_mac = fixture()
        changed_win["assets"][0]["digest"] = "sha256:" + "c" * 64
        with self.assertRaisesRegex(ValueError, "same-version"):
            publisher.render_manifests(
                [changed_win, changed_mac], self.root, self.key)

    def test_tampered_existing_feed_is_rejected_and_not_overwritten(self):
        win, mac = fixture()
        publisher.render_manifests([win, mac], self.root, self.key)
        dest = self.root / "windows-x64.json"
        corrupted = json.loads(dest.read_text())
        corrupted["size"] += 1
        original = json.dumps(corrupted)
        dest.write_text(original)
        with self.assertRaises(Exception):
            publisher.render_manifests([win, mac], self.root, self.key)
        self.assertEqual(dest.read_text(), original)

    def test_wrong_signing_key_refused(self):
        other = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()).hex()
        with self.assertRaisesRegex(ValueError, "does NOT match"):
            publisher.signing_key(other)

    def test_missing_signature_key_refused(self):
        with self.assertRaisesRegex(ValueError, "is missing"):
            publisher.signing_key("")

    def test_malformed_signing_secret_refused_without_echoing_it(self):
        bad = "not-the-existing-private-key"
        with self.assertRaisesRegex(ValueError, "invalid format") as result:
            publisher.signing_key(bad)
        self.assertNotIn(bad, str(result.exception))
        self.assertNotIn(self.pub.hex(), str(result.exception))

    def test_invalid_asset_metadata_refused(self):
        win, mac = fixture()
        win["assets"][0]["digest"] = "sha256:" + "bad"
        with self.assertRaisesRegex(ValueError, "digest"):
            publisher.render_manifests([win, mac], self.root, self.key)


if __name__ == "__main__":
    unittest.main()
