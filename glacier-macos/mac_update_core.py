"""Glacier macOS ARM64: signed metadata and first-party VPS HTTPS-only updater.

This is NOT Apple Developer ID notarization. Installer origin is authenticated by
an embedded Ed25519 key, checksum/size and constrained GitHub release URL.
"""
from __future__ import annotations
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CURRENT_VERSION = "0.20.24"
CHANNEL = "macos-arm64"
KEY_ID = "cf9452226375ff7d"
PUBLIC_KEY = bytes.fromhex("7c375bfd04b4941a662a9a66e9c3f980653cb01b9e5df286ec651eca84e26dab")
FEED_URL = "https://sync.borealos.cn/downloads/macos-arm64.json"
MAX_MANIFEST = 65536
MAX_DMG = 1_073_741_824
FIELDS = frozenset(("channel","version","url","sha256","size","notes","key_id","signature"))
TRUSTED_REDIRECT_HOSTS = frozenset(("github.com", "sync.borealos.cn", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "github-releases.githubusercontent.com"))
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class UpdateError(Exception):
    pass


def version_parts(v):
    if not isinstance(v,str) or not VERSION_RE.fullmatch(v):
        raise UpdateError("版本号不合法")
    return tuple(int(x) for x in v.split("."))


def newer_than(local, remote):
    return version_parts(remote) > version_parts(local)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",",":"), allow_nan=False).encode("utf-8")


def unique_json_pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d:
            raise UpdateError("更新清单存在重复字段")
        d[k]=v
    return d


def verify_manifest(doc):
    if not isinstance(doc,dict) or set(doc)!=FIELDS:
        raise UpdateError("更新清单字段不完整或存在未知字段")
    if doc["channel"]!=CHANNEL or doc["key_id"]!=KEY_ID:
        raise UpdateError("更新通道或签名密钥不受信任")
    signature=doc["signature"]
    if not isinstance(signature,str):
        raise UpdateError("缺少更新清单数字签名")
    try:
        decoded=base64.b64decode(signature,validate=True)
    except (ValueError,binascii.Error) as exc:
        raise UpdateError("更新清单数字签名编码错误") from exc
    if len(decoded)!=64:
        raise UpdateError("更新清单数字签名长度不正确")
    payload={k:v for k,v in doc.items() if k!="signature"}
    try:
        Ed25519PublicKey.from_public_bytes(PUBLIC_KEY).verify(decoded,canonical(payload))
    except (InvalidSignature,ValueError,TypeError) as exc:
        raise UpdateError("更新清单签名验证失败，已拒绝更新") from exc
    ver=doc["version"]
    version_parts(ver)
    url=doc["url"]
    if not isinstance(url,str):
        raise UpdateError("下载地址无效")
    p=urlsplit(url)
    expected=(f"/zxasd2183-oss/comfyui-director-release/releases/download/"
              f"glacier-macos-v{ver}/GlacierBrowser-v{ver}-macOS-AppleSilicon.dmg")
    vps_expected=f"/downloads/GlacierBrowser-v{ver}-macOS-AppleSilicon.dmg"
    permitted=((p.hostname=="github.com" and p.path==expected) or
               (p.hostname=="sync.borealos.cn" and p.path==vps_expected))
    if (p.scheme!="https" or not permitted or p.username or
            p.password or p.port is not None or p.query or p.fragment):
        raise UpdateError("下载地址不符合 Mac 可信发布路径")
    digest=doc["sha256"]
    if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise UpdateError("安装包 SHA256 无效")
    if type(doc["size"]) is not int or not 1_000_000<=doc["size"]<=MAX_DMG:
        raise UpdateError("安装包大小异常")
    if not isinstance(doc["notes"],str) or len(doc["notes"])>5000:
        raise UpdateError("更新说明格式错误")
    return doc


