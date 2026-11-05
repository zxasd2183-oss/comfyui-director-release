"""Headless Qt widget test: catches missing Mac updater/Chrome UI integration."""
from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QTabWidget, QMenu,
)
from mac_chrome_adapter import MacChrome14


class MinimalBrowser(MacChrome14,QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(960,720)
        root=QWidget(self);self.setCentralWidget(root)
        self.layout=QVBoxLayout(root)
        self.nav=QHBoxLayout()
        self.layout.addLayout(self.nav)
        self.address=QLineEdit(self)
        self.nav.addWidget(self.address)
        self.bookmark_button=QPushButton("☆",self)
        self.nav.addWidget(self.bookmark_button)
        self._mac_update_button=QPushButton("↻ Mac 更新",self)
        self.nav.addWidget(self._mac_update_button)
        self.bookmarks_menu=QMenu(self)
        self.tabs=QTabWidget(self)
        self.tabs.addTab(QWidget(self),"Test tab")
        self.layout.addWidget(self.tabs)
        self._pinned_tabs13=set()
        self.setup_chrome14(self.layout,self.nav)

    def show_mac_updates(self):pass
    def new_tab(self):self.tabs.addTab(QWidget(self),"New tab")
    def close_tab(self,index):
        if 0<=index<self.tabs.count():self.tabs.removeTab(index)
    def open_satellite(self,private=False):pass
    def toggle_bookmark(self):pass
    def show_history(self):pass
    def show_downloads(self):pass
    def open_find13(self):pass
    def start_connection_check(self):pass
    def open_settings(self):pass
    def close_other_tabs13(self,*args):pass
    def pin_tab13(self,*args):pass


class MacChromeStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication(["Glacier-QA","-platform","offscreen"])

    def test_updater_adapter_survives_real_qt_chrome_toolbar_setup(self):
        window=MinimalBrowser()
        self.assertEqual(window.chrome_tab14.count(),1)
        self.assertIs(window.update_manager.button,window._mac_update_button)
        self.assertTrue(callable(window.update_manager.show_dialog))
        self.assertIn("v0.17.0",window.windowTitle())
        window.close()


if __name__=="__main__":
    unittest.main()
