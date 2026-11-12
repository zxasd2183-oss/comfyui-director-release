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
    """Offline, script-free Glacier mountain landing page shared by both desktop platforms."""
    return """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>Glacier Browser · 新标签页</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
html{min-height:100%;background:#fafdff}
body{position:relative;min-height:100vh;margin:0;overflow-x:hidden;
  color:#253651;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",
  "Microsoft YaHei UI",sans-serif;
  background:radial-gradient(ellipse 64% 34% at 50% 19%,#eaf5ff 0%,#fff 83%)}
a{color:inherit;text-decoration:none}
.top{position:absolute;z-index:5;top:0;right:0;display:flex;align-items:center;
  gap:22px;padding:18px 26px;color:#424b58;font-size:12px}
.top>a:hover{text-decoration:underline}
.top .apps{display:grid;grid-template-columns:repeat(3,4px);gap:3px;padding:7px;
  border-radius:50%}
.top .apps i{width:4px;height:4px;border-radius:50%;background:#687488}
.top .apps:hover{background:#edf2f8}
.top .avatar{display:grid;place-items:center;width:32px;height:32px;
  border-radius:50%;background:#dceafa;color:#365a90;font-weight:650}
main{position:relative;z-index:2;width:min(100%,860px);margin:auto;
  padding:clamp(100px,18vh,172px) 22px 185px;text-align:center}
.wordmark{display:flex;align-items:center;justify-content:center;gap:11px;
  margin:0 auto 30px;font-size:clamp(31px,4.9vw,50px);line-height:1.05;
  letter-spacing:-1.7px;font-weight:650;color:#173258}
.wordmark em{font-style:normal;font-weight:400;color:#657da1}
.mountain-mark{width:clamp(60px,7vw,81px);height:auto;overflow:visible;flex:0 0 auto}
.search{display:flex;align-items:center;gap:13px;width:min(100%,640px);
  height:47px;margin:0 auto;padding:0 14px 0 18px;
  background:#fff;border:1px solid #e0e6ee;border-radius:26px;
  box-shadow:0 3px 13px #234b7214,0 1px 2px #234b720f;
  transition:box-shadow .15s,border-color .15s}
.search:hover,.search:focus-within{border-color:#cbdceb;
  box-shadow:0 4px 18px #2b6da126,0 1px 3px #234b7215}
.search svg{flex:0 0 auto;width:19px;height:19px;fill:none;stroke:#70809b;
  stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.search input{flex:1;min-width:0;height:100%;padding:0;border:0;outline:0;
  background:transparent;color:#253651;font:13px -apple-system,BlinkMacSystemFont,
  "Segoe UI","Microsoft YaHei UI",sans-serif}
.search input::placeholder{color:#919bad;opacity:1}
.search .search-label{padding:5px 9px;border-radius:12px;
  background:#eef5ff;color:#5281b5;font-size:11px;white-space:nowrap}
.actions{display:flex;gap:12px;justify-content:center;margin:17px auto 16px;
  flex-wrap:wrap}
.action{display:flex;align-items:center;justify-content:space-between;gap:16px;
  width:190px;min-height:47px;padding:9px 13px;border:1px solid #eef2ff;
  border-radius:14px;background:#f0f5ffbb;color:#254b86;text-align:left;
  transition:background .15s,transform .15s}
.action:hover,.action:focus-visible{background:#e4efff;transform:translateY(-1px)}
.action .symbol{display:grid;place-items:center;flex:0 0 auto;width:23px;height:23px;
  border-radius:8px;background:#ddebff;color:#2779df;font-size:18px}
.action .copy{flex:1;min-width:0}
.action strong{display:block;font-size:12px;font-weight:650}
.action small{display:block;margin-top:2px;color:#8293b0;font-size:10px}
.action .chev{color:#6784b0;font-size:16px}
.shortcuts{display:flex;justify-content:center;flex-wrap:wrap;gap:5px;
  max-width:770px;margin:0 auto}
.shortcut{display:flex;flex-direction:column;align-items:center;
  gap:8px;width:91px;min-height:88px;padding:9px 4px 7px;
  border-radius:12px;font-size:11px;color:#46556b}
.shortcut:hover,.shortcut:focus-visible{background:#edf4fbb8;outline:0}
.tile{display:grid;place-items:center;width:42px;height:42px;
  border-radius:50%;background:#f2f5fa;box-shadow:0 1px 4px #193d5e12;
  font-size:18px;font-weight:700}
.tile.gemini{color:#6686db;background:#f0f3ff}
.tile.github{color:#202b3d;background:#f0f1f5}
.tile.chatgpt{color:#326c5b;background:#eaf6f0}
.tile.claude{color:#c36b4d;background:#fff0e7}
.tile.minimax{color:#ed528a;background:#fff0f5}
.tile.shop{color:#df3444;background:#fff0ef}
.tile.docs{color:#4786e5;background:#eef5ff}
.shortcut .name{display:block;max-width:89px;overflow:hidden;
  white-space:nowrap;text-overflow:ellipsis}
.landscape{position:fixed;bottom:0;left:0;z-index:1;width:100%;height:clamp(100px,23vh,220px);
  pointer-events:none}
@media(max-width:660px){
  .top{padding:13px 16px;gap:15px}
  main{padding:clamp(98px,19vh,145px) 14px 160px}
  .wordmark{gap:6px;font-size:clamp(28px,6vw,39px);letter-spacing:-1.5px}
  .mountain-mark{width:57px}
  .action{width:173px}
  .shortcut{width:77px;font-size:10px}
}
@media(max-width:430px){
  main{padding-top:108px}
  .wordmark{font-size:29px}
  .mountain-mark{width:49px}
  .actions{gap:8px}.action{width:156px;padding:8px;gap:8px}
  .search .search-label{display:none}
  .shortcut{width:68px;min-height:82px}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<nav class="top" aria-label="Google 快速入口">
<a href="https://mail.google.com/">Gmail</a>
<a href="https://www.google.com/imghp">图片</a>
<a class="apps" href="https://www.google.com/intl/zh-CN/about/products/" aria-label="Google 应用">
<i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></a>
<a class="avatar" href="https://accounts.google.com/" aria-label="Google 账号">G</a>
</nav>
<main>
<div class="wordmark">
<svg class="mountain-mark" viewBox="0 0 100 70" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="冰川山峰标识">
<defs><linearGradient id="peak-blue" x1="0" y1="0" x2="1" y2="1">
<stop stop-color="#65d5fa"/><stop offset=".58" stop-color="#348ef7"/><stop offset="1" stop-color="#2564d8"/></linearGradient></defs>
<path d="M2 56 28 17l12 18L58 5l40 51-26-8-15-21-13 20-15-13-15 22Z" fill="url(#peak-blue)"/>
<path d="m28 17 12 18-8-3-5-7-8 17Z" fill="#d2f7ff"/>
<path d="m58 5 17 22-12-8-6 9-7-7Z" fill="#eefbff"/>
<path d="M2 61q22-10 45-5 25 5 51-2Q73 68 46 64 23 60 2 65Z" fill="#65bdea"/>
<path d="M10 68q28-10 50-5 17 4 34-1" fill="none" stroke="#2a8de4" stroke-width="3" stroke-linecap="round"/>
</svg>
<span>Glacier <em>Browser</em></span>
</div>
<form class="search" action="https://www.google.com/search" method="get" aria-label="使用 Google 搜索">
<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.7" cy="10.7" r="6.7"/><path d="m16 16 5 5"/></svg>
<input name="q" autocomplete="off" aria-label="搜索网络" placeholder="搜索 Google 或输入网址">
<span class="search-label">Google 搜索</span>
</form>
<section class="actions" aria-label="AI 快捷入口">
<a class="action" href="https://chatgpt.com/" title="前往 ChatGPT，非浏览器内置 AI 模式">
<span class="symbol">✦</span><span class="copy"><strong>开启 AI 助手</strong><small>前往 ChatGPT</small></span><span class="chev">›</span></a>
<a class="action" href="https://gemini.google.com/" title="前往 Gemini，非浏览器内置图片生成">
<span class="symbol">▧</span><span class="copy"><strong>创作图片</strong><small>前往 Gemini</small></span><span class="chev">›</span></a>
</section>
<section class="shortcuts" aria-label="快捷访问">
<a class="shortcut" href="https://gemini.google.com/"><span class="tile gemini">✦</span><span class="name">Gemini</span></a>
<a class="shortcut" href="https://github.com/"><span class="tile github">⌘</span><span class="name">GitHub</span></a>
<a class="shortcut" href="https://chatgpt.com/"><span class="tile chatgpt">◎</span><span class="name">ChatGPT</span></a>
<a class="shortcut" href="https://claude.ai/"><span class="tile claude">✳</span><span class="name">Claude</span></a>
<a class="shortcut" href="https://www.minimaxi.com/"><span class="tile minimax">≋</span><span class="name">MiniMax</span></a>
<a class="shortcut" href="https://www.jd.com/"><span class="tile shop">JD</span><span class="name">京东</span></a>
<a class="shortcut" href="https://docs.google.com/"><span class="tile docs">▤</span><span class="name">文档</span></a>
</section>
</main>
<svg class="landscape" viewBox="0 0 1440 230" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<defs><linearGradient id="sky-haze" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#d7ebfa"/></linearGradient>
<linearGradient id="distant-mountain" x1="0" y1="0" x2="0" y2="1">
<stop stop-color="#bdd9ed"/><stop offset="1" stop-color="#8bbad8"/></linearGradient></defs>
<rect width="1440" height="230" fill="url(#sky-haze)"/>
<path d="M0 166 62 144l35-43 40 25 40-38 70 52 50 5 80 62H0ZM1060 230l80-91 66 16 72-65 55 50 59-34 48 46v78Z" fill="#d8eaf7"/>
<path d="m0 184 90-92 47 34 40-38 70 52-38-5-28-24-21 29-60-16-54 68Zm1060 46 80-91 66 16 72-65 55 50 59-34 48 46-65-14-43 20-53-37-69 55-62-17-37 57Z" fill="url(#distant-mountain)"/>
<path d="m89 92 29 21-16-5-10 10-12-2Zm1089 47 28 16 72-65-24 42-23-12-22 26Z" fill="#f6fcff" opacity=".9"/>
<path d="M0 194q157-33 289-10t277 1q173-40 352 0t522-22v67H0Z" fill="#a7c9e0" opacity=".65"/>
<path d="M0 210q155-18 315-1t305-11q160-27 314-3t506 2v33H0Z" fill="#7fa8c7" opacity=".7"/>
<path d="M0 225q161-20 306-11t312-1q168-15 314 1t508-9v25H0Z" fill="#668fac" opacity=".5"/>
</svg>
</body></html>"""

def ensure_offline_home_file(directory, html):
    """Write only our static script-free homepage for a local WebEngine fallback.

    A file URL needs no network and avoids the data: URL renderer path on
    Windows QtWebEngine. No credentials, proxy links or user state are stored.
    """
    import os
    import tempfile
    from pathlib import Path

    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    path = base / "glacier-offline-home-v34.html"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PermissionError("Unsafe local Glacier homepage path")
    payload = html.encode("utf-8")
    if len(payload) > 200000 or b"<script" in payload.lower():
        raise ValueError("Untrusted or oversized Glacier homepage")
    if path.is_file() and path.read_bytes() == payload:
        return path
    fd, tmp = tempfile.mkstemp(prefix=".glacier-home-", dir=base)
    try:
        os.fchmod(fd, 0o600) if hasattr(os, "fchmod") else None
        with os.fdopen(fd, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return path


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
