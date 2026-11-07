import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub_rpc as hub
import hub_bridge
import configure_director_hub_nginx as nginx


class FakeStream:
    def __init__(self, body, url):
        self.body, self.url = body, url
    def geturl(self):
        return self.url
    def read(self, limit):
        return self.body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, data=None):
        self.data = data if data is not None else {"ok": True, "state": "Stopped"}
        self.requests = []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        answer = {"jsonrpc": "2.0", "id": 1,
                  "result": {"isError": False, "structuredContent": self.data}}
        return FakeStream(json.dumps(answer).encode(), request.full_url)


class HubV05Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.gpu = Path(self.temp.name) / "gpu-path"
        self.gpu.write_text("/mcp/" + ("a" * 64) + "\n")
        self.token = Path(self.temp.name) / "hub-token"
        self.token.write_text("b" * 64 + "\n")
        self.token.chmod(0o640)

    def test_allowlisted_tools_are_scoped(self):
        self.assertEqual(len(hub.ALL_TOOLS), 25)
        self.assertEqual(len(hub.GPU_TOOLS), 8)
        self.assertEqual(len(hub.VPS_TOOLS), 2)
        self.assertEqual(len(hub.POWER_TOOLS), 5)
        self.assertEqual(len(hub.BRAIN_TOOLS), 10)
        self.assertFalse(hub.BRAIN_TOOLS & hub.POWER_TOOLS)
        self.assertFalse(set(hub.GPU_TOOLS) & set(hub.POWER_TOOLS))

    def test_pinned_local_route_all_backends(self):
        self.assertEqual(hub.endpoint("get_studio_status", self.gpu),
                         "http://127.0.0.1:18790/mcp/" + "a" * 64)
        self.assertEqual(hub.endpoint("get_gpu_power_status"),
                         "http://127.0.0.1:8892/mcp")
        self.assertEqual(hub.endpoint("request_gpu_stop"),
                         "http://127.0.0.1:8892/mcp")
        with self.assertRaisesRegex(hub.HubError, "allowlisted"):
            hub.endpoint("run_shell")

    def test_no_outbound_gpu_when_missing_route(self):
        self.gpu.unlink()
        with patch.object(hub._OPENER, "open") as upstream:
            response = hub.call("get_studio_status", {}, self.gpu)
            self.assertEqual(response["reason"], "gpu_route_unconfigured")
            upstream.assert_not_called()

    def test_no_symlink_or_invalid_route(self):
        other = Path(self.temp.name) / "other"
        other.write_text("/mcp/" + "z" * 64)
        self.gpu.unlink()
        self.gpu.symlink_to(other)
        with self.assertRaisesRegex(hub.HubError, "unconfigured"):
            hub.gpu_path(self.gpu)
        self.gpu.unlink()
        self.gpu.write_text("https://attacker.example/mcp/" + "x" * 64)
        with self.assertRaisesRegex(hub.HubError, "invalid"):
            hub.gpu_path(self.gpu)

    def test_request_arguments_are_strict(self):
        with self.assertRaisesRegex(hub.HubError, "unexpected"):
            hub.check_args("request_gpu_stop", {"override": True})
        with self.assertRaisesRegex(hub.HubError, "unexpected"):
            hub.check_args("get_h3_workflow_structure", {})
        with self.assertRaisesRegex(hub.HubError, "invalid"):
            hub.check_args("get_power_request_status", {"request_id": "../secret"})
        with self.assertRaisesRegex(hub.HubError, "unexpected"):
            hub.check_args("get_h3_node_inputs", {"node_type": "MiniMaxH3", "shell": "id"})

    def test_gpu_proxy_uses_only_read_tool_and_local_port(self):
        mock = FakeOpener({"ok": True, "running": 0, "pending": 0})
        result = hub.call("get_queue_summary", {}, self.gpu, opener=mock)
        self.assertEqual(result["running"], 0)
        req, timeout = mock.requests[0]
        self.assertEqual(req.full_url, hub.endpoint("get_queue_summary", self.gpu))
        body = json.loads(req.data)
        self.assertEqual(body["params"]["name"], "get_queue_summary")
        self.assertEqual(body["params"]["arguments"], {})
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Host"), "127.0.0.1:8790")

    def test_power_write_only_creates_existing_request(self):
        mock = FakeOpener({"ok": True, "state": "pending",
                           "approval_required": "independent_browser_totp"})
        data = hub.call("request_gpu_start", opener=mock)
        self.assertEqual(data["state"], "pending")
        req = mock.requests[0][0]
        self.assertEqual(req.full_url, "http://127.0.0.1:8892/mcp")
        self.assertEqual(req.get_header("Host"), "127.0.0.1:8892")
        self.assertEqual(json.loads(req.data)["params"]["name"], "request_gpu_start")

    def test_upstream_error_and_sse_misparse_fails_closed(self):
        for payload in [
            {"jsonrpc": "2.0", "error": {"code": -32000, "message": "private_url"}},
            {"jsonrpc": "2.0", "result": {"isError": True, "content": []}},
            {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "secret"}]}},
        ]:
            with self.assertRaises(hub.HubError):
                hub.unwrap(payload)

    def test_text_result_compatibility(self):
        data = hub.unwrap({"jsonrpc": "2.0", "result": {"content": [
            {"type": "text", "text": '{"ok":true,"state":"Running"}'}]}})
        self.assertEqual(data["state"], "Running")

    def test_token_strict_and_file_permission(self):
        self.assertEqual(hub_bridge.load_token(self.token), "b" * 64)
        self.token.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "readable"):
            hub_bridge.load_token(self.token)
        self.token.unlink()
        self.token.symlink_to(self.gpu)
        with self.assertRaises(RuntimeError):
            hub_bridge.load_token(self.token)

    def test_nginx_target_patch_idempotent_preserves_mobile(self):
        src = '''server {
 listen 443 ssl;
 server_name jipite.borealos.cn;
 ssl_certificate /etc/nginx/cert.pem;
 location ^~ /api/v1/mobile/ { proxy_pass http://127.0.0.1:8895; }
 location / { return 200 "ok"; }
}
server { listen 443 ssl; server_name director.borealos.cn; location / { return 200; } }
'''
        patched, changed = nginx.patch(src)
        self.assertTrue(changed)
        self.assertEqual(nginx.DOMAIN, "jipite.borealos.cn")
        self.assertIn("127.0.0.1:8895", patched)
        self.assertIn("server_name director.borealos.cn", patched)
        self.assertEqual(patched.count(nginx.MARKER), 1)
        same, changed_again = nginx.patch(patched)
        self.assertFalse(changed_again)
        self.assertEqual(same, patched)

    def test_nginx_rejects_duplicate_and_inline_routes(self):
        src = '''server {
 listen 8443 ssl;
 server_name jipite.borealos.cn;
 location ^~ /mcp/ { proxy_pass http://127.0.0.1:9999; }
}
'''
        with self.assertRaisesRegex(RuntimeError, "inline"):
            nginx.patch(src)
        with self.assertRaisesRegex(RuntimeError, "one"):
            nginx.patch("server { listen 443 ssl; server_name other.example; }")


if __name__ == "__main__":
    unittest.main()
