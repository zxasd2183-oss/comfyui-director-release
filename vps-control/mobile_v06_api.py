"""Local-only HTTP API for the V0.6 Android approval app.

Public Nginx must proxy ONLY /api/v1/mobile/* on jipite.borealos.cn.
No approval browser UI exists on this service. The legacy TOTP approval
service is deliberately unchanged for safe rollback.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mobile_v06_core import (Rejected, challenge, decide, enroll, open_db,
                             pending, update_push)
from power_ops import read_systemd_credential_env

PERSONAL_TID = "9188040d-6c67-4c5b-b112-36a304b66dad"
PERSONAL_ISSUER = f"https://login.microsoftonline.com/{PERSONAL_TID}/v2.0"
JWKS_URL = "https://login.microsoftonline.com/consumers/discovery/v2.0/keys"
MAX_BODY = 16384

class AuthRejected(Rejected):
    pass


class MicrosoftIdentity:
    def __init__(self, client_id: str):
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", client_id):
            raise ValueError("Microsoft app Client ID must be configured")
        import jwt
        self.jwt = jwt
        self.client_id = client_id
        self.jwks = jwt.PyJWKClient(JWKS_URL, cache_jwk_set=True,
                                    lifespan=300, timeout=5)
    def verify(self, token: str) -> str:
        if not isinstance(token, str) or len(token) < 100 or len(token) > 16384:
            raise AuthRejected("microsoft_auth_invalid")
        try:
            from jwt import InvalidTokenError
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = self.jwt.decode(
                token, key.key, algorithms=["RS256"], audience=self.client_id,
                issuer=PERSONAL_ISSUER,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=30)
            if claims.get("tid") != PERSONAL_TID or claims.get("ver") not in ("2.0", None):
                raise AuthRejected("microsoft_personal_only")
            subject = claims.get("sub")
            if not isinstance(subject, str) or not 8 <= len(subject) <= 256:
                raise AuthRejected("microsoft_auth_invalid")
            return subject
        except AuthRejected:
            raise
        except Exception:
            raise AuthRejected("microsoft_auth_invalid") from None


def fcm_sender(credentials_path: str):
    """Optional Firebase Admin SDK: only a request ID/action, NEVER an OTP,
    pairing secret, GPU provider credential or private MCP URL, is pushed.
    Google network access is required for real delivery.
    """
    if not credentials_path or not Path(credentials_path).is_file():
        return None
    import firebase_admin
    from firebase_admin import credentials, messaging
    app = firebase_admin.initialize_app(credentials.Certificate(credentials_path),
                                        name="jipite-mobile-approvals")
    def send(device_token: str, request_id: str, action: str):
        message = messaging.Message(
            token=device_token,
            data={"request_id":request_id, "action":action, "kind":"gpu-approval"},
            android=messaging.AndroidConfig(priority="high"))
        messaging.send(message, app=app)
    return send


def xiaomi_sender(secret_path: str, channel_path: str):
    """Mi Push enabled ONLY after owner installed a reviewed no-variable template."""
    if not Path(secret_path).is_file() or not Path(channel_path).is_file():
        return None
    from mobile_v06_xiaomi import send_xiaomi
    secret = Path(secret_path).read_text(encoding="ascii").strip()
    if not 8 <= len(secret) <= 256:
        raise RuntimeError("invalid Xiaomi server credentials")
    settings = json.loads(Path(channel_path).read_text(encoding="utf-8"))
    if not isinstance(settings, dict) or set(settings) != {"channel_id", "template_id"}:
        raise RuntimeError("invalid Xiaomi channel configuration")
    channel_id, template_id = settings["channel_id"], settings["template_id"]
    for value in (channel_id, template_id):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
            raise RuntimeError("invalid Xiaomi channel configuration")
    def send(reg_id: str, request_id: str, action: str, ttl_ms: int):
        send_xiaomi(reg_id, request_id, action, secret, ttl_ms=ttl_ms,
                    channel_id=channel_id, template_id=template_id)
    return send


def push_dispatcher(firebase, xiaomi):
    if firebase is None and xiaomi is None:
        return None
    def send(registration: str, request_id: str, action: str, ttl_ms: int):
        if registration.startswith("xm:"):
            if xiaomi is None:
                raise RuntimeError("xiaomi_push_not_configured")
            xiaomi(registration[3:], request_id, action, ttl_ms)
        else:
            if firebase is None:
                raise RuntimeError("fcm_not_configured")
            firebase(registration, request_id, action)
    return send


def notify_worker(db_path: str, sender, stop: threading.Event):
    """Best-effort delivery, never blocks MCP request creation or approval.
    Push has no authority. Only the app's biometric signature may approve.
    """
    if sender is None:
        return
    while not stop.wait(5):
        now = time.time()
        try:
            with open_db(db_path) as db:
                rows = db.execute("""
                    SELECT r.id,r.action,r.expires,d.fcm_token,
                           COALESCE(p.tries,0) AS tries
                    FROM requests r CROSS JOIN mobile_device d
                    LEFT JOIN mobile_push p ON p.request_id=r.id
                    WHERE r.state='pending' AND r.expires>? AND d.fcm_token!=''
                    AND COALESCE(p.sent,0)=0 AND COALESCE(p.tries,0)<3
                    AND COALESCE(p.last_attempt,0)<?
                    ORDER BY r.created LIMIT 3""", (now, now-20)).fetchall()
            for row in rows:
                delivered = False
                try:
                    sender(row["fcm_token"], row["id"], row["action"],
                           max(1000, int((row["expires"] - time.time()) * 1000)))
                    delivered = True
                except Exception:
                    pass
                with open_db(db_path) as db:
                    db.execute("INSERT INTO mobile_push(request_id,last_attempt,tries,sent)"
                               " VALUES(?,?,1,?) ON CONFLICT(request_id) DO UPDATE SET"
                               " last_attempt=excluded.last_attempt,tries=tries+1,"
                               " sent=excluded.sent",
                               (row["id"], time.time(), 1 if delivered else 0))
        except Exception:
            # Log no exceptions that could accidentally reveal provider responses or tokens.
            pass


def build_handler(identity, config_provider, pairing_code: str, db_path: str):
    paths = {"/api/v1/mobile/enroll", "/api/v1/mobile/pending",
             "/api/v1/mobile/challenge", "/api/v1/mobile/decision",
             "/api/v1/mobile/push"}
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *unused): pass

        def reply(self, status: int, value: dict):
            data = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"ok":True,"version":"0.6.0","mode":"device_signed"})
            else:
                self.reply(404, {"ok":False,"reason":"not_found"})
        def do_POST(self):
            if self.path not in paths or "?" in self.path:
                return self.reply(404, {"ok":False,"reason":"not_found"})
            if self.headers.get("Transfer-Encoding"):
                return self.reply(400, {"ok":False,"reason":"bad_encoding"})
            if "application/json" not in self.headers.get("Content-Type", "").lower():
                return self.reply(415, {"ok":False,"reason":"json_required"})
            try:
                n = int(self.headers.get("Content-Length","-1"))
                if not 2 <= n <= MAX_BODY:
                    return self.reply(413, {"ok":False,"reason":"bad_size"})
                body = json.loads(self.rfile.read(n))
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.reply(400, {"ok":False,"reason":"invalid_json"})
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                return self.reply(401, {"ok":False,"reason":"microsoft_login_required"})
            try:
                sub = identity.verify(authorization[len("Bearer "):])
            except AuthRejected as exc:
                return self.reply(401, {"ok":False,"reason":str(exc)})
            try:
                if self.path.endswith("/enroll"):
                    answer = enroll(sub, body.get("pairing_code"), pairing_code,
                                    body.get("public_key"), body.get("fcm_token",""),
                                    db_path)
                elif self.path.endswith("/pending"):
                    answer = pending(sub, body.get("device_id"), db_path)
                elif self.path.endswith("/challenge"):
                    answer = challenge(sub, body.get("device_id"),
                                       body.get("request_id"),
                                       body.get("decision"), db_path)
                elif self.path.endswith("/push"):
                    answer = update_push(sub, body.get("device_id"),
                                         body.get("fcm_token"), db_path)
                else:
                    answer = decide(sub, body.get("device_id"),
                                    body.get("request_id"), body.get("nonce"),
                                    body.get("signature"), body.get("decision"),
                                    config_provider(), db_path)
                self.reply(200, answer)
            except Rejected as exc:
                self.reply(409, {"ok":False,"reason":str(exc)})
            except Exception:
                self.reply(503, {"ok":False,"reason":"service_unavailable"})
    return Handler


def main():
    directory = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not directory:
        raise SystemExit("Systemd LoadCredential required")
    def cred(name):
        value = (Path(directory) / name).read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError("Missing required runtime credential")
        return value

    client_id = cred("clientid")
    pairing_code = cred("pairing")
    identity = MicrosoftIdentity(client_id)
    config_path = str(Path(directory) / "directorenv")
    def power_config():
        return read_systemd_credential_env(config_path, directory)
    db_path = os.environ.get("DIRECTOR_POWER_DB",
                             "/var/lib/comfyui-director-power/requests.db")
    with open_db(db_path) as db:
        db.execute("SELECT 1")
    firebase_path = str(Path(directory) / "firebase")
    firebase = fcm_sender(firebase_path)
    xiaomi = xiaomi_sender(str(Path(directory) / "xiaomi"),
                           str(Path(directory) / "xiaomicfg"))
    sender = push_dispatcher(firebase, xiaomi)
    stop = threading.Event()
    worker = threading.Thread(target=notify_worker,
                              args=(db_path,sender,stop),daemon=True)
    worker.start()
    srv = ThreadingHTTPServer(("127.0.0.1", 8895),
                              build_handler(identity,power_config,pairing_code,db_path))
    srv.daemon_threads = True
    print("Jipite V0.6 mobile API: loopback-only 127.0.0.1:8895; "
          "FCM enabled=" + str(firebase is not None) +
          "; Mi Push enabled=" + str(xiaomi is not None),flush=True)
    try:
        srv.serve_forever()
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()
