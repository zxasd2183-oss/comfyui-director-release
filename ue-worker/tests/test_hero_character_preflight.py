"""V1.2.2 hero MetaHuman preflight: no GPU, no arbitrary execution."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class HeroMetaHumanPreflightTests(unittest.TestCase):
    def test_unconfigured_project_never_claims_ready(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(agent, "workspace_root", return_value=Path(td)), \
                 patch.object(agent, "find_ue_installations", return_value=[]):
                state = agent.hero_character_readiness()
        self.assertEqual(state["target"], "WaitingOffice/EP01/CHAR_GPT")
        self.assertEqual(state["project_state"], "missing")
        self.assertFalse(state["metahuman_project_plugin_enabled"])
        self.assertFalse(state["character_production_ready"])
        self.assertFalse(state["mutations_performed"])
        self.assertIn("not_verified", state["creator_core_data"])
        self.assertIn("not_verified", state["epic_cloud_auth"])

    def test_plugin_descriptor_and_project_flag_are_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = root / "UE_5.8" / "Engine"
            exe = engine / "Binaries" / "Win64" / "UnrealEditor.exe"
            exe.parent.mkdir(parents=True)
            exe.touch()
            plugin = (engine / "Plugins" / "MetaHuman" /
                      "MetaHumanCharacter")
            plugin.mkdir(parents=True)
            (plugin / "MetaHumanCharacter.uplugin").write_text("{}")
            ex = plugin / "Content" / "Python" / "examples"
            ex.mkdir(parents=True)
            (ex / "example_create_asset.py").write_text("pass")
            project = root / "workspace" / "DirectorVirtualStudio.uproject"
            project.parent.mkdir()
            project.write_text(json.dumps({
                "Plugins": [{"Name": "MetaHumanCharacter", "Enabled": True}]
            }), encoding="utf-8")
            with patch.object(agent, "workspace_root", return_value=project.parent), \
                 patch.object(agent, "find_ue_installations",
                              return_value=[{"editor_path": str(exe)}]):
                state = agent.hero_character_readiness()
            self.assertTrue(state["engine_detected"])
            self.assertTrue(state["metahuman_character_plugin_descriptor_found"])
            self.assertTrue(state["metahuman_python_examples_found"])
            self.assertTrue(state["metahuman_project_plugin_enabled"])
            self.assertEqual(state["project_state"], "valid")
            self.assertFalse(state["character_production_ready"])

    def test_fake_project_plugin_does_not_pass_installation_check(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "DirectorVirtualStudio.uproject").write_text(
                json.dumps({"Plugins": [
                    {"Name": "MetaHumanCharacter", "Enabled": True}]}),
                encoding="utf-8")
            with patch.object(agent, "workspace_root", return_value=root), \
                 patch.object(agent, "find_ue_installations", return_value=[]):
                state = agent.hero_character_readiness()
            self.assertTrue(state["metahuman_project_plugin_enabled"])
            self.assertFalse(state["metahuman_character_plugin_descriptor_found"])
            self.assertFalse(state["character_production_ready"])

    def test_status_provides_safe_read_only_preflight(self):
        with patch.object(agent, "find_ue_installations", return_value=[]), \
             patch.object(agent, "gpu_summary", return_value={"available": False}), \
             patch.object(agent, "workspace_root", return_value=Path("/not_a_workspace")), \
             patch.object(agent, "signed_update_status", return_value={"status": "ok"}):
            state = agent.status()
        self.assertEqual(state["worker_version"], "1.2.3")
        self.assertIn("hero_character_readiness", state)
        self.assertFalse(state["hero_character_readiness"]["character_production_ready"])


if __name__ == "__main__":
    unittest.main()
