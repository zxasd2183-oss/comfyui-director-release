"""Glacier Browser v0.17: safe, local download activity center.

Observes the existing Qt WebEngine download handler; never accepts a download
silently, changes proxy routing, downloads outside WebEngine, or bypasses TLS.
Stored download history uses the existing platform encryption function.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton,
    QToolButton, QVBoxLayout,
)


HISTORY_LIMIT17 = 150
HISTORY_BYTES17 = 1024 * 1024
STATE_NAMES17 = {
    "DownloadRequested": "等待确认",
    "DownloadInProgress": "下载中",
    "DownloadCompleted": "已完成",
    "DownloadCancelled": "已取消",
    "DownloadInterrupted": "已中断",
}
ACTIVE_STATES17 = {"requested", "in_progress", "paused"}


def _state_name17(value):
    name = getattr(value, "name", str(value).split(".")[-1])
    return {
        "DownloadRequested": "requested",
        "DownloadInProgress": "in_progress",
        "DownloadCompleted": "completed",
        "DownloadCancelled": "cancelled",
        "DownloadInterrupted": "interrupted",
    }.get(str(name), "interrupted")


def _safe_download_path17(record):
    """Only explicitly open a valid completed filesystem target."""
    if record.get("state") != "completed":
        return None
    filename, directory = record.get("name"), record.get("directory")
    if (not isinstance(filename, str) or not isinstance(directory, str)
            or not filename or len(filename) > 256 or len(directory) > 2048
            or Path(filename).name != filename
            or PureWindowsPath(filename).name != filename):
        return None
    root = Path(directory)
    if not root.is_absolute():
        return None
    target = root / filename
    if not target.is_file():
        return None
    return target


def _clean_download_history17(data):
    if (not isinstance(data, dict) or data.get("schema") != 1
            or not isinstance(data.get("items"), list)):
        raise ValueError("invalid downloads metadata")
    cleaned = []
    for item in data["items"][:HISTORY_LIMIT17]:
        if not isinstance(item, dict):
            continue
        name, directory = item.get("name"), item.get("directory")
        state = item.get("state")
        if (not isinstance(name, str) or len(name) > 256
                or not isinstance(directory, str) or len(directory) > 2048
                or state not in ("requested", "in_progress", "paused",
                                 "completed", "cancelled", "interrupted")):
            continue
        received = item.get("received", 0)
        total = item.get("total", 0)
        if type(received) is not int or type(total) is not int:
            continue
        cleaned.append({
            "id": secrets.token_hex(8), "name": name, "directory": directory,
            "state": ("interrupted" if state in ACTIVE_STATES17 else state),
            "received": max(0, received), "total": max(0, total),
            "created": item.get("created", 0) if type(item.get("created")) in (int, float) else 0
        })
    return cleaned


class GlacierDownloads17:
    """Download observer, pause/resume/cancel controls, encrypted history."""

    def setup_downloads17(self, nav, data_directory, cipher):
        self._downloads_cipher17 = cipher
        self._downloads_file17 = Path(data_directory) / "downloads-v17.enc"
        self._downloads_readonly17 = False
        self._downloads_items17 = []
        self._download_objects17 = {}
        self._downloads_visible17 = []
        self._downloads_dialog17 = None

        path = self._downloads_file17
        if path.exists():
            try:
                if path.stat().st_size > HISTORY_BYTES17:
                    raise ValueError("download history is too large")
                payload = cipher(path.read_bytes(), True)
                self._downloads_items17 = _clean_download_history17(
                    json.loads(payload.decode("utf-8")))
            except Exception:
                # Preserve the original encrypted file rather than overwrite it.
                self._downloads_readonly17 = True
                self.statusBar().showMessage(
                    "下载历史无法读取，旧文件已保留；停止写入以防数据丢失", 9000)

        self._downloads_timer17 = QTimer(self)
        self._downloads_timer17.setSingleShot(True)
        self._downloads_timer17.setInterval(800)
        self._downloads_timer17.timeout.connect(self._save_downloads17)

        self._downloads_button17 = QToolButton(self)
        self._downloads_button17.setObjectName("GlacierDownloadButton17")
        self._downloads_button17.setText("↓ 下载")
        self._downloads_button17.setToolTip("查看下载进度、暂停、继续或打开文件")
        self._downloads_button17.clicked.connect(self.show_download_center17)
        nav.addWidget(self._downloads_button17)
        self.profile.downloadRequested.connect(self._on_download_requested17)
        self.setStyleSheet(self.styleSheet() + """
