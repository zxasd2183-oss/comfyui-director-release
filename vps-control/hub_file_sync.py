"""Transfer an authorized ChatGPT image into Director Studio via signed loopback.

FileParams supplies an ephemeral URL and opaque file ID. The current operation
fetches only bounded image bytes; signed URLs are never persisted, logged, or
returned. This module cannot call GPU or power APIs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from hub_brain import secret_from_systemd

MEDIA_PATH = "/api/v1/brain/visual"
MEDIA_URL = "http://127.0.0.1:8900" + MEDIA_PATH
MAX_IMAGE = 8 * 1024 * 1024
MAX_REPLY = 4096
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,47}$")

# Exact OpenAI hostnames or suffixes plus the constrained, observed regional
# Azure account family (max storage account name is 24 chars). Do NOT allow
# arbitrary *.blob.core.windows.net or arbitrary HTTPS hosts.
_ALLOWED_HOSTS = frozenset({
    "chatgpt.com", "openai.com", "oaiusercontent.com", "openaiusercontent.com"
})
_ALLOWED_HOST_SUFFIXES = (
    ".chatgpt.com", ".openai.com", ".oaiusercontent.com",
    ".openaiusercontent.com"
)
_OPENAI_AZURE_BLOB_HOST = re.compile(
    r"^oaisdmntpr[a-z0-9]{1,14}\.blob\.core\.windows\.net$"
)


class SyncError(ValueError):
    def __init__(self, reason, *, hostname=None, http_status=None):
        self.reason = reason
        self.hostname = hostname if (
            isinstance(hostname, str)
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", hostname)
        ) else None
        self.http_status = http_status if (
            type(http_status) is int and 100 <= http_status <= 599
        ) else None
        super().__init__(reason)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SyncError("studio_redirect_blocked")


# This opener is for the fixed 127.0.0.1:8900 Studio endpoint ONLY.
_STUDIO_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirect()
)


def _trusted_host(host):
    return (host in _ALLOWED_HOSTS
            or any(host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES)
            or _OPENAI_AZURE_BLOB_HOST.fullmatch(host) is not None)


def validate_file_ref(file):
    if not isinstance(file, dict) or set(file) - {
        "download_url", "file_id", "mime_type", "file_name"
    }:
        raise SyncError("invalid_chatgpt_file_reference")
    identifier = file.get("file_id")
    if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 2048
            or any(ord(ch) < 32 for ch in identifier)):
        raise SyncError("invalid_chatgpt_file_id")
    source_token = "file_" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    value = file.get("download_url")
    if (not isinstance(value, str) or len(value) > 8192
            or any(ord(ch) < 32 for ch in value)):
        raise SyncError("invalid_chatgpt_file_url")
    try:
        parts = urllib.parse.urlsplit(value)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise SyncError("invalid_chatgpt_file_url") from None
    if (parts.scheme != "https" or not host or parts.username or parts.password
            or parts.fragment or port not in (None, 443)
            or not _trusted_host(host)):
        raise SyncError("untrusted_chatgpt_file_host", hostname=host)
    if not parts.path or not parts.path.startswith("/") or parts.path == "/":
        raise SyncError("invalid_chatgpt_file_url")
    return value, source_token


def _check_public_resolve(host):
    """Check every returned address; return pinned public IP candidates."""
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise SyncError("chatgpt_download_dns_unavailable") from None
    ips = []
    for answer in answers:
        address = answer[4][0].split("%")[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise SyncError("untrusted_chatgpt_file_host") from None
        if not ip.is_global:
            raise SyncError("untrusted_chatgpt_file_host")
        if str(ip) not in ips:
            ips.append(str(ip))
    if not ips:
        raise SyncError("chatgpt_download_dns_unavailable")
    return tuple(ips[:8])


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the validated IP while retaining original-host TLS SNI."""

    def __init__(self, hostname, pinned_ip):
        super().__init__(hostname, 443, timeout=20, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _fetch_pinned(parts, ips):
    host = parts.hostname.lower()
    request_path = parts.path + (("?" + parts.query) if parts.query else "")
    last_reason = "chatgpt_download_network_error"
    for ip in ips[:4]:
        connection = _PinnedHTTPSConnection(host, ip)
        try:
            connection.request("GET", request_path, headers={
                "Host": host, "Accept": "image/png, image/jpeg, image/webp",
                "Accept-Encoding": "identity"
            })
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise SyncError("chatgpt_download_redirect_blocked")
            if response.status != 200:
                raise SyncError("chatgpt_download_http_error",
                                http_status=response.status)
            size_header = response.getheader("Content-Length")
            if size_header and size_header.isdecimal() and int(size_header) > MAX_IMAGE:
                raise SyncError("chatgpt_image_size_unsupported")
            return response.read(MAX_IMAGE + 1)
        except ssl.SSLError:
            last_reason = "chatgpt_download_tls_error"
        except (OSError, TimeoutError, http.client.HTTPException):
            last_reason = "chatgpt_download_network_error"
        finally:
            connection.close()
    raise SyncError(last_reason)


def fetch_file(file, *, opener=None):
    url, source_id = validate_file_ref(file)
    parts = urllib.parse.urlsplit(url)
    ips = _check_public_resolve(parts.hostname)
    if opener is None:
        raw = _fetch_pinned(parts, ips)
    else:
        # Only injected by offline tests; production always uses pinned TLS.
        request = urllib.request.Request(
            url, method="GET", headers={"Accept": "image/png, image/jpeg, image/webp"}
        )
        try:
            with opener.open(request, timeout=20) as response:
                if response.geturl() != url or response.status != 200:
                    raise SyncError("chatgpt_download_redirect_blocked")
                raw = response.read(MAX_IMAGE + 1)
        except urllib.error.HTTPError as exc:
            raise SyncError("chatgpt_download_http_error",
                            http_status=exc.code) from None
        except (OSError, urllib.error.URLError, TimeoutError):
            raise SyncError("chatgpt_download_network_error") from None
    if len(raw) < 32 or len(raw) > MAX_IMAGE:
        raise SyncError("chatgpt_image_size_unsupported")
    return raw, source_id


def signed_request(secret, body, timestamp, nonce):
    value = "\n".join((
        "POST", MEDIA_PATH, str(timestamp), nonce, hashlib.sha256(body).hexdigest()
    )).encode("ascii")
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


def _safe_filename(value):
    if value is None or value == "":
        return "chatgpt-generated-image"
    if not isinstance(value, str) or "\x00" in value:
        raise SyncError("invalid_filename")
    # The host may return an opaque library path instead of a basename.
    # This is metadata only and must never define a filesystem destination.
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or len(name) > 120 or any(ord(c) < 32 for c in name):
        raise SyncError("invalid_filename")
    return name


def sync_chatgpt_visual(project_id, episode_id, kind, subject_id, file, *,
                        opener=None):
    try:
        if not all(isinstance(x, str) and _ID.fullmatch(x)
                   for x in (project_id, episode_id, subject_id)):
            raise SyncError("invalid_studio_scope")
        if kind not in ("character", "scene", "storyboard"):
            raise SyncError("invalid_visual_kind")
        raw, source_id = fetch_file(file, opener=opener)
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            media = "image/png"
        elif raw.startswith(b"\xff\xd8\xff"):
            media = "image/jpeg"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            media = "image/webp"
        else:
            raise SyncError("unsupported_image_format")
        supplied = file.get("mime_type")
        if supplied and supplied not in (media, "application/octet-stream"):
            raise SyncError("image_mime_mismatch")
        filename = _safe_filename(file.get("file_name"))
        payload = json.dumps({
            "project_id": project_id, "episode_id": episode_id,
            "kind": kind, "subject_id": subject_id,
            "filename": filename, "source_file_id": source_id,
            "image_base64": base64.b64encode(raw).decode("ascii")
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        secret = secret_from_systemd()
        stamp, nonce = str(int(time.time())), secrets.token_hex(16)
        req = urllib.request.Request(
            MEDIA_URL, method="POST", data=payload,
            headers={
                "Host": "127.0.0.1:8900", "Content-Type": "application/json",
                "X-Director-Brain-Time": stamp, "X-Director-Brain-Nonce": nonce,
                "X-Director-Brain-Signature": signed_request(
                    secret, payload, stamp, nonce
                )
            }
        )
        try:
            with _STUDIO_OPENER.open(req, timeout=30) as response:
                if response.status not in (200, 201) or response.geturl() != MEDIA_URL:
                    raise SyncError("studio_visual_ingest_unavailable")
                result = json.loads(response.read(MAX_REPLY + 1))
        except urllib.error.HTTPError as exc:
            raise SyncError("studio_visual_ingest_http_error",
                            http_status=exc.code) from None
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise SyncError("studio_visual_ingest_unavailable")
        return {"ok": True, "project_id": project_id, "episode_id": episode_id,
                "visual_id": result.get("visual_id"), "version": result.get("version"),
                "unchanged": result.get("unchanged", False), "gpu_action": False}
    except SyncError as exc:
        result = {"ok": False, "reason": exc.reason}
        if exc.reason == "untrusted_chatgpt_file_host" and exc.hostname:
            result["download_host"] = exc.hostname
        if exc.http_status is not None:
            result["http_status"] = exc.http_status
        return result
    except (ValueError, TypeError, OSError, urllib.error.URLError,
            http.client.HTTPException):
        return {"ok": False, "reason": "studio_visual_sync_unavailable"}
