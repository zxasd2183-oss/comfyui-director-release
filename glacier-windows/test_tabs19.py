"""v0.19 tab context operations: QTabWidget without network or WebEngine."""
from __future__ import annotations
import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget, QTabBar

from glacier_tabs19 import GlacierTabs19


class FakePage(QWidget):
    def __init__(self, uri="about:blank"):
        super().__init__()
        self._url=QUrl(uri)
        self.reloads=0

    def url(self):
        return self._url

    def setUrl(self, uri):
        self._url=uri

    def reload(self):
        self.reloads+=1


class Host(GlacierTabs19, QMainWindow):
    def __init__(self):
        super().__init__()
        self.tabs=QTabWidget(self)
        self.setCentralWidget(self.tabs)
        self.chrome_tab14=QTabBar(self)
        self._workspace_group_by_view17={}
        self._workspace_doc17={"active":"default", "items":[{"id":"default","groups":[{"id":"work","name":"工作"}]}]}
        self.add("https://example.org/a")
        self.add("https://example.org/b")
        self.add("about:blank")
        self.tabs.setCurrentIndex(0)
        self.setup_tabs19()

    def _active_workspace17(self):
        return self._workspace_doc17["items"][0]

    def _decorate_group_tabs17(self):
        pass

    def _queue_workspace_save17(self):
        pass

    def assign_tab_group17(self, group_id):
        if group_id is not None and group_id!="work":
            return False
        self._workspace_group_by_view17[id(self.tabs.currentWidget())]=group_id
        return True

    def add(self, url):
        tab=FakePage(url)
        self.tabs.addTab(tab,"Page")
        self.chrome_tab14.addTab("Page")
        return tab

    def new_tab(self):
        tab=self.add("about:blank")
        self.tabs.setCurrentWidget(tab)
        return tab

    def close_tab(self, index):
        if index < 0 or index >= self.tabs.count():
            return
        view=self.tabs.widget(index)
        self._workspace_group_by_view17.pop(id(view),None)
        self.tabs.removeTab(index)
        self.chrome_tab14.removeTab(index)
        view.deleteLater()
        if not self.tabs.count():
            self.new_tab()


class TabContextTests19(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication(
            ["glacier-tab19-test","-platform","offscreen"])

    def setUp(self):
        self.win=Host()

    def tearDown(self):
        self.win.close()

    def test_context_menu_on_both_tabs(self):
        self.assertEqual(len(self.win._tab_bars19),2)

    def test_duplicate_retains_group(self):
        first=self.win.tabs.widget(0)
        self.assertTrue(self.win._assign_view_to_group19(first,"work"))
        self.assertTrue(self.win._duplicate_tab19(first))
        new=self.win.current_tab if hasattr(self.win,"current_tab") else self.win.tabs.currentWidget()
        self.assertEqual(new.url().toString(),"https://example.org/a")
        self.assertEqual(self.win._workspace_group_by_view17[id(new)],"work")

    def test_copy_sanitizes_no_credential(self):
        first=self.win.tabs.widget(0)
        self.assertTrue(self.win._copy_tab_url19(first))
        self.assertEqual(QApplication.clipboard().text(),"https://example.org/a")
        first.setUrl(QUrl("https://alice:pass@example.org/secret"))
        self.assertFalse(self.win._copy_tab_url19(first))

    def test_duplicate_non_http_blocked(self):
        blank=self.win.tabs.widget(2)
        self.assertFalse(self.win._duplicate_tab19(blank))
        self.assertEqual(self.win.tabs.count(),3)

    def test_batch_close_right(self):
        first=self.win.tabs.widget(0)
        self.assertTrue(self.win._close_tabs_right19(first))
        self.assertEqual(self.win.tabs.count(),1)
        self.assertIs(self.win.tabs.widget(0),first)

    def test_close_others_preserves_target(self):
        middle=self.win.tabs.widget(1)
        self.assertTrue(self.win._close_other_tabs19(middle))
        self.assertEqual(self.win.tabs.count(),1)
        self.assertIs(self.win.tabs.widget(0),middle)

    def test_group_change_restores_focus(self):
        first=self.win.tabs.widget(0)
        self.win.tabs.setCurrentIndex(1)
        focus=self.win.tabs.currentWidget()
        self.assertTrue(self.win._assign_view_to_group19(first,"work"))
        self.assertIs(self.win.tabs.currentWidget(),focus)
        self.assertEqual(self.win._workspace_group_by_view17.get(id(first)),"work")


if __name__=="__main__":
    unittest.main()
