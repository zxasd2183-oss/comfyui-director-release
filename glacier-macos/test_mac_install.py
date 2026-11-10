"""Offline security regression for Mac one-click DMG installation.

Every test uses a generated short-lived signing key and mocked installer launch;
the tests never replace apps or execute the DMG.
"""
import base64
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import mac_install as i
import mac_update_core as u


class MacOneClickInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.apps = self.root / "Applications"
        self.exe = self.apps / "GlacierBrowser.app" / "Contents" / "MacOS" / "GlacierBrowser"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"executable")
        (self.apps / "GlacierBrowser.app" / "Contents" / "Info.plist").write_text("test")
        self.updates = self.root / "updates"
        self.updates.mkdir()
        self.data = b"G" * 1_100_000
        self.dmg = self.updates / "GlacierBrowser-v0.20.17-macOS-AppleSilicon.dmg"
        self.dmg.write_bytes(self.data)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        payload = {
            "channel": "macos-arm64",
            "version": "0.20.17",
            "url": "https://sync.borealos.cn/downloads/" + self.dmg.name,
            "size": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "notes": "One-click install regression",
            "key_id": u.KEY_ID,
        }
        self.manifest = payload.copy()
        self.manifest["signature"] = base64.b64encode(
            self.key.sign(u.canonical(payload))).decode("ascii")

    def test_only_existing_writable_mac_app_can_be_replaced(self):
        self.assertIsNone(i.writable_installed_app(
            self.exe, home=self.root, platform="linux", roots=[self.apps]))
        self.assertEqual(i.writable_installed_app(
            self.exe, home=self.root, platform="darwin", roots=[self.apps]),
            self.apps / "GlacierBrowser.app")
        self.assertIsNone(i.writable_installed_app(
            self.exe, home=self.root, platform="darwin",
            roots=[self.root / "Elsewhere"]))
        with patch.object(i.os, "access", return_value=False):
            self.assertIsNone(i.writable_installed_app(
                self.exe, home=self.root, platform="darwin", roots=[self.apps]))

    def test_symlinked_app_never_qualifies(self):
        link = self.root / "LinkedApplications"
        try:
            link.symlink_to(self.apps, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation not supported")
        linked = link / "GlacierBrowser.app" / "Contents" / "MacOS" / "GlacierBrowser"
        self.assertIsNone(i.writable_installed_app(
            linked, home=self.root, platform="darwin", roots=[link]))

    def test_helper_syntax_and_bounded_commands(self):
        result = subprocess.run(["/bin/bash", "-n"], input=i.INSTALL_HELPER,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/usr/bin/shasum -a 256", i.INSTALL_HELPER)
        self.assertIn("/usr/bin/codesign --verify --deep", i.INSTALL_HELPER)
        self.assertIn("/usr/libexec/PlistBuddy", i.INSTALL_HELPER)
        self.assertIn("/usr/bin/hdiutil attach -readonly", i.INSTALL_HELPER)
        self.assertIn("cn.borealos.glacierbrowser", i.INSTALL_HELPER)
        self.assertNotIn("sudo ", i.INSTALL_HELPER)
        self.assertNotIn("spctl --master-disable", i.INSTALL_HELPER)
        self.assertNotIn("xattr -dr", i.INSTALL_HELPER)

    @patch.object(i.subprocess, "Popen")
    def test_verified_one_click_handoff_uses_fixed_shell_argv(self, popen):
        with patch.object(i.sys, "platform", "darwin"), patch.object(
                i, "writable_installed_app", return_value=self.apps / "GlacierBrowser.app"
            ), patch.object(u, "PUBLIC_KEY", self.public):
            self.assertTrue(i.launch_user_confirmed_install(
                self.manifest, self.dmg, self.updates))
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], "/bin/bash")
        self.assertEqual(args[0][2], str(self.dmg))
        self.assertEqual(args[0][3], self.manifest["sha256"])
        self.assertEqual(args[0][4], str(len(self.data)))
        self.assertEqual(args[0][5], "0.20.17")
        self.assertEqual(args[0][6], str(self.apps / "GlacierBrowser.app"))
        self.assertTrue(kwargs["start_new_session"])
        self.assertFalse(kwargs.get("shell", False))
        scripts = list(self.updates.glob("glacier-install-*.sh"))
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0].read_text(), i.INSTALL_HELPER)

    @patch.object(i.subprocess, "Popen")
    def test_modified_dmg_or_bad_signature_blocks_handoff(self, popen):
        with patch.object(i.sys, "platform", "darwin"), patch.object(
                i, "writable_installed_app", return_value=self.apps / "GlacierBrowser.app"
            ), patch.object(u, "PUBLIC_KEY", self.public):
            self.dmg.write_bytes(b"x" + self.data[1:])
            with self.assertRaises(u.UpdateError):
                i.launch_user_confirmed_install(self.manifest, self.dmg, self.updates)
            self.dmg.write_bytes(self.data)
            self.manifest["signature"] = "bad"
            with self.assertRaises(u.UpdateError):
                i.launch_user_confirmed_install(self.manifest, self.dmg, self.updates)
        popen.assert_not_called()

    @patch.object(i.subprocess, "Popen")
    def test_wrong_directory_and_downgrade_are_rejected(self, popen):
        with patch.object(i.sys, "platform", "darwin"), patch.object(
                i, "writable_installed_app", return_value=self.apps / "GlacierBrowser.app"
            ), patch.object(u, "PUBLIC_KEY", self.public):
            with self.assertRaises(u.UpdateError):
                i.launch_user_confirmed_install(self.manifest, self.dmg, self.root)
            with patch.object(i, "CURRENT_VERSION", "0.20.18"):
                with self.assertRaises(u.UpdateError):
                    i.launch_user_confirmed_install(self.manifest, self.dmg, self.updates)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
