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
    """Script-free, offline Chromium-style start page with Glacier branding."""
    return """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Glacier · 新标签页</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:#fff;color:#202124;
  font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",
  "Microsoft YaHei UI",sans-serif}
.top{position:absolute;top:0;right:0;display:flex;align-items:center;
  gap:22px;padding:18px 29px;color:#3c4043;font-size:13px}
.top a{text-decoration:none;color:inherit}
.top a:hover{text-decoration:underline}
.top .about{display:grid;place-items:center;width:32px;height:32px;
  border-radius:50%;background:#e8f0fe;color:#3565a0;font-size:14px;
  font-weight:700;text-decoration:none}
main{width:min(100%,720px);margin:0 auto;
  padding:clamp(120px,19vh,200px) 24px 40px;text-align:center}
.wordmark{margin:0 auto 36px;display:flex;align-items:center;
  justify-content:center;gap:13px;letter-spacing:-2px;
  font-size:clamp(43px,6vw,67px);font-weight:550;line-height:1.15;
  color:#263c50}
.symbol{display:grid;place-items:center;width:58px;height:58px;
  border-radius:20px;background:linear-gradient(145deg,#dceefb,#f2f8ff);
  box-shadow:inset 0 1px 0 #fff;color:#528db5;
  font-size:37px;letter-spacing:0;font-weight:400}
.search{height:49px;max-width:584px;margin:0 auto;
  display:flex;align-items:center;gap:17px;padding:0 18px;
  border:1px solid #dfe1e5;border-radius:26px;
  background:#fff;box-shadow:0 1px 6px #20212417}
.search:hover,.search:focus-within{
  border-color:transparent;box-shadow:0 1px 7px #20212433}
.magnify{display:block;position:relative;width:15px;height:15px;
  flex:0 0 15px;border:2px solid #80868b;border-radius:50%}
.magnify:after{content:"";position:absolute;right:-6px;bottom:-3px;
  width:7px;height:2px;background:#80868b;transform:rotate(48deg);
  border-radius:1px}
input{width:100%;min-width:0;height:100%;padding:0;margin:0;
  color:#202124;outline:0;border:0;background:transparent;
  font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",
  "Microsoft YaHei UI",sans-serif}
input::placeholder{color:#80868b;opacity:1}
.shortcuts{margin:30px auto 0;display:grid;grid-template-columns:
  repeat(4,112px);gap:4px;justify-content:center;max-width:580px}
a{color:inherit;text-decoration:none}
.shortcut{display:flex;flex-direction:column;align-items:center;
  gap:12px;min-height:112px;padding:15px 4px 10px;
  border-radius:5px;color:#3c4043;font-size:12px;
  transition:background .12s ease}
.shortcut:hover,.shortcut:focus-visible{background:#f1f3f4;outline:0}
.tile{display:grid;place-items:center;width:47px;height:47px;
  border-radius:50%;background:#f1f3f4;color:#5f6368;
  font-size:16px;font-weight:650}
.tile.google{color:#4285f4;background:#eaf1fd}
.tile.youtube{color:#e94235;background:#fcefed}
.tile.github{color:#30363d;background:#eceef0}
.tile.chatgpt{color:#247d69;background:#e7f5f0}
.foot{margin-top:30px;color:#9aa0a6;font-size:11px;
  letter-spacing:.015em}
@media(max-width:520px){
  .top{padding:14px 17px;gap:14px}
  main{padding:clamp(125px,22vh,190px) 14px 24px}
  .wordmark{font-size:45px;gap:9px}
  .symbol{width:45px;height:45px;font-size:29px;border-radius:15px}
  .shortcuts{grid-template-columns:repeat(4,minmax(0,1fr));gap:0}
  .shortcut{font-size:11px}
}
</style></head><body>
<nav class="top" aria-label="快速导航">
<a href="https://mail.google.com">Gmail</a>
<a href="https://www.google.com/imghp">图片</a>
<a class="about" href="https://www.google.com" aria-label="Google">G</a>
</nav>
<main>
<div class="wordmark"><span class="symbol" aria-hidden="true">❄</span>Glacier</div>
<form class="search" action="https://www.google.com/search" method="get"
 aria-label="使用 Google 搜索">
<span class="magnify" aria-hidden="true"></span>
<input name="q" autocomplete="off" placeholder="在 Google 中搜索或输入网址"
 aria-label="搜索网络">
</form>
<section class="shortcuts" aria-label="快捷访问">
<a class="shortcut" href="https://www.google.com"><span class="tile google">G</span>Google</a>
<a class="shortcut" href="https://www.youtube.com"><span class="tile youtube">▶</span>YouTube</a>
<a class="shortcut" href="https://github.com"><span class="tile github">GH</span>GitHub</a>
<a class="shortcut" href="https://chatgpt.com"><span class="tile chatgpt">AI</span>ChatGPT</a>
</section>
<div class="foot">Glacier Browser · 新标签页</div>
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
        # Preview and formal update checks belong together in the main menu.
        # Avoid a second permanent navigation button crowding the omnibox.
        preview = getattr(self, "_preview_button25", None)
        if preview is not None:
            preview.hide()

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
        drag_diagnostic = getattr(self, "open_drag_diagnostic21", None)
        open_external = getattr(self, "open_in_system_browser21", None)
        if callable(drag_diagnostic) or callable(open_external):
            menu.addSeparator()
            if callable(drag_diagnostic):
                menu.addAction("网页拖动诊断（本地）", drag_diagnostic)
            if callable(open_external):
                menu.addAction("在系统浏览器打开当前页", open_external)
        menu.addSeparator()
        updater = getattr(getattr(self, "update_manager", None), "show_dialog", None)
        if callable(updater):
            menu.addAction("检查更新", updater)
        preview_check = getattr(self, "check_preview_updates25", None)
        if callable(preview_check):
            menu.addAction("检查 VPS 预览版更新", preview_check)
        center = getattr(self, "show_account_center26", None)
        if callable(center):
            menu.addAction("Glacier 账号中心", center)
        settings = getattr(self, "open_settings", None)
        if callable(settings):
            menu.addAction("浏览器设置", settings)