def signed_update_session(port):
    """Fail closed: every update request, including DNS, uses local VLESS SOCKS5."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise UpdateError("VLESS 代理未就绪，已拒绝直连更新")
    sess=requests.Session()
    sess.trust_env=False
    proxy=f"socks5h://127.0.0.1:{port}"
    sess.proxies={"http":proxy,"https":proxy}
    return sess


def owner_vps_session():
    """Use direct TLS to our own HTTPS VPS without system or VLESS proxies."""
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"http": None, "https": None}
    return sess


def _request(session,url,allowed_hosts,stream=True):
    for _ in range(8):
        parsed=urlsplit(url)
        if (parsed.scheme!="https" or parsed.hostname not in allowed_hosts or parsed.username
                or parsed.password or parsed.port or parsed.fragment):
            raise UpdateError("发现不受信任的更新下载重定向，已阻止")
        try:
            response=session.get(url,timeout=(12,60),allow_redirects=False,stream=stream)
        except requests.RequestException as exc:
            raise UpdateError("VLESS 更新请求失败：" + str(exc)) from exc
        if response.status_code in (301,302,303,307,308):
            dest=response.headers.get("Location","")
            response.close()
            if not dest:
                raise UpdateError("更新源重定向缺少目标地址")
            url=urljoin(url,dest)
            continue
        if response.status_code!=200:
            response.close()
            raise UpdateError(f"更新服务器返回 HTTP {response.status_code}")
        return response
    raise UpdateError("更新下载重定向次数过多")


def get_manifest(port):
    session=owner_vps_session()
    try:
        # Signed metadata is fetched from our own HTTPS VPS.
        response=_request(session,FEED_URL,{"sync.borealos.cn"})
        with response:
            buf=bytearray()
            for chunk in response.iter_content(8192):
                buf.extend(chunk)
                if len(buf)>MAX_MANIFEST:
                    raise UpdateError("更新清单大小异常")
        try:
            doc=json.loads(buf.decode("utf-8-sig"),object_pairs_hook=unique_json_pairs)
        except (UnicodeError,ValueError) as exc:
            raise UpdateError("更新清单不是有效 JSON") from exc
        return verify_manifest(doc)
    finally:
        session.close()


def download_dmg(manifest, port, directory, progress=lambda n:None):
    verify_manifest(manifest)
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    final=directory/("GlacierBrowser-v"+manifest["version"]+"-macOS-AppleSilicon.dmg")
    partial=final.with_suffix(".dmg.partial")
    is_vps = urlsplit(manifest["url"]).hostname == "sync.borealos.cn"
    session=owner_vps_session() if is_vps else signed_update_session(port)
    expected=manifest["size"]
    total=0
    digest=hashlib.sha256()
    try:
        allowed = {"sync.borealos.cn"} if is_vps else TRUSTED_REDIRECT_HOSTS - {"sync.borealos.cn"}
        with _request(session,manifest["url"],allowed) as response:
            advertised=response.headers.get("Content-Length")
            if advertised and int(advertised)!=expected:
                raise UpdateError("远端文件长度与签名清单不一致")
            with partial.open("wb") as handle:
                for chunk in response.iter_content(1024*1024):
                    if not chunk:
                        continue
                    total+=len(chunk)
                    if total>expected:
                        raise UpdateError("下载文件大于签名清单指定大小")
                    digest.update(chunk)
                    handle.write(chunk)
                    progress(min(100,int(total*100/expected)))
                handle.flush()
                os.fsync(handle.fileno())
        if total!=expected or not hmac.compare_digest(digest.hexdigest(),manifest["sha256"]):
            raise UpdateError("Mac 更新文件大小或 SHA256 校验失败")
        os.replace(partial,final)
        return final
    except (OSError,requests.RequestException,ValueError) as exc:
        raise UpdateError("更新下载或存储失败："+str(exc)) from exc
    finally:
        session.close()
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass


def verify_local_dmg(manifest, filename):
    """Reject cached DMGs changed since download, before Finder opens them."""
    verify_manifest(manifest)
    path = Path(filename)
    expected_name = "GlacierBrowser-v" + manifest["version"] + "-macOS-AppleSilicon.dmg"
    if path.name != expected_name or path.is_symlink() or not path.is_file():
        raise UpdateError("本地更新包路径无效")
    digest = hashlib.sha256()
    try:
        if path.stat().st_size != manifest["size"]:
            raise UpdateError("本地更新包大小与签名清单不一致")
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise UpdateError("无法读取本地更新包") from exc
    if not hmac.compare_digest(digest.hexdigest(), manifest["sha256"]):
        raise UpdateError("本地更新包 SHA256 验证失败")
    return path
