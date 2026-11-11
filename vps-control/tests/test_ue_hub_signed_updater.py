"""Domain separated signed VPS Hub updates, no real service restart or network."""
from __future__ import annotations
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_hub_signed_updater as updater
import ue_hub_sign_release as signer

class SignedHubTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.code = self.root / "hub"
        self.code.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.source = self.root / "trusted"
        self.source.mkdir()
        for name in updater.FILES:
            version = 'UE_HUB_API_VERSION = "0.7.0"\n' if name == "hub_app.py" else ""
            (self.source / name).write_text(version + "VALUE = 'reviewed'\n")
            (self.code / name).write_text('VALUE = "old"\n')
            (self.code / name).chmod(0o644)
        (self.state / "installed-version.txt").write_text("0.5.1")
        priv = Ed25519PrivateKey.generate()
        self.private = priv.private_bytes_raw().hex()
        self.public = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        self.out = self.root / "signed"
        signer.sign("0.7.0", self.source, self.out, self.private, self.public)
        self.manifest_raw = (self.out / "channel.json").read_bytes()
        self.manifest = updater.verify_manifest(self.manifest_raw, self.public)
        self.archive = (self.out / "ue-hub-v0.7.0.zip").read_bytes()
        self.patches = [
            patch.object(updater, "HUB_DIR", self.code),
            patch.object(updater, "STATE", self.state),
            patch.object(updater, "get_worker_state", return_value={
                "ok": True, "active_job_id": None, "worker_version": "0.7.0"
            }),
            patch.object(updater, "check_hub", return_value=True),
            patch.object(updater, "systemctl", return_value=None),
            patch.object(updater.time, "sleep", return_value=None),
        ]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    def test_signature_version_and_only_two_files(self):
        self.assertEqual(self.manifest["format"], updater.FORMAT)
        self.assertEqual(set(updater.files_from_archive(self.archive, self.manifest)),
                         set(updater.FILES))
        bad = json.loads(self.manifest_raw)
        bad["archive_size"] += 1
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(json.dumps(bad).encode(), self.public)
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(self.manifest_raw, "0"*64)
        with self.assertRaises(updater.UpdateError):
            updater.files_from_archive(self.archive + b"extra", self.manifest)

    def test_apply_update_preserves_readable_files_and_leaves_audit_backup(self):
        result = updater.run_once(
            channel=lambda: self.manifest_raw,
            download=lambda version: self.archive,
            public=self.public
        )
        self.assertEqual(result, {"status": "upgraded", "version": "0.7.0"})
        self.assertIn('UE_HUB_API_VERSION = "0.7.0"',
                      (self.code/"hub_app.py").read_text())
        self.assertTrue(stat.S_IMODE((self.code/"hub_app.py").stat().st_mode) & 0o004)
        self.assertEqual((self.state/"installed-version.txt").read_text(), "0.7.0")
        self.assertFalse((self.state/"pending.json").exists())
        self.assertEqual(len(list(self.state.glob("backup-*"))), 1)
        self.assertEqual(updater.run_once(
            channel=lambda:self.manifest_raw,
            download=lambda v:self.fail("stale update downloaded"),
            public=self.public
        )["status"], "already_current")

    def test_fails_closed_on_active_worker_and_missing_worker_activity(self):
        for value in ("a"*32, "unknown"):
            with patch.object(updater, "get_worker_state",
                              side_effect=updater.UpdateError("worker_busy_or_activity_unknown")):
                with self.assertRaises(updater.UpdateError):
                    updater.apply_update(
                        self.manifest,
                        updater.files_from_archive(self.archive,self.manifest))
        self.assertEqual((self.code/"hub_app.py").read_text(), 'VALUE = "old"\n')
        self.assertEqual(len(list(self.state.glob("backup-*"))), 0)

    def test_failed_service_health_rolls_back_without_leaving_pending(self):
        original = {x:(self.code/x).read_bytes() for x in updater.FILES}
        calls = {"n":0}
        def check():
            calls["n"] += 1
            if calls["n"] == 2:
                raise updater.UpdateError("hub_did_not_start")
            return True
        with patch.object(updater, "check_hub", side_effect=check):
            with self.assertRaisesRegex(updater.UpdateError,"hub_did_not_start"):
                updater.apply_update(
                    self.manifest,
                    updater.files_from_archive(self.archive, self.manifest))
        self.assertFalse((self.state/"pending.json").exists())
        self.assertEqual((self.state/"installed-version.txt").read_text(),"0.5.1")
        for name in updater.FILES:
            self.assertEqual((self.code/name).read_bytes(),original[name])

    def test_refuse_symlink_before_modification(self):
        (self.code/"hub_app.py").unlink()
        (self.code/"hub_app.py").symlink_to(self.source/"hub_app.py")
        with self.assertRaises(updater.UpdateError):
            updater.apply_update(
                self.manifest,
                updater.files_from_archive(self.archive,self.manifest))
        self.assertEqual(len(list(self.state.glob("backup-*"))),0)

if __name__ == "__main__":
    unittest.main()
