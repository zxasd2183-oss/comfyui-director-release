"""Non-power, authenticated hardware-key proof for the enrolled Jipite phone.

This protocol NEVER creates GPU requests, invokes a provider, reads GPU
credentials, or calls decide(). The only database mutations are one-time,
short-lived challenge records in a separate table.

Android uses the existing hardware-backed per-use BIOMETRIC_STRONG key, and
the VPS validates a P-256 SHA256withECDSA signature with the registered key.
This verifies key possession, NOT remote Android hardware attestation.
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

from mobile_v06_core import DB_DEFAULT, Rejected, b64_decode, ensure_owner, open_db

TTL_SECONDS = 90
NONCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{24,64}\Z")
DOMAIN = "JIPITE-SELFTEST-V1"


def _owner(db, subject, device_id):
    if not isinstance(device_id, str) or not 8 <= len(device_id) <= 100:
        raise Rejected("invalid_device_id")
    row = ensure_owner(db, subject)
    if not hmac.compare_digest(row["id"], device_id):
        raise Rejected("wrong_device")
    return row


def _schema(db):
    # Isolated from real requests, GPU challenges, power state, and audit rows.
    db.execute("""CREATE TABLE IF NOT EXISTS mobile_selftest_nonce(
        device_id TEXT PRIMARY KEY,
        nonce TEXT NOT NULL,
        expires INTEGER NOT NULL
    )""")


def canonical(device_id: str, nonce: str, expires: int) -> bytes:
    if (not isinstance(device_id, str) or not 8 <= len(device_id) <= 100
            or not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None
            or not isinstance(expires, int) or expires <= 0):
        raise Rejected("invalid_selftest_challenge")
    return (DOMAIN + "\n" + device_id + "\n" + nonce + "\n" +
            str(expires)).encode("ascii")


def start(subject: str, device_id: str, db_path=DB_DEFAULT,
          now: float | None = None) -> dict:
    current = int(time.time() if now is None else now)
    nonce = secrets.token_urlsafe(24)
    expires = current + TTL_SECONDS
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        _owner(db, subject, device_id)
        _schema(db)
        # New starts invalidate a previous challenge for the same bound phone.
        db.execute(
            "INSERT INTO mobile_selftest_nonce(device_id,nonce,expires) "
            "VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET "
            "nonce=excluded.nonce,expires=excluded.expires",
            (device_id, nonce, expires)
        )
        db.execute("COMMIT")
    return {
        "ok": True,
        "nonce": nonce,
        "expires_at": expires,
        "payload_b64": base64.b64encode(canonical(device_id, nonce, expires)).decode("ascii"),
        "kind": "biometric_selftest"
    }


def verify(subject: str, device_id: str, nonce: str, signature_b64: str,
           db_path=DB_DEFAULT, now: float | None = None) -> dict:
    current = int(time.time() if now is None else now)
    if not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None:
        raise Rejected("invalid_selftest_challenge")
    signature = b64_decode(signature_b64, 256)
    with open_db(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        owner = _owner(db, subject, device_id)
        _schema(db)
        challenge = db.execute(
            "SELECT nonce,expires FROM mobile_selftest_nonce WHERE device_id=?",
            (device_id,)
        ).fetchone()
        if (challenge is None or challenge["expires"] <= current
                or not hmac.compare_digest(challenge["nonce"], nonce)):
            db.execute("ROLLBACK")
            raise Rejected("selftest_expired_or_consumed")
        message = canonical(device_id, nonce, int(challenge["expires"]))
        # Consume BEFORE verification: an invalid signature cannot be retried
        # to brute-force the same server challenge. Concurrent verification
        # sees no nonce after the transaction commits.
        db.execute(
            "DELETE FROM mobile_selftest_nonce WHERE device_id=? AND nonce=?",
            (device_id, nonce)
        )
        db.execute("COMMIT")
        public_der = owner["pubkey_der"]
    try:
        key = serialization.load_der_public_key(public_der)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
                key.curve, ec.SECP256R1):
            raise ValueError("not enrolled P-256")
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        raise Rejected("selftest_signature_invalid") from None
    # No GPU request ID, power state, configuration or sensitive identifiers.
    return {
        "ok": True,
        "identity_verified": True,
        "device_bound": True,
        "signature_verified": True,
        "one_time_challenge_consumed": True,
        "gpu_operation_performed": False
    }
