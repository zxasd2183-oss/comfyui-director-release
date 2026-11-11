"""Glacier desktop UI refresh: visible Chrome-style controls and site vault.

This layer changes only presentation. It never loads remote UI resources,
changes the proxy, autofills credentials or bypasses website verification.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QDialog, QLabel, QMessageBox, QPushButton,
                               QTextBrowser, QToolButton, QVBoxLayout)

CHROME_QSS30 = """
QMainWindow { background: #f6f8fb; color: #263240; }
QWidget#GlacierTabStrip14 {
  background: #e9eef4; border: 0;
  border-bottom: 1px solid #dce4ec;
}
QTabBar#GlacierExternalTabs14::tab {
  background: #e2e8ee; color: #4a5b6c; border: 1px solid #dce4ec;
  border-bottom: 0; border-top-left-radius: 12px;
  border-top-right-radius: 12px; min-width: 128px;
  max-width: 220px; min-height: 32px;
  padding: 3px 16px 1px; margin-right: 4px; margin-top: 3px;
}
QTabBar#GlacierExternalTabs14::tab:selected {
  background: #fff; border-color: #d7e0e9; color: #213648;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
  background: #f5f8fc; color: #243f53;
}
QLineEdit#GlacierOmnibox14 {
  background: #f0f3f7; color: #273b4d;
  border: 1px solid #edf0f4; border-radius: 21px;
  min-height: 28px; padding: 6px 15px; font-size: 13px;
}
QLineEdit#GlacierOmnibox14:focus {
  background: white; border: 1px solid #8ab8d5;
}
QPushButton#GlacierAccount26 {
  background: #eaf3f9; color: #326583; border: 1px solid #d4e7f3;
  border-radius: 18px; font-size: 12px; padding: 6px 13px;
  min-height: 27px; font-weight: 600;
}
QPushButton#GlacierAccount26:hover { background: #daedf8; }
QPushButton#GlacierProxyHealth29 {
  background: #f6f9fc; border: 1px solid #e1e9f0;
  border-radius: 16px; padding: 5px 10px; font-size: 12px;
}
QToolButton#GlacierSiteInfo30 {
  background: #f0f3f7; color: #40687c;
  border: 1px solid transparent; border-radius: 16px;
  font-size: 15px; min-width: 30px; min-height: 30px;
  max-width: 33px; margin: 0;
}
QToolButton#GlacierSiteInfo30:hover { background: #dae8f2; }
QToolButton#GlacierHub20, QToolButton#GlacierMore14 {
  border-radius: 11px; min-width: 31px; min-height: 30px;
}
QTabWidget::pane { background: white; border: 0; }
QMenu { background: #fff; border: 1px solid #e0e6ec; }
QMenu::item:selected { background: #e9f4fa; color: #274c65; }
"""

def new_tab_page30():
    """Offline, script-free homepage with working HTTPS links and search."""
    return """<!doctype html><html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glacier · 新标签页</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;color:#253747;
font:15px -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
background:radial-gradient(ellipse 42% 30% at 92% 2%,#e1effa 0%,transparent 100%),
radial-gradient(ellipse 44% 40% at 4% 90%,#eff7f9 0%,transparent 100%),#f9fbfd}
header{max-width:1120px;margin:auto;display:flex;align-items:center;
justify-content:space-between;padding:30px 32px}
.brand{font-size:13px;letter-spacing:.16em;font-weight:800;color:#367fa6}
.privacy{font-size:12px;color:#849bad;display:flex;gap:9px;align-items:center}
.dot{width:8px;height:8px;border-radius:50%;background:#75bca5}
main{max-width:760px;margin:clamp(75px,13vh,158px) auto 0;padding:0 26px}
.logo{text-align:center;font-size:42px;margin:0 0 12px;color:#3183ae;letter-spacing:-2px;font-weight:700}
h1{font-size:23px;font-weight:500;text-align:center;color:#51697a;margin:0 0 36px}
.search{display:flex;align-items:center;min-height:62px;background:#fff;
border:1px solid #dee8f0;border-radius:32px;padding:0 23px;
box-shadow:0 9px 29px #315a7c10}
.search:focus-within{border-color:#96c0d9;box-shadow:0 12px 30px #3e88b21b}
.search span{font-size:25px;color:#8da6b6;margin-right:16px}
.search input{border:0;outline:0;background:transparent;flex:1;min-width:0;
font:15px inherit;color:#284457}
.section{display:flex;align-items:center;justify-content:space-between;
margin:44px 4px 17px}
.section b{font-size:14px;font-weight:600;color:#567184}
.section small{font-size:12px;color:#9badba}
.grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}
a{text-decoration:none;color:inherit}
.tile{border-radius:17px;background:#fff;min-height:108px;
border:1px solid #e8edf2;display:flex;align-items:center;
justify-content:center;flex-direction:column;gap:12px;font-size:12px;
color:#627688;transition:transform .15s,background .15s}
.tile:hover{background:#eef7fc;transform:translateY(-2px);border-color:#c9e1ed}
.icon{width:43px;height:43px;border-radius:14px;background:#eaf3fa;
display:grid;place-items:center;font-size:17px;font-weight:700;color:#357da4}
.note{margin:28px 0;text-align:center;font-size:12px;color:#a3b2bd}
@media(max-width:660px){.grid{grid-template-columns:repeat(3,1fr)}
header{padding:23px}.privacy{display:none}main{margin-top:11vh}}
</style></head>
<body><header><div class="brand">❄ GLACIER BROWSER</div>
<div class="privacy"><i class="dot"></i>本地浏览 · 自有线路 · 不自动填充账号</div></header>
<main><p class="logo">Glacier</p><h1>探索，从此刻开始</h1>
<form class="search" action="https://www.google.com/search" method="get">
<span aria-hidden="true">⌕</span><input type="search" name="q" autofocus
autocomplete="off" placeholder="使用 Google 搜索网络" aria-label="搜索网络"></form>
<div class="section"><b>快捷访问</b><small>常用网站 · 使用浏览器当前网络连接</small></div>
<nav class="grid" aria-label="快捷网站">
<a class="tile" href="https://www.google.com"><span class="icon">G</span>Google</a>
<a class="tile" href="https://chatgpt.com"><span class="icon">AI</span>ChatGPT</a>
<a class="tile" href="https://www.youtube.com"><span class="icon">▶</span>YouTube</a>
<a class="tile" href="https://github.com"><span class="icon">GH</span>GitHub</a>
<a class="tile" href="https://mail.google.com"><span class="icon">✉</span>Gmail</a>
<a class="tile" href="https://www.wikipedia.org"><span class="icon">W</span>Wikipedia</a>
</nav><div class="note">网站账号卡片可在地址栏旁的连接信息按钮中查看</div>
</main></body></html>"""

class GlacierChromeUI30:
    """One shared desktop UI without changing encrypted stores or proxy routing."""

    def home_markup(self):
        return new_tab_page30()

    def setup_ui30(self, nav):
        self.address.setObjectName("GlacierOmnibox14")
        self.address.setMinimumHeight(40)
        self.address.setPlaceholderText("搜索 Google 或输入网址")
        identity = QToolButton(self)
        identity.setObjectName("GlacierSiteInfo30")
        identity.setToolTip("查看当前网站与账号卡片")
        identity.clicked.connect(self.open_site_info30)
        nav.insertWidget(nav.indexOf(self.address), identity)
        self._site_button30 = identity
        # The external tab strip already owns the New Tab (+) control.
        for n in range(nav.count()):
            item = nav.itemAt(n)
            button = item.widget() if item else None
            if isinstance(button, QPushButton) and button.text() == "＋":
                button.hide()
        self.address.textChanged.connect(lambda _: self.update_site_info30())
        self.tabs.currentChanged.connect(lambda _: self.update_site_info30())
        self.update_site_info30()
        self.setStyleSheet(self.styleSheet() + "\n" + CHROME_QSS30)

    def _current_site30(self):
        view = self.current()
        if view is None:
            return ""
        url = view.url()
        if not isinstance(url, QUrl) or not url.isValid():
            return ""
        if url.scheme().lower() != "https" or url.userInfo() or url.port(-1) not in (-1,443):
            return ""
        from glacier_accounts22 import page_site22
        return page_site22(url)

    def update_site_info30(self):
        current = self.current()
        url = current.url() if current is not None else QUrl()
        site = self._current_site30()
        if site:
            self._site_button30.setText("♙")
            self._site_button30.setToolTip(
                site + " · HTTPS 已加密；点击查看/添加该网站账号卡片")
        elif url.scheme().lower() == "http":
            self._site_button30.setText("!")
            self._site_button30.setToolTip("此页面不是 HTTPS，不能显示或保存网站账号")
        else:
            self._site_button30.setText("❄")
            self._site_button30.setToolTip("Glacier · 本地标签页")

    def open_site_info30(self):
        site = self._current_site30()
        if not site:
            QMessageBox.information(self, "Glacier 连接信息",
                "当前不是可匹配的 HTTPS 网站，账号卡片已禁用。")
            return
        self.show_accounts22(site)

    def _build_hub_menu20(self):
        # Keep every original action, then make actual release changes visible.
        parent = getattr(super(), "_build_hub_menu20", None)
        if callable(parent):
            parent()
        menu = getattr(self, "_hub_menu20", None)
        if menu is not None:
            menu.addSeparator()
            diagnostic = getattr(self, "start_gemini_diagnostic31", None)
            if callable(diagnostic):
                menu.addAction("Gemini 连接诊断（VLESS HTTPS）", diagnostic)
            menu.addAction("本版新增功能与更新说明", self.open_release_notes30)

    def open_release_notes30(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Glacier · 本版更新说明")
        dialog.setObjectName("GlacierReleaseNotes30")
        dialog.resize(570, 510)
        dialog.setStyleSheet("""
          QDialog#GlacierReleaseNotes30 { background:#f6faff; color:#28475c; }
          QTextBrowser#GlacierNotes30 {
            background:white; border:1px solid #deebf4;
            border-radius:14px; padding:16px; color:#344d5c;
          }
          QPushButton#GlacierNotesClose30 {
            background:#337fa8; color:white; border:0;
            border-radius:10px; padding:10px 18px; font-weight:600;
          }
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        heading = QLabel("❄ Glacier · 这次实际更新了什么", dialog)
        heading.setStyleSheet("font-size:20px;font-weight:700;color:#285d79;")
        layout.addWidget(heading)
        note = QLabel("统一的轻量浏览体验 · 不重复导入已有的 VLESS 线路", dialog)
        note.setStyleSheet("color:#758fa0;font-size:12px;")
        layout.addWidget(note)
        panel = QTextBrowser(dialog)
        panel.setObjectName("GlacierNotes30")
        panel.setOpenExternalLinks(False)
        panel.setHtml("""
            <h3>全新桌面布局</h3>
            <p>更紧凑的 Chrome 风格标签栏、圆角地址栏与轻量新标签页，
            常用网站快捷入口；多余功能收起到统一工具中心。</p>
            <h3>网站账号卡片</h3>
            <p>打开 HTTPS 网站可查看对应账号卡片，手动复制账号密码，
            或按已配置的接口获取验证码；不自动填表、不跳过安全验证。</p>
            <h3>工作与私人空间</h3>
            <p>不同工作区具有独立浏览器 Cookie 和本地存储；支持标签恢复、
            下载管理、加密账号资料，以及授权的账号同步。</p>
            <h3>代理与安全</h3>
            <p>继续使用已保存的本机 VLESS 节点；代理断开禁止自动直连，
            更新安装包校验签名、大小和 SHA-256。</p>
            <p style="color:#71899a;font-size:12px">
              平台功能以实际安装包为准。网站安全验证仍需用户自行完成。
              此说明不代表你设备上的升级已经完成。</p>
        """)
        layout.addWidget(panel, 1)
        close = QPushButton("知道了", dialog)
        close.setObjectName("GlacierNotesClose30")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
