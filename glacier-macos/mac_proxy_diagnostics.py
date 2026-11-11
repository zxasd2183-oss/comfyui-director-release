"""Mac sing-box failure classification. NEVER persist raw core logs or VLESS links.

sing-box defaults to logging to stdout, NOT stderr. The caller must merge
stderr into a captured stdout PIPE; raw output may contain node hostnames,
credentials, URLs or IPs. We recognize a small list of fixed error CATEGORIES
and discard each raw line immediately. Only those categories are presented.
"""
from __future__ import annotations

import collections
import threading
import weakref

_LOCK=threading.Lock()
_HINTS=weakref.WeakKeyDictionary()
_FAILURES=(
    ("reality verification failed", "REALITY 握手验证失败"),
    ("reality handshake", "REALITY 握手失败"),
    ("tls: failed to verify certificate", "TLS 证书校验失败"),
    ("certificate verify failed", "TLS 证书校验失败"),
    ("x509:", "TLS 证书校验失败"),
    ("tls: handshake failure", "TLS 握手失败"),
    ("tls handshake", "TLS 握手失败"),
    ("websocket: bad handshake", "WebSocket 握手失败"),
    ("bad handshake", "WebSocket 或传输协议握手失败"),
    ("unexpected http response", "HTTP 传输握手失败"),
    ("grpc", "gRPC 传输连接失败"),
    ("no such host", "节点域名解析失败"),
    ("dns", "DNS 解析或查询失败"),
    ("lookup", "域名解析失败"),
    ("network is unreachable", "无法到达节点所在网络"),
    ("connection refused", "节点服务拒绝连接"),
    ("i/o timeout", "节点连接或握手超时"),
    ("context deadline exceeded", "节点连接或握手超时"),
    ("connection reset by peer", "远端断开连接"),
    ("unexpected eof", "连接意外中断"),
    ("eof", "连接意外中断"),
    ("connection: open connection", "出站连接失败，具体协议原因待进一步确认"),
    ("outbound/vless", "VLESS 出站连接失败，具体原因待进一步确认"),
)


def classify(line):
    """Return a fixed category string only; never echo arbitrary log content."""
    if not isinstance(line, str):
        return None
    low=line.lower()
    for keyword,description in _FAILURES:
        if keyword in low:
            return description
    return None


def start_capture(process):
    """Drain combined stdout+stderr without retaining secrets or raw log lines."""
    if process is None or process.stdout is None:
        return
    hints=collections.deque(maxlen=10)
    with _LOCK:
        _HINTS[process]=hints

    def reader():
        try:
            while True:
                raw=process.stdout.readline(4096)
                if not raw:
                    break
                # Raw bytes are discarded immediately after safe categorization.
                line=raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                category=classify(line)
                if category:
                    with _LOCK:
                        hints.append(category)
        except (OSError,ValueError):
            pass
        finally:
            try:
                process.stdout.close()
            except (OSError,ValueError):
                pass

    threading.Thread(target=reader,daemon=True,name="glacier-safe-core-diagnostics").start()


def latest_hint(process):
    if process is None:
        return None
    with _LOCK:
        hints=_HINTS.get(process)
        return hints[-1] if hints else None


def reset_hints(process):
    """Clear previous probe's categories so a new failure never shows stale hints."""
    with _LOCK:
        hints=_HINTS.get(process) if process is not None else None
        if hints is not None:
            hints.clear()
