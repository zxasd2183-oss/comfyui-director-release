"""Keep Director Hub bound to the production 8898/8897 port contract.

8896 belongs to the unrelated OIDC notification service and must never be
reintroduced by fresh installs, safe upgrades or Brain Link rollouts.
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
        self.assertIn('("127.0.0.1", 8897)',bridge)
        self.assertNotIn("port=8896",app)
        self.assertNotIn("127.0.0.1:8896/mcp",bridge)
        nginx=content(VPS/"nginx-alidns"/"jipite-hub.conf")
        self.assertIn("proxy_pass http://127.0.0.1:8897;",nginx)

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
        self.assertIn('cp -p "$BACKUP/hub_bridge.py" "$HUB/hub_bridge.py"',link)
        v05=content(VPS/"install-hub-v05.sh")
        self.assertIn("hub_brain.py hub_app.py hub_bridge.py",v05)

    def test_legacy_v06_upgrade_checks_six_core_and_nineteen_hub_tools(self):
        script=content(VPS/"install-hub-v06.sh")
        groups=re.search(
            r'^core=(\{.*?\})\s*^hub=(\{.*?\})\s*^for attempt in range\(8\):',
            script,re.S|re.M)
        self.assertIsNotNone(groups,"MCP registry probes not found")
        core=ast.literal_eval(groups.group(1))
        hub=ast.literal_eval(groups.group(2))
        self.assertEqual(len(core),6)
        self.assertEqual(len(hub),19)
        self.assertTrue(core<=hub|{"get_power_service_health"})
        self.assertIn('((8892,core),(8898,hub))',script)
        self.assertIn('"$SRC/hub_bridge.py" "$HUB/hub_bridge.py"',script)
        self.assertIn('systemctl restart director-hub-bridge',script)


if __name__=="__main__":
    unittest.main()
