"""V0.6 signed updater private bridge contracts; no arbitrary deploy commands."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


class Response:
    def __init__(self,url,blob=b'{"ok":true,"state":"pending_next_signed_poll"}'):
        self.url=url
        self.blob=blob
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def geturl(self):
        return self.url
    def read(self,n):
        return self.blob[:n]


class Capture:
    def __init__(self,fail=False):
        self.calls=[]
        self.fail=fail
    def open(self,request,timeout=0):
        self.calls.append(request)
        if self.fail:
            raise urllib.error.HTTPError(
                request.full_url,404,"Not Found",None,
                io.BytesIO(b'{"ok":false,"reason":"job_not_found"}'),
            )
        return Response(request.full_url)


class UpdateRpcTests(unittest.TestCase):
    def test_fixed_signed_update_routes_no_payload(self):
        with tempfile.TemporaryDirectory() as td:
            token=Path(td)/"worker.token"
            token.write_text("a"*64)
            token.chmod(0o600)
            opener=Capture()
            with patch.dict(os.environ,{"DIRECTOR_UE_WORKER_ENABLED":"1"}):
                read=rpc.get_ue_signed_update_status(opener,token)
                write=rpc.request_ue_signed_update(opener,token)
            self.assertTrue(read["ok"])
            self.assertTrue(write["ok"])
            self.assertEqual(len(opener.calls),2)
            self.assertEqual(opener.calls[0].full_url,
                             "http://127.0.0.1:18910/v4/update/status")
            self.assertEqual(opener.calls[0].get_method(),"GET")
            self.assertEqual(opener.calls[1].full_url,
                             "http://127.0.0.1:18910/v4/update/request")
            self.assertEqual(opener.calls[1].get_method(),"POST")
            self.assertIsNone(opener.calls[0].data)
            self.assertIsNone(opener.calls[1].data)

    def test_worker_404_exposes_real_error_not_network_failure(self):
        with tempfile.TemporaryDirectory() as td:
            token=Path(td)/"worker.token"
            token.write_text("b"*64)
            token.chmod(0o600)
            opener=Capture(fail=True)
            with patch.dict(os.environ,{"DIRECTOR_UE_WORKER_ENABLED":"1"}):
                reply=rpc.get_ue_episode_job_status("a"*32,opener,token)
            self.assertFalse(reply["ok"])
            self.assertEqual(reply["reason"],"job_not_found")
            self.assertEqual(reply["worker_http_status"],404)


if __name__=="__main__":
    unittest.main()
