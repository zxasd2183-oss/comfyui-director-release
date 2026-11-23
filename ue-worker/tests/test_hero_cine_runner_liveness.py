"""Offline tests for transient RDP heartbeat drops during Cine assembly."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_process
import ue_jobs

JOB = "a" * 32
FORMAT = ue_process.HERO_BRIDGE_FORMAT


def prepare(root):
    folder = root / "JobStatus" / "InteractiveHero"
    for name in ("requests", "results", "cancel", "heartbeat", "claimed"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    (root / "Jobs" / JOB).mkdir(parents=True)
    return folder


class HeroCineRunnerLivenessTests(unittest.TestCase):
    def test_transient_ready_gap_recovers_in_same_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = prepare(root)
            good = {"available": True, "user": "Administrator", "session_id": 2}
            gap = {"available": False, "reason": "interactive_runner_not_current"}
            statuses = [good, gap, gap, good]
            calls = []
            def status(_):
                calls.append(1)
                return statuses.pop(0) if statuses else good
            def write_success():
                request = folder / "requests" / (JOB + ".json")
                for _ in range(100):
                    if request.is_file():
                        data = ue_process._bridge_read(request)
                        time.sleep(1.7)
                        receipt = {"format": FORMAT, "job_id": JOB,
                                   "nonce": data["nonce"], "exit_code": 0,
                                   "session_id": 2, "user": "Administrator",
                                   "reason": "finished"}
                        ue_process._bridge_write(
                            folder / "results" / (JOB + ".json"), receipt)
                        return
                    time.sleep(.02)
            t = threading.Thread(target=write_success, daemon=True)
            t.start()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows", return_value=True), \
                 patch.object(ue_process, "interactive_hero_status", side_effect=status):
                ue_process.run_interactive_hero_rig(
                    root, root / "Jobs" / JOB, 5, task="hero_cine_v260")
            t.join(timeout=2)
            self.assertGreaterEqual(len(calls), 4)
            self.assertFalse((folder / "cancel" / (JOB + ".json")).exists())

    def test_different_owner_session_is_rejected_without_grace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = prepare(root)
            statuses = [
                {"available": True, "user": "Administrator", "session_id": 2},
                {"available": True, "user": "OtherUser", "session_id": 2},
            ]
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows", return_value=True), \
                 patch.object(ue_process, "interactive_hero_status", side_effect=statuses):
                with self.assertRaisesRegex(
                    ue_jobs.JobError, "hero_interactive_session_changed"
                ):
                    ue_process.run_interactive_hero_rig(
                        root, root / "Jobs" / JOB, 5, task="hero_cine_v260")
            self.assertTrue((folder / "cancel" / (JOB + ".json")).exists())

    def test_absence_exceeding_grace_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = prepare(root)
            good = {"available": True, "user": "Administrator", "session_id": 2}
            lost = {"available": False, "reason": "interactive_runner_not_current"}
            state = [good]
            def status(_):
                return state.pop(0) if state else lost
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows", return_value=True), \
                 patch.object(ue_process, "interactive_hero_status", side_effect=status), \
                 patch.object(ue_process, "HERO_BRIDGE_READY_GRACE_SECONDS", .1):
                with self.assertRaisesRegex(
                    ue_jobs.JobError, "hero_interactive_runner_disconnected"
                ):
                    ue_process.run_interactive_hero_rig(
                        root, root / "Jobs" / JOB, 5, task="hero_cine_v260")
            self.assertTrue((folder / "cancel" / (JOB + ".json")).exists())

    def test_cine_bridge_receipt_read_only_and_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = prepare(root)
            results = folder / "results" / (JOB + ".json")
            ue_process._bridge_write(results, {
                "format": FORMAT, "job_id": JOB, "nonce": "f" * 32,
                "exit_code": 1, "session_id": 2, "user": "Administrator",
                "reason": "editor_failed"
            })
            cine = root / "Jobs" / JOB / "hero_cine_result.json"
            cine.write_text(json.dumps({
                "ok": False, "reason": "hero_cine_failed_build",
                "private": "must never be surfaced"}))
            before = cine.read_bytes()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                report = ue_process.hero_cine_bridge_diagnostic(root, JOB)
            self.assertEqual(report["results"], "valid")
            self.assertEqual(report["process_reason"], "editor_failed")
            self.assertEqual(report["cine_receipt"], "failed")
            self.assertEqual(report["cine_stage"], "hero_cine_failed_build")
            self.assertNotIn("private", str(report))
            self.assertNotIn("user", str(report))
            self.assertNotIn("nonce", str(report))
            self.assertNotIn("rig_receipt", report)
            self.assertFalse(report["mutations_performed"])
            self.assertEqual(cine.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
