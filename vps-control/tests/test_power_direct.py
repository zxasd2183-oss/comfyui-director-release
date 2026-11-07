"""Isolated immediate power tests. Fake provider only; NEVER start real hardware."""
import tempfile
import unittest
from pathlib import Path

from power_direct import execute_direct
from power_v03 import connect


class DirectPowerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "requests.db")
        with connect(self.db):
            pass
        self.submissions = []

    def submit(self, action, config):
        self.submissions.append(action)
        return {"accepted": True}

    def allowed(self, action, config):
        return {"allowed": True}

    def test_start_no_otp_no_pending_request(self):
        result = execute_direct("start", {}, self.db, plan_fn=self.allowed,
                                submit_fn=self.submit, now=1000)
        self.assertTrue(result["ok"])
        self.assertFalse(result["approval_required"])
        self.assertFalse(result["final_state_verified"])
        self.assertEqual(result["state"], "submitted")
        self.assertEqual(self.submissions, ["start"])
        with connect(self.db) as db:
            row = db.execute("SELECT state FROM requests").fetchone()
            self.assertEqual(row["state"], "submitted")

    def test_stop_blocked_when_queue_not_verified(self):
        def blocked(action, config):
            return {"allowed": False, "reason": "comfyui_queue_not_verified"}
        result = execute_direct("stop", {}, self.db, plan_fn=blocked,
                                submit_fn=self.submit, now=1000)
        self.assertEqual(result["reason"], "comfyui_queue_not_verified")
        self.assertEqual(self.submissions, [])

    def test_second_preflight_failure_prevents_submission(self):
        calls = [0]
        def changed(action, config):
            calls[0] += 1
            return {"allowed": calls[0] == 1,
                    "reason": "comfyui_queue_not_empty"}
        result = execute_direct("stop", {}, self.db, plan_fn=changed,
                                submit_fn=self.submit, now=1000)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(self.submissions, [])

    def test_cooldown_prevents_duplicate_provider_action(self):
        first = execute_direct("start", {}, self.db, plan_fn=self.allowed,
                               submit_fn=self.submit, now=1000)
        duplicate = execute_direct("start", {}, self.db, plan_fn=self.allowed,
                                   submit_fn=self.submit, now=1001)
        self.assertTrue(first["ok"])
        self.assertEqual(duplicate["reason"], "power_operation_in_progress_or_cooldown")
        self.assertEqual(self.submissions, ["start"])

    def test_pending_legacy_request_blocks_direct_submission(self):
        with connect(self.db) as db:
            db.execute(
                "INSERT INTO requests(id,action,state,created,expires,updated) "
                "VALUES('legacy','start','pending',990,1300,990)")
        result = execute_direct("start", {}, self.db, plan_fn=self.allowed,
                                submit_fn=self.submit, now=1000)
        self.assertEqual(result["reason"], "power_operation_in_progress_or_cooldown")
        self.assertEqual(self.submissions, [])

    def test_uncertain_provider_error_does_not_auto_retry(self):
        def fail(action, config):
            self.submissions.append(action)
            raise TimeoutError("private provider detail")
        result = execute_direct("start", {}, self.db, plan_fn=self.allowed,
                                submit_fn=fail, now=1000)
        self.assertEqual(result["state"], "error")
        self.assertEqual(result["result"], "provider_request_uncertain_check_status")
        self.assertNotIn("private provider", str(result))
        again = execute_direct("start", {}, self.db, plan_fn=self.allowed,
                               submit_fn=fail, now=1001)
        self.assertFalse(again["ok"])
        self.assertEqual(self.submissions, ["start"])


if __name__ == "__main__":
    unittest.main()
