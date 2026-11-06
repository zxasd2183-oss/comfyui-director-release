"""Local, no-network checks for Glacier's ordinary pointer-drag diagnostics."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QUrl
from glacier_input21 import (
    GlacierInput21,
    allowed_external_url21,
    diagnostic_page21,
)


class FakeStatusBar:
    def __init__(self):
        self.message = ""

    def showMessage(self, text, duration):
        self.message = text


class FakeView:
    def __init__(self, url):
        self.value = QUrl(url)

    def url(self):
        return self.value


class FakeHost(GlacierInput21):
    def __init__(self, url):
        self.view = FakeView(url)
        self.status = FakeStatusBar()

    def current(self):
        return self.view

    def statusBar(self):
        return self.status


class FakeWidget:
    def setFocusPolicy(self, value):
        self.focus = value

    def setMouseTracking(self, value):
        self.tracking = value

    def setAcceptDrops(self, value):
        self.drops = value


class Input21Tests(unittest.TestCase):
    def test_diagnostics_cover_real_pointer_and_html5_events_offline(self):
        html = diagnostic_page21()
        for marker in (
            'addEventListener("pointerdown"',
            'addEventListener("pointermove"',
            'addEventListener("pointerup"',
            'setPointerCapture',
            'addEventListener("dragstart"',
            'addEventListener("drop"',
            'draggable="true"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("<iframe", html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("captcha", html.lower().split("<script>")[1])

    def test_native_qt_input_keeps_mouse_focus_and_drop_enabled(self):
        widget = FakeWidget()
        GlacierInput21.prepare_page_input21(widget)
        self.assertEqual(widget.focus, Qt.FocusPolicy.StrongFocus)
        self.assertTrue(widget.tracking)
        self.assertTrue(widget.drops)

    def test_only_ordinary_web_urls_are_exported(self):
        for url in (
            "https://example.com/path?token=sample",
            "http://example.org/",
        ):
            self.assertTrue(allowed_external_url21(QUrl(url)))
        for url in (
            "file:///C:/private.txt",
            "javascript:alert(1)",
            "data:text/html,hello",
            "about:blank",
            "https://user:password@example.com/",
            "",
        ):
            self.assertFalse(allowed_external_url21(QUrl(url)))

    def test_system_browser_launch_requires_direct_user_action(self):
        host = FakeHost("https://example.org/help?q=test%20drag")
        with patch("glacier_input21.webbrowser.open", return_value=True) as opened:
            self.assertTrue(host.open_in_system_browser21())
            opened.assert_called_once()
            self.assertIn("https://example.org/help?q=test%20drag", opened.call_args.args[0])
        self.assertIn("登录状态是独立的", host.status.message)

    def test_system_browser_launch_failure_is_nonfatal(self):
        host = FakeHost("https://example.com/")
        with patch("glacier_input21.webbrowser.open", side_effect=OSError("missing")):
            self.assertFalse(host.open_in_system_browser21())
        self.assertIn("手动访问", host.status.message)

    def test_non_web_url_never_reaches_browser(self):
        host = FakeHost("file:///C:/private.txt")
        with patch("glacier_input21.webbrowser.open") as opened:
            with patch("glacier_input21.QMessageBox.information"):
                self.assertFalse(host.open_in_system_browser21())
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
