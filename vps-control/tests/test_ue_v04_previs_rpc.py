"""Confirm Hub V04 preview derives all inputs from Director Studio."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc

DURATIONS=[3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]


class Response:
    def __init__(self,url):
        self.url=url
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def geturl(self):
        return self.url
    def read(self,limit):
        return b'{"ok":true,"state":"queued","job_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'


class Opener:
    def __init__(self):
        self.calls=[]
    def open(self,request,timeout=0):
        self.calls.append(request)
        return Response(request.full_url)


def episode(tool,args):
    return {
        "ok":True,"shot_count":31,"shots_truncated":False,
        "shots":[{"shot_id":f"{i:02}","ordinal":i,
                  "duration_ms":seconds*1000}
                 for i,seconds in enumerate(DURATIONS,1)]
    }


class RouteTest(unittest.TestCase):
    def test_fixed_render_job_uses_studio_and_no_remote_paths(self):
        with tempfile.TemporaryDirectory() as td:
            token=Path(td)/"token"
            token.write_text("a"*64)
            token.chmod(0o600)
            op=Opener()
            with patch.dict(os.environ,{"DIRECTOR_UE_WORKER_ENABLED":"1"}):
                result=rpc.enqueue_ue_previs_stills(
                    "WaitingOffice","EP01",studio_getter=episode,
                    opener=op,token_file=token)
            self.assertTrue(result["ok"])
            self.assertEqual(len(op.calls),1)
            data=json.loads(op.calls[0].data)
            self.assertEqual(data["task"],"render_previs_stills")
            self.assertEqual(data["expected_total_ms"],160000)
            self.assertEqual(len(data["shots"]),31)
            for forbidden in ("command","render_script","output_directory",
                              "preset","map","shot_ids"):
                self.assertNotIn(forbidden,data)
            self.assertIn("source",result)

    def test_rejects_other_episodes_before_network(self):
        op=Opener()
        result=rpc.enqueue_ue_previs_stills("WaitingOffice","EP02",
                                            studio_getter=episode,opener=op)
        self.assertFalse(result["ok"])
        self.assertFalse(op.calls)


if __name__=="__main__":
    unittest.main()
