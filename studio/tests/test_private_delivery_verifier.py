"""Offline validation for owner-downloaded MP4 and final QC receipt."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_private_delivery as checker


class PrivateDeliveryVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.movie = self.base / "private.mp4"
        self.movie.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 256)
        body = self.movie.read_bytes()
        self.receipt = {
            "schema": "director_studio_private_delivery_receipt_v1",
            "project_id": "WaitingOffice", "episode_id": "EP01",
            "release_id": "REL_" + "a" * 32,
            "mp4_sha256": hashlib.sha256(body).hexdigest(),
            "mp4_bytes": len(body), "duration_seconds": 3.0,
            "source_manifest_sha256": "b" * 64,
            "av_master_id": "MASTER_123", "av_master_sha256": "c" * 64,
            "subtitle_id": "SUB_123", "subtitle_sha256": "d" * 64,
            "subtitle_language": "zh-CN", "reviewer": "owner",
            "reviewed_at": 1790000000, "final_qc_status": "approved",
            "publicly_released": False,
            "external_distribution_authorized": False, "signed_receipt": False,
        }
        self.receipt_path = self.base / "receipt.json"
        self.write_receipt()

    def write_receipt(self):
        canonical = json.dumps(self.receipt, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":")).encode()
        outer = {"ok": True, "receipt": self.receipt,
                 "receipt_sha256": hashlib.sha256(canonical).hexdigest(),
                 "checksum_type": "sha256_canonical_json_not_signature",
                 "gpu_action": False}
        self.receipt_path.write_text(json.dumps(outer), encoding="utf-8")

    def test_valid_files_match_and_never_claim_publication(self):
        result = checker.verify(self.receipt_path, self.movie,
                                project="WaitingOffice", episode="EP01",
                                release="REL_" + "a" * 32)
        self.assertTrue(result["ok"])
        self.assertEqual(result["bytes_verified"], self.movie.stat().st_size)
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["signed_receipt"])
        self.assertEqual(result["gpu_actions"], 0)
        self.assertEqual(result["network_calls"], 0)

    def test_tampered_mp4_rejected_even_with_same_byte_count(self):
        self.movie.write_bytes(self.movie.read_bytes()[:-1] + b"x")
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "mp4_checksum_mismatch"):
            checker.verify(self.receipt_path, self.movie)

    def test_wrong_size_rejected(self):
        self.movie.write_bytes(self.movie.read_bytes() + b"x")
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "mp4_size_mismatch"):
            checker.verify(self.receipt_path, self.movie)

    def test_modified_receipt_checksum_rejected(self):
        document = json.loads(self.receipt_path.read_text())
        document["receipt"]["reviewer"] = "forged"
        self.receipt_path.write_text(json.dumps(document))
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "receipt_checksum_mismatch"):
            checker.verify(self.receipt_path, self.movie)

    def test_missing_or_incorrect_scope_rejected(self):
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "episode_id_mismatch"):
            checker.verify(self.receipt_path, self.movie, episode="EP02")
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "release_id_mismatch"):
            checker.verify(self.receipt_path, self.movie,
                           release="REL_" + "f" * 32)

    def test_modified_approval_status_rejected_after_rehash(self):
        self.receipt["final_qc_status"] = "in_review"
        self.write_receipt()
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "release_not_approved"):
            checker.verify(self.receipt_path, self.movie)

    def test_publication_flag_rejected_after_rehash(self):
        self.receipt["external_distribution_authorized"] = True
        self.write_receipt()
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "unsupported_receipt_permission"):
            checker.verify(self.receipt_path, self.movie)

    def test_missing_human_reviewer_rejected(self):
        self.receipt["reviewer"] = ""
        self.write_receipt()
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "missing_final_reviewer"):
            checker.verify(self.receipt_path, self.movie)

    def test_symlink_movie_and_receipt_rejected(self):
        movie_link = self.base / "alias.mp4"
        movie_link.symlink_to(self.movie)
        with self.assertRaisesRegex(checker.PrivateDeliveryError, "symlink"):
            checker.verify(self.receipt_path, movie_link)
        receipt_link = self.base / "alias.json"
        receipt_link.symlink_to(self.receipt_path)
        with self.assertRaisesRegex(checker.PrivateDeliveryError, "symlink"):
            checker.verify(receipt_link, self.movie)

    def test_ffprobe_optional_validates_media_streams(self):
        def runner(args, **kwargs):
            self.assertEqual(args[0], "ffprobe")
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
                "format": {"format_name": "mov,mp4,m4a", "duration": "3.0"},
                "streams": [{"codec_type": "video", "codec_name": "h264"},
                            {"codec_type": "audio", "codec_name": "aac"},
                            {"codec_type": "subtitle", "codec_name": "mov_text"}]
            }).encode())
        self.assertTrue(checker.verify(self.receipt_path, self.movie,
                         check_streams=True, runner=runner)["streams_verified"])

    def test_ffprobe_rejects_absent_subtitle_track(self):
        def runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
                "format": {"format_name": "mov,mp4", "duration": "3.0"},
                "streams": [{"codec_type": "video", "codec_name": "h264"},
                            {"codec_type": "audio", "codec_name": "aac"}]
            }).encode())
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "mp4_ffprobe_stream_verification_failed"):
            checker.verify(self.receipt_path, self.movie,
                           check_streams=True, runner=runner)

    def test_unsupported_checksum_contract_and_missing_file_fail_closed(self):
        doc = json.loads(self.receipt_path.read_text())
        doc["checksum_type"] = "signature"
        self.receipt_path.write_text(json.dumps(doc))
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "receipt_checksum_contract_mismatch"):
            checker.verify(self.receipt_path, self.movie)
        with self.assertRaisesRegex(checker.PrivateDeliveryError,
                                    "mp4_missing_or_symlink"):
            self.write_receipt()
            checker.verify(self.receipt_path, self.base / "bad.mp4")


if __name__ == "__main__":
    unittest.main()
