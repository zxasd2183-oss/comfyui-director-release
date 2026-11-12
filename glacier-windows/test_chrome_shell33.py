"""Actual Qt geometry, behavior and menu preservation for Chrome shell 33."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu, QTabBar, QToolButton, QPushButton
from glacier_chrome_shell33 import GlacierChromeShell33, CHROME_SHELL_QSS33
from test_desktop_ui32 import BrowserShellStub


class ChromeShell33Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["Glacier-33", "-platform", "offscreen"])

    def setUp(self):
        self.window = BrowserShellStub()
        self.window.more.setMenu(QMenu(self.window.more))
        strip = self.window.chrome_tab14.parentWidget()
        self.new_tab_button = QPushButton("+", strip)
        self.new_tab_clicks = 0
        self.new_tab_button.clicked.connect(self._clicked_new_tab)
        strip.layout().addWidget(self.new_tab_button)
        GlacierChromeShell33.setup_chrome_shell33(self.window)

    def _clicked_new_tab(self):
        self.new_tab_clicks += 1

    def tearDown(self):
        self.window.close()

    def test_real_address_group_and_compact_sizes(self):
        w = self.window
        shell = w._chrome_omnibox_shell33
        self.assertEqual(shell.objectName(), "GlacierOmniboxShell33")
        self.assertEqual(w._navigation32.itemAt(3).widget(), shell)
        self.assertEqual([shell.layout().itemAt(i).widget() for i in range(3)],
                         [w._site_button30, w.address, w.bookmark_button])
        self.assertEqual(w._navigation_surface32.height(), 50)
        self.assertEqual(w.chrome_tab14.parentWidget().height(), 44)
        self.assertEqual(shell.height(), 38)
        self.assertLessEqual(w.address.maximumHeight(), 35)
        self.assertEqual(w.address.placeholderText(), "搜索或输入网址")
        self.assertFalse(w.tabs.tabBar().isVisible())
        plus = self.new_tab_button
        self.assertEqual(plus.objectName(), "GlacierNewTab34")
        self.assertEqual((plus.width(), plus.height()), (32, 32))
        self.assertEqual(plus.text(), "")
        self.assertFalse(plus.icon().isNull())
        self.assertEqual(plus.accessibleName(), "新建标签页")
        plus.click()
        self.assertEqual(self.new_tab_clicks, 1)
        self.assertIn("GlacierNewTab34", CHROME_SHELL_QSS33)
        self.assertIn("min-width: 160px", CHROME_SHELL_QSS33)

    def test_focus_and_menu_visual_state_are_functional(self):
        w = self.window
        from PySide6.QtCore import QEvent
        shell = w._chrome_omnibox_shell33
        w._omnibox_focus_guard33.eventFilter(w.address, QEvent(QEvent.Type.FocusIn))
        self.assertTrue(shell.property("glacierFocus"))
        w._omnibox_focus_guard33.eventFilter(w.address, QEvent(QEvent.Type.FocusOut))
        self.assertFalse(shell.property("glacierFocus"))
        self.assertIn("QMenu::item:selected", CHROME_SHELL_QSS33)
        self.assertNotIn(":focus-within", CHROME_SHELL_QSS33)

    def test_tab_close_icon_is_neutral_not_native_red_tile(self):
        bar = self.window.chrome_tab14
        bar.setTabsClosable(True)
        bar.addTab("A real new tab")
        self.window._polish_close_buttons33()
        button = bar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        self.assertIsNotNone(button)
        self.assertIsInstance(button, QToolButton)
        self.assertEqual(button.objectName(), "GlacierTabClose33")
        self.assertFalse(button.icon().isNull())
        self.assertEqual(button.width(), 20)
        self.assertEqual(button.toolTip(), "关闭标签")
        clicked = []
        bar.tabCloseRequested.connect(clicked.append)
        button.click()
        self.assertEqual(clicked, [0])
        self.window._polish_close_buttons33()
        self.assertIs(bar.tabButton(0, QTabBar.ButtonPosition.RightSide), button)
        button.click()
        self.assertEqual(clicked, [0, 0])
        self.assertEqual(self.window.more.popupMode(),
                         QToolButton.ToolButtonPopupMode.InstantPopup)
        self.assertIn("::menu-indicator", CHROME_SHELL_QSS33)

    def test_previous_handlers_keep_their_original_connections(self):
        w = self.window
        self.assertFalse(w.more.icon().isNull())
        self.assertFalse(w.downloads.icon().isNull())
        self.assertFalse(w._hub_button20.icon().isNull())
        self.assertFalse(w._site_button30.icon().isNull())
        self.assertFalse(w._account_button26.icon().isNull())
        self.assertEqual(w._account_button26.width(), 36)
        self.assertEqual(w._account_button26.accessibleName(), "Glacier 账号中心")
        self.assertFalse(w.windowIcon().isNull())
        self.assertIsNotNone(w._utility_shelf32)
        # Original utility button remains wired to the shelf.
        w.more.menu().aboutToShow.emit()
        actions = [a for a in w.more.menu().actions()
                   if a.objectName() == "GlacierUtilityMenuAction33"]
        self.assertEqual(len(actions), 1)
        self.assertTrue(w._utility_shelf32.isHidden())
        actions[0].trigger()
        self.assertFalse(w._utility_shelf32.isHidden())
        w.legacy.click()
        self.assertEqual(w.clicks, 1)
        w.more.menu().aboutToShow.emit()
        self.assertEqual(len([a for a in w.more.menu().actions()
                              if a.objectName() == "GlacierUtilityMenuAction33"]), 1)

    def test_styling_is_presentation_only_and_double_setup_is_rejected(self):
        self.assertIn("GlacierOmniboxShell33", CHROME_SHELL_QSS33)
        self.assertIn("#f1f3f5", CHROME_SHELL_QSS33)
        for forbidden in ("socks5://", "QNetworkProxy", "dpapi", "requests.get"):
            self.assertNotIn(forbidden, CHROME_SHELL_QSS33)
        with self.assertRaisesRegex(RuntimeError, "only be installed once"):
            GlacierChromeShell33.setup_chrome_shell33(self.window)


if __name__ == "__main__":
    unittest.main()
