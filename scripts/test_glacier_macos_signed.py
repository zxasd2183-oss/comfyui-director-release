"""Offline macOS independent signing regressions: no network or real keys."""
import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from source.scripts import glacier_publish_signed_updates as signed
from source.scripts import glacier_publish_macos_signed as mac


def release(version, digest="a"*64, size=286100000, **kwargs):
    return {
        "tag_name": "glacier-macos-v" + version,
        "draft": False, "prerelease": False,
        "published_at": "2026-11-11T07:00:00Z",
        "assets": [{"name": f"GlacierBrowser-v{version}-macOS-AppleSilicon.dmg",
                    "state": "uploaded", "digest": "sha256:" + digest, "size": size}],
        **kwargs,
    }


class MacOnlySigning(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.id = "v2-" + hashlib.sha256(self.public).hexdigest()[:16]
        for patcher in (
            patch.object(signed, "PUBLIC", self.public),
            patch.object(signed, "KEY_ID", self.id),
            patch.dict(os.environ, {"GLACIER_MACOS_RELEASE_VERIFIED": "1"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_existing("0.20.16")
        self.windows = self.folder / "windows-x64.json"
        self.windows.write_text("windows channel must never change")

    def write_existing(self, version):
        payload = mac.make_macos_payload(version, release(version))
        payload["signature"] = base64.b64encode(
            self.key.sign(signed.canonical(payload))).decode("ascii")
        (self.folder / "macos-arm64.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_independent_macos_update_does_not_wait_for_windows(self):
        newer = release("0.20.17", "9"*64)
        self.assertTrue(mac.pending_macos([newer], self.folder))
        self.assertTrue(mac.render_macos([newer], self.folder, self.key))
        updated = signed.read_unique(self.folder / "macos-arm64.json")
        self.assertEqual(signed.verify_signed_doc(updated)["version"], "0.20.17")
        self.assertEqual(updated["url"], "https://sync.borealos.cn/downloads/"
                         "GlacierBrowser-v0.20.17-macOS-AppleSilicon.dmg")
        self.assertEqual(self.windows.read_text(), "windows channel must never change")
        self.assertFalse(mac.pending_macos([newer], self.folder))

    def test_full_asset_bytes_gate_is_mandatory(self):
        before = (self.folder / "macos-arm64.json").read_bytes()
        with patch.dict(os.environ, {"GLACIER_MACOS_RELEASE_VERIFIED": ""}):
            with self.assertRaisesRegex(ValueError, "full canonical DMG"):
                mac.render_macos([release("0.20.17")], self.folder, self.key)
        self.assertEqual((self.folder / "macos-arm64.json").read_bytes(), before)

    def test_replaced_asset_at_same_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "same-version"):
            mac.pending_macos([release("0.20.16", "b"*64)], self.folder)

    def test_existing_signed_feed_must_verify_before_update(self):
        path = self.folder / "macos-arm64.json"
        doc = json.loads(path.read_text())
        doc["size"] += 99
        path.write_text(json.dumps(doc))
        with self.assertRaises(Exception):
            mac.render_macos([release("0.20.17")], self.folder, self.key)

    def test_drafts_duplicates_and_rollback_are_refused(self):
        self.assertFalse(mac.pending_macos([release("0.20.19", draft=True)], self.folder))
        self.assertFalse(mac.pending_macos([release("0.20.19", prerelease=True)], self.folder))
        self.assertFalse(mac.pending_macos([release("0.20.15")], self.folder))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            mac.pending_macos([release("0.20.17"), release("0.20.17")], self.folder)

    def test_invalid_asset_digest_and_missing_existing_feed(self):
        with self.assertRaises(ValueError):
            mac.pending_macos([release("0.20.17", digest="not-a-sha")], self.folder)
        (self.folder / "macos-arm64.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            mac.pending_macos([release("0.20.17")], self.folder)

if __name__=="__main__":
    unittest.main()
