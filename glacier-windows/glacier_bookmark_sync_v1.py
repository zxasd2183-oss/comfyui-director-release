"""Fail-closed Glacier bookmark reconciliation used by Windows/macOS clients.

No UI, file mutation, or network connection is performed here. The caller may
inject its existing authorized VLESS-backed SyncTransport23. This module never
touches /v1/vault/{private,work}; those routes contain website account cards.

IMPORTANT: A new device requires an explicit first-sync decision. Imported
bookmarks remain a preview until the owning browser confirms and saves them.
"""
from __future__ import annotations
import hashlib
import json
import re

from glacier_bookmark_portable_v1 import (
    BookmarkError, _clean, decrypt_bookmarks, encrypt_bookmarks, merge_bookmarks,
)

CHECKPOINT_KEYS = {"owner", "space", "version", "local_hash", "remote_hash"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class BookmarkSyncError(ValueError):
    pass


def rows_in_space(all_rows, space):
    if space not in ("private", "work"):
        raise BookmarkSyncError("Invalid bookmark space")
    if not isinstance(all_rows, list):
        raise BookmarkSyncError("Missing bookmark collection")
    if any(not isinstance(row, dict) or row.get("profile") not in ("private", "work")
           for row in all_rows):
        raise BookmarkSyncError("Corrupt or cross-space bookmark collection")
    return _clean([r for r in all_rows if r["profile"] == space], space)


def fingerprint(rows, space):
    items = rows_in_space(rows, space)
    canonical = sorted(items, key=lambda r: (r["url"], r["at"], r["title"]))
    packed = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(packed).hexdigest()


def checkpoint(owner, space, version, local_rows, remote_rows):
    if not isinstance(owner, str) or not 1 <= len(owner) <= 256:
        raise BookmarkSyncError("Missing verified Glacier account scope")
    if type(version) is not int or not 0 <= version <= 2147483647:
        raise BookmarkSyncError("Invalid bookmark version")
    return {"owner": owner, "space": space, "version": version,
            "local_hash": fingerprint(local_rows, space),
            "remote_hash": fingerprint(remote_rows, space)}


def _checkpoint(current, owner, space):
    if not isinstance(current, dict) or set(current) != CHECKPOINT_KEYS:
        return None
    if current["owner"] != owner or current["space"] != space:
        raise BookmarkSyncError("Bookmark checkpoint belongs to another signed-in account")
    if (type(current["version"]) is not int or current["version"] < 0
            or current["version"] > 2147483647
            or any(not isinstance(current[k], str) or not HASH_RE.fullmatch(current[k])
                   for k in ("local_hash", "remote_hash"))):
        raise BookmarkSyncError("Corrupt bookmark checkpoint; preserve local data")
    return current


def _remote(remote, space, passphrase):
    if not isinstance(remote, dict) or type(remote.get("version")) is not int:
        raise BookmarkSyncError("Malformed cloud bookmark version")
    version = remote["version"]
    if not 0 <= version <= 2147483647:
        raise BookmarkSyncError("Out-of-range bookmark cloud version")
    envelope = remote.get("envelope")
    if version == 0:
        if envelope is not None:
            raise BookmarkSyncError("Unversioned bookmark ciphertext rejected")
        return version, []
    if not isinstance(envelope, str) or not envelope:
        raise BookmarkSyncError("Missing cloud bookmark ciphertext")
    try:
        return version, decrypt_bookmarks(space, envelope, passphrase)
    except BookmarkError as exc:
        raise BookmarkSyncError("Cloud bookmark decrypt failed; local data remains intact") from exc


def _call(transport, method, space, data=None):
    if space not in ("private", "work") or not callable(getattr(transport, "call", None)):
        raise BookmarkSyncError("No authorized bookmark transport")
    # Caller supplies the existing VLESS-only SyncTransport23. No URL is taken
    # from a server response and no redirects/direct HTTP fallback are allowed.
    return transport.call(method, "/v1/bookmarks/" + space, data)


def first_sync(transport, owner, space, all_rows, passphrase, *, choice):
    """An explicitly consented one-time choice: 'upload' or 'download'.

    'download' returns only an additive preview. The caller must persist that
    preview before storing the proposed checkpoint, and must recheck local hash.
    """
    if choice not in ("upload", "download"):
        raise BookmarkSyncError("Explicit first-sync choice required")
    local = rows_in_space(all_rows, space)
    cloud_version, cloud_rows = _remote(_call(transport, "GET", space),
                                        space, passphrase)
    current_hash = fingerprint(local, space)
    if choice == "upload":
        if cloud_version != 0:
            raise BookmarkSyncError("Cloud already has bookmarks; explicit reconciliation required")
        crypt = encrypt_bookmarks(space, local, passphrase)
        ack = _call(transport, "PUT", space,
                    {"expected_version": 0, "envelope": crypt})
        if not isinstance(ack, dict) or type(ack.get("version")) is not int or ack["version"] != 1:
            raise BookmarkSyncError("Invalid first-upload acknowledgement; checkpoint unchanged")
        return {"kind": "uploaded", "version": 1,
                "checkpoint": checkpoint(owner, space, 1, local, local),
                "expected_local_hash": current_hash}
    if cloud_version == 0:
        return {"kind": "empty", "version": 0,
                "expected_local_hash": current_hash}
    preview = merge_bookmarks(local, cloud_rows, space)
    return {"kind": "download_pending", "records": preview,
            "version": cloud_version, "expected_local_hash": current_hash,
            "checkpoint": checkpoint(owner, space, cloud_version, preview, cloud_rows)}


def reconcile(transport, owner, space, all_rows, baseline, passphrase):
    """Pure local preview plus a versioned upload, never modifies browser files.

    Auto-download outcomes must first be reviewed/applied by the browser and
    its local fingerprint rechecked; it cannot directly overwrite documents.
    """
    local = rows_in_space(all_rows, space)
    previous = _checkpoint(baseline, owner, space)
    if previous is None:
        return {"kind": "uninitialized"}
    version, remote_rows = _remote(_call(transport, "GET", space),
                                    space, passphrase)
    if version < previous["version"]:
        return {"kind": "rollback"}
    cloud_hash = fingerprint(remote_rows, space)
    if version == previous["version"] and cloud_hash != previous["remote_hash"]:
        return {"kind": "tampered"}
    local_hash = fingerprint(local, space)
    here = local_hash != previous["local_hash"]
    there = version != previous["version"]
    if here and there:
        return {"kind": "conflict"}
    if here:
        crypt = encrypt_bookmarks(space, local, passphrase)
        ack = _call(transport, "PUT", space,
                    {"expected_version": version, "envelope": crypt})
        if not isinstance(ack, dict) or type(ack.get("version")) is not int or ack["version"] != version + 1:
            raise BookmarkSyncError("Invalid bookmark upload acknowledgement")
        return {"kind": "uploaded", "version": version + 1,
                "checkpoint": checkpoint(owner, space, version + 1, local, local),
                "expected_local_hash": local_hash}
    if there:
        merged = merge_bookmarks(local, remote_rows, space)
        return {"kind": "download_pending", "records": merged,
                "version": version, "expected_local_hash": local_hash,
                "checkpoint": checkpoint(owner, space, version, merged, remote_rows)}
    return {"kind": "unchanged", "version": version}


def accept_download(preview, owner, space, current_rows):
    """Validate pending preview against the *current* local space.

    Return records/checkpoint only; the app must commit both in encrypted
    local storage after user approval and a successful atomic library save.
    """
    if not isinstance(preview, dict) or preview.get("kind") != "download_pending":
        raise BookmarkSyncError("No pending download to approve")
    current_hash = fingerprint(current_rows, space)
    if preview.get("expected_local_hash") != current_hash:
        raise BookmarkSyncError("Local bookmarks changed since the download; import blocked")
    newrows = rows_in_space(preview.get("records"), space)
    c = _checkpoint(preview.get("checkpoint"), owner, space)
    if c is None or c["local_hash"] != fingerprint(newrows, space):
        raise BookmarkSyncError("Invalid bookmark import checkpoint")
    return {"records": newrows, "checkpoint": c}


def existing_authorized_transport(sync_state, proxy_process, proxy_port):
    """Use ONLY the established Glacier device session and running VLESS core.

    Returns (VLESS-only existing SyncTransport23, account scope); never accepts
    a caller-supplied username/token override or falls back to direct HTTPS.
    The browser must store checkpoints only in its existing OS-encrypted
    account session and use the returned account scope on every sync action.
    """
    if not isinstance(sync_state, dict) or sync_state.get("locked"):
        raise BookmarkSyncError("Glacier device session is unavailable")
    if (sync_state.get("approved") is not True
            or not all(isinstance(sync_state.get(k), str) and sync_state.get(k)
                       for k in ("base", "token", "username", "device_id"))):
        raise BookmarkSyncError("Glacier account and device approval required")
    if (proxy_process is None or not callable(getattr(proxy_process, "poll", None))
            or proxy_process.poll() is not None):
        raise BookmarkSyncError("VLESS is offline; bookmark sync cannot connect directly")
    if type(proxy_port) is not int or not 1 <= proxy_port <= 65535:
        raise BookmarkSyncError("Invalid local SOCKS5 port")
    from glacier_sync23 import SyncTransport23, sync_url23
    base = sync_url23(sync_state["base"])
    if not base or base != sync_state["base"]:
        raise BookmarkSyncError("Glacier Sync base URL is not secure")
    owner = base + "|" + sync_state["username"].casefold()
    return SyncTransport23(base, proxy_port, sync_state["token"]), owner
