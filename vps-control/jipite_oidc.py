"""Verify GitHub Actions OIDC tokens for Jipite's *sync-only* VPS webhook.

No shared secret or SSH credential in GitHub Actions. Only the dedicated
workflow running on this repository's main branch can trigger a read-only
sync of signed APK releases. GitHub's public JWKS is fetched via HTTPS.

Uses the VPS system's OpenSSL CLI to verify RS256 (stdlib + openssl only).
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = ISSUER + "/.well-known/jwks"
AUDIENCE = "jipite-vps-update-sync"
REPOSITORY = "zxasd2183-oss/comfyui-director-release"
REPOSITORY_ID = "1444506143"
WORKFLOW_REF = REPOSITORY + "/.github/workflows/jipite-immediate-sync.yml@refs/heads/main"
SUBJECT = "repo:" + REPOSITORY + ":ref:refs/heads/main"
MAX_TOKEN_LENGTH = 10000
MAX_JWKS_BYTES = 100000


class AuthenticationFailure(ValueError):
    pass


def b64url(text: str) -> bytes:
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise AuthenticationFailure("Malformed base64url segment")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise AuthenticationFailure("Invalid base64url encoding") from exc


def _der_length(length: int) -> bytes:
    if length < 0:
        raise AuthenticationFailure("Negative DER length")
    if length < 128:
        return bytes([length])
    encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(encoded)]) + encoded


def _der(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(payload)) + payload


def _der_int(raw: bytes) -> bytes:
    value = raw.lstrip(b"\x00")
    if not value:
        raise AuthenticationFailure("Invalid RSA integer")
    if value[0] & 0x80:
        value = b"\x00" + value
    return _der(0x02, value)


def public_key_pem(jwk: dict) -> bytes:
    """Construct standard SubjectPublicKeyInfo PEM for the pinned RSA JWK."""
    if jwk.get("kty") != "RSA" or jwk.get("use", "sig") != "sig":
        raise AuthenticationFailure("Not an RSA signing key")
    if jwk.get("alg", "RS256") != "RS256":
        raise AuthenticationFailure("Unexpected JWT signing algorithm")
    modulus, exponent = b64url(jwk["n"]), b64url(jwk["e"])
    if len(modulus) < 256 or len(modulus) > 1024 or len(exponent) > 8:
        raise AuthenticationFailure("Unexpected RSA public key size")
    rsa_key = _der(0x30, _der_int(modulus) + _der_int(exponent))
    rsa_algorithm = _der(0x30, bytes.fromhex("06092a864886f70d010101") + b"\x05\x00")
    spki = _der(0x30, rsa_algorithm + _der(0x03, b"\x00" + rsa_key))
    encoded = base64.b64encode(spki).decode("ascii")
    lines = "\n".join(encoded[i:i + 64] for i in range(0, len(encoded), 64))
    return ("-----BEGIN PUBLIC KEY-----\n" + lines +
            "\n-----END PUBLIC KEY-----\n").encode("ascii")


def check_claims(payload: dict, now: int | None = None) -> None:
    if not isinstance(payload, dict):
        raise AuthenticationFailure("Malformed token claims")
    required = {
        "iss": ISSUER, "aud": AUDIENCE, "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID, "ref": "refs/heads/main",
        "event_name": "workflow_run", "workflow_ref": WORKFLOW_REF,
        "sub": SUBJECT,
    }
    for name, expected in required.items():
        if payload.get(name) != expected:
            raise AuthenticationFailure("OIDC claim mismatch: " + name)
    current = int(time.time() if now is None else now)
    for key in ("exp", "iat", "nbf"):
        if not isinstance(payload.get(key), int):
            raise AuthenticationFailure("Missing or invalid temporal claim: " + key)
    if not current < payload["exp"] <= current + 600:
        raise AuthenticationFailure("Expired or unusually long OIDC token")
    if not current - 300 <= payload["iat"] <= current + 60:
        raise AuthenticationFailure("Stale or future OIDC issuance time")
    if payload["nbf"] > current + 60 or payload["iat"] > payload["exp"]:
        raise AuthenticationFailure("OIDC token not yet valid")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("sha", ""))):
        raise AuthenticationFailure("Invalid workflow commit SHA")
    if not re.fullmatch(r"[1-9][0-9]{0,24}", str(payload.get("run_id", ""))):
        raise AuthenticationFailure("Invalid workflow run id")


def get_jwks():
    with urlopen(Request(JWKS_URL, headers={
        "Accept": "application/json", "User-Agent": "jipite-vps-oidc/1.0"
    }), timeout=8) as response:
        data = response.read(MAX_JWKS_BYTES + 1)
        if len(data) > MAX_JWKS_BYTES:
            raise AuthenticationFailure("JWK payload too large")
        return json.loads(data)


def verify(token: str, *, jwks=None, now: int | None = None) -> dict:
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        raise AuthenticationFailure("Token missing or too long")
    segments = token.split(".")
    if len(segments) != 3:
        raise AuthenticationFailure("Malformed JWT")
    header_b64, payload_b64, signature_b64 = segments
    try:
        header = json.loads(b64url(header_b64))
        payload = json.loads(b64url(payload_b64))
    except (ValueError, UnicodeError) as exc:
        raise AuthenticationFailure("Invalid JWT header or payload") from exc
    if not isinstance(header, dict) or header.get("alg") != "RS256":
        raise AuthenticationFailure("Expected RS256 only")
    kid = header.get("kid")
    if not isinstance(kid, str) or not 1 <= len(kid) <= 180:
        raise AuthenticationFailure("Missing JWT key ID")
    # Check claims before doing network I/O. Signature verification is still
    # mandatory before any side effect can occur.
    check_claims(payload, now)
    keys = get_jwks() if jwks is None else jwks
    selected = [key for key in keys.get("keys", [])
                if isinstance(key, dict) and key.get("kid") == kid]
    if len(selected) != 1:
        raise AuthenticationFailure("Unknown OIDC signing key")
    pem = public_key_pem(selected[0])
    signature = b64url(signature_b64)
    if len(signature) < 256:
        raise AuthenticationFailure("Invalid JWT signature length")
    with tempfile.TemporaryDirectory(prefix="jipite-jwt-") as directory:
        root = Path(directory)
        (root / "public.pem").write_bytes(pem)
        (root / "signature.bin").write_bytes(signature)
        process = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(root / "public.pem"),
             "-signature", str(root / "signature.bin")],
            input=(header_b64 + "." + payload_b64).encode("ascii"),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=False, timeout=5,
        )
    if process.returncode != 0:
        raise AuthenticationFailure("Invalid GitHub OIDC signature")
    return payload
