"""Fail-closed adapter tests: no external sockets."""
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


class FakeResponse:
    def __init__(self, url, value):
        self.url = url
        self.value = json.dumps(value).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, n):
        return self.value[:n]


class FakeOpener:
    def __init__(self):
        self.calls = []
    def open(self, request, timeout=None):
        self.calls.append(request)
        return FakeResponse(request.full_url, {"ok": True, "node_id": "ue-worker-01"})


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = Path(self.tmp.name) / "token"
        self.token.write_text("f" * 64)
        self.token.chmod(0o600)
        self.env = patch.dict(os.environ, {"DIRECTOR_UE_WORKER_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_read_route_is_pinned(self):
        opener = FakeOpener()
        response = rpc.call_ue_worker("get_ue_worker_status", opener, self.token)
        self.assertTrue(response["ok"])
        request = opener.calls[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18910/v1/status")
        self.assertTrue(request.get_header("Authorization").startswith("Bearer "))

    def test_only_named_workspace_action(self):
        opener = FakeOpener()
        response = rpc.call_ue_worker("prepare_ue_workspace", opener, self.token)
        self.assertTrue(response["ok"])
        self.assertEqual(json.loads(opener.calls[0].data), {"action": "prepare_workspace"})
        denied = rpc.call_ue_worker("run_command", opener, self.token)
        self.assertEqual(denied["reason"], "action_denied")
        self.assertEqual(len(opener.calls), 1)

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"DIRECTOR_UE_WORKER_ENABLED": "0"}):
            self.assertEqual(rpc.call_ue_worker("get_ue_worker_status",
                             token_file=self.token)["reason"], "ue_worker_not_enabled")

    def test_missing_secret_fails_closed(self):
        self.assertEqual(rpc.call_ue_worker("get_ue_worker_status",
                         token_file=Path(self.tmp.name) / "missing")["reason"],
                         "ue_worker_unavailable")


if __name__ == "__main__":
    unittest.main()
