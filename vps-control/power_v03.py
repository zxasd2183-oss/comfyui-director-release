"""Two-factor power-operation request state machine (no web framework dependencies).

The MCP side can only CREATE a request. The approval side runs an independent
user-authentication ceremony and performs final state/queue checks before the
provider API is called. One-time TOTP approval is never shown to MCP/ChatGPT.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import time
from pathlib import Path

from power_ops import PowerError, build_plan, submit_power_request

TTL_SECONDS = 300
MAX_BAD_CODES = 5
DB_DEFAULT = "/var/lib/comfyui-director-power/requests.db"


def connect(db_path: str = DB_DEFAULT) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.parent.is_dir():
        raise RuntimeError("StateDirectory is missing; install service correctly.")
    if path.is_symlink():
        raise RuntimeError("Refuse symbolic link database")
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS requests ("
               "id TEXT PRIMARY KEY, action TEXT NOT NULL, state TEXT NOT NULL, "
               "created REAL NOT NULL, expires REAL NOT NULL, updated REAL NOT NULL, "
               "bad_codes INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '')")
    db.execute("CREATE TABLE IF NOT EXISTS audit ("
               "event_id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, "
               "action TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS auth ("
               "key TEXT PRIMARY KEY, number INTEGER NOT NULL)")
    if path.exists():
        os.chmod(path, 0o600)
    return db


def _audit(db, req_id: str, action: str, event: str, now: float):
    db.execute("INSERT INTO audit(request_id,action,event,at) VALUES(?,?,?,?)",
               (req_id, action, event, now))


def _public(row, now: float | None = None) -> dict:
    state = row["state"]
    if state == "pending" and row["expires"] <= (time.time() if now is None else now):
        state = "expired"
    return {"ok": True, "request_id": row["id"], "action": row["action"],
            "state": state, "expires_at": int(row["expires"]),
            "result": row["result"] or None}


def plan_and_request(action: str, config: dict, db_path: str = DB_DEFAULT,
                     plan_fn=build_plan, now: float | None = None) -> dict:
    if action not in ("start", "stop"):
        return {"ok": False, "reason": "invalid_action"}
    current = time.time() if now is None else now
    try:
        plan = plan_fn(action, config)
    except (PowerError, Exception):
        return {"ok": False, "reason": "preflight_unavailable"}
    if not plan.get("allowed"):
        return {"ok": False, "reason": plan.get("reason", "preflight_blocked"),
                "workload": plan.get("workload")}
    req_id = secrets.token_urlsafe(24)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute("SELECT COUNT(*) FROM requests WHERE state='pending' "
                            "AND expires>? ", (current,)).fetchone()[0]
        recent = db.execute("SELECT COUNT(*) FROM requests WHERE created>?",
                            (current - 300,)).fetchone()[0]
        if active or recent >= 5:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "pending_request_exists_or_rate_limited"}
        db.execute("INSERT INTO requests(id, action, state, created, expires, updated)"
                   " VALUES(?,?,?,?,?,?)",
                   (req_id, action, "pending", current, current+TTL_SECONDS, current))
        _audit(db, req_id, action, "created", current)
        db.execute("COMMIT")
    return {"ok": True, "request_id": req_id, "action": action,
            "state": "pending", "expires_in_seconds": TTL_SECONDS,
            "approval_required": "independent_browser_totp",
            "gpu_power_changed": False}


def request_status(request_id: str, db_path: str = DB_DEFAULT,
                   now: float | None = None) -> dict:
    if not isinstance(request_id, str) or len(request_id) > 80:
        return {"ok": False, "reason": "invalid_request_id"}
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        return {"ok": False, "reason": "request_not_found"}
    result = _public(row, now)
    if row["state"] == "pending":
        current = time.time() if now is None else now
        if row["expires"] <= current:
            result["state"] = "expired"
    return result


def totp_step(secret_b32: str, digits: str, now: float, last_step: int = -1) -> int | None:
    if not isinstance(digits, str) or len(digits) != 6 or not digits.isascii() or not digits.isdigit():
        return None
    secret = base64.b32decode(secret_b32.strip().upper() + "=" * (-len(secret_b32.strip()) % 8))
    if len(secret) < 20:
        raise RuntimeError("TOTP seed too short")
    current = int(now // 30)
    for step in (current, current - 1, current + 1):
        if step < 0 or step <= last_step:
            continue
        digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
        offset = digest[-1] & 15
        number = (struct.unpack(">I", digest[offset:offset+4])[0] & 0x7fffffff) % 1000000
        if hmac.compare_digest(f"{number:06d}", digits):
            return step
    return None


def approve_request(request_id: str, digits: str, typed_phrase: str, seed: str,
                    config: dict, db_path: str = DB_DEFAULT,
                    plan_fn=build_plan, submit_fn=submit_power_request,
                    now: float | None = None) -> dict:
    """Atomic one-time approval; UNKNOWN provider outcomes are never auto-retried."""
    current = time.time() if now is None else now
    if not isinstance(request_id, str) or not 20 <= len(request_id) <= 80:
        return {"ok": False, "reason": "invalid_request_id"}
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "request_not_found"}
        action = row["action"]
        phrase = "START GPU" if action == "start" else "STOP GPU"
        if row["state"] != "pending" or row["expires"] <= current:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "request_expired_or_consumed"}
        if row["bad_codes"] >= MAX_BAD_CODES:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "approval_locked"}
        if typed_phrase.strip() != phrase:
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "confirmation_phrase_mismatch"}
        previous = db.execute("SELECT number FROM auth WHERE key='last_totp_step'").fetchone()
        last_step = previous[0] if previous else -1
        try:
            step = totp_step(seed, digits, current, last_step)
        except (ValueError, RuntimeError, base64.binascii.Error):
            db.execute("ROLLBACK")
            return {"ok": False, "reason": "otp_configuration_invalid"}
        if step is None:
            count = row["bad_codes"] + 1
            db.execute("UPDATE requests SET bad_codes=?, updated=? WHERE id=?",
                       (count, current, request_id))
            _audit(db, request_id, action, "bad_code", current)
            db.execute("COMMIT")
            return {"ok": False, "reason": "invalid_or_replayed_otp",
                    "remaining_attempts": max(0, MAX_BAD_CODES-count)}
        db.execute("INSERT INTO auth(key,number) VALUES('last_totp_step',?) "
                   "ON CONFLICT(key) DO UPDATE SET number=excluded.number", (step,))
        db.execute("UPDATE requests SET state='executing',updated=? WHERE id=?",
                   (current, request_id))
        _audit(db, request_id, action, "approved", current)
        db.execute("COMMIT")
    # The credential never reaches ChatGPT and the transaction is consumed.
    # A crash or network timeout here leaves the request in "executing".
    state = "blocked"
    result = "state_or_ue_workload_changed"
    try:
        plan = plan_fn(action, config)
        if plan.get("allowed"):
            response = submit_fn(action, config)
            if response.get("accepted") is True:
                state, result = "submitted", "accepted_by_provider_verify_final_state"
            else:
                state, result = "error", "provider_not_accepted"
    except Exception:
        state, result = "error", "provider_request_uncertain_check_status"
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE requests SET state=?,result=?,updated=? "
                   "WHERE id=? AND state='executing'",
                   (state, result, time.time(), request_id))
        _audit(db, request_id, action, state, time.time())
        db.execute("COMMIT")
    return {"ok": state == "submitted", "action": action, "state": state,
            "result": result, "request_id": request_id}
