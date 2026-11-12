"""Glacier desktop UI refresh: visible Chrome-style controls and site vault.

This layer changes only presentation. It never loads remote UI resources,
changes the proxy, autofills credentials or bypasses website verification.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, QSize
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
    """One canonical, offline, script-free new-tab design across both OSes."""
    from glacier_shell20 import glacier_home20
    return glacier_home20()


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
        if getattr(self, "_chrome_ui33_ready", False):
            # Keep the live site security state but replace decorative glyphs
            # with consistent native-resolution icons in the new omnibox.
            from glacier_chrome_shell33 import shell_icon33
            self._site_button30.setIcon(
                shell_icon33("insecure" if url.scheme().lower() == "http" else "site"))
            self._site_button30.setIconSize(QSize(18, 18))
            self._site_button30.setText("")

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
            <h3>本次真正重做桌面顶部布局（Windows 0.20.23 / macOS 0.20.21）</h3>
            <p>旧版仅追加颜色样式，现已替换为两层 Chrome 式布局：
            上方完整标签栏、下方独立导航栏、44px 圆角可伸缩地址框；
            返回/前进/刷新使用统一轮廓图标。代理状态改成不挤占地址栏的
            小状态点，网站账号、下载和菜单保持可见。</p>
            <p>旧版附加功能保留原处理逻辑，集中到可展开的「工具」区；
            不会修改你的 VLESS、Cookie、账号库或工作区数据。</p>
            <h3>网站账号卡片</h3>
            <p>打开 HTTPS 网站可查看对应账号卡片，手动复制账号密码，
            或按已配置的接口获取验证码；不自动填表、不跳过安全验证。</p>
            <h3>工作与私人空间</h3>
            <p>不同工作区具有独立浏览器 Cookie 和本地存储；支持标签恢复、
            下载管理、加密账号资料，以及授权的账号同步。</p>
            <h3>Gemini 连接诊断</h3>
            <p>工具中心可主动检测 Gemini 的 HTTPS 入口是否能通过当前 VLESS
            线路建立连接，分辨代理、证书、超时、限流等问题；不会读取聊天内容，
            不会自动重发或刷新页面。HTTPS 可达不代表 Gemini 流式回复正常。</p>
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
