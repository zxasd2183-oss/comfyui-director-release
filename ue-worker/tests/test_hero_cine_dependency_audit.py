"""Read-only failure evidence from one fixed Unreal MetaHuman project log."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import ue_process


def write_log(root, lines):
    path = root / "HeroProjects" / "CHAR_GPT" / "Saved" / "Logs" / "DirectorHeroGPT.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class CineDependencyEvidenceTests(unittest.TestCase):
    def test_recent_failure_scopes_missing_deps_and_sanitizes_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lines = [
                "[2026.11.22-07.30.00:000]LogAsset: Failed to load /Game/OldSecret/ShouldBeIgnored",
                "[2026.11.22-08.10.00:000]LogAsset: Failed to load /Game/Director/Candidates/EP01/HeroCine/Jabc/Face/SKM_Face",
                "[2026.11.22-08.11.00:000]LogAsset: Can't find file /Engine/Plugins/MetaHumanCreator/Animation/RTG_MH_IKRig",
                "[2026.11.22-08.12.00:000]LogPython: Warning: Director UE Cine phase=build exception_class=RuntimeError",
            ]
            log = write_log(root, lines)
            before = log.read_bytes()
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                output = ue_process.hero_cine_missing_dependency_audit(root)
            self.assertTrue(output["available"])
            self.assertEqual(output["categories"]["missing_package_lines"], 2)
            self.assertEqual(output["categories"]["project_or_other"], 1)
            self.assertEqual(output["categories"]["engine_metahuman"], 1)
            self.assertEqual(len(output["known_engine_meta_packages"]), 1)
            self.assertIn("/game/director/candidates/ep01/herocine/jabc/face/skm_face", output["known_ep01_packages"])
            self.assertIn("load_failed", output["missing_signal_kinds"])
            self.assertIn("file_not_found", output["missing_signal_kinds"])
            self.assertNotIn("SecretAvatar", str(output))
            self.assertNotIn("PrivateName", str(output))
            self.assertNotIn("OldSecret", str(output))
            self.assertFalse(output["mutations_performed"])
            self.assertEqual(log.read_bytes(), before)

    def test_absent_or_invalid_log_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(ue_process, "HERO_BRIDGE_ROOT", root):
                missing = ue_process.hero_cine_missing_dependency_audit(root)
                write_log(root, ["LogAsset: Failed to load /Game/FakeWithoutTimestamp"])
                unmatched = ue_process.hero_cine_missing_dependency_audit(root)
                wrong = ue_process.hero_cine_missing_dependency_audit(root / "Other")
            self.assertFalse(missing["available"])
            self.assertEqual(missing["reason"], "editor_log_unavailable")
            self.assertEqual(unmatched["reason"], "cine_failure_marker_not_found")
            self.assertEqual(wrong["reason"], "invalid_diagnostic_target")

    def test_existing_worker_status_has_safe_audit(self):
        script = (Path(__file__).resolve().parents[1] / "agent.py").read_text("utf-8")
        self.assertIn('"hero_cine_dependency_audit":', script)
        self.assertIn("hero_cine_missing_dependency_audit", script)
        self.assertNotIn("subprocess", ue_process.hero_cine_missing_dependency_audit.__doc__)


if __name__ == "__main__":
    unittest.main()
