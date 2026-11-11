"""Signed, version-bound owner-VPS Windows Setup downloads with HTTP Range resume.

Called only after secure_update verifies the Ed25519 signed channel.
No redirect, proxy inheritance, alternate domain, unsigned fallback or installer
execution. Interrupted HTTPS downloads keep bounded .part bytes for retry;
only a complete SHA256/size match is atomically promoted to Setup.exe.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

MAX_SETUP = 900_000_000
_VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")


class DownloadError(Exception):
    pass


class DownloadCancelled(DownloadError):
    pass


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest


def _validate(manifest):
    version = getattr(manifest, "version", None)
    url = getattr(manifest, "url", None)
    size = getattr(manifest, "size", None)
    sha = getattr(manifest, "sha256", None)
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise DownloadError("签名更新版本无效")
    filename = f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
    expected = "https://sync.borealos.cn/downloads/" + filename
    if url != expected or urlsplit(url).geturl() != expected:
        raise DownloadError("签名安装包的 HTTPS 地址不受信任")
    if (type(size) is not int or not 1_000_000 <= size <= MAX_SETUP or
            not isinstance(sha, str) or not _SHA256.fullmatch(sha)):
        raise DownloadError("签名安装包大小或 SHA256 不合法")
    return filename, size, sha


def download_signed_vps(manifest, target_dir, progress=None, cancel=None, verify_cached=None):
    """Resume on HTTP 206; on HTTP 200 restart safely from zero.

    On transient network errors, keep partial bytes in the user's update
    directory. A subsequent call rehashes them; no partial bytes can execute.
    """
    filename, expected_size, expected_sha = _validate(manifest)
    root = Path(target_dir)
    if root.is_symlink():
        raise DownloadError("更新下载目录不可信")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError("无法创建更新目录") from exc
    final = root / filename
    partial = root / (filename + ".part")
    if final.is_symlink() or partial.is_symlink():
        raise DownloadError("更新包文件路径不可信")

    if final.is_file():
        if callable(verify_cached) and verify_cached(final, manifest):
            if progress is not None:
                progress(expected_size, expected_size)
            return final
        try:
            final.unlink()
        except OSError as exc:
            raise DownloadError("无法清理旧版不完整安装包") from exc

    try:
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > expected_size or offset < 0:
            partial.unlink()
            offset = 0
        if offset:
            digest = _digest_file(partial)
            if offset == expected_size:
                if hmac.compare_digest(digest.hexdigest(), expected_sha):
                    os.replace(partial, final)
                    if progress is not None:
                        progress(expected_size, expected_size)
                    return final
                partial.unlink()
                offset = 0
                digest = hashlib.sha256()
        else:
            digest = hashlib.sha256()
    except OSError as exc:
        raise DownloadError("无法读取断点下载数据") from exc

    if cancel is not None and cancel.is_set():
        partial.unlink(missing_ok=True)
        raise DownloadCancelled("更新下载已取消")

    session = requests.Session()
    session.trust_env = False
    retain_partial = False
    try:
        headers = {
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
            "User-Agent": "GlacierBrowser/signed-resume-update",
        }
        if offset:
            headers["Range"] = f"bytes={offset}-"
        with session.get(
            manifest.url, headers=headers, timeout=(12, 60),
            allow_redirects=False, stream=True,
        ) as response:
            if response.status_code == 206 and offset:
                match = _RANGE.fullmatch(response.headers.get("Content-Range", "").strip())
                if not match or tuple(map(int, match.groups())) != (
                        offset, expected_size - 1, expected_size):
                    raise DownloadError("断点响应范围与签名安装包不符")
                start = offset
                mode = "ab"
            elif response.status_code == 200:
                # The server may ignore Range; reset bytes AND hasher.
                start = 0
                mode = "wb"
                digest = hashlib.sha256()
            else:
                raise DownloadError(
                    "VPS 断点下载 HTTP " + str(response.status_code))
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding not in ("", "identity"):
                raise DownloadError("拒绝未经授权的压缩安装包响应")
            advertised = response.headers.get("Content-Length")
            if advertised is not None:
                try:
                    length = int(advertised)
                except (TypeError, ValueError) as exc:
                    raise DownloadError("下载响应大小无效") from exc
                if length != expected_size - start:
                    raise DownloadError("下载响应长度与签名清单不符")
            total = start
            if progress is not None and start:
                progress(start, expected_size)
            with partial.open(mode) as output:
                for chunk in response.iter_content(1024 * 1024):
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled("更新下载已取消")
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > expected_size:
                        raise DownloadError("下载大小超过签名清单")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress is not None:
                        progress(total, expected_size)
                output.flush()
                os.fsync(output.fileno())
        if total != expected_size or not hmac.compare_digest(
                digest.hexdigest(), expected_sha):
            raise DownloadError("安装包大小或 SHA256 不一致")
        os.replace(partial, final)
        return final
    except requests.RequestException as exc:
        # This is an availability failure, not an integrity failure.
        # A retry rehashes local partial bytes and validates full content.
        retain_partial = True
        raise DownloadError("VPS 网络中断；已保留下载进度，可重新下载") from exc
    except OSError as exc:
        raise DownloadError("安装包保存失败") from exc
    finally:
        session.close()
        if not retain_partial:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
