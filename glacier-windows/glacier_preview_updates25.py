"""Independent, opt-in Glacier preview discovery.

Preview releases are NOT signed update manifests. This module only opens the
official GitHub release page after user confirmation; it never downloads or
executes an installer, and never modifies the signed production updater.
GitHub API requests go through the already-running local VLESS/SOCKS proxy.
"""
from __future__ import annotations

import re
import threading
from urllib.parse import urlsplit

import requests
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtWidgets import QMessageBox, QPushButton

REPO = "zxasd2183-oss/comfyui-director-release"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASE_ROOT = f"https://github.com/{REPO}/releases/tag/"
ASSET_PREFIX = f"https://github.com/{REPO}/releases/download/"
TAG_PATTERN = re.compile(r"^glacier-v(\d+\.\d+\.\d+)-(?:sync-v\d+-[0-9a-f]{7}|input-preview(?:-r\d+)?|preview-[0-9a-z-]+)$")
INSTALLER_PATTERN = re.compile(r"^GlacierBrowser-v(\d+\.\d+\.\d+)-Windows-Setup-x64\.exe$")


class PreviewError25(Exception):
    pass


def _version25(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", value):
        raise PreviewError25("Invalid version")
    return tuple(int(x) for x in value.split("."))


def select_preview25(releases, current):
    """Select a newer preview and validate exact official release/asset URLs."""
    if not isinstance(releases, list) or len(releases) > 30:
        raise PreviewError25("Invalid release data")
    local = _version25(current)
    candidates = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") or not item.get("prerelease"):
            continue
        tag = item.get("tag_name")
        if not isinstance(tag, str):
            continue
        match = TAG_PATTERN.fullmatch(tag)
        if not match:
            continue
        version = match.group(1)
        if _version25(version) <= local:
            continue
        url = item.get("html_url")
        if url != RELEASE_ROOT + tag:
            continue
        assets = item.get("assets")
        if not isinstance(assets, list) or len(assets) > 30:
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            if not isinstance(name, str):
                continue
            matched = INSTALLER_PATTERN.fullmatch(name)
            if not matched or matched.group(1) != version:
                continue
            download = asset.get("browser_download_url")
            if download != ASSET_PREFIX + tag + "/" + name:
                continue
            size = asset.get("size")
            if not isinstance(size, int) or not (10_000_000 < size < 1_500_000_000):
                continue
            candidates.append({
                "version": version,
                "tag": tag,
                "page": url,
                "size": size,
            })
    return max(candidates, key=lambda item: (_version25(item["version"]), item["tag"])) if candidates else None


def fetch_preview25(current, port):
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise PreviewError25("Glacier VLESS proxy is unavailable")
    session = requests.Session()
    session.trust_env = False
    sock = f"socks5h://127.0.0.1:{port}"
    session.proxies = {"http": sock, "https": sock}
    try:
        with session.get(
            API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "GlacierBrowser/preview-check"},
            timeout=(6, 15),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise PreviewError25("GitHub preview listing unavailable")
            if int(response.headers.get("Content-Length", "0")) > 512_000:
                raise PreviewError25("Oversized GitHub response")
            payload = bytearray()
            for chunk in response.iter_content(8192):
                payload.extend(chunk)
                if len(payload) > 512_000:
                    raise PreviewError25("Oversized GitHub response")
            try:
                return select_preview25(requests.models.complexjson.loads(payload.decode("utf-8")), current)
            except (ValueError, UnicodeError) as exc:
                raise PreviewError25("Invalid preview listing") from exc
    except requests.RequestException as exc:
        raise PreviewError25("Cannot reach GitHub via VLESS") from exc
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
        btn.setToolTip("发现官方 GitHub 预览版；手动下载，不绕过正式更新的数字签名校验")
        btn.clicked.connect(self.check_preview_updates25)
        bar.addWidget(btn)
        self._preview_button25 = btn

    def check_preview_updates25(self):
        if self._preview_busy25:
            return
        process = getattr(self, "proc", None)
        if process is None or process.poll() is not None:
            QMessageBox.warning(self, "Glacier 预览版", "VLESS 核心未运行，禁止直连 GitHub。")
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
                result = {"error": "无法通过 VLESS 读取 GitHub 官方预览清单，请检查网络。"}
            except Exception:
                result = {"error": "预览版检查失败；正式更新功能未受影响。"}
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
                "GitHub 官方预览通道暂无比当前安装版本更新的 Windows 预览版。\n"
                "正式版仍由独立 Ed25519 签名更新清单检查。")
            return
        answer = QMessageBox.question(
            self, "发现 Glacier 预览版 " + found["version"],
            "发现 Windows 预览版 " + found["version"] + "（约 "
            + str(round(found["size"] / 1_000_000)) + " MB）。\n\n"
            "预览版不属于正式签名更新渠道，不能自动下载安装。\n"
            "是否在 Glacier 浏览器中打开官方 GitHub Release 页面，手动下载安装？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            # Official release page only; no arbitrary asset URL is opened.
            tab = self.new_tab()
            tab.setUrl(QUrl(found["page"]))
