"""Synthetic-only cross-device Glacier account-vault interoperability and CAS tests.

Run separately with PYTHONPATH=glacier-windows and PYTHONPATH=glacier-macos.
No production token, website account, endpoint, or real network requests.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from glacier_sync23 import SyncError23, decrypt_space23, encrypt_space23
from glacier_sync_auto24 import (
    account_digest24, check_manual_snapshot24, sync_one_space24
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "glacier-android-gecko/app/src/androidTest/assets/glacier_sync_interop_private_v1.json"
)


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class InMemoryCAS:
    """Fake sync backend with atomic expected_version semantics, no network."""
    def __init__(self, version=3, envelope=None):
        self.version, self.envelope = version, envelope
        self.puts = []

    def call(self, method, path, data=None):
        if path != "/v1/vault/private":
            raise AssertionError("Unexpected space or route")
        if method == "GET":
            return {"version": self.version, "envelope": self.envelope}
        if method == "PUT":
            if data["expected_version"] != self.version:
                raise SyncError23("Concurrent server version change")
            self.puts.append(data)
            self.version += 1
            self.envelope = data["envelope"]
            return {"version": self.version}
        raise AssertionError("Unexpected fake request")


class CrossDeviceVaultContract(unittest.TestCase):
    def test_desktop_decrypts_android_consumable_fixture(self):
        f = fixture()
        decoded = decrypt_space23(f["envelope"], f["space"], f["passphrase"])
        self.assertEqual(decoded, [f["card"]])
        self.assertNotIn(f["card"]["password"], f["envelope"])
        # Production encryption must be randomized rather than reuse fixture salt/nonce.
        fresh = encrypt_space23(decoded, f["space"], f["passphrase"])
        self.assertEqual(decrypt_space23(fresh, f["space"], f["passphrase"]), decoded)
        self.assertNotEqual(fresh, f["envelope"])

    def test_wrong_password_or_profile_cannot_decrypt_fixture(self):
        f = fixture()
        for space, passphrase in (
            (f["space"], "wrong-synthetic-passphrase"),
            ("work", f["passphrase"]),
        ):
            with self.subTest(space=space):
                with self.assertRaises(SyncError23):
                    decrypt_space23(f["envelope"], space, passphrase)

    def test_two_devices_conflict_and_unmodified_device_download(self):
        f = fixture()
        source = f["card"]
        other = dict(source, username="other-fictional@example.com")
        shared = InMemoryCAS()
        baseline = {"version": 3, "local_hash": account_digest24([], "private")}
        with patch("glacier_sync_auto24.SyncTransport23", return_value=shared):
            a = sync_one_space24("https://sync.borealos.cn", 18566,
                                 "fake-token", "private", [source],
                                 baseline, f["passphrase"])
            self.assertEqual(a["kind"], "uploaded")
            self.assertEqual(shared.version, 4)
            self.assertEqual(shared.puts[0]["expected_version"], 3)
            b = sync_one_space24("https://sync.borealos.cn", 18566,
                                 "fake-token", "private", [other],
                                 baseline, f["passphrase"])
            self.assertEqual(b["kind"], "conflict")
            self.assertEqual(len(shared.puts), 1)
            unchanged = sync_one_space24("https://sync.borealos.cn", 18566,
                                        "fake-token", "private", [],
                                        baseline, f["passphrase"])
            self.assertEqual(unchanged["kind"], "downloaded")
            self.assertEqual(unchanged["records"], [source])
            self.assertEqual(unchanged["version"], 4)

    def test_cloud_restore_cannot_overwrite_known_newer_local_version(self):
        f = fixture()
        known = {"version": 8, "local_hash": account_digest24([f["card"]], "private")}
        remote = InMemoryCAS(version=7, envelope=f["envelope"])
        with patch("glacier_sync_auto24.SyncTransport23", return_value=remote):
            result = sync_one_space24("https://sync.borealos.cn", 18566,
                                      "fake-token", "private", [f["card"]],
                                      known, f["passphrase"])
        self.assertEqual(result["kind"], "rollback")
        self.assertEqual(remote.puts, [])
        for direction in (True, False):
            with self.assertRaises(SyncError23):
                check_manual_snapshot24(
                    {"version": 7, "envelope": f["envelope"]},
                    known, [f["card"]], "private", upload=direction)


if __name__ == "__main__":
    unittest.main()
