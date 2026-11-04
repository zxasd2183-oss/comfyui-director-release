import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from scripts.recover_gpu_v3 import (
    read_installed, start_installed_director, tools_ready,
    director_health, comfyui_health, main,
)

TOKEN="a"*64
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/"config.json").write_text(json.dumps(
            {"port":8790,"mcp_path":"/mcp/"+TOKEN}),encoding="utf-8")
    def tearDown(self):
        self.temp.cleanup()

    def test_existing_install_port_and_secret_path(self):
        self.assertEqual(read_installed(self.root),(8790,"/mcp/"+TOKEN))

    def test_refuse_slink_port(self):
        (self.root/"config.json").write_text(json.dumps(
            {"port":8765,"mcp_path":"/mcp/"+TOKEN}))
        with self.assertRaises(ValueError):
            read_installed(self.root)

    def test_refuse_missing_or_too_short_secret(self):
        (self.root/"config.json").write_text(json.dumps(
            {"port":8790,"mcp_path":"/mcp/secret"}))
        with self.assertRaises(ValueError):
            read_installed(self.root)

    def test_reject_symlink_config(self):
        src=self.root/"source.json"
        (self.root/"config.json").rename(src)
        (self.root/"config.json").symlink_to(src)
        with self.assertRaises(ValueError):
            read_installed(self.root)

    @patch("scripts.recover_gpu_v3.json_get")
    def test_director_health_requires_v3(self, getter):
        getter.return_value={"ok":True,"version":"0.2.0"}
        self.assertFalse(director_health(8790))
        getter.return_value={"ok":True,"version":"0.3.0"}
        self.assertTrue(director_health(8790))

    @patch("scripts.recover_gpu_v3.json_get")
    def test_comfyui_health(self,getter):
        getter.return_value={"system":{"os":"Linux"}}
        self.assertTrue(comfyui_health())
        getter.side_effect=ConnectionError
        self.assertFalse(comfyui_health())

    @patch("scripts.recover_gpu_v3.json_get")
    def test_tools_list_needs_expected_readonly_controls(self,getter):
        names=["get_studio_status","get_queue_summary","get_upgrade_readiness",
               "audit_h3_workflow","a","b","c","d"]
        getter.return_value={"result":{"tools":[{"name":n} for n in names]}}
        self.assertEqual(tools_ready(8790,"/mcp/"+TOKEN),(True,8))
        getter.return_value={"result":{"tools":[{"name":"unknown"}]}}
        self.assertEqual(tools_ready(8790,"/mcp/"+TOKEN),(False,1))

    @patch("scripts.recover_gpu_v3.director_health",return_value=True)
    @patch("scripts.recover_gpu_v3.subprocess.run")
    def test_healthy_supervisor_never_restarted(self, run, health):
        self.assertTrue(start_installed_director(self.root,8790))
        run.assert_not_called()

    @patch("scripts.recover_gpu_v3.director_health",return_value=False)
    @patch("scripts.recover_gpu_v3.subprocess.run")
    def test_missing_start_script_does_not_invoke_commands(self,run,health):
        self.assertFalse(start_installed_director(self.root,8790))
        run.assert_not_called()

    @patch("scripts.recover_gpu_v3.comfyui_health",return_value=True)
    @patch("scripts.recover_gpu_v3.tools_ready",return_value=(True,8))
    @patch("scripts.recover_gpu_v3.director_health",return_value=True)
    @patch("scripts.recover_gpu_v3.start_quick_tunnel")
    def test_local_only_does_not_invoke_tunnel(self,tunnel,health,tools,comfy):
        self.assertEqual(main(["--root",str(self.root)]),0)
        tunnel.assert_not_called()

    @patch("scripts.recover_gpu_v3.comfyui_health",return_value=False)
    @patch("scripts.recover_gpu_v3.tools_ready",return_value=(True,8))
    @patch("scripts.recover_gpu_v3.director_health",return_value=True)
    @patch("scripts.recover_gpu_v3.start_quick_tunnel")
    def test_tunnel_is_opt_in(self,tunnel,health,tools,comfy):
        tunnel.return_value=("https://testing.trycloudflare.com/mcp/"+TOKEN,12345)
        self.assertEqual(main(["--root",str(self.root),"--tunnel"]),0)
        tunnel.assert_called_once()

if __name__=="__main__":
    unittest.main()
