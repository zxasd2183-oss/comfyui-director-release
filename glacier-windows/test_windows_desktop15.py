"""Glacier Browser v0.15 Windows desktop behavior smoke tests."""
from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow, QPushButton, QTabBar, QTabWidget, QWidget
from windows_desktop15 import WindowsDesktop15


class FakePage(QWidget):
    def __init__(self):
        super().__init__()
        self.loaded = None

    def setUrl(self, url):
        self.loaded = url


class FakeWindowsBrowser(WindowsDesktop15, QMainWindow):
    def __init__(self):
        super().__init__()
        self.address = QLineEdit(self)
        self.chrome_tab14 = QTabBar(self)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(FakePage(), "Start")
        self.update_manager = type("Updater", (), {"button": QPushButton("更新", self)})()
        self.saved = 0
        self.setup_desktop15()

    def new_tab(self):
        page = FakePage()
        self.tabs.addTab(page, "Reopened")
        self.tabs.setCurrentWidget(page)
        return page

    def current(self):
        return self.tabs.currentWidget()

    def save_session(self):
        self.saved += 1

    def close_tab(self, index):
        if 0 <= index < self.tabs.count():
            self.tabs.removeTab(index)


class WindowsDesktop15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["Glacier-Win-QA", "-platform", "offscreen"])

    def setUp(self):
        self.win = FakeWindowsBrowser()

    def tearDown(self):
        self.win._autosave_timer15.stop()
        self.win.close()

    def test_version_theme_and_shortcuts(self):
        self.assertIn("v0.20.26", self.win.windowTitle())
        self.assertIn("#e9f5fc", self.win.styleSheet())
        keys = {
            s.key().toString(QKeySequence.SequenceFormat.PortableText)
            for s in self.win._desktop15_shortcuts
        }
        for key in ("Ctrl+L", "Ctrl+T", "Ctrl+W", "Ctrl+R", "Ctrl+Shift+T", "Ctrl+9"):
            self.assertIn(key, keys)

    def test_restore_http_only(self):
        self.win.remember_recent15("file:///C:/secret.txt")
        self.win.remember_recent15("javascript:alert(1)")
        self.assertFalse(self.win._recently_closed15)
        self.win.remember_recent15("https://example.com/")
        self.win.reopen_closed_tab15()
        self.assertEqual(self.win.current().loaded.toString(), "https://example.com/")
        self.assertFalse(self.win._recently_closed15)

    def test_save_session_reuses_original_writer(self):
        self.win._autosave_session15()
        self.assertEqual(self.win.saved, 1)


if __name__ == "__main__":
    unittest.main()
