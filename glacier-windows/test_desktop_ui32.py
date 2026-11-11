"""Functional/geometry regressions for the ACTUAL shared Chrome-style shell."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,QFrame,QHBoxLayout,QLabel,QLineEdit,QMainWindow,
    QPushButton,QTabBar,QTabWidget,QToolButton,QVBoxLayout,QWidget,
)
from glacier_desktop_ui32 import GlacierDesktopUI32,nav_icon32,CHROME_DESKTOP_QSS32

class BrowserShellStub(GlacierDesktopUI32,QMainWindow):
    def __init__(self):
        super().__init__()
        root=QWidget(self)
        self.setCentralWidget(root)
        self.column=QVBoxLayout(root)
        strip=QWidget(root)
        strip.setObjectName("GlacierTabStrip14")
        strip_row=QHBoxLayout(strip)
        strip_row.addWidget(QLabel("❄",strip))
        self.chrome_tab14=QTabBar(strip)
        self.chrome_tab14.setObjectName("GlacierExternalTabs14")
        strip_row.addWidget(self.chrome_tab14)
        self.column.addWidget(strip)
        self.old_nav=QHBoxLayout()
        self.column.addLayout(self.old_nav)
        self.back=QPushButton("←",self)
        self.forward=QPushButton("→",self)
        self.reload=QPushButton("↻",self)
        self.old_add=QPushButton("＋",self)
        self._site_button30=QToolButton(self)
        self._site_button30.setObjectName("GlacierSiteInfo30")
        self.address=QLineEdit(self)
        self.bookmark_button=QPushButton("☆",self)
        self.bookmark_button.setObjectName("GlacierBookmark14")
        self.downloads=QToolButton(self)
        self.downloads.setObjectName("GlacierDownloads14")
        self._hub_button20=QToolButton(self)
        self._hub_button20.setObjectName("GlacierHub20")
        self.proxy_label=QPushButton("● 本地 VLESS",self)
        self.proxy_label.setObjectName("GlacierProxyHealth29")
        self._account_button26=QPushButton("登录 Glacier",self)
        self._account_button26.setObjectName("GlacierAccount26")
        self.more=QToolButton(self)
        self.more.setObjectName("GlacierMore14")
        self.legacy=QPushButton("旧版扩展功能",self)
        self.clicks=0
        self.legacy.clicked.connect(lambda:self._count())
        self.hidden_legacy=QPushButton("隐藏的测试按钮",self)
        for w in (
            self.back,self.forward,self.reload,self.old_add,
            self.address,self.legacy,self._site_button30,
            self.bookmark_button,self.downloads,self._hub_button20,
            self.proxy_label,self._account_button26,self.more,
            self.hidden_legacy,
        ):
            self.old_nav.addWidget(w)
        self.old_add.hide()
        self.hidden_legacy.hide()
        self.tabs=QTabWidget(self)
        self.tabs.addTab(QWidget(),"Example")
        self.column.addWidget(self.tabs)
        self.setup_desktop_ui32(self.column,self.old_nav)
    def _count(self):
        self.clicks+=1

class ChromeDesktop32Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication(["glacier-32","-platform","offscreen"])
    def setUp(self):
        self.window=BrowserShellStub()
    def tearDown(self):
        self.window.close()
    def test_real_two_row_layout_and_single_visible_external_tabs(self):
        w=self.window
        self.assertEqual(w.centralWidget().layout().contentsMargins().left(),0)
        self.assertEqual(w._navigation_surface32.objectName(),"GlacierNavigation32")
        self.assertEqual(w.centralWidget().layout().itemAt(1).widget(),w._navigation_surface32)
        self.assertTrue(w.tabs.tabBar().isHidden())
        self.assertEqual(w.chrome_tab14.objectName(),"GlacierExternalTabs14")
        self.assertIn("min-height: 42px",w.styleSheet())
    def test_address_centered_and_primary_actions_preserved(self):
        w=self.window
        visible=[w._navigation32.itemAt(i).widget() for i in range(w._navigation32.count())]
        self.assertEqual(visible[0:5],[w.back,w.forward,w.reload,w._site_button30,w.address])
        self.assertLess(visible.index(w.address),visible.index(w.bookmark_button))
        self.assertLess(visible.index(w._account_button26),visible.index(w.more))
        self.assertTrue(w.address.sizePolicy().horizontalPolicy().name=="Expanding")
        for button in (w.back,w.forward,w.reload):
            self.assertFalse(button.icon().isNull())
        self.assertEqual(w.back.text(),"")
        self.assertEqual(w.reload.toolTip(),"重新加载 (Ctrl+R)")
    def test_previous_extensions_stay_accessible_but_not_crowding(self):
        w=self.window
        self.assertTrue(w._utility_shelf32.isHidden())
        self.assertEqual(w._utility_legacy32,(w.legacy,))
        self.assertFalse(w._utility_legacy32[0] in
                         [w._navigation32.itemAt(i).widget() for i in range(w._navigation32.count())])
        w._utility_toggle32.setChecked(True)
        self.assertFalse(w._utility_shelf32.isHidden())
        w.legacy.click()
        self.assertEqual(w.clicks,1)
        self.assertTrue(w.old_add.isHidden())
        self.assertTrue(w.hidden_legacy.isHidden())
        w._utility_toggle32.setChecked(False)
        self.assertTrue(w._utility_shelf32.isHidden())
    def test_prevents_duplicate_installation(self):
        with self.assertRaisesRegex(RuntimeError,"only be installed once"):
            self.window.setup_desktop_ui32(self.window.column,self.window.old_nav)
    def test_theme_is_bright_and_does_not_touch_networking(self):
        self.assertIn("#ffffff",CHROME_DESKTOP_QSS32)
        self.assertIn("GlacierOmnibox14",CHROME_DESKTOP_QSS32)
        for excluded in ("socks5","QNetworkProxy","VLESS","requests.get","QWebEngineProfile"):
            self.assertNotIn(excluded,CHROME_DESKTOP_QSS32)

if __name__ == "__main__":
    unittest.main()
