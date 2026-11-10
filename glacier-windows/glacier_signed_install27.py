"""User-confirmed Glacier Windows signed Setup launch, independent of UI/Qt.

Never execute cached Setup based only on download completion: verify its
version-bound path and exact SHA-256 against the signed update manifest again.
The installer has no Windows Authenticode signature; the UI must confirm first.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


class SetupLaunchError(OSError):
    """Refuse an untrusted or modified Windows installer."""


def launch_verified_setup(installer, manifest, output_dir, verify_file):
    """Validate a signed VPS installer again and start Inno Setup after consent.

    Caller closes its browser only if this function returns successfully.
    The next Inno Setup [Run] section relaunches the browser on success.
    """
    version = getattr(manifest, "version", None)
    if not isinstance(version, str) or not re.fullmatch(
            r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise SetupLaunchError("签名更新版本无效")
    filename = f"GlacierBrowser-v{version}-Windows-Setup-x64.exe"
    expected_url = "https://sync.borealos.cn/downloads/" + filename
    if getattr(manifest, "url", None) != expected_url:
        raise SetupLaunchError("签名清单中的 VPS 安装包地址不可信")
    root, target = Path(output_dir), Path(installer)
    if (root.is_symlink() or not root.is_dir() or target.is_symlink()
            or not target.is_file() or target.name != filename):
        raise SetupLaunchError("安装包不存在或文件路径无效")
    try:
        root_real = root.resolve(strict=True)
        target_real = target.resolve(strict=True)
    except OSError as exc:
        raise SetupLaunchError("无法解析安装包路径") from exc
    if target_real.parent != root_real:
        raise SetupLaunchError("安装包不位于专用更新目录")
    if not callable(verify_file):
        raise SetupLaunchError("更新包 SHA256 验证不可用")
    try:
        valid = verify_file(target, manifest)
    except (OSError, ValueError) as exc:
        raise SetupLaunchError("安装包重新校验失败") from exc
    if not valid:
        raise SetupLaunchError("安装包大小或 SHA256 与签名清单不一致")
    return subprocess.Popen(
        [str(target_real), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"],
        cwd=str(root_real), shell=False, close_fds=True,
    )
