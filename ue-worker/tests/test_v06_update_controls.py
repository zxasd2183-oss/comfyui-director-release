"""Authenticated MCP -> private Worker signed update requests, no shell or version input."""
from __future__ import annotations

import json
import os
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
import ue_signed_updater as updater


class SignedControlProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{"DIRECTOR_UE_WORKSPACE":self.tmp.name})
        self.env.start()
        self.server=agent.ThreadingHTTPServer(("127.0.0.1",0),agent.Handler)
        self.server.token="a"*64
        self.url="http://127.0.0.1:"+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.env.stop()
        self.tmp.cleanup()

    def api(self,path,method="GET",body=None,auth=True):
        headers={"Authorization":"Bearer "+"a"*64} if auth else {}
        data=json.dumps(body).encode() if body is not None else None
        request=urllib.request.Request(
            self.url+path,method=method,data=data,headers=headers
        )
        try:
            with urllib.request.urlopen(request,timeout=3) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as err:
            return err.code,json.loads(err.read())

    def test_requires_signed_updater_and_token(self):
        code,doc=self.api("/v4/update/request",method="POST")
        self.assertEqual(code,409)
        self.assertEqual(doc["reason"],"signed_updater_not_ready")
        self.assertFalse((self.root/"JobStatus").exists())
        code,_=self.api("/v4/update/request",method="POST",auth=False)
        self.assertEqual(code,401)
        code,doc=self.api("/v4/update/status")
        self.assertEqual(code,200)
        self.assertEqual(doc["signed_update"]["status"],"not_configured")

    def test_request_only_no_body_idempotent_and_consumable(self):
        with patch.object(agent,"signed_update_status",return_value={
            "status":"no_signed_channel","checked_at":"2026-11-11T00:00:00Z"
        }):
            self.assertEqual(self.api(
                "/v4/update/request",method="POST",body={"command":"powershell"}
            )[0],400)
            self.assertFalse((self.root/"JobStatus").exists())
            code,first=self.api("/v4/update/request",method="POST")
            self.assertEqual(code,202)
            self.assertTrue(first["ok"])
            self.assertEqual(first["state"],"pending_next_signed_poll")
            self.assertEqual(len(first["request_id"]),32)
            code,second=self.api("/v4/update/request",method="POST")
            self.assertEqual(code,202)
            self.assertEqual(second["request_id"],first["request_id"])
            self.assertTrue(second["duplicate"])
            code,status=self.api("/v4/update/status")
            self.assertEqual(code,200)
            self.assertEqual(status["pending_request"]["request_id"],first["request_id"])
            self.assertEqual(status["poll_interval_seconds"],300)
        with patch.object(updater,"REQUEST_DIR",self.root/"JobStatus"):
            receipt=updater.read_signed_update_request()
            self.assertEqual(receipt["request_id"],first["request_id"])
            updater.finish_signed_update_request(receipt)
            self.assertIsNone(updater.read_signed_update_request())
        self.assertEqual(self.api("/v4/update/status")[1]["pending_request"],None)

    def test_corrupt_request_fails_closed_without_exposing_or_running_commands(self):
        folder=self.root/"JobStatus"
        folder.mkdir()
        file=folder/agent.UPDATE_REQUEST_NAME
        file.write_text('{"request_id":"../../x","requested_at":"now","cmd":"powershell"}')
        with patch.object(agent,"signed_update_status",return_value={"status":"already_current"}):
            code,doc=self.api("/v4/update/request",method="POST")
            self.assertEqual(code,409)
            self.assertEqual(doc["reason"],"update_request_unavailable")
            code,doc=self.api("/v4/update/status")
            self.assertEqual(code,200)
            self.assertFalse(doc["ok"])
        with patch.object(updater,"REQUEST_DIR",folder):
            with self.assertRaises(updater.UpdateError):
                updater.read_signed_update_request()
        self.assertIn("powershell",file.read_text())


if __name__=="__main__":
    unittest.main()
