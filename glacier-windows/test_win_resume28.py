"""Offline regressions for Windows signed VPS Range downloads.

These tests never fetch network resources or execute installers.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
import glacier_win_resume28 as u


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.data = b"R" * 1_200_000
        self.manifest = SimpleNamespace(
            version="0.20.18",
            url="https://sync.borealos.cn/downloads/"
                "GlacierBrowser-v0.20.18-Windows-Setup-x64.exe",
            sha256=hashlib.sha256(self.data).hexdigest(),
            size=len(self.data),
        )
        self.path = self.root / "GlacierBrowser-v0.20.18-Windows-Setup-x64.exe"
        self.part = self.root / (self.path.name + ".part")

    def response(self, status=200, chunks=None, headers=None):
        r = MagicMock()
        r.status_code = status
        r.headers = headers or {}
        r.iter_content.return_value = iter(chunks if chunks is not None else [self.data])
        r.__enter__.return_value = r
        return r

    def factory(self, responses):
        session = MagicMock()
        session.get.side_effect = responses
        return session

    def verify_cached(self, path, manifest):
        return (path.stat().st_size == manifest.size
                and hashlib.sha256(path.read_bytes()).hexdigest() == manifest.sha256)

    def test_206_resume_from_interrupted_download(self):
        def cut():
            yield self.data[:300_000]
            raise requests.ConnectionError("network dropped")
        first = self.response(chunks=[])
        first.iter_content.return_value = cut()
        tail = self.data[300_000:]
        second = self.response(
            status=206, chunks=[tail[:600_000], tail[600_000:]],
            headers={
                "Content-Range": "bytes 300000-1199999/1200000",
                "Content-Length": str(len(tail)),
            },
        )
        session = self.factory([first, second])
        updates = []
        with patch.object(u.requests, "Session", return_value=session):
            with self.assertRaisesRegex(u.DownloadError, "保留下载进度"):
                u.download_signed_vps(self.manifest, self.root)
            self.assertEqual(self.part.stat().st_size, 300_000)
            self.assertFalse(self.path.exists())
            result = u.download_signed_vps(
                self.manifest, self.root,
                progress=lambda n, total: updates.append((n, total)))
        self.assertEqual(result.read_bytes(), self.data)
        self.assertFalse(self.part.exists())
        self.assertEqual(updates[0], (300_000, len(self.data)))
        self.assertEqual(updates[-1], (len(self.data), len(self.data)))
        self.assertEqual(session.get.call_args.kwargs["headers"]["Range"], "bytes=300000-")
        self.assertFalse(session.trust_env)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_200_range_ignored_restarts_safely(self):
        self.part.write_bytes(b"X" * 250_000)
        response = self.response(
            status=200,
            headers={"Content-Length": str(self.manifest.size)},
        )
        session = self.factory([response])
        with patch.object(u.requests, "Session", return_value=session):
            result = u.download_signed_vps(self.manifest, self.root)
        self.assertEqual(result.read_bytes(), self.data)
        self.assertFalse(self.part.exists())
        self.assertEqual(session.get.call_args.kwargs["headers"]["Range"], "bytes=250000-")

    def test_invalid_range_never_publishes_or_preserves_invalid_part(self):
        self.part.write_bytes(self.data[:300_000])
        for content_range in (
            "bytes 0-899999/1200000",
            "bytes 300001-1199999/1200000",
            "bytes 300000-1199999/1200001",
            "",
        ):
            self.part.write_bytes(self.data[:300_000])
            response = self.response(status=206, chunks=[self.data[300_000:]],
                                     headers={"Content-Range": content_range})
            with patch.object(u.requests, "Session", return_value=self.factory([response])):
                with self.assertRaisesRegex(u.DownloadError, "范围"):
                    u.download_signed_vps(self.manifest, self.root)
            self.assertFalse(self.part.exists())
            self.assertFalse(self.path.exists())

    def test_complete_partial_only_promoted_if_sha256_valid(self):
        self.part.write_bytes(self.data)
        with patch.object(u.requests, "Session", side_effect=AssertionError("no network")):
            result = u.download_signed_vps(self.manifest, self.root)
        self.assertEqual(result.read_bytes(), self.data)
        self.assertFalse(self.part.exists())

    def test_tampered_partial_final_hash_blocks_exe(self):
        self.part.write_bytes(b"X" * 200_000)
        response = self.response(
            status=206, chunks=[self.data[200_000:]],
            headers={"Content-Range": "bytes 200000-1199999/1200000"},
        )
        with patch.object(u.requests, "Session", return_value=self.factory([response])):
            with self.assertRaisesRegex(u.DownloadError, "SHA256"):
                u.download_signed_vps(self.manifest, self.root)
        self.assertFalse(self.part.exists())
        self.assertFalse(self.path.exists())

    def test_wrong_origin_and_unsupported_encoding_refused(self):
        bad = SimpleNamespace(**vars(self.manifest))
        bad.url = "https://evil.example/downloads/" + self.path.name
        with patch.object(u.requests, "Session", side_effect=AssertionError("no network")):
            with self.assertRaisesRegex(u.DownloadError, "可信"):
                u.download_signed_vps(bad, self.root)
        response = self.response(headers={"Content-Encoding": "gzip"})
        with patch.object(u.requests, "Session", return_value=self.factory([response])):
            with self.assertRaisesRegex(u.DownloadError, "压缩"):
                u.download_signed_vps(self.manifest, self.root)
        self.assertFalse(self.path.exists())

    def test_cached_verified_file_requires_no_network(self):
        self.path.write_bytes(self.data)
        with patch.object(u.requests, "Session", side_effect=AssertionError("no network")):
            result = u.download_signed_vps(
                self.manifest, self.root, verify_cached=self.verify_cached)
        self.assertEqual(result, self.path)

    def test_bad_content_length_and_sha_delete_part(self):
        response = self.response(headers={"Content-Length": "1200001"})
        with patch.object(u.requests, "Session", return_value=self.factory([response])):
            with self.assertRaisesRegex(u.DownloadError, "大小"):
                u.download_signed_vps(self.manifest, self.root)
        self.assertFalse(self.part.exists())
        response = self.response(chunks=[b"Z" * self.manifest.size])
        with patch.object(u.requests, "Session", return_value=self.factory([response])):
            with self.assertRaisesRegex(u.DownloadError, "SHA256"):
                u.download_signed_vps(self.manifest, self.root)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.part.exists())


if __name__ == "__main__":
    unittest.main()
