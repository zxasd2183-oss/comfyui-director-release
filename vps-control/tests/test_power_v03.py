import base64
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from power_v03 import (
    approve_request, connect, plan_and_request, request_status,
    totp_step, TTL_SECONDS,
)

CFG = {
    "COMP_PUBLIC_KEY": "test-public", "COMP_PRIVATE_KEY": "never-print-me",
    "COMP_UHOST_ID": "uhost-test", "COMP_REGION": "cn-sh2",
    "COMP_ZONE": "cn-sh2-01",
}
SEED = base64.b32encode(b"test-secret-01234567890123456").decode("ascii")
T0 = 1780000000.0


def code_at(when):
    step = int(when // 30)
    key = base64.b32decode(SEED)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff) % 1000000:06d}"


def allowed(action, cfg):
    return {"allowed": True, "action": action, "state": "Running"}


class PowerV03Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "requests.sqlite")
        self.submitted = []
        self.submit = lambda action, config: (self.submitted.append(action) or
                                               {"accepted": True})
    def tearDown(self):
        self.tmp.cleanup()

    def request(self, action="start", now=T0, plan=allowed):
        return plan_and_request(action, CFG, self.db, plan_fn=plan, now=now)

    def approve(self, request, now=T0, phrase="START GPU",
                otp=None, plan=allowed, submit=None):
        return approve_request(
            request["request_id"], code_at(now) if otp is None else otp,
            phrase, SEED, CFG, self.db, plan_fn=plan,
            submit_fn=self.submit if submit is None else submit, now=now)

    def test_request_is_staged_without_cloud_call(self):
        r = self.request()
        self.assertTrue(r["ok"])
        self.assertFalse(r["gpu_power_changed"])
        self.assertEqual(self.submitted, [])
        self.assertEqual(request_status(r["request_id"], self.db, now=T0)["state"],
                         "pending")

    def test_blocked_preflight_makes_no_ticket(self):
        r = self.request(plan=lambda *_: {"allowed": False,
                                           "reason": "ue_worker_readiness_not_verified"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "ue_worker_readiness_not_verified")
        with connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM requests").fetchone()[0], 0)

    def test_single_pending_request(self):
        first = self.request()
        second = self.request("stop")
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])

    def test_unknown_request_and_bad_action(self):
        self.assertFalse(request_status("unknown", self.db)["ok"])
        self.assertEqual(self.request("delete")["reason"], "invalid_action")

    def test_otp_accept_once_only(self):
        r = self.request()
        outcome = self.approve(r)
        self.assertTrue(outcome["ok"])
        self.assertEqual(self.submitted, ["start"])
        self.assertEqual(request_status(r["request_id"], self.db)["state"],
                         "submitted")
        second = self.approve(r)
        self.assertFalse(second["ok"])
        self.assertEqual(self.submitted, ["start"])

    def test_wrong_code_never_submits(self):
        r = self.request()
        bad = self.approve(r, otp="bad")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["remaining_attempts"], 4)
        self.assertFalse(self.submitted)

    def test_limit_wrong_codes(self):
        r = self.request()
        for _ in range(5):
            result = self.approve(r, otp="00000x")
        self.assertEqual(result["remaining_attempts"], 0)
        result = self.approve(r)
        self.assertEqual(result["reason"], "approval_locked")
        self.assertFalse(self.submitted)

    def test_typed_phrase_mandatory(self):
        r = self.request()
        result = self.approve(r, phrase="YES")
        self.assertEqual(result["reason"], "confirmation_phrase_mismatch")
        self.assertFalse(self.submitted)

    def test_stop_phrase_is_different(self):
        r = self.request("stop")
        self.assertEqual(self.approve(r)["reason"], "confirmation_phrase_mismatch")
        outcome = self.approve(r, phrase="STOP GPU")
        self.assertTrue(outcome["ok"])
        self.assertEqual(self.submitted, ["stop"])

    def test_recheck_prevents_billing_if_state_changes(self):
        r = self.request()
        blocked = self.approve(r, plan=lambda *_: {"allowed": False,
                                                   "reason": "instance_state_not_stopped"})
        self.assertEqual(blocked["state"], "blocked")
        self.assertFalse(self.submitted)

    def test_approval_expiry_blocks(self):
        r = self.request()
        result = self.approve(r, now=T0+TTL_SECONDS+1)
        self.assertEqual(result["reason"], "request_expired_or_consumed")
        self.assertFalse(self.submitted)

    def test_provider_uncertain_failure_not_retried(self):
        r = self.request()
        def uncertain(*args):
            raise TimeoutError("secret network URL")
        result = self.approve(r, submit=uncertain)
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["result"], "provider_request_uncertain_check_status")
        self.assertNotIn("secret", str(result))
        self.assertEqual(self.approve(r)["reason"], "request_expired_or_consumed")

    def test_replayed_code_rejected_across_requests(self):
        first = self.request()
        self.assertTrue(self.approve(first)["ok"])
        second = self.request(now=T0+1)
        self.assertTrue(second["ok"])
        reused = self.approve(second, now=T0+1)
        self.assertFalse(reused["ok"])
        self.assertEqual(reused["reason"], "invalid_or_replayed_otp")
        self.assertEqual(self.submitted, ["start"])

    def test_bad_otp_inputs(self):
        self.assertIsNone(totp_step(SEED, "12345", T0))
        self.assertIsNone(totp_step(SEED, "abcdef", T0))
        code = code_at(T0)
        self.assertEqual(totp_step(SEED, code, T0), int(T0//30))
        self.assertIsNone(totp_step(SEED, code, T0, int(T0//30)))

    def test_audit_does_not_store_keys_or_codes(self):
        r = self.request()
        self.approve(r)
        raw = Path(self.db).read_bytes()
        self.assertNotIn(b"never-print-me", raw)
        self.assertNotIn(SEED.encode(), raw)
        self.assertNotIn(code_at(T0).encode(), raw)

if __name__ == "__main__":
    unittest.main()
