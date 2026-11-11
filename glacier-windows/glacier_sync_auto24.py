"""Glacier private/work account auto-sync coordinator.

Automatic sync is opt-in and can be disabled. The server receives ciphertext
only. A per-space baseline prevents overwriting concurrent changes: if both
the local encrypted vault and server have changed, sync halts and requires
manual resolution. No requests are made without a running local SOCKS proxy.
"""
from __future__ import annotations

import hashlib
import json

from PySide6.QtCore import QObject, Signal

from glacier_accounts22 import clean_accounts22
from glacier_sync23 import SyncTransport23, SyncError23, decrypt_space23, encrypt_space23


class AutoSyncResult24(QObject):
    completed = Signal(object)


def account_digest24(records, space):
    if space not in ("private", "work"):
        raise SyncError23("Invalid account space")
    subset = [r for r in records if r.get("space", "private") == space]
    clean = clean_accounts22({"schema": 1, "accounts": subset})["accounts"]
    normalized = sorted(clean, key=lambda r: (r["site"], r["name"].casefold()))
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sync_one_space24(base, port, token, space, local_records, baseline, passphrase):
    """Runs in background thread; no Qt access or local file mutation."""
    if not isinstance(baseline, dict) or not isinstance(baseline.get("version"), int):
        return {"space": space, "kind": "uninitialized"}
    version = baseline["version"]
    old_hash = baseline.get("local_hash")
    if not isinstance(old_hash, str) or len(old_hash) != 64:
        return {"space": space, "kind": "uninitialized"}
    transport = SyncTransport23(base, port, token)
    remote = transport.call("GET", "/v1/vault/" + space)
    server_version = remote["version"]
    local_hash = account_digest24(local_records, space)
    local_changed = local_hash != old_hash
    remote_changed = server_version != version
    if local_changed and remote_changed:
        return {"space": space, "kind": "conflict"}
    if local_changed:
        encrypted = encrypt_space23(
            [r for r in local_records if r.get("space", "private") == space],
            space, passphrase)
        result = transport.call("PUT", "/v1/vault/" + space, {
            "expected_version": version, "envelope": encrypted})
        return {"space": space, "kind": "uploaded",
                "version": result["version"], "local_hash": local_hash}
    if remote_changed:
        if not remote.get("envelope"):
            return {"space": space, "kind": "conflict"}
        cards = decrypt_space23(remote["envelope"], space, passphrase)
        return {"space": space, "kind": "downloaded", "records": cards,
                "version": server_version, "local_hash": local_hash}
    return {"space": space, "kind": "unchanged"}
