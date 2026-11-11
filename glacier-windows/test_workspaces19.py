"""v0.19 regression: restored tabs save navigation changes, no startup write."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from test_workspaces17 import Host, fake_cipher


class WorkspaceNavigation19Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication(
            ["glacier-workspace19-test","-platform","offscreen"])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.win=Host(self.folder)

    def tearDown(self):
        self.win._workspace_timer17.stop()
        self.win.close()
        self.temp.cleanup()

    def test_existing_initial_tab_is_bound_for_navigation(self):
        view=self.win.tabs.widget(0)
        self.assertIn(id(view), self.win._workspace_bound_views19)
        self.win._workspace_timer17.stop()
        view.setUrl(QUrl("https://second.example/path"))
        self.assertTrue(self.win._workspace_timer17.isActive())
        self.win._save_active_workspace17()
        contents=fake_cipher((self.folder/"workspaces-v17.enc").read_bytes(),True)
        self.assertIn(b"second.example/path", contents)

    def test_initial_bind_does_not_overwrite_existing_encrypted_data(self):
        self.assertFalse((self.folder/"workspaces-v17.enc").exists())
        self.assertFalse(self.win._workspace_timer17.isActive())
        self.win._workspace_register17(self.win.tabs.widget(0))
        self.assertFalse(self.win._workspace_timer17.isActive())

    def test_close_discards_binding(self):
        view=self.win.tabs.widget(0)
        self.assertIn(id(view),self.win._workspace_bound_views19)
        self.win._workspace_forget17(view)
        self.assertNotIn(id(view),self.win._workspace_bound_views19)


if __name__=="__main__":
    unittest.main()
