"""Glacier v0.20.2 account sync release gates.

Only synthetic credentials are used here. No production token, endpoint,
account or vault data is required.
"""
import json
import unittest
from unittest.mock import patch

from glacier_sync23 import (
    SyncError23, decrypt_space23, encrypt_space23, sync_url23,
)
from glacier_sync_auto24 import account_digest24, sync_one_space24
from glacier_accounts22 import extract_code22


EXAMPLE = {
    "site": "example.com", "name": "Sample",
    "username": "fictional@example.com", "password": "dummy-not-a-secret",
    "code_api": "https://codes.example.com/otp", "space": "private",
}
PASSWORD = "fictional-test-passphrase-only"


class VaultInteroperabilityTests(unittest.TestCase):
    def test_encrypted_wire_format_and_round_trip(self):
        encrypted = encrypt_space23([EXAMPLE], "private", PASSWORD)
        wrapper = json.loads(encrypted)
        self.assertEqual(wrapper["format"], "glacier-vault-v1")
        self.assertEqual(wrapper["kdf"], "pbkdf2-sha256-400k")
        self.assertNotIn(EXAMPLE["password"], encrypted)
        cards = decrypt_space23(encrypted, "private", PASSWORD)
        self.assertEqual(cards[0]["username"], EXAMPLE["username"])
        self.assertEqual(cards[0]["code_api"], EXAMPLE["code_api"])

    def test_wrong_passphrase_does_not_decrypt(self):
        encrypted = encrypt_space23([EXAMPLE], "private", PASSWORD)
        with self.assertRaises(SyncError23):
            decrypt_space23(encrypted, "private", "different-test-password")

    def test_cross_space_envelope_never_decrypts(self):
        encrypted = encrypt_space23([EXAMPLE], "private", PASSWORD)
        with self.assertRaises(SyncError23):
            decrypt_space23(encrypted, "work", PASSWORD)
        with self.assertRaises(SyncError23):
            encrypt_space23([EXAMPLE], "work", PASSWORD)

    def test_server_address_requires_https_no_credentials(self):
        self.assertEqual(sync_url23("https://sync.borealos.cn"),
                         "https://sync.borealos.cn")
        for invalid in ("http://sync.borealos.cn",
                        "https://u:p@sync.borealos.cn",
                        "https://sync.borealos.cn/v1/",
                        "https://localhost",
                        "https://sync.borealos.cn/?token=hello"):
            self.assertEqual(sync_url23(invalid), "")


class OtpResponseTests(unittest.TestCase):
    def test_plain_digits_with_whitespace(self):
        self.assertEqual(extract_code22(b"  123456\n"), "123456")

    def test_json_digits_and_unsafe_payloads(self):
        self.assertEqual(extract_code22(b'{"data":{"code":"654321"}}'), "654321")
        self.assertEqual(extract_code22(b'{"code":"not-a-code"}'), "")
        self.assertEqual(extract_code22(b'{"code":"1234567","other":"ignore"}' * 500), "")


class ConflictProtectionTests(unittest.TestCase):
    def test_private_fingerprint_excludes_work_cards(self):
        old = account_digest24([EXAMPLE], "private")
        work = dict(EXAMPLE, space="work", password="different")
        self.assertEqual(old, account_digest24([EXAMPLE, work], "private"))

    @patch("glacier_sync_auto24.SyncTransport23")
    def test_both_sides_changed_requires_manual_resolution(self, transport):
        transport.return_value.call.return_value = {
            "version": 8, "envelope": None,
        }
        baseline = {
            "version": 7,
            "local_hash": account_digest24([], "private"),
        }
        result = sync_one_space24(
            "https://sync.borealos.cn", 18566, "pretend-token",
            "private", [EXAMPLE], baseline, PASSWORD)
        self.assertEqual(result["kind"], "conflict")
        transport.return_value.call.assert_called_once_with(
            "GET", "/v1/vault/private")

    @patch("glacier_sync_auto24.SyncTransport23")
    def test_local_change_upload_uses_expected_version(self, transport):
        transport.return_value.call.side_effect = [
            {"version": 3, "envelope": None},
            {"version": 4},
        ]
        baseline = {
            "version": 3,
            "local_hash": account_digest24([], "private"),
        }
        result = sync_one_space24(
            "https://sync.borealos.cn", 18566, "pretend-token",
            "private", [EXAMPLE], baseline, PASSWORD)
        self.assertEqual(result["kind"], "uploaded")
        self.assertEqual(result["version"], 4)
        path, body = transport.return_value.call.call_args.args[1:]
        self.assertEqual(path, "/v1/vault/private")
        self.assertEqual(body["expected_version"], 3)
        self.assertEqual(
            decrypt_space23(body["envelope"], "private", PASSWORD)[0]["site"],
            EXAMPLE["site"])


if __name__ == "__main__":
    unittest.main()
