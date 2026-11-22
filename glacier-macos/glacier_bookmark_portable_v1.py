"""Glacier Bookmark Envelope v1: portable, opt-in E2E data only.

This module intentionally NEVER invokes account-vault routes or reads cookies,
tokens, passwords or browser profiles. Cloud transport requires a separately
authenticated bookmark endpoint; unsupported servers must fail closed.
"""
from __future__ import annotations
import base64
import json
import os
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

FORMAT = "glacier-bookmarks-v1"
KDF = "pbkdf2-sha256-400k"
LIMIT = 160
MAX_PLAIN = 150000
MAX_ENVELOPE = 350000
MAX_TIMESTAMP = 4102444800000


class BookmarkError(ValueError):
    pass


def _space(value):
    if value not in ("private", "work"):
        raise BookmarkError("Unknown bookmark space")
    return value


def _url(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 2048:
        raise BookmarkError("Invalid bookmark URL")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise BookmarkError("URL contains control characters")
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower()
        if u.scheme.lower() not in ("http", "https") or not host:
            raise BookmarkError("Unsupported bookmark scheme or host")
        if u.username is not None or u.password is not None:
            raise BookmarkError("Credential-bearing bookmark URL forbidden")
        if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost"):
            raise BookmarkError("Local browser address cannot be cloud-imported")
        _ = u.port
    except ValueError as exc:
        raise BookmarkError("Malformed bookmark URL") from exc
    return value


def _clean(rows, space):
    _space(space)
    if not isinstance(rows, list) or len(rows) > LIMIT:
        raise BookmarkError("Bookmark list exceeds space limit")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get("profile") != space:
            raise BookmarkError("Bookmark belongs to another space")
        url = _url(row.get("url"))
        title = row.get("title")
        if (not isinstance(title, str) or not title or len(title) > 180
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in title)):
            raise BookmarkError("Invalid bookmark title")
        stamp = row.get("at")
        if type(stamp) is not int or not 0 <= stamp <= MAX_TIMESTAMP:
            raise BookmarkError("Invalid bookmark timestamp")
        if url in seen:
            raise BookmarkError("Duplicate bookmark URL in one space")
        seen.add(url)
        result.append({"profile": space, "title": title, "url": url, "at": stamp})
    return result


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value):
    if not isinstance(value, str) or len(value) > MAX_ENVELOPE:
        raise BookmarkError("Malformed base64 field")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise BookmarkError("Invalid base64 alphabet")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64(raw) != value:
        raise BookmarkError("Noncanonical base64 field")
    return raw


def _key(password, salt):
    if not isinstance(password, str) or len(password) < 12 or len(salt) != 16:
        raise BookmarkError("Invalid bookmark passphrase or salt")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=salt, iterations=400000).derive(password.encode("utf-8"))


def encrypt_bookmarks(space, records, passphrase, *, salt=None, nonce=None):
    space = _space(space)
    rows = _clean(records, space)
    plain = json.dumps({"schema": 1, "space": space, "bookmarks": rows},
                       ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(plain) > MAX_PLAIN:
        raise BookmarkError("Bookmark snapshot too large")
    if salt is None:
        salt = os.urandom(16)
    if nonce is None:
        nonce = os.urandom(12)
    if not isinstance(salt, bytes) or len(salt) != 16 or not isinstance(nonce, bytes) or len(nonce) != 12:
        raise BookmarkError("Invalid encryption randomness")
    # Fixture callers may inject a fixed nonce; production callers do not.
    cipher = AESGCM(_key(passphrase, salt)).encrypt(
        nonce, plain, (FORMAT + ":" + space).encode("utf-8"))
    return json.dumps({"format": FORMAT, "kdf": KDF,
                       "salt": _b64(salt), "nonce": _b64(nonce),
                       "ciphertext": _b64(cipher)},
                      separators=(",", ":"))


def decrypt_bookmarks(space, envelope, passphrase):
    space = _space(space)
    if not isinstance(envelope, str) or len(envelope) > MAX_ENVELOPE:
        raise BookmarkError("Bookmark encrypted envelope too large")
    try:
        doc = json.loads(envelope)
        if not isinstance(doc, dict) or doc.get("format") != FORMAT or doc.get("kdf") != KDF:
            raise BookmarkError("Unsupported bookmark format")
        salt = _decode(doc["salt"])
        nonce = _decode(doc["nonce"])
        ciphertext = _decode(doc["ciphertext"])
        if len(salt) != 16 or len(nonce) != 12 or not 16 <= len(ciphertext) <= 200000:
            raise BookmarkError("Invalid bookmark envelope lengths")
        plain = AESGCM(_key(passphrase, salt)).decrypt(
            nonce, ciphertext, (FORMAT + ":" + space).encode("utf-8"))
        if len(plain) > MAX_PLAIN:
            raise BookmarkError("Decrypted bookmark data too large")
        data = json.loads(plain)
        if (not isinstance(data, dict) or type(data.get("schema")) is not int
                or data.get("schema") != 1 or data.get("space") != space):
            raise BookmarkError("Bookmark payload belongs to a different space")
        return _clean(data["bookmarks"], space)
    except (ValueError, KeyError, TypeError) as exc:
        raise BookmarkError("Encrypted bookmark data invalid or wrong passphrase") from exc
    except Exception as exc:
        raise BookmarkError("Cannot decrypt bookmark snapshot; local data unchanged") from exc


def merge_bookmarks(local, imported, space):
    """Pure, no-overwrite preview; caller commits only after explicit approval.

    Keep all local rows in existing order; append new imported rows within the
    160-per-space limit. If there is no space, refuse, rather than drop old data.
    """
    mine = _clean(local, space)
    incoming = _clean(imported, space)
    urls = {row["url"] for row in mine}
    result = list(mine)
    for row in incoming:
        if row["url"] in urls:
            continue
        if len(result) >= LIMIT:
            raise BookmarkError("Import would silently discard saved bookmarks")
        result.append(row)
        urls.add(row["url"])
    return result
