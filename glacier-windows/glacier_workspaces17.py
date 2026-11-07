"""Glacier Browser v0.17: encrypted local workspaces and colored tab groups.

Uses the browser's existing Windows DPAPI / macOS Keychain-backed cipher.
No sync server, external requests, or plaintext URL persistence.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QToolButton


WORKSPACE_LIMIT17 = 12
GROUP_LIMIT17 = 16
TAB_LIMIT17 = 80
STORAGE_LIMIT17 = 1024 * 1024
PALETTE17 = ("#2786b1", "#8450bb", "#148a79", "#ba7629",
             "#ba5381", "#658324", "#d25c52", "#3c76a5")


def _safe_url17(raw):
    """Only save navigable web pages and never persist URL credentials."""
    if not isinstance(raw, str) or len(raw) > 4096:
        return ""
    try:
        parts = urlsplit(raw)
        if (parts.scheme.lower() not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None):
            return ""
        if any(ord(ch) < 32 for ch in raw):
            return ""
        # Reject malformed ports without opening a network connection.
        _ = parts.port
    except ValueError:
        return ""
    return raw


def _default_workspace17():
    return {"id": "default", "name": "默认工作区", "groups": [],
            "tabs": [], "selected": 0}


def _clean_workspaces17(raw):
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise ValueError("unsupported workspace schema")
    entries = raw.get("items")
    if not isinstance(entries, list) or not 1 <= len(entries) <= WORKSPACE_LIMIT17:
        raise ValueError("invalid workspace count")
    cleaned = []
    seen = set()
    for ws in entries:
        if not isinstance(ws, dict):
            raise ValueError("invalid workspace")
        key, name = ws.get("id"), ws.get("name")
        if (not isinstance(key, str) or not (1 <= len(key) <= 64)
                or key in seen or not isinstance(name, str)
                or not (1 <= len(name.strip()) <= 36)):
            raise ValueError("invalid workspace identity")
        seen.add(key)
        groups = ws.get("groups", [])
        tabs = ws.get("tabs", [])
        if (not isinstance(groups, list) or len(groups) > GROUP_LIMIT17
                or not isinstance(tabs, list) or len(tabs) > TAB_LIMIT17):
            raise ValueError("workspace limits exceeded")
        cleaned_groups = []
        group_ids = set()
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("invalid tab group")
            group_id, group_name = group.get("id"), group.get("name")
            if (not isinstance(group_id, str) or not (1 <= len(group_id) <= 64)
                    or group_id in group_ids or not isinstance(group_name, str)
                    or not (1 <= len(group_name.strip()) <= 28)):
                raise ValueError("invalid tab group")
            group_ids.add(group_id)
            cleaned_groups.append({"id": group_id, "name": group_name.strip()})
        cleaned_tabs = []
        for tab in tabs:
            if not isinstance(tab, dict) or not _safe_url17(tab.get("url")):
                raise ValueError("invalid workspace URL")
            group_id = tab.get("group")
            if group_id is not None and group_id not in group_ids:
                raise ValueError("unknown tab group")
            cleaned_tabs.append({"url": tab["url"], "group": group_id})
        selected = ws.get("selected", 0)
        if type(selected) is not int or selected < 0:
            selected = 0
        cleaned.append({"id": key, "name": name.strip(),
                        "groups": cleaned_groups, "tabs": cleaned_tabs,
                        "selected": min(selected, max(0, len(cleaned_tabs) - 1))})
    active = raw.get("active")
    if active not in seen:
        raise ValueError("unknown active workspace")
    return {"schema": 1, "active": active, "items": cleaned}


class GlacierWorkspaces17:
    """Multiple local workspaces and group labels without modifying WebEngine."""

    def initialize_workspace_profiles17(self, data_directory, cipher):
        """Pick the active workspace profile before creating WebEngine tabs.

        Legacy default profile remains at its original storage path; other
        workspaces use physically separate cookies, caches and service workers.
        Never copy shared legacy cookies into a newly isolated workspace.
        """
        self._workspace_profiles17 = {"default": self.profile}
        self._workspace_profile_root17 = Path(data_directory) / "workspace-profiles"
        path = Path(data_directory) / "workspaces-v17.enc"
        active = "default"
        if path.exists():
            try:
                if path.stat().st_size > STORAGE_LIMIT17:
                    raise ValueError("workspace store too large")
                doc = _clean_workspaces17(json.loads(
                    cipher(path.read_bytes(), True).decode("utf-8")))
                active = doc["active"]
            except Exception:
                # setup_workspaces17 will preserve and report corrupted data.
                active = "default"
        self.profile = self._workspace_profile17(active)

    def _workspace_profile17(self, wid):
        profiles = getattr(self, "_workspace_profiles17", None)
        if profiles is None:
            # Non-WebEngine consumers may use workspace tab snapshots alone.
            return getattr(self, "profile", None)
        if wid in profiles:
            return profiles[wid]
        digest = hashlib.sha256(wid.encode("utf-8")).hexdigest()[:24]
        base = self._workspace_profile_root17 / digest
        profile = QWebEngineProfile("Glacier-space-" + digest, self)
        profile.setPersistentStoragePath(str(base / "profile"))
        profile.setCachePath(str(base / "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        profiles[wid] = profile
        return profile

    def setup_workspaces17(self, nav, data_directory, cipher):
        self._workspace_file17 = Path(data_directory) / "workspaces-v17.enc"
        self._workspace_cipher17 = cipher
        self._workspace_readonly17 = False
        self._workspace_switching17 = False
        self._workspace_group_by_view17 = {}
        self._workspace_bound_views19 = set()
        self._workspace_doc17 = {"schema": 1, "active": "default",
                                  "items": [_default_workspace17()]}
        path = self._workspace_file17
        if path.exists():
            try:
                if path.stat().st_size > STORAGE_LIMIT17:
                    raise ValueError("workspace file too large")
                plaintext = cipher(path.read_bytes(), True)
                self._workspace_doc17 = _clean_workspaces17(json.loads(
                    plaintext.decode("utf-8")))
            except (OSError, ValueError, TypeError, UnicodeError, KeyError, Exception) as exc:
                # Preserve unreadable encrypted data rather than clobbering it.
                self._workspace_readonly17 = True
                self.statusBar().showMessage(
                    "工作区文件无法解密或解析，旧文件保留；为防丢失已禁用写入", 12000)

        self._workspace_timer17 = QTimer(self)
        self._workspace_timer17.setSingleShot(True)
        self._workspace_timer17.setInterval(950)
        self._workspace_timer17.timeout.connect(self._save_active_workspace17)

        workspace_button = QToolButton(self)
        workspace_button.setObjectName("GlacierWorkspaceButton17")
        workspace_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        workspace_button.setToolTip("独立工作区：Cookie、网站存储、标签与分组均分别保存")
        workspace_button.setMinimumWidth(120)
        workspace_menu = QMenu(workspace_button)
        workspace_menu.aboutToShow.connect(self._build_workspace_menu17)
        workspace_button.setMenu(workspace_menu)
        nav.addWidget(workspace_button)
        self._workspace_button17 = workspace_button
        self._workspace_menu17 = workspace_menu

        group_button = QToolButton(self)
        group_button.setObjectName("GlacierTabGroupsButton17")
        group_button.setText("◉ 分组")
        group_button.setToolTip("为当前标签设置彩色分组")
        group_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        group_menu = QMenu(group_button)
        group_menu.aboutToShow.connect(self._build_group_menu17)
        group_button.setMenu(group_menu)
        nav.addWidget(group_button)
        self._group_menu17 = group_menu
        self._group_button17 = group_button

        # Existing session restoration from v0.16 is authoritative at startup.
        # Attach group metadata only to matching restored tabs; never replace tabs
        # just because a v0.17 workspace file exists.
        self._restore_current_groups17()
        # v0.18 restored tabs before this workspace layer was initialized.
        # Register their URL changes too, without immediately rewriting the
        # encrypted workspace snapshot while startup is still settling.
        for i in range(self.tabs.count()):
            self._workspace_register17(self.tabs.widget(i), queue=False)
        self._update_workspace_controls17()
        self.tabs.currentChanged.connect(lambda _index: self._queue_workspace_save17())
        self.setStyleSheet(self.styleSheet() + """
