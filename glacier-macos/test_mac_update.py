"""No keys are committed: tests use temporary Ed25519 identities at runtime."""
import base64
import copy
import hashlib
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import mac_update_core as u


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=Ed25519PrivateKey.generate()
        cls.pub=cls.key.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw,
        )

    def signed(self, version="0.14.1"):
        payload={
            "channel":"macos-arm64",
            "version":version,
            "url":f"https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/glacier-macos-v{version}/GlacierBrowser-v{version}-macOS-AppleSilicon.dmg",
            "sha256":hashlib.sha256(b"test").hexdigest(),
            "size":2_000_000,
            "notes":"Mac build test",
            "key_id":u.KEY_ID,
        }
        payload["signature"]=base64.b64encode(
            self.key.sign(u.canonical(payload))
        ).decode("ascii")
        return payload

    def check(self,payload):
        with patch.object(u,"PUBLIC_KEY",self.pub):
            return u.verify_manifest(payload)

    def test_valid_signature(self):
        self.assertEqual(self.check(self.signed())["channel"],"macos-arm64")

    def test_vps_signed_installer_origin_accepted(self):
        m=self.signed("0.20.10")
        m["url"]="https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.10-macOS-AppleSilicon.dmg"
        m["signature"]=base64.b64encode(self.key.sign(u.canonical(
            {k:v for k,v in m.items() if k!="signature"}))).decode("ascii")
        self.assertEqual(self.check(m)["version"],"0.20.10")

    def test_vps_signed_wrong_path_rejected(self):
        m=self.signed("0.20.10")
        m["url"]="https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.11-macOS-AppleSilicon.dmg"
        m["signature"]=base64.b64encode(self.key.sign(u.canonical(
            {k:v for k,v in m.items() if k!="signature"}))).decode("ascii")
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_modified_hash(self):
        m=self.signed()
        m["sha256"]="0"*64
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_modified_url(self):
        m=self.signed()
        m["url"]=m["url"].replace("github.com","evil.example")
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_wrong_channel(self):
        m=self.signed()
        m["channel"]="windows-x64"
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_unknown_key(self):
        m=self.signed()
        m["key_id"]="attacker"
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_unsigned(self):
        m=self.signed()
        m.pop("signature")
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_wrong_platform_filename_even_if_signed(self):
        m=self.signed()
        m["url"]=m["url"].replace("macOS-AppleSilicon.dmg","Windows-Setup-x64.exe")
        m.pop("signature")
        m["signature"]=base64.b64encode(self.key.sign(u.canonical(m))).decode()
        with self.assertRaises(u.UpdateError):self.check(m)

    def test_version_order(self):
        self.assertTrue(u.newer_than("0.14.0","0.14.1"))
        self.assertFalse(u.newer_than("0.14.1","0.14.0"))
        with self.assertRaises(u.UpdateError):u.newer_than("0.14.0","0.14.0-rc1")

    def test_duplicate_json(self):
        with self.assertRaises(u.UpdateError):
            __import__("json").loads('{"a":1,"a":2}',object_pairs_hook=u.unique_json_pairs)

    def test_disallowed_redirect(self):
        class Session:
            def get(self,*args,**kw):
                class R:
                    status_code=302
                    headers={"Location":"https://evil.example/bad.dmg"}
                    def close(self):pass
                return R()
        with self.assertRaises(u.UpdateError):
            u._request(Session(),"https://github.com/allowed",u.TRUSTED_REDIRECT_HOSTS)

    def test_vless_update_proxy_and_dns_fail_closed(self):
        session=u.signed_update_session(18080)
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies["https"],"socks5h://127.0.0.1:18080")
        self.assertEqual(session.proxies["http"],"socks5h://127.0.0.1:18080")
        self.assertTrue(u.FEED_URL.startswith("https://raw.githubusercontent.com/"))
        session.close()
        for port in (0, -1, 65536, None):
            with self.assertRaises(u.UpdateError):u.signed_update_session(port)

if __name__=="__main__":
    unittest.main()
