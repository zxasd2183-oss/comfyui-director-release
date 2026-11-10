"""V03 Hub command is limited to the registered Studio EP01 source."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


class HttpResponse:
    def __init__(self,url):
        self.url=url
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def geturl(self):
        return self.url
    def read(self,size):
        return b'{"ok":true,"job_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"queued"}'


class Capture:
    def __init__(self):
        self.requests=[]
    def open(self,request,timeout=10):
        self.requests.append(request)
        return HttpResponse(request.full_url)


def episode(tool,args):
    durations=[3,5,5,6,6,5,5,6,5,6,5,5,4,5,5,5,7,5,5,5,6,5,6,5,4,5,5,6,5,5,5]
    return {"ok":True,"shot_count":31,"shots_truncated":False,
            "shots":[{"shot_id":f"{i:02}","ordinal":i,"duration_ms":d*1000}
                     for i,d in enumerate(durations,1)]}


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.secret=Path(self.temp.name)/"token"
        self.secret.write_text("a"*64)
        self.secret.chmod(0o600)
        self.environment=patch.dict(os.environ,{"DIRECTOR_UE_WORKER_ENABLED":"1"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_source_is_registered_shots_not_caller_input(self):
        opener=Capture()
        result=rpc.enqueue_ue_stage_cameras(
            "WaitingOffice","EP01",studio_getter=episode,
            opener=opener,token_file=self.secret)
        self.assertTrue(result["ok"])
        self.assertEqual(len(opener.requests),1)
        spec=json.loads(opener.requests[0].data)
        self.assertEqual(spec["task"],"build_stage_cameras")
        self.assertEqual(spec["expected_total_ms"],160000)
        self.assertEqual(spec["shots"][-1]["shot_id"],"31")
        self.assertNotIn("code",spec)
        self.assertEqual(result["source"],"Director Studio registered shots")

    def test_rejects_unapproved_episode(self):
        opener=Capture()
        result=rpc.enqueue_ue_stage_cameras(
            "WaitingOffice","EP02",studio_getter=episode,
            opener=opener,token_file=self.secret)
        self.assertEqual(result["reason"],"v03_stage_requires_locked_ep01")
        self.assertEqual(opener.requests,[])


if __name__=="__main__":
    unittest.main()
