"""Offline regression tests for Glacier D03 account card privacy and host binding."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl
from glacier_accounts22 import (
    GlacierAccounts22, clean_accounts22, page_site22, safe_site22,
)


class EmptyTabs:
    def count(self):
        return 0


class Host(GlacierAccounts22):
    def __init__(self):
        self.tabs = EmptyTabs()


class AccountCardTests(unittest.TestCase):
    def test_domains_require_exact_sanitized_https_hostname(self):
        self.assertEqual(safe_site22("www.ChatGPT.com"), "chatgpt.com")
        self.assertEqual(page_site22(QUrl("https://chatgpt.com/c/abc")), "chatgpt.com")
        self.assertEqual(page_site22(QUrl("https://www.chatgpt.com/")), "chatgpt.com")
        for url in ("http://chatgpt.com", "https://fakechatgpt.com",
                    "https://user:pass@chatgpt.com", "https://chatgpt.com:444",
                    "file:///secret", "javascript:alert(1)"):
            result = page_site22(QUrl(url))
            self.assertNotEqual(result, "chatgpt.com", url)
        for bad in ("", "chatgpt.com/evil", "chatgpt.com:443", "-bad.com",
                    "localhost", "chatgpt.com@evil.com", "127.0.0.1"):
            self.assertEqual(safe_site22(bad), "", bad)

    def test_schema_rejects_duplicate_bad_domain_and_oversize(self):
        item = {"site": "chatgpt.com", "name": "Personal",
                "username": "example@site.test", "password": "example-pass"}
        self.assertEqual(len(clean_accounts22({"schema": 1, "accounts": [item]})["accounts"]), 1)
        for payload in (
            {"schema": 1, "accounts": [item, item]},
            {"schema": 0, "accounts": [item]},
            {"schema": 1, "accounts": [{**item, "site": "chatgpt.com.evil"}] * 101},
            {"schema": 1, "accounts": [{**item, "site": "http://chatgpt.com"}]},
        ):
            with self.assertRaises(ValueError):
                clean_accounts22(payload)

    def test_duplicate_account_name_normalization(self):
        base = {"site": "chatgpt.com", "name": "Primary",
                "username": "one@example.com", "password": ""}
        for variant in (" Primary ", "primary", "PRIMARY"):
            with self.subTest(name=variant):
                with self.assertRaises(ValueError):
                    clean_accounts22({"schema": 1, "accounts": [
                        base, {**base, "name": variant, "username": "other@example.com"}
                    ]})

    def test_vault_is_encrypted_and_atomically_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Host()
            encrypted = []
            def protect(data):
                encrypted.append(data)
                return b"TEST_ENCRYPTED:" + data[::-1]
            def reveal(data):
                self.assertTrue(data.startswith(b"TEST_ENCRYPTED:"))
                return data.split(b":", 1)[1][::-1]
            host.setup_accounts22(tmp, protect, reveal)
            host._accounts_doc22["accounts"].append({
                "site": "chatgpt.com", "name": "Personal",
                "username": "account@test.invalid", "password": "example-secret"
            })
            host._save_accounts22()
            raw = (Path(tmp) / "accounts-d03.dpapi").read_bytes()
            self.assertNotIn(b"example-secret", raw)
            self.assertNotIn(b"account@test.invalid", raw)
            restored = Host()
            restored.setup_accounts22(tmp, protect, reveal)
            self.assertEqual(restored._accounts_doc22["accounts"], host._accounts_doc22["accounts"])
            self.assertFalse(restored._accounts_readonly22)

    def test_delete_persists_and_failed_write_restores_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Host()
            def protect(data):
                return b"ENCRYPTED:" + data[::-1]
            def reveal(data):
                return data.split(b":", 1)[1][::-1]
            host.setup_accounts22(tmp, protect, reveal)
            record = {"site": "chatgpt.com", "name": "Primary",
                      "username": "example@test.invalid", "password": "secret"}
            host._accounts_doc22["accounts"].append(record)
            host._save_accounts22()
            self.assertTrue(host.delete_account22("chatgpt.com", "Primary"))
            self.assertFalse(host._accounts_doc22["accounts"])
            restored = Host()
            restored.setup_accounts22(tmp, protect, reveal)
            self.assertFalse(restored._accounts_doc22["accounts"])
            restored._accounts_doc22["accounts"].append(record)
            restored._save_accounts22()
            original = restored._accounts_doc22
            restored._accounts_encrypt22 = lambda data: data
            self.assertFalse(restored.delete_account22("chatgpt.com", "Primary"))
            self.assertIs(restored._accounts_doc22, original)

    def test_edit_persists_and_rejects_duplicate_with_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Host()
            def encrypt(data):
                return b"ENCRYPTED:" + data[::-1]
            def decrypt(data):
                return data.split(b":", 1)[1][::-1]
            host.setup_accounts22(tmp, encrypt, decrypt)
            first = {"site": "chatgpt.com", "name": "Personal",
                     "username": "old@test.invalid", "password": "old-secret"}
            second = {"site": "chatgpt.com", "name": "Work",
                      "username": "work@test.invalid", "password": ""}
            host._accounts_doc22["accounts"] = [first, second]
            host._save_accounts22()
            self.assertTrue(host.update_account22(
                "chatgpt.com", "Personal", "Personal", "new@test.invalid", "new-secret"))
            self.assertFalse(host.update_account22(
                "chatgpt.com", "Personal", " work ", "new@test.invalid", "new-secret"))
            reloaded = Host()
            reloaded.setup_accounts22(tmp, encrypt, decrypt)
            self.assertEqual(reloaded._accounts_doc22["accounts"][0]["username"],
                             "new@test.invalid")
            self.assertEqual(reloaded._accounts_doc22["accounts"][0]["password"],
                             "new-secret")
            self.assertEqual(reloaded._accounts_doc22["accounts"][1]["name"], "Work")

    def test_fail_closed_without_encryption(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Host()
            host.setup_accounts22(tmp, lambda data: data, lambda data: data)
            host._accounts_doc22["accounts"].append({
                "site": "chatgpt.com", "name": "Personal",
                "username": "test", "password": ""
            })
            with self.assertRaises(ValueError):
                host._save_accounts22()
            self.assertFalse((Path(tmp) / "accounts-d03.dpapi").exists())


if __name__ == "__main__":
    unittest.main()
