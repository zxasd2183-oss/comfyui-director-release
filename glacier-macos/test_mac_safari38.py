"""Native Qt smoke test for macOS Safari-style desktop presentation.

No live websites, accounts, passwords, proxy, or signing keys are required.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QPushButton, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget
)

from mac_safari38 import SAFARI_MAC_QSS38, install_mac_safari38, safari_icon38


class SamplePage(QWidget):
    def __init__(self, address, parent=None):
        super().__init__(parent)
        self._address = QUrl(address)

    def url(self):
        return self._address


class SafariFixture(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1050, 730)
        self.central = QWidget()
        self.central.setObjectName("GlacierBrowserRoot32")
        self.setCentralWidget(self.central)
        root = QVBoxLayout(self.central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        strip = QWidget(self.central)
        strip.setObjectName("GlacierTabStrip14")
        strip_row = QHBoxLayout(strip)
        self.chrome_tab14 = QTabBar(strip)
        self.chrome_tab14.setObjectName("GlacierExternalTabs14")
        self.chrome_tab14.addTab("首页")
        self.chrome_tab14.addTab("项目")
        strip_row.addWidget(self.chrome_tab14)
        strip_row.addStretch()
        root.addWidget(strip)

        self._navigation_surface32 = QFrame(self.central)
        self._navigation_surface32.setObjectName("GlacierNavigation32")
        self._navigation32 = QHBoxLayout(self._navigation_surface32)
        self._navigation32.addWidget(QPushButton("←"))
        self._navigation32.addWidget(QPushButton("→"))
        self._chrome_omnibox_shell33 = QFrame(self._navigation_surface32)
        self._chrome_omnibox_shell33.setObjectName("GlacierOmniboxShell33")
        self.address = QLineEdit(self._chrome_omnibox_shell33)
        inside = QHBoxLayout(self._chrome_omnibox_shell33)
        inside.addWidget(self.address)
        self._navigation32.addWidget(self._chrome_omnibox_shell33, 1)
        self._account_button26 = QPushButton("账号")
        self._navigation32.addWidget(self._account_button26)
        root.addWidget(self._navigation_surface32)

        self.tabs = QTabWidget(self.central)
        self.tabs.addTab(SamplePage("https://example.com/"), "示例首页")
        self.tabs.addTab(SamplePage("https://example.org/"), "示例项目")
        root.addWidget(self.tabs, 1)
        self.bookmarks_menu = QMenu(self)
        self.bookmarks_menu.addAction("示例书签")
        self.history_opened = 0
        self._chrome_ui33_ready = True
        self._group_button17 = QToolButton(self)
        self._group_button17.setMenu(QMenu(self))
        self._group_button17.menu().addAction("无分组")
        self.statusBar()

    def show_history(self):
        self.history_opened += 1


@unittest.skipUnless(sys.platform == "darwin", "macOS-native layout only")
class MacSafari38Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["Glacier-Safari38-QA", "-platform", "offscreen"]
        )

    def setUp(self):
        self.window = SafariFixture()
        install_mac_safari38(self.window)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window._safari_refresh_timer38.stop()
        self.window.close()
        self.app.processEvents()

    def test_real_widgets_reordered_and_browser_pages_preserved(self):
        win = self.window
        root = win.centralWidget().layout()
        self.assertEqual(root.indexOf(win._navigation_surface32), 0)
        self.assertEqual(root.indexOf(win.chrome_tab14.parentWidget()), 1)
        self.assertIs(win.tabs.parentWidget(), win._safari_split38)
        self.assertEqual(win.tabs.count(), 2)
        self.assertEqual(win.tabs.widget(0).url().toString(), "https://example.com/")
        self.assertEqual(win._navigation_surface32.height(), 53)
        self.assertEqual(win.chrome_tab14.parentWidget().height(), 39)
        self.assertNotIn("FramelessWindowHint", str(win.windowFlags()))
        self.assertFalse(win._safari_sidebar_button38.isChecked())

    def test_sidebar_toggles_and_selects_original_tabs(self):
        win = self.window
        win._safari_sidebar_button38.click()
        self.app.processEvents()
        self.assertTrue(win._safari_sidebar38.isVisible())
        self.assertEqual(win._safari_tab_list38.count(), 2)
        win._safari_tab_list38.setCurrentRow(1)
        self.assertEqual(win.tabs.currentIndex(), 1)
        win._safari_sidebar_button38.click()
        self.app.processEvents()
        self.assertFalse(win._safari_sidebar38.isVisible())
        self.assertEqual(win.tabs.count(), 2)

    def test_share_copies_only_http_https_and_does_not_navigate(self):
        win = self.window
        win._safari_share_button38.click()
        self.assertEqual(self.app.clipboard().text(), "https://example.com/")
        win.tabs.widget(0)._address = QUrl("file:///private/secret.txt")
        self.app.clipboard().setText("keep-existing")
        win._safari_share_button38.click()
        self.assertEqual(self.app.clipboard().text(), "keep-existing")

    def test_existing_bookmark_and_history_actions_are_retained(self):
        win = self.window
        buttons = {
            widget.objectName():widget
            for widget in win._safari_sidebar38.findChildren(QPushButton)
        }
        self.assertIn("GlacierSafariBookmarks38", buttons)
        self.assertIn("GlacierSafariHistory38", buttons)
        self.assertIn("GlacierSafariGroups38", buttons)
        buttons["GlacierSafariHistory38"].click()
        self.assertEqual(win.history_opened, 1)
        self.assertEqual(len(win.bookmarks_menu.actions()), 1)
        self.assertFalse(safari_icon38("share").isNull())
        self.assertIn("GlacierSafariSidebar38", SAFARI_MAC_QSS38)

    def test_second_install_is_rejected(self):
        with self.assertRaises(RuntimeError):
            install_mac_safari38(self.window)


if __name__ == "__main__":
    unittest.main()
