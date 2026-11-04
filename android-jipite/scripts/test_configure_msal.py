"""Offline tests for deterministic MSAL Android client configuration.

No Microsoft accounts are accessed and no private signing key is handled.
"""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

import configure_msal


class SigningConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.old_project = configure_msal.PROJECT
        configure_msal.PROJECT = Path(self.temporary.name)
        self.config_path = configure_msal.PROJECT / "app/src/main/res/raw/msal_config.json"
        self.manifest_path = configure_msal.PROJECT / "app/src/main/AndroidManifest.xml"
        self.config_path.parent.mkdir(parents=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps({"client_id": "00000000-0000-0000-0000-000000000000"}), encoding="utf-8")
        self.manifest_path.write_text(
            '<manifest><activity android:name="com.microsoft.identity.client.BrowserTabActivity" '
            'android:path="/REPLACE_SIGNATURE_HASH"/></manifest>', encoding="utf-8"
        )
        self.hash = base64.b64encode(bytes(range(20))).decode()

    def tearDown(self):
        configure_msal.PROJECT = self.old_project
        self.temporary.cleanup()

    def test_signing_hash_and_redirect_are_encoded_exactly(self):
        client_id = "11111111-1111-4111-8111-111111111111"
        result = configure_msal.configure(client_id, self.hash)
        self.assertEqual(result, self.hash)
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["client_id"], client_id)
        self.assertEqual(config["redirect_uri"],
                         "msauth://cn.borealos.jipite/" + quote(self.hash, safe=""))
        self.assertFalse(config["broker_redirect_uri_registered"])
        self.assertIn('android:path="/' + self.hash + '"',
                      self.manifest_path.read_text(encoding="utf-8"))

    def test_placeholder_client_id_is_rejected(self):
        with self.assertRaises(ValueError):
            configure_msal.configure("00000000-0000-0000-0000-000000000000", self.hash)

    def test_invalid_signing_hash_is_rejected(self):
        with self.assertRaises(ValueError):
            configure_msal.configure("11111111-1111-4111-8111-111111111111", "fake-hash")


if __name__ == "__main__":
    unittest.main()
