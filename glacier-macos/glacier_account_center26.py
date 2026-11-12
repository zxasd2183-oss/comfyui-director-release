"""Visible Glacier account center, backed by existing encrypted account APIs.

This is a presentation adapter only: existing login, registration, device
approval and sync routines remain the single source of truth.
"""
from PySide6.QtCore import Qt, QPoint, QSize, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)


def account_label26(state):
    if state.get("locked"):
        return "账号已锁定", "本机加密会话无法读取，保留旧数据"
    if not state.get("token"):
        return "登录 Glacier", "同步账号 · 尚未登录"
    if not state.get("approved"):
        return "等待设备授权", "请在已授权设备中确认登录申请"
    return str(state.get("username") or "Glacier 账号"), "已登录 · 此设备已授权"


class GlacierAccountCenter26:
    def setup_account_center26(self, nav):
        button = QPushButton("登录 Glacier", self)
        button.setObjectName("GlacierAccount26")
        button.setMinimumHeight(34)
        button.setMinimumWidth(114)
        button.setToolTip("Glacier 账号、注册登录、设备授权与加密同步")
        button.clicked.connect(self.show_account_center26)
        nav.addWidget(button)
        self._account_button26 = button
        self.refresh_account_center26()

    def refresh_account_center26(self):
        state = getattr(self, "_sync_state23", {})
        title, subtitle = account_label26(state)
        button = getattr(self, "_account_button26", None)
        if button is not None:
            # Chrome-like shell uses a profile avatar, not a wide account pill.
            # Keep the full state available on hover and in the actual dialog.
            button.setText("" if getattr(self, "_chrome_ui33_ready", False) else "❄ " + title)
            button.setToolTip(title + " · " + subtitle)

    def show_account_center26(self):
        """Show an anchored Chrome-like profile menu, not a separate dialog.

        All actions delegate to the existing encrypted vault, device approval
        and account sync methods. Neither credentials nor OTPs appear here.
        """
        old = getattr(self, "_account_popover37", None)
        if old is not None:
            try:
                if old.isVisible():
                    old.close()
                    return None
            except RuntimeError:
                pass

        from glacier_chrome_top35 import top_icon35
        state = getattr(self, "_sync_state23", {})
        title, subtitle = account_label26(state)
        locked = bool(state.get("locked"))
        logged = bool(state.get("token"))
        approved = bool(state.get("approved"))
        anchor = self._account_button26

        panel = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        panel.setObjectName("GlacierProfilePopover37")
        panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        panel.setFixedWidth(344)
        panel.setStyleSheet("""
            QFrame#GlacierProfilePopover37 {
                background: #ffffff;
                color: #27354a;
                border: 1px solid #dce4ef;
                border-radius: 15px;
            }
            QFrame#GlacierProfileHero37 {
                background: #edf3fc;
                border: 0;
                border-radius: 12px;
            }
            QLabel#GlacierProfileBrand37 {
                font-size: 11px; font-weight: 700;
                color: #587da9;
            }
            QLabel#GlacierProfileName37 {
                font-size: 16px; font-weight: 650;
                color: #203854;
            }
            QLabel#GlacierProfileStatus37 {
                font-size: 11px; color: #607a97;
            }
            QLabel#GlacierProfileSection37 {
                font-size: 11px; font-weight: 600;
                color: #71829a; padding: 8px 7px 3px;
            }
            QLabel#GlacierProfileFooter37 {
                font-size: 10px; color: #7f8d9e;
                padding: 10px 4px 4px;
            }
            QPushButton#GlacierProfileMain37 {
                background: #1764d8; color: white;
                font-size: 12px; font-weight: 600;
                border: none; border-radius: 18px;
                padding: 8px 12px; min-height: 21px;
            }
            QPushButton#GlacierProfileMain37:hover { background: #0e56bd; }
            QPushButton#GlacierProfileRow37 {
                color: #32445d; background: transparent;
                border: 0; border-radius: 8px;
                text-align: left; padding: 7px 10px;
                min-height: 24px; font-size: 12px;
            }
            QPushButton#GlacierProfileRow37:hover { background: #eff4fa; }
            QPushButton#GlacierProfileRow37:pressed { background: #e1ebf7; }
            QScrollArea#GlacierProfileScroll37 {
                background: #ffffff; border: 0;
            }
            QWidget#GlacierProfileRows37 { background: white; }
        """)
        root = QVBoxLayout(panel)
        root.setContentsMargins(11, 11, 11, 10)
        root.setSpacing(0)

        hero = QFrame(panel)
        hero.setObjectName("GlacierProfileHero37")
        header = QVBoxLayout(hero)
        header.setContentsMargins(13, 12, 13, 13)
        header.setSpacing(4)
        mark = QLabel(hero)
        mark.setObjectName("GlacierProfileAvatar37")
        mark.setPixmap(top_icon35("glacier").pixmap(QSize(40, 40)))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(mark, alignment=Qt.AlignmentFlag.AlignHCenter)
        brand = QLabel("GLACIER BROWSER", hero)
        brand.setObjectName("GlacierProfileBrand37")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(brand)
        name = QLabel(title, hero)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setObjectName("GlacierProfileName37")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        header.addWidget(name)
        status = QLabel(subtitle, hero)
        status.setTextFormat(Qt.TextFormat.PlainText)
        status.setObjectName("GlacierProfileStatus37")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setWordWrap(True)
        header.addWidget(status)

        def execute(handler):
            # Hide the popup before showing any login form, system workspace
            # menu or confirmation dialog. The Qt event loop then opens it.
            panel.close()
            def run():
                try:
                    handler()
                except Exception as exc:
                    self._sync_error23(type(exc).__name__ + "，操作未完成")
                finally:
                    self.refresh_account_center26()
            QTimer.singleShot(0, run)

        if locked:
            main_label, main_handler = "管理本机网站账号", self.manage_accounts22
        elif not logged:
            main_label, main_handler = "登录 Glacier 账号", lambda: self._account_form26(False)
        elif not approved:
            main_label, main_handler = "检查设备授权", self._sync_activate23
        else:
            main_label, main_handler = "管理网站账号", self.manage_accounts22

        main = QPushButton(main_label, hero)
        main.setObjectName("GlacierProfileMain37")
        main.setAccessibleName(main_label)
        main.clicked.connect(lambda _checked=False: execute(main_handler))
        header.addSpacing(8)
        header.addWidget(main)
        root.addWidget(hero)

        scroll = QScrollArea(panel)
        scroll.setObjectName("GlacierProfileScroll37")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("GlacierProfileRows37")
        rows = QVBoxLayout(body)
        rows.setContentsMargins(6, 7, 6, 4)
        rows.setSpacing(2)

        def section(label):
            heading = QLabel(label, body)
            heading.setObjectName("GlacierProfileSection37")
            rows.addWidget(heading)

        def item(label, handler, glyph):
            btn = QPushButton(label, body)
            btn.setObjectName("GlacierProfileRow37")
            btn.setIcon(top_icon35(glyph))
            btn.setIconSize(QSize(18, 18))
            btn.setMinimumHeight(38)
            btn.setAccessibleName(label)
            btn.clicked.connect(lambda _checked=False, h=handler: execute(h))
            rows.addWidget(btn)

        section("网站与个人资料")
        item("网站账号和密码", self.manage_accounts22, "site")
        workspace_button = getattr(self, "_workspace_button17", None)
        if workspace_button is not None:
            item("切换 / 管理工作空间", workspace_button.showMenu, "hub")

        if locked:
            section("同步会话已锁定")
            info = QLabel("原有加密会话已保留，不会自动覆盖。", body)
            info.setWordWrap(True)
            rows.addWidget(info)
        elif not logged:
            section("Glacier 账号")
            item("创建 Glacier 账号", lambda: self._account_form26(True), "profile")
        else:
            section("设备授权与加密同步")
            if approved:
                item("管理已授权设备", self._sync_devices23, "profile")
                item("上传加密资料", self._sync_push23, "download")
                item("下载加密资料", self._sync_pull23, "download")
                if state.get("auto_enabled"):
                    item("关闭自动同步", self._sync_disable_auto23, "reload")
                else:
                    item("开启自动同步", self._sync_enable_auto23, "reload")
            else:
                item("重新检查设备授权", self._sync_activate23, "reload")
            item("退出 Glacier 账号", self._sync_logout23, "back")

        rows.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll)

        footer = QLabel("网站密码仅手动复制 · 验证码仅点击获取", panel)
        footer.setObjectName("GlacierProfileFooter37")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setWordWrap(True)
        root.addWidget(footer)

        screen = anchor.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        scroll.setFixedHeight(min(body.sizeHint().height() + 8,
                                  max(120, available.height() - 230)))
        panel.adjustSize()
        panel_height = min(panel.sizeHint().height(), available.height() - 16)
        panel.resize(344, panel_height)
        desired = anchor.mapToGlobal(QPoint(anchor.width() - panel.width(),
                                            anchor.height() + 8))
        x = max(available.left() + 8,
                min(desired.x(), available.right() - panel.width() - 8))
        y = desired.y()
        if y + panel.height() > available.bottom() - 8:
            y = max(available.top() + 8,
                    anchor.mapToGlobal(QPoint(0, 0)).y() - panel.height() - 8)
        panel.move(x, y)
        self._account_popover37 = panel
        panel.show()
        panel.raise_()
        return panel

    def _account_form26(self, register=False):
        """One coherent register/login form, not a series of prompt dialogs."""
        from glacier_sync23 import DEFAULT_SYNC_URL23, sync_url23
        form = QDialog(self)
        form.setWindowTitle("创建 Glacier 账号" if register else "登录 Glacier")
        form.setMinimumWidth(430)
        form.setObjectName("GlacierAccountForm26")
        layout = QVBoxLayout(form)
        layout.setContentsMargins(25, 22, 25, 22)
        layout.setSpacing(13)
        head = QLabel("创建你的 Glacier 账号" if register else "欢迎回来", form)
        head.setStyleSheet("font-size:20px;font-weight:600;color:#285b7c;")
        layout.addWidget(head)
        hint = QLabel("端到端加密账号同步 · 设备授权保护", form)
        hint.setStyleSheet("color:#718a9c;")
        layout.addWidget(hint)
        fields = QFormLayout()
        base = QLineEdit(form)
        base.setText(getattr(self, "_sync_state23", {}).get("base") or DEFAULT_SYNC_URL23)
        user = QLineEdit(form)
        user.setPlaceholderText("Glacier 账号 ID")
        user.setText(getattr(self, "_sync_state23", {}).get("username", "") if not register else "")
        password = QLineEdit(form)
        password.setEchoMode(QLineEdit.EchoMode.Password)
        password.setPlaceholderText("至少 12 个字符")
        fields.addRow("同步服务器", base)
        fields.addRow("账号", user)
        fields.addRow("登录密码", password)
        invitation = None
        if register:
            invitation = QLineEdit(form)
            invitation.setEchoMode(QLineEdit.EchoMode.Password)
            invitation.setPlaceholderText("私人注册邀请码")
            fields.addRow("注册邀请码", invitation)
        layout.addLayout(fields)
        note = QLabel("不会自动填充网站登录表单；同步密码与设备授权信息保存在本机加密会话。", form)
        note.setWordWrap(True)
        note.setStyleSheet("color:#718a9c;font-size:11px;")
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            form)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建账号" if register else "登录")
        def submit():
            url, name, secret = base.text().strip(), user.text().strip(), password.text()
            if not sync_url23(url) or not name or len(secret) < 12:
                QMessageBox.warning(form, "Glacier 账号",
                                    "请检查 HTTPS 服务器、账号以及至少 12 位的密码。")
                return
            invite = invitation.text() if register else ""
            if register and not invite:
                QMessageBox.warning(form, "Glacier 账号", "注册邀请码不能为空。")
                return
            # Do not dismiss the form on network or permission failures:
            # users can correct credentials without entering them twice.
            submit_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
            submit_button.setEnabled(False)
            try:
                if register:
                    self._sync_register23(base=url, username=name,
                                          password=secret, invite=invite)
                else:
                    self._sync_login23(base=url, username=name, password=secret)
            except Exception as exc:
                # Never echo URLs with credentials, tokens, or raw server bodies.
                QMessageBox.warning(form, "Glacier 账号",
                                    type(exc).__name__ + "：操作未完成。请检查网络、账号或授权。")
            else:
                form.accept()
            finally:
                submit_button.setEnabled(True)

        buttons.accepted.connect(submit)
        buttons.rejected.connect(form.reject)
        layout.addWidget(buttons)
        return form.exec() == QDialog.DialogCode.Accepted
