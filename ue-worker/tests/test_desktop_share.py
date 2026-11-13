"""RDP desktop sharing: bearer-authenticated, human-armed, read-only protocol."""
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import agent


class DesktopBridgeTests(unittest.TestCase):
    def tearDown(self):
        agent.unpair_desktop()

    def test_unpaired_cannot_capture_even_if_companion_would_answer(self):
        agent.unpair_desktop()
        with patch.object(agent,"_desktop_http") as remote:
            with self.assertRaisesRegex(ValueError,"desktop_not_paired"):
                agent.desktop_frame()
            remote.assert_not_called()

    def test_pair_requires_real_live_consent(self):
        code="a"*32
        with patch.object(agent,"_desktop_http",return_value=(
                "application/json",b'{"ok":true,"sharing":false}')):
            self.assertFalse(agent.pair_desktop(code)["ok"])
        self.assertFalse(agent.desktop_status()["paired"])
        with patch.object(agent,"_desktop_http",return_value=(
                "application/json",b'{"ok":true,"sharing":true}')):
            self.assertTrue(agent.pair_desktop(code)["ok"])
        self.assertIsNotNone(agent._desktop_pair_code())
        self.assertFalse(agent.desktop_status()["control_enabled"])

    def test_expiring_consent_blocks_screens(self):
        code="b"*32
        with patch.object(agent,"_desktop_http",return_value=(
                "application/json",b'{"ok":true,"sharing":true}')):
            agent.pair_desktop(code)
        with agent.DESKTOP_LOCK:
            agent.DESKTOP_PIN_EXPIRES=time.monotonic()-1
        with patch.object(agent,"_desktop_http") as remote:
            with self.assertRaisesRegex(ValueError,"desktop_not_paired"):
                agent.desktop_frame()
            remote.assert_not_called()

    def test_snapshot_needs_valid_jpeg_bytes_and_no_control_methods(self):
        code="c"*32
        jpg=bytes((255,216))+b"f"*256+bytes((255,217))
        with patch.object(agent,"_desktop_http",return_value=(
                "application/json",b'{"ok":true,"sharing":true}')):
            agent.pair_desktop(code)
        with patch.object(agent,"_desktop_http",return_value=("image/jpeg",jpg)):
            data,digest=agent.desktop_frame()
        self.assertEqual(data,jpg)
        self.assertEqual(len(digest),64)
        with patch.object(agent,"_desktop_http",return_value=(
                "image/jpeg",b"not a screenshot"*50)):
            with self.assertRaisesRegex(ValueError,"desktop_frame_unavailable"):
                agent.desktop_frame()
        self.assertFalse(agent.capabilities()["supports_desktop_keyboard_or_mouse"])
        self.assertTrue(agent.capabilities()["supports_desktop_view_only"])

    def test_worker_http_requires_bearer_and_valid_one_time_code(self):
        server=agent.ThreadingHTTPServer(("127.0.0.1",0),agent.Handler)
        server.token="d"*64
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            uri=f"http://127.0.0.1:{server.server_port}/v14/desktop/pair"
            def call(headers,body):
                request=urllib.request.Request(uri,method="POST",
                    headers=headers,data=json.dumps(body).encode("utf-8"))
                try:
                    with urllib.request.urlopen(request,timeout=3) as answer:
                        return answer.status,json.load(answer)
                except urllib.error.HTTPError as err:
                    return err.code,json.loads(err.read())
            result,data=call({},{"code":"a"*32})
            self.assertEqual(result,401)
            self.assertEqual(data["reason"],"unauthorized")
            result,data=call({"Authorization":"Bearer "+"d"*64},
                             {"code":"NOT_A_PAIR_CODE"})
            self.assertEqual(result,409)
            self.assertEqual(data["reason"],"desktop_pair_code_invalid")
            with patch.object(agent,"_desktop_http",return_value=(
                "application/json",b'{"ok":true,"sharing":true}')):
                result,data=call({"Authorization":"Bearer "+"d"*64},
                                 {"code":"a"*32})
            self.assertEqual(result,200)
            self.assertTrue(data["paired"])
            self.assertNotIn("code",data)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__=="__main__":
    unittest.main()
