"""V0.6 mobile-specific power approvals: device-bound, per-request ECDSA signatures.

This is a SECOND independent approval path to the existing V0.3 5-minute
requests, not an MCP power tool. No Microsoft token or biometric secret is
accepted from ChatGPT. All cloud operations still require a fresh preflight.
"""
from __future__ import annotations

import base64
import hmac
import re
import secrets
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from power_v03 import DB_DEFAULT, _audit, connect as power_connect
from power_ops import build_plan, submit_power_request

CHALLENGE_TTL = 90
MAX_KEY_BYTES = 1024


class Rejected(Exception):
    """Expected denial; safe to expose this fixed, nonsecret reason."""


def b64_decode(value: str, max_len: int) -> bytes:
    if not isinstance(value, str) or len(value) > max_len * 2 or not value:
        raise Rejected("invalid_encoding")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error):
        raise Rejected("invalid_encoding") from None


def validate_push_token(token: str) -> None:
    """Legacy fcm_token storage holds FCM or prefixed Xiaomi regId.
    Token never conveys authorization to approve the GPU.
    """
    if not isinstance(token, str) or len(token) > 2048:
        raise Rejected("push_token_invalid")
    if token.startswith("xm:") and not re.fullmatch(r"xm:[A-Za-z0-9_-]{8,256}", token):
        raise Rejected("push_token_invalid")


