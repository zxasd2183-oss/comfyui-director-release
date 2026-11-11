"""Offline signed release and fail-closed updater tests, no Windows needed."""
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_signed_updater as updates
import ue_sign_release as signer


class SignedUpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"
        self.src.mkdir()
        for name in updates.FILES:
            (self.src / name).write_text(
                '"""test fixture"""\n' +
                ('def status():\n    return {"worker_version": "0.6.0"}\n'
                 if name == "agent.py" else 'value = 1\n'),
                encoding="utf-8",
            )
        private = Ed25519PrivateKey.generate()
        self.private = private.private_bytes_raw().hex()
        self.public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        ).hex()
        self.out = self.root / "out"
        self.receipt = signer.build_release(
            "0.6.0", self.src, self.out, self.private, self.public,
        )
        self.channel = (self.out / "channel.json").read_bytes()
        self.manifest = updates.verify_manifest(self.channel, self.public)
        self.blob = (self.out / self.receipt["archive_name"]).read_bytes()

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_release_and_signing_key_pair(self):
        self.assertEqual(self.manifest["version"], "0.6.0")
        self.assertEqual(self.manifest["archive_size"], len(self.blob))
        data = updates.verified_files(self.blob, self.manifest)
        self.assertEqual(set(data), set(updates.FILES))
        self.assertIn(b'"worker_version": "0.6.0"', data["agent.py"])

    def test_reject_wrong_key_forged_signature_and_duplicate_field(self):
        other = Ed25519PrivateKey.generate()
        wrong = other.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()
        for public in (wrong, "0"*64):
            with self.assertRaises(updates.UpdateError):
                updates.verify_manifest(self.channel, public)
        forged = json.loads(self.channel)
        forged["archive_size"] += 1
        with self.assertRaisesRegex(updates.UpdateError, "release_signature"):
            updates.verify_manifest(json.dumps(forged).encode(), self.public)
        with self.assertRaises(updates.UpdateError):
            updates.verify_manifest(
                b'{"version":"0.6.0","version":"0.6.0"}', self.public
            )

    def test_reject_invalid_zip_or_traversal_and_archive_hash(self):
        with self.assertRaisesRegex(updates.UpdateError, "archive_hash"):
            updates.verified_files(self.blob + b"bad", self.manifest)
        # A correctly signed digest cannot authorize an archive with unlisted files.
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for name in updates.FILES:
                z.writestr(name, (self.src/name).read_bytes())
            z.writestr("../evil.py", b"print('evil')")
        bad = out.getvalue()
        fake = dict(self.manifest)
        fake["archive_size"] = len(bad)
        fake["archive_sha256"] = hashlib.sha256(bad).hexdigest()
        with self.assertRaisesRegex(updates.UpdateError, "archive_allowlist"):
            updates.verified_files(bad, fake)

    def test_signed_package_applies_with_one_health_check_and_no_file_escape(self):
        code_dir = self.root / "code"
        code_dir.mkdir()
        state = self.root / "updater"
        state.mkdir()
        old_files = {}
        for name in updates.FILES:
            data = (self.src/name).read_bytes().replace(b"0.6.0", b"0.5.0")
            old_files[name] = data
            (code_dir/name).write_bytes(data)
        (state/"installed-version.txt").write_text("0.5.0")
        with patch.object(updates, "worker_status", return_value={"worker_version":"0.5.0"}),patch.object(
            updates, "check_no_running_ue_commandlet"
        ),patch.object(updates, "invoke_task") as task,patch.object(
            updates, "worker_reaches_version", return_value=True
        ):
            result = updates.run_once(
                code_dir, state, self.public,
                channel=lambda:self.channel, download=lambda v:self.blob,
            )
        self.assertEqual(result["status"], "upgraded")
        self.assertEqual(result["version"], "0.6.0")
        self.assertEqual((state/"installed-version.txt").read_text(), "0.6.0")
        self.assertEqual(task.call_count, 2)
        self.assertFalse((state/"pending.json").exists())
        for name in updates.FILES:
            self.assertEqual((code_dir/name).read_bytes(), (self.src/name).read_bytes())
        # Anti-rollback: same version is a no-op; never fetches release ZIP.
        second = updates.run_once(
            code_dir, state, self.public, channel=lambda:self.channel,
            download=lambda _:self.fail("unexpected second download"),
        )
        self.assertEqual(second["status"], "already_current")

    def test_unhealthy_worker_rolls_back_and_persists_previous_version(self):
        code = self.root / "code"
        state = self.root / "state"
        code.mkdir()
        state.mkdir()
        original = {}
        for name in updates.FILES:
            data = (self.src/name).read_bytes().replace(b"0.6.0", b"0.5.0")
            original[name] = data
            (code/name).write_bytes(data)
        (state/"installed-version.txt").write_text("0.5.0")
        with patch.object(updates, "worker_status", return_value={"worker_version":"0.5.0"}),patch.object(
            updates, "check_no_running_ue_commandlet"
        ),patch.object(updates, "invoke_task"),patch.object(
            updates, "worker_reaches_version",
            side_effect=lambda _root,version,**_: version == "0.5.0"
        ):
            with self.assertRaisesRegex(updates.UpdateError,"new_worker_health_failed"):
                updates.apply_update(
                    code, state, self.manifest,
                    updates.verified_files(self.blob, self.manifest),
                )
        self.assertFalse((state/"pending.json").exists())
        self.assertEqual((state/"installed-version.txt").read_text(), "0.5.0")
        for name in updates.FILES:
            self.assertEqual((code/name).read_bytes(), original[name])


if __name__ == "__main__":
    unittest.main()
