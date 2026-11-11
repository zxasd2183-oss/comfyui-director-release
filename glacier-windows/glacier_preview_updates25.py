"""Glacier Windows preview discovery exclusively through owner's HTTPS VPS.

GitHub is never queried by the installed client. The unprivileged VPS mirror
fetches upstream releases, validates upstream SHA-256 and serves a bounded
informational preview manifest. Formal in-app updates still use independently
Ed25519-signed manifests. Preview assets are offered for user-confirmed
manual installation only; never auto-run or silently overwrite.
"""
from __future__ import annotations

import json
import re
import threading

import requests
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtWidgets import QMessageBox, QPushButton

PREVIEW_FEED25 = "https://sync.borealos.cn/downloads/windows-preview.json"
ASSET_ROOT25 = "https://sync.borealos.cn/downloads/"
FIELDS25 = frozenset(("platform", "channel", "version", "url", "size", "sha256"))


class PreviewError25(Exception):
    pass


def _version25(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", value):
        raise PreviewError25("Invalid version")
    return tuple(int(x) for x in value.split("."))


def _unique25(pairs):
    doc = {}
    for key, value in pairs:
        if key in doc:
            raise PreviewError25("Duplicate preview metadata key")
        doc[key] = value
    return doc


def select_preview25(document, current):
    """Validate a VPS preview manifest; never treat it as signed update data."""
    if not isinstance(document, dict) or frozenset(document) != FIELDS25:
        raise PreviewError25("Invalid VPS preview manifest schema")
    if document.get("platform") != "windows" or document.get("channel") != "preview-manual":
        raise PreviewError25("Preview channel/platform mismatch")
    version = document.get("version")
    if _version25(version) <= _version25(current):
        return None
    expected = ASSET_ROOT25 + f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
    if document.get("url") != expected:
        raise PreviewError25("Preview installer must be hosted on the owner VPS")
    size = document.get("size")
    sha = document.get("sha256")
    if type(size) is not int or not 10_000_000 <= size <= 900_000_000:
        raise PreviewError25("Invalid installer size")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise PreviewError25("Invalid installer SHA-256")
    return {"version": version, "url": expected, "size": size, "sha256": sha}


def fetch_preview25(current, port):
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise PreviewError25("Glacier VLESS proxy is unavailable")
    session = requests.Session()
    session.trust_env = False
    sock = f"socks5h://127.0.0.1:{port}"
    session.proxies = {"http": sock, "https": sock}
    try:
        with session.get(
            PREVIEW_FEED25,
            headers={"Accept": "application/json", "User-Agent": "GlacierBrowser/VPS-preview-check"},
            timeout=(6, 15),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise PreviewError25("VPS preview feed unavailable")
            if int(response.headers.get("Content-Length", "0")) > 16_384:
                raise PreviewError25("Oversized preview manifest")
            payload = bytearray()
            for chunk in response.iter_content(4096):
                payload.extend(chunk)
                if len(payload) > 16_384:
                    raise PreviewError25("Oversized preview manifest")
            try:
                doc = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique25)
            except (ValueError, UnicodeError) as exc:
                raise PreviewError25("Invalid VPS preview JSON") from exc
            return select_preview25(doc, current)
    except requests.RequestException as exc:
        raise PreviewError25("Cannot reach VPS preview feed via VLESS") from exc
    finally:
        session.close()


class PreviewSignal25(QObject):
    ready = Signal(object)


class GlacierPreviewUpdates25:
    def setup_preview_updates25(self, bar):
        self._preview_signal25 = PreviewSignal25(self)
        self._preview_signal25.ready.connect(self._preview_result25)
        self._preview_busy25 = False
        btn = QPushButton("预览版更新", self)
        btn.setToolTip("通过自有 VPS 查找预览版；手动安装，不改变正式版数字签名校验")
        btn.clicked.connect(self.check_preview_updates25)
        bar.addWidget(btn)
        self._preview_button25 = btn

    def check_preview_updates25(self):
        if self._preview_busy25:
            return
        process = getattr(self, "proc", None)
        if process is None or process.poll() is not None:
            QMessageBox.warning(self, "Glacier 预览版", "VLESS 核心未运行，已禁止直连下载。")
            return
        port = int(getattr(self, "proxy_port", 0))
        from secure_update import CURRENT_VERSION
        self._preview_busy25 = True
        self._preview_button25.setEnabled(False)
        self._preview_button25.setText("检查预览版…")

        def work():
            try:
                result = {"preview": fetch_preview25(CURRENT_VERSION, port)}
            except PreviewError25:
                result = {"error": "无法从 VPS 读取预览版清单，请检查代理或镜像服务。"}
            except Exception:
                result = {"error": "预览版检查失败；正式版签名更新未受影响。"}
            self._preview_signal25.ready.emit(result)

        threading.Thread(target=work, daemon=True, name="glacier-preview-check").start()

    def _preview_result25(self, data):
        self._preview_busy25 = False
        self._preview_button25.setEnabled(True)
        self._preview_button25.setText("预览版更新")
        if "error" in data:
            QMessageBox.warning(self, "Glacier 预览版", data["error"])
            return
        found = data.get("preview")
        if found is None:
            QMessageBox.information(
                self, "Glacier 预览版",
                "自有 VPS 镜像暂无比当前版本更新的 Windows 预览版。\n"
                "正式版仍独立使用 Ed25519 签名更新清单。")
            return
        answer = QMessageBox.question(
            self, "发现 Glacier 预览版 " + found["version"],
            "VPS 上已有 Windows 预览版 " + found["version"] + "（约 "
            + str(round(found["size"] / 1_000_000)) + " MB）。\n"
            "镜像已校验 SHA-256，预览版仍需手动安装。\n\n"
            "是否在 Glacier 中打开 VPS 下载地址？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            tab = self.new_tab()
            tab.setUrl(QUrl(found["url"]))
