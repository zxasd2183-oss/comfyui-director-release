"""V05 VPS-bridge operations: strict IDs, log allowlist and no shell relay."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


class Response:
    def __init__(self, url):
        self.url = url
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, limit):
        return b'{"ok":true,"cancel_requested":true}'


class Opener:
    def __init__(self):
        self.calls = []
    def open(self, request, timeout=0):
        self.calls.append(request)
        return Response(request.full_url)


class V05Routes(unittest.TestCase):
    def test_valid_requests_use_only_local_tunnel_and_no_payload(self):
        with tempfile.TemporaryDirectory() as td:
            secret = Path(td) / "worker.token"
            secret.write_text("a" * 64)
            secret.chmod(0o600)
            opener = Opener()
            with patch.dict(os.environ, {"DIRECTOR_UE_WORKER_ENABLED": "1"}):
                log = rpc.get_ue_job_logs("f"*32, "render_13", opener, secret)
                stop = rpc.cancel_ue_job("f"*32, opener, secret)
            self.assertTrue(log["ok"])
            self.assertTrue(stop["ok"])
            self.assertEqual(len(opener.calls), 2)
            self.assertEqual(
                opener.calls[0].full_url,
                "http://127.0.0.1:18910/v3/jobs/" + "f"*32 + "/logs/render_13",
            )
            self.assertEqual(opener.calls[0].get_method(), "GET")
            self.assertEqual(
                opener.calls[1].full_url,
                "http://127.0.0.1:18910/v3/jobs/" + "f"*32 + "/cancel",
            )
            self.assertEqual(opener.calls[1].get_method(), "POST")
            self.assertIsNone(opener.calls[1].data)

    def test_invalid_fields_never_reach_network(self):
        opener = Opener()
        for jobid in ("../", "abc", "g"*32, "a"*32+"/../"):
            self.assertEqual(
                rpc.cancel_ue_job(jobid, opener)["reason"], "invalid_job_id"
            )
            self.assertEqual(
                rpc.get_ue_job_logs(jobid, "preset", opener)["reason"],
                "invalid_job_id"
            )
        for kind in ("../../../worker.token", "agent", "render_02", "render_01?x"):
            self.assertEqual(
                rpc.get_ue_job_logs("a"*32, kind, opener)["reason"],
                "invalid_log_kind"
            )
        self.assertEqual(opener.calls, [])


if __name__ == "__main__":
    unittest.main()
