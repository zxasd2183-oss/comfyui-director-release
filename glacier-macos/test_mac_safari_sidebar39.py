"""macOS Safari sidebar 39 native widget and security regression tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication

from mac_safari38 import install_mac_safari38
from mac_safari_sidebar39 import _safe_history_url39, SafariSidebar39
from test_mac_safari38 import SafariFixture, SamplePage


@unittest.skipUnless(sys.platform == "darwin", "Native macOS Safari sidebar only")
class SafariSidebar39Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["Glacier-SafariSidebar39-QA", "-platform", "offscreen"]
        )

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ini = os.path.join(self.directory.name, "glacier-safari.ini")
        self.win = self._new_window()

    def _new_window(self):
        win = SafariFixture()
        win._safari_settings39 = QSettings(self.ini, QSettings.Format.IniFormat)
        install_mac_safari38(win)
        win.show()
        self.app.processEvents()
        return win

    def tearDown(self):
        self.win._safari_refresh_timer38.stop()
        self.win.close()
        self.app.processEvents()
        self.directory.cleanup()

    def _open(self):
        if not self.win._safari_sidebar_button38.isChecked():
            self.win._safari_sidebar_button38.click()
        self.app.processEvents()
        self.win._safari_refresh38()
        return self.win._safari_controller39

    def test_tab_search_filters_titles_and_preserves_true_tab_identity(self):
        controller = self._open()
        controller.search.setText("示例项目")
        self.app.processEvents()
        self.assertEqual(controller.list.count(), 1)
        self.assertEqual(controller.list.item(0).text(), "示例项目")
        self.assertEqual(self.win.tabs.currentIndex(), 0)
        controller.activate(controller.list.item(0))
        self.assertEqual(self.win.tabs.currentIndex(), 1)
        self.assertEqual(self.win.tabs.count(), 2)
        controller.search.clear()
        self.assertEqual(controller.list.count(), 2)

    def test_bookmark_actions_trigger_existing_browser_callback(self):
        fired = []
        action = self.win.bookmarks_menu.actions()[0]
        action.triggered.connect(lambda _: fired.append("bookmark"))
        controller = self._open()
        controller.bookmarks_button.click()
        self.app.processEvents()
        self.assertEqual(controller.mode, "bookmarks")
        self.assertEqual(controller.list.count(), 1)
        self.assertEqual(controller.list.item(0).text(), "示例书签")
        controller.activate(controller.list.item(0))
        self.assertEqual(fired, ["bookmark"])
        self.assertEqual(self.win.tabs.count(), 2)

    def test_history_only_lists_http_https_and_is_click_to_open(self):
        self.win._recently_closed15 = [
            "file:///private/notes.txt",
            "javascript:alert(1)",
            "https://name:secret@example.com/",
            "https://recent.example/page"
        ]
        self.assertEqual(_safe_history_url39("file:///tmp/note"), "")
        self.assertEqual(_safe_history_url39("https://u:pw@site.test/"), "")
        self.assertEqual(_safe_history_url39("javascript:alert(1)"), "")
        created = []

        def new_page():
            page = SamplePage("https://new.example/", self.win)
            def set_url(url):
                page._address = url
                created.append(url.toString())
            page.setUrl = set_url
            return page

        self.win.new_tab = new_page
        controller = self._open()
        controller.history_button.click()
        self.app.processEvents()
        self.assertEqual(controller.mode, "history")
        self.assertEqual(controller.list.count(), 1)
        self.assertEqual(created, [])  # Never open a URL on sidebar refresh.
        controller.activate(controller.list.item(0))
        self.assertEqual(created, ["https://recent.example/page"])
        controller.footer.click()
        self.assertEqual(self.win.history_opened, 1)

    def test_ui_state_persists_without_any_visit_history_or_password(self):
        controller = self._open()
        controller.set_mode("bookmarks")
        controller.width = 272
        controller.settings.setValue("ui/macSafariSidebar39/width", 272)
        controller.settings.sync()
        self.assertTrue(controller.toggle.isChecked())
        self.assertEqual(controller.settings.value("ui/macSafariSidebar39/mode"), "bookmarks")
        saved_keys = controller.settings.allKeys()
        self.assertTrue(all(key.startswith("ui/macSafariSidebar39/") for key in saved_keys))
        self.assertFalse(any("recent.example" in str(controller.settings.value(k))
                             for k in saved_keys))
        self.win._safari_refresh_timer38.stop()
        self.win.close()
        self.app.processEvents()
        self.win = self._new_window()
        self.app.processEvents()
        other = self.win._safari_controller39
        self.assertTrue(other.toggle.isChecked())
        self.assertEqual(other.mode, "bookmarks")
        self.assertEqual(other.width, 272)

    def test_closing_sidebar_preserves_existing_browser_tabs(self):
        controller = self._open()
        self.assertEqual(self.win.tabs.count(), 2)
        controller.toggle.click()
        self.app.processEvents()
        self.assertFalse(controller.side.isVisible())
        self.assertEqual(controller.settings.value("ui/macSafariSidebar39/open"), False)
        self.assertEqual(self.win.tabs.count(), 2)


if __name__ == "__main__":
    unittest.main()
