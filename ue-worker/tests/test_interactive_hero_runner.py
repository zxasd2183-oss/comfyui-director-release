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
    def test_readonly_diagnostic_classifies_completed_failed_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            result = folder / "results" / (JOB + ".json")
            payload = {"format": FORMAT, "job_id": JOB, "nonce": NONCE,
                       "exit_code": 0, "session_id": 3, "user": "Administrator",
                       "reason": "finished"}
            ue_process._bridge_write(result, payload)
            old = result.read_bytes()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                diag = ue_process.interactive_hero_job_diagnostic(root, JOB)
            self.assertTrue(diag["available"])
            self.assertEqual(diag["results"], "valid")
            self.assertEqual(diag["process_exit"], "zero")
            self.assertEqual(diag["rig_receipt"], "missing")
            self.assertFalse(diag["mutations_performed"])
            self.assertNotIn("user", diag)
            self.assertNotIn("nonce", diag)
            self.assertEqual(result.read_bytes(), old)

    def test_readonly_diagnostic_rejects_untrusted_paths_and_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = setup(root)
            receipt = root / "Jobs" / JOB / "hero_rig_result.json"
            receipt.write_text('{"ok": false, "reason": "hero_rig_failed_cloud_request"}')
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                diag = ue_process.interactive_hero_job_diagnostic(root, JOB)
                rejected = ue_process.interactive_hero_job_diagnostic(
                    root, "../unsafe")
            self.assertEqual(diag["rig_receipt"], "failed")
            self.assertEqual(diag["rig_stage"], "hero_rig_failed_cloud_request")
            self.assertFalse(rejected["available"])


    def test_bridge_read_uses_one_atomic_bounded_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ready.json"
            expected = {"format": FORMAT, "user": "Administrator",
                        "session_id": 3, "pid": 123, "updated": time.time()}
            ue_process._bridge_write(p, expected)
            self.assertEqual(ue_process._bridge_read(p), expected)
            p.write_bytes(b"x" * 1201)
            with self.assertRaises(ValueError):
                ue_process._bridge_read(p)
            p.write_bytes(b"{broken}")
            with self.assertRaises(ValueError):
                ue_process._bridge_read(p)

    def test_runner_requires_sustained_heartbeat_loss_not_single_read_race(self):
        source = Path(ue_process.__file__).read_text("utf-8")
        runner = source[source.index("def _interactive_hero_once("):
                        source.index("def interactive_hero_runner_main(")]
        self.assertIn("last_valid_worker_heartbeat = time.monotonic()", runner)
        self.assertIn("time.monotonic() - last_valid_worker_heartbeat > 15", runner)
        self.assertIn("if valid_heartbeat:", runner)
        self.assertIn('reason = "worker_heartbeat_lost"', runner)

    def test_editor_log_diagnostic_classifies_only_this_job_without_raw_logs(self):
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / "HeroProjects" / "CHAR_GPT" / "Saved" / "Logs"
            folder.mkdir(parents=True)
            path = folder / "DirectorHeroGPT.log"
            now = datetime.now(timezone.utc).replace(microsecond=0)
            stamp = now.strftime("[%Y.%m.%d-%H.%M.%S:000]")
            path.write_text(
                "[2020.01.01-01.01.01:000] LogMetaHumanAuth: Login failed\n" +
                stamp + " LogEOSAuth: No existing persistent auth credentials were found\n" +
                stamp + " LogMetaHumanAuth: Login failed - error code EOS_InvalidAuth\n" +
                stamp + " LogMetaHumanCharacterEditor: Error: Auto-Rigging of Face failed\n",
                encoding="utf-8")
            start = (now - __import__("datetime").timedelta(seconds=2)).isoformat()
            end = (now + __import__("datetime").timedelta(seconds=2)).isoformat()
            original = path.read_bytes()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                report = ue_process.hero_rig_editor_log_diagnostic(root, start, end)
            self.assertTrue(report["available"])
            self.assertEqual(report["status"], "analyzed")
            self.assertEqual(report["signals"], [
                "cloud_autorig_failed", "epic_signin_failed",
                "no_epic_persistent_credentials"])
            self.assertFalse(report["mutations_performed"])
            self.assertNotIn("EOS_InvalidAuth", str(report))
            self.assertEqual(path.read_bytes(), original)

    def test_editor_log_diagnostic_denies_stale_or_unscoped_logs(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / "HeroProjects" / "CHAR_GPT" / "Saved" / "Logs"
            folder.mkdir(parents=True)
            path = folder / "DirectorHeroGPT.log"
            path.write_text("[2020.01.01-01.01.01:000] LogMetaHumanAuth: Login failed")
            now = datetime.now(timezone.utc)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                report = ue_process.hero_rig_editor_log_diagnostic(
                    root, (now-timedelta(seconds=5)).isoformat(),
                    (now+timedelta(seconds=5)).isoformat())
                rejected = ue_process.hero_rig_editor_log_diagnostic(
                    root, "invalid", now.isoformat())
            self.assertTrue(report["available"])
            self.assertEqual(report["signals"], [])
            self.assertEqual(report["status"], "no_correlated_timestamped_lines")
            self.assertFalse(rejected["available"])


    def test_editor_log_classifies_actual_rig_readback_exception_without_raw_text(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / "HeroProjects" / "CHAR_GPT" / "Saved" / "Logs"
            folder.mkdir(parents=True)
            path = folder / "DirectorHeroGPT.log"
            now = datetime.now(timezone.utc).replace(microsecond=0)
            stamp = now.strftime("[%Y.%m.%d-%H.%M.%S:000]")
            content = (
                "[2020.01.01-01.01.01:000] LogPython: Warning: Director Hero Rig blocked phase=rig_readback exception_class=AttributeError\n"
                + stamp + " LogPython: Warning: Director Hero Rig blocked phase=rig_readback exception_class=RuntimeError\n"
                + stamp + " LogHttp: Warning: Request timed out for private-token\n"
            )
            path.write_text(content, encoding="utf-8")
            before = path.read_bytes()
            start = (now - timedelta(seconds=1)).isoformat()
            end = (now + timedelta(seconds=1)).isoformat()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                report = ue_process.hero_rig_editor_log_diagnostic(root, start, end)
            self.assertEqual(report["readback_exception"], "RuntimeError")
            self.assertEqual(report["signals"], ["editor_python_error", "http_request_timeout"])
            self.assertNotIn("private-token", str(report))
            self.assertEqual(path.read_bytes(), before)

    def test_editor_log_readback_not_observed_does_not_guess(self):
        from datetime import datetime, timedelta, timezone
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / "HeroProjects" / "CHAR_GPT" / "Saved" / "Logs"
            folder.mkdir(parents=True)
            path = folder / "DirectorHeroGPT.log"
            now = datetime.now(timezone.utc).replace(microsecond=0)
            stamp = now.strftime("[%Y.%m.%d-%H.%M.%S:000]")
            path.write_text(stamp + " LogPython: Error: unrelated exception", encoding="utf-8")
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                report = ue_process.hero_rig_editor_log_diagnostic(
                    root, (now - timedelta(seconds=1)).isoformat(),
                    (now + timedelta(seconds=1)).isoformat())
            self.assertEqual(report["readback_exception"], "not_observed")


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
        self.assertIn('"-ExecutePythonScript="', source)
        self.assertNotIn('argv = [str(editor), str(project), "-run=pythonscript"', source)
        self.assertIn('Win64\\UnrealEditor.exe', source)
        self.assertIn('"hero_interactive_gui_editor_missing"', source)
        self.assertIn('"hero_rig_v200"', source)
        self.assertNotIn("shell=True", source)
        self.assertIn("_interactive_hero_preflight(root, ident)", source)
        self.assertIn("time.monotonic() - last_valid_worker_heartbeat > 15", source)

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
        # Two exact triggers: owner logon and owner RDP reconnection.
        self.assertIn("New-ScheduledTaskTrigger -AtLogOn -User $identity.Name", code)
        self.assertIn("$currentDefinition.Triggers.Create(11)", code)
        self.assertIn("$rdpTrigger.UserId = $identity.User.Value", code)
        self.assertIn("$rdpTrigger.StateChange = 3", code)
        self.assertIn("$targetSid -ne $expectedSid", code)
        self.assertIn("$remoteConnectCount -gt 1", code)
        # Only an already verified task may be migrated; never a foreign one.
        self.assertIn("verified_logon_only", code)
        self.assertIn("unexpected_task_action", code)
        self.assertIn("unexpected_task_description", code)
        self.assertIn("principal_not_interactive_token", code)
        self.assertIn("RegisterTaskDefinition(", code)
        self.assertIn("Task update failed and was restored", code)
        self.assertIn("Start-ScheduledTask -TaskName $taskName", code)
        self.assertIn("RestartCount 12", code)
        self.assertIn("-MultipleInstances IgnoreNew", code)
        self.assertIn('"2.6.3"', code)
        self.assertNotIn("Invoke-WebRequest", code)
        self.assertNotIn("Start-Process", code)
        self.assertNotIn("RunLevel Highest", code)


if __name__ == "__main__":
    unittest.main()
