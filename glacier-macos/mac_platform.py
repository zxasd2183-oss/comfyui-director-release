"""Native macOS support for Glacier Browser (no Windows DPAPI or EXE dependency)."""
from __future__ import annotations

import os
import sys
import secrets
from pathlib import Path

from mac_local_vault import (protect, read_node, write_node, import_legacy_key,
                             legacy_ciphertext_exists, local_key)
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


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    """Session encryption backed by a private local vault, not startup Keychain.

    The existing encrypted account files remain untouched during migration.
    Unsigned apps cannot reliably retain Keychain ACL across updates.
    """
    return protect(appdir(), data, decrypt)


def _restore_legacy_on_request(validate):
    """Keychain is accessed ONLY after the user selects Restore in our UI."""
    import keyring

    directory = appdir()
    # Read both before writing anything. Denying either access must not leave
    # partially migrated accounts or silently replace their encryption key.
    old_key = keyring.get_password(SERVICE, SESSION_ACCOUNT)
    old_node = keyring.get_password(SERVICE, NODE_ACCOUNT)
    if old_node:
        validate(old_node)
    if legacy_ciphertext_exists(directory) and not old_key:
        raise RuntimeError("Old encrypted records require their original key")
    if not old_key and not old_node:
        raise RuntimeError("No legacy Glacier entries are accessible")
    if old_key:
        import_legacy_key(directory, old_key)
    if old_node:
        write_node(directory, old_node)
    return old_node


def get_link(app, validate):
    """Start without invoking Keychain; migrate old entries only on user action."""
    directory = appdir()
    try:
        existing = read_node(directory)
        if existing:
            validate(existing)
            return existing
    except Exception:
        QMessageBox.warning(
            None, "Glacier Browser",
            "本机加密线路读取失败。为避免覆盖旧数据，已停止自动连接。"
            "请检查资料权限或使用旧版本恢复。")
        return ""

    try:
        has_local_key = local_key(directory, create=False) is not None
    except Exception:
        QMessageBox.warning(
            None, "Glacier Browser",
            "本机加密密钥无法安全读取，已停止自动连接；现有文件不会被覆盖。")
        return ""

    legacy_files = legacy_ciphertext_exists(directory)
    # Existing Chrome profile is a non-sensitive signal of an upgrade where
    # the old VLESS node may still be only in the user's Keychain.
    previous_install = (directory / "profile").exists() and not has_local_key
    if legacy_files and not has_local_key or previous_install:
        msg = QMessageBox()
        msg.setWindowTitle("Glacier Browser · 旧数据迁移")
        msg.setText(
            "检测到旧版 Glacier 本机资料。\n"
            "只有你选择“迁移旧资料”后才会读取 macOS 钥匙串；"
            "此操作可能需要一次系统授权。之后普通启动不再读取钥匙串。\n"
            "迁移会将加密主密钥保存到仅当前 Mac 用户可访问的本地文件；"
            "同一系统用户运行的其他程序仍可能读取该文件，保护强度低于系统钥匙串。\n"
            "旧钥匙串项目和已有加密文件会保留。")
        restore_button = msg.addButton("迁移旧资料", QMessageBox.ButtonRole.AcceptRole)
        skip_button = msg.addButton("暂不迁移", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is restore_button:
            try:
                old_node = _restore_legacy_on_request(validate)
                if old_node:
                    return old_node
            except Exception:
                QMessageBox.warning(
                    None, "Glacier Browser",
                    "旧版钥匙串资料尚未完成迁移。未删除、替换旧版账号或线路。")
                return ""
        elif msg.clickedButton() is skip_button and legacy_files and not has_local_key:
            # Avoid creating a new unrelated Fernet key for old ciphertext.
            return ""

    clipboard = app.clipboard().text().strip()
    suggested = clipboard if clipboard.lower().startswith("vless://") else ""
    value, ok = QInputDialog.getMultiLineText(
        None,
        "Glacier Browser · 导入 VLESS",
        "请粘贴 VLESS 分享链接。加密存放于本机用户专属目录：",
        suggested,
    )
    if not ok or not value.strip():
        return ""
    try:
        value = value.strip()
        validate(value)
        write_node(directory, value)
        return value
    except Exception:
        QMessageBox.warning(
            None, "Glacier Browser",
            "线路导入未完成，本地加密密钥或资料需要恢复；旧文件未被覆盖。")
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
