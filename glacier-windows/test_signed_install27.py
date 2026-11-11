"""Offline Windows Setup launch security tests (no installer is executed)."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import glacier_signed_install27 as installer


class SignedSetupLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = b"Glacier signed Setup test" * 50
        self.version = "0.20.16"
        self.target = self.root / ("GlacierBrowser-v" + self.version + "-Windows-Setup-x64.exe")
        self.target.write_bytes(self.data)
        self.manifest = SimpleNamespace(
            version=self.version,
            url="https://sync.borealos.cn/downloads/" + self.target.name,
            size=len(self.data),
            sha256=hashlib.sha256(self.data).hexdigest(),
        )

    def verify(self, target, manifest):
        return (target.stat().st_size == manifest.size and
                hashlib.sha256(target.read_bytes()).hexdigest() == manifest.sha256)

    @patch.object(installer.subprocess, "Popen")
    def test_launch_only_when_current_cached_installer_matches_signed_manifest(self, popen):
        installer.launch_verified_setup(self.target, self.manifest, self.root, self.verify)
        popen.assert_called_once_with(
            [str(self.target.resolve()), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"],
            cwd=str(self.root.resolve()), shell=False, close_fds=True,
        )

    @patch.object(installer.subprocess, "Popen")
    def test_checksum_failure_blocks_execution(self, popen):
        self.target.write_bytes(b"modified")
        with self.assertRaises(installer.SetupLaunchError):
            installer.launch_verified_setup(self.target, self.manifest, self.root, self.verify)
        popen.assert_not_called()

    @patch.object(installer.subprocess, "Popen")
    def test_wrong_url_is_refused(self, popen):
        self.manifest.url = self.manifest.url.replace(self.version, "0.20.17")
        with self.assertRaises(installer.SetupLaunchError):
            installer.launch_verified_setup(self.target, self.manifest, self.root, self.verify)
        popen.assert_not_called()

    @patch.object(installer.subprocess, "Popen")
    def test_wrong_directory_and_symlink_refused(self, popen):
        other_dir = self.root / "unrelated"
        other_dir.mkdir()
        with self.assertRaises(installer.SetupLaunchError):
            installer.launch_verified_setup(self.target, self.manifest, other_dir, self.verify)
        symlink = other_dir / self.target.name
        try:
            symlink.symlink_to(self.target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks prohibited on host")
        with self.assertRaises(installer.SetupLaunchError):
            installer.launch_verified_setup(symlink, self.manifest, other_dir, self.verify)
        popen.assert_not_called()

    @patch.object(installer.subprocess, "Popen")
    def test_no_integrity_verifier_is_rejected(self, popen):
        for fn in (None, lambda *_: False):
            with self.assertRaises(installer.SetupLaunchError):
                installer.launch_verified_setup(self.target, self.manifest, self.root, fn)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
