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
    # Windows-native 2026 UI refresh: familiar Chrome-like light settings.
    source = _once(
        source, "        self.resize(530, 425)",
        "        self.resize(570, 445)\n"
        "        self.setObjectName('GlacierUpdateDialog28')\n"
        "        self.setStyleSheet('''\n"
        "QDialog#GlacierUpdateDialog28 { background:#f7fafc; color:#263d4f; }\n"
        "QDialog#GlacierUpdateDialog28 QLabel { background:transparent; color:#405e72; }\n"
        "QDialog#GlacierUpdateDialog28 QPushButton { background:#fff; color:#2c556f;\n"
        " border:1px solid #dce6ed; border-radius:9px; padding:8px 12px; min-height:27px; }\n"
        "QDialog#GlacierUpdateDialog28 QPushButton:hover { background:#edf5fa; border-color:#bed7e6; }\n"
        "QDialog#GlacierUpdateDialog28 QPushButton:disabled { color:#a4b2bc; background:#f5f8fa; }\n"
        "QDialog#GlacierUpdateDialog28 QPushButton#GlacierPrimaryUpdate28 {\n"
        " background:#277aa8; border:1px solid #277aa8; color:white; font-weight:600; }\n"
        "QDialog#GlacierUpdateDialog28 QPushButton#GlacierPrimaryUpdate28:hover {\n"
        " background:#17678f; }\n"
        "QDialog#GlacierUpdateDialog28 QProgressBar { background:#e9f0f6;\n"
        " border:1px solid #dce8f0; border-radius:7px; height:13px; text-align:center; }\n"
        "QDialog#GlacierUpdateDialog28 QProgressBar::chunk { background:#3c97c4; border-radius:6px; }\n"
        "QDialog#GlacierUpdateDialog28 QTextEdit { background:white;\n"
        " border:1px solid #e1e9ef; border-radius:9px; padding:9px; }\n"
        "''')",
    )
    source = _once(source, "        layout = QVBoxLayout(self)",
                   "        layout = QVBoxLayout(self)\n"
                   "        layout.setContentsMargins(24, 21, 24, 20)\n"
                   "        layout.setSpacing(10)")
    source = _once(
        source, "Qt WebEngine 浏览器 · 内置 sing-box VLESS · 本地优先",
        "Windows x64 · 内置 VLESS · 用户数据保存在本机",
    )
    source = _once(
        source, "这是未签名的测试版；为安全起见，不会静默安装。",
        "下载中断后可继续；安装包尚无 Authenticode 代码签名，安装前必须确认。",
    )
    source = _once(source, "QPushButton('安装更新并退出')",
                   "QPushButton('安装更新并重启')")
    source = _once(
        source, "        self.install_button.clicked.connect(manager.install)",
        "        self.install_button.setObjectName('GlacierPrimaryUpdate28')\n"
        "        self.install_button.clicked.connect(manager.install)",
    )
    # Do not falsely reset the visible progress to 0 if partial bytes survive.
    source = _once(
        source,
        "        if self.dialog:\n"
        "            self.dialog.progress.setRange(0, 100)\n"
        "            self.dialog.progress.setValue(0)\n\n"
        "    def _on_finished(self):",
        "        if self.dialog and '已保留下载进度' not in error:\n"
        "            self.dialog.progress.setRange(0, 100)\n"
        "            self.dialog.progress.setValue(0)\n\n"
        "    def _on_finished(self):",
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
