"""Regression checks for the visible Chrome UI, site identity and quick links."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLineEdit, QMainWindow, QPushButton,
    QTabWidget, QWidget,
)
from glacier_chrome_ui30 import GlacierChromeUI30, new_tab_page30


class PageStub(QWidget):
    def __init__(self, url):
        super().__init__()
        self.link = QUrl(url)

    def url(self):
        return self.link


class Host(GlacierChromeUI30, QMainWindow):
    def __init__(self):
        super().__init__()
        root = QWidget(self)
        self.setCentralWidget(root)
        self.nav = QHBoxLayout(root)
        self.nav.addWidget(QPushButton("＋", self))
        self.address = QLineEdit(self)
        self.nav.addWidget(self.address)
        self.tabs = QTabWidget(self)
        self.page = PageStub("https://chatgpt.com/")
        self.tabs.addTab(self.page, "ChatGPT")
        self.clicked_site = None
        self.setup_ui30(self.nav)

    def current(self):
        return self.page

    def show_accounts22(self, site):
        self.clicked_site = site


class ChromeUI30Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["glacier-ui", "-platform", "offscreen"])

    def setUp(self):
        self.win = Host()

    def tearDown(self):
        self.win.close()

    def test_https_identity_opens_exact_site_vault(self):
        self.assertIn("chatgpt.com", self.win._site_button30.toolTip())
        self.win.open_site_info30()
        self.assertEqual(self.win.clicked_site, "chatgpt.com")

    def test_http_never_exposes_account_cards(self):
        self.win.page.link = QUrl("http://chatgpt.com/")
        self.win.update_site_info30()
        self.assertEqual(self.win._site_button30.text(), "!")
        self.assertEqual(self.win._current_site30(), "")

    def test_duplicate_new_tab_button_is_removed(self):
        self.assertTrue(self.win.nav.itemAt(0).widget().isHidden())
        self.assertEqual(self.win.address.objectName(), "GlacierOmnibox14")

    def test_release_notes_are_real_and_accessible(self):
        from PySide6.QtWidgets import QMenu
        import unittest.mock
        self.win._hub_menu20 = QMenu(self.win)
        with unittest.mock.patch.object(self.win, "open_release_notes30") as open_notes:
            self.win._build_hub_menu20()
            matches = [a for a in self.win._hub_menu20.actions()
                       if a.text() == "本版新增功能与更新说明"]
            self.assertEqual(len(matches), 1)
            matches[0].trigger()
            open_notes.assert_called_once_with()

    def test_gemini_diagnostic_action_is_in_hub(self):
        from PySide6.QtWidgets import QMenu
        from unittest.mock import Mock
        self.win._hub_menu20 = QMenu(self.win)
        self.win.start_gemini_diagnostic31 = Mock()
        self.win._build_hub_menu20()
        actions = [a for a in self.win._hub_menu20.actions()
                   if a.text() == "Gemini 连接诊断（VLESS HTTPS）"]
        self.assertEqual(len(actions), 1)
        actions[0].trigger()
        self.win.start_gemini_diagnostic31.assert_called_once_with()

    def test_home_is_visible_and_functional_without_remote_scripts(self):
        html = new_tab_page30()
        for site in ("chatgpt.com", "github.com", "mail.google.com",
                     "www.youtube.com", "www.google.com"):
            self.assertIn("https://" + site, html)
        self.assertIn('name="q"', html)
        self.assertIn("快捷访问", html)
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("http://", html.lower().replace('xmlns="http://www.w3.org/2000/svg"', ""))
        self.assertEqual(self.win.home_markup(), html)


if __name__ == "__main__":
    unittest.main()
