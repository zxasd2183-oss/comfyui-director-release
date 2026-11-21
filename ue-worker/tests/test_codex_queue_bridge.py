"""Offline, no-network tests for local-consent Codex queue bridge."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_process


FMT = "director_codex_bridge_v1"
THREAD = "01a1fe46-eafb-7db1-9b0f-bf4180cbd242"


def create_local(temp, thread=THREAD, enabled=True):
    local = temp / "Local"
    consent = local / "DirectorCodexBridge"
    consent.mkdir(parents=True)
    (consent / "consent.json").write_text(
        json.dumps({"format": FMT, "enabled": enabled, "thread_id": thread}),
        encoding="utf-8")
    exe = local / "OpenAI" / "Codex" / "bin" / "approved"
    exe.mkdir(parents=True)
    (exe / "codex.exe").write_bytes(b"offline_fake_exe")
    return local


class CodexQueueBridgeTests(unittest.TestCase):
    def test_no_consent_no_queue_and_no_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            root.mkdir()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.object(ue_process, "_codex_cli_path", create=True) as unused, \
                 patch.dict(os.environ, {"LOCALAPPDATA": str(Path(td) / "missing")}):
                ue_process._codex_poll(root, 2)
                result = ue_process.codex_stage("Do nothing", root)
                self.assertFalse(result["ok"])
                self.assertEqual(result["reason"], "codex_local_consent_required")
                self.assertFalse(ue_process.codex_bridge_status(root)["available"])
                self.assertEqual(list((root/"JobStatus"/"CodexBridge"/"requests").glob("*.json")), [])

    def test_same_thread_queue_and_separate_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            root = temp / "workspace"
            root.mkdir()
            local = create_local(temp)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), \
                 patch.object(ue_process.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner:
                ue_process._codex_poll(root, 2)
                self.assertEqual(ue_process.codex_bridge_status(root)["session_id"], 2)
                queued = ue_process.codex_stage("CODEX-HUB-1121: safe test", root)
                self.assertTrue(queued["ok"])
                self.assertEqual(queued["state"], "staged")
                self.assertFalse(queued["gui_delivery_confirmed"])
                ident = queued["request_id"]
                self.assertEqual(ue_process.codex_lookup(ident, root)["state"], "staged")
                ue_process._codex_poll(root, 2)
                runner.assert_called_once()
                args = runner.call_args.args[0]
                self.assertEqual(args[1:], ["queue", "--thread", THREAD,
                                            "--message", "CODEX-HUB-1121: safe test"])
                self.assertTrue(str(args[0]).endswith("codex.exe"))
                self.assertIs(runner.call_args.kwargs.get("shell", False), False)
                self.assertEqual(runner.call_args.kwargs["timeout"], 30)
                receipt = ue_process.codex_lookup(ident, root)
                self.assertTrue(receipt["ok"])
                self.assertEqual(receipt["state"], "queued_by_cli")
                self.assertFalse(receipt["completed"])
                self.assertFalse(receipt["gui_delivery_confirmed"])
                self.assertNotIn(THREAD, str(receipt))

    def test_failed_cli_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            root = temp / "workspace"
            root.mkdir()
            local = create_local(temp)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root), \
                 patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), \
                 patch.object(ue_process.subprocess, "run",
                              return_value=SimpleNamespace(returncode=1)):
                ue_process._codex_poll(root, 2)
                item = ue_process.codex_stage("No files", root)
                ue_process._codex_poll(root, 2)
                self.assertEqual(ue_process.codex_lookup(item["request_id"], root)["state"], "failed")

    def test_disabled_or_invalid_local_thread_denied(self):
        for thread,enabled in ((THREAD,False), ("not-a-thread",True)):
            with self.subTest(thread=thread,enabled=enabled):
                with tempfile.TemporaryDirectory() as td:
                    tmp=Path(td)
                    root=tmp/"workspace"
                    root.mkdir()
                    local=create_local(tmp,thread,enabled)
                    with patch.object(ue_process,"HERO_BRIDGE_ROOT",root), \
                         patch.dict(os.environ,{"LOCALAPPDATA":str(local)}):
                        ue_process._codex_poll(root,2)
                        self.assertFalse(ue_process.codex_bridge_status(root)["available"])
                        self.assertFalse(ue_process.codex_stage("safe test",root)["ok"])

    def test_message_validation_and_invalid_receipt_ids(self):
        for value in ("", "\x00", "\r\nbad", "X"*1201, None, {"bad":1}):
            self.assertFalse(ue_process._codex_message_valid(value))
        self.assertFalse(ue_process.codex_lookup("../secret")["ok"])
        self.assertFalse(ue_process.codex_lookup("123")["ok"])

    def test_stale_session_and_claimed_not_replayed(self):
        with tempfile.TemporaryDirectory() as td:
            tmp=Path(td)
            root=tmp/"workspace"
            root.mkdir()
            local=create_local(tmp)
            with patch.object(ue_process,"HERO_BRIDGE_ROOT",root), \
                 patch.dict(os.environ,{"LOCALAPPDATA":str(local)}), \
                 patch.object(ue_process.subprocess,"run",
                              return_value=SimpleNamespace(returncode=0)) as run:
                ue_process._codex_poll(root,2)
                msg=ue_process.codex_stage("one-time",root)
                ident=msg["request_id"]
                req=root/"JobStatus"/"CodexBridge"/"requests"/(ident+".json")
                claim=root/"JobStatus"/"CodexBridge"/"claims"/(ident+".json")
                claim.write_text(ident)
                ue_process._codex_poll(root,2)
                run.assert_not_called()
                self.assertEqual(ue_process.codex_lookup(ident,root)["state"],
                                 "claimed_unknown_delivery")
                self.assertTrue(req.exists())
                ready=root/"JobStatus"/"CodexBridge"/"ready.json"
                state=json.loads(ready.read_text("ascii"))
                state["updated"]=time.time()-60
                ready.write_text(json.dumps(state),encoding="ascii")
                self.assertFalse(ue_process.codex_stage("second",root)["ok"])


if __name__ == "__main__":
    unittest.main()
