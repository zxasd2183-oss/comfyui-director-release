"""Fail-closed regression checks for v0.18 client public-key migration."""
from __future__ import annotations
import hashlib
import tempfile
import unittest
from pathlib import Path

from source.scripts import glacier_prepare_rotated_update as migrate


class ClientKeyMigrationTests(unittest.TestCase):
    PUB = "a1" * 32

    def test_public_validation_requires_new_strict_hex_key(self):
        for bad in ("", "hello", migrate.OLD_PUBLIC, "0" * 64, "a" * 63, "g" * 64):
            with self.assertRaises(ValueError):
                migrate.validate_public(bad)
        self.assertEqual(migrate.validate_public(self.PUB.upper()), self.PUB)

    def test_key_id_is_stable_public_fingerprint(self):
        self.assertEqual(migrate.derived_key_id(self.PUB),
                         "v2-" + hashlib.sha256(bytes.fromhex(self.PUB)).hexdigest()[:16])

    def test_both_platforms_pin_same_new_public_key_and_version(self):
        for platform, quote in (("windows", "'"), ("macos", '"')):
            sample = (
                f"CURRENT_VERSION = {quote}0.18.0{quote}\n"
                f"KEY_ID = {quote}{migrate.OLD_KEY_ID}{quote}\n"
                f"PUBLIC_KEY = bytes.fromhex({quote}{migrate.OLD_PUBLIC}{quote})\n"
            )
            rewritten = migrate.rewrite_source(sample, platform, self.PUB)
            self.assertIn(f"PUBLIC_KEY = bytes.fromhex({quote}{self.PUB}{quote})", rewritten)
            self.assertIn(migrate.derived_key_id(self.PUB), rewritten)
            self.assertNotIn(migrate.OLD_PUBLIC, rewritten)

    def test_mismatch_fails_not_silent(self):
        with self.assertRaises(ValueError):
            migrate.rewrite_source("PUBLIC_KEY = bytes.fromhex('changed')", "windows", self.PUB)

    def test_refuse_to_build_wrong_version(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "secure_update.py"
            file.write_text(
                "CURRENT_VERSION = '0.17.0'\n"
                f"KEY_ID = '{migrate.OLD_KEY_ID}'\n"
                f"PUBLIC_KEY = bytes.fromhex('{migrate.OLD_PUBLIC}')\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Not a Glacier v0.18"):
                migrate.prepare(root, "windows", self.PUB)

    def test_prepare_macos_writes_new_key(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "mac_update_core.py"
            file.write_text(
                'CURRENT_VERSION = "0.18.0"\n'
                f'KEY_ID = "{migrate.OLD_KEY_ID}"\n'
                f'PUBLIC_KEY = bytes.fromhex("{migrate.OLD_PUBLIC}")\n',
                encoding="utf-8",
            )
            migrate.prepare(root, "macos", self.PUB)
            self.assertIn(self.PUB, file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
