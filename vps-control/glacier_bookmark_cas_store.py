"""Isolated SQL backend for E2E bookmark envelopes; not mounted in live VPS.

The current Glacier Sync account-vault backend is separate and MUST remain
unchanged. The caller must bind a verified user ID from the existing session
auth system: never trust user IDs supplied as request JSON. This module has
no HTTP routes, login implementation, or access to browser cookies.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

MAX_ENVELOPE = 350000
MAX_VERSION = 2147483647


class BookmarkStoreError(ValueError):
    pass


class BookmarkConflict(BookmarkStoreError):
    pass


def _user(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or not value.isascii() or
            not all(c.isalnum() or c in "_-:." for c in value)):
        raise BookmarkStoreError("Missing verified session identity")
    return value


def _space(value):
    if value not in ("private", "work"):
        raise BookmarkStoreError("Unsupported bookmark profile")
    return value


def _canonical_b64(value, maximum):
    if (not isinstance(value, str) or not value
            or len(value) > maximum or
            any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value)):
        raise BookmarkStoreError("Malformed bookmark ciphertext metadata")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise BookmarkStoreError("Invalid bookmark base64") from exc
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
        raise BookmarkStoreError("Noncanonical bookmark base64")
    return raw


def validate_envelope(envelope):
    """Inspect format only; the server never receives a decryption passphrase."""
    if not isinstance(envelope, str) or len(envelope) > MAX_ENVELOPE:
        raise BookmarkStoreError("Encrypted bookmark envelope too large")
    try:
        doc = json.loads(envelope)
    except (TypeError, ValueError) as exc:
        raise BookmarkStoreError("Malformed encrypted envelope") from exc
    if not isinstance(doc, dict) or set(doc) != {"format", "kdf", "salt", "nonce", "ciphertext"}:
        raise BookmarkStoreError("Unsupported encrypted envelope shape")
    if doc["format"] != "glacier-bookmarks-v1" or doc["kdf"] != "pbkdf2-sha256-400k":
        raise BookmarkStoreError("Unsupported encrypted bookmark format")
    if (len(_canonical_b64(doc["salt"], 50)) != 16 or
        len(_canonical_b64(doc["nonce"], 36)) != 12 or
        not 16 <= len(_canonical_b64(doc["ciphertext"], 270000)) <= 200000):
        raise BookmarkStoreError("Invalid bookmark envelope byte sizes")
    return envelope


class BookmarkCASStore:
    """Separate per-user/per-space encrypted records with atomic versioned CAS.

    No client can downgrade the version. The service must map the authenticated
    session's stable user ID to read/put calls and enforce TLS/VLESS upstream.
    """

    def __init__(self, sqlite_path):
        self.path = str(Path(sqlite_path))
        if not sqlite_path:
            raise BookmarkStoreError("Database path required")
        with self._conn() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS glacier_e2e_bookmarks_v1 (
                    user_id TEXT NOT NULL,
                    space TEXT NOT NULL CHECK(space IN ('private','work')),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    envelope TEXT NOT NULL,
                    PRIMARY KEY(user_id, space)
                )
            """)

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, verified_user_id, space):
        user = _user(verified_user_id)
        space = _space(space)
        with self._conn() as db:
            row = db.execute(
                "SELECT version,envelope FROM glacier_e2e_bookmarks_v1 WHERE user_id=? AND space=?",
                (user, space)).fetchone()
        return {"version": int(row[0]), "envelope": row[1]} if row else {"version": 0, "envelope": None}

    def put(self, verified_user_id, space, expected_version, envelope):
        user = _user(verified_user_id)
        space = _space(space)
        if type(expected_version) is not int or not 0 <= expected_version < MAX_VERSION:
            raise BookmarkStoreError("Invalid expected CAS version")
        validate_envelope(envelope)
        db = self._conn()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT version FROM glacier_e2e_bookmarks_v1 WHERE user_id=? AND space=?",
                (user, space)).fetchone()
            current = int(row[0]) if row else 0
            if current != expected_version:
                raise BookmarkConflict("Bookmark cloud record changed; do not overwrite")
            version = current + 1
            if row:
                db.execute(
                    "UPDATE glacier_e2e_bookmarks_v1 SET version=?,envelope=? WHERE user_id=? AND space=?",
                    (version, envelope, user, space))
            else:
                db.execute(
                    "INSERT INTO glacier_e2e_bookmarks_v1(user_id,space,version,envelope) VALUES (?,?,?,?)",
                    (user, space, version, envelope))
            db.commit()
            return {"version": version}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
