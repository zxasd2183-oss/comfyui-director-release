"""Dry-run sign the ACTUAL integrated release source without real secrets or GPU."""
import sys
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"ue-worker"))
sys.path.insert(0, str(ROOT/"vps-control"))
import ue_signed_updater as worker_updater
import ue_sign_release as worker_signer
import ue_hub_signed_updater as hub_updater
import ue_hub_sign_release as hub_signer

class ActualReleaseSmoke(unittest.TestCase):
    def test_real_worker_and_hub_sign_and_validate(self):
        private = Ed25519PrivateKey.generate()
        prv = private.private_bytes_raw().hex()
        pub = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            w=folder/"worker"
            h=folder/"hub"
            worker_signer.build_release("0.7.2", ROOT/"ue-worker", w, prv, pub)
            hub_signer.sign("0.7.1", ROOT/"vps-control", h, prv, pub)
            wdoc=worker_updater.verify_manifest(
                (w/"channel.json").read_bytes(),pub)
            hdoc=hub_updater.verify_manifest(
                (h/"channel.json").read_bytes(),pub)
            self.assertEqual(set(worker_updater.verified_files(
                (w/"ue-worker-v0.7.2.zip").read_bytes(),wdoc)),
                set(worker_updater.FILES))
            self.assertEqual(set(hub_updater.files_from_archive(
                (h/"ue-hub-v0.7.1.zip").read_bytes(),hdoc)),
                set(hub_updater.FILES))
            self.assertEqual(len(worker_updater.FILES),9)
            self.assertEqual(len(hub_updater.FILES),2)
            with self.assertRaises(hub_updater.UpdateError):
                hub_updater.verify_manifest((w/"channel.json").read_bytes(),pub)
            with self.assertRaises(worker_updater.UpdateError):
                worker_updater.verify_manifest((h/"channel.json").read_bytes(),pub)

if __name__=="__main__":
    unittest.main()
