"""Glacier desktop D03: local encrypted website-account cards.

No automatic form filling, password injection, login automation or network calls.
Accounts are matched by exact canonical HTTPS hostname, never page text.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QListWidget, QVBoxLayout, QWidget,
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


def safe_code_api22(raw):
    """HTTPS-only explicit OTP endpoint, never localhost or URL credentials."""
    if not isinstance(raw, str) or len(raw) > 2048:
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if (parts.scheme.lower() != "https" or parts.username is not None
                or parts.password is not None or parts.fragment
                or parts.port not in (None, 443)
                or not parts.hostname or not safe_site22(parts.hostname)
                or any(ord(c) < 32 for c in raw)):
            return ""
    except ValueError:
        return ""
    return raw


def extract_code22(raw):
    """Only accept an unambiguous 4–10 digit code; never echo API responses."""
    import re
    if not isinstance(raw, bytes) or len(raw) > 4096:
        return ""
    try:
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeError, ValueError):
        payload = None
        decoded = raw.decode("utf-8", "replace")
    if isinstance(payload, dict):
        for container in (payload, payload.get("data")):
            if isinstance(container, dict):
                for key in ("code", "otp", "verification_code", "sms_code"):
                    value = str(container.get(key, ""))
                    if re.fullmatch(r"[0-9]{4,10}", value):
                        return value
    if re.fullmatch(r"\s*[0-9]{4,10}\s*", decoded):
        return decoded.strip()
    return ""


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
        if (not domain or safe_site22(domain) != domain or not isinstance(name, str)
                or not isinstance(username, str) or not isinstance(password, str)
                or not (1 <= len(name.strip()) <= 60)
                or not (1 <= len(username) <= 250) or len(password) > 2048):
            raise ValueError("Invalid account entry")
        code_api = r.get("code_api", "")
        if code_api and safe_code_api22(code_api) != code_api:
            raise ValueError("Invalid HTTPS OTP API endpoint")
        if not isinstance(code_api, str):
            raise ValueError("Invalid OTP API field")
        space = r.get("space", "private")
        if space not in ("private", "work"):
            raise ValueError("Invalid account space")
        normalized_name = name.strip()
        key = (space, domain, normalized_name.casefold())
        if key in seen:
            raise ValueError("Duplicate account")
        seen.add(key)
        result.append({"site": domain, "name": normalized_name,
                       "username": username, "password": password,
                       "code_api": code_api, "space": space})
    return {"schema": 1, "accounts": result}


def account_site_summary22(records, query=""):
    """Search domain/alias only: never index usernames, passwords or tokens."""
    words = query.strip().casefold().split()
    sites = {}
    for record in records:
        site = record["site"]
        if all(word in (site + " " + record["name"]).casefold() for word in words):
            sites[site] = sites.get(site, 0) + 1
    return sorted(sites.items())


class GlacierAccounts22:
    def _account_space22(self):
        current = getattr(self, "_workspace_doc17", {}).get("active", "default")
        return "private" if current == "default" else "work"

    def setup_accounts22(self, directory, encrypt, decrypt):
        self._accounts_path22 = Path(directory) / "accounts-d03.dpapi"
        self._accounts_encrypt22 = encrypt
        self._accounts_decrypt22 = decrypt
        self._accounts_readonly22 = False
        self._accounts_doc22 = {"schema": 1, "accounts": []}
        self._account_last_site22 = {}
        self._account_presented22 = {}
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
        self.tabs.currentChanged.connect(self._on_account_tab_selected22)

    def register_account_tab22(self, view):
        if not hasattr(self, "_accounts_doc22") or view is None:
            return
        view.urlChanged.connect(lambda url, v=view: self._on_account_url22(v, url))

    def unregister_account_tab22(self, view):
        """Drop ephemeral popup state when a tab is closed or workspace swaps."""
        if view is None:
            return
        key = id(view)
        self._account_last_site22.pop(key, None)
        self._account_presented22.pop(key, None)

    def _on_account_url22(self, view, url):
        site = page_site22(url)
        key = id(view)
        if self._account_last_site22.get(key) != site:
            self._account_last_site22[key] = site
            self._account_presented22.pop(key, None)
        self._schedule_site_account22(view, site)

    def _on_account_tab_selected22(self, index):
        if index < 0:
            return
        view = self.tabs.widget(index)
        if view is None:
            return
        try:
            self._schedule_site_account22(view, page_site22(view.url()))
        except RuntimeError:
            return

    def _schedule_site_account22(self, view, site):
        key = id(view)
        if (not site or view is not self.current()
                or self._account_presented22.get(key) == site):
            return
        if any(r["site"] == site and r.get("space", "private") == self._account_space22() for r in self._accounts_doc22["accounts"]):
            # Recheck at display time: navigation or focus may change.
            QTimer.singleShot(350, lambda v=view, s=site: self._show_site_accounts22(v, s))

    def _show_site_accounts22(self, view, site):
        try:
            if view is not self.current() or page_site22(view.url()) != site:
                return
        except RuntimeError:
            return
        key = id(view)
        if self._account_presented22.get(key) == site:
            return
        if not any(r["site"] == site and r.get("space", "private") == self._account_space22() for r in self._accounts_doc22["accounts"]):
            return
        self._account_presented22[key] = site
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
        # Normalize legacy cards only after encrypted atomic replacement succeeded.
        self._accounts_doc22 = doc
        notify = getattr(self, "_queue_auto_sync23", None)
        if callable(notify):
            notify()

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
        code_api = QLineEdit(dialog)
        code_api.setPlaceholderText("可选：HTTPS 接码 API 地址（仅点击时访问）")
        layout.addRow("验证码 API", code_api)
        save = QPushButton("加密保存", dialog)
        save.clicked.connect(dialog.accept)
        layout.addRow(save)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        record = {"site": site, "name": name.text().strip(),
                  "username": username.text(), "password": password.text(),
                  "code_api": code_api.text().strip()}
        record["space"] = self._account_space22()
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

    def update_account22(self, site, original_name, name, username, password, code_api=None):
        """Update one stored card atomically; never alter ciphertext on invalid input."""
        if self._accounts_readonly22:
            return False
        old = self._accounts_doc22
        space = self._account_space22()
        index = next((i for i, r in enumerate(old["accounts"])
                      if r["site"] == site and r["name"] == original_name
                      and r.get("space", "private") == space), -1)
        if index < 0:
            return False
        records = [dict(r) for r in old["accounts"]]
        candidate = {"schema": 1, "accounts": records}
        try:
            if not isinstance(name, str):
                return False
            records[index] = {"site": site, "name": name.strip(),
                              "username": username, "password": password,
                              "code_api": records[index].get("code_api", "") if code_api is None else code_api,
                              "space": space}
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
        code_api = QLineEdit(record.get("code_api", ""), dialog)
        code_api.setPlaceholderText("可选：HTTPS 接码 API 地址")
        layout.addRow("验证码 API", code_api)
        button = QPushButton("保存修改", dialog)
        button.clicked.connect(dialog.accept)
        layout.addRow(button)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if not self.update_account22(site, record["name"], name.text(),
                                     username.text(), password.text(), code_api.text().strip()):
            QMessageBox.warning(self, "Glacier", "修改未保存；原有资料保持不变。")
            return False
        return True

    def delete_account22(self, site, name):
        if self._accounts_readonly22:
            return False
        previous = self._accounts_doc22
        space = self._account_space22()
        remaining = [r for r in previous["accounts"]
                     if not (r["site"] == site and r["name"] == name
                             and r.get("space", "private") == space)]
        if len(remaining) == len(previous["accounts"]):
            return False
        self._accounts_doc22 = {"schema": 1, "accounts": remaining}
        try:
            self._save_accounts22()
        except (OSError, ValueError):
            self._accounts_doc22 = previous
            return False
        return True

    def manage_accounts22(self):
        """Local vault directory: expose site names, never passwords in the list."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Glacier · 网站账号管理")
        dialog.resize(540, 410)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("所有账号仅保存在本机加密资料库。选择网站后查看、编辑或删除。", dialog))
        search = QLineEdit(dialog)
        search.setPlaceholderText("搜索网站域名或账号备注")
        layout.addWidget(search)
        items = QListWidget(dialog)
        layout.addWidget(items, 1)
        footer = QHBoxLayout()
        open_button = QPushButton("查看所选网站", dialog)
        add_button = QPushButton("添加账号", dialog)
        footer.addWidget(open_button)
        footer.addWidget(add_button)
        layout.addLayout(footer)

        def refresh(query=""):
            items.clear()
            space = self._account_space22()
            local = [r for r in self._accounts_doc22["accounts"]
                     if r.get("space", "private") == space]
            for site, count in account_site_summary22(local, query):
                from PySide6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(site + "  ·  " + str(count) + " 个账号")
                item.setData(Qt.ItemDataRole.UserRole, site)
                items.addItem(item)

        def open_selected():
            item = items.currentItem()
            if item is None:
                return
            site = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(site, str) or not safe_site22(site):
                return
            dialog.accept()
            self.show_accounts22(site)

        def add_new():
            dialog.accept()
            self.add_account22()

        search.textChanged.connect(refresh)
        open_button.clicked.connect(open_selected)
        items.itemDoubleClicked.connect(lambda _item: open_selected())
        add_button.clicked.connect(add_new)
        refresh()
        dialog.exec()

    def request_account_code22(self, endpoint, dialog):
        """One explicit HTTPS GET via the configured local SOCKS5 port.

        No implicit direct fallback, automatic refresh, redirects or response
        logging. A code is shown only after a valid user-initiated response.
        """
        if safe_code_api22(endpoint) != endpoint or not getattr(self, "proxy_port", 0):
            QMessageBox.warning(dialog, "Glacier", "验证码 API 地址无效或代理未配置。")
            return
        if not getattr(self, "proc", None) or self.proc.poll() is not None:
            QMessageBox.warning(dialog, "Glacier", "代理内核未运行，已拒绝直连。")
            return
        manager = QNetworkAccessManager(dialog)
        manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.Socks5Proxy,
                                       "127.0.0.1", int(self.proxy_port)))
        request = QNetworkRequest(QUrl(endpoint))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(12000)
        reply = manager.get(request)
        def finished():
            try:
                if reply.error() != reply.NetworkError.NoError:
                    QMessageBox.warning(dialog, "Glacier", "接码请求未成功；请检查代理与 API 配置。")
                    return
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if status != 200:
                    QMessageBox.warning(dialog, "Glacier", "接码接口未返回成功状态。")
                    return
                data = bytes(reply.readAll())
                code = extract_code22(data)
                if not code:
                    QMessageBox.information(dialog, "Glacier", "接口未返回可识别的 4–10 位数字验证码。")
                    return
                self._copy_account22(code)
                QMessageBox.information(dialog, "Glacier", "验证码已复制到剪贴板，30 秒后自动清除。")
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)

    def show_accounts22(self, site=None):
        if site is None:
            view = self.current()
            site = page_site22(view.url()) if view is not None else ""
        site = safe_site22(site) if site else ""
        if not site:
            QMessageBox.information(self, "Glacier", "当前页面没有可匹配的 HTTPS 网站域名。")
            return
        space = self._account_space22()
        entries = [r for r in self._accounts_doc22["accounts"]
                   if r["site"] == site and r.get("space", "private") == space]
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
            if record.get("code_api"):
                code_button = QPushButton("获取验证码", dialog)
                code_button.clicked.connect(
                    lambda checked=False, ep=record["code_api"]: self.request_account_code22(ep, dialog))
                row.addWidget(code_button)
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
