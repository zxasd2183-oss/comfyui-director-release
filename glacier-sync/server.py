"""Glacier Sync v1: self-hosted encrypted vault relay.

The server never receives a decrypted vault or the vault passphrase.
Production requires HTTPS at the reverse proxy, a private bootstrap invite,
persistent SQLite file, and a strong account password. Do not expose the raw
uvicorn port directly to the Internet.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

DB = Path(os.environ.get("GLACIER_SYNC_DB", "./glacier-sync.sqlite3"))
INVITE = os.environ.get("GLACIER_SYNC_INVITE", "")
SESSION_SECONDS = 24 * 3600
PENDING_SECONDS = 15 * 60
MAX_VAULT = 256 * 1024
LOCK = threading.RLock()
app = FastAPI(title="Glacier Sync", version="1.0.0", docs_url=None, redoc_url=None)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


@contextmanager
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        connection = sqlite3.connect(DB, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


@app.on_event("startup")
def initialize():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
          salt BLOB NOT NULL, password_digest BLOB NOT NULL,
          created INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS devices (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          name TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
          created INTEGER NOT NULL, approved_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          device_id TEXT NOT NULL REFERENCES devices(id),
          expires INTEGER NOT NULL, pending INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS owner_devices (
          device_id TEXT PRIMARY KEY REFERENCES devices(id)
        );
        CREATE TABLE IF NOT EXISTS device_grants (
          device_id TEXT NOT NULL REFERENCES devices(id),
          space TEXT NOT NULL,
          PRIMARY KEY(device_id, space)
        );
        CREATE TABLE IF NOT EXISTS space_vaults (
          user_id TEXT NOT NULL REFERENCES users(id),
          space TEXT NOT NULL, version INTEGER NOT NULL,
          envelope TEXT NOT NULL, updated INTEGER NOT NULL,
          PRIMARY KEY(user_id,space)
        );
        CREATE TABLE IF NOT EXISTS vaults (
          user_id TEXT PRIMARY KEY REFERENCES users(id),
          version INTEGER NOT NULL, envelope TEXT NOT NULL,
          updated INTEGER NOT NULL
        );
        """)


class Register(BaseModel):
    invite: str = Field(min_length=12, max_length=256)
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=12, max_length=256)
    device_name: str = Field(min_length=1, max_length=80)


class Login(BaseModel):
    username: str
    password: str
    device_name: str = Field(min_length=1, max_length=80)
    device_id: str | None = None


class Grants(BaseModel):
    spaces: list[str] = Field(min_length=1, max_length=2)


def validate_spaces(spaces):
    if len(set(spaces)) != len(spaces) or not all(
            space in ("private", "work") for space in spaces):
        raise HTTPException(status_code=422, detail="Invalid account spaces")
    return spaces


def require_owner(conn, session):
    owner = conn.execute("SELECT 1 FROM owner_devices WHERE device_id=?",
                         (session["device_id"],)).fetchone()
    if not owner:
        raise HTTPException(status_code=403, detail="Owner device required")


def require_space(conn, session, space):
    if space not in ("private", "work"):
        raise HTTPException(status_code=404, detail="Unknown account space")
    grant = conn.execute("""
      SELECT 1 FROM device_grants WHERE device_id=? AND space=?
    """, (session["device_id"], space)).fetchone()
    if not grant:
        raise HTTPException(status_code=403, detail="Account space not shared with device")


class Vault(BaseModel):
    expected_version: int = Field(ge=0)
    envelope: str = Field(min_length=32, max_length=MAX_VAULT)


def valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_.-]{3,80}", name))


def token_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization required")
    token = authorization[7:]
    if len(token) != 64 or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise HTTPException(status_code=401, detail="Invalid session")
    return digest(token)


def authorize(conn, authorization: str | None, *, pending=False):
    row = conn.execute("""
        SELECT s.user_id, s.device_id, s.pending, s.expires, d.approved
          FROM sessions s JOIN devices d ON d.id=s.device_id
         WHERE s.token_hash=?
    """, (token_header(authorization),)).fetchone()
    if not row or row["expires"] < time.time() or (not pending and
            (row["pending"] or not row["approved"])):
        raise HTTPException(status_code=401, detail="Session unavailable")
    return row


def issue_session(conn, user_id, device_id, *, pending):
    token = secrets.token_hex(32)
    expires = int(time.time()) + (PENDING_SECONDS if pending else SESSION_SECONDS)
    conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?)",
                 (digest(token), user_id, device_id, expires, int(pending)))
    return {"token": token, "device_id": device_id,
            "approved": not pending, "expires_at": expires}


@app.get("/health")
def health():
    return {"status": "ok", "service": "glacier-sync", "version": 1}


