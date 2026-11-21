"""Three-device synthetic private/work E2E vault and concurrent CAS checks.

Run with PYTHONPATH=glacier-windows and PYTHONPATH=glacier-macos.
No production login, cookies, device tokens, external HTTP calls or account changes.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from glacier_sync23 import SyncError23, decrypt_space23, encrypt_space23
from glacier_sync_auto24 import account_digest24, sync_one_space24

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "glacier-android-gecko/app/src/androidTest/assets"


def fixture(space):
    assert space in ("private", "work")
    f = json.loads((ASSETS / f"glacier_sync_interop_{space}_v1.json").read_text(encoding="utf-8"))
    assert f["space"] == space
    return f


class IsolatedCAS:
    def __init__(self):
        self.data = {space: {"version": 3, "envelope": None, "writes": 0}
                     for space in ("private", "work")}

    def call(self, method, path, data=None):
        if path not in ("/v1/vault/private", "/v1/vault/work"):
            raise AssertionError("unexpected synthetic account sync route")
        state = self.data[path.removeprefix("/v1/vault/")]
        if method == "GET":
            return {"version": state["version"], "envelope": state["envelope"]}
        if method != "PUT" or data is None:
            raise AssertionError("unexpected synthetic backend operation")
        if type(data.get("expected_version")) is not int or data["expected_version"] != state["version"]:
            raise SyncError23("synthetic concurrent CAS conflict")
        if not isinstance(data.get("envelope"), str) or not data["envelope"]:
            raise AssertionError("synthetic backend must receive encrypted envelope")
        state["version"] += 1
        state["envelope"] = data["envelope"]
        state["writes"] += 1
        return {"version": state["version"]}


class DualSpaceInterop(unittest.TestCase):
    def test_synthetic_work_fixture_is_valid_and_sealed_from_private(self):
        f = fixture("work")
        decoded = decrypt_space23(f["envelope"], "work", f["passphrase"])
        self.assertEqual(decoded, [f["card"]])
        self.assertNotIn(f["card"]["password"], f["envelope"])
        fresh = encrypt_space23(decoded, "work", f["passphrase"])
        self.assertNotEqual(fresh, f["envelope"])
        self.assertEqual(decrypt_space23(fresh, "work", f["passphrase"]), decoded)
        for other_space, phrase in (("private", f["passphrase"]),
                                   ("work", "synthetic-wrong-passphrase")):
            with self.subTest(space=other_space), self.assertRaises(SyncError23):
                decrypt_space23(f["envelope"], other_space, phrase)

    def test_two_spaces_sync_independently_and_never_cross_decrypt(self):
        private, work = fixture("private"), fixture("work")
        fake = IsolatedCAS()
        both = [private["card"], work["card"]]
        empty_baselines = {space: {"version": 3, "local_hash": account_digest24([], space)}
                           for space in ("private", "work")}
        with patch("glacier_sync_auto24.SyncTransport23", return_value=fake):
            for f in (private, work):
                res = sync_one_space24("https://sync.borealos.cn", 18566, "fictional-token",
                                       f["space"], both, empty_baselines[f["space"]],
                                       f["passphrase"])
                self.assertEqual(res["kind"], "uploaded")
                self.assertEqual(res["version"], 4)
            for f in (private, work):
                state = fake.data[f["space"]]
                self.assertEqual(state["version"], 4)
                self.assertEqual(state["writes"], 1)
                self.assertEqual(decrypt_space23(state["envelope"], f["space"],
                                                f["passphrase"]), [f["card"]])
                self.assertNotIn(f["card"]["password"], state["envelope"])
                wrong = "work" if f["space"] == "private" else "private"
                with self.assertRaises(SyncError23):
                    decrypt_space23(state["envelope"], wrong, f["passphrase"])
                restored = sync_one_space24("https://sync.borealos.cn", 18566,
                                            "fictional-token", f["space"], [],
                                            empty_baselines[f["space"]], f["passphrase"])
                self.assertEqual(restored["kind"], "downloaded")
                self.assertEqual(restored["records"], [f["card"]])
                self.assertEqual(restored["version"], 4)
            self.assertEqual(fake.data["private"]["writes"], 1)
            self.assertEqual(fake.data["work"]["writes"], 1)

    def test_private_conflict_does_not_damage_work_and_rollback_blocks_writes(self):
        private, work = fixture("private"), fixture("work")
        fake = IsolatedCAS()
        fake.data["private"]["version"] = 4
        fake.data["private"]["envelope"] = private["envelope"]
        baseline = {"version": 3, "local_hash": account_digest24([], "private")}
        with patch("glacier_sync_auto24.SyncTransport23", return_value=fake):
            conflict = sync_one_space24("https://sync.borealos.cn", 18566,
                                        "fictional-token", "private", [private["card"]],
                                        baseline, private["passphrase"])
            self.assertEqual(conflict["kind"], "conflict")
            self.assertEqual(fake.data["private"]["writes"], 0)
            untouched = sync_one_space24("https://sync.borealos.cn", 18566,
                                         "fictional-token", "work", [],
                                         {"version": 3, "local_hash": account_digest24([], "work")},
                                         work["passphrase"])
            self.assertEqual(untouched["kind"], "unchanged")
            fake.data["private"]["version"] = 2
            rollback = sync_one_space24("https://sync.borealos.cn", 18566,
                                        "fictional-token", "private", [private["card"]],
                                        baseline, private["passphrase"])
            self.assertEqual(rollback["kind"], "rollback")
            self.assertEqual(fake.data["private"]["writes"], 0)


if __name__ == "__main__":
    unittest.main()
