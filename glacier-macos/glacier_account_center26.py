"""Visible Glacier account center, backed by existing encrypted account APIs.

This is a presentation adapter only: existing login, registration, device
approval and sync routines remain the single source of truth.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
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
            button.setText("❄ " + title)
            button.setToolTip(subtitle)

    def show_account_center26(self):
        state = getattr(self, "_sync_state23", {})
        title, subtitle = account_label26(state)
        dialog = QDialog(self)
        dialog.setWindowTitle("Glacier · 账号中心")
        dialog.setObjectName("GlacierAccountCenter26")
        dialog.setMinimumSize(480, 500)
        dialog.resize(520, 560)
        dialog.setStyleSheet("""
            QDialog#GlacierAccountCenter26 {
                background:#f7fbfe; color:#263949;
            }
            QLabel#GlacierAccountTitle26 {
                font-size:23px; font-weight:700; color:#264c67;
            }
            QLabel#GlacierAccountDesc26 {
                color:#708b9e; font-size:12px;
            }
            QFrame#GlacierAccountPanel26 {
                border:1px solid #deebf4; border-radius:16px;
                background:white;
            }
            QPushButton#GlacierAccountAction26 {
                text-align:left; padding:11px 16px;
                background:#fff; border:1px solid #e1eaf1;
                border-radius:10px; color:#2b506b; font-size:13px;
            }
            QPushButton#GlacierAccountAction26:hover {
                background:#edf7fe; border-color:#a9cfe5;
            }
            QPushButton#GlacierAccountMain26 {
                padding:12px; border:0; border-radius:11px;
                background:#327da7; color:white; font-weight:600;
            }
            QPushButton#GlacierAccountMain26:hover {
                background:#286b92;
            }
        """)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(26, 25, 26, 20)
        root.setSpacing(11)
        emblem = QLabel("❄  GLACIER ACCOUNT", dialog)
        emblem.setStyleSheet("color:#3985ac; font-size:12px; font-weight:700;")
        root.addWidget(emblem)
        headline = QLabel(title, dialog)
        headline.setObjectName("GlacierAccountTitle26")
        root.addWidget(headline)
        description = QLabel(subtitle + "\n服务器 · sync.borealos.cn", dialog)
        description.setObjectName("GlacierAccountDesc26")
        root.addWidget(description)
        root.addSpacing(10)

        panel = QFrame(dialog)
        panel.setObjectName("GlacierAccountPanel26")
        column = QVBoxLayout(panel)
        column.setContentsMargins(15, 15, 15, 15)
        column.setSpacing(8)
        root.addWidget(panel, 1)

        locked = bool(state.get("locked"))
        logged = bool(state.get("token"))
        approved = bool(state.get("approved"))

        def action(text, handler, primary=False):
            btn = QPushButton(text, panel)
            btn.setObjectName("GlacierAccountMain26" if primary else "GlacierAccountAction26")
            btn.clicked.connect(lambda: execute(handler))
            column.addWidget(btn)
            return btn

        def execute(handler):
            # Account operations may open their own form. Cancellation must
            # leave this center visible, without discarding account state.
            try:
                result = handler()
            except Exception as exc:
                self._sync_error23(type(exc).__name__ + "，操作未完成")
                return
            if result is False:
                return
            dialog.accept()
            self.refresh_account_center26()

        if locked:
            note = QLabel("本机账号会话已锁定。不会自动删除或覆盖任何保存的数据。", panel)
            note.setWordWrap(True)
            column.addWidget(note)
        elif not logged:
            action("登录已有 Glacier 账号", lambda: self._account_form26(False), True)
            action("注册新的 Glacier 账号", lambda: self._account_form26(True))
            note = QLabel("注册需要私密邀请码。密码和验证码不会自动填入网页。", panel)
            note.setWordWrap(True)
            note.setStyleSheet("color:#71889a; padding:9px;")
            column.addWidget(note)
        else:
            action("检查当前设备授权", self._sync_activate23, not approved)
            if approved:
                action("管理和批准其他设备", self._sync_devices23)
                action("上传当前空间（加密）", self._sync_push23)
                action("下载当前空间（解密）", self._sync_pull23)
                if state.get("auto_enabled"):
                    action("关闭自动同步", self._sync_disable_auto23)
                else:
                    action("开启自动加密同步", self._sync_enable_auto23)
                action("网站账号卡片", lambda: self.show_accounts22())
            action("退出当前设备账号", self._sync_logout23)
        column.addStretch(1)
        footer = QLabel("私人 / 工作空间隔离 · 加密凭据仅由授权设备访问", dialog)
        footer.setStyleSheet("color:#8095a4;font-size:11px;")
        root.addWidget(footer)
        close = QPushButton("完成", dialog)
        close.clicked.connect(dialog.accept)
        root.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()
        self.refresh_account_center26()

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
        buttons.accepted.connect(form.accept)
        buttons.rejected.connect(form.reject)
        layout.addWidget(buttons)
        if form.exec() != QDialog.DialogCode.Accepted:
            return False
        url, name, secret = base.text().strip(), user.text().strip(), password.text()
        if not sync_url23(url) or not name or len(secret) < 12:
            QMessageBox.warning(self, "Glacier 账号", "请检查 HTTPS 服务器、账号以及至少 12 位的密码。")
            return False
        if register:
            invite = invitation.text()
            if not invite:
                QMessageBox.warning(self, "Glacier 账号", "注册邀请码不能为空。")
                return False
            self._sync_register23(base=url, username=name, password=secret, invite=invite)
        else:
            self._sync_login23(base=url, username=name, password=secret)
        return True
