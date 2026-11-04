"""Validate fail-closed systemd LoadCredential handling without production keys."""
import os
import tempfile
import unittest
from pathlib import Path
from power_ops import PowerError, read_env_file, read_systemd_credential_env

CFG = {
    "COMP_PUBLIC_KEY":"test-public",
    "COMP_PRIVATE_KEY":"test-private",
    "COMP_UHOST_ID":"uhost-test",
    "COMP_REGION":"cn-sh2",
    "COMP_ZONE":"cn-sh2-01",
}

class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "original.env"
        self.directory = self.root / "credentials"
        self.directory.mkdir(mode=0o700)
        self.runtime = self.directory / "directorenv"
        payload = "\n".join(f"{k}={v}" for k,v in CFG.items())
        self.private.write_text(payload, encoding="utf-8")
        self.runtime.write_text(payload, encoding="utf-8")
        self.private.chmod(0o600)
        self.runtime.chmod(0o444)

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        return read_systemd_credential_env(
            str(self.runtime), str(self.directory), str(self.private),
            expected_source_uid=os.getuid())

    def test_protected_source_and_readable_runtime_copy(self):
        cfg=self.load()
        self.assertEqual(cfg["COMP_REGION"], "cn-sh2")
        self.assertEqual(cfg["COMP_ZONE"], "cn-sh2-01")

    def test_normal_cli_still_rejects_world_readable_file(self):
        with self.assertRaises(PowerError):
            read_env_file(str(self.runtime))

    def test_original_source_must_remain_private(self):
        self.private.chmod(0o644)
        with self.assertRaisesRegex(PowerError,"root-owned and mode 0600"):
            self.load()

    def test_runtime_must_be_inside_credential_directory(self):
        with self.assertRaises(PowerError):
            read_systemd_credential_env(
                str(self.private), str(self.directory), str(self.private),
                expected_source_uid=os.getuid())

    def test_symlink_runtime_denied(self):
        link = self.directory / "directorenv"
        link.unlink()
        link.symlink_to(self.private)
        with self.assertRaises(PowerError):
            self.load()

    def test_runtime_credential_must_have_exact_name(self):
        other=self.directory / "other"
        other.write_text("some key")
        with self.assertRaises(PowerError):
            read_systemd_credential_env(str(other), str(self.directory),
                                        str(self.private),
                                        expected_source_uid=os.getuid())

if __name__=="__main__":
    unittest.main()