QToolButton#GlacierDownloadButton17 {
    background:#e8f4fc; border:1px solid #bedae8; border-radius:10px;
    color:#29647f; padding:6px 11px; min-height:24px;
}
QToolButton#GlacierDownloadButton17:hover { background:#d3e9f8; }
""")
        self._refresh_download_ui17()

    def _on_download_requested17(self, request):
        # The existing v0.16 handler remains responsible for asking/accepting.
        # Observe state only. Accepting here would bypass destination consent.
        key = secrets.token_hex(8)
        try:
            record = {
                "id": key, "name": str(request.downloadFileName())[:256],
                "directory": str(request.downloadDirectory())[:2048],
                "received": max(0, int(request.receivedBytes())),
                "total": max(0, int(request.totalBytes())),
                "state": _state_name17(request.state()),
                "created": time.time(),
            }
            for signal_name in ("stateChanged", "receivedBytesChanged",
                                "totalBytesChanged", "isPausedChanged"):
                signal = getattr(request, signal_name, None)
                if signal is not None:
                    signal.connect(lambda *_args, ident=key: self._sync_download17(ident))
        except (RuntimeError, AttributeError, TypeError, ValueError):
            return
        self._download_objects17[key] = request
        self._downloads_items17.insert(0, record)
        self._downloads_items17 = self._downloads_items17[:HISTORY_LIMIT17]
        self._refresh_download_ui17()
        self._queue_download_save17()

    def _download_record17(self, key):
        return next((x for x in self._downloads_items17 if x["id"] == key), None)

    def _sync_download17(self, key):
        item = self._download_record17(key)
        request = self._download_objects17.get(key)
        if item is None or request is None:
            return
        try:
            item["received"] = max(0, int(request.receivedBytes()))
            item["total"] = max(0, int(request.totalBytes()))
            item["state"] = _state_name17(request.state())
            item["name"] = str(request.downloadFileName())[:256]
            item["directory"] = str(request.downloadDirectory())[:2048]
            if getattr(request, "isPaused", lambda: False)() and item["state"] == "in_progress":
                item["state"] = "paused"
        except (RuntimeError, AttributeError, ValueError, TypeError):
            self._download_objects17.pop(key, None)
            return
        if item["state"] in ("completed", "cancelled", "interrupted"):
            self._download_objects17.pop(key, None)
        self._queue_download_save17()
        self._refresh_download_ui17()

    def _queue_download_save17(self):
        if not getattr(self, "_downloads_readonly17", True):
            self._downloads_timer17.start()

    def _save_downloads17(self):
        if self._downloads_readonly17:
            return
        contents = {"schema": 1, "items": [
            {k: v for k, v in x.items() if k in (
                "name", "directory", "received", "total", "state", "created")}
            for x in self._downloads_items17[:HISTORY_LIMIT17]]}
        data = json.dumps(contents, separators=(",", ":"), ensure_ascii=False).encode()
        if len(data) > HISTORY_BYTES17:
            self.statusBar().showMessage("下载历史超出大小限制，未写入", 5000)
            return
        dest = self._downloads_file17
        temp = dest.with_name(dest.name + "." + secrets.token_hex(6) + ".tmp")
        try:
            encrypted = self._downloads_cipher17(data)
            fd = os.open(str(temp), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(encrypted)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, dest)
        except Exception:
            self.statusBar().showMessage("下载历史保存失败；原有记录不受影响", 5000)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def flush_downloads17(self):
        if hasattr(self, "_downloads_timer17"):
            self._downloads_timer17.stop()
            self._save_downloads17()

    def _refresh_download_ui17(self):
        if not hasattr(self, "_downloads_button17"):
            return
        active = sum(1 for x in self._downloads_items17
                     if x["state"] in ACTIVE_STATES17)
        self._downloads_button17.setText(f"↓ 下载 {active}" if active else "↓ 下载")
        if self._downloads_dialog17 is None:
            return
        chosen = self._selected_download17()
        chosen_id = chosen["id"] if chosen else None
        view = self._downloads_list17
        view.clear()
        self._downloads_visible17 = []
        for row in self._downloads_items17[:HISTORY_LIMIT17]:
            done = row["received"]
            total = row["total"]
            percentage = f"{min(100, int(done * 100 / total))}%" if total else "未知"
            state = {"requested": "等待确认", "in_progress": "下载中",
                     "paused": "已暂停", "completed": "已完成",
                     "cancelled": "已取消", "interrupted": "已中断"}.get(
                         row["state"], row["state"])
            self._downloads_visible17.append(row["id"])
            view.addItem(f"{row['name']}   ·   {state}   ·   {percentage}"
                         f"   ({done // 1024} KB)")
        if chosen_id in self._downloads_visible17:
            view.setCurrentRow(self._downloads_visible17.index(chosen_id))
        elif self._downloads_visible17:
            view.setCurrentRow(0)

    def _init_download_dialog17(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("❄ Glacier 下载中心")
        dlg.resize(660, 450)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("下载任务与历史（仅在本机加密保存）", dlg))
        records = QListWidget(dlg)
        layout.addWidget(records, 1)
        self._downloads_list17 = records
        self._downloads_visible17 = []
        row1 = QHBoxLayout()
        for label, method in [
            ("暂停", self.pause_download17),
            ("继续", self.resume_download17),
            ("取消", self.cancel_download17),
            ("打开文件", self.open_download_file17),
            ("打开目录", self.open_download_directory17),
        ]:
            button = QPushButton(label, dlg)
            button.clicked.connect(method)
            row1.addWidget(button)
        layout.addLayout(row1)
        clear = QPushButton("清除已结束的历史记录", dlg)
        clear.clicked.connect(self.clear_finished_downloads17)
        layout.addWidget(clear)
        self._downloads_dialog17 = dlg
        self._refresh_download_ui17()

    def show_download_center17(self):
        if self._downloads_dialog17 is None:
            self._init_download_dialog17()
        self._refresh_download_ui17()
        self._downloads_dialog17.show()
        self._downloads_dialog17.raise_()
        self._downloads_dialog17.activateWindow()

    def _selected_download17(self):
        if self._downloads_dialog17 is None:
            return None
        index = self._downloads_list17.currentRow()
        if not 0 <= index < len(self._downloads_visible17):
            return None
        return self._download_record17(self._downloads_visible17[index])

    def _current_request17(self):
        row = self._selected_download17()
        if row is None:
            return None
        return self._download_objects17.get(row["id"])

    def pause_download17(self):
        req = self._current_request17()
        if req is not None:
            try:
                if _state_name17(req.state()) == "in_progress" and not req.isPaused():
                    req.pause()
                    self._sync_download17(self._selected_download17()["id"])
            except (RuntimeError, AttributeError):
                pass

    def resume_download17(self):
        req = self._current_request17()
        if req is not None:
            try:
                if _state_name17(req.state()) == "in_progress" and req.isPaused():
                    req.resume()
                    self._sync_download17(self._selected_download17()["id"])
            except (RuntimeError, AttributeError):
                pass

    def cancel_download17(self):
        req = self._current_request17()
        if req is not None:
            try:
                if _state_name17(req.state()) in ("requested", "in_progress"):
                    if QMessageBox.question(
                            self, "取消下载", "确认取消当前下载任务？") != QMessageBox.StandardButton.Yes:
                        return
                    req.cancel()
                    self._sync_download17(self._selected_download17()["id"])
            except (RuntimeError, AttributeError):
                pass

    def open_download_file17(self):
        row = self._selected_download17()
        if row is None:
            return False
        target = _safe_download_path17(row)
        if target is None:
            self.statusBar().showMessage("文件未下载完成或已被移动，无法打开", 3500)
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))))

    def open_download_directory17(self):
        row = self._selected_download17()
        if row is None or not isinstance(row.get("directory"), str):
            return False
        path = Path(row["directory"])
        if not path.is_absolute() or not path.is_dir():
            self.statusBar().showMessage("下载目录不存在", 3500)
            return False
        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))

    def clear_finished_downloads17(self):
        self._downloads_items17 = [x for x in self._downloads_items17
                                    if x["state"] in ACTIVE_STATES17]
        self._queue_download_save17()
        self._refresh_download_ui17()
