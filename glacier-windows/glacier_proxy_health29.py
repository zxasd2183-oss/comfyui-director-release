"""Glacier Windows local VLESS core startup, privacy and health primitives.

No external probing, no credentials in logs, and no fallback to direct egress.
DPAPI-encrypted node.dpapi remains the only persistent VLESS credentials file.
The sing-box JSON needed during startup lives in a randomly named local file
and is removed after the configured SOCKS/mixed inbound begins listening.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import time
from contextlib import contextmanager
from pathlib import Path


def local_proxy_ready(port: int, *, timeout: float = 0.2) -> bool:
    """Only test the local bound port: never make a direct external request."""
    if type(port) is not int or not 1 <= port <= 65535:
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


def await_proxy_ready(
    proc, port: int, *, timeout: float = 12.0, interval: float = 0.15,
    probe=local_proxy_ready, clock=time.monotonic, pause=time.sleep,
) -> None:
    """Fail closed if sing-box exits or local inbound never becomes available."""
    if not 0 < timeout <= 60 or not 0 < interval <= 5:
        raise ValueError("Invalid bounded local proxy readiness timeout")
    deadline = clock() + timeout
    while True:
        if proc.poll() is not None:
            raise RuntimeError("VLESS 核心异常退出，浏览器保持禁止直连")
        if probe(port):
            return
        remaining = deadline - clock()
        if remaining <= 0:
            raise RuntimeError("VLESS 核心启动超时，浏览器保持禁止直连")
        pause(min(interval, remaining))


@contextmanager
def ephemeral_proxy_config(directory, document):
    """Create an exclusive temporary config; remove plaintext even on failure.

    Windows retains ACL protection from the user's own LocalAppData directory.
    The inode/name is not reused and cannot overwrite another local config.
    """
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("代理运行目录不可用")
    name = ".glacier-core-" + secrets.token_hex(16) + ".json"
    target = root / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = None
    try:
        fd = os.open(target, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            fd = None
            json.dump(document, output, ensure_ascii=False, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        yield target
    finally:
        if fd is not None:
            os.close(fd)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            # If a local AV tool temporarily holds the file, don't present
            # secrets or paths in UI exceptions. A later process may retry.
            pass


def proxy_status_text(proc, port: int, *, probe=local_proxy_ready):
    """State exposed in toolbar; listener readiness is not Internet reachability."""
    if proc is None or proc.poll() is not None:
        return "● 代理已断开 · 点击重连", False
    if not probe(port):
        return "● 代理启动中 · 点击重连", False
    return "● 本地代理就绪", True
