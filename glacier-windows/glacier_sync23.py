"""Glacier Sync v1 desktop: explicit E2E encrypted account sync.

This module never sends plaintext credentials or the vault passphrase to the
sync server. HTTPS requests go through Glacier's own SOCKS5 proxy, with no
environment-proxy or direct-connection fallback.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from glacier_accounts22 import clean_accounts22


DEFAULT_SYNC_URL23 = "https://sync.borealos.cn"


class SyncError23(Exception):
    pass


def sync_url23(raw):
    if not isinstance(raw, str):
        return ""
    raw = raw.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)
                or parsed.path or parsed.query or parsed.fragment
                or parsed.hostname in ("localhost", "127.0.0.1")):
            return ""
    except ValueError:
        return ""
    return raw


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text):
    if not isinstance(text, str) or len(text) > 400000:
        raise SyncError23("Invalid vault encoding")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encrypt_space23(records, space, password):
    if space not in ("private", "work") or len(password) < 12:
        raise SyncError23("Invalid encryption passphrase or space")
    doc = clean_accounts22({"schema": 1, "accounts": records})
    if any(record.get("space", "private") != space
           for record in doc["accounts"]):
        raise SyncError23("Cross-space account data rejected")
    plain = json.dumps({"schema": 1, "space": space, "accounts": doc["accounts"]},
                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(plain) > 150000:
        raise SyncError23("Account space too large to sync")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=400000).derive(password.encode("utf-8"))
    context = ("glacier-sync-v1:" + space).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plain, context)
    return json.dumps({"format": "glacier-vault-v1",
                       "kdf": "pbkdf2-sha256-400k",
                       "salt": _b64(salt),
                       "nonce": _b64(nonce), "ciphertext": _b64(ciphertext)},
                      separators=(",", ":"))


def decrypt_space23(envelope, space, password):
    if space not in ("private", "work") or len(password) < 12:
        raise SyncError23("Invalid encryption passphrase or space")
    try:
        doc = json.loads(envelope)
        if (not isinstance(doc, dict) or doc.get("format") != "glacier-vault-v1"
                or doc.get("kdf") != "pbkdf2-sha256-400k"):
            raise ValueError("Bad envelope")
        salt, nonce, ciphertext = (_unb64(doc[k])
                                   for k in ("salt", "nonce", "ciphertext"))
        if len(salt) != 16 or len(nonce) != 12 or len(ciphertext) > 200000:
            raise ValueError("Bad encrypted length")
        key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                            salt=salt, iterations=400000).derive(
                                password.encode("utf-8"))
        plaintext = AESGCM(key).decrypt(nonce, ciphertext,
                                      ("glacier-sync-v1:" + space).encode("utf-8"))
        if len(plaintext) > 150000:
            raise ValueError("Bad plaintext length")
        parsed = json.loads(plaintext)
        if parsed.get("schema") != 1 or parsed.get("space") != space:
            raise ValueError("Wrong account space")
        cards = clean_accounts22({"schema": 1, "accounts": parsed["accounts"]})
        if any(c.get("space", "private") != space for c in cards["accounts"]):
            raise ValueError("Cross-space data")
        return cards["accounts"]
    except (ValueError, KeyError, UnicodeError, TypeError) as error:
        raise SyncError23("Vault data malformed or wrong passphrase") from error
    except Exception as error:
        raise SyncError23("Vault cannot be decrypted; local records were not changed") from error


class SyncTransport23:
    def __init__(self, base, port, token=""):
        self.base = sync_url23(base)
        if not self.base or not isinstance(port, int) or not (1 <= port <= 65535):
            raise SyncError23("Secure Glacier Sync URL or proxy port invalid")
        self.port = port
        self.token = token

    def call(self, method, path, data=None):
        if not path.startswith("/v1/"):
            raise SyncError23("Unsupported sync request")
        sess = requests.Session()
        sess.trust_env = False
        proxy = "socks5h://127.0.0.1:" + str(self.port)
        sess.proxies = {"http": proxy, "https": proxy}
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            with sess.request(method, self.base + path, json=data, headers=headers,
                              timeout=(6, 12), allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    raise SyncError23("Redirects are refused")
                if response.status_code >= 400:
                    raise SyncError23("Sync server rejected request (HTTP "
                                      + str(response.status_code) + ")")
                if len(response.content) > 360000:
                    raise SyncError23("Sync response too large")
                return response.json()
        except requests.RequestException as error:
            raise SyncError23("Cannot reach Glacier Sync through VLESS/SOCKS5") from error
        finally:
            sess.close()


class GlacierSync23:
    def setup_sync23(self, directory, encrypt, decrypt):
        self._sync_path23 = Path(directory) / "sync-account-v1.enc"
        self._sync_encrypt23 = encrypt
        self._sync_decrypt23 = decrypt
        self._sync_state23 = {}
        if self._sync_path23.exists():
            try:
                if self._sync_path23.stat().st_size > 16384:
                    raise ValueError("Sync state too large")
                data = json.loads(decrypt(self._sync_path23.read_bytes()))
                if (not isinstance(data, dict)
                        or sync_url23(data.get("base", "")) != data.get("base", "")
                        or not isinstance(data.get("token", ""), str)):
                    raise ValueError("Invalid sync session")
                self._sync_state23 = data
            except Exception:
                # Never overwrite corrupted session material silently.
                self._sync_state23 = {"locked": True}

    def _save_sync23(self):
        if self._sync_state23.get("locked"):
            raise SyncError23("Existing sync session is unreadable; cannot overwrite it")
        data = json.dumps(self._sync_state23).encode("utf-8")
        blob = self._sync_encrypt23(data)
        if not isinstance(blob, bytes) or blob == data or len(blob) > 16384:
            raise SyncError23("Local session encryption failed")
        self._sync_path23.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".glacier-sync-", dir=self._sync_path23.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(blob)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, self._sync_path23)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _sync_transport23(self, *, auth=True):
        state = self._sync_state23
        if state.get("locked"):
            raise SyncError23("Encrypted account session cannot be opened")
        process = getattr(self, "proc", None)
        if process is None or process.poll() is not None:
            raise SyncError23("VLESS core is offline; refusing direct sync connection")
        if auth and not state.get("token"):
            raise SyncError23("Please log in to Glacier account first")
        return SyncTransport23(state["base"], int(self.proxy_port),
                               state.get("token", "") if auth else "")

    def _prompt_sync23(self, title, label, *, secret=False):
        value, ok = QInputDialog.getText(
            self, title, label,
            QLineEdit.EchoMode.Password if secret else QLineEdit.EchoMode.Normal)
        return value if ok else None

    def _sync_info23(self, message):
        QMessageBox.information(self, "Glacier 统一账号", message)

    def _sync_error23(self, error):
        # Never show raw request URLs, tokens, response body or vault secrets.
        QMessageBox.warning(self, "Glacier 统一账号", str(error))

    def show_sync23(self):
        if self._sync_state23.get("locked"):
            self._sync_error23(SyncError23("已保存的同步会话无法解密；旧文件保持不变。"))
            return
        choices = ["注册统一账号", "登录 / 申请新设备授权",
                   "检查设备审批状态", "管理已授权设备",
                   "上传当前账号空间（加密）", "下载当前账号空间（解密）",
                   "退出当前设备账号"]
        current = self._sync_state23.get("username", "未登录")
        selected, ok = QInputDialog.getItem(
            self, "Glacier 统一账号 · " + current,
            "账号资料只传输密文；首次注册需要服务端邀请口令。", choices, 0, False)
        if not ok:
            return
        try:
            if selected == choices[0]:
                self._sync_register23()
            elif selected == choices[1]:
                self._sync_login23()
            elif selected == choices[2]:
                self._sync_activate23()
            elif selected == choices[3]:
                self._sync_devices23()
            elif selected == choices[4]:
                self._sync_push23()
            elif selected == choices[5]:
                self._sync_pull23()
            else:
                self._sync_logout23()
        except (SyncError23, ValueError, OSError) as error:
            self._sync_error23(error)

    def _sync_register23(self):
        base = self._prompt_sync23("同步服务器", "https://sync.borealos.cn（留空使用默认地址）")
        if base == "":
            base = DEFAULT_SYNC_URL23
        if base is None:
            return
        if not sync_url23(base):
            raise SyncError23("Sync server URL must use HTTPS with no path")
        username = self._prompt_sync23("创建 Glacier 账号", "账号 ID（字母与数字）")
        password = self._prompt_sync23("创建 Glacier 账号", "登录密码（至少 12 位）", secret=True)
        invite = self._prompt_sync23("创建 Glacier 账号", "管理员提供的注册邀请码", secret=True)
        if None in (username, password, invite):
            return
        if len(password) < 12:
            raise SyncError23("Login password must contain at least 12 characters")
        import platform
        result = SyncTransport23(base, int(self.proxy_port)).call(
            "POST", "/v1/register", {"invite": invite, "username": username,
                                    "password": password,
                                    "device_name": platform.node()[:80] or "Glacier Desktop"})
        self._sync_state23 = {"base": sync_url23(base), "username": username,
                              "device_id": result["device_id"],
                              "token": result["token"], "approved": True}
        self._save_sync23()
        self._sync_info23("已注册，当前设备成为主设备。\n请单独牢记云端保险箱加密口令；它不会上传服务器。")

    def _sync_login23(self):
        base = self._sync_state23.get("base")
        if not base:
            base = self._prompt_sync23("同步服务器", "https://同步服务域名")
        if base is None or not sync_url23(base):
            return
        username = self._prompt_sync23("Glacier 登录", "账号 ID")
        password = self._prompt_sync23("Glacier 登录", "登录密码", secret=True)
        if username is None or password is None:
            return
        import platform
        result = SyncTransport23(base, int(self.proxy_port)).call(
            "POST", "/v1/login", {"username": username, "password": password,
                                  "device_name": platform.node()[:80] or "Glacier Desktop",
                                  "device_id": (self._sync_state23.get("device_id")
                                                if username == self._sync_state23.get("username")
                                                and sync_url23(base) == self._sync_state23.get("base")
                                                else None)})
        self._sync_state23 = {"base": sync_url23(base), "username": username,
                              "device_id": result["device_id"], "token": result["token"],
                              "approved": result["approved"]}
        self._save_sync23()
        self._sync_info23("登录成功。" if result["approved"] else
                          "新设备正在等待主设备审批。\n设备 ID：" + result["device_id"])

    def _sync_activate23(self):
        transport = self._sync_transport23()
        status = transport.call("GET", "/v1/session")
        if not status["approved"]:
            self._sync_info23("此设备尚未获得主设备批准。")
            return
        if status.get("pending"):
            result = transport.call("POST", "/v1/session/activate")
            self._sync_state23["token"] = result["token"]
            self._sync_state23["approved"] = True
            self._save_sync23()
        self._sync_info23("设备已授权，可以同步已允许的账号空间。")

    def _sync_devices23(self):
        transport = self._sync_transport23()
        device_list = transport.call("GET", "/v1/devices")["devices"]
        labels = [d["name"] + " · " + d["id"][:10] +
                  (" · 待审批" if not d["approved"] else
                   " · " + ",".join(d["spaces"])) for d in device_list]
        selected, ok = QInputDialog.getItem(self, "已授权设备", "选择设备：",
                                            labels, 0, False)
        if not ok or not selected:
            return
        entry = device_list[labels.index(selected)]
        actions = ["批准新设备", "仅共享私人空间", "共享私人和工作空间", "撤销设备"]
        action, ok = QInputDialog.getItem(self, "设备操作", "仅主设备可授权或撤销：",
                                          actions, 0, False)
        if not ok:
            return
        path = "/v1/devices/" + entry["id"]
        if action == actions[0]:
            transport.call("POST", path + "/approve")
        elif action in (actions[1], actions[2]):
            transport.call("PUT", path + "/grants", {"spaces":
                           ["private"] if action == actions[1] else ["private", "work"]})
        elif action == actions[3]:
            if QMessageBox.question(self, "撤销设备", "撤销后设备无法再同步资料，确定？") != QMessageBox.StandardButton.Yes:
                return
            transport.call("DELETE", path)
        self._sync_info23("设备操作已完成。")

    def _sync_space23(self):
        workspace = getattr(self, "_workspace_doc17", {}).get("active", "default")
        return "private" if workspace == "default" else "work"

    def _sync_passphrase23(self):
        value = self._prompt_sync23("端到端加密口令", "输入云端保险箱口令（至少 12 位）", secret=True)
        if value is None:
            return None
        if len(value) < 12:
            raise SyncError23("Vault passphrase must contain at least 12 characters")
        return value

    def _sync_push23(self):
        transport = self._sync_transport23()
        space = self._sync_space23()
        remote = transport.call("GET", "/v1/vault/" + space)
        if remote["version"]:
            if QMessageBox.question(
                self, "覆盖远端账号资料",
                "远端此账号空间已有记录。上传会替换远端密文，确定继续？"
            ) != QMessageBox.StandardButton.Yes:
                return
        password = self._sync_passphrase23()
        if password is None:
            return
        records = [r for r in self._accounts_doc22["accounts"]
                   if r.get("space", "private") == space]
        payload = encrypt_space23(records, space, password)
        transport.call("PUT", "/v1/vault/" + space,
                       {"expected_version": remote["version"], "envelope": payload})
        self._sync_info23("当前账号空间已端到端加密上传。")

    def _sync_pull23(self):
        transport = self._sync_transport23()
        space = self._sync_space23()
        remote = transport.call("GET", "/v1/vault/" + space)
        if not remote.get("envelope"):
            self._sync_info23("这个账号空间暂时没有云端资料。")
            return
        password = self._sync_passphrase23()
        if password is None:
            return
        cards = decrypt_space23(remote["envelope"], space, password)
        if self._accounts_readonly22:
            raise SyncError23("Local account vault is read-only")
        if QMessageBox.question(
            self, "下载加密账号资料",
            "下载将替换当前账号空间的本地账号卡片；其他账号空间不变。确定继续？"
        ) != QMessageBox.StandardButton.Yes:
            return
        previous = self._accounts_doc22
        keep = [r for r in previous["accounts"]
                if r.get("space", "private") != space]
        self._accounts_doc22 = clean_accounts22(
            {"schema": 1, "accounts": keep + cards})
        try:
            self._save_accounts22()
        except Exception:
            self._accounts_doc22 = previous
            raise SyncError23("Local encrypted save failed; previous records restored")
        self._sync_info23("当前账号空间已解密导入本机。")

    def _sync_logout23(self):
        if self._sync_state23.get("token"):
            try:
                self._sync_transport23().call("POST", "/v1/logout")
            except SyncError23:
                pass
        self._sync_state23["token"] = ""
        self._save_sync23()
        self._sync_info23("已退出云端会话，本机账号资料未删除。")
