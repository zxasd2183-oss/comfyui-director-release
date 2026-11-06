"""Glacier Browser v0.15 Windows desktop experience.

Parallels the Mac v0.15 feature set while retaining Windows DPAPI, VLESS
fail-closed routing and the Ed25519-signed updater unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu

from secure_update import CURRENT_VERSION


GLACIER_WINDOWS_QSS15 = """
QMainWindow, QWidget {
    font-family: 'Segoe UI', 'Microsoft YaHei UI', sans-serif;
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
    background: white;
    border: 1px solid #6eb5d9;
}
QPushButton#GlacierUpdate14 {
    border: 1px solid #c2e1f1;
    background: #e8f6ff;
    color: #2a7297;
}
"""


class WindowsDesktop15:
    """Mirrors Mac v0.15 shortcuts and recovery without changing networking."""

    def _build_menu14(self, menu: QMenu):
        def add(label, callback):
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False: callback())
            return action

        add("新建标签页                 Ctrl+T", self.new_tab)
        add("重新打开关闭的标签      Ctrl+Shift+T", self.reopen_closed_tab15)
        if callable(getattr(self, "show_tab_search16", None)):
            add("搜索标签页                  Ctrl+Shift+A", self.show_tab_search16)
        add("新建窗口                     Ctrl+N", lambda: self.open_satellite(private=False))
        add("新建无痕窗口             Ctrl+Shift+N", lambda: self.open_satellite(private=True))
        menu.addSeparator()
        add("收藏此页面                  Ctrl+D", self.toggle_bookmark)
        menu.addMenu(self.bookmarks_menu)
        add("历史记录                      Ctrl+H", self.show_history)
        add("下载中心                      Ctrl+J", lambda: self.show_download_center17() if hasattr(self, "show_download_center17") else self.show_downloads())
        add("在网页中查找               Ctrl+F", self.open_find13)
        menu.addSeparator()
        diagnostic = getattr(self, "open_drag_diagnostic21", None)
        external = getattr(self, "open_in_system_browser21", None)
        if callable(diagnostic):
            add("网页拖动诊断（本地）", diagnostic)
        if callable(external):
            add("在系统浏览器打开当前页", external)
        if callable(diagnostic) or callable(external):
            menu.addSeparator()
        if callable(getattr(self, "show_accounts22", None)):
            add("当前网站账号卡片", self.show_accounts22)
            add("添加网站账号卡片", self.add_account22)
            menu.addSeparator()
        add("检测 VLESS 连接", self.start_connection_check)
        add("浏览器设置", self.open_settings)
        add("关于 · 检查更新", self.update_manager.show_dialog)

    def setup_desktop15(self):
        self._recently_closed15 = []
        self._desktop15_shortcuts = []
        self.setWindowTitle(f"❄ Glacier Browser · Windows v{CURRENT_VERSION}")
        self.setStyleSheet(self.styleSheet() + "\n" + GLACIER_WINDOWS_QSS15)
        self.chrome_tab14.setMinimumHeight(39)
        self.address.setToolTip("输入网址或搜索 · Ctrl+L")
        self.update_manager.button.setToolTip("检查 Glacier Browser 更新")
        shortcuts = {
            "Ctrl+L": lambda: self.address.setFocus(),
            "Ctrl+T": self.new_tab,
            "Ctrl+W": lambda: self.close_tab(self.tabs.currentIndex()),
            "Ctrl+R": self.reload_current15,
            "Ctrl+Shift+T": self.reopen_closed_tab15,
            "Ctrl+N": lambda: self.open_satellite(private=False),
            "Ctrl+Shift+N": lambda: self.open_satellite(private=True),
            "Ctrl+D": lambda: self.toggle_bookmark(),
            "Ctrl+F": lambda: self.open_find13(),
            "Ctrl+J": lambda: self.show_download_center17() if hasattr(self, "show_download_center17") else self.show_downloads(),
            "Ctrl+H": lambda: self.show_history(),
        }
        for index in range(1, 9):
            shortcuts[f"Ctrl+{index}"] = (
                lambda i=index - 1: self.select_tab15(i)
            )
        shortcuts["Ctrl+9"] = lambda: self.select_tab15(self.tabs.count() - 1)
        for key, callback in shortcuts.items():
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._desktop15_shortcuts.append(shortcut)

        # The existing secure session serializer remains the only writer.
        self._autosave_timer15 = QTimer(self)
        self._autosave_timer15.setInterval(45_000)
        self._autosave_timer15.timeout.connect(self._autosave_session15)
        self._autosave_timer15.start()

    def select_tab15(self, index):
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    def reload_current15(self):
        view = self.current()
        if view is not None:
            view.reload()

    def remember_recent15(self, url):
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
                self.statusBar().showMessage("自动保存会话失败", 6000)
