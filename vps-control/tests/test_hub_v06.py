"""V0.6 tests: one private provider core, no extra GPU or power permissions."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub_rpc
import power_ops
import vps_unified_status as status


class _FakeCloud:
    def __init__(self, body):
        self.body = body
        self.actions = []

    def ucompshare(self):
        return self

    def invoke(self, name, values):
        self.actions.append(name)
        return self.body


def config():
    return {
        "COMP_PUBLIC_KEY": "not-for-logs",
        "COMP_PRIVATE_KEY": "even-more-private",
        "COMP_UHOST_ID": "instance-secret",
        "COMP_REGION": "cn-sh2", "COMP_ZONE": "cn-sh2-01",
    }


class UnifiedVpsV06Tests(unittest.TestCase):
    def test_status_configuration_no_key_leak(self):
        result = status.control_center_status(config)
        self.assertTrue(result["configured"])
        self.assertTrue(result["gpu_control_enabled"])
        self.assertEqual(result["version"],"0.7.0")
        self.assertEqual(result["stop_guard"],"ue_worker_tasklist_v1")
        self.assertEqual(result["mode"], "owner_direct")
        self.assertNotIn("COMP_PRIVATE_KEY", str(result))
        self.assertNotIn("not-for-logs", str(result))
        self.assertFalse(status.control_center_status(lambda: {})["configured"])
        self.assertFalse(status.control_center_status(lambda: 1/0)["configured"])

    def test_gpu_provider_read_only_redacts_secrets(self):
        cloud = _FakeCloud({"RetCode": 0, "UHostSet": [{
            "UHostId": "instance-secret", "Region": "cn-sh2",
            "Zone": "cn-sh2-01", "State": "Stopped",
            "GpuType": "5090", "GPU": 1, "ChargeType": "Postpay",
            "IsSpot": False, "SSHPassword": "must-not-leak",
        }]})
        result = status.gpu_power_status(
            config, state_fn=lambda cfg: power_ops.get_provider_state(cfg, client=cloud))
        self.assertEqual(result, {
            "ok": True, "state": "Stopped", "region": "cn-sh2",
            "zone": "cn-sh2-01", "gpu_type": "5090", "gpu_count": 1,
            "charge_type": "Postpay", "is_spot": False, "mode": "read_only",
        })
        self.assertEqual(cloud.actions, ["DescribeCompShareInstance"])
        self.assertNotIn("must-not-leak", json.dumps(result))
        self.assertNotIn("instance-secret", json.dumps(result))

    def test_gpu_status_fails_closed(self):
        self.assertEqual(status.gpu_power_status(lambda: 1 / 0),
                         {"ok": False, "reason": "not_configured", "mode": "read_only"})
        def leak(_):
            raise RuntimeError("my-private-key")
        result = status.gpu_power_status(config, state_fn=leak)
        self.assertEqual(result["reason"], "provider_request_failed")
        self.assertNotIn("my-private-key", str(result))

    def test_all_five_vps_tools_route_to_single_private_core(self):
        for name in hub_rpc.VPS_TOOLS | hub_rpc.POWER_TOOLS:
            self.assertEqual(hub_rpc.endpoint(name), "http://127.0.0.1:8892/mcp")
        self.assertEqual(len(hub_rpc.ALL_TOOLS), 25)
        with self.assertRaisesRegex(hub_rpc.HubError, "allowlisted"):
            hub_rpc.endpoint("submit_power_request")

    def test_stop_api_requires_existing_staged_preflight(self):
        # A stopped GPU may not be stopped; no cloud call or direct API route.
        result = power_ops.evaluate_action("stop", {"state": "Stopped"}, None)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "instance_state_not_running")
        result = power_ops.evaluate_action("stop", {"state": "Running"}, {
            "verified": False, "empty": True})
        self.assertEqual(result["reason"], "ue_worker_readiness_not_verified")


if __name__ == "__main__":
    unittest.main()
