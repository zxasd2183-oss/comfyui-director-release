#!/usr/bin/env python3
"""Fail-closed integration patch for the historical compressed Windows Qt UI.

Release builds first decode update_ui.py.xz.b64 and replace its imported
update_core with secure_update. Apply these reviewed changes ONLY after that
replacement; stop the build if the upstream UI layout changes.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _once(source, before, after):
    if source.count(before) != 1:
        raise ValueError("Windows updater changed; refusing unsafe patch: " + repr(before[:80]))
    return source.replace(before, after)


def patch(source):
    source = _once(source, "from secure_update import (",
                   "from glacier_signed_install27 import launch_verified_setup\n"
                   "from secure_update import (")
    source = _once(
        source,
        "        if not self.browser.proc or self.browser.proc.poll() is not None:\n"
        "            self._update_status('代理核心未运行，无法通过 VLESS 检查更新（不会直连）')\n"
        "            return\n",
        "        # The independently signed VPS feed uses direct HTTPS.\n"
        "        # Browser page networking still remains fail-closed through VLESS.\n",
    )
    source = _once(source, "self._update_status('正在通过 VLESS 检查软件更新…')",
                   "self._update_status('正在从自有 VPS HTTPS 检查软件更新…')")
    source = _once(source, "self._update_status('正在通过 VLESS 下载并校验安装包…')",
                   "self._update_status('正在从自有 VPS HTTPS 下载并校验安装包…')")
    source = _once(source, "self.auto_download = False",
                   "self.auto_download = True")
    source = _once(source, "obj.get('auto_download', False)",
                   "obj.get('auto_download', True)")
    source = _once(
        source,
        "            subprocess.Popen([str(self.ready_path), '/SILENT', '/NORESTART',\n"
        "                              '/CLOSEAPPLICATIONS'], cwd=str(self.output_dir))",
        "            launch_verified_setup(\n"
        "                self.ready_path, self.new_manifest, self.output_dir, verify_file\n"
        "            )",
    )
    source = _once(
        source,
        "已验证 HTTPS 更新源及 SHA256，但此测试版没有 Windows 代码签名。",
        "已验证 Ed25519 更新清单及 SHA256；安装包尚无 Windows Authenticode 签名。",
    )
    if "subprocess.Popen([str(self.ready_path)" in source:
        raise ValueError("Direct unverified installer execution remains in UI")
    compile(source, "<decoded signed Windows update UI>", "exec")
    return source


def main(path):
    target = Path(path)
    result = patch(target.read_text(encoding="utf-8"))
    target.write_text(result, encoding="utf-8")
    print("Windows signed update UI integrated: direct VPS HTTPS, auto-download, safe Setup restart")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: glacier_patch_windows_update_ui.py <decoded-update_ui.py>")
    main(sys.argv[1])
