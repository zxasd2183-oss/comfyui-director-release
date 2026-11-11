"""Glacier site diagnostics 31: a bounded, user-triggered HTTPS check over VLESS.

This does not inspect Gemini messages, simulate chat requests, inject page
JavaScript, log destinations with query strings or claim that SSE streams work.
The only destination is the fixed Gemini landing page via the LOCAL SOCKS5
listener with remote DNS and verified TLS. Direct fallback is impossible.
"""
from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
import threading
import time

import requests
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from glacier_proxy_health29 import local_proxy_ready

GEMINI_PROBE_URL31 = "https://gemini.google.com/app"


@dataclass(frozen=True)
class SiteProbeResult31:
    code: str
    message: str
    elapsed_ms: int = 0


def classify_http31(status: int, elapsed_ms: int) -> SiteProbeResult31:
    if status in (429, 503):
        return SiteProbeResult31("busy", "Gemini 服务返回限流或临时不可用；不要连续重复发送同一消息。", elapsed_ms)
    if 500 <= status <= 599:
        return SiteProbeResult31("server", "已通过 VLESS 到达远端，但 Gemini 返回服务错误。", elapsed_ms)
    if status in (401, 403):
        return SiteProbeResult31("access", "Gemini HTTPS 已响应，但当前网络或账号访问可能受限。", elapsed_ms)
    if status in (200, 204, 301, 302, 303, 307, 308):
        return SiteProbeResult31("reachable", "Gemini 的 HTTPS 入口可达；这不等于聊天回复流正常。", elapsed_ms)
    if 100 <= status <= 499:
        return SiteProbeResult31("http", "Gemini 服务器已响应，但返回了非正常页面状态。", elapsed_ms)
    return SiteProbeResult31("invalid", "远端返回无效的 HTTP 状态。", elapsed_ms)


def check_gemini_via_proxy31(port: int, *, ready=local_proxy_ready, session_factory=requests.Session, clock=time.monotonic) -> SiteProbeResult31:
    """One HTTPS request, no redirect, no message content, remote SOCKS DNS.

    A successful test proves only TLS/HTTP response headers, not WebEngine,
    login status, Gemini streaming transport or request completion.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        return SiteProbeResult31("offline", "本地代理端口不可用，已禁止直连。")
    if not ready(port):
        return SiteProbeResult31("offline", "本地 VLESS 代理不可用；没有尝试公网直连。")
    start = clock()
    try:
        with session_factory() as session:
            session.trust_env = False
            proxy = "socks5h://127.0.0.1:" + str(port)
            session.proxies = {"http": proxy, "https": proxy}
            with session.get(
                GEMINI_PROBE_URL31,
                timeout=(5, 11),
                allow_redirects=False,
                stream=True,
                verify=True,
                headers={"Accept": "text/html", "Cache-Control": "no-store"},
            ) as response:
                status = response.status_code
        elapsed = max(0, int((clock() - start) * 1000))
        return classify_http31(status, elapsed)
    except requests.exceptions.SSLError:
        return SiteProbeResult31("tls", "通过 VLESS 连接时 TLS 证书验证失败；没有关闭验证。")
    except requests.exceptions.Timeout:
        return SiteProbeResult31("timeout", "Gemini HTTPS 建连或等待响应超时；可能是线路波动。")
    except requests.exceptions.ProxyError:
        return SiteProbeResult31("proxy", "VLESS 代理未能完成 Gemini 的远端连接。")
    except requests.exceptions.RequestException:
        return SiteProbeResult31("network", "Gemini HTTPS 请求未完成；请检查线路及目标站点。")
    except (OSError, ValueError):
        return SiteProbeResult31("network", "检测过程发生连接错误；未切换到直连。")


class GlacierSiteDiagnostic31:
    """Shared Windows/macOS native UI for diagnosing Gemini without a reload."""

    def start_gemini_diagnostic31(self):
        dialog = getattr(self, "_gemini_dialog31", None)
        if dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Glacier · Gemini 连接诊断")
            dialog.setObjectName("GlacierGeminiDiagnostic31")
            dialog.setMinimumWidth(485)
            box = QVBoxLayout(dialog)
            box.setSpacing(12)
            intro = QLabel("检测 Gemini HTTPS 入口与当前 VLESS 线路，不读取任何聊天内容。", dialog)
            intro.setWordWrap(True)
            box.addWidget(intro)
            status = QLabel("准备诊断", dialog)
            status.setObjectName("GlacierGeminiProbeResult31")
            status.setWordWrap(True)
            box.addWidget(status)
            note = QLabel(
                "连接成功不代表 Gemini 的流式回复一定正常。\n"
                "回复卡住时请先复制尚未发送的文字；不要自动重复提交，避免重复消息。\n"
                "本检测不刷新网页，不清除 Cookie，不上传线路信息。",
                dialog,
            )
            note.setWordWrap(True)
            box.addWidget(note)
            retry = QPushButton("再次检测", dialog)
            retry.setObjectName("GlacierGeminiProbeButton31")
            retry.clicked.connect(self._launch_gemini_probe31)
            box.addWidget(retry)
            dismiss = QPushButton("关闭", dialog)
            dismiss.clicked.connect(dialog.close)
            box.addWidget(dismiss)
            self._gemini_dialog31 = dialog
            self._gemini_status31 = status
            self._gemini_button31 = retry
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._launch_gemini_probe31()

    def _launch_gemini_probe31(self):
        # This runs only when the user explicitly asks for a diagnostic.
        if getattr(self, "_gemini_poll31", None) is not None and self._gemini_poll31.isActive():
            return
        self._gemini_button31.setEnabled(False)
        self._gemini_status31.setText("正在通过当前 VLESS 代理检测 Gemini HTTPS 入口…")
        results = Queue(maxsize=1)
        self._gemini_queue31 = results
        port = self.proxy_port
        def execute():
            try:
                result = check_gemini_via_proxy31(port)
            except Exception:
                # No raw exception text: URLs and socket errors may be sensitive.
                result = SiteProbeResult31("unknown", "诊断异常终止；未尝试直连。")
            results.put_nowait(result)
        threading.Thread(target=execute, daemon=True, name="GlacierGeminiProbe31").start()
        timer = QTimer(self)
        timer.setInterval(150)
        timer.timeout.connect(self._poll_gemini_probe31)
        self._gemini_poll31 = timer
        timer.start()

    def _poll_gemini_probe31(self):
        try:
            result = self._gemini_queue31.get_nowait()
        except Empty:
            return
        self._gemini_poll31.stop()
        self._gemini_poll31.deleteLater()
        self._gemini_poll31 = None
        self._gemini_button31.setEnabled(True)
        suffix = f"\nHTTPS 响应耗时：{result.elapsed_ms} ms" if result.elapsed_ms else ""
        self._gemini_status31.setText(result.message + suffix)
        self._gemini_last_result31 = result
