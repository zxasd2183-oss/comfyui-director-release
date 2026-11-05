"""v0.17 workspaces smoke tests: encryption, local isolation and group recovery."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QTabBar, QTabWidget, QWidget

from glacier_workspaces17 import (
    GlacierWorkspaces17, _clean_workspaces17, _safe_url17,
    WORKSPACE_LIMIT17,
)


def fake_cipher(data, decrypt=False):
    if decrypt:
        if not data.startswith(b"ENC17"):
            raise ValueError("not encrypted")
        return data[5:][::-1]
    return b"ENC17" + data[::-1]


class Page(QWidget):
    urlChanged = Signal(QUrl)
    titleChanged = Signal(str)

    def __init__(self, url="about:blank"):
        super().__init__()
        self._url = QUrl(url)

    def url(self):
        return self._url

    def setUrl(self, url):
        self._url = url
        self.urlChanged.emit(url)


class Base(QMainWindow):
    def refresh_tabs14(self):
        self.refreshed = getattr(self, "refreshed", 0) + 1


class Host(GlacierWorkspaces17, Base):
    def __init__(self, folder):
        super().__init__()
        self._root = QWidget(self)
        self.setCentralWidget(self._root)
        self.nav = QHBoxLayout(self._root)
        self.chrome_tab14 = QTabBar(self)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(Page("https://alpha.example/page"), "Alpha")
        self.setup_workspaces17(self.nav, folder, fake_cipher)

    def current(self):
        return self.tabs.currentWidget()

    def new_tab(self):
        page = Page()
        self.tabs.addTab(page, "New")
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        self._workspace_register17(page)
        self.refresh_tabs14()
        return page

    def cleanup_closed13(self, view):
        pass


class WorkspaceTests17(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["Glacier-workspaces-test", "-platform", "offscreen"]
        )

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.win = Host(Path(self.folder.name))

    def tearDown(self):
        self.win._workspace_timer17.stop()
        self.win.close()
        self.folder.cleanup()

    def test_encrypt_and_switch_between_isolated_workspaces(self):
        self.assertTrue(self.win.create_workspace17("项目 A"))
        self.assertEqual(self.win.tabs.count(), 1)
        self.win.current().setUrl(QUrl("https://beta.example/"))
        self.win._save_active_workspace17()
        self.assertNotIn(b"beta.example",
                         (Path(self.folder.name) / "workspaces-v17.enc").read_bytes())

        self.assertTrue(self.win.switch_workspace17("default"))
        self.assertEqual(self.win.current().url().toString(),
                         "https://alpha.example/page")
        second_id = next(w["id"] for w in self.win._workspace_doc17["items"]
                         if w["id"] != "default")
        self.assertTrue(self.win.switch_workspace17(second_id))
        self.assertEqual(self.win.current().url().toString(),
                         "https://beta.example/")
        self.assertTrue(self.win.rename_workspace17("私人项目"))
        self.assertIn("私人项目", self.win._workspace_button17.text())

    def test_tab_group_creation_colors_and_persistence(self):
        self.assertTrue(self.win.create_group17("研究"))
        self.assertEqual(self.win.tabs.tabBar().tabToolTip(0), "标签分组：研究")
        self.win._save_active_workspace17()
        self.assertIn("研究", fake_cipher(
            (Path(self.folder.name) / "workspaces-v17.enc").read_bytes(), True
        ).decode("utf-8"))
        gid = self.win._active_workspace17()["groups"][0]["id"]
        self.assertTrue(self.win.rename_group17(gid, "文档"))
        self.assertEqual(self.win.tabs.tabBar().tabToolTip(0), "标签分组：文档")
        self.assertTrue(self.win.delete_group17(gid))
        self.assertEqual(self.win.tabs.tabBar().tabToolTip(0), "")

    def test_bad_url_and_bad_workspace_document_are_rejected(self):
        for invalid in ("file:///secret", "javascript:alert(1)",
                        "https://user:password@example.com", "not-a-url"):
            self.assertEqual(_safe_url17(invalid), "")
        with self.assertRaises(ValueError):
            _clean_workspaces17({
                "schema": 1, "active": "default",
                "items": [{"id": "default", "name": "default", "groups": [],
                           "tabs": [{"url": "file:///home/secret", "group": None}],
                           "selected": 0}]})

    def test_corrupt_file_is_not_overwritten(self):
        path = Path(self.folder.name) / "workspaces-v17.enc"
        self.win._workspace_timer17.stop()
        path.write_bytes(b"damaged-encrypted-bytes")
        second = Host(Path(self.folder.name))
        try:
            self.assertTrue(second._workspace_readonly17)
            second._save_active_workspace17()
            self.assertEqual(path.read_bytes(), b"damaged-encrypted-bytes")
        finally:
            second._workspace_timer17.stop()
            second.close()

    def test_no_workspace_duplicate_and_delete_last(self):
        self.assertFalse(self.win.delete_workspace17())
        self.assertTrue(self.win.create_workspace17("second"))
        self.assertTrue(self.win.delete_workspace17())
        self.assertEqual(len(self.win._workspace_doc17["items"]), 1)
        self.assertEqual(self.win._workspace_doc17["active"], "default")


if __name__ == "__main__":
    unittest.main()
