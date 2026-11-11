"""Offline tests: real Ed25519 Studio archive, exact allowlist and rollback."""
from __future__ import annotations
import io
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_signed_updater as updater
import studio_sign_release as signer


class SignedStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.src=self.root/"source";self.src.mkdir()
        self.code=self.root/"studio";self.code.mkdir()
        self.state=self.root/"state";self.state.mkdir()
        self.original={}
        for filename in updater.FILES:
            payload=(b'STUDIO_CODE_VERSION = "0.10.0"\n' if filename=="studio_server.py"
                     else b'RELEASED = True\n' if filename.endswith(".py")
                     else b'<!doctype html>\n' if filename.endswith(".html")
                     else b'/* stylesheet */\n' if filename.endswith(".css")
                     else b'const ready = true;\n' if filename.endswith(".js")
                     else b'<svg xmlns="http://www.w3.org/2000/svg"/>\n')
            (self.src/filename).write_bytes(payload)
            old=b'RELEASED = False\n' if filename.endswith(".py") else b'legacy\n'
            (self.code/filename).write_bytes(old)
            (self.code/filename).chmod(0o644)
            self.original[filename]=old
        (self.state/"installed-version.txt").write_text("0.9.0")
        key=Ed25519PrivateKey.generate()
        self.private=key.private_bytes_raw().hex()
        self.public=key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        self.out=self.root/"release"
        signer.sign("0.10.0",self.src,self.out,self.private,self.public)
        self.channel=(self.out/"channel.json").read_bytes()
        self.manifest=updater.verify_manifest(self.channel,self.public)
        self.zip=(self.out/"director-studio-v0.10.0.zip").read_bytes()
        self.patches=[
            patch.object(updater,"STUDIO_DIR",self.code),
            patch.object(updater,"STATE",self.state),
            patch.object(updater,"check_studio_health",return_value={
                "projects":1,"episodes":1,"production_shots":31,"assets":0,
            }),
            patch.object(updater,"systemctl",return_value=None),
            patch.object(updater.time,"sleep",return_value=None),
        ]
        for p in self.patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])

    def test_signer_verifies_only_exact_35_installed_files(self):
        self.assertEqual(len(updater.FILES),35)
        self.assertNotIn("studio_signed_updater.py",updater.FILES)
        self.assertNotIn("studio.sqlite",updater.FILES)
        self.assertNotIn("production.sqlite",updater.FILES)
        self.assertNotIn("signed-update-status.json",updater.FILES)
        extracted=updater.files_from_archive(self.zip,self.manifest)
        self.assertEqual(set(extracted),set(updater.FILES))
        self.assertEqual(extracted["studio_server.py"],
                         b'STUDIO_CODE_VERSION = "0.10.0"\n')

    def test_reject_wrong_key_manifest_tampering_and_corrupted_archive(self):
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(self.channel,"0"*64)
        doc=json.loads(self.channel)
        doc["archive_sha256"]="0"*64
        with self.assertRaises(updater.UpdateError):
            updater.verify_manifest(json.dumps(doc).encode(),self.public)
        with self.assertRaises(updater.UpdateError):
            updater.files_from_archive(self.zip+b'x',self.manifest)

    def test_valid_upgrade_preserves_all_originals_as_backup(self):
        result=updater.run_once(channel=lambda:self.channel,
                                download=lambda _:self.zip,public=self.public)
        self.assertEqual(result,{"status":"upgraded","version":"0.10.0"})
        self.assertEqual((self.state/"installed-version.txt").read_text(),"0.10.0")
        self.assertFalse((self.state/"pending.json").exists())
        backups=list(self.state.glob("backup-*"))
        self.assertEqual(len(backups),1)
        for name in updater.FILES:
            self.assertEqual((backups[0]/name).read_bytes(),self.original[name])
            self.assertTrue(stat.S_IMODE((self.code/name).stat().st_mode)&0o004)
        stale=updater.run_once(channel=lambda:self.channel,
            download=lambda _:self.fail("already current must not download"),
            public=self.public)
        self.assertEqual(stale["status"],"already_current")

    def test_health_or_ledger_drift_rolls_back_completely(self):
        prior={name:(self.code/name).read_bytes() for name in updater.FILES}
        baseline={"projects":1,"episodes":1,"production_shots":31,"assets":0}
        changed={**baseline,"production_shots":30}
        with patch.object(updater,"check_studio_health",
                          side_effect=[baseline,changed,baseline]):
            with self.assertRaisesRegex(updater.UpdateError,
                                         "studio_ledger_changed_during_upgrade"):
                updater.apply_update(self.manifest,
                    updater.files_from_archive(self.zip,self.manifest))
        self.assertEqual((self.state/"installed-version.txt").read_text(),"0.9.0")
        self.assertFalse((self.state/"pending.json").exists())
        for name in updater.FILES:
            self.assertEqual((self.code/name).read_bytes(),prior[name])

    def test_symlink_existing_file_is_refused_before_backup(self):
        target=self.code/"studio_brain.py"
        target.unlink()
        target.symlink_to(self.src/"studio_brain.py")
        with self.assertRaisesRegex(updater.UpdateError,"unsafe_existing_studio_file"):
            updater.apply_update(self.manifest,
                                 updater.files_from_archive(self.zip,self.manifest))
        self.assertEqual(list(self.state.glob("backup-*")),[])

    def test_live_studio_version_must_match_signed_release(self):
        # Matches REAL studio /api/v1/production: intentionally no "ok" key.
        data={"version":"0.9.0","mode":"read_only_production_summary",
              "audit_chain_verified":True,
              "studio_code_version":"0.9.0",
              "counts":{"projects":1,"episodes":1,"production_shots":31}}
        class Reply:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def geturl(self):return "http://127.0.0.1:8900/api/v1/production"
            def read(self,max_bytes):return json.dumps(data).encode("utf-8")
        class Opener:
            def open(self,request,timeout=0):
                self_request=request.full_url
                if self_request!="http://127.0.0.1:8900/api/v1/production":
                    raise AssertionError("unexpected health URL")
                return Reply()
        with patch.object(updater.urllib.request,"build_opener",return_value=Opener()):
            with self.assertRaisesRegex(updater.UpdateError,"studio_running_version_mismatch"):
                updater.check_studio("0.10.0")
            data["studio_code_version"]="0.10.0"
            self.assertEqual(updater.check_studio("0.10.0")["production_shots"],31)
            data["audit_chain_verified"]=False
            with self.assertRaisesRegex(updater.UpdateError,"studio_audit_or_health_invalid"):
                updater.check_studio("0.10.0")
            data["audit_chain_verified"]=True
            data["mode"]="microsoft_owner_api"
            with self.assertRaisesRegex(updater.UpdateError,"studio_audit_or_health_invalid"):
                updater.check_studio("0.10.0")

    def test_missing_or_unsafe_pinned_source_fails_build(self):
        (self.src/"studio_brain.py").unlink()
        with self.assertRaises(updater.UpdateError):
            signer.sign("0.10.0",self.src,self.root/"other",self.private,self.public)
        (self.src/"studio_brain.py").symlink_to(self.code/"studio_brain.py")
        with self.assertRaises(updater.UpdateError):
            signer.sign("0.10.0",self.src,self.root/"other",self.private,self.public)


if __name__=="__main__":
    unittest.main()
