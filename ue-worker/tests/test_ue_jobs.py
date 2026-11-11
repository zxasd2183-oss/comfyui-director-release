"""Offline checks for bounded Studio -> UE frame conversion and queue."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_jobs


def episode(count=31):
    return {
        "task": "build_episode_timeline", "project_id": "WaitingOffice",
        "episode_id": "EP01", "fps": 24,
        "shots": [{"shot_id": f"{x:02}", "ordinal": x,
                   "duration_ms": 5000} for x in range(1, count + 1)],
        "expected_total_ms": count * 5000,
    }


class PlanTest(unittest.TestCase):
    def test_31_shots_are_3720_frames(self):
        result = ue_jobs.sanitized_plan(episode())
        self.assertEqual(result["total_frames"], 3720)
        self.assertEqual(result["shots"][0]["start_frame"], 0)
        self.assertEqual(result["shots"][-1]["end_frame"], 3720)

    def test_rejects_paths_code_and_extra_args(self):
        for key, value in [("project_id", "../other"),
                           ("episode_id", "EP01;cmd"),
                           ("fps", 26)]:
            bad = episode()
            bad[key] = value
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.sanitized_plan(bad)
        bad = episode()
        bad["cmd"] = "powershell.exe"
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)

    def test_rejects_reordered_and_truncated_plan(self):
        bad = episode()
        bad["shots"][1]["ordinal"] = 5
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)
        bad = episode()
        bad["expected_total_ms"] = 160000
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)

    def test_noninteger_duration_is_denied(self):
        bad = episode()
        bad["shots"][0]["duration_ms"] = True
        with self.assertRaises(ue_jobs.JobError):
            ue_jobs.sanitized_plan(bad)

    def test_no_overwrite_unmanaged_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = ue_jobs.ensure_project(root)
            self.assertTrue(project.is_file())
            self.assertEqual(project, ue_jobs.ensure_project(root))
            project.write_text("untrusted modified project")
            with self.assertRaises(ue_jobs.JobError):
                ue_jobs.ensure_project(root)


class QueueTest(unittest.TestCase):
    def test_async_job_is_observable_and_single_flight(self):
        started = threading.Event()
        release = threading.Event()

        def fake_runner(spec, root, job_dir):
            started.set()
            release.wait(timeout=4)
            return {"shot_count": len(spec["shots"]),
                    "master": "/Game/Director/Episodes/WaitingOffice_EP01_Master"}

        with tempfile.TemporaryDirectory() as temp:
            manager = ue_jobs.JobManager(lambda: Path(temp), runner=fake_runner)
            submitted = manager.submit(episode())
            self.assertTrue(submitted["ok"])
            self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(ue_jobs.JobError, "ue_worker_busy"):
                manager.submit(episode())
            release.set()
            for _ in range(100):
                state = manager.lookup(submitted["job_id"])
                if state["state"] == "succeeded":
                    break
                time.sleep(0.01)
            self.assertEqual(state["state"], "succeeded")
            self.assertIn("master", state["result"])

    def test_receipts_survive_restart_and_running_jobs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = ue_jobs.JobManager(lambda: root, runner=lambda *args: {
                "master": "/Game/Director/Episodes/WaitingOffice_EP01_Master"
            })
            item = manager.submit(episode())
            for _ in range(100):
                if manager.lookup(item["job_id"])["state"] == "succeeded":
                    break
                time.sleep(0.01)
            restored = ue_jobs.JobManager(lambda: root)
            self.assertEqual(restored.lookup(item["job_id"])["state"], "succeeded")
            stale = {
                "ok": True, "job_id": "a" * 32,
                "state": "running", "task": "build_episode_timeline"
            }
            status_dir = root / "JobStatus"
            (status_dir / (("a" * 32) + ".json")).write_text(json.dumps(stale))
            recovered = ue_jobs.JobManager(lambda: root)
            self.assertEqual(recovered.lookup("a"*32)["state"], "failed")
            self.assertEqual(recovered.lookup("a"*32)["reason"],
                             "worker_restarted_job_result_unconfirmed")

    def test_invalid_job_id_is_not_executable(self):
        manager = ue_jobs.JobManager(lambda: Path("."))
        with self.assertRaises(ue_jobs.JobError):
            manager.lookup("../../anything")


if __name__ == "__main__":
    unittest.main()
