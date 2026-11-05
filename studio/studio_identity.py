"""V0.9.1 Microsoft personal-account Web OIDC login for Director Studio.

Owner ONLY: client ID must match the existing Jipite Android app registration,
and the expected pairwise 'sub' is copied by a local root-only setup tool from
the previously enrolled owner (not user input or the first public visitor).
Auth-code + PKCE/state/nonce via MSAL, independently signature-validated ID
token with pinned Microsoft consumers issuer and trusted JWKS.
Tokens never enter browser storage, logs, SQLite or provider-facing tools.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

PERSONAL_TID = "9188040d-6c67-4c5b-b112-36a304b66dad"
ISSUER = "https://login.microsoftonline.com/" + PERSONAL_TID + "/v2.0"
AUTHORITY = "https://login.microsoftonline.com/consumers"
JWKS_URL = AUTHORITY + "/discovery/v2.0/keys"
REDIRECT = "https://jipite.borealos.cn/studio/auth/callback"
COOKIE_SID = "__Secure-director_studio_sid"
COOKIE_STATE = "__Secure-director_studio_flow"
MAX_PENDING = 32
MAX_SESSIONS = 20
FLOW_TTL = 300
SESSION_TTL = 7200
SESSION_IDLE = 1800
_CLIENT_ID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_OWNER_SUB = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
_TOKEN_ID = re.compile(r"^[A-Za-z0-9_-]{24,96}$")
_STATE_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class IdentityError(ValueError):
    pass


def _valid_config(config):
    if not isinstance(config, dict) or set(config) != {"client_id", "client_secret", "owner_sub"}:
        raise IdentityError("identity_config_invalid")
    if not isinstance(config["client_id"], str) or not _CLIENT_ID.fullmatch(config["client_id"]):
        raise IdentityError("identity_client_id_invalid")
    if not isinstance(config["client_secret"], str) or not 12 <= len(config["client_secret"]) <= 2048:
        raise IdentityError("identity_client_credential_invalid")
    if not isinstance(config["owner_sub"], str) or not _OWNER_SUB.fullmatch(config["owner_sub"]):
        raise IdentityError("identity_owner_not_bound")
    return config


def load_systemd_config(environ=None):
    env = environ if environ is not None else os.environ
    directory = env.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None  # Microsoft SSO not installed; local SSH mode remains available.
    root = Path(directory)
    source = root / "msweb"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 4096:
        return None  # fail closed on public proxy requests, no fallback to Basic bypass.
    try:
        return _valid_config(json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError):
        return None


def cookies(header):
    if not isinstance(header, str) or len(header) > 8192:
        return {}
    try:
        jar = SimpleCookie()
        jar.load(header)
        return {k:v.value for k,v in jar.items()}
    except Exception:
        return {}


def session_cookie(sid):
    if not _TOKEN_ID.fullmatch(sid):
        raise IdentityError("invalid_session_id")
    return (COOKIE_SID + "=" + sid +
            "; Path=/studio/; Max-Age=7200; Secure; HttpOnly; SameSite=Lax")


def state_cookie(state):
    if not _STATE_ID.fullmatch(state):
        raise IdentityError("invalid_auth_state")
    return (COOKIE_STATE + "=" + state +
            "; Path=/studio/; Max-Age=300; Secure; HttpOnly; SameSite=Lax")


def clear_cookie(name):
    if name not in (COOKIE_SID, COOKIE_STATE):
        raise IdentityError("invalid_cookie_name")
    return name + "=; Path=/studio/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"


def _now():
    return time.time()


class MicrosoftStudioIdentity:
    def __init__(self, config, *, msal_app=None, validator=None, clock=_now):
        self.config = _valid_config(config)
        self.clock = clock
        if msal_app is None:
            import msal
            msal_app = msal.ConfidentialClientApplication(
                config["client_id"], authority=AUTHORITY,
                client_credential=config["client_secret"],
                enable_pii_log=False)
        if validator is None:
            import jwt
            jwks = jwt.PyJWKClient(JWKS_URL, cache_jwk_set=True,
                                   lifespan=300, timeout=5)
            def validate(token):
                if not isinstance(token,str) or not 100 <= len(token) <= 16384:
                    raise IdentityError("invalid_id_token")
                key = jwks.get_signing_key_from_jwt(token)
                return jwt.decode(
                    token, key.key, algorithms=["RS256"],
                    audience=config["client_id"], issuer=ISSUER,
                    options={"require":["iss","aud","exp","iat","sub","nonce","tid"]},
                    leeway=30)
            validator = validate
        self.app = msal_app
        self.validate = validator
        self.lock = threading.Lock()
        self.pending = {}
        self.sessions = {}

    def start(self):
        flow = self.app.initiate_auth_code_flow(
            scopes=["openid", "profile"], redirect_uri=REDIRECT,
            response_mode="query", max_age=1200)
        if (not isinstance(flow,dict) or not _STATE_ID.fullmatch(str(flow.get("state",""))) or
                not isinstance(flow.get("code_verifier"),str) or
                len(flow["code_verifier"]) < 43 or
                not isinstance(flow.get("nonce"),str) or
                len(flow["nonce"]) < 16 or
                not isinstance(flow.get("auth_uri"),str) or
                not flow["auth_uri"].startswith(AUTHORITY+"/")):
            raise IdentityError("oidc_pkce_preflight_failed")
        state = flow["state"]
        now = self.clock()
        with self.lock:
            self.pending = {s:x for s,x in self.pending.items() if x[1] > now}
            if len(self.pending) >= MAX_PENDING:
                raise IdentityError("too_many_auth_flows")
            self.pending[state]=(flow, now+FLOW_TTL)
        return flow["auth_uri"],state

    def finish(self, query, state_cookie_value):
        if (not isinstance(query,dict) or set(query) != {"state","code"}
                or not _STATE_ID.fullmatch(str(query.get("state","")))
                or not isinstance(query.get("code"),str)
                or not 12 <= len(query["code"]) <= 8192
                or state_cookie_value != query["state"]):
            raise IdentityError("oidc_state_invalid")
        state=query["state"]
        now=self.clock()
        with self.lock:
            entry = self.pending.pop(state,None)  # one use, even if validation fails
        if entry is None or entry[1] <= now:
            raise IdentityError("oidc_flow_expired")
        flow = entry[0]
        try:
            result=self.app.acquire_token_by_auth_code_flow(flow, query)
            if not isinstance(result,dict) or "error" in result:
                raise IdentityError("microsoft_token_exchange_failed")
            claims=self.validate(result.get("id_token"))
        except IdentityError:
            raise
        except Exception:
            raise IdentityError("microsoft_token_verification_failed") from None
        expected_nonce = hashlib.sha256(flow["nonce"].encode("ascii")).hexdigest()
        if (not isinstance(claims,dict) or
                claims.get("tid") != PERSONAL_TID or
                claims.get("iss") != ISSUER or
                claims.get("aud") != self.config["client_id"] or
                claims.get("nonce") != expected_nonce or
                not hmac.compare_digest(str(claims.get("sub","")),self.config["owner_sub"])):
            raise IdentityError("microsoft_owner_not_authorized")
        sid=secrets.token_urlsafe(32)
        with self.lock:
            self.sessions={s:item for s,item in self.sessions.items()
                           if item["expires"] > now and item["last"]+SESSION_IDLE > now}
            if len(self.sessions)>=MAX_SESSIONS:
                # Do not revoke legitimate current sessions to make space for attackers.
                raise IdentityError("too_many_sessions")
            self.sessions[sid]={"sub":claims["sub"],"expires":now+SESSION_TTL,
                                "last":now,"csrf":secrets.token_urlsafe(32)}
        return sid

    def check(self, sid):
        if not isinstance(sid,str) or not _TOKEN_ID.fullmatch(sid):
            return None
        now=self.clock()
        with self.lock:
            data=self.sessions.get(sid)
            if not data:
                return None
            if data["expires"]<=now or data["last"]+SESSION_IDLE<=now:
                del self.sessions[sid]
                return None
            data["last"]=now
            return {"sub":data["sub"],"csrf":data["csrf"]}

    def logout(self, sid):
        if not isinstance(sid,str):
            return
        with self.lock:
            self.sessions.pop(sid,None)


def from_systemd():
    if os.environ.get("DIRECTOR_STUDIO_MICROSOFT_REQUIRED") != "1":
        return None
    config=load_systemd_config()
    if config is None:
        return None
    try:
        return MicrosoftStudioIdentity(config)
    except Exception:
        return None  # Unconfigured/public callers will receive 503.
