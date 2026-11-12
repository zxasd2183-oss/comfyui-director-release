"""Headless regression tests for Glacier v0.20's shared Chrome-like shell."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QPushButton, QTabBar, QToolButton, QVBoxLayout, QWidget,
)
from glacier_shell20 import GlacierShell20, glacier_home20


class MockUpdater:
    def __init__(self, parent):
        self.button = QPushButton("检查更新", parent)
        self.opened = False

    def show_dialog(self):
        self.opened = True


class MockHost(GlacierShell20, QMainWindow):
    def __init__(self):
        super().__init__()
        root = QWidget(self)
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        strip = QWidget(self)
        strip.setObjectName("GlacierTabStrip14")
        row = QHBoxLayout(strip)
        brand = QLabel("❄", strip)
        brand.setObjectName("GlacierBrand14")
        row.addWidget(brand)
        self.chrome_tab14 = QTabBar(strip)
        self.chrome_tab14.setObjectName("GlacierExternalTabs14")
        row.addWidget(self.chrome_tab14)
        plus = QToolButton(strip)
        plus.setObjectName("GlacierAddTab14")
        row.addWidget(plus)
        self._tab_search_button16 = QToolButton(strip)
        row.addWidget(self._tab_search_button16)
        layout.addWidget(strip)
        self.nav = QHBoxLayout()
        layout.addLayout(self.nav)
        for text in ("←", "→", "↻", "＋"):
            self.nav.addWidget(QPushButton(text, self))
        self.address = QLineEdit(self)
        self.nav.addWidget(self.address, 1)
        self.bookmark_button = QPushButton("☆", self)
        self.nav.addWidget(self.bookmark_button)
        self.update_manager = MockUpdater(self)
        self.nav.addWidget(self.update_manager.button)
        down = QToolButton(self)
        down.setObjectName("GlacierDownloads14")
        self.nav.addWidget(down)
        more = QToolButton(self)
        more.setObjectName("GlacierMore14")
        self.nav.addWidget(more)

        self._workspace_button17 = QToolButton(self)
        self._workspace_menu17 = QMenu(self._workspace_button17)
        self._workspace_menu17.addAction("项目 A")
        self.nav.addWidget(self._workspace_button17)
        self._group_button17 = QToolButton(self)
        self._group_menu17 = QMenu(self._group_button17)
        self._group_menu17.addAction("工作")
        self.nav.addWidget(self._group_button17)
        self._zoom_button16 = QToolButton(self)
        zm = QMenu(self._zoom_button16)
        zm.addAction("100%")
        self._zoom_button16.setMenu(zm)
        self.nav.addWidget(self._zoom_button16)
        self._downloads_button17 = QToolButton(self)
        self.nav.addWidget(self._downloads_button17)
        self._context14 = lambda pt: None
        self.download_center_open = False
        self.tab_search_open = False
        self.settings_open = False
        self.setup_shell20(self.nav)

    def show_download_center17(self):
        self.download_center_open = True

    def show_tab_search16(self):
        self.tab_search_open = True

    def open_settings(self):
        self.settings_open = True


class Shell20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["glacier-v020-shell-test", "-platform", "offscreen"])

    def setUp(self):
        self.win = MockHost()

    def tearDown(self):
        self.win.close()

    def test_toolbar_has_compact_chrome_layout(self):
        w = self.win
        self.assertIn("GlacierOmnibox14", w.address.objectName())
        self.assertIn("搜索或输入网址", w.address.placeholderText())
        widgets = [w.nav.itemAt(i).widget() for i in range(w.nav.count())]
        self.assertLess(widgets.index(w.address), widgets.index(w.bookmark_button))
        self.assertLess(widgets.index(w.bookmark_button), widgets.index(w._hub_button20))
        self.assertLess(widgets.index(w._hub_button20),
                        widgets.index(w.findChild(QToolButton, "GlacierMore14")))
        self.assertEqual(w._hub_button20.text(), "▦")
        self.assertIn("#eef1f5", w.styleSheet())
        self.assertIn("#f1f3f6", w.styleSheet())

    def test_new_hub_preserves_all_original_actions(self):
        w = self.win
        w._build_hub_menu20()
        titles = [a.text() for a in w._hub_menu20.actions()]
        for title in ("工作区", "标签分组", "搜索标签页",
                      "页面缩放", "下载中心", "检查更新", "浏览器设置"):
            self.assertIn(title, titles)
        w._hub_menu20.actions()[titles.index("下载中心")].trigger()
        self.assertTrue(w.download_center_open)
        w._hub_menu20.actions()[titles.index("检查更新")].trigger()
        self.assertTrue(w.update_manager.opened)

    def test_new_tab_page_is_local_and_simple(self):
        page = glacier_home20()
        self.assertIn("Glacier", page)
        self.assertIn('name="q"', page)
        self.assertIn("https://chatgpt.com", page)
        self.assertNotIn("<script", page.casefold())
        self.assertNotIn("http://", page.casefold().replace('xmlns="http://www.w3.org/2000/svg"', ""))
        self.assertEqual(self.win.home_markup(), page)


if __name__ == "__main__":
    unittest.main()
