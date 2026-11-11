"""Deterministic tests. Never contact Gemini or a real proxy."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import requests
from PySide6.QtWidgets import QApplication, QMainWindow

from glacier_site_diagnostic31 import (
    GEMINI_PROBE_URL31, SiteProbeResult31, GlacierSiteDiagnostic31,
    check_gemini_via_proxy31, classify_http31,
)


class FakeResponse:
    def __init__(self, status):
        self.status_code = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FakeSession:
    def __init__(self, code=200, error=None):
        self.trust_env = True
        self.proxies = {}
        self.code = code
        self.error = error
        self.arguments = None
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def get(self, *args, **kw):
        self.arguments = (args, kw)
        if self.error:
            raise self.error
        return FakeResponse(self.code)


class ProbeTests31(unittest.TestCase):
    def test_requires_valid_running_local_proxy_without_request(self):
        create = Mock()
        self.assertEqual(check_gemini_via_proxy31(0, session_factory=create).code, "offline")
        self.assertEqual(check_gemini_via_proxy31(1080, ready=lambda _: False,
                                               session_factory=create).code, "offline")
        create.assert_not_called()

    def test_remote_dns_tls_and_redirects_are_never_bypassed(self):
        session = FakeSession(302)
        result = check_gemini_via_proxy31(1080, ready=lambda _: True,
                                           session_factory=lambda: session,
                                           clock=iter([1.0, 1.2]).__next__)
        self.assertEqual(result.code, "reachable")
        self.assertEqual(result.elapsed_ms, 199)
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies, {
            "http": "socks5h://127.0.0.1:1080",
            "https": "socks5h://127.0.0.1:1080",
        })
        args, kwargs = session.arguments
        self.assertEqual(args, (GEMINI_PROBE_URL31,))
        self.assertTrue(kwargs["verify"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["timeout"], (5, 11))
        self.assertNotIn("Cookie", kwargs["headers"])
        self.assertNotIn("Authorization", kwargs["headers"])

    def test_http_statuses_are_not_misreported_as_streaming_success(self):
        self.assertEqual(classify_http31(200, 40).code, "reachable")
        self.assertIn("不等于", classify_http31(200, 40).message)
        self.assertEqual(classify_http31(429, 10).code, "busy")
        self.assertEqual(classify_http31(503, 10).code, "busy")
        self.assertEqual(classify_http31(401, 10).code, "access")
        self.assertEqual(classify_http31(502, 10).code, "server")

    def test_no_credential_leak_from_proxy_errors(self):
        for error, code in (
            (requests.exceptions.ProxyError("vless://secret-token"), "proxy"),
            (requests.exceptions.SSLError("private-certificate"), "tls"),
            (requests.exceptions.ConnectTimeout("private-address"), "timeout"),
        ):
            session = FakeSession(error=error)
            result = check_gemini_via_proxy31(1080, ready=lambda _: True,
                                                session_factory=lambda: session)
            self.assertEqual(result.code, code)
            self.assertNotIn("private", result.message)
            self.assertNotIn("secret", result.message)

    def test_windows_proxy_is_locked_before_qt_initializes(self):
        from pathlib import Path
        source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
        entry = source.split("def main():", 1)[1]
        flags = entry.index('os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]')
        startup = entry.index("app=QApplication(sys.argv)")
        self.assertLess(flags, startup)
        self.assertIn("--proxy-server=socks5://127.0.0.1:", entry[flags:startup])
        self.assertIn("--disable-quic", entry[flags:startup])

    def test_probe_not_triggered_until_user_action(self):
        class Host(GlacierSiteDiagnostic31, QMainWindow):
            proxy_port = 1080
        app = QApplication.instance() or QApplication(["glacier", "-platform", "offscreen"])
        with patch("glacier_site_diagnostic31.threading.Thread") as thread:
            window = Host()
            self.assertIsNone(getattr(window, "_gemini_dialog31", None))
            thread.assert_not_called()
            window.close()


if __name__ == "__main__":
    unittest.main()
