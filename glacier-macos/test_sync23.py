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



class UnreadableVaultFailClosedTests(unittest.TestCase):
    """Damaged local encrypted data must never erase a recoverable cloud backup."""

    def host(self, readonly=True):
        from glacier_sync23 import GlacierSync23
        h = GlacierSync23()
        h._accounts_readonly22 = readonly
        h._accounts_doc22 = {"schema": 1, "accounts": [] if readonly else [EXAMPLE]}
        h._sync_auto_busy23 = False
        h._sync_state23 = {"auto_enabled": True, "approved": True,
                           "vault_passphrase": PASSWORD}
        return h

    def test_readonly_manual_upload_refuses_before_any_remote_request(self):
        h = self.host()
        with patch.object(h, "_sync_transport23") as transport:
            with self.assertRaises(SyncError23) as raised:
                h._sync_push23()
            transport.assert_not_called()
        self.assertIn("已禁止上传", str(raised.exception))
        self.assertEqual(h._accounts_doc22["accounts"], [])

    def test_readonly_auto_sync_refuses_before_any_network_or_mutation(self):
        h = self.host()
        with patch.object(h, "_sync_transport23") as transport:
            h._sync_auto_tick23()
            transport.assert_not_called()
        self.assertFalse(h._sync_auto_busy23)
        self.assertEqual(h._accounts_doc22["accounts"], [])

    def test_healthy_manual_upload_remains_available(self):
        h = self.host(False)
        class FakeTransport:
            def __init__(self):
                self.calls = []
            def call(self, method, route, payload=None):
                self.calls.append((method, route, payload))
                return {"version": 0} if method == "GET" else {"version": 1}
        wire = FakeTransport()
        baseline = []
        with patch.object(h, "_sync_transport23", return_value=wire), \
             patch.object(h, "_sync_space23", return_value="private"), \
             patch.object(h, "_sync_passphrase23", return_value=PASSWORD), \
             patch.object(h, "_sync_mark_baseline23", side_effect=lambda s,v:baseline.append((s,v))), \
             patch.object(h, "_sync_info23"):
            h._sync_push23()
        self.assertEqual(baseline, [("private", 1)])
        self.assertEqual(wire.calls[0][:2], ("GET", "/v1/vault/private"))
        self.assertEqual(wire.calls[1][:2], ("PUT", "/v1/vault/private"))
        self.assertEqual(wire.calls[1][2]["expected_version"], 0)
        cards = decrypt_space23(wire.calls[1][2]["envelope"], "private", PASSWORD)
        self.assertEqual(cards[0]["username"], EXAMPLE["username"])

if __name__ == "__main__":
    unittest.main()
