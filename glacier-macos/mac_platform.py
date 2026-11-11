"""Native macOS support for Glacier Browser (no Windows DPAPI or EXE dependency)."""
from __future__ import annotations

import os
import sys
import secrets
from pathlib import Path

import keyring
from cryptography.fernet import Fernet
from PySide6.QtWidgets import QInputDialog, QMessageBox

SERVICE = "cn.borealos.glacier-browser"
NODE_ACCOUNT = "vless-node"
SESSION_ACCOUNT = "session-encryption-key"


def appdir():
    p = Path.home() / "Library" / "Application Support" / "GlacierBrowser"
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        p.chmod(0o700)
    except OSError:
        pass
    return p


def _session_key():
    saved = keyring.get_password(SERVICE, SESSION_ACCOUNT)
    if saved:
        return saved.encode("ascii")
    key = Fernet.generate_key()
    keyring.set_password(SERVICE, SESSION_ACCOUNT, key.decode("ascii"))
    return key


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    """Compatibility wrapper for session encryption; key lives in macOS Keychain.

    No encryption keys or node IDs are written to configuration files.
    """
    cipher = Fernet(_session_key())
    return cipher.decrypt(data) if decrypt else cipher.encrypt(data)


def get_link(app, validate):
    """Read VLESS URL from Keychain; prompt for it only on first launch."""
    try:
        existing = keyring.get_password(SERVICE, NODE_ACCOUNT)
        if existing:
            validate(existing)
            return existing
    except Exception as exc:
        QMessageBox.warning(None, "Glacier Browser", "无法读取钥匙串中的线路：" + str(exc))
        return ""

    clipboard = app.clipboard().text().strip()
    suggested = clipboard if clipboard.lower().startswith("vless://") else ""
    value, ok = QInputDialog.getMultiLineText(
        None,
        "Glacier Browser · 首次导入 VLESS",
        "请粘贴 VLESS 分享链接。仅保存在本机 macOS 钥匙串中：",
        suggested,
    )
    if not ok or not value.strip():
        return ""
    try:
        value = value.strip()
        validate(value)
        keyring.set_password(SERVICE, NODE_ACCOUNT, value)
        return value
    except Exception as exc:
        QMessageBox.warning(None, "Glacier Browser", "线路导入失败：" + str(exc))
        return ""


def xray_core_path():
    """Locate the bundled official Xray-core arm64 binary (no external install)."""
    roots = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
        Path(sys.executable).parent,
        Path(sys.executable).parent.parent / "Resources",
        Path(sys.executable).parent.parent / "Frameworks",
    ]
    for root in roots:
        for name in ("bin/xray", "xray", "_internal/bin/xray"):
            candidate = root / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def core_path():
    roots = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
        Path(sys.executable).parent,
        Path(sys.executable).parent.parent / "Resources",
        Path(sys.executable).parent.parent / "Frameworks",
    ]
    for root in roots:
        for name in ("bin/sing-box", "sing-box", "_internal/bin/sing-box"):
            candidate = root / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None
