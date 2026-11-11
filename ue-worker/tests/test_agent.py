"""Offline tests for the Windows worker protocol; run on any OS."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class WorkerApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        self.server.token = "a" * 64
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.env = patch.dict("os.environ", {"DIRECTOR_UE_WORKSPACE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, path, body=None, auth=True):
        headers = {}
        if auth:
            headers["Authorization"] = "Bearer " + "a" * 64
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_denies_unauthenticated(self):
        code, data = self.request("/v1/status", auth=False)
        self.assertEqual(code, 401)
        self.assertFalse(data["ok"])

    def test_capabilities_explicitly_deny_shell(self):
        code, data = self.request("/v1/capabilities")
        self.assertEqual(code, 200)
        self.assertFalse(data["supports_arbitrary_commands"])
        self.assertEqual(data["actions"], ["prepare_workspace"])

    def test_workspace_setup_is_idempotent(self):
        for _ in range(2):
            code, data = self.request("/v1/actions", {"action": "prepare_workspace"})
            self.assertEqual(code, 200)
            self.assertTrue(data["ok"])
        self.assertTrue((Path(self.tmp.name) / "Sequences").is_dir())
        self.assertTrue((Path(self.tmp.name) / "Outputs").is_dir())

    def test_rejects_arbitrary_action_and_extra_parameters(self):
        code, _ = self.request("/v1/actions", {"action": "run_shell"})
        self.assertEqual(code, 403)
        code, _ = self.request("/v1/actions", {"action": "prepare_workspace",
                                                "path": "/etc"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
