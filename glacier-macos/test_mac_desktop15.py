"""Headless smoke checks for the Glacier v0.15 Mac desktop layer."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QWidget

from mac_desktop15 import MacDesktop15
from test_mac_gui_start import MinimalBrowser


class TestPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loaded_url = None

    def setUrl(self, url):
        self.loaded_url = url


class DesktopBrowser(MacDesktop15, MinimalBrowser):
    def __init__(self):
        self.saved = 0
        super().__init__()

    def save_session(self):
        self.saved += 1

    def new_tab(self):
        page = TestPage(self)
        self.tabs.addTab(page, "Restored")
        self.tabs.setCurrentWidget(page)
        return page

    def current(self):
        return self.tabs.currentWidget()


class Desktop15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["Glacier-v15-QA", "-platform", "offscreen"]
        )

    def setUp(self):
        self.window = DesktopBrowser()
        self.window.setup_desktop15()

    def tearDown(self):
        self.window._autosave_timer15.stop()
        self.window.close()

    def test_mac_version_theme_and_shortcuts(self):
        self.assertIn("v0.20.17", self.window.windowTitle())
        self.assertIn("#e9f5fc", self.window.styleSheet())
        keys = {s.key().toString(QKeySequence.SequenceFormat.PortableText)
                for s in self.window._desktop15_shortcuts}
        for key in ("Meta+L", "Meta+T", "Meta+W", "Meta+R", "Meta+Shift+T", "Meta+9"):
            self.assertIn(key, keys)

    def test_recent_tabs_only_restore_https_and_http(self):
        self.window.remember_recent15("file:///private/secret.txt")
        self.window.remember_recent15("javascript:alert(1)")
        self.window.remember_recent15("vless://example")
        self.assertEqual(self.window._recently_closed15, [])
        self.window.remember_recent15("https://www.google.com/search?q=glacier")
        self.window.reopen_closed_tab15()
        self.assertEqual(
            self.window.tabs.currentWidget().loaded_url.toString(),
            "https://www.google.com/search?q=glacier",
        )
        self.assertEqual(self.window._recently_closed15, [])

    def test_autosave_uses_existing_session_writer(self):
        self.window._autosave_session15()
        self.assertEqual(self.window.saved, 1)


if __name__ == "__main__":
    unittest.main()