def with_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS mobile_device (
        id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL, pubkey_der BLOB NOT NULL,
        fcm_token TEXT NOT NULL DEFAULT '', created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS mobile_challenge (
        request_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, nonce TEXT NOT NULL,
        decision TEXT NOT NULL, expires REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS mobile_push (
        request_id TEXT PRIMARY KEY, last_attempt REAL NOT NULL DEFAULT 0,
        tries INTEGER NOT NULL DEFAULT 0, sent INTEGER NOT NULL DEFAULT 0)""")


def open_db(path=DB_DEFAULT):
    db = power_connect(path)
    with_schema(db)
    return db


def ensure_owner(db, subject: str):
    if not isinstance(subject, str) or not 8 <= len(subject) <= 256:
        raise Rejected("identity_invalid")
    row = db.execute("SELECT * FROM mobile_device LIMIT 1").fetchone()
    if row is None or not hmac.compare_digest(row["owner_sub"], subject):
        raise Rejected("device_not_enrolled")
    return row


def enroll(subject: str, pairing: str, expected_pairing: str,
           public_key_b64: str, fcm_token: str = "",
           db_path: str = DB_DEFAULT, now: float | None = None) -> dict:
    """First-owner enrollment requires BOTH signed Microsoft ID token verification
    by the HTTP layer AND a one-time root-only pairing secret entered on phone.
    No second enrollment occurs without an explicit local administrator reset.
    """
    if not isinstance(subject, str) or not 8 <= len(subject) <= 256:
        raise Rejected("identity_invalid")
    if (not isinstance(pairing, str) or not isinstance(expected_pairing, str)
            or len(expected_pairing) < 32
            or not hmac.compare_digest(pairing, expected_pairing)):
        raise Rejected("pairing_invalid")
    validate_push_token(fcm_token)
    der = b64_decode(public_key_b64, MAX_KEY_BYTES)
    try:
        pub = serialization.load_der_public_key(der)
        if not isinstance(pub, ec.EllipticCurvePublicKey) or not isinstance(pub.curve, ec.SECP256R1):
            raise Rejected("key_must_be_p256")
    except (ValueError, TypeError):
        raise Rejected("invalid_public_key") from None
    when = time.time() if now is None else now
    device_id = secrets.token_urlsafe(18)
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM mobile_device LIMIT 1").fetchone():
            db.execute("ROLLBACK")
            raise Rejected("device_already_enrolled")
        db.execute("INSERT INTO mobile_device(id,owner_sub,pubkey_der,fcm_token,created)"
                   " VALUES(?,?,?,?,?)",
                   (device_id, subject, der, fcm_token, when))
        db.execute("COMMIT")
    return {"ok": True, "device_id": device_id, "push_configured": bool(fcm_token)}


def update_push(subject: str, device_id: str, token: str, db_path=DB_DEFAULT) -> dict:
    validate_push_token(token)
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = ensure_owner(db, subject)
        if not hmac.compare_digest(row["id"], device_id):
            db.execute("ROLLBACK")
            raise Rejected("wrong_device")
        db.execute("UPDATE mobile_device SET fcm_token=? WHERE id=?", (token, device_id))
        db.execute("COMMIT")
    return {"ok": True}


def pending(subject: str, device_id: str, db_path=DB_DEFAULT,
            now: float | None = None) -> dict:
    current = time.time() if now is None else now
    with open_db(db_path) as db:
        owner = ensure_owner(db, subject)
        if not hmac.compare_digest(owner["id"], device_id):
            raise Rejected("wrong_device")
        rows = db.execute("SELECT id,action,expires FROM requests WHERE state='pending'"
                          " AND expires>? ORDER BY created DESC LIMIT 5", (current,)).fetchall()
    return {"ok": True, "requests": [{"request_id":r["id"], "action":r["action"],
                                      "expires_at":int(r["expires"])} for r in rows]}


def signed_message(request_id: str, action: str, decision: str,
                   nonce: str, expires: int, device_id: str) -> bytes:
    # Exact canonical byte string. Android signs this with Keystore P-256 ECDSA.
    return ("JIPITE-V0.6\n" + request_id + "\n" + action + "\n" + decision +
            "\n" + nonce + "\n" + str(expires) + "\n" + device_id).encode("ascii")


def challenge(subject: str, device_id: str, request_id: str, decision: str,
              db_path=DB_DEFAULT, now: float | None = None) -> dict:
    current = time.time() if now is None else now
    if decision not in ("approve", "deny") or not isinstance(request_id, str) or len(request_id) > 80:
        raise Rejected("invalid_request")
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        owner = ensure_owner(db, subject)
        if not hmac.compare_digest(owner["id"], device_id):
            db.execute("ROLLBACK")
            raise Rejected("wrong_device")
        req = db.execute("SELECT id,action,state,expires FROM requests WHERE id=?",
                         (request_id,)).fetchone()
        if req is None or req["state"] != "pending" or req["expires"] <= current:
            db.execute("ROLLBACK")
            raise Rejected("request_expired_or_consumed")
        nonce = secrets.token_urlsafe(24)
        # Use integer seconds consistently to avoid timezone/floating mismatch.
        expires = min(int(req["expires"]), int(current)+CHALLENGE_TTL)
        db.execute("INSERT INTO mobile_challenge(request_id,device_id,nonce,decision,expires)"
                   " VALUES(?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET "
                   "device_id=excluded.device_id,nonce=excluded.nonce,"
                   "decision=excluded.decision,expires=excluded.expires",
                   (request_id, device_id, nonce, decision, expires))
        db.execute("COMMIT")
    canonical = signed_message(request_id, req["action"], decision, nonce, expires, device_id)
    return {"ok": True, "request_id": request_id, "action":req["action"],
            "decision":decision, "expires_at":expires, "nonce":nonce,
            "payload_b64":base64.b64encode(canonical).decode("ascii")}


def decide(subject: str, device_id: str, request_id: str, nonce: str,
           signature_b64: str, decision: str, config: dict, db_path=DB_DEFAULT,
           now: float | None = None, plan_fn=build_plan,
           submit_fn=submit_power_request) -> dict:
    """Consume a biometric signature exactly once, before any cloud API call.

    On a crash/uncertain network result, the request cannot be reused.
    """
    current = time.time() if now is None else now
    if decision not in ("approve", "deny") or not isinstance(request_id, str) or len(request_id) > 80:
        raise Rejected("invalid_request")
    signature = b64_decode(signature_b64, 256)
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        owner = ensure_owner(db, subject)
        if not hmac.compare_digest(owner["id"], device_id):
            db.execute("ROLLBACK")
            raise Rejected("wrong_device")
        req = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        chl = db.execute("SELECT * FROM mobile_challenge WHERE request_id=?",
                         (request_id,)).fetchone()
        if (req is None or chl is None or req["state"] != "pending"
                or req["expires"] <= current or chl["expires"] <= current
                or chl["nonce"] != nonce or chl["device_id"] != device_id
                or chl["decision"] != decision):
            db.execute("ROLLBACK")
            raise Rejected("challenge_expired_or_consumed")
        message = signed_message(request_id, req["action"], decision, nonce,
                                 int(chl["expires"]), device_id)
        try:
            key = serialization.load_der_public_key(owner["pubkey_der"])
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError):
            db.execute("ROLLBACK")
            raise Rejected("biometric_signature_invalid") from None
        target_state = "executing" if decision == "approve" else "denied"
        db.execute("UPDATE requests SET state=?,updated=? WHERE id=?",
                   (target_state, current, request_id))
        db.execute("DELETE FROM mobile_challenge WHERE request_id=?", (request_id,))
        _audit(db, request_id, req["action"], "mobile_"+decision, current)
        db.execute("COMMIT")
    if decision == "deny":
        return {"ok": True, "request_id":request_id, "state":"denied"}
    state, result = "blocked", "state_or_queue_changed"
    try:
        plan = plan_fn(req["action"], config)
        if plan.get("allowed"):
            output = submit_fn(req["action"], config)
            if output.get("accepted") is True:
                state, result = "submitted", "accepted_by_provider_verify_final_state"
            else:
                state, result = "error", "provider_not_accepted"
    except Exception:
        state, result = "error", "provider_request_uncertain_check_status"
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE requests SET state=?,result=?,updated=? WHERE id=? AND state='executing'",
                   (state, result, time.time(), request_id))
        _audit(db, request_id, req["action"], state, time.time())
        db.execute("COMMIT")
    return {"ok":state == "submitted", "request_id":request_id, "action":req["action"],
            "state":state, "result":result}
