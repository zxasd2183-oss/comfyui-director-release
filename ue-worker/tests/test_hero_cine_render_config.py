"""Offline safety tests for isolated MetaHuman Renderer configuration."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


def workspace(root, existing=None):
    root.mkdir(parents=True, exist_ok=True)
    project = root / "HeroProjects" / "CHAR_GPT" / "DirectorHeroGPT.uproject"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps(agent.hero_project_manifest()), encoding="utf-8")
    folder = project.parent / "Config"
    folder.mkdir()
    ini = folder / "DefaultEngine.ini"
    if existing is not None:
        ini.write_bytes(existing)
    original = root / "DirectorVirtualStudio.uproject"
    original.write_bytes(b"LOCKED_PRODUCTION_EP01")
    return ini, original


class RendererConfigTests(unittest.TestCase):
    def test_pre_existing_ini_is_exactly_backed_up_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "DirectorVirtualStudio"
            original = (b"[/Script/EngineSettings.GameMapsSettings]\r\n"
                        b"GameDefaultMap=/Engine/Maps/Templates/Template_Default\r\n")
            ini, episode = workspace(root, original)
            with patch.object(agent, "workspace_root", return_value=root):
                first = agent.prepare_hero_cine_render_config()
                after = ini.read_bytes()
                second = agent.prepare_hero_cine_render_config()
                audit = agent.hero_cine_config_audit(root)
            self.assertTrue(first["configured"])
            self.assertTrue(first["changed"])
            self.assertTrue(first["backup_created"])
            self.assertTrue(second["configured"])
            self.assertFalse(second["changed"])
            self.assertEqual(ini.read_bytes(), after)
            self.assertEqual(
                (ini.parent / "DefaultEngine.ini.pre-director-cine-v1.bak").read_bytes(),
                original)
            self.assertTrue(after.startswith(original))
            self.assertEqual(first["ini_sha256"], hashlib.sha256(after).hexdigest())
            self.assertTrue(audit["explicit_settings"]["dx12_default_explicit"])
            self.assertTrue(audit["explicit_settings"]["sm6_target_explicit"])
            self.assertTrue(audit["explicit_settings"]["gpu_skin_16bit_explicit"])
            self.assertTrue(audit["explicit_settings"]["gpu_skin_unlimited_explicit"])
            self.assertTrue(audit["explicit_settings"]["skin_cache_explicit"])
            self.assertEqual(episode.read_bytes(), b"LOCKED_PRODUCTION_EP01")
            self.assertFalse(first["mutations_outside_isolated_config"])

    def test_foreign_or_conflicting_rhi_fails_without_modification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "DirectorVirtualStudio"
            ini, _ = workspace(root,
                b"[/Script/WindowsTargetPlatform.WindowsTargetSettings]\n"
                b"DefaultGraphicsRHI=DefaultGraphicsRHI_DX11\n")
            before = ini.read_bytes()
            with patch.object(agent, "workspace_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "existing_conflict"):
                    agent.prepare_hero_cine_render_config()
            self.assertEqual(ini.read_bytes(), before)
            self.assertFalse(
                (ini.parent / "DefaultEngine.ini.pre-director-cine-v1.bak").exists())
            project = ini.parent.parent / "DirectorHeroGPT.uproject"
            project.write_bytes(b"foreign")
            with patch.object(agent, "workspace_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "project_untrusted"):
                    agent.prepare_hero_cine_render_config()

    def test_existing_sm5_can_coexist_with_explicit_sm6(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "DirectorVirtualStudio"
            ini, _ = workspace(root,
                b"[/Script/WindowsTargetPlatform.WindowsTargetSettings]\n"
                b"+D3D12TargetedShaderFormats=PCD3D_SM5\n")
            with patch.object(agent, "workspace_root", return_value=root):
                result = agent.prepare_hero_cine_render_config()
                audit = agent.hero_cine_config_audit(root)
            self.assertTrue(result["configured"])
            self.assertTrue(audit["explicit_settings"]["sm5_target_explicit"])
            self.assertTrue(audit["explicit_settings"]["sm6_target_explicit"])

    def test_symlink_and_oversized_ini_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "DirectorVirtualStudio"
            ini, _ = workspace(root)
            ini.write_bytes(b"X" * 131073)
            with patch.object(agent, "workspace_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "ini_oversized"):
                    agent.prepare_hero_cine_render_config()
            ini.unlink()
            other = root / "outside.ini"
            other.write_bytes(b"Not ours")
            try:
                ini.symlink_to(other)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            with patch.object(agent, "workspace_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "link_unsafe"):
                    agent.prepare_hero_cine_render_config()


if __name__ == "__main__":
    unittest.main()
