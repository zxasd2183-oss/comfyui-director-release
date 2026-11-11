"""Offline tests for Hub's Studio-only UE job routing."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as ue


class Response:
    def __init__(self, url):
        self.url = url
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, max_bytes):
        return json.dumps({"ok": True, "job_id": "a"*32,
                           "state": "queued"}).encode()


class Opener:
    def __init__(self):
        self.calls = []
    def open(self, request, timeout=0):
        self.calls.append(request)
        return Response(request.full_url)


def studio(tool, fields):
    assert tool == "get_production_episode"
    assert fields == {"project_id": "WaitingOffice", "episode_id": "EP01"}
    shots = [{"shot_id": f"{i:02}", "ordinal": i, "duration_ms": ms*1000}
             for i, ms in enumerate(
                [3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5], 1)]
    return {"ok": True, "shots": shots,
            "shot_count": len(shots), "shots_truncated": False}


class StudioDispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = Path(self.tmp.name) / "token"
        self.token.write_text("b" * 64)
        self.token.chmod(0o600)
        self.env = patch.dict(os.environ, {"DIRECTOR_UE_WORKER_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_only_studio_registered_shots_are_sent(self):
        op = Opener()
        result = ue.enqueue_ue_episode_timeline(
            "WaitingOffice", "EP01", studio_getter=studio,
            opener=op, token_file=self.token
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(op.calls), 1)
        req = op.calls[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:18910/v2/jobs")
        spec = json.loads(req.data)
        self.assertEqual(spec["expected_total_ms"], 160000)
        self.assertEqual(len(spec["shots"]), 31)
        self.assertEqual(spec["fps"], 24)
        self.assertNotIn("script", spec)
        self.assertNotIn("command", spec)

    def test_truncated_studio_plan_denied(self):
        def truncated(tool, fields):
            return {"ok": True, "shots": [{"shot_id": "01", "ordinal": 1,
                                             "duration_ms": 5000}],
                    "shot_count": 31, "shots_truncated": True}
        op = Opener()
        result = ue.enqueue_ue_episode_timeline(
            "WaitingOffice", "EP01", studio_getter=truncated,
            opener=op, token_file=self.token
        )
        self.assertEqual(result["reason"], "studio_plan_unavailable")
        self.assertFalse(op.calls)

    def test_job_status_route_requires_random_id(self):
        op = Opener()
        result = ue.get_ue_episode_job_status("a"*32, opener=op,
                                               token_file=self.token)
        self.assertTrue(result["ok"])
        self.assertEqual(op.calls[0].full_url,
                         "http://127.0.0.1:18910/v2/jobs/" + "a"*32)
        result = ue.get_ue_episode_job_status("../../../", opener=op,
                                               token_file=self.token)
        self.assertEqual(result["reason"], "invalid_job_id")
        self.assertEqual(len(op.calls), 1)


if __name__ == "__main__":
    unittest.main()
