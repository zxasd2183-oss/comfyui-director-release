"""No-GPU tests for the separately authorized interactive Windows rig runner."""
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

FORMAT = ue_process.HERO_BRIDGE_FORMAT
JOB = "a" * 32
NONCE = "f" * 32


def setup(root, session=3, user="Administrator"):
    folder = root / "JobStatus" / "InteractiveHero"
    for name in ("requests", "results", "cancel", "heartbeat", "claimed"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    (root / "Jobs" / JOB).mkdir(parents=True, exist_ok=True)
    ue_process._bridge_write(
        folder / "ready.json",
        {"format": FORMAT, "user": user, "session_id": session,
         "pid": 1234, "updated": time.time()},
    )
    return folder


class InteractiveHeroTests(unittest.TestCase):
    def test_ready_requires_fresh_session_and_valid_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                state = ue_process.interactive_hero_status(root)
                self.assertEqual(state["session_id"], 3)
                self.assertEqual(state["user"], "Administrator")
                self.assertTrue(state["available"])
                stale = {"format": FORMAT, "user": "Administrator",
                         "session_id": 3, "pid": 1234,
                         "updated": time.time() - 30}
                ue_process._bridge_write(folder / "ready.json", stale)
                self.assertFalse(
                    ue_process.interactive_hero_status(root)["available"]
                )
                stale["updated"] = time.time()
                stale["user"] = "DirectorUEWorker"
                ue_process._bridge_write(folder / "ready.json", stale)
                self.assertFalse(
                    ue_process.interactive_hero_status(root)["available"]
                )

    def test_job_handoff_checks_nonce_and_same_logon_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            done = threading.Event()

            def fake_interactive():
                path = folder / "requests" / (JOB + ".json")
                for _ in range(80):
                    if path.exists():
                        ticket = ue_process._bridge_read(path)
                        receipt = {"format": FORMAT, "job_id": JOB,
                                   "nonce": ticket["nonce"],
                                   "exit_code": 0, "session_id": 3,
                                   "user": "Administrator",
                                   "reason": "finished"}
                        ue_process._bridge_write(
                            folder / "results" / (JOB + ".json"), receipt)
                        done.set()
                        return
                    time.sleep(0.05)

            runner = threading.Thread(target=fake_interactive, daemon=True)
            runner.start()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows",
                              return_value=True):
                ue_process.run_interactive_hero_rig(root, root / "Jobs" / JOB, 5)
            runner.join(timeout=2)
            self.assertTrue(done.is_set())
            req = ue_process._bridge_read(
                folder / "requests" / (JOB + ".json"))
            self.assertEqual(set(req), {
                "format", "task", "job_id", "nonce", "created"})
            self.assertEqual(req["task"], "hero_rig_v200")
            self.assertEqual(len(req["nonce"]), 32)

    def test_unavailable_runner_fails_closed_without_queueing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            (folder / "ready.json").unlink()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows",
                              return_value=True):
                with self.assertRaisesRegex(
                    ue_jobs.JobError, "hero_interactive_login_session_required"
                ):
                    ue_process.run_interactive_hero_rig(
                        root, root / "Jobs" / JOB, 5)
            self.assertFalse(any((folder / "requests").iterdir()))

    def test_reply_from_wrong_windows_session_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            def fake_interactive():
                path = folder / "requests" / (JOB + ".json")
                for _ in range(80):
                    if path.exists():
                        ticket = ue_process._bridge_read(path)
                        ue_process._bridge_write(
                            folder / "results" / (JOB + ".json"),
                            {"format": FORMAT, "job_id": JOB,
                             "nonce": ticket["nonce"],
                             "exit_code": 0, "session_id": 99,
                             "user": "Administrator", "reason": "finished"})
                        return
                    time.sleep(.05)
            t = threading.Thread(target=fake_interactive, daemon=True)
            t.start()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows",
                              return_value=True):
                with self.assertRaisesRegex(
                    ue_jobs.JobError, "hero_interactive_receipt_invalid"
                ):
                    ue_process.run_interactive_hero_rig(
                        root, root / "Jobs" / JOB, 5)
            t.join(timeout=2)

    def test_request_has_no_remote_commands_or_untrusted_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_hero_bridge_is_windows",
                              return_value=True):
                with self.assertRaisesRegex(
                    ue_jobs.JobError, "hero_interactive_work_invalid"
                ):
                    ue_process.run_interactive_hero_rig(
                        root, root / "Jobs" / ("z" * 32), 5)
            self.assertFalse(any((folder / "requests").iterdir()))
        source = Path(ue_process.__file__).read_text(encoding="utf-8")
        self.assertIn('"-run=pythonscript"', source)
        self.assertIn('Win64\\UnrealEditor.exe', source)
        self.assertIn('"hero_interactive_gui_editor_missing"', source)
        self.assertIn('"hero_rig_v200"', source)
        self.assertNotIn("shell=True", source)
        self.assertIn("_interactive_hero_preflight(root, ident)", source)
        self.assertIn("time.time() - beat[\"updated\"] > 15", source)

    def test_setup_requires_real_interactive_account_no_password(self):
        path = Path(__file__).resolve().parents[1] / "install-interactive-hero-runner.ps1"
        code = path.read_text(encoding="utf-8")
        self.assertIn("-LogonType Interactive", code)
        self.assertIn("-RunLevel Limited", code)
        self.assertIn("-AtLogOn", code)
        self.assertIn("-interactive-hero-runner", code)
        self.assertNotIn("-LogonType Password", code)
        self.assertNotIn("ConvertTo-SecureString", code)
        self.assertNotIn("Invoke-Expression", code)


if __name__ == "__main__":
    unittest.main()
