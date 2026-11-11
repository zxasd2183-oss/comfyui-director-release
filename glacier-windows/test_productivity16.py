"""Cross-platform v0.16 Qt smoke tests (no real internet, proxy or WebEngine)."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QTabBar, QTabWidget,
    QVBoxLayout, QWidget,
)
from glacier_productivity16 import GlacierProductivity16


class FakePage(QWidget):
    def __init__(self, url):
        super().__init__()
        self._url = QUrl(url)
        self._zoom = 1.0

    def url(self):
        return self._url

    def setUrl(self, url):
        self._url = url

    def zoomFactor(self):
        return self._zoom

    def setZoomFactor(self, factor):
        self._zoom = factor


class Host(GlacierProductivity16, QMainWindow):
    def __init__(self, *, mac=False):
        super().__init__()
        root = QWidget(self)
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        self.strip = QWidget(self)
        top = QHBoxLayout(self.strip)
        self.chrome_tab14 = QTabBar(self.strip)
        top.addWidget(self.chrome_tab14)
        lay.addWidget(self.strip)
        self.nav = QHBoxLayout()
        lay.addLayout(self.nav)
        self.tabs = QTabWidget(self)
        lay.addWidget(self.tabs)
        self.tabs.addTab(FakePage("https://www.google.com"), "Google 搜索")
        self.tabs.addTab(FakePage("https://www.youtube.com/watch"), "Video")
        self._recently_closed15 = ["https://closed.example/private-path"]
        self.setup_productivity16(self.nav, mac=mac)

    def current(self):
        return self.tabs.currentWidget()

    def new_tab(self):
        view = FakePage("about:blank")
        self.tabs.addTab(view, "新标签")
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        return view


class Productivity16Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["Glacier-v0.16-QA", "-platform", "offscreen"]
        )

    def test_tab_search_matches_title_and_hostname(self):
        win = Host()
        try:
            win.show_tab_search16()
            win._tab_search_input16.setText("youtube.com")
            self.assertEqual(len(win._tab_search_results16), 1)
            win._activate_tab_search16()
            self.assertEqual(win.tabs.currentIndex(), 1)
        finally:
            win.close()

    def test_recently_closed_restore_uses_only_http_urls(self):
        win = Host()
        try:
            win._recently_closed15.append("file:///private/secret")
            win.show_tab_search16()
            win._tab_search_input16.setText("closed.example")
            self.assertEqual(len(win._tab_search_results16), 1)
            win._activate_tab_search16()
            self.assertEqual(win.tabs.count(), 3)
            self.assertEqual(win.current().url().toString(),
                             "https://closed.example/private-path")
            self.assertNotIn("https://closed.example/private-path",
                             win._recently_closed15)
        finally:
            win.close()

    def test_zoom_steps_and_per_tab_isolation(self):
        win = Host()
        try:
            win.change_zoom16(1)
            self.assertEqual(win.current().zoomFactor(), 1.1)
            self.assertEqual(win._zoom_button16.text(), "110%")
            win.tabs.setCurrentIndex(1)
            self.assertEqual(win._zoom_button16.text(), "100%")
            for _ in range(30):
                win.change_zoom16(-1)
            self.assertEqual(win.current().zoomFactor(), 0.50)
            win.reset_zoom16()
            self.assertEqual(win.current().zoomFactor(), 1.0)
            win.tabs.setCurrentIndex(0)
            self.assertEqual(win.current().zoomFactor(), 1.1)
        finally:
            win.close()

    def test_both_platform_shortcuts(self):
        for mac, prefix in ((False, "Ctrl"), (True, "Meta")):
            win = Host(mac=mac)
            try:
                keys = {
                    s.key().toString(QKeySequence.SequenceFormat.PortableText)
                    for s in win._productivity_shortcuts16
                }
                self.assertIn(f"{prefix}+Shift+A", keys)
                self.assertIn(f"{prefix}+-", keys)
                self.assertNotIn("", keys)
                self.assertIn(f"{prefix}+0", keys)
            finally:
                win.close()


if __name__ == "__main__":
    unittest.main()
