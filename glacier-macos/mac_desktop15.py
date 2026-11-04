"""Glacier Browser v0.15: macOS-native desktop polish.

UI and keyboard shortcuts only. Networking, credentials, proxy fail-closed
behavior, and signed update verification remain in the existing modules.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu

from mac_update_core import CURRENT_VERSION


GLACIER_MAC_QSS15 = """
QMainWindow, QWidget {
    font-family: -apple-system, 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', sans-serif;
    color: #2b5064;
}
QWidget#GlacierTabStrip14 {
    background: #e9f5fc;
    border-bottom: 1px solid #cce4f2;
}
QTabBar#GlacierExternalTabs14::tab {
    background: #d8ebf7;
    border: 1px solid #c3e0f0;
    border-bottom: none;
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
    min-height: 34px;
    margin-right: 4px;
    padding: 2px 14px;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: white;
    color: #24536e;
    border-color: #b9d9eb;
}
QLineEdit#GlacierOmnibox14 {
    border-radius: 17px;
    background: #f0f8fd;
    border: 1px solid #d8eaf4;
    selection-background-color: #a6d8f0;
}
QLineEdit#GlacierOmnibox14:focus {
    background: #ffffff;
    border: 1px solid #6eb5d9;
}
QPushButton#GlacierUpdate14 {
    border: 1px solid #c2e1f1;
    background: #e8f6ff;
    color: #2a7297;
}
QMenu { font-family: -apple-system, 'PingFang SC', sans-serif; }
"""


class MacDesktop15:
    """Desktop behavior layered onto the v0.14 tab model, without replacing it."""

    def _build_menu14(self, menu: QMenu):
        def add(label, callback):
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False: callback())
            return action

        add("新建标签页                 ⌘T", self.new_tab)
        add("重新打开关闭的标签      ⇧⌘T", self.reopen_closed_tab15)
        add("新建窗口                     ⌘N", lambda: self.open_satellite(private=False))
        add("新建无痕窗口             ⇧⌘N", lambda: self.open_satellite(private=True))
        menu.addSeparator()
        add("收藏此页面                  ⌘D", self.toggle_bookmark)
        menu.addMenu(self.bookmarks_menu)
        add("历史记录                      ⌘Y", self.show_history)
        add("下载内容                      ⌘J", self.show_downloads)
        add("在网页中查找               ⌘F", self.open_find13)
        menu.addSeparator()
        add("检测 VLESS 连接", self.start_connection_check)
        add("浏览器设置", self.open_settings)
        add("关于 · 检查更新", self.update_manager.show_dialog)

    def setup_desktop15(self):
        self._recently_closed15 = []
        self._desktop15_shortcuts = []
        self.setWindowTitle(f"❄ Glacier Browser · macOS v{CURRENT_VERSION}")
        self.setStyleSheet(self.styleSheet() + "\n" + GLACIER_MAC_QSS15)
        self.chrome_tab14.setMinimumHeight(39)
        self.address.setToolTip("输入网址或搜索 · ⌘L")
        self._mac_update_button.setToolTip("检查 Glacier Browser 更新")

        shortcuts = {
            "Meta+L": lambda: self.address.setFocus(),
            "Meta+T": self.new_tab,
            "Meta+W": lambda: self.close_tab(self.tabs.currentIndex()),
            "Meta+R": self.reload_current15,
            "Meta+Shift+T": self.reopen_closed_tab15,
            "Meta+N": lambda: self.open_satellite(private=False),
            "Meta+Shift+N": lambda: self.open_satellite(private=True),
            "Meta+D": self.toggle_bookmark,
            "Meta+F": self.open_find13,
            "Meta+J": self.show_downloads,
            "Meta+Y": self.show_history,
        }
        for index in range(1, 9):
            shortcuts[f"Meta+{index}"] = (
                lambda i=index - 1: self.select_tab15(i)
            )
        shortcuts["Meta+9"] = lambda: self.select_tab15(self.tabs.count() - 1)
        for key, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._desktop15_shortcuts.append(shortcut)

        # This supplements existing debounced session saves with periodic
        # snapshots, reducing loss after a process crash without changing
        # the established encrypted on-disk session format.
        self._autosave_timer15 = QTimer(self)
        self._autosave_timer15.setInterval(45_000)
        self._autosave_timer15.timeout.connect(self._autosave_session15)
        self._autosave_timer15.start()

    def select_tab15(self, index):
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def reload_current15(self):
        page = self.current()
        if page is not None:
            page.reload()

    def remember_recent15(self, url):
        # Never reopen internal pages, file URLs, scripts, or VLESS links.
        if not isinstance(url, str):
            return
        parsed = QUrl(url)
        if not parsed.isValid() or parsed.scheme().lower() not in ("http", "https") or not parsed.host():
            return
        recent = getattr(self, "_recently_closed15", None)
        if recent is None:
            return
        if not recent or recent[-1] != url:
            recent.append(url)
            del recent[:-20]

    def reopen_closed_tab15(self):
        recent = getattr(self, "_recently_closed15", [])
        if not recent:
            self.statusBar().showMessage("没有可重新打开的标签页", 2500)
            return
        url = recent.pop()
        view = self.new_tab()
        if view is not None:
            view.setUrl(QUrl(url))

    def _autosave_session15(self):
        if self.tabs.count():
            try:
                self.save_session()
            except Exception:
                # Do not disclose potentially sensitive URLs or Keychain errors.
                self.statusBar().showMessage("自动保存会话失败，请检查本机钥匙串", 6000)
