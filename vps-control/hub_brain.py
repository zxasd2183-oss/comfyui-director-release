"""Only Director Hub can sign requests to the private Studio brain endpoint.

Does not use Microsoft browser credentials, provider tokens or external URLs.
HMAC credential is provided as a separate systemd LoadCredential and never
logged, exposed in MCP output or passed in HTTP body.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

STUDIO_URL="http://127.0.0.1:8900/api/v1/brain"
PATH="/api/v1/brain"
MAX_RESPONSE=1048576
MAX_REQUEST=32768
HEX64=re.compile(r"^[0-9a-f]{64}$")


class BrainHubError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise BrainHubError("brain_backend_redirect_blocked")


def secret_from_systemd(environ=None):
    env=environ if environ is not None else os.environ
    directory=env.get("CREDENTIALS_DIRECTORY")
    if not directory:
        raise BrainHubError("brain_link_not_configured")
    f=Path(directory)/"brain_link"
    if f.is_symlink() or not f.is_file() or f.stat().st_size>128:
        raise BrainHubError("brain_link_not_configured")
    try:
        value=f.read_text(encoding="ascii").strip()
    except (OSError,UnicodeError):
        raise BrainHubError("brain_link_not_configured") from None
    if not HEX64.fullmatch(value):
        raise BrainHubError("brain_link_not_configured")
    return bytes.fromhex(value)


def sign(secret,body,timestamp,nonce):
    digest=hashlib.sha256(body).hexdigest()
    text="\n".join(("POST",PATH,timestamp,nonce,digest)).encode("ascii")
    return hmac.new(secret,text,hashlib.sha256).hexdigest()


def call_studio(tool,params,*,environ=None,opener=None,clock=time.time,rand=None):
    try:
        secret=secret_from_systemd(environ)
        payload=json.dumps({"tool":tool,"arguments":params},ensure_ascii=False,
                           separators=(",",":")).encode("utf-8")
        if len(payload)>MAX_REQUEST:
            raise BrainHubError("brain_request_too_large")
        now=str(int(clock()))
        nonce=rand() if rand is not None else secrets.token_hex(16)
        if not re.fullmatch(r"[0-9a-f]{32}",nonce):
            raise BrainHubError("brain_nonce_invalid")
        req=urllib.request.Request(
            STUDIO_URL,data=payload,method="POST",
            headers={
                "Host":"127.0.0.1:8900",
                "Content-Type":"application/json",
                "X-Director-Brain-Time":now,
                "X-Director-Brain-Nonce":nonce,
                "X-Director-Brain-Signature":sign(secret,payload,now,nonce),
            }
        )
        backend=opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),_NoRedirect())
        try:
            with backend.open(req,timeout=8) as response:
                if response.geturl()!=STUDIO_URL:
                    raise BrainHubError("brain_backend_redirect_blocked")
                raw=response.read(MAX_RESPONSE+1)
                if len(raw)>MAX_RESPONSE:
                    raise BrainHubError("brain_reply_too_large")
                if response.status!=200:
                    raise BrainHubError("brain_backend_unavailable")
                data=json.loads(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (400,403,404,409,413,415,503):
                raw=exc.read(MAX_RESPONSE+1)
                if len(raw)>MAX_RESPONSE:
                    raise BrainHubError("brain_reply_too_large")
                item=json.loads(raw)
                if isinstance(item,dict) and item.get("ok") is False:
                    reason=item.get("reason")
                    allowed={
                        "invalid_identifier","invalid_text","invalid_shot_identifier",
                        "invalid_shot_timing","invalid_episode_order","invalid_revision",
                        "invalid_outline","invalid_brain_arguments","brain_tool_not_allowed",
                        "duplicate_or_invalid_parent","stale_outline_revision",
                        "episode_not_found","audit_integrity_failure",
                        "project_limit_reached","episode_limit_reached","shot_limit_reached",
                        "brain_link_not_configured","studio_storage_unavailable",
                        "studio_brain_unavailable","brain_link_denied","json_only",
                        "invalid_brain_request",
                        "project_not_found","character_not_found",
                        "invalid_character_project","invalid_character_id",
                        "invalid_character_name","invalid_character_role",
                        "invalid_character_notes","invalid_character_fields",
                        "invalid_character_revision","stale_character_revision",
                        "character_already_exists","character_catalog_full",
                        "character_visual_not_found","invalid_reference_type",
                        "invalid_character_visual_id","character_link_limit",
                        "character_visual_not_linked",
                    }
                    if reason in allowed:
                        return {"ok":False,"reason":reason}
            raise BrainHubError("brain_backend_unavailable") from None
        if not isinstance(data,dict) or data.get("ok") is not True:
            raise BrainHubError("brain_result_invalid")
        return data
    except BrainHubError as exc:
        return {"ok":False,"reason":str(exc)}
    except (OSError,ValueError,TypeError,urllib.error.URLError):
        return {"ok":False,"reason":"brain_backend_unavailable"}
