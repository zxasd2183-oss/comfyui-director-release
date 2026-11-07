"""Studio -> localhost MCP may only invoke two fixed owner power tools."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gpu_power_bridge import operate, CORE


class FakeResponse:
    def __init__(self, uri, value):
        self.uri, self.value = uri, value
    def geturl(self):
        return self.uri
    def read(self, limit):
        return json.dumps(self.value).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, result=None, redirect=False):
        self.result = result or {"jsonrpc": "2.0", "result": {
            "structuredContent": {"ok": True, "state": "submitted",
                                  "approval_required": False, "secret": "NEVER"}}}
        self.redirect = redirect
        self.requests = []
    def open(self, req, timeout):
        self.requests.append(req)
        return FakeResponse("https://example.org/" if self.redirect else CORE, self.result)


class PowerBridgeTests(unittest.TestCase):
    def test_start_is_fixed_loopback_tool_and_redacted(self):
        api = FakeOpener()
        outcome = operate("start", api)
        self.assertTrue(outcome["ok"])
        self.assertNotIn("secret", outcome)
        req = api.requests[0]
        self.assertEqual(req.full_url, CORE)
        self.assertEqual(req.get_method(), "POST")
        body = json.loads(req.data)
        self.assertEqual(body["params"],
                         {"name": "start_gpu_now", "arguments": {}})

    def test_stop_and_no_user_supplied_host(self):
        api = FakeOpener()
        self.assertTrue(operate("stop", api)["ok"])
        body = json.loads(api.requests[0].data)
        self.assertEqual(body["params"]["name"], "stop_gpu_now")

    def test_invalid_action_never_networks(self):
        api = FakeOpener()
        self.assertEqual(operate("stop;rm -rf /", api)["reason"], "invalid_power_action")
        self.assertFalse(api.requests)

    def test_redirect_rejected(self):
        api = FakeOpener(redirect=True)
        result = operate("start", api)
        self.assertEqual(result["reason"], "power_backend_redirect_denied")

    def test_backend_fail_closed(self):
        api = FakeOpener(result={"jsonrpc": "2.0", "error": {"message": "private"}})
        self.assertEqual(operate("start", api)["reason"], "power_backend_protocol_error")


if __name__ == "__main__":
    unittest.main()
