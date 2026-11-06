"""Glacier desktop D03: local encrypted website-account cards.

No automatic form filling, password injection, login automation or network calls.
Accounts are matched by exact canonical HTTPS hostname, never page text.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

MAX_ACCOUNTS = 100
MAX_STORE_BYTES = 256 * 1024


def safe_site22(raw):
    """Exact host match; reject http, credentials, ports, IP literals and URLs with paths."""
    if not isinstance(raw, str):
        return ""
    raw = raw.strip().lower()
    if not raw or len(raw) > 253 or "/" in raw or "@" in raw or ":" in raw:
        return ""
    if raw.startswith("www."):
        raw = raw[4:]
    labels = raw.split(".")
    if len(labels) < 2 or any(
        not label or len(label) > 63 or label[0] == "-" or label[-1] == "-"
        or any(not (c.isascii() and (c.isalnum() or c == "-")) for c in label)
        for label in labels
    ):
        return ""
    if labels[-1].isdigit():
        return ""
    return raw


def page_site22(url):
    if not isinstance(url, QUrl) or not url.isValid() or url.scheme().lower() != "https":
        return ""
    if url.userInfo() or url.port(-1) not in (-1, 443):
        return ""
    return safe_site22(url.host())


def clean_accounts22(payload):
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("Unsupported account-vault schema")
    records = payload.get("accounts")
    if not isinstance(records, list) or len(records) > MAX_ACCOUNTS:
        raise ValueError("Invalid account count")
    result, seen = [], set()
    for r in records:
        if not isinstance(r, dict):
            raise ValueError("Invalid account record")
        domain, name, username, password = (
            r.get("site"), r.get("name"), r.get("username"), r.get("password")
        )
        if (safe_site22(domain) != domain or not isinstance(name, str)
                or not isinstance(username, str) or not isinstance(password, str)
                or not (1 <= len(name.strip()) <= 60)
                or not (1 <= len(username) <= 250) or len(password) > 2048):
            raise ValueError("Invalid account entry")
        normalized_name = name.strip()
        key = (domain, normalized_name.casefold())
        if key in seen:
            raise ValueError("Duplicate account")
        seen.add(key)
        result.append({"site": domain, "name": normalized_name,
                       "username": username, "password": password})
    return {"schema": 1, "accounts": result}


class GlacierAccounts22:
    def setup_accounts22(self, directory, encrypt, decrypt):
        self._accounts_path22 = Path(directory) / "accounts-d03.dpapi"
        self._accounts_encrypt22 = encrypt
        self._accounts_decrypt22 = decrypt
        self._accounts_readonly22 = False
        self._accounts_doc22 = {"schema": 1, "accounts": []}
        self._account_last_site22 = {}
        if self._accounts_path22.exists():
            try:
                if self._accounts_path22.stat().st_size > MAX_STORE_BYTES:
                    raise ValueError("Account vault too large")
                clear = decrypt(self._accounts_path22.read_bytes())
                self._accounts_doc22 = clean_accounts22(json.loads(clear.decode("utf-8")))
            except Exception:
                # Never overwrite or "repair" corrupt ciphertext automatically.
                self._accounts_readonly22 = True
                QMessageBox.warning(self, "Glacier 账号卡片",
                                    "加密账号资料无法读取，已进入只读保护；旧文件不会被覆盖。")
        for index in range(self.tabs.count()):
            self.register_account_tab22(self.tabs.widget(index))

    def register_account_tab22(self, view):
        if not hasattr(self, "_accounts_doc22") or view is None:
            return
        view.urlChanged.connect(lambda url, v=view: self._on_account_url22(v, url))

    def _on_account_url22(self, view, url):
        site = page_site22(url)
        key = id(view)
        if self._account_last_site22.get(key) == site:
            return
        self._account_last_site22[key] = site
        if site and any(r["site"] == site for r in self._accounts_doc22["accounts"]):
            QTimer.singleShot(350, lambda v=view, s=site: self._show_site_accounts22(v, s))

    def _show_site_accounts22(self, view, site):
        try:
            if page_site22(view.url()) != site:
                return
        except RuntimeError:
            return
        self.show_accounts22(site)

    def _save_accounts22(self):
        if self._accounts_readonly22:
            raise ValueError("Account vault locked read-only; refusing to overwrite")
        doc = clean_accounts22(self._accounts_doc22)
        plaintext = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        blob = self._accounts_encrypt(plaintext)
        if not isinstance(blob, bytes) or not blob or blob == plaintext or len(blob) > MAX_STORE_BYTES:
            raise ValueError("Invalid encrypted account file")
        self._accounts_path22.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".accounts-d03-", dir=self._accounts_path22.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(blob)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self._accounts_path22)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _copy_account22(self, value):
        # Copy only on an explicit button press. Never paste into a webpage.
        clipboard = self._account_clipboard22()
        clipboard.setText(value)
        QTimer.singleShot(30000, lambda c=clipboard, v=value:
                          c.clear() if c.text() == v else None)

    def _account_clipboard22(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.clipboard()

    def add_account22(self, site=None):
        if self._accounts_readonly22:
            QMessageBox.warning(self, "Glacier", "账号资料已锁定为只读，不能修改。")
            return
        site = safe_site22(site) if site else ""
        if not site:
            site, ok = QInputDialog.getText(self, "添加网站账号", "HTTPS 网站域名（例如 chatgpt.com）")
            if not ok:
                return
            site = safe_site22(site)
        if not site:
            QMessageBox.warning(self, "Glacier", "请输入有效的网站域名。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Glacier · 添加账号卡片")
        layout = QFormLayout(dialog)
        name = QLineEdit(dialog)
        username = QLineEdit(dialog)
        password = QLineEdit(dialog)
        password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("备注名称", name)
        layout.addRow("账号", username)
        layout.addRow("密码（可留空）", password)
        save = QPushButton("加密保存", dialog)
        save.clicked.connect(dialog.accept)
        layout.addRow(save)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        record = {"site": site, "name": name.text().strip(),
                  "username": username.text(), "password": password.text()}
        candidate = {"schema": 1, "accounts": self._accounts_doc22["accounts"] + [record]}
        previous = self._accounts_doc22
        try:
            clean_accounts22(candidate)
            self._accounts_doc22 = candidate
            self._save_accounts22()
        except (ValueError, OSError) as exc:
            self._accounts_doc22 = previous
            QMessageBox.warning(self, "Glacier", "无法保存账号卡片：" + str(exc))
            return
        QMessageBox.information(self, "Glacier", "账号卡片已在本机加密保存。")

    def update_account22(self, site, original_name, name, username, password):
        """Update one stored card atomically; never alter ciphertext on invalid input."""
        if self._accounts_readonly22:
            return False
        old = self._accounts_doc22
        index = next((i for i, r in enumerate(old["accounts"])
                      if r["site"] == site and r["name"] == original_name), -1)
        if index < 0:
            return False
        records = [dict(r) for r in old["accounts"]]
        records[index] = {"site": site, "name": name.strip(),
                          "username": username, "password": password}
        candidate = {"schema": 1, "accounts": records}
        try:
            clean_accounts22(candidate)
            self._accounts_doc22 = candidate
            self._save_accounts22()
        except (ValueError, OSError):
            self._accounts_doc22 = old
            return False
        return True

    def edit_account22(self, site, record):
        if self._accounts_readonly22:
            QMessageBox.warning(self, "Glacier", "账号资料只读，无法编辑。")
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle("Glacier · 编辑账号卡片")
        layout = QFormLayout(dialog)
        name = QLineEdit(record["name"], dialog)
        username = QLineEdit(record["username"], dialog)
        password = QLineEdit(record["password"], dialog)
        password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("备注名称", name)
        layout.addRow("账号", username)
        layout.addRow("密码（可留空）", password)
        button = QPushButton("保存修改", dialog)
        button.clicked.connect(dialog.accept)
        layout.addRow(button)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if not self.update_account22(site, record["name"], name.text(),
                                     username.text(), password.text()):
            QMessageBox.warning(self, "Glacier", "修改未保存；原有资料保持不变。")
            return False
        return True

    def delete_account22(self, site, name):
        if self._accounts_readonly22:
            return False
        previous = self._accounts_doc22
        remaining = [r for r in previous["accounts"]
                     if not (r["site"] == site and r["name"] == name)]
        if len(remaining) == len(previous["accounts"]):
            return False
        self._accounts_doc22 = {"schema": 1, "accounts": remaining}
        try:
            self._save_accounts22()
        except (OSError, ValueError):
            self._accounts_doc22 = previous
            return False
        return True

    def show_accounts22(self, site=None):
        if site is None:
            view = self.current()
            site = page_site22(view.url()) if view is not None else ""
        site = safe_site22(site) if site else ""
        if not site:
            QMessageBox.information(self, "Glacier", "当前页面没有可匹配的 HTTPS 网站域名。")
            return
        entries = [r for r in self._accounts_doc22["accounts"] if r["site"] == site]
        if not entries:
            self.add_account22(site)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Glacier · " + site + " 账号信息")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("仅显示和手动复制；不会自动填充或自动登录。", dialog))
        for record in entries:
            row = QHBoxLayout()
            identity = QLabel(record["name"] + " · " + record["username"], dialog)
            identity.setTextFormat(Qt.TextFormat.PlainText)
            row.addWidget(identity, 1)
            copy_user = QPushButton("复制账号", dialog)
            copy_user.clicked.connect(lambda checked=False, v=record["username"]: self._copy_account22(v))
            row.addWidget(copy_user)
            if record["password"]:
                copy_password = QPushButton("复制密码", dialog)
                copy_password.clicked.connect(lambda checked=False, v=record["password"]: self._copy_account22(v))
                row.addWidget(copy_password)
            edit = QPushButton("编辑", dialog)
            def edit_current(checked=False, s=site, r=dict(record)):
                if self.edit_account22(s, r):
                    dialog.accept()
            edit.clicked.connect(edit_current)
            row.addWidget(edit)
            delete = QPushButton("删除", dialog)
            def remove_current(checked=False, s=site, n=record["name"]):
                response = QMessageBox.question(
                    dialog, "删除本地账号卡片",
                    "确定删除此网站的账号资料？删除后无法从本地恢复。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if response == QMessageBox.StandardButton.Yes:
                    if self.delete_account22(s, n):
                        dialog.accept()
                    else:
                        QMessageBox.warning(dialog, "Glacier", "删除未完成；原始加密文件已保留。")
            delete.clicked.connect(remove_current)
            row.addWidget(delete)
            layout.addLayout(row)
        close = QPushButton("关闭", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
