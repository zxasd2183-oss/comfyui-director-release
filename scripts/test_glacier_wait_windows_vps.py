"""Offline regression: event-bound Windows VPS readiness requires no VPS token."""
import io
import unittest
import urllib.error
from unittest.mock import Mock, patch

from source.scripts import glacier_wait_windows_vps as wait


class FakeResponse:
    def __init__(self, status, url, size):
        self.status = status
        self.url = url
        self.headers = {"Content-Length": str(size)}

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class WaitVpsTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "url": "https://sync.borealos.cn/downloads/"
                   "GlacierBrowser-v0.20.18-Windows-Setup-x64.exe",
            "size": 175907184,
            "sha256": "a" * 64,
        }

    def test_404_then_ready_triggers_full_hash_without_waiting_for_cron(self):
        clock_value = [0.0]
        checks = Mock(side_effect=[False, False, True])
        digest = Mock()

        def clock():
            return clock_value[0]

        def sleep(seconds):
            clock_value[0] += seconds

        result = wait.wait_and_verify(
            self.payload, 700, 6,
            probe=checks, verify=digest, clock=clock, sleep=sleep,
        )
        self.assertEqual(result, 3)
        self.assertEqual(clock_value[0], 12)
        digest.assert_called_once_with(
            self.payload["url"], self.payload["size"], self.payload["sha256"],
        )

    def test_timeout_is_bounded_and_no_signature_or_hash_promotion(self):
        clock_value = [0.0]
        digest = Mock()
        def sleep(seconds):
            clock_value[0] += seconds
        with self.assertRaisesRegex(TimeoutError, "nothing signed"):
            wait.wait_and_verify(
                self.payload, 13, 5, probe=lambda *_: False, verify=digest,
                clock=lambda: clock_value[0], sleep=sleep,
            )
        self.assertEqual(clock_value[0], 13)
        digest.assert_not_called()

    def test_integrity_gate_failure_fails_closed_no_retry(self):
        digest = Mock(side_effect=ValueError("bad SHA256"))
        with self.assertRaisesRegex(ValueError, "SHA256"):
            wait.wait_and_verify(
                self.payload, probe=lambda *_: True, verify=digest,
                sleep=lambda *_: self.fail("must not retry a digest mismatch"),
            )
        digest.assert_called_once()

    def test_bad_configuration_does_not_poll(self):
        for seconds, interval in [(721, 6), (-1, 6), (10, 0), (10, 61)]:
            with self.assertRaises(ValueError):
                wait.wait_and_verify(
                    self.payload, seconds, interval,
                    probe=lambda *_: self.fail("unexpected probe"),
                )

    @patch.object(wait.urllib.request, "build_opener")
    def test_404_is_transient_but_403_is_not(self, build):
        e404 = urllib.error.HTTPError(self.payload["url"], 404, "missing", {}, None)
        e403 = urllib.error.HTTPError(self.payload["url"], 403, "forbidden", {}, None)
        build.return_value.open.side_effect = [e404, e403]
        self.assertFalse(wait.probe_ready(self.payload["url"], self.payload["size"]))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            wait.probe_ready(self.payload["url"], self.payload["size"])
        self.assertEqual(ctx.exception.code, 403)

    @patch.object(wait.urllib.request, "build_opener")
    def test_head_requires_exact_url_and_size(self, build):
        url = self.payload["url"]
        build.return_value.open.return_value = FakeResponse(
            200, url, self.payload["size"])
        self.assertTrue(wait.probe_ready(url, self.payload["size"]))
        build.return_value.open.return_value = FakeResponse(
            200, "https://other.example/redirect", self.payload["size"])
        with self.assertRaisesRegex(ValueError, "redirect"):
            wait.probe_ready(url, self.payload["size"])
        build.return_value.open.return_value = FakeResponse(
            200, url, self.payload["size"] + 100)
        with self.assertRaisesRegex(ValueError, "length"):
            wait.probe_ready(url, self.payload["size"])
        with self.assertRaisesRegex(ValueError, "non-owner"):
            wait.probe_ready("https://github.com/asset.exe", self.payload["size"])


if __name__ == "__main__":
    unittest.main()
