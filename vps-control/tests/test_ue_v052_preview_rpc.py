"""Private image bridge must not accept paths, expose links, or weaken hashes."""
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ue_worker_rpc as rpc


PNG = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
    + struct.pack(">II",720,1280) + b"\x08\x02\x00\x00\x00"
    + b"x" * 3000
)


class Response:
    def __init__(self, url, png=PNG, mime="image/png", digest=None):
        self.url = url
        self.png = png
        self.headers = {
            "Content-Type": mime,
            "Content-Length": str(len(png)),
            "X-Director-PNG-SHA256": digest or hashlib.sha256(png).hexdigest(),
        }
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, max_bytes):
        return self.png[:max_bytes]


class Opener:
    def __init__(self, **options):
        self.calls = []
        self.options = options
    def open(self, req, timeout=0):
        self.calls.append(req)
        if self.options.get("http_404"):
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", {}, BytesIO(
                    b'{"ok":false,"reason":"preview_job_not_completed"}'
                ),
            )
        return Response(req.full_url, **{
            k: v for k, v in self.options.items() if k != "http_404"
        })


class PreviewRPC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token = Path(self.tmp.name) / "worker.token"
        self.token.write_text("a" * 64)
        self.token.chmod(0o600)
        self.env = patch.dict(os.environ, {"DIRECTOR_UE_WORKER_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_exact_png_and_bearer_through_loopback(self):
        opener = Opener()
        result = rpc.get_ue_preview_png("a"*32, "13", opener, self.token)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], PNG)
        self.assertEqual(result["sha256"], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0].full_url,
                         "http://127.0.0.1:18910/v5/jobs/"+"a"*32+"/previews/13")
        self.assertEqual(opener.calls[0].headers["Authorization"],
                         "Bearer " + "a"*64)

    def test_invalid_inputs_do_not_reach_the_worker(self):
        opener = Opener()
        for job in ("../", "abc", "a"*32+"/../../token", "g"*32):
            self.assertEqual(rpc.get_ue_preview_png(
                job,"01",opener,self.token)["reason"],"invalid_job_id")
        for shot in ("02", "../", "01?x=y", "00", "thumbnail"):
            self.assertEqual(rpc.get_ue_preview_png(
                "a"*32,shot,opener,self.token)["reason"],"invalid_preview_shot")
        self.assertEqual(opener.calls,[])

    def test_reject_corrupt_digest_or_wrong_mime(self):
        for options, reason in (
            ({"digest":"0"*64}, "preview_hash_mismatch"),
            ({"mime":"application/json"}, "preview_mime_mismatch"),
            ({"png":PNG+b"x"}, None),
        ):
            result=rpc.get_ue_preview_png(
                "a"*32,"01",Opener(**options),self.token)
            if reason:
                self.assertEqual(result["reason"],reason)
            else:
                self.assertTrue(result["ok"])
        denied=rpc.get_ue_preview_png(
            "a"*32,"01",Opener(http_404=True),self.token)
        self.assertEqual(denied["reason"],"preview_job_not_completed")


if __name__ == "__main__":
    unittest.main()
