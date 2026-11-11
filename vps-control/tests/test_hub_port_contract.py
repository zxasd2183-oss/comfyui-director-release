"""Keep Director Hub bound to the production 8898/8899 port contract.

8896 belongs to the existing OIDC service and 8897 belongs to Glacier OIDC.
Neither port may be claimed by new Hub installers or Brain Link upgrades.
These source checks run in CI without opening sockets or touching any VPS.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
VPS=ROOT/"vps-control"
STUDIO=ROOT/"studio"


def content(path):
    return path.read_text(encoding="utf-8")


class HubPortContractTests(unittest.TestCase):
    def test_hub_bind_and_bridge_upstream_both_point_to_8898(self):
        app=content(VPS/"hub_app.py")
        bridge=content(VPS/"hub_bridge.py")
        self.assertRegex(app,r'FastMCP\("Director Hub Studio Brain",\s*host="127\.0\.0\.1", port=8898,')
        self.assertIn('build_handler(token, upstream="http://127.0.0.1:8898/mcp")',bridge)
        self.assertIn('("127.0.0.1", 8899)',bridge)
        self.assertNotIn("port=8896",app)
        self.assertNotIn("127.0.0.1:8896/mcp",bridge)
        nginx=content(VPS/"nginx-alidns"/"jipite-hub.conf")
        self.assertIn("proxy_pass http://127.0.0.1:8899;",nginx)
        self.assertIn("proxy_set_header Host 127.0.0.1:8899;",nginx)
        self.assertNotIn("127.0.0.1:8897",nginx)
        self.assertNotIn("127.0.0.1:8897",bridge)

    def test_all_three_installers_probe_8898_not_8896(self):
        for path in (STUDIO/"install-brain-link.sh",
                     VPS/"install-hub-v05.sh",VPS/"install-hub-v06.sh"):
            with self.subTest(path=path.name):
                script=content(path)
                self.assertIn("8898",script)
                self.assertNotIn("http://127.0.0.1:8896/mcp",script)
        link=content(STUDIO/"install-brain-link.sh")
        self.assertIn('"$VPS/hub_bridge.py" "$HUB/hub_bridge.py"',link)
        self.assertIn('systemctl restart director-hub-bridge',link)
        self.assertIn("proxy_pass http://127.0.0.1:8899;",link)
        for installer in ("install-hub-v05.sh","install-hub-v06.sh"):
            self.assertIn("proxy_pass http://127.0.0.1:8899;",
                          content(VPS/installer))
        self.assertIn('cp -p "$BACKUP/hub_bridge.py" "$HUB/hub_bridge.py"',link)
        v05=content(VPS/"install-hub-v05.sh")
        self.assertIn("hub_brain.py hub_file_sync.py hub_sync_jobs.py hub_app.py hub_bridge.py",v05)

    def test_v06_upgrade_checks_eight_core_and_forty_seven_hub_tools(self):
        script=content(VPS/"install-hub-v06.sh")
        groups=re.search(
            r'^core=(\{.*?\})\s*^hub=(\{.*?\})\s*^for attempt in range\(8\):',
            script,re.S|re.M)
        self.assertIsNotNone(groups,"MCP registry probes not found")
        core=ast.literal_eval(groups.group(1))
        hub=ast.literal_eval(groups.group(2))
        self.assertEqual(len(core),8)
        self.assertEqual(len(hub),47)
        # Guard against omitted or invented tool names at deployment.
        registered=set(re.findall(
            r'@app\.tool\([\s\S]*?\)\n(?:\#[^\n]*\n)*def\s+(\w+)\s*\(',
            content(VPS/"hub_app.py")))
        self.assertEqual(hub,registered)
        self.assertTrue(core<=hub|{"get_power_service_health"})
        self.assertIn('((8892,core),(8898,hub))',script)
        self.assertIn('"$SRC/hub_bridge.py" "$HUB/hub_bridge.py"',script)
        self.assertIn('systemctl restart director-hub-bridge',script)


    def test_installer_accepts_only_exact_retired_gpu_readonly_state(self):
        script=content(VPS/"install-hub-v06.sh")
        # Verify the embedded, actual post-deployment Python probe compiles.
        probe=re.search(r"""(?s)"\$PYTHON" - <<'PY'\n(.*?)\nPY""",script)
        self.assertIsNotNone(probe,"read-only deployment probe missing")
        compile(probe.group(1),"<director-hub-deploy-probe>","exec")
        self.assertIn('controller.get("configured")',probe.group(1))
        self.assertIn('controller.get("instance_selected")',probe.group(1))
        self.assertIn('controller.get("gpu_control_enabled") is False',probe.group(1))
        self.assertIn('controller.get("mode") == "read_only"',probe.group(1))
        self.assertIn('stat.get("ok") is False',probe.group(1))
        self.assertIn('stat.get("mode") == "read_only"',probe.group(1))
        self.assertIn('stat.get("reason") == "provider_request_failed"',probe.group(1))
        self.assertIn('raise RuntimeError("Read-only status backend unavailable")',probe.group(1))
        self.assertNotIn('read(port,"start_gpu_now")',probe.group(1))
        self.assertNotIn('read(port,"stop_gpu_now")',probe.group(1))
        self.assertIn("Hub 47 tools; no GPU power operation",probe.group(1))


if __name__=="__main__":
    unittest.main()