@app.post("/v1/register", status_code=201)
def register(data: Register):
    if not INVITE or not hmac.compare_digest(data.invite, INVITE):
        raise HTTPException(status_code=403, detail="Registration disabled")
    if not valid_name(data.username):
        raise HTTPException(status_code=422, detail="Invalid account name")
    now = int(time.time())
    salt = secrets.token_bytes(16)
    user_id, device_id = secrets.token_hex(16), secrets.token_hex(16)
    with db() as conn:
        try:
            conn.execute("INSERT INTO users VALUES(?,?,?,?,?)",
                         (user_id, data.username, salt,
                          password_hash(data.password, salt), now))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Account already exists")
        conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?)",
                     (device_id, user_id, data.device_name, 1, now, now))
        conn.execute("INSERT INTO owner_devices VALUES(?)", (device_id,))
        conn.executemany("INSERT INTO device_grants VALUES(?,?)",
                         [(device_id, "private"), (device_id, "work")])
        return issue_session(conn, user_id, device_id, pending=False)


@app.post("/v1/login")
def login(data: Login):
    # Password verification precedes any device grant. Unknown devices remain
    # pending until an approved session explicitly authorizes them.
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE name=?",
                            (data.username,)).fetchone()
        salt = user["salt"] if user else b"no-such-glacier-user"
        candidate = password_hash(data.password, salt)
        if not user or not hmac.compare_digest(candidate, user["password_digest"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        known = None
        if data.device_id:
            known = conn.execute("SELECT * FROM devices WHERE id=? AND user_id=?",
                                 (data.device_id, user["id"])).fetchone()
            if not known:
                raise HTTPException(status_code=403, detail="Device was removed")
        device_id = known["id"] if known else secrets.token_hex(16)
        approved = bool(known and known["approved"])
        if not known:
            conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,NULL)",
                         (device_id, user["id"], data.device_name, 0, int(time.time())))
        return issue_session(conn, user["id"], device_id, pending=not approved)


@app.get("/v1/session")
def session(authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization, pending=True)
        device = conn.execute("SELECT approved FROM devices WHERE id=?",
                              (session["device_id"],)).fetchone()
        return {"approved": bool(device["approved"]),
                "pending": bool(session["pending"]),
                "device_id": session["device_id"]}


@app.post("/v1/session/activate")
def activate(authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization, pending=True)
        if not session["approved"]:
            raise HTTPException(status_code=403, detail="Waiting for device approval")
        # Invalidate the pending token and issue a fresh full session.
        conn.execute("DELETE FROM sessions WHERE token_hash=?",
                     (token_header(authorization),))
        return issue_session(conn, session["user_id"], session["device_id"], pending=False)


@app.post("/v1/logout")
def logout(authorization: str | None = Header(default=None)):
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?",
                     (token_header(authorization),))
    return {"ok": True}


@app.get("/v1/devices")
def devices(authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization)
        entries = conn.execute("""
          SELECT id, name, approved, created, approved_at FROM devices
           WHERE user_id=? ORDER BY created DESC
        """, (session["user_id"],)).fetchall()
        result = []
        for item in entries:
            entry = dict(item)
            entry["owner"] = bool(conn.execute(
                "SELECT 1 FROM owner_devices WHERE device_id=?",
                (entry["id"],)).fetchone())
            entry["spaces"] = [row["space"] for row in conn.execute(
                "SELECT space FROM device_grants WHERE device_id=? ORDER BY space",
                (entry["id"],)).fetchall()]
            result.append(entry)
        return {"devices": result, "current_device_id": session["device_id"]}


@app.post("/v1/devices/{device_id}/approve")
def approve(device_id: str, authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization)
        require_owner(conn, session)
        if device_id == session["device_id"]:
            raise HTTPException(status_code=400, detail="Cannot self-approve")
        cursor = conn.execute("""
          UPDATE devices SET approved=1,approved_at=?
           WHERE id=? AND user_id=? AND approved=0
        """, (int(time.time()), device_id, session["user_id"]))
        if cursor.rowcount != 1:
            raise HTTPException(status_code=404, detail="No pending device")
        # Least privilege: newly approved devices start with private space.
        conn.execute("INSERT INTO device_grants VALUES(?,?)", (device_id, "private"))
        return {"approved": True, "spaces": ["private"]}


@app.delete("/v1/devices/{device_id}")
def revoke(device_id: str, authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization)
        require_owner(conn, session)
        if device_id == session["device_id"]:
            raise HTTPException(status_code=400, detail="Use logout for current device")
        cursor = conn.execute("DELETE FROM sessions WHERE device_id=? AND user_id=?",
                              (device_id, session["user_id"]))
        conn.execute("DELETE FROM device_grants WHERE device_id=?", (device_id,))
        found = conn.execute("DELETE FROM devices WHERE id=? AND user_id=?",
                             (device_id, session["user_id"]))
        if found.rowcount != 1:
            raise HTTPException(status_code=404, detail="Unknown device")
        return {"revoked": True}


