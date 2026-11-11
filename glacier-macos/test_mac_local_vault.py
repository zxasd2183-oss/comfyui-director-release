"""Local macOS vault regression tests; no real Keychain access."""
import os
import stat
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from mac_local_vault import (
    KEY_FILE, NODE_FILE, import_legacy_key, legacy_ciphertext_exists,
    local_key, protect, read_node, write_node,
)


class LocalVaultTests(unittest.TestCase):
    def test_new_install_encrypts_node_and_persists_session(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            node = "vless://00000000-0000-4000-8000-000000000001@test.invalid:443?security=reality"
            write_node(folder, node)
            self.assertEqual(read_node(folder), node)
            self.assertEqual(protect(folder, protect(folder, b"account-token"), True), b"account-token")
            for name in (KEY_FILE, NODE_FILE):
                path = folder / name
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(path.stat().st_uid, os.getuid())
            self.assertNotIn(node.encode(), (folder / NODE_FILE).read_bytes())

    def test_explicit_migration_preserves_original_account_ciphertext(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            key = Fernet.generate_key()
            ciphertext = Fernet(key).encrypt(b"previous-account-data")
            (folder / "accounts-d03.dpapi").write_bytes(ciphertext)
            self.assertTrue(legacy_ciphertext_exists(folder))
            with self.assertRaisesRegex(RuntimeError, "migration"):
                protect(folder, b"new-secret")
            self.assertFalse((folder / KEY_FILE).exists())
            self.assertTrue(import_legacy_key(folder, key.decode()))
            self.assertFalse(import_legacy_key(folder, key.decode()))
            self.assertEqual(protect(folder, ciphertext, decrypt=True), b"previous-account-data")
            self.assertEqual((folder / "accounts-d03.dpapi").read_bytes(), ciphertext)

    def test_reject_overwriting_key_and_do_not_overwrite_legacy(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            old_key = Fernet.generate_key().decode()
            self.assertTrue(import_legacy_key(folder, old_key))
            with self.assertRaisesRegex(RuntimeError, "replace"):
                import_legacy_key(folder, Fernet.generate_key().decode())
            self.assertEqual(local_key(folder), old_key.encode())

    def test_reject_group_readable_or_symlink_key(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            key = folder / KEY_FILE
            key.write_bytes(Fernet.generate_key())
            key.chmod(0o644)
            with self.assertRaises(PermissionError):
                local_key(folder)
            key.unlink()
            outside = folder / "outside"
            outside.write_bytes(Fernet.generate_key())
            key.symlink_to(outside)
            with self.assertRaises((OSError, PermissionError)):
                local_key(folder)

    def test_existing_encrypted_node_cannot_create_new_key(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            path = folder / NODE_FILE
            path.write_bytes(Fernet.generate_key())
            path.chmod(0o600)
            with self.assertRaises(RuntimeError):
                read_node(folder)
            self.assertFalse((folder / KEY_FILE).exists())

    def test_corrupted_ciphertext_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            write_node(folder, "vless://user@host.invalid:443")
            (folder / NODE_FILE).write_bytes(b"corrupted")
            with self.assertRaises(InvalidToken):
                read_node(folder)
            self.assertTrue((folder / KEY_FILE).exists())


if __name__ == "__main__":
    unittest.main()
