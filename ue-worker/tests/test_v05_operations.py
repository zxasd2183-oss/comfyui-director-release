"""Offline protocol tests for the authenticated V05 operator controls."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import ue_jobs
import ue_logs
from ue_process import JobCancelled, ProcessController, job_scope, run_fixed


def spec():
    return {
        "task": "build_episode_timeline", "project_id": "WaitingOffice",
        "episode_id": "EP01", "fps": 24,
        "shots": [{"shot_id": f"{i:02}", "ordinal": i, "duration_ms": 5000}
                  for i in range(1, 32)],
        "expected_total_ms": 31 * 5000,
    }


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.entered = threading.Event()
        self.release = threading.Event()

        def slow_runner(_spec, _root, _work):
            self.entered.set()
            self.release.wait(timeout=5)
            return {"note": "test_result"}

        self.manager = ue_jobs.JobManager(lambda: self.root, runner=slow_runner)
        self.original_manager = agent.JOB_MANAGER
        agent.JOB_MANAGER = self.manager
        self.server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        self.server.token = "a" * 64
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.env = patch.dict("os.environ", {"DIRECTOR_UE_WORKSPACE": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.release.set()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        agent.JOB_MANAGER = self.original_manager
        self.tmp.cleanup()

    def request(self, path, *, method="GET", body=None, token=True):
        headers = {"Authorization": "Bearer " + "a" * 64} if token else {}
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.url + path, method=method, data=data, headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_job_logs_allowlist_and_redaction(self):
        jid = "b" * 32
        entry = {"ok": True, "job_id": jid, "state": "succeeded"}
        self.manager.jobs[jid] = entry
        work = self.root / "Jobs" / jid
        work.mkdir(parents=True)
        (work / "preset.log").write_text(
            "Started\nAuthorization: Bearer secret-should-not-leak-12345678\n"
            "token=abcdef12345678\nFinished\n",
            encoding="utf-8",
        )
        code, result = self.request(f"/v3/jobs/{jid}/logs/preset")
        self.assertEqual(code, 200)
        self.assertTrue(result["ok"])
        self.assertIn("Finished", result["tail"])
        self.assertNotIn("secret-should-not-leak", result["tail"])
        self.assertNotIn("abcdef12345678", result["tail"])
        self.assertIn("[REDACTED]", result["tail"])

        self.assertEqual(self.request(f"/v3/jobs/{jid}/logs/preset", token=False)[0], 401)
        self.assertEqual(self.request(f"/v3/jobs/{jid}/logs/../../worker.token")[0], 404)
        self.assertEqual(self.request(f"/v3/jobs/{jid}/logs/agent")[0], 404)
        self.assertEqual(self.request(f"/v3/jobs/{jid}/logs/unreal")[0], 404)

    def test_cancel_one_owned_job_but_no_arbitrary_command(self):
        task = self.manager.submit(spec())
        jid = task["job_id"]
        self.assertTrue(self.entered.wait(2))
        route = f"/v3/jobs/{jid}/cancel"
        self.assertEqual(self.request(route, method="POST", token=False)[0], 401)
        self.assertEqual(self.request(route, method="POST", body={"pid": 123})[0], 400)
        self.assertEqual(self.request(route, method="POST")[0], 202)
        self.release.set()
        state = {}
        for _ in range(200):
            state = self.manager.lookup(jid)
            if state["state"] == "cancelled":
                break
            time.sleep(.01)
        self.assertEqual(state["state"], "cancelled")
        self.assertEqual(self.request(route, method="POST")[1]["already_terminal"], True)
        self.assertEqual(self.request("/v3/jobs/" + "0"*32 + "/cancel", method="POST")[0], 404)

    def test_cancellation_terminates_only_own_child_process(self):
        ctl = ProcessController()
        outcome = []
        log = self.root / "child.log"

        def run():
            with job_scope(ctl):
                try:
                    run_fixed(
                        [sys.executable, "-c", "import time; time.sleep(20)"],
                        self.root, log, timeout=25, env=None,
                        timeout_reason="timeout", failed_reason="failed",
                    )
                except JobCancelled:
                    outcome.append("cancelled")

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        for _ in range(200):
            with ctl.lock:
                active = ctl.process
            if active is not None:
                break
            time.sleep(.01)
        self.assertIsNotNone(active)
        ctl.cancel()
        thread.join(timeout=8)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, ["cancelled"])
        self.assertIsNotNone(active.poll())


if __name__ == "__main__":
    unittest.main()
