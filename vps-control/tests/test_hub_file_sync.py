"""Offline trusted file parameter and Studio HMAC transfer tests."""
import hashlib
import socket
import urllib.parse
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

    def test_region_varying_openai_blob_host_family(self):
        approved=(
            "oaisdmntprcentralus.blob.core.windows.net",
            "oaisdmntprwestcentralus.blob.core.windows.net",
            "oaisdmntpreastus.blob.core.windows.net",
            "oaisdmntprswedencentral.blob.core.windows.net",
        )
        for host in approved:
            with self.subTest(approved_host=host):
                out,_=fs.validate_file_ref(
                    {**REF,"download_url":"https://"+host+"/object?token=PRIVATE"})
                self.assertIn(host,out)
        for host in (
            "oaisdmntprwestcentralus.blob.core.windows.net.attacker.test",
            "oaisdmntprattacker.blob.core.windows.net.evil.test",
            "someoneelse.blob.core.windows.net",
            "oaisdmntpr"+("z"*15)+".blob.core.windows.net",
        ):
            with self.subTest(blocked_host=host):
                with self.assertRaises(fs.SyncError):
                    fs.validate_file_ref(
                        {**REF,"download_url":"https://"+host+"/file?token=PRIVATE"})

    def test_dns_answers_with_non_global_addresses_rejected(self):
        with patch.object(fs.socket,"getaddrinfo", return_value=[
                (socket.AF_INET,socket.SOCK_STREAM,6,"",("8.8.8.8",443)),
                (socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",443))]):
            with self.assertRaises(fs.SyncError) as caught:
                fs._check_public_resolve("oaisdmntprcentralus.blob.core.windows.net")
        self.assertEqual(caught.exception.reason,"untrusted_chatgpt_file_host")

    def test_tls_connect_uses_validated_ip_and_original_sni(self):
        with patch.object(fs.ssl,"create_default_context") as mkctx, \
             patch.object(fs.socket,"create_connection") as connect:
            host="oaisdmntprwestcentralus.blob.core.windows.net"
            conn=fs._PinnedHTTPSConnection(host,"8.8.8.8")
            conn.connect()
            connect.assert_called_once_with(("8.8.8.8",443),20)
            mkctx.return_value.wrap_socket.assert_called_once_with(
                connect.return_value,server_hostname=host)

    def test_download_http_status_is_classified_without_exposing_url(self):
        class FakeConnection:
            def request(self,*a,**kw):pass
            def getresponse(self):
                return type("Reply",(),{"status":403})()
            def close(self):pass
        host="oaisdmntprwestcentralus.blob.core.windows.net"
        url=urllib.parse.urlsplit("https://"+host+"/image?sig=PRIVATE")
        with patch.object(fs,"_PinnedHTTPSConnection",return_value=FakeConnection()):
            with self.assertRaises(fs.SyncError) as caught:
                fs._fetch_pinned(url,("8.8.8.8",))
        self.assertEqual(caught.exception.reason,"chatgpt_download_http_error")
        self.assertEqual(caught.exception.http_status,403)
        self.assertNotIn("PRIVATE",str(caught.exception))

    def test_filename_metadata_is_bounded_and_basename_only(self):
        self.assertEqual(fs._safe_filename("user/old/path/Qwen.png"),"Qwen.png")
        self.assertEqual(fs._safe_filename(r"C:\tmp\Qwen.png"),"Qwen.png")
        with self.assertRaises(fs.SyncError):
            fs._safe_filename("x"*121)

    def test_numeric_storyboard_ids_reach_signed_transfer_validation(self):
        # Validate scopes without any network calls: an intentionally rejected
        # URL must fail on the host allowlist, not on the numeric shot ID.
        unsafe={**REF,"download_url":"https://example.com/not-allowed"}
        result=fs.sync_chatgpt_visual(
            "WaitingOffice","EP01","storyboard","01",unsafe)
        self.assertEqual(result["reason"],"untrusted_chatgpt_file_host")
        for kind,subject in (("character","01"),("scene","01"),
                             ("storyboard","../01"),("storyboard","镜头01")):
            with self.subTest(kind=kind,subject=subject):
                result=fs.sync_chatgpt_visual(
                    "WaitingOffice","EP01",kind,subject,unsafe)
                self.assertEqual(result["reason"],"invalid_studio_scope")

    def test_no_http_access_with_invalid_project(self):
        result=fs.sync_chatgpt_visual("bad/project","EP01",
                                      "character","CHAR_GEM",REF)
        self.assertEqual(result["reason"],"invalid_studio_scope")

if __name__=="__main__":
    unittest.main()
