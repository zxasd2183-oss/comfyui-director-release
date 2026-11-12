"""Isolated MetaHuman hero project: real JSON contract and no original asset writes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def fake_engine(root):
    engine = root / "UE_5.8" / "Engine"
    editor = engine / "Binaries" / "Win64" / "UnrealEditor.exe"
    editor.parent.mkdir(parents=True)
    editor.write_bytes(b"stub")
    plugin = (engine / "Plugins" / "MetaHuman" /
              "MetaHumanCharacter" / "MetaHumanCharacter.uplugin")
    plugin.parent.mkdir(parents=True)
    plugin.write_text("{}", encoding="utf-8")
    return [{"editor_path": str(editor)}]


class HeroProjectTests(unittest.TestCase):
    def test_prepare_isolated_project_twice_and_preserve_episode(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "DirectorVirtualStudio"
            root.mkdir()
            original = root / "DirectorVirtualStudio.uproject"
            original.write_bytes(b"EXISTING_EP01_SOURCE_LOCKED")
            with patch.object(agent, "workspace_root", return_value=root), \
                 patch.object(agent, "find_ue_installations",
                              return_value=fake_engine(base)):
                first = agent.prepare_hero_metahuman_project()
                second = agent.prepare_hero_metahuman_project()
                report = agent.hero_character_readiness()
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["state"], "prepared")
            self.assertEqual(original.read_bytes(), b"EXISTING_EP01_SOURCE_LOCKED")
            target = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
            data = json.loads(target.read_text("utf-8"))
            self.assertEqual(data, agent.hero_project_manifest())
            self.assertEqual(data["Plugins"][-1],
                             {"Name": "MetaHumanCharacter", "Enabled": True})
            self.assertEqual(report["isolated_hero_project_state"], "prepared")
            self.assertFalse(report["character_production_ready"])
            self.assertTrue((target.parent / "Content").is_dir())

    def test_rejects_missing_plugin_without_writing_any_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(agent, "workspace_root", return_value=root), \
                 patch.object(agent, "find_ue_installations", return_value=[]):
                with self.assertRaisesRegex(ValueError,
                                            "metahuman_plugin_not_installed"):
                    agent.prepare_hero_metahuman_project()
            self.assertFalse((root / "HeroProjects").exists())

    def test_collision_does_not_overwrite_unrelated_project(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "workspace"
            target = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"NOT OUR PROJECT")
            with patch.object(agent, "workspace_root", return_value=root), \
                 patch.object(agent, "find_ue_installations",
                              return_value=fake_engine(base)):
                with self.assertRaisesRegex(ValueError, "hero_project_collision"):
                    agent.prepare_hero_metahuman_project()
            self.assertEqual(target.read_bytes(), b"NOT OUR PROJECT")

    def test_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "workspace"
            root.mkdir()
            (root / "HeroProjects").symlink_to(base / "other", target_is_directory=True)
            with patch.object(agent, "workspace_root", return_value=root), \
                 patch.object(agent, "find_ue_installations",
                              return_value=fake_engine(base)):
                with self.assertRaisesRegex(ValueError, "unsafe_hero_project_directory"):
                    agent.prepare_hero_metahuman_project()


if __name__ == "__main__":
    unittest.main()
