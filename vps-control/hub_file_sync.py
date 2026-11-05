"""Receive authorized ChatGPT file-parameter images and send them to Studio.

No arbitrary HTTP URL imports: an OpenAI file reference must supply an
HTTPS temporary URL on an explicitly allowed OpenAI content host. Download is
bounded, redirects and proxies are disabled, and bytes only ever travel over
the existing signed Hub-to-Studio loopback channel. No GPU operations.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from hub_brain import secret_from_systemd

MEDIA_PATH="/api/v1/brain/visual"
MEDIA_URL="http://127.0.0.1:8900"+MEDIA_PATH
MAX_IMAGE=8*1024*1024
MAX_REPLY=4096
_ALLOWED_HOST_SUFFIXES=(".oaiusercontent.com",".openai.com")
_ID=re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,47}$")
_FILE_ID=re.compile(r"^file[_-][A-Za-z0-9_-]{5,180}$")


class SyncError(ValueError):
    def __init__(self, reason):
        self.reason=reason
        super().__init__(reason)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise SyncError("download_redirect_blocked")


OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())


def validate_file_ref(file):
    if not isinstance(file,dict) or set(file)-{"download_url","file_id","mime_type","file_name"}:
        raise SyncError("invalid_chatgpt_file_reference")
    identifier=file.get("file_id")
    if not isinstance(identifier,str) or not _FILE_ID.fullmatch(identifier):
        raise SyncError("invalid_chatgpt_file_id")
    value=file.get("download_url")
    if not isinstance(value,str) or len(value)>8192:
        raise SyncError("invalid_chatgpt_file_url")
    parts=urllib.parse.urlsplit(value)
    host=(parts.hostname or "").lower()
    if (parts.scheme!="https" or not host or parts.username or parts.password
            or parts.fragment or parts.port not in (None,443)
            or not any(host.endswith(s) for s in _ALLOWED_HOST_SUFFIXES)):
        raise SyncError("untrusted_chatgpt_file_host")
    # A signed URL can be temporary; never print it in an error or log.
    if not parts.path or parts.path=="/":
        raise SyncError("invalid_chatgpt_file_url")
    return value,identifier


def _check_public_resolve(host):
    # Defense-in-depth for an unexpectedly misconfigured trusted DNS record.
    try:
        addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError:
        raise SyncError("chatgpt_download_unavailable") from None
    for entry in addresses:
        ip=ipaddress.ip_address(entry[4][0].split("%")[0])
        if not ip.is_global:
            raise SyncError("untrusted_chatgpt_file_host")


def fetch_file(file, *, opener=OPENER):
    url,ref=validate_file_ref(file)
    _check_public_resolve(urllib.parse.urlsplit(url).hostname)
    request=urllib.request.Request(url,method="GET",
        headers={"Accept":"image/png, image/jpeg, image/webp"})
    try:
        with opener.open(request,timeout=20) as response:
            if response.geturl()!=url or response.status!=200:
                raise SyncError("chatgpt_download_unavailable")
            raw=response.read(MAX_IMAGE+1)
    except (OSError,urllib.error.URLError,urllib.error.HTTPError,TimeoutError):
        raise SyncError("chatgpt_download_unavailable") from None
    if len(raw)<32 or len(raw)>MAX_IMAGE:
        raise SyncError("chatgpt_image_size_unsupported")
    return raw,ref


def signed_request(secret,body,timestamp,nonce):
    value="\n".join(("POST",MEDIA_PATH,str(timestamp),nonce,
                      hashlib.sha256(body).hexdigest())).encode("ascii")
    return hmac.new(secret,value,hashlib.sha256).hexdigest()


def sync_chatgpt_visual(project_id,episode_id,kind,subject_id,file,*,opener=OPENER):
    try:
        if not all(isinstance(x,str) and _ID.fullmatch(x)
                   for x in (project_id,episode_id,subject_id)):
            raise SyncError("invalid_studio_scope")
        if kind not in ("character","scene","storyboard"):
            raise SyncError("invalid_visual_kind")
        raw,ref=fetch_file(file,opener=opener)
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            media="image/png"
        elif raw.startswith(b"\xff\xd8\xff"):
            media="image/jpeg"
        elif raw[:4]==b"RIFF" and raw[8:12]==b"WEBP":
            media="image/webp"
        else:
            raise SyncError("unsupported_image_format")
        supplied=file.get("mime_type")
        if supplied and supplied!=media:
            raise SyncError("image_mime_mismatch")
        name=file.get("file_name") or "chatgpt-generated-image"
        if (not isinstance(name,str) or not 1<=len(name)<=120 or
                any(c in name for c in ("/","\\","\x00")) or
                any(ord(c)<32 for c in name)):
            raise SyncError("invalid_filename")
        payload=json.dumps({"project_id":project_id,"episode_id":episode_id,
            "kind":kind,"subject_id":subject_id,"filename":name,
            "source_file_id":ref,
            "image_base64":base64.b64encode(raw).decode("ascii")},
            ensure_ascii=False,separators=(",",":")).encode("utf-8")
        secret=secret_from_systemd()
        now=str(int(time.time()))
        nonce=secrets.token_hex(16)
        req=urllib.request.Request(MEDIA_URL,method="POST",data=payload,
            headers={"Host":"127.0.0.1:8900",
              "Content-Type":"application/json",
              "X-Director-Brain-Time":now,
              "X-Director-Brain-Nonce":nonce,
              "X-Director-Brain-Signature":signed_request(secret,payload,now,nonce)})
        try:
            with OPENER.open(req,timeout=30) as response:
                if response.status not in (200,201) or response.geturl()!=MEDIA_URL:
                    raise SyncError("studio_visual_ingest_unavailable")
                reply=json.loads(response.read(MAX_REPLY+1))
        except urllib.error.HTTPError as exc:
            # Deliberately suppress server response, signed file URL and body.
            raise SyncError("studio_visual_ingest_unavailable") from None
        if not isinstance(reply,dict) or reply.get("ok") is not True:
            raise SyncError("studio_visual_ingest_unavailable")
        return {"ok":True,"project_id":project_id,"episode_id":episode_id,
                "visual_id":reply.get("visual_id"),"version":reply.get("version"),
                "unchanged":reply.get("unchanged",False),
                "gpu_action":False}
    except SyncError as exc:
        return {"ok":False,"reason":exc.reason}
    except (ValueError,TypeError,OSError,urllib.error.URLError):
        return {"ok":False,"reason":"studio_visual_sync_unavailable"}