QToolButton#GlacierWorkspaceButton17,QToolButton#GlacierTabGroupsButton17 {
  background:#e4f1fa; border:1px solid #b9d9eb; border-radius:10px;
  color:#255d7d; padding:6px 11px; min-height:24px;
}
QToolButton#GlacierWorkspaceButton17:hover,QToolButton#GlacierTabGroupsButton17:hover {
  background:#cfe8f7;
}
""")

    def _active_workspace17(self):
        key = self._workspace_doc17["active"]
        return next(ws for ws in self._workspace_doc17["items"] if ws["id"] == key)

    def _restore_current_groups17(self):
        current = self._active_workspace17()
        rows = current["tabs"]
        if len(rows) != self.tabs.count():
            return
        for i, row in enumerate(rows):
            view = self.tabs.widget(i)
            try:
                url = _safe_url17(view.url().toString())
            except (RuntimeError, AttributeError):
                url = ""
            if url == row["url"] and row["group"]:
                self._workspace_group_by_view17[id(view)] = row["group"]
        self._decorate_group_tabs17()

    def _capture_workspace17(self):
        if self.tabs.count() > TAB_LIMIT17:
            raise ValueError("工作区最多保存 80 个标签，请先关闭部分标签")
        ws = self._active_workspace17()
        rows = []
        selected = 0
        for i in range(self.tabs.count()):
            view = self.tabs.widget(i)
            try:
                url = _safe_url17(view.url().toString())
            except (RuntimeError, AttributeError):
                continue
            if url:
                if i == self.tabs.currentIndex():
                    selected = len(rows)
                rows.append({"url": url,
                             "group": self._workspace_group_by_view17.get(id(view))})
        ws["tabs"] = rows
        ws["selected"] = selected

    def _write_workspaces17(self):
        if self._workspace_readonly17:
            return False
        dest = self._workspace_file17
        data = json.dumps(self._workspace_doc17, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        if len(data) > STORAGE_LIMIT17:
            raise ValueError("工作区保存的数据超过大小限制")
        tmp = dest.with_name(dest.name + "." + secrets.token_hex(6) + ".tmp")
        try:
            payload = self._workspace_cipher17(data)
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                raise
            os.replace(tmp, dest)
            return True
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _queue_workspace_save17(self):
        if (not getattr(self, "_workspace_switching17", True)
                and not self._workspace_readonly17):
            self._workspace_timer17.start()

    def _save_active_workspace17(self):
        if self._workspace_switching17 or self._workspace_readonly17:
            return
        try:
            self._capture_workspace17()
            self._write_workspaces17()
        except (OSError, ValueError, RuntimeError):
            self.statusBar().showMessage("工作区保存失败；原有工作区数据保持不变", 6500)

    def flush_workspaces17(self):
        if hasattr(self, "_workspace_timer17"):
            self._workspace_timer17.stop()
            self._save_active_workspace17()

    def _workspace_register17(self, view, *, queue=True):
        if not hasattr(self, "_workspace_group_by_view17") or view is None:
            return
        ident = id(view)
        if ident in self._workspace_bound_views19:
            return
        self._workspace_bound_views19.add(ident)
        view.urlChanged.connect(lambda _url: self._queue_workspace_save17())
        view.titleChanged.connect(lambda _title: self._decorate_group_tabs17())
        if queue:
            self._queue_workspace_save17()

    def _workspace_forget17(self, view):
        if hasattr(self, "_workspace_group_by_view17"):
            self._workspace_group_by_view17.pop(id(view), None)
            self._workspace_bound_views19.discard(id(view))
            self._queue_workspace_save17()

    def _update_workspace_controls17(self):
        if not hasattr(self, "_workspace_button17"):
            return
        name = self._active_workspace17()["name"]
        self._workspace_button17.setText("▦ " + name[:18])
        self._decorate_group_tabs17()

    def _decorate_group_tabs17(self):
        if not hasattr(self, "_workspace_group_by_view17"):
            return
        group_defs = self._active_workspace17()["groups"]
        info = {g["id"]: (g["name"], PALETTE17[i % len(PALETTE17)])
                for i, g in enumerate(group_defs)}
        bars = [self.tabs.tabBar()]
        if hasattr(self, "chrome_tab14"):
            bars.append(self.chrome_tab14)
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            group = info.get(self._workspace_group_by_view17.get(id(view)))
            for bar in bars:
                if index >= bar.count():
                    continue
                if group:
                    name, color = group
                    bar.setTabTextColor(index, QColor(color))
                    bar.setTabToolTip(index, "标签分组：" + name)
                else:
                    bar.setTabTextColor(index, QColor("#365b72"))
                    bar.setTabToolTip(index, "")

    def refresh_tabs14(self):
        result = super().refresh_tabs14()
        if hasattr(self, "_workspace_doc17"):
            self._decorate_group_tabs17()
        return result

    def _build_workspace_menu17(self):
        menu = self._workspace_menu17
        menu.clear()
        for item in self._workspace_doc17["items"]:
            key = item["id"]
            action = menu.addAction(item["name"])
            action.setCheckable(True)
            action.setChecked(key == self._workspace_doc17["active"])
            action.triggered.connect(
                lambda checked=False, wid=key: self.switch_workspace17(wid))
        menu.addSeparator()
        menu.addAction("＋ 新建工作区", self._prompt_new_workspace17)
        menu.addAction("重命名当前工作区", self._prompt_rename_workspace17)
        menu.addAction("删除当前工作区", self._prompt_delete_workspace17)

    def _prompt_new_workspace17(self):
        name, ok = QInputDialog.getText(self, "新建工作区", "工作区名称：")
        if ok:
            self.create_workspace17(name)

    def create_workspace17(self, name):
        name = str(name).strip()
        if not name or len(name) > 36:
            return False
        if self._workspace_readonly17 or len(self._workspace_doc17["items"]) >= WORKSPACE_LIMIT17:
            self.statusBar().showMessage("工作区不可写或已达到数量上限", 5000)
            return False
        try:
            self._capture_workspace17()
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return False
        wid = secrets.token_hex(8)
        self._workspace_doc17["items"].append(
            {"id": wid, "name": name, "groups": [], "tabs": [], "selected": 0})
        return self.switch_workspace17(wid, skip_capture=True)

    def switch_workspace17(self, wid, *, skip_capture=False):
        if self._workspace_readonly17:
            return False
        if wid == self._workspace_doc17["active"]:
            return True
        dest = next((x for x in self._workspace_doc17["items"] if x["id"] == wid), None)
        if dest is None:
            return False
        self._workspace_timer17.stop()
        if not skip_capture:
            try:
                self._capture_workspace17()
            except ValueError as exc:
                self.statusBar().showMessage(str(exc), 6500)
                return False
        self._workspace_switching17 = True
        try:
            # Switch the actual WebEngine profile BEFORE constructing tabs.
            # Cookies/localStorage/service workers never cross workspaces.
            profile = self._workspace_profile17(wid)
            if profile is not None:
                self.profile = profile
            self._workspace_doc17["active"] = wid
            self._workspace_group_by_view17.clear()
            for index in reversed(range(self.tabs.count())):
                view = self.tabs.widget(index)
                cleanup = getattr(self, "cleanup_closed13", None)
                if callable(cleanup):
                    cleanup(view)
                self.tabs.removeTab(index)
                view.deleteLater()
            for row in dest["tabs"]:
                view = self.new_tab()
                view.setUrl(QUrl(row["url"]))
                if row["group"]:
                    self._workspace_group_by_view17[id(view)] = row["group"]
            if not self.tabs.count():
                self.new_tab()
            self.tabs.setCurrentIndex(min(dest["selected"], self.tabs.count() - 1))
        finally:
            self._workspace_switching17 = False
        self.refresh_tabs14()
        self._update_workspace_controls17()
        self._save_active_workspace17()
        return True

    def rename_workspace17(self, name):
        name = str(name).strip()
        if self._workspace_readonly17 or not (1 <= len(name) <= 36):
            return False
        self._active_workspace17()["name"] = name
        self._update_workspace_controls17()
        self._queue_workspace_save17()
        return True

    def _prompt_rename_workspace17(self):
        name, ok = QInputDialog.getText(self, "重命名工作区", "新名称：",
                                        text=self._active_workspace17()["name"])
        if ok:
            self.rename_workspace17(name)

    def _prompt_delete_workspace17(self):
        if len(self._workspace_doc17["items"]) <= 1:
            self.statusBar().showMessage("至少保留一个工作区", 4000)
            return
        if QMessageBox.question(self, "删除工作区",
                                "删除当前工作区及其保存的标签列表？") == QMessageBox.StandardButton.Yes:
            self.delete_workspace17()

    def delete_workspace17(self):
        if self._workspace_readonly17 or len(self._workspace_doc17["items"]) <= 1:
            return False
        current = self._workspace_doc17["active"]
        next_id = next(w["id"] for w in self._workspace_doc17["items"]
                       if w["id"] != current)
        # Delete the saved snapshot, not the user's WebEngine profile or files.
        self._workspace_doc17["items"] = [w for w in self._workspace_doc17["items"]
                                           if w["id"] != current]
        self._workspace_doc17["active"] = current
        # Switch without saving the workspace being deleted.
        return self.switch_workspace17(next_id, skip_capture=True)

    def _build_group_menu17(self):
        menu = self._group_menu17
        menu.clear()
        if not self.tabs.count():
            return
        current_view = self.current()
        selected_group = self._workspace_group_by_view17.get(id(current_view))
        for i, group in enumerate(self._active_workspace17()["groups"]):
            label = "● " + group["name"]
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(selected_group == group["id"])
            action.triggered.connect(
                lambda checked=False, gid=group["id"]: self.assign_tab_group17(gid))
        menu.addSeparator()
        menu.addAction("＋ 新建分组", self._prompt_new_group17)
        menu.addAction("移出分组", lambda: self.assign_tab_group17(None))
        menu.addAction("重命名当前分组", self._prompt_rename_group17)
        menu.addAction("删除当前分组", self._prompt_delete_group17)

    def _prompt_new_group17(self):
        name, ok = QInputDialog.getText(self, "新建标签分组", "分组名称：")
        if ok:
            self.create_group17(name)

    def create_group17(self, name):
        name = str(name).strip()
        ws = self._active_workspace17()
        if (self._workspace_readonly17 or not (1 <= len(name) <= 28)
                or len(ws["groups"]) >= GROUP_LIMIT17):
            return False
        if any(g["name"] == name for g in ws["groups"]):
            return False
        gid = secrets.token_hex(6)
        ws["groups"].append({"id": gid, "name": name})
        self.assign_tab_group17(gid)
        return True

    def assign_tab_group17(self, gid):
        ws = self._active_workspace17()
        if self._workspace_readonly17 or not self.tabs.count():
            return False
        if gid is not None and not any(g["id"] == gid for g in ws["groups"]):
            return False
        self._workspace_group_by_view17[id(self.current())] = gid
        self._decorate_group_tabs17()
        self._queue_workspace_save17()
        return True

    def rename_group17(self, gid, name):
        name = str(name).strip()
        if self._workspace_readonly17 or not (1 <= len(name) <= 28):
            return False
        groups = self._active_workspace17()["groups"]
        if any(g["name"] == name and g["id"] != gid for g in groups):
            return False
        for g in groups:
            if g["id"] == gid:
                g["name"] = name
                self._decorate_group_tabs17()
                self._queue_workspace_save17()
                return True
        return False

    def _prompt_rename_group17(self):
        gid = self._workspace_group_by_view17.get(id(self.current()))
        group = next((g for g in self._active_workspace17()["groups"] if g["id"] == gid),
                     None)
        if group is None:
            return
        name, ok = QInputDialog.getText(self, "重命名标签分组", "名称：",
                                        text=group["name"])
        if ok:
            self.rename_group17(gid, name)

    def _prompt_delete_group17(self):
        gid = self._workspace_group_by_view17.get(id(self.current()))
        if gid is not None:
            self.delete_group17(gid)

    def delete_group17(self, gid):
        if self._workspace_readonly17:
            return False
        ws = self._active_workspace17()
        if not any(g["id"] == gid for g in ws["groups"]):
            return False
        ws["groups"] = [g for g in ws["groups"] if g["id"] != gid]
        self._workspace_group_by_view17 = {
            k: v for k, v in self._workspace_group_by_view17.items() if v != gid}
        self._decorate_group_tabs17()
        self._queue_workspace_save17()
        return True
