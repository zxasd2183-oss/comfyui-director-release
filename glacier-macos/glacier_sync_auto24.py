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



def check_manual_snapshot24(remote, baseline, records, space, *, upload):
    """Reject stale cloud snapshots and unresolved divergence for manual sync.

    Unlike the opt-in automatic flow, manual buttons formerly trusted any
    server version, including a stale value after a VPS backup restore.
    """
    if not isinstance(remote, dict) or type(remote.get("version")) is not int:
        raise SyncError23("Invalid cloud vault version; account data preserved")
    version = remote["version"]
    if version < 0:
        raise SyncError23("Invalid cloud vault version; account data preserved")
    if baseline is None:
        return version
    if (not isinstance(baseline, dict)
            or type(baseline.get("version")) is not int
            or baseline["version"] < 0
            or not isinstance(baseline.get("local_hash"), str)
            or len(baseline["local_hash"]) != 64
            or any(ch not in "0123456789abcdef" for ch in baseline["local_hash"])):
        raise SyncError23("Local sync checkpoint invalid; account data preserved")
    if version < baseline["version"]:
        raise SyncError23("Cloud account version rolled back; refusing overwrite")
    if upload and version > baseline["version"]:
        raise SyncError23("Cloud account changed on another device; refusing overwrite")
    if not upload and account_digest24(records, space) != baseline["local_hash"]:
        raise SyncError23("Local account data changed; refusing destructive download")
    return version


def check_manual_upload_ack24(reply, expected_version):
    if not isinstance(reply, dict) or type(reply.get("version")) is not int:
        raise SyncError23("Invalid cloud upload acknowledgement; checkpoint unchanged")
    written = reply["version"]
    if written <= expected_version:
        raise SyncError23("Non-increasing upload version; checkpoint unchanged")
    return written


def sync_one_space24(base, port, token, space, local_records, baseline, passphrase):
    """Runs in background thread; no Qt access or local file mutation."""
    if (not isinstance(baseline, dict)
            or type(baseline.get("version")) is not int
            or baseline["version"] < 0):
        return {"space": space, "kind": "uninitialized"}
    version = baseline["version"]
    old_hash = baseline.get("local_hash")
    if not isinstance(old_hash, str) or len(old_hash) != 64:
        return {"space": space, "kind": "uninitialized"}
    transport = SyncTransport23(base, port, token)
    remote = transport.call("GET", "/v1/vault/" + space)
    server_version = remote.get("version")
    # A restored/replayed or malformed server record must never replace a
    # newer, locally known E2E vault. Do not decrypt, upload or alter baseline.
    if type(server_version) is not int or server_version < version:
        return {"space": space, "kind": "rollback"}
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
        written_version = result.get("version")
        if type(written_version) is not int or written_version <= version:
            return {"space": space, "kind": "rollback"}
        return {"space": space, "kind": "uploaded",
                "version": written_version, "local_hash": local_hash}
    if remote_changed:
        if not remote.get("envelope"):
            return {"space": space, "kind": "conflict"}
        cards = decrypt_space23(remote["envelope"], space, passphrase)
        return {"space": space, "kind": "downloaded", "records": cards,
                "version": server_version, "local_hash": local_hash}
    return {"space": space, "kind": "unchanged"}
