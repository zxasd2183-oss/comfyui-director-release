"""Single-command GPU episode executor: fake local ComfyUI, never billed."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import director_video as dv


class EpisodeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = dv.build_plan(
            {"1": {"class_type": "TextNode", "inputs": {"text": "X"}}},
            {"prompt": {"node": "1", "input": "text"}},
            [{"shot_id": "01", "seconds": 3, "prompt": "one"},
             {"shot_id": "02", "seconds": 3, "prompt": "two"}],
            24)
        self.db = self.root / "runs.sqlite"
        self.results = self.root / "results"
        self.sent = []

    def fake_api(self, endpoint, body=None):
        if endpoint.startswith("/object_info/"):
            return {"TextNode": {"input": {}}}
        if endpoint == "/queue":
            return {"queue_running": [], "queue_pending": []}
        if endpoint == "/prompt":
            index = len(self.sent) + 1
            identifier = "prompt-%08d" % index
            self.sent.append(identifier)
            return {"prompt_id": identifier}
        if endpoint.startswith("/history/"):
            pid = endpoint.rsplit("/", 1)[-1]
            return {pid: {"status": {"status_str": "success", "completed": True},
                          "outputs": {"2": {"videos": [{
                              "filename": pid + ".mp4", "subfolder": "",
                              "type": "output"}]}}}}
        raise AssertionError("Unexpected endpoint: " + endpoint)

    def fake_download(self, asset, destination):
        data = (b"fake-clip-for-local-dispatch-tests-" * 8 +
                destination.name.encode())
        destination.write_bytes(data)
        return {"file": destination.name, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data)}

    def test_one_command_renders_and_archives_all_shots(self):
        with patch.object(dv, "comfy_json", side_effect=self.fake_api), \
             patch.object(dv, "download_output", side_effect=self.fake_download):
            result = dv.run_episode(self.plan, self.db, self.results)
        self.assertTrue(result["ok"])
        self.assertEqual(result["completed_shots"], 2)
        self.assertEqual(len(self.sent), 2)
        for sid in ("01", "02"):
            self.assertEqual(dv.verify_completed_shot(self.results, sid)["shot_id"], sid)
        # Resuming a completed run must never send another /prompt.
        with patch.object(dv, "comfy_json") as network:
            self.assertEqual(dv.run_episode(self.plan, self.db, self.results)["completed_shots"], 2)
            network.assert_not_called()

    def test_pending_queued_resumes_without_resubmitting(self):
        con = dv.db_open(self.db, self.plan)
        dv.set_state(con, "01", "queued", prompt_id="prompt-00000001")
        con.close()
        with patch.object(dv, "comfy_json", side_effect=self.fake_api), \
             patch.object(dv, "download_output", side_effect=self.fake_download):
            result = dv.run_episode(self.plan, self.db, self.results)
        self.assertEqual(result["completed_shots"], 2)
        self.assertEqual(len(self.sent), 1)

    def test_uncertain_state_never_auto_retries(self):
        con = dv.db_open(self.db, self.plan)
        dv.set_state(con, "01", "uncertain", error="submit_unknown")
        con.close()
        with patch.object(dv, "comfy_json") as network:
            with self.assertRaisesRegex(dv.PlanError, "cannot safely auto-retry"):
                dv.run_episode(self.plan, self.db, self.results)
            network.assert_not_called()

    def test_existing_runner_lock_rejected(self):
        import fcntl
        lock = self.root / "runs.sqlite.runner.lock"
        with lock.open("wb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(dv, "comfy_json") as network:
                with self.assertRaisesRegex(dv.PlanError, "already active"):
                    dv.run_episode(self.plan, self.db, self.results)
                network.assert_not_called()

    def test_corrupt_completed_output_refuses_advance(self):
        con = dv.db_open(self.db, self.plan)
        dv.set_state(con, "01", "done", prompt_id="prompt-00000001")
        con.close()
        with patch.object(dv, "comfy_json") as network:
            with self.assertRaisesRegex(dv.PlanError, "output missing"):
                dv.run_episode(self.plan, self.db, self.results)
            network.assert_not_called()

    def test_cli_requires_explicit_execution_flags(self):
        file = self.root / "plan.json"
        dv.atomic_json(file, self.plan)
        with patch.object(dv, "comfy_json") as network:
            with self.assertRaisesRegex(dv.PlanError, "BOTH"):
                dv.run_cli(["run-episode", "--plan", str(file), "--db", str(self.db),
                            "--results", str(self.results)])
            self.assertFalse(self.db.exists())
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
