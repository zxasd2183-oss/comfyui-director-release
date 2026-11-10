"""Glacier Browser v0.11: independently authorized, unsigned-code update channel.

Installers lack Windows Authenticode. This module authenticates the signed update
metadata using a pinned Ed25519 public key before trusting the URL or SHA-256.
Private key is intentionally NEVER included in repo, CI or installed packages.
"""
from __future__ import annotations
import base64
import binascii
import json
from urllib.parse import urlsplit

import requests

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from update_core import (
    UpdateError, FEED_URL, MAX_MANIFEST, CHANNEL, Manifest, newer_than,
    fetch_via_socks, verify_file, download_installer, parsed_version,
    parse_manifest as _parse_insecure_manifest,
)

CURRENT_VERSION = '0.20.11'
# Signed update metadata is delivered directly by our own HTTPS VPS.
# The Ed25519 pinned key (rotated by the trusted build job) still verifies it.
VPS_FEED_URL = 'https://sync.borealos.cn/downloads/windows-x64.json'
FEED_URL = VPS_FEED_URL
KEY_ID = 'cf9452226375ff7d'
PUBLIC_KEY = bytes.fromhex('7c375bfd04b4941a662a9a66e9c3f980653cb01b9e5df286ec651eca84e26dab')
ALLOWED_KEYS = {'channel', 'version', 'url', 'sha256', 'size', 'notes', 'key_id', 'signature'}

def _unique_object(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise UpdateError('更新清单有重复 JSON 字段，已拒绝')
        obj[k] = v
    return obj

def canonical(payload):
    try:
        return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise UpdateError('更新清单签名数据格式错误') from exc

def parse_manifest(document):
    if not isinstance(document, dict) or set(document) != ALLOWED_KEYS:
        raise UpdateError('更新清单缺少签名或字段异常')
    if document.get('key_id') != KEY_ID:
        raise UpdateError('更新清单使用了未知签名密钥')
    b64sig = document.get('signature')
    if not isinstance(b64sig, str):
        raise UpdateError('更新清单缺少签名')
    try:
        signature = base64.b64decode(b64sig, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise UpdateError('数字签名编码无效') from exc
    if len(signature) != 64:
        raise UpdateError('更新清单签名长度无效')
    payload = {key: value for key, value in document.items() if key != 'signature'}
    try:
        Ed25519PublicKey.from_public_bytes(PUBLIC_KEY).verify(signature, canonical(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise UpdateError('更新清单签名无效，已阻止安装') from exc
    manifest = _parse_insecure_manifest(payload)
    v = manifest.version
    p = urlsplit(manifest.url)
    expected_path = (f'/zxasd2183-oss/comfyui-director-release/releases/download/'
                     f'glacier-v{v}/GlacierBrowser-v{v}-Windows-Setup-x64.exe')
    vps_path = f'/downloads/GlacierBrowser-v{v}-Windows-Setup-x64.exe'
    permitted = (
        (p.hostname == 'github.com' and p.path == expected_path) or
        (p.hostname == 'sync.borealos.cn' and p.path == vps_path)
    )
    if (not permitted or p.query or p.fragment or p.username or p.password
            or p.port is not None or p.scheme != 'https'):
        raise UpdateError('签名版本和可信下载地址不匹配')
    return manifest

def load_remote_manifest(port):
    """Fetch only the owner's HTTPS signed channel without VLESS dependency.

    No system proxy, no arbitrary URL, no redirects and no unsigned fallback.
    A failure never triggers direct execution or download of any installer.
    The existing caller argument is retained for UI compatibility.
    """
    raw = bytearray()
    session = requests.Session()
    session.trust_env = False
    try:
        with session.get(
            VPS_FEED_URL,
            headers={'Accept':'application/json', 'User-Agent':'GlacierBrowser/signed-update'},
            timeout=(10, 20),
            allow_redirects=False, stream=True,
        ) as response:
            if response.status_code != 200:
                raise UpdateError('VPS 正式更新通道返回 HTTP '+str(response.status_code))
            advertised = response.headers.get('Content-Length')
            if advertised is not None:
                try:
                    length = int(advertised)
                except (ValueError, TypeError) as exc:
                    raise UpdateError('VPS 更新清单长度无效') from exc
                if length > MAX_MANIFEST:
                    raise UpdateError('VPS 更新清单超出长度限制')
            for chunk in response.iter_content(4096):
                raw.extend(chunk)
                if len(raw) > MAX_MANIFEST:
                    raise UpdateError('VPS 更新清单超出长度限制')
    except requests.RequestException as exc:
        raise UpdateError('无法通过 HTTPS 访问 VPS 正式更新通道') from exc
    finally:
        session.close()
    try:
        doc = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError('更新清单 JSON 无效') from exc
    return parse_manifest(doc)
