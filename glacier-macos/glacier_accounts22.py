"""Glacier website-account vault and explicit, same-site click-to-fill.

No automatic credential insertion, form submission, or login automation.
Account injection is only user initiated into its own isolated HTTPS profile.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkRequest
from PySide6.QtWebEngineCore import QWebEngineProfile
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



def cookie_host_matches22(cookie_domain, site):
    """Scope user-requested deletion to this site's exact cookie host.

    Never use an eTLD suffix or a substring match; that could log other
    sites out. A leading RFC 6265 dot is a cookie-domain attribute, not
    permission to broaden this operation to every subdomain.
    """
    if not isinstance(cookie_domain, str) or not isinstance(site, str):
        return False
    if not site or safe_site22(site) != site:
        return False
    domain = cookie_domain.lstrip(".").lower()
    return domain == site or domain == "www." + site



def build_login_fill_script22(site, username, password):
    """Make top-frame, exact-origin, form-only JavaScript for a user click.

    The generated code is never logged, persisted, or sent to the cloud. All
    credential strings use JSON escaping, not HTML or selector interpolation.
    The page's origin is checked a second time at JavaScript execution time.
    """
    if (not isinstance(site, str) or not site or safe_site22(site) != site
            or not isinstance(username, str) or not username
            or not isinstance(password, str) or len(password) > 2048):
        raise ValueError("Invalid saved website identity")
    values = json.dumps({"host": site, "username": username,
                         "password": password}, ensure_ascii=True)
    return "(function(){'use strict';const values=" + values + ";" + r"""
        const host = String(location.hostname || '').toLowerCase();
        const exact = host === values.host || host === 'www.' + values.host;
        if (window.top !== window || location.protocol !== 'https:' ||
            (location.port && location.port !== '443') || !exact ||
            document.readyState === 'loading') return 'refused';

        function usable(el) {
          if (!(el instanceof HTMLInputElement) || !el.isConnected ||
              el.disabled || el.readOnly || !el.getClientRects().length) return false;
          const css = window.getComputedStyle(el);
          return css.display !== 'none' && css.visibility !== 'hidden' &&
                 css.visibility !== 'collapse' && Number(css.opacity) > 0;
        }
        const all = Array.from(document.querySelectorAll('input'));
        const passwords = all.filter(el => el.type === 'password' && usable(el));
        const focused = document.activeElement;
        const activePassword = passwords.find(el => el === focused ||
               (focused && el.form && el.form === focused.form));
        const password = activePassword || passwords[0] || null;
        const sameForm = password && password.form;
        // Without a password input, require explicit username/email
        // semantics to avoid filling arbitrary search or feedback forms.
        const pool = sameForm
          ? Array.from(sameForm.querySelectorAll('input'))
          : all;
        function isUsername(el) {
          if (!usable(el) || !['text','email','tel'].includes(el.type)) return false;
          const autocomplete = String(el.autocomplete || '').toLowerCase().split(/\s+/);
          const hint = [el.name, el.id, el.getAttribute('aria-label'),
                        el.getAttribute('placeholder')].join(' ').toLowerCase();
          return autocomplete.includes('username') || autocomplete.includes('email') ||
                 el.type === 'email' ||
                 /\b(user(name)?|e-?mail|login|account|phone)\b/i.test(hint);
        }
        const username = pool.find(el => isUsername(el)) || null;
        if (!username && !password) return 'no-fields';

        function setInput(el, value) {
          const setter = Object.getOwnPropertyDescriptor(
              HTMLInputElement.prototype, 'value').set;
          setter.call(el, value);
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
        }
        if (username) setInput(username, values.username);
        if (password && values.password) setInput(password, values.password);
        // Never call submit(), requestSubmit(), click() or navigate().
        if (username && password && values.password) return 'filled';
        if (username) return 'username-only';
        if (password && values.password) return 'password-only';
        return 'no-fields';
    })();"""


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
        self._account_profiles22 = {}
        self._account_profiles_root22 = Path(directory) / "account-profiles-v1"
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
        blob = self._accounts_encrypt22(plaintext)
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
        """Show the browser password manager; old vault list is safe fallback."""
        manager = getattr(self, "show_password_manager38", None)
        if callable(manager):
            return manager()
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

    def clear_site_cookies22(self, site):
        """Explicit local-only cookie deletion in the active workspace profile.

        Qt's cookie store loads asynchronously; the signal can report all
        cookies already held by this profile. Never log/read cookie values,
        upload cookies, or touch another workspace's cookie store.
        """
        site = site.strip().lower() if isinstance(site, str) else ""
        if not site or safe_site22(site) != site:
            return False
        profile = getattr(self, "profile", None)
        if profile is None or not callable(getattr(profile, "cookieStore", None)):
            QMessageBox.warning(self, "Glacier", "当前工作空间 Cookie 存储不可用。")
            return False
        decision = QMessageBox.question(
            self, "清除网站 Cookie · " + site,
            "只清除当前工作空间中此域名的 Cookie；不会删除保存的网站账号或密码。"
            "\n该网站可能因此退出登录，且网页可能立即重新创建 Cookie。确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return False
        store = profile.cookieStore()
        requested = {"count": 0}
        def on_cookie(cookie):
            try:
                if cookie_host_matches22(cookie.domain(), site):
                    requested["count"] += 1
                    store.deleteCookie(cookie)
            except (RuntimeError, AttributeError, TypeError):
                return
        store.cookieAdded.connect(on_cookie)
        store.loadAllCookies()
        def finish():
            try:
                store.cookieAdded.disconnect(on_cookie)
            except (RuntimeError, TypeError):
                pass
            # Delete requests are asynchronous: don't falsely report completion.
            self.statusBar().showMessage(
                f"{site}：已提交 {requested['count']} 条 Cookie 删除请求（仅当前空间）。"
                "如网站仍保持登录，请关闭相关标签页后重试。", 8500)
        QTimer.singleShot(1800, finish)
        return True

    def _profile_for_saved_account22(self, record):
        """Create a dedicated persistent WebEngine profile for one saved login.

        Account passwords and Cookie bytes never appear in file or profile names.
        Separate account identities and workspaces cannot share Cookie jars.
        No existing default-workspace profiles are changed or migrated.
        """
        if not isinstance(record, dict):
            return None
        site, username = record.get("site"), record.get("username")
        space = self._account_space22()
        current_ws = getattr(self, "_workspace_doc17", {}).get("active", "default")
        if (not isinstance(site, str) or not site or safe_site22(site) != site
                or not isinstance(username, str) or not username
                or not isinstance(current_ws, str) or not current_ws
                or record.get("space", "private") != space
                or record not in self._accounts_doc22["accounts"]):
            return None
        identity = json.dumps([current_ws, space, site, username],
                              separators=(",", ":"), ensure_ascii=False)
        token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        existing = self._account_profiles22.get(token)
        if existing is not None:
            return existing
        root = self._account_profiles_root22 / token
        profile = QWebEngineProfile("Glacier-account-" + token, self)
        profile.setPersistentStoragePath(str(root / "profile"))
        profile.setCachePath(str(root / "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        self._account_profiles22[token] = profile
        return profile

    def clear_account_session_cookies22(self, record):
        """Clear only a saved login's dedicated local Cookie jar on demand."""
        profile = self._profile_for_saved_account22(record)
        if profile is None:
            return False
        decision = QMessageBox.question(
            self, "清除独立登录 Cookie",
            "这只会清除该账号专属浏览器会话的 Cookie，不会删除账号密码，"
            "也不会影响其他网站账号或普通工作空间。确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return False
        profile.cookieStore().deleteAllCookies()
        self.statusBar().showMessage(
            "已提交此账号独立 Cookie 清除请求；网站可能需要重新登录。", 8500)
        return True

    def open_account_session22(self, record):
        """Open a saved site in its own Cookie/localStorage context.

        This does not auto-inject credentials, impersonate a remote session,
        or share website session tokens between devices.
        """
        profile = self._profile_for_saved_account22(record)
        if profile is None:
            return False
        page = self.new_tab(account_profile=profile)
        if page is None:
            return False
        page.setUrl(QUrl("https://" + record["site"] + "/"))
        return True

    def fill_account_form22(self, record):
        """Fill only the selected, saved account's current isolated HTTPS tab.

        No background tabs, no unrelated workspaces, no auto-submit. The JS
        revalidates top-level origin to fail closed on navigation races.
        """
        profile = self._profile_for_saved_account22(record)
        if profile is None or not isinstance(record, dict):
            return False
        view = self.current()
        if view is None:
            return False
        try:
            page = view.page()
            site = record["site"]
            if (page.profile() is not profile
                    or page_site22(view.url()) != site
                    or page_site22(page.url()) != site):
                self.statusBar().showMessage(
                    "请先使用“在独立会话中打开”，并在对应 HTTPS 登录页手动选择填充。", 8000)
                return False
            script = build_login_fill_script22(
                site, record["username"], record["password"])
        except (RuntimeError, AttributeError, KeyError, TypeError, ValueError):
            return False

        def finished(outcome):
            # Never put credential data, JS source or arbitrary page output
            # into logs or UI. Treat all other results as refusal.
            messages = {
                "filled": "已填入账号和密码，请确认后自行点击登录。",
                "username-only": "已填入账号；如需密码，请进入网站密码输入步骤后再次选择填充。",
                "password-only": "已填入密码，请确认后自行点击登录。",
                "no-fields": "没有发现可填充的可见登录输入框。",
                "refused": "目标网页已变化或尚未加载完成，已拒绝填充。",
            }
            try:
                self.statusBar().showMessage(
                    messages.get(outcome, "未能确认登录输入框，未执行自动登录。"), 9000)
            except RuntimeError:
                pass

        try:
            # ApplicationWorld avoids reusing page-defined JavaScript globals;
            # it still writes normal DOM input values as a user-requested fill.
            page.runJavaScript(script, 1, finished)
        except RuntimeError:
            return False
        return True

    def open_account_site22(self, site):
        """Open the recorded HTTPS site in the active workspace, without login injection."""
        site = site.strip().lower() if isinstance(site, str) else ""
        if not site or safe_site22(site) != site:
            return False
        tab = self.new_tab()
        if tab is None:
            return False
        tab.setUrl(QUrl("https://" + site + "/"))
        return True

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
        layout.addWidget(QLabel("密码只会在你点击“填充当前页”时写入对应 HTTPS 账号会话；不会自动提交。", dialog))
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
            own_session = QPushButton("使用此账号并填充", dialog)
            own_session.setToolTip("此账号使用自己的 Cookie 和网站存储；不会覆盖同站其他账号")
            def open_current_account(checked=False, r=dict(record)):
                use = getattr(self, "use_saved_password38", self.open_account_session22)
                if use(r):
                    dialog.accept()
            own_session.clicked.connect(open_current_account)
            row.addWidget(own_session)
            fill_page = QPushButton("填充当前页", dialog)
            fill_page.setToolTip("只填充此账号专属会话的 HTTPS 登录表单；不会自动提交")
            def fill_current_account(_checked=False, r=dict(record)):
                if self.fill_account_form22(r):
                    dialog.accept()
            fill_page.clicked.connect(fill_current_account)
            row.addWidget(fill_page)
            clear_session = QPushButton("清除此账号 Cookie", dialog)
            clear_session.clicked.connect(
                lambda _checked=False, r=dict(record): self.clear_account_session_cookies22(r))
            row.addWidget(clear_session)
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
        site_actions = QHBoxLayout()
        open_site = QPushButton("在当前空间打开网站", dialog)
        open_site.clicked.connect(
            lambda _checked=False, s=site: (dialog.accept(), self.open_account_site22(s)))
        site_actions.addWidget(open_site)
        clear_cookie = QPushButton("清除本网站 Cookie", dialog)
        clear_cookie.setToolTip("只影响当前工作空间里的此网站；不会清除保存的账号和密码")
        clear_cookie.clicked.connect(
            lambda _checked=False, s=site: self.clear_site_cookies22(s))
        site_actions.addWidget(clear_cookie)
        layout.addLayout(site_actions)
        close = QPushButton("关闭", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
