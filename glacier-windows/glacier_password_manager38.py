"""Glacier Password Manager — actual cross-device browser password UX.

Full-size desktop control center, not a manually edited credential-card popup.
The password table exposes site/alias/username but NEVER a cleartext password.
It edits the existing OS-encrypted vault and uses existing device authorization
and E2E account synchronization; no independent service credentials are added.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QScrollArea, QWidget,
    QMessageBox, QSplitter
)


def manager_summary38(accounts, state, readonly=False):
    """UI metadata only; never returns plaintext passwords."""
    rows = accounts if isinstance(accounts, list) else []
    sites = {(r.get("space", "private"), r.get("site")) for r in rows
             if isinstance(r, dict) and isinstance(r.get("site"), str)}
    if readonly:
        sync = "本机密码库只读保护"
    elif not state.get("token"):
        sync = "仅此设备 · 登录 Glacier 可在授权设备间同步"
    elif not state.get("approved"):
        sync = "等待新设备授权"
    elif state.get("auto_enabled"):
        sync = "已启用加密账号同步 · 需已建立各空间基线"
    else:
        sync = "设备已授权 · 自动同步尚未开启"
    return {"sites": len(sites), "logins": len(rows),
            "private": sum(r.get("space", "private") == "private" for r in rows),
            "work": sum(r.get("space", "private") == "work" for r in rows),
            "sync": sync}


def visible_password_rows38(accounts, scope, search):
    if scope not in ("all", "private", "work"):
        return []
    words = [w.casefold() for w in str(search or "").split() if w]
    rows = []
    for card in accounts:
        if not isinstance(card, dict):
            continue
        space = card.get("space", "private")
        if space not in ("private", "work") or scope not in ("all", space):
            continue
        # Only search visible nonsecret metadata; never search password or OTP.
        hay = (str(card.get("site", ""))+" "+str(card.get("name", ""))+
               " "+str(card.get("username", ""))).casefold()
        if all(w in hay for w in words):
            rows.append(card)
    return sorted(rows, key=lambda c:(c.get("site", ""),
                                      c.get("space", "private"),
                                      c.get("name", "").casefold()))


class GlacierPasswordManager38:
    def show_password_manager38(self):
        """One coherent native window for saved logins, security and devices."""
        state = getattr(self, "_sync_state23", {})
        accounts = getattr(self, "_accounts_doc22", {"accounts": []}).get("accounts", [])
        summary = manager_summary38(accounts, state,
                                    getattr(self, "_accounts_readonly22", False))
        dialog = QDialog(self)
        dialog.setObjectName("GlacierPasswordManager38")
        dialog.setWindowTitle("Glacier · 密码管理器")
        dialog.setMinimumSize(850, 580)
        dialog.resize(1050, 690)
        dialog.setStyleSheet("""
          QDialog#GlacierPasswordManager38 {
            background:#F5F8FD; color:#1C2E46;
            font-family: "Segoe UI", "PingFang SC", sans-serif;
          }
          QFrame#GlacierPasswordsSidebar38 {
            background:#132641; border:0; border-radius:17px;
          }
          QLabel#GlacierPasswordsBrand38 {
            font-size:19px; font-weight:750; color:#FFFFFF;
          }
          QLabel#GlacierPasswordsSideHint38 {
            font-size:11px; color:#93AFCF;
          }
          QPushButton#GlacierPasswordsNav38 {
            background:transparent; border:0; border-radius:10px;
            text-align:left; padding:12px 15px;
            color:#D7E6F8; font-size:13px; font-weight:600;
          }
          QPushButton#GlacierPasswordsNav38:hover {background:#264360;}
          QPushButton#GlacierPasswordsNav38:checked {
            background:#295A81; color:#FFFFFF;
          }
          QLabel#GlacierPasswordsTitle38 {
            font-size:25px; color:#1D304C; font-weight:750;
          }
          QLabel#GlacierPasswordsSub38 {
            font-size:12px; color:#68819A;
          }
          QLabel#GlacierPasswordsMetricNumber38 {
            color:#152B46; font-size:23px; font-weight:750;
          }
          QLabel#GlacierPasswordsMetricLabel38 {
            color:#648096; font-size:11px;
          }
          QFrame#GlacierPasswordsMetric38, QFrame#GlacierPasswordsDetail38 {
            background:white; border:1px solid #E1EAF3; border-radius:14px;
          }
          QLabel#GlacierPasswordsStatus38 {
            color:#376181; font-size:12px;
            padding:7px 12px; background:#E8F1FA;
            border-radius:10px;
          }
          QLineEdit#GlacierPasswordsSearch38 {
            background:white; border:1px solid #D6E3F0;
            border-radius:10px; padding:12px 15px;
            font-size:13px; color:#1A3550;
            min-height:20px;
          }
          QListWidget#GlacierPasswordsList38 {
            background:white; border:1px solid #E1EAF3;
            border-radius:13px; padding:8px; font-size:13px; color:#243C58;
            outline:0;
          }
          QListWidget#GlacierPasswordsList38::item {
            padding:13px 10px; border-radius:9px; min-height:25px;
          }
          QListWidget#GlacierPasswordsList38::item:selected {
            background:#E8F1FA; color:#183B67;
          }
          QLabel#GlacierPasswordsDomain38 {
            color:#1D3655; font-size:19px; font-weight:750;
          }
          QLabel#GlacierPasswordsField38 {
            color:#74899E; font-size:11px;
          }
          QLabel#GlacierPasswordsValue38 {
            color:#203A55; font-size:13px;
          }
          QPushButton#GlacierPasswordsPrimary38 {
            background:#1A6EA8; color:white; border:0;
            border-radius:9px; font-size:12px; font-weight:650;
            padding:11px 12px;
          }
          QPushButton#GlacierPasswordsPrimary38:hover {background:#145C90;}
          QPushButton#GlacierPasswordsSecondary38 {
            background:white; border:1px solid #D7E4F0;
            color:#254768; border-radius:9px;
            font-size:12px; padding:10px 12px;
          }
          QPushButton#GlacierPasswordsSecondary38:hover {background:#EEF5FB;}
          QPushButton:disabled {color:#A8B7C8;background:#EFF3F7;}
        """)
        outer = QHBoxLayout(dialog)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.setSpacing(16)

        sidebar = QFrame(dialog)
        sidebar.setObjectName("GlacierPasswordsSidebar38")
        sidebar.setFixedWidth(209)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 24, 16, 20)
        side.setSpacing(9)
        logo = QLabel("◆  GLACIER", sidebar)
        logo.setObjectName("GlacierPasswordsBrand38")
        side.addWidget(logo)
        sidehint = QLabel("PASSWORDS & IDENTITY", sidebar)
        sidehint.setObjectName("GlacierPasswordsSideHint38")
        side.addWidget(sidehint)
        side.addSpacing(30)
        scope_nav = []
        for code, label in (
            ("all", "全部登录密码"), ("private", "私人空间"),
            ("work", "工作空间")
        ):
            btn = QPushButton(label, sidebar)
            btn.setObjectName("GlacierPasswordsNav38")
            btn.setCheckable(True)
            side.addWidget(btn)
            scope_nav.append((code, btn))
        side.addSpacing(15)
        devices = QPushButton("设备与账号同步", sidebar)
        devices.setObjectName("GlacierPasswordsNav38")
        side.addWidget(devices)
        side.addStretch()
        lock_label = QLabel("本机加密 · 授权设备同步\n密码不会在列表中直接显示", sidebar)
        lock_label.setObjectName("GlacierPasswordsSideHint38")
        lock_label.setWordWrap(True)
        side.addWidget(lock_label)
        outer.addWidget(sidebar)

        main = QWidget(dialog)
        main_col = QVBoxLayout(main)
        main_col.setContentsMargins(2, 6, 4, 4)
        main_col.setSpacing(16)
        title = QLabel("密码管理器", main)
        title.setObjectName("GlacierPasswordsTitle38")
        main_col.addWidget(title)
        subtitle = QLabel("登录网站后自动识别并询问保存 · 再次访问可选择填充 · 授权设备端到端加密同步", main)
        subtitle.setWordWrap(True)
        subtitle.setObjectName("GlacierPasswordsSub38")
        main_col.addWidget(subtitle)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        for number, name in (
            (summary["sites"], "已保存网站"),
            (summary["logins"], "登录凭据"),
            (summary["private"], "私人空间"),
            (summary["work"], "工作空间")
        ):
            card = QFrame(main)
            card.setObjectName("GlacierPasswordsMetric38")
            content = QVBoxLayout(card)
            content.setContentsMargins(15, 11, 15, 11)
            number_label = QLabel(str(number), card)
            number_label.setObjectName("GlacierPasswordsMetricNumber38")
            metric_label = QLabel(name, card)
            metric_label.setObjectName("GlacierPasswordsMetricLabel38")
            content.addWidget(number_label)
            content.addWidget(metric_label)
            metrics.addWidget(card, 1)
        main_col.addLayout(metrics)

        status = QLabel("●  "+summary["sync"], main)
        status.setObjectName("GlacierPasswordsStatus38")
        main_col.addWidget(status)

        tools = QHBoxLayout()
        search = QLineEdit(main)
        search.setObjectName("GlacierPasswordsSearch38")
        search.setPlaceholderText("搜索网站、账号名称或用户名")
        tools.addWidget(search, 1)
        add = QPushButton("＋ 添加登录", main)
        add.setObjectName("GlacierPasswordsSecondary38")
        tools.addWidget(add)
        main_col.addLayout(tools)

        split = QSplitter(Qt.Orientation.Horizontal, main)
        split.setChildrenCollapsible(False)
        listing = QListWidget(split)
        listing.setObjectName("GlacierPasswordsList38")
        listing.setMinimumWidth(250)

        detail = QFrame(split)
        detail.setObjectName("GlacierPasswordsDetail38")
        detail.setMinimumWidth(242)
        info = QVBoxLayout(detail)
        info.setContentsMargins(20, 20, 20, 19)
        info.setSpacing(12)
        domain = QLabel("选择一个已保存的登录", detail)
        domain.setObjectName("GlacierPasswordsDomain38")
        domain.setWordWrap(True)
        info.addWidget(domain)
        alias_title = QLabel("账户备注", detail)
        alias_title.setObjectName("GlacierPasswordsField38")
        info.addWidget(alias_title)
        alias = QLabel("—", detail)
        alias.setObjectName("GlacierPasswordsValue38")
        alias.setTextFormat(Qt.TextFormat.PlainText)
        alias.setWordWrap(True)
        info.addWidget(alias)
        username_title = QLabel("用户名", detail)
        username_title.setObjectName("GlacierPasswordsField38")
        info.addWidget(username_title)
        username = QLabel("—", detail)
        username.setTextFormat(Qt.TextFormat.PlainText)
        username.setWordWrap(True)
        username.setObjectName("GlacierPasswordsValue38")
        info.addWidget(username)
        password_label = QLabel("密码", detail)
        password_label.setObjectName("GlacierPasswordsField38")
        info.addWidget(password_label)
        masked = QLabel("••••••••••••", detail)
        masked.setObjectName("GlacierPasswordsValue38")
        info.addWidget(masked)
        space_label = QLabel("保存位置：—", detail)
        space_label.setObjectName("GlacierPasswordsField38")
        info.addWidget(space_label)
        info.addSpacing(8)
        open_btn = QPushButton("打开独立登录会话", detail)
        open_btn.setObjectName("GlacierPasswordsPrimary38")
        fill_btn = QPushButton("填充当前 HTTPS 登录页", detail)
        fill_btn.setObjectName("GlacierPasswordsSecondary38")
        copy_btn = QPushButton("复制密码 · 30 秒自动清除", detail)
        copy_btn.setObjectName("GlacierPasswordsSecondary38")
        edit_btn = QPushButton("编辑此登录", detail)
        edit_btn.setObjectName("GlacierPasswordsSecondary38")
        delete_btn = QPushButton("删除此登录", detail)
        delete_btn.setObjectName("GlacierPasswordsSecondary38")
        for widget in (open_btn, fill_btn, copy_btn, edit_btn, delete_btn):
            info.addWidget(widget)
        info.addStretch()
        split.addWidget(listing)
        split.addWidget(detail)
        split.setSizes([410, 320])
        main_col.addWidget(split, 1)

        footer = QLabel("网站密码只会在你明确批准后保存；跨设备同步复用现有 Glacier 设备授权。", main)
        footer.setObjectName("GlacierPasswordsSub38")
        footer.setWordWrap(True)
        main_col.addWidget(footer)
        outer.addWidget(main, 1)

        selection = [None]
        visible = ["all"]

        def refresh():
            # Re-read the live encrypted record cache after edits.
            current = getattr(self, "_accounts_doc22", {"accounts": []}).get("accounts", [])
            rows = visible_password_rows38(current, visible[0], search.text())
            listing.clear()
            for r in rows:
                item = QListWidgetItem(
                    r["site"]+"\n"+r["name"]+
                    "   ·   "+("工作" if r.get("space", "private") == "work" else "私人"))
                item.setData(Qt.ItemDataRole.UserRole,
                             (r.get("space", "private"),r["site"],r["name"]))
                listing.addItem(item)
            listing.setCurrentRow(0 if rows else -1)
            show_selected()

        def selected_card():
            item = listing.currentItem()
            if item is None:
                return None
            key = item.data(Qt.ItemDataRole.UserRole)
            for r in getattr(self, "_accounts_doc22", {"accounts":[]})["accounts"]:
                if (r.get("space","private"),r["site"],r["name"]) == key:
                    return r
            return None

        def show_selected():
            c = selected_card()
            selection[0] = c
            domain.setText(c["site"] if c else "没有符合条件的登录")
            alias.setText(c["name"] if c else "—")
            username.setText(c["username"] if c else "—")
            space_label.setText("保存位置："+(
                "工作空间" if c and c.get("space","private")=="work"
                else "私人空间" if c else "—"))
            compatible = bool(c and self._account_space22() == c.get("space","private"))
            for btn in (open_btn, fill_btn, copy_btn, edit_btn, delete_btn):
                btn.setEnabled(compatible and not getattr(self,"_accounts_readonly22",False))
            if c and not compatible:
                footer.setText("此登录位于另一工作空间；请先切换到相应空间，再打开或编辑。")
            else:
                footer.setText("网站密码只会在你明确批准后保存；跨设备同步复用现有 Glacier 设备授权。")

        def scope_changed(scope):
            visible[0] = scope
            for code,btn in scope_nav: btn.setChecked(code == scope)
            refresh()

        def selected_action(handler):
            card = selected_card()
            if card is None or self._account_space22() != card.get("space","private"):
                return
            handler(card)

        def edit(card):
            if self.edit_account22(card["site"],card):
                refresh()

        def remove(card):
            if QMessageBox.question(dialog,"删除已保存登录",
                "确定删除 "+card["site"]+" 的登录记录？此操作只删除本机当前空间的数据。",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            if self.delete_account22(card["site"],card["name"]):
                refresh()

        for code,btn in scope_nav:
            btn.clicked.connect(lambda _checked=False, s=code: scope_changed(s))
        devices.clicked.connect(lambda: self.show_sync23())
        listing.currentItemChanged.connect(lambda _new,_old:show_selected())
        search.textChanged.connect(lambda _value:refresh())
        add.clicked.connect(lambda: (self.add_account22(), refresh()))
        open_btn.clicked.connect(lambda: selected_action(self.open_account_session22))
        fill_btn.clicked.connect(lambda: selected_action(self.fill_account_form22))
        copy_btn.clicked.connect(lambda: selected_action(
            lambda c: self._copy_account22(c["password"])))
        edit_btn.clicked.connect(lambda: selected_action(edit))
        delete_btn.clicked.connect(lambda: selected_action(remove))
        scope_changed(self._account_space22())
        return dialog.exec()
