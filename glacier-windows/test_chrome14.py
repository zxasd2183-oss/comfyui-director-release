"""Windows/Qt smoke checks: external top tabs mirror the real browser tabs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from PySide6.QtWidgets import QApplication, QTabBar, QTabWidget, QWidget
from chrome14 import GlacierChrome14, chrome_home14


class Host(GlacierChrome14):
    pass


class Chrome14Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_browser(self):
        h = Host()
        h.tabs = QTabWidget()
        h.chrome_tab14 = QTabBar()
        return h

    def test_tabs_count_title_and_current(self):
        h = self.make_browser()
        h.tabs.addTab(QWidget(), 'Google')
        h.tabs.addTab(QWidget(), 'GitHub')
        h.refresh_tabs14()
        self.assertEqual(h.chrome_tab14.count(), 2)
        self.assertEqual(h.chrome_tab14.tabText(0), 'Google')
        h._switch_tab14(1)
        self.assertEqual(h.tabs.currentIndex(), 1)
        h.tabs.setTabText(1, 'Renamed')
        h.refresh_tabs14()
        self.assertEqual(h.chrome_tab14.tabText(1), 'Renamed')
        h.tabs.removeTab(0)
        h.refresh_tabs14()
        self.assertEqual(h.chrome_tab14.count(), 1)

    def test_drag_reorders_real_tabs(self):
        h = self.make_browser()
        a, b = QWidget(), QWidget()
        h.tabs.addTab(a, 'A')
        h.tabs.addTab(b, 'B')
        h.refresh_tabs14()
        h._tab_moved14(0, 1)
        self.assertIs(h.tabs.widget(1), a)

    def test_new_tab_is_local_and_uses_glacier_brand(self):
        page = chrome_home14()
        self.assertIn('Glacier Browser', page)
        self.assertIn('name="q"', page)
        self.assertNotIn('<script', page.lower())


if __name__ == '__main__':
    unittest.main()
