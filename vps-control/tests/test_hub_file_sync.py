"""Offline trusted file parameter and Studio HMAC transfer tests."""
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

VPS=Path(__file__).resolve().parents[1]
STUDIO=VPS.parent/"studio"
sys.path.insert(0,str(VPS))
sys.path.insert(0,str(STUDIO))
import hub_file_sync as fs
from studio_brain import signature

PNG=bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")
REF={"file_id":"file_00000abcde123456",
     "download_url":"https://files.oaiusercontent.com/secure/sample?signature=xyz",
     "mime_type":"image/png","file_name":"Gemini.png"}


class TestHubFileTransfer(unittest.TestCase):
    def test_signed_bytes_match_studio_verifier(self):
        body=b'{"project_id":"WaitingOffice"}'
        secret=b"x"*32;stamp="1793884508";nonce="a"*32
        self.assertEqual(fs.signed_request(secret,body,stamp,nonce),
            signature(secret,"POST",fs.MEDIA_PATH,stamp,nonce,body))

    def test_deny_ssrf_and_arbitrary_file_url(self):
        for url in ("http://files.oaiusercontent.com/x",
                    "https://127.0.0.1/a",
                    "https://files.oaiusercontent.com.evil.test/secret",
                    "https://localhost/a",
                    "https://user:pass@files.oaiusercontent.com/a",
                    "https://files.oaiusercontent.com:8443/a",
                    "https://example.com/a"):
            with self.subTest(url=url):
                with self.assertRaises(fs.SyncError):
                    fs.validate_file_ref({**REF,"download_url":url})

    def test_file_reference_and_bytes(self):
        class Reply:
            status=200
            def geturl(self): return REF["download_url"]
            def read(self,n): return PNG[:n]
            def __enter__(self):return self
            def __exit__(self,*args):pass
        class Opener:
            def open(self,req,timeout):return Reply()
        with patch.object(fs,"_check_public_resolve"):
            raw,fileid=fs.fetch_file(REF,opener=Opener())
        self.assertEqual(raw,PNG)
        self.assertEqual(fileid,"file_"+hashlib.sha256(REF["file_id"].encode()).hexdigest())

    def test_direct_file_url_is_never_returned_in_error(self):
        invalid={**REF,"download_url":"https://example.com/sensitive?key=SECRETTOKEN"}
        result=fs.sync_chatgpt_visual("WaitingOffice","EP01",
                                      "character","CHAR_GEM",invalid)
        self.assertFalse(result["ok"])
        self.assertNotIn("SECRETTOKEN",str(result))

    def test_opaque_file_reference_is_supported_without_leaking_raw_id(self):
        imported={**REF,"file_id":"opaque-runtime-file-v4-+&id=9"}
        url,source=fs.validate_file_ref(imported)
        self.assertEqual(url,REF["download_url"])
        self.assertTrue(source.startswith("file_"))
        self.assertEqual(len(source),69)
        self.assertNotIn(imported["file_id"],source)
        self.assertEqual(source,fs.validate_file_ref(imported)[1])

    def test_chatgpt_hostname_allowed_with_https_only(self):
        for host in ("chatgpt.com","files.chatgpt.com",
                     "files.openaiusercontent.com","openai.com",
                     "files.oaiusercontent.com",
                     "oaisdmntprcentralus.blob.core.windows.net"):
            with self.subTest(host=host):
                out,_=fs.validate_file_ref(
                    {**REF,"download_url":"https://"+host+"/secure/file?token=SECRET"})
                self.assertEqual(out.split("/")[2],host)
        for host in ("chatgpt.com.evil.test","evilopenaiusercontent.com",
                     "openai.com.attacker.net",
                     "oaisdmntprcentralus.blob.core.windows.net.attacker.test",
                     "someoneelse.blob.core.windows.net"):
            with self.subTest(host=host):
                result=fs.sync_chatgpt_visual("WaitingOffice","EP01",
                    "character","CHAR_GEM",
                    {**REF,"download_url":"https://"+host+"/f?token=SECRET"})
                self.assertEqual(result["reason"],"untrusted_chatgpt_file_host")
                self.assertEqual(result.get("download_host"),host)
                self.assertNotIn("SECRET",str(result))

    def test_no_http_access_with_invalid_project(self):
        result=fs.sync_chatgpt_visual("bad/project","EP01",
                                      "character","CHAR_GEM",REF)
        self.assertEqual(result["reason"],"invalid_studio_scope")

if __name__=="__main__":
    unittest.main()
