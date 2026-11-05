"""Glacier Windows updater security regressions, with ephemeral test keys only."""
import base64
import copy
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import secure_update as update


class GlacierUpdateSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = Ed25519PrivateKey.generate()
        cls.pub = cls.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )

    def fixture(self, version="0.18.0"):
        payload = {
            "channel": "windows-x64", "version": version,
            "url": f"https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/glacier-v{version}/GlacierBrowser-v{version}-Windows-Setup-x64.exe",
            "sha256": "0" * 64, "size": 173_205_726,
            "notes": "signed updater test vector",
            "key_id": update.KEY_ID,
        }
        payload["signature"] = base64.b64encode(
            self.key.sign(update.canonical(payload))).decode("ascii")
        return payload

    def parse(self, document):
        with patch.object(update, "PUBLIC_KEY", self.pub):
            return update.parse_manifest(document)

    def test_signed_manifest_accepted(self):
        self.assertEqual(self.parse(self.fixture()).version, "0.18.0")

    def test_checksum_tamper_rejected(self):
        doc = self.fixture()
        doc["sha256"] = "1" * 64
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_version_tamper_rejected(self):
        doc = self.fixture()
        doc["version"] = "0.18.1"
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_unsigned_manifest_rejected(self):
        doc = self.fixture()
        doc.pop("signature")
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_different_key_rejected(self):
        doc = self.fixture()
        doc["key_id"] = "foreign"
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_signed_rollback_is_not_newer(self):
        self.assertFalse(update.newer_than(update.CURRENT_VERSION, "0.17.0"))
        self.assertTrue(update.newer_than("0.17.0", update.CURRENT_VERSION))

    def test_url_redirect_replacement_rejected(self):
        doc = self.fixture()
        doc["url"] = "https://evil.example/setup.exe"
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_same_key_replay_cross_platform_rejected(self):
        doc = self.fixture()
        doc["channel"] = "macos-arm64"
        doc.pop("signature")
        doc["signature"] = base64.b64encode(
            self.key.sign(update.canonical(doc))).decode("ascii")
        with self.assertRaises(update.UpdateError):
            self.parse(doc)


if __name__ == "__main__":
    unittest.main()
