"""Zero-UE tests for fixed failed Cine build's sanitized Editor log readback."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_process
import ue_jobs

START = "2026-11-22T07:34:18+00:00"
END = "2026-11-22T07:40:03+00:00"


def make_log(root, lines, mod_time="2026-11-22T07:39:59+00:00"):
    path = root / "HeroProjects" / "CHAR_GPT" / "Saved" / "Logs" / "DirectorHeroGPT.log"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    epoch = datetime.fromisoformat(mod_time).timestamp()
    os.utime(path, (epoch, epoch))
    return path


class CineFailedBuildLogTests(unittest.TestCase):
    def test_real_timestamp_and_safe_classification_without_raw_log(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = make_log(root, [
                "[2026.11.22-07.20.00:111]LogPython: Error: OLD failure ignored",
                "[2026.11.22-07.36.00:111]LogPython: Warning: Director UE Cine phase=build exception_class=RuntimeError",
                "[2026.11.22-07.36.01:222]LogControlRig: Error: Cannot break link email secret@example.com token=123",
                "[2026.11.22-07.37.00:333]LogKismetCompiler: Error: compile failed http://host.example/secret",
                "[2026.11.22-07.37.02:333]LogAsset: Warning: Failed to load /Game/HiddenOwner/Path",
            ])
            before = path.read_bytes()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                result = ue_process.hero_cine_editor_log_diagnostic(root, START, END)
            self.assertTrue(result["available"])
            self.assertEqual(result["status"], "analyzed")
            self.assertEqual(result["build_exception_class"], "RuntimeError")
            self.assertIn("control_rig_cannot_break_link", result["signals"])
            self.assertIn("control_rig_error", result["signals"])
            self.assertIn("blueprint_compile_error", result["signals"])
            self.assertIn("asset_dependency_missing", result["signals"])
            self.assertNotIn("OLD", str(result))
            self.assertNotIn("secret@example.com", str(result))
            self.assertNotIn("HiddenOwner", str(result))
            self.assertFalse(result["mutations_performed"])
            self.assertEqual(before, path.read_bytes())

    def test_missing_or_stale_log_does_not_invent_cause(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                unavailable = ue_process.hero_cine_editor_log_diagnostic(root, START, END)
                path = make_log(root, [
                    "[2026.11.22-07.36.01:222]LogControlRig: Error: Cannot break link",
                ], "2026-11-22T09:30:00+00:00")
                stale = ue_process.hero_cine_editor_log_diagnostic(root, START, END)
            self.assertEqual(unavailable["reason"], "editor_log_unavailable")
            self.assertEqual(stale["reason"], "editor_log_not_correlated")
            self.assertTrue(path.is_file())

    def test_unsupported_root_and_non_utc_window_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                wrong = ue_process.hero_cine_editor_log_diagnostic(root / "Other", START, END)
                bad_window = ue_process.hero_cine_editor_log_diagnostic(
                    root, "2026-11-22T07:34:18", END)
            self.assertEqual(wrong["reason"], "invalid_diagnostic_target")
            self.assertEqual(bad_window["reason"], "invalid_job_window")

    def test_no_timestamped_evidence_cannot_be_claimed_as_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_log(root, [
                "Cannot break link without a real UE UTC timestamp",
                "[2026.11.22-06.30.00:000]LogControlRig: Error: old failure",
            ])
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                result = ue_process.hero_cine_editor_log_diagnostic(root, START, END)
            self.assertEqual(result["status"], "no_correlated_timestamped_lines")
            self.assertEqual(result["signals"], [])
            self.assertEqual(result["build_exception_class"], "not_observed")

    def test_diagnostic_only_attached_to_failed_cine_job(self):
        code = (Path(__file__).resolve().parents[1] / "ue_jobs.py").read_text("utf-8")
        self.assertIn('response.get("task") == "build_ep01_hero_cine_assembly"', code)
        self.assertIn('response.get("reason") == "hero_cine_failed_build"', code)
        self.assertIn("hero_cine_editor_log_diagnostic", code)
        self.assertNotIn("subprocess", ue_process.hero_cine_editor_log_diagnostic.__doc__)


if __name__ == "__main__":
    unittest.main()
