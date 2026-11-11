"""Offline tests for long-lived independent Windows signed owner-VPS updates."""
import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from source.scripts import glacier_publish_signed_updates as shared
from source.scripts import glacier_publish_windows_signed as win


def release(version, digest="a" * 64, size=175907184, **flags):
    return {
        "tag_name": "glacier-v" + version, "draft": False,
        "prerelease": False, "published_at": "2026-11-11T01:56:53Z",
        "assets": [{
            "name": "GlacierBrowser-v" + version + "-Windows-Setup-x64.exe",
            "state": "uploaded", "digest": "sha256:" + digest,
            "size": size,
        }],
        **flags,
    }


class WindowsSignedUpdates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.key_id = "v2-" + hashlib.sha256(self.public).hexdigest()[:16]
        self.p1 = patch.object(shared, "PUBLIC", self.public)
        self.p2 = patch.object(shared, "KEY_ID", self.key_id)
        self.p3 = patch.dict(os.environ, {"GLACIER_WINDOWS_VPS_VERIFIED": "1"})
        for item in (self.p1, self.p2, self.p3):
            item.start()
            self.addCleanup(item.stop)
        self.write_existing("0.20.16")
        self.mac_file = self.path / "macos-arm64.json"
        self.mac_file.write_text("mac signed manifest must not be altered")

    def write_existing(self, version):
        payload = win.make_windows_payload(version, release(version))
        payload["signature"] = base64.b64encode(
            self.key.sign(shared.canonical(payload))
        ).decode("ascii")
        (self.path / "windows-x64.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def test_windows_signed_update_without_any_mac_release(self):
        newer = release("0.20.18", "9" * 64)
        self.assertTrue(win.pending_windows([newer], self.path))
        self.assertTrue(win.render_windows([newer], self.path, self.key))
        actual = shared.read_unique(self.path / "windows-x64.json")
        self.assertEqual(actual["version"], "0.20.18")
        self.assertEqual(actual["url"], "https://sync.borealos.cn/downloads/"
                         "GlacierBrowser-v0.20.18-Windows-Setup-x64.exe")
        self.assertEqual(actual["key_id"], self.key_id)
        self.assertEqual(shared.verify_signed_doc(actual)["sha256"], "9" * 64)
        self.assertEqual(self.mac_file.read_text(),
                         "mac signed manifest must not be altered")
        self.assertFalse(win.pending_windows([newer], self.path))
        self.assertFalse(win.render_windows([newer], self.path, self.key))

    def test_missing_vps_full_hash_gate_blocks_publish(self):
        before = (self.path / "windows-x64.json").read_bytes()
        with patch.dict(os.environ, {"GLACIER_WINDOWS_VPS_VERIFIED": ""}):
            with self.assertRaisesRegex(ValueError, "complete SHA256"):
                win.render_windows([release("0.20.18")], self.path, self.key)
        self.assertEqual(before, (self.path / "windows-x64.json").read_bytes())

    def test_tampered_existing_signature_is_never_replaced(self):
        p = self.path / "windows-x64.json"
        old = json.loads(p.read_text())
        old["size"] += 1
        p.write_text(json.dumps(old))
        with self.assertRaises(Exception):
            win.render_windows([release("0.20.18")], self.path, self.key)
        self.assertEqual(json.loads(p.read_text())["size"], old["size"])

    def test_same_version_replaced_asset_is_rejected(self):
        wrong = release("0.20.16", "b" * 64)
        with self.assertRaisesRegex(ValueError, "same-version"):
            win.pending_windows([wrong], self.path)

    def test_old_release_cannot_roll_back_signed_windows_feed(self):
        self.assertFalse(win.pending_windows([release("0.20.15")], self.path))
        self.assertFalse(win.render_windows([release("0.20.15")], self.path, self.key))
        self.assertEqual(shared.read_unique(self.path / "windows-x64.json")
                         ["version"], "0.20.16")

    def test_prerelease_draft_and_duplicate_cannot_be_promoted(self):
        for bad in [
            [release("0.20.19", prerelease=True)],
            [release("0.20.19", draft=True)],
            [release("0.20.18"), release("0.20.18")],
        ]:
            if len(bad) == 2:
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    win.pending_windows(bad, self.path)
            else:
                self.assertFalse(win.pending_windows(bad, self.path))

    def test_invalid_release_digest_or_missing_asset_rejected(self):
        for bad in [release("0.20.18", digest="zzzz"),
                    release("0.20.18", size=1_000),
                    dict(release("0.20.18"), assets=[])]:
            with self.assertRaises(ValueError):
                win.pending_windows([bad], self.path)

    def test_macos_signed_version_may_lag_independent_windows(self):
        newer = release("0.20.18")
        win.render_windows([newer], self.path, self.key)
        mac = {
            "tag_name": "glacier-macos-v0.20.16",
            "draft": False, "published_at": "2026-11-10T15:06:03Z",
            "prerelease": False,
            "assets": [{
                "name": "GlacierBrowser-v0.20.16-macOS-AppleSilicon.dmg",
                "state": "uploaded", "size": 284693421,
                "digest": "sha256:" + "b" * 64,
            }]
        }
        # A paired 0.20.16 release must never downgrade Windows 0.20.18.
        # This only asserts the independently signed update stays intact.
        self.assertEqual(shared.verify_signed_doc(shared.read_unique(
            self.path / "windows-x64.json"))["version"], "0.20.18")
        self.assertFalse(win.pending_windows([newer, mac], self.path))

    def test_mac_can_later_catch_up_without_rewriting_newer_windows(self):
        from source.scripts.test_glacier_signed_updates import fixture
        old_win, old_mac = fixture("0.20.16")
        mac_payload = shared.make_payloads("0.20.16", old_win, old_mac)["macos-arm64"]
        mac_doc = dict(mac_payload)
        mac_doc["signature"] = base64.b64encode(
            self.key.sign(shared.canonical(mac_payload))
        ).decode("ascii")
        self.mac_file.write_text(json.dumps(mac_doc))
        new_win = release("0.20.18", "9" * 64)
        with patch.dict(os.environ, {"GLACIER_VPS_MIGRATION_READY": "1"}):
            win.render_windows([new_win], self.path, self.key)
            windows_bytes = (self.path / "windows-x64.json").read_bytes()
            # Latest common release is only v0.20.16: not allowed to
            # overwrite the newer Windows v0.20.18 manifest.
            self.assertFalse(shared.needs_new_signed_release(
                [old_win, old_mac, new_win], self.path))
            latest_mac = fixture("0.20.18")[1]
            self.assertTrue(shared.needs_new_signed_release(
                [old_win, old_mac, new_win, latest_mac], self.path))
            self.assertTrue(shared.render_manifests(
                [old_win, old_mac, new_win, latest_mac], self.path, self.key))
        self.assertEqual(windows_bytes,
                         (self.path / "windows-x64.json").read_bytes())
        updated_mac = shared.read_unique(self.mac_file)
        self.assertEqual(shared.verify_signed_doc(updated_mac)["version"], "0.20.18")

    def test_existing_feed_is_required_for_safe_rollout(self):
        (self.path / "windows-x64.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            win.pending_windows([release("0.20.18")], self.path)


if __name__ == "__main__":
    unittest.main()
