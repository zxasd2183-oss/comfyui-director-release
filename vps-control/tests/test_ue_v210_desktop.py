"""Director Desktop: view-only by default, constrained local-arm input."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hub_app
import ue_worker_rpc as rpc


class BridgeTests(unittest.TestCase):
    def test_reject_invalid_pair_codes_before_network(self):
        with patch.object(rpc,"_v2_request") as request:
            for code in ("","123456","Z"*32,"0"*64,"../secret"):
                self.assertEqual(
                    rpc.pair_ue_desktop(code)["reason"],
                    "invalid_desktop_pairing_code")
            request.assert_not_called()

    def test_valid_pair_only_pinned_worker_route(self):
        with patch.object(rpc,"_v2_request",return_value={
            "ok":True,"paired":True,"sharing":True}) as request:
            item=rpc.pair_ue_desktop("a"*32)
        self.assertTrue(item["ok"])
        args=request.call_args.args
        self.assertEqual(args[:3],(
            "/v14/desktop/pair","POST",{"code":"a"*32}))
        self.assertIn("get_ue_desktop_snapshot",dir(hub_app))
        self.assertIn("unpair_ue_desktop",dir(hub_app))
        self.assertNotIn("desktop_click",dir(hub_app))
        self.assertNotIn("desktop_type",dir(hub_app))

    def test_desktop_action_requires_exact_allowlisted_fields(self):
        with patch.object(rpc, "_v2_request", return_value={"ok": True}) as backend:
            for item in (
                {"action": "click", "x": -1, "y": 5, "clicks": 1},
                {"action": "click", "x": True, "y": 5, "clicks": 1},
                {"action": "click", "x": 20, "y": 40, "clicks": 1, "url": "secret"},
                {"action": "text", "text": "echo $env:SECRET"},
                {"action": "text", "text": "some\ncommand"},
                {"action": "key", "key": "CTRL_ALT_DEL"},
                {"action": "shell", "command": "powershell.exe"},
            ):
                self.assertEqual(rpc.send_ue_desktop_action(item)["reason"],
                                 "desktop_action_invalid")
            backend.assert_not_called()
            data = {"action": "click", "x": 500, "y": 240, "clicks": 2}
            self.assertTrue(rpc.send_ue_desktop_action(data)["ok"])
            self.assertEqual(backend.call_args.args[:3],
                             ("/v15/desktop/action", "POST", data))

    def test_hub_tools_only_relay_narrow_actions(self):
        with patch.object(hub_app, "send_ue_desktop_action_rpc",
                          return_value={"ok": False,
                                        "reason": "desktop_control_not_authorized"}) as backend:
            self.assertEqual(hub_app.ue_desktop_click(250, 750)["reason"],
                             "desktop_control_not_authorized")
            self.assertEqual(backend.call_args.args[0], {
                "action": "click", "x": 250, "y": 750, "clicks": 1})
            hub_app.ue_desktop_key("ESC")
            self.assertEqual(backend.call_args.args[0],
                             {"action": "key", "key": "ESC"})
            hub_app.ue_desktop_text("MetaHuman 5.8")
            self.assertEqual(backend.call_args.args[0],
                             {"action": "text", "text": "MetaHuman 5.8"})
        self.assertFalse(hasattr(hub_app, "desktop_shell"))
        self.assertFalse(hasattr(hub_app, "desktop_execute"))

    def test_no_snapshot_transport_without_worker_gate(self):
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"0"}):
            result=rpc.get_ue_desktop_snapshot()
        self.assertEqual(result,{"ok":False,"reason":"ue_worker_not_enabled"})

    def test_snapshot_must_be_sha_verified_jpeg(self):
        jpg=bytes((255,216))+b"x"*256+bytes((255,217))
        digest=hashlib.sha256(jpg).hexdigest()
        class Response:
            def __init__(self,byte_data,sha):
                self.data=byte_data
                self.headers={"Content-Type":"image/jpeg",
                              "Content-Length":str(len(byte_data)),
                              "X-Director-JPEG-SHA256":sha}
            def geturl(self):
                return rpc.WORKER_ORIGIN+"/v14/desktop/frame"
            def read(self,n):
                return self.data[:n]
            def __enter__(self):
                return self
            def __exit__(self,*args):
                return False
        class Opener:
            def __init__(self,data,sha):
                self.data=data
                self.sha=sha
            def open(self,req,timeout):
                self.request=req
                return Response(self.data,self.sha)
        with patch.dict("os.environ",{"DIRECTOR_UE_WORKER_ENABLED":"1"}), \
             patch.object(rpc,"load_token",return_value="a"*64):
            output=rpc.get_ue_desktop_snapshot(opener=Opener(jpg,digest))
            self.assertTrue(output["ok"])
            self.assertEqual(output["data"],jpg)
            tampered=rpc.get_ue_desktop_snapshot(opener=Opener(jpg,"f"*64))
            self.assertFalse(tampered["ok"])
            self.assertEqual(tampered["reason"],"desktop_frame_integrity_failed")
            invalid=rpc.get_ue_desktop_snapshot(opener=Opener(b"notjpeg"*45,
                                                              hashlib.sha256(b"notjpeg"*45).hexdigest()))
            self.assertFalse(invalid["ok"])


if __name__=="__main__":
    unittest.main()
