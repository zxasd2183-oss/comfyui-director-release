"""Glacier Windows updater security regressions, with ephemeral test keys only."""
import base64
import copy
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import secure_update as update


class GlacierUpdateSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = Ed25519PrivateKey.generate()
        cls.pub = cls.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )

    def fixture(self, version="0.18.0"):
        payload = {
            "channel": "windows-x64", "version": version,
            "url": f"https://github.com/zxasd2183-oss/comfyui-director-release/releases/download/glacier-v{version}/GlacierBrowser-v{version}-Windows-Setup-x64.exe",
            "sha256": "0" * 64, "size": 173_205_726,
            "notes": "signed updater test vector",
            "key_id": update.KEY_ID,
        }
        payload["signature"] = base64.b64encode(
            self.key.sign(update.canonical(payload))).decode("ascii")
        return payload

    def parse(self, document):
        with patch.object(update, "PUBLIC_KEY", self.pub):
            return update.parse_manifest(document)

    def test_windows_signed_channel_fetched_directly_from_owner_vps(self):
        doc=self.fixture("0.20.10")
        doc["url"]="https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.10-Windows-Setup-x64.exe"
        doc["signature"]=base64.b64encode(self.key.sign(
            update.canonical({k:v for k,v in doc.items() if k!="signature"})
        )).decode("ascii")
        payload=json.dumps(doc).encode("utf-8")
        response=MagicMock()
        response.status_code=200
        response.headers={"Content-Length":str(len(payload))}
        response.iter_content.return_value=[payload]
        response.__enter__.return_value=response
        session=MagicMock()
        session.get.return_value=response
        with patch.object(update.requests,"Session",return_value=session), patch.object(update,"PUBLIC_KEY",self.pub):
            result=update.load_remote_manifest(0)
        self.assertEqual(result.version,"0.20.10")
        self.assertFalse(session.trust_env)
        args,kwargs=session.get.call_args
        self.assertEqual(args[0],"https://sync.borealos.cn/downloads/windows-x64.json")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        session.close.assert_called_once()

    def test_windows_signed_channel_rejects_redirect_without_fallback(self):
        response=MagicMock()
        response.status_code=302
        response.headers={"Location":"https://evil.example/unsigned.json"}
        response.__enter__.return_value=response
        session=MagicMock()
        session.get.return_value=response
        with patch.object(update.requests,"Session",return_value=session):
            with self.assertRaises(update.UpdateError):
                update.load_remote_manifest(0)
        session.close.assert_called_once()

    def _vps_fixture(self,data=b"V"*1_100_000):
        return SimpleNamespace(
            version="0.20.12",
            url="https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.12-Windows-Setup-x64.exe",
            sha256=hashlib.sha256(data).hexdigest(),size=len(data),
        )

    def test_vps_signed_installer_download_over_direct_https(self):
        data=b"V"*1_100_000
        manifest=self._vps_fixture(data)
        response=MagicMock()
        response.status_code=200
        response.headers={"Content-Length":str(len(data))}
        response.iter_content.return_value=[data[:400_000],data[400_000:]]
        response.__enter__.return_value=response
        session=MagicMock()
        session.get.return_value=response
        progress=[]
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(update.requests,"Session",return_value=session), patch.object(
                    update,"_legacy_download_installer",
                    side_effect=AssertionError("VPS must not fall back to GitHub redirect validator")):
                downloaded=update.download_installer(0,temp,manifest,lambda n,total:progress.append((n,total)))
            self.assertEqual(downloaded.read_bytes(),data)
            self.assertEqual(progress[-1],(len(data),len(data)))
            self.assertFalse((Path(temp)/"GlacierBrowser-v0.20.12-Windows-Setup-x64.exe.part").exists())
        self.assertFalse(session.trust_env)
        args,kwargs=session.get.call_args
        self.assertEqual(args[0],manifest.url)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        session.close.assert_called_once()

    def test_vps_signed_download_rejects_redirect_without_fallback(self):
        manifest=self._vps_fixture()
        response=MagicMock()
        response.status_code=302
        response.__enter__.return_value=response
        session=MagicMock()
        session.get.return_value=response
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(update.requests,"Session",return_value=session), patch.object(
                    update,"_legacy_download_installer",side_effect=AssertionError("legacy")):
                with self.assertRaisesRegex(update.UpdateError,"HTTP 302"):
                    update.download_installer(0,temp,manifest)
            self.assertFalse(list(Path(temp).glob("*.part")))

    def test_vps_signed_download_rejects_tampered_installer(self):
        data=b"V"*1_100_000
        manifest=self._vps_fixture(data)
        response=MagicMock()
        response.status_code=200
        response.headers={"Content-Length":str(len(data))}
        response.iter_content.return_value=[b"A"*len(data)]
        response.__enter__.return_value=response
        session=MagicMock()
        session.get.return_value=response
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(update.requests,"Session",return_value=session):
                with self.assertRaisesRegex(update.UpdateError,"SHA256"):
                    update.download_installer(0,temp,manifest)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_vps_signed_download_rejects_path_mismatch(self):
        manifest=self._vps_fixture()
        manifest.url="https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.13-Windows-Setup-x64.exe"
        with patch.object(update.requests,"Session",side_effect=AssertionError("network not allowed")):
            with self.assertRaisesRegex(update.UpdateError,"不可信"):
                update.download_installer(0,"unused",manifest)

    def test_vps_signed_download_rejects_unexpected_length(self):
        manifest=self._vps_fixture()
        response=MagicMock()
        response.status_code=200
        response.headers={"Content-Length":str(manifest.size+1)}
        response.__enter__.return_value=response
        session=MagicMock()
        session.get.return_value=response
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(update.requests,"Session",return_value=session):
                with self.assertRaisesRegex(update.UpdateError,"大小"):
                    update.download_installer(0,temp,manifest)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_signed_manifest_accepted(self):
        self.assertEqual(self.parse(self.fixture()).version, "0.18.0")

    def test_signed_vps_installer_origin_accepted(self):
        doc = self.fixture("0.20.10")
        doc["url"] = "https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.10-Windows-Setup-x64.exe"
        doc["signature"] = base64.b64encode(self.key.sign(
            update.canonical({k: v for k, v in doc.items() if k != "signature"})
        )).decode("ascii")
        self.assertEqual(self.parse(doc).version, "0.20.10")

    def test_signed_vps_wrong_filename_and_nonstandard_port_rejected(self):
        for url in (
            "https://sync.borealos.cn/downloads/GlacierBrowser-v0.20.11-Windows-Setup-x64.exe",
            "https://sync.borealos.cn:443/downloads/GlacierBrowser-v0.20.10-Windows-Setup-x64.exe",
            "https://evil.example/downloads/GlacierBrowser-v0.20.10-Windows-Setup-x64.exe",
        ):
            doc = self.fixture("0.20.10")
            doc["url"] = url
            doc["signature"] = base64.b64encode(self.key.sign(
                update.canonical({k: v for k, v in doc.items() if k != "signature"})
            )).decode("ascii")
            with self.assertRaises(update.UpdateError):
                self.parse(doc)

    def test_checksum_tamper_rejected(self):
        doc = self.fixture()
        doc["sha256"] = "1" * 64
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_version_tamper_rejected(self):
        doc = self.fixture()
        doc["version"] = "0.18.1"
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_unsigned_manifest_rejected(self):
        doc = self.fixture()
        doc.pop("signature")
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_different_key_rejected(self):
        doc = self.fixture()
        doc["key_id"] = "foreign"
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_signed_rollback_is_not_newer(self):
        self.assertFalse(update.newer_than(update.CURRENT_VERSION, "0.17.0"))
        self.assertTrue(update.newer_than("0.17.0", update.CURRENT_VERSION))

    def test_url_redirect_replacement_rejected(self):
        doc = self.fixture()
        doc["url"] = "https://evil.example/setup.exe"
        with self.assertRaises(update.UpdateError):
            self.parse(doc)

    def test_same_key_replay_cross_platform_rejected(self):
        doc = self.fixture()
        doc["channel"] = "macos-arm64"
        doc.pop("signature")
        doc["signature"] = base64.b64encode(
            self.key.sign(update.canonical(doc))).decode("ascii")
        with self.assertRaises(update.UpdateError):
            self.parse(doc)


if __name__ == "__main__":
    unittest.main()
