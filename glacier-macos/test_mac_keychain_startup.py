"""Startup regression: no implicit macOS Keychain permission dialog."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import mac_platform
from mac_local_vault import read_node, write_node


class StartupWithoutKeychainTests(unittest.TestCase):
    def test_existing_local_vless_is_loaded_without_keychain_access(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            node = "vless://00000000-0000-4000-8000-000000000001@host.invalid:443"
            write_node(directory, node)
            with patch.object(mac_platform, "appdir", return_value=directory), \
                    patch("keyring.get_password", side_effect=AssertionError("Keychain read")), \
                    patch.object(mac_platform.QInputDialog, "getMultiLineText", side_effect=AssertionError("dialog")):
                self.assertEqual(mac_platform.get_link(Mock(), lambda link: link.startswith("vless://")), node)
                self.assertEqual(read_node(directory), node)

    def test_fresh_import_persists_without_keychain_access(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            node = "vless://00000000-0000-4000-8000-000000000001@host.invalid:443"
            app = Mock()
            app.clipboard.return_value.text.return_value = ""
            with patch.object(mac_platform, "appdir", return_value=directory), \
                    patch("keyring.get_password", side_effect=AssertionError("Keychain read")), \
                    patch.object(mac_platform.QInputDialog, "getMultiLineText", return_value=(node, True)):
                self.assertEqual(mac_platform.get_link(app, lambda x: x.startswith("vless://")), node)
            self.assertEqual(read_node(directory), node)

    def test_declining_migration_does_not_read_keychain_or_replace_old_data(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            old_vault = directory / "accounts-d03.dpapi"
            old_vault.write_bytes(b"old-opaque-encrypted-record")
            message = Mock()
            restore_button = object()
            skip_button = object()
            message.addButton.side_effect = [restore_button, skip_button]
            message.clickedButton.return_value = skip_button
            with patch.object(mac_platform, "appdir", return_value=directory), \
                    patch.object(mac_platform, "QMessageBox", return_value=message), \
                    patch("keyring.get_password", side_effect=AssertionError("Keychain read")), \
                    patch.object(mac_platform.QInputDialog, "getMultiLineText", side_effect=AssertionError("unexpected import")):
                self.assertEqual(mac_platform.get_link(Mock(), lambda _: True), "")
            self.assertEqual(old_vault.read_bytes(), b"old-opaque-encrypted-record")
            self.assertFalse((directory / "mac-vault-key-v1").exists())


if __name__ == "__main__":
    unittest.main()