@app.get("/v1/vault")
def read_vault(authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization)
        row = conn.execute("SELECT version,envelope FROM vaults WHERE user_id=?",
                           (session["user_id"],)).fetchone()
        return {"version": row["version"], "envelope": row["envelope"]} if row else {
            "version": 0, "envelope": None}


@app.put("/v1/vault")
def write_vault(data: Vault, authorization: str | None = Header(default=None)):
    try:
        wrapper = json.loads(data.envelope)
        if (wrapper.get("format") != "glacier-vault-v1"
                or not all(isinstance(wrapper.get(k), str)
                           for k in ("salt", "nonce", "ciphertext"))):
            raise ValueError("Bad encrypted envelope")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Expected encrypted vault envelope")
    with db() as conn:
        session = authorize(conn, authorization)
        row = conn.execute("SELECT version FROM vaults WHERE user_id=?",
                           (session["user_id"],)).fetchone()
        current = row["version"] if row else 0
        if current != data.expected_version:
            raise HTTPException(status_code=409, detail="Remote vault has changed")
        version = current + 1
        conn.execute("""
          INSERT INTO vaults(user_id,version,envelope,updated) VALUES(?,?,?,?)
          ON CONFLICT(user_id) DO UPDATE SET version=excluded.version,
            envelope=excluded.envelope,updated=excluded.updated
        """, (session["user_id"], version, data.envelope, int(time.time())))
        return {"version": version}

@app.put("/v1/devices/{device_id}/grants")
def set_device_grants(device_id: str, data: Grants,
                      authorization: str | None = Header(default=None)):
    spaces = validate_spaces(data.spaces)
    with db() as conn:
        session = authorize(conn, authorization)
        require_owner(conn, session)
        if conn.execute("SELECT 1 FROM owner_devices WHERE device_id=?",
                        (device_id,)).fetchone():
            raise HTTPException(status_code=400, detail="Owner grants cannot be changed")
        device = conn.execute("SELECT approved FROM devices WHERE id=? AND user_id=?",
                              (device_id, session["user_id"])).fetchone()
        if not device or not device["approved"]:
            raise HTTPException(status_code=404, detail="Approved device not found")
        conn.execute("DELETE FROM device_grants WHERE device_id=?", (device_id,))
        conn.executemany("INSERT INTO device_grants VALUES(?,?)",
                         [(device_id, space) for space in spaces])
        return {"spaces": spaces}


@app.get("/v1/spaces")
def my_spaces(authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization)
        spaces = [row["space"] for row in conn.execute(
            "SELECT space FROM device_grants WHERE device_id=? ORDER BY space",
            (session["device_id"],)).fetchall()]
        return {"spaces": spaces}


@app.get("/v1/vault/{space}")
def read_space(space: str, authorization: str | None = Header(default=None)):
    with db() as conn:
        session = authorize(conn, authorization)
        require_space(conn, session, space)
        row = conn.execute(
            "SELECT version,envelope FROM space_vaults WHERE user_id=? AND space=?",
            (session["user_id"], space)).fetchone()
        return {"version": row["version"], "envelope": row["envelope"]} if row else {
            "version": 0, "envelope": None}


@app.put("/v1/vault/{space}")
def write_space(space: str, data: Vault,
                authorization: str | None = Header(default=None)):
    try:
        wrapper = json.loads(data.envelope)
        if (not isinstance(wrapper, dict) or
                wrapper.get("format") != "glacier-vault-v1"
                or not all(isinstance(wrapper.get(k), str)
                           for k in ("salt", "nonce", "ciphertext"))):
            raise ValueError("Bad encrypted envelope")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Expected encrypted vault envelope")
    with db() as conn:
        session = authorize(conn, authorization)
        require_space(conn, session, space)
        row = conn.execute("SELECT version FROM space_vaults WHERE user_id=? AND space=?",
                           (session["user_id"], space)).fetchone()
        current = row["version"] if row else 0
        if current != data.expected_version:
            raise HTTPException(status_code=409, detail="Remote account space changed")
        version = current + 1
        conn.execute("""
          INSERT INTO space_vaults(user_id,space,version,envelope,updated)
          VALUES(?,?,?,?,?)
          ON CONFLICT(user_id,space) DO UPDATE SET version=excluded.version,
            envelope=excluded.envelope,updated=excluded.updated
        """, (session["user_id"], space, version, data.envelope, int(time.time())))
        return {"version": version}
