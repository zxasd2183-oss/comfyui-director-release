"""Per-user local vault for unsigned macOS Glacier releases.

Avoid Keychain permission dialogs on ordinary launch. Unlike Keychain, the
local encryption key is accessible to other processes running as the same
macOS user; user-home permissions and FileVault are the security boundary.
Legacy Keychain items and existing account ciphertext are never deleted.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

KEY_FILE = "mac-vault-key-v1"
NODE_FILE = "mac-vless-node-v1.enc"
LEGACY_FILES = (
    "accounts-d03.dpapi",
    "sync-account-v1.enc",
    "workspaces-v17.enc",
    "downloads-v17.enc",
)


def _read_private(path: Path, limit=65536) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or (stat.S_IMODE(info.st_mode) & 0o077)
                or info.st_size > limit):
            raise PermissionError("Private Glacier vault file has unsafe permissions")
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise ValueError("Glacier vault file is too large")
        return data
    finally:
        os.close(fd)


def _write_temp(directory: Path, data: bytes) -> Path:
    fd, temp = tempfile.mkstemp(prefix=".glacier-vault-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        return Path(temp)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temp).unlink(missing_ok=True)
        raise


def _put_once(path: Path, data: bytes) -> None:
    temp = _write_temp(path.parent, data)
    try:
        # Never replace a master key during concurrent browser launches.
        os.link(temp, path, follow_symlinks=False)
    finally:
        temp.unlink(missing_ok=True)


def _replace_private(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise PermissionError("Refusing to replace a symlink in Glacier vault")
    temp = _write_temp(path.parent, data)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def legacy_ciphertext_exists(directory: Path) -> bool:
    return any((Path(directory) / name).exists() for name in LEGACY_FILES)


def local_key(directory: Path, create: bool = True) -> bytes | None:
    directory = Path(directory)
    path = directory / KEY_FILE
    try:
        data = _read_private(path, 256)
    except FileNotFoundError:
        if not create:
            return None
        # Never orphan existing protected user data by generating a fresh key.
        if legacy_ciphertext_exists(directory) or (directory / NODE_FILE).exists():
            raise RuntimeError("Existing encrypted Glacier data needs explicit migration")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            _put_once(path, Fernet.generate_key())
        except FileExistsError:
            pass
        data = _read_private(path, 256)
    Fernet(data)
    return data


def import_legacy_key(directory: Path, old_key: str) -> bool:
    """Explicit one-time migration, preserving old ciphertext without rewriting."""
    directory = Path(directory)
    old_bytes = old_key.encode("ascii")
    Fernet(old_bytes)
    current = local_key(directory, create=False)
    if current is not None:
        if current != old_bytes:
            raise RuntimeError("Cannot replace existing Glacier vault key")
        return False
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _put_once(directory / KEY_FILE, old_bytes)
    except FileExistsError:
        if local_key(directory, create=False) != old_bytes:
            raise RuntimeError("Glacier vault changed during migration")
        return False
    return True


def protect(directory: Path, data: bytes, decrypt: bool = False) -> bytes:
    cipher = Fernet(local_key(Path(directory)))
    return cipher.decrypt(data) if decrypt else cipher.encrypt(data)


def read_node(directory: Path) -> str | None:
    try:
        blob = _read_private(Path(directory) / NODE_FILE, 16384)
    except FileNotFoundError:
        return None
    node = protect(directory, blob, decrypt=True).decode("utf-8")
    if not node.startswith("vless://") or len(node) > 8192:
        raise ValueError("Invalid Glacier VLESS node stored locally")
    return node


def write_node(directory: Path, node: str) -> None:
    if not isinstance(node, str) or not node.startswith("vless://") or len(node) > 8192:
        raise ValueError("Invalid Glacier VLESS node")
    directory = Path(directory)
    blob = protect(directory, node.encode("utf-8"))
    _replace_private(directory / NODE_FILE, blob)
