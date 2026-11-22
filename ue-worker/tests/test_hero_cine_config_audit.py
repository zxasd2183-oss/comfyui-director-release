"""Offline read-only audit for fixed GPT Hero project settings."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def prepare(root):
    project = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text(json.dumps(agent.hero_project_manifest()), "utf-8")
    (project.parent / "Config").mkdir()
    return project.parent / "Config" / "DefaultEngine.ini"


class ConfigAuditTests(unittest.TestCase):
    def test_missing_ini_is_not_claimed_as_effective_engine_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prepare(root)
            result = agent.hero_cine_config_audit(root)
        self.assertTrue(result["available"])
        self.assertEqual(result["state"], "ini_not_present")
        self.assertTrue(all(v is False for v in result["explicit_settings"].values()))
        self.assertFalse(result["mutations_performed"])

    def test_explicit_dx12_sm6_gpu_skin_values_are_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ini = prepare(root)
            ini.write_text(
                "[/Script/WindowsTargetPlatform.WindowsTargetSettings]\n"
                "DefaultGraphicsRHI=DefaultGraphicsRHI_DX12\n"
                "+D3D12TargetedShaderFormats=PCD3D_SM6\n"
                "[/Script/Engine.RendererSettings]\n"
                "r.GPUSkin.Support16BitBoneIndex=True\n"
                "r.GPUSkin.UnlimitedBoneInfluences=True\n"
                "r.SkinCache.CompileShaders=True\n",
                encoding="utf-8")
            before = ini.read_bytes()
            result = agent.hero_cine_config_audit(root)
            self.assertTrue(result["available"])
            self.assertTrue(result["explicit_settings"]["dx12_default_explicit"])
            self.assertTrue(result["explicit_settings"]["sm6_target_explicit"])
            self.assertTrue(result["explicit_settings"]["gpu_skin_16bit_explicit"])
            self.assertTrue(result["explicit_settings"]["gpu_skin_unlimited_explicit"])
            self.assertTrue(result["explicit_settings"]["skin_cache_explicit"])
            self.assertFalse(result["explicit_settings"]["sm5_target_explicit"])
            self.assertEqual(before, ini.read_bytes())

    def test_foreign_project_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ini = prepare(root)
            project = ini.parent.parent / "DirectorHeroGPT.uproject"
            project.write_text('{"Plugins":[]}', "utf-8")
            self.assertEqual(agent.hero_cine_config_audit(root)["state"],
                             "untrusted_project")
            project.write_text(json.dumps(agent.hero_project_manifest()), "utf-8")
            target = root / "untrusted.ini"
            target.write_text("[ConsoleVariables]\nr.GPUSkin.Support16BitBoneIndex=True")
            try:
                ini.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            self.assertEqual(agent.hero_cine_config_audit(root)["state"],
                             "unsafe_ini_path")

    def test_status_includes_read_only_audit(self):
        script = (Path(__file__).resolve().parents[1] / "agent.py").read_text("utf-8")
        self.assertIn('"hero_cine_config_audit": hero_cine_config_audit()', script)
        self.assertNotIn("subprocess", agent.hero_cine_config_audit.__doc__)
        self.assertNotIn("write_text(", agent.hero_cine_config_audit.__doc__)


if __name__ == "__main__":
    unittest.main()
