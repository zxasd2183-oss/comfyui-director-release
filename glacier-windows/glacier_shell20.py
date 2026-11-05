"""Glacier v0.20: unified light Chrome-like desktop shell (Windows/macOS).

UI-only module. Existing proxy, session/profile, bookmarks, update verification
and downloads remain the original implementations. The new hub exposes existing
controls without adding extra toolbar clutter or collecting user data.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QTabBar,
    QToolButton, QWidget,
)


GLACIER_SHELL_QSS20 = """
QMainWindow {
    background: #ffffff;
    color: #252e39;
}
QWidget#GlacierTabStrip14 {
    background: #eef1f5;
    border: none;
    border-bottom: 1px solid #e2e7ed;
}
QLabel#GlacierBrand14 {
    background: transparent;
    color: #477893;
    font-size: 17px;
    font-weight: 600;
    padding-left: 3px;
    padding-right: 7px;
}
QTabBar#GlacierExternalTabs14 {
    background: transparent;
    border: none;
}
QTabBar#GlacierExternalTabs14::tab {
    background: #e7eaee;
    color: #555e68;
    min-width: 108px;
    max-width: 212px;
    min-height: 30px;
    padding: 1px 14px 0px 14px;
    margin-top: 4px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-bottom: 0px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: #ffffff;
    color: #222e3b;
    border-color: #dfe5eb;
    font-weight: 600;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
    background: #f5f7fa;
    color: #2b4152;
}
QToolButton#GlacierAddTab14 {
    color: #4c5e6d;
    background: transparent;
    border: none;
    border-radius: 17px;
    font-size: 20px;
    padding: 3px;
    min-width: 29px;
    min-height: 29px;
    max-width: 35px;
}
QToolButton#GlacierAddTab14:hover {
    background: #dbe3eb;
}
QLineEdit#GlacierOmnibox14 {
    background: #f1f3f6;
    border: 1px solid #e6e9ee;
    border-radius: 19px;
    color: #233341;
    font-size: 13px;
    padding: 7px 14px;
    selection-background-color: #bfdceb;
}
QLineEdit#GlacierOmnibox14:focus {
    background: #ffffff;
    border-color: #77a9c6;
}
QPushButton#GlacierNavButton20, QPushButton#GlacierBookmark14,
QToolButton#GlacierDownloads14, QToolButton#GlacierHub20,
QToolButton#GlacierMore14 {
    background: transparent;
    color: #4b5d6b;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 4px 6px;
    min-width: 26px;
    max-width: 38px;
    min-height: 29px;
    font-size: 17px;
}
QPushButton#GlacierNavButton20:hover, QPushButton#GlacierBookmark14:hover,
QToolButton#GlacierDownloads14:hover, QToolButton#GlacierHub20:hover,
QToolButton#GlacierMore14:hover {
    background: #eef3f7;
}
QToolButton#GlacierHub20 {
    color: #42738f;
    font-size: 18px;
}
QMenu {
    background: #ffffff;
    color: #253848;
    border: 1px solid #e2e8ee;
    padding: 5px;
    min-width: 196px;
}
QMenu::item {
    padding: 8px 25px;
    border-radius: 6px;
}
QMenu::item:selected {
    color: #245875;
    background: #ecf4f9;
}
QMenu::separator {
    background: #ebeff3;
    height: 1px;
    margin: 5px 10px;
}
QTabWidget::pane {
    background: #ffffff;
    border: 0px;
}
QStatusBar {
    background: #fbfcfe;
    color: #657b8b;
    border-top: 1px solid #eef1f5;
}
"""


def glacier_home20():
    """Beautiful offline HTML new tab page, no script, tracking or remote assets."""
    return """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Glacier · 新标签页</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:
  radial-gradient(ellipse 58% 40% at 80% -5%,#e6f2f8 0%,transparent 100%),
  linear-gradient(180deg,#f8fafc 0%,#fff 72%);
  color:#273849;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",
  "Microsoft YaHei UI",sans-serif}
header{margin:0 auto;max-width:1080px;padding:36px 36px 0;display:flex;
  justify-content:space-between;align-items:center}
.brand{font-size:13px;letter-spacing:.13em;font-weight:700;color:#3b7899}
.hint{color:#91a1b1;font-size:12px}
main{max-width:700px;margin:clamp(86px,17vh,178px) auto 0;padding:0 26px}
h1{font-size:clamp(30px,4.3vw,42px);letter-spacing:-1.4px;font-weight:600;
  margin:0 0 12px;color:#233b4c}
.subtitle{margin:0 0 32px;color:#788d9d;font-size:15px}
.search{display:flex;align-items:center;gap:12px;min-height:60px;padding:0 20px;
  background:#fff;border:1px solid #e2e9f0;border-radius:16px;
  box-shadow:0 12px 32px #385d7510}
.search:focus-within{border-color:#94bfd7;box-shadow:0 12px 32px #477d9c1c}
.glass{font-size:22px;color:#7d9bab}
input{border:0;outline:0;min-width:0;flex:1;background:transparent;
  color:#283d4b;font:15px inherit}
.links{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  gap:12px;margin-top:30px}
a{color:inherit;text-decoration:none}
.link{min-height:94px;border:1px solid #ecf0f4;border-radius:13px;background:#fff;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:9px;color:#546d7f;font-size:13px;transition:background .13s}
.link:hover{background:#f0f7fb;border-color:#d5e5ee}
.mark{display:grid;place-items:center;width:32px;height:32px;border-radius:10px;
  background:#eaf3f8;color:#377da3;font-size:14px;font-weight:700}
footer{margin-top:34px;text-align:center;color:#a4b2be;font-size:12px}
@media(max-width:540px){header{padding:22px 22px 0}
main{margin-top:12vh}.links{grid-template-columns:repeat(2,1fr)}
.hint{display:none}}
</style></head><body>
<header><div class="brand">❄ GLACIER</div><span class="hint">专注浏览 · 轻盈自在</span></header>
<main><h1>从这里，开启新的一页。</h1>
<p class="subtitle">简洁、私密、专注于你想探索的内容。</p>
<form class="search" action="https://www.google.com/search" method="get">
<span class="glass" aria-hidden="true">⌕</span>
<input name="q" autofocus autocomplete="off" placeholder="搜索网络..."
 aria-label="使用 Google 搜索">
</form>
<div class="links">
<a class="link" href="https://www.google.com"><span class="mark">G</span>Google</a>
<a class="link" href="https://www.youtube.com"><span class="mark">▶</span>YouTube</a>
<a class="link" href="https://github.com"><span class="mark">GH</span>GitHub</a>
<a class="link" href="https://chatgpt.com"><span class="mark">AI</span>ChatGPT</a>
</div>
<footer>Glacier Browser · 新标签页</footer>
</main></body></html>"""


class GlacierShell20:
    """A single compact tool hub on top of the unchanged functional modules."""

    def home_markup(self):
        return glacier_home20()

    def setup_shell20(self, nav):
        self.address.setObjectName("GlacierOmnibox14")
        self.address.setPlaceholderText("搜索或输入网址")
        self.address.setMinimumHeight(39)

        # Leave the actual page ownership and tab ordering in QTabWidget.
        self.chrome_tab14.setElideMode(Qt.TextElideMode.ElideRight)
        self.chrome_tab14.setUsesScrollButtons(True)
        self.chrome_tab14.setExpanding(False)
        self.chrome_tab14.setIconSize(QSize(16, 16))

        tab_strip = self.chrome_tab14.parentWidget()
        if tab_strip is not None and isinstance(tab_strip.layout(), QHBoxLayout):
            row = tab_strip.layout()
            row.setContentsMargins(13, 5, 12, 0)
            row.setSpacing(4)
            for n in range(row.count()):
                w = row.itemAt(n).widget()
                if isinstance(w, QLabel) and w.objectName() == "GlacierBrand14":
                    w.setText("❄")
                    w.setToolTip("Glacier Browser")

        # These post-v0.14 buttons currently stack up in the navigation bar.
        # Keep their menus/handlers alive, but expose them through one hub.
        for attr in (
            "_zoom_button16", "_workspace_button17", "_group_button17",
            "_downloads_button17", "_tab_search_button16",
        ):
            w = getattr(self, attr, None)
            if w is not None:
                w.hide()

        hub = QToolButton(self)
        hub.setObjectName("GlacierHub20")
        hub.setText("▦")
        hub.setToolTip("工作区、标签分组、搜索、缩放与下载")
        hub.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        hub_menu = QMenu(hub)
        hub_menu.aboutToShow.connect(self._build_hub_menu20)
        hub.setMenu(hub_menu)
        self._hub_button20 = hub
        self._hub_menu20 = hub_menu

        # Reorder the toolbar into a familiar browser layout.
        # Existing actions remain connected to their original implementations.
        downloads = self.findChild(QToolButton, "GlacierDownloads14")
        more = self.findChild(QToolButton, "GlacierMore14")
        for index in range(nav.count()):
            item = nav.itemAt(index)
            w = item.widget() if item else None
            if isinstance(w, QPushButton) and w.text() in ("←", "→", "↻"):
                w.setObjectName("GlacierNavButton20")
                w.setMinimumWidth(32)
                w.setMaximumWidth(37)
                w.show()
        self.bookmark_button.setObjectName("GlacierBookmark14")
        keep = [self.bookmark_button, downloads, hub, more]
        for w in keep:
            if w is not None:
                nav.removeWidget(w)
                nav.addWidget(w)
                w.show()

        if downloads is not None:
            downloads.setText("↓")
            downloads.setToolTip("下载中心 (Ctrl+J)")
            # Keep the v0.19 download center, not the legacy downloads dialog.
            if hasattr(self, "show_download_center17"):
                try:
                    downloads.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                downloads.clicked.connect(self.show_download_center17)

        if more is not None:
            more.setText("⋮")
            more.setToolTip("Glacier 主菜单")

        # The updater remains available from the main menu without taking
        # permanent space. There is no silent update installation.
        update = getattr(getattr(self, "update_manager", None), "button", None)
        if update is not None:
            update.hide()

        # The legacy tab context menu and new v0.19 tab context menu were
        # both connected; remove only the obsolete handler.
        legacy = getattr(self, "_context14", None)
        if callable(legacy):
            try:
                self.chrome_tab14.customContextMenuRequested.disconnect(legacy)
            except (RuntimeError, TypeError):
                pass

        nav.setContentsMargins(13, 6, 13, 7)
        nav.setSpacing(5)
        self.setStyleSheet(self.styleSheet() + "\n" + GLACIER_SHELL_QSS20)

    def _build_hub_menu20(self):
        menu = self._hub_menu20
        menu.clear()

        workspace = getattr(self, "_workspace_menu17", None)
        groups = getattr(self, "_group_menu17", None)
        if isinstance(workspace, QMenu):
            workspace.setTitle("工作区")
            menu.addMenu(workspace)
        if isinstance(groups, QMenu):
            groups.setTitle("标签分组")
            menu.addMenu(groups)
        if workspace is not None or groups is not None:
            menu.addSeparator()

        finder = getattr(self, "show_tab_search16", None)
        if callable(finder):
            menu.addAction("搜索标签页", finder)
        zoom = getattr(getattr(self, "_zoom_button16", None), "menu", None)
        zoom_menu = zoom() if callable(zoom) else None
        if isinstance(zoom_menu, QMenu):
            zoom_menu.setTitle("页面缩放")
            menu.addMenu(zoom_menu)

        downloads = getattr(self, "show_download_center17", None)
        if callable(downloads):
            menu.addSeparator()
            menu.addAction("下载中心", downloads)
        menu.addSeparator()
        updater = getattr(getattr(self, "update_manager", None), "show_dialog", None)
        if callable(updater):
            menu.addAction("检查更新", updater)
        settings = getattr(self, "open_settings", None)
        if callable(settings):
            menu.addAction("浏览器设置", settings)
