"""Offline trust-contract test for one-time root Hub route repair."""
from __future__ import annotations
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
CONTROL=ROOT/"vps-control"
sys.path.insert(0,str(CONTROL))
import hub_rpc


class OwnerDirectRouterRepairTests(unittest.TestCase):
    def test_direct_tools_route_to_protected_vps_core_not_public_url(self):
        for name in ("start_gpu_now","stop_gpu_now"):
            self.assertIn(name,hub_rpc.POWER_TOOLS)
            self.assertEqual(hub_rpc.check_args(name,{}),{})
            self.assertEqual(hub_rpc.endpoint(name),"http://127.0.0.1:8892/mcp")
            with self.assertRaisesRegex(hub_rpc.HubError,"unexpected_arguments"):
                hub_rpc.check_args(name,{"url":"http://example.com"})
        self.assertNotIn("submit_power_request",hub_rpc.ALL_TOOLS)

    def test_fix_expects_exact_audited_pre_direct_and_current_blobs(self):
        script=(CONTROL/"repair-owner-direct-hub-route.sh").read_text("utf-8")
        old=re.search(r"^OLD_BLOB=([a-f0-9]{40})$",script,re.M).group(1)
        new=re.search(r"^NEW_BLOB=([a-f0-9]{40})$",script,re.M).group(1)
        current=subprocess.check_output(
            ["git","-C",str(ROOT),"hash-object",str(CONTROL/"hub_rpc.py")],
            text=True).strip()
        previous=subprocess.check_output(
            ["git","-C",str(ROOT),"rev-parse",
             "d1b6e998e6472e3e852129b8c718dabdcc4c4a3c:vps-control/hub_rpc.py"],
            text=True).strip()
        self.assertEqual(old,previous)
        self.assertEqual(new,current)
        self.assertNotEqual(old,new)
        self.assertIn("installed_router_not_known_audited_pre_direct_version",script)

    def test_repair_does_not_issue_start_or_stop(self):
        script=(CONTROL/"repair-owner-direct-hub-route.sh").read_text("utf-8")
        self.assertIn('hub_rpc.call("get_control_center_status")',script)
        self.assertNotIn('hub_rpc.call("start_gpu_now")',script)
        self.assertNotIn('hub_rpc.call("stop_gpu_now")',script)
        self.assertIn('cp -p -- "$TARGET" "$BACKUP/hub_rpc.py"',script)
        self.assertIn('trap rollback EXIT',script)
        syntax=subprocess.run(
            ["bash","-n",str(CONTROL/"repair-owner-direct-hub-route.sh")],
            capture_output=True,text=True,check=False)
        self.assertEqual(syntax.returncode,0,syntax.stderr)


if __name__=="__main__":
    unittest.main()
