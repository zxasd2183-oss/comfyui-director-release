"""In-app Mac updater: signed DMGs from GitHub through fail-closed VLESS."""
from __future__ import annotations
import json
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout)
from mac_update_core import (CURRENT_VERSION, UpdateError, get_manifest,
                             newer_than, download_dmg, verify_local_dmg)
from mac_install import writable_installed_app, launch_user_confirmed_install


class _UpdateSignals(QObject):
    checked = Signal(object)
    downloaded = Signal(str)
    failed = Signal(str)
    progress = Signal(int)


class MacUpdateUI:
    def setup_updater(self, bar, directory):
        self._mac_update_dir = Path(directory) / "updates"
        self._mac_update_dir.mkdir(parents=True,exist_ok=True)
        self._mac_settings_path = Path(directory) / "mac-update-settings.json"
        try:
            self._mac_update_settings = json.loads(self._mac_settings_path.read_text(encoding="utf-8"))
            if not isinstance(self._mac_update_settings,dict): raise ValueError()
        except (OSError,ValueError):
            self._mac_update_settings = {"auto_check": True, "auto_download": True}
        self._mac_update_busy = False
        self._mac_manifest = None
        self._mac_installer = None
        self._mac_signal = _UpdateSignals()
        self._mac_signal.checked.connect(self._mac_checked)
        self._mac_signal.downloaded.connect(self._mac_downloaded)
        self._mac_signal.failed.connect(self._mac_failed)
        self._mac_signal.progress.connect(self._mac_progress_changed)

        button = QPushButton("↻ Mac 更新")
        button.setToolTip("检查 macOS Apple Silicon 版本更新")
        button.clicked.connect(self.show_mac_updates)
        bar.addWidget(button)
        self._mac_update_button = button

        dlg = QDialog(self)
        dlg.setWindowTitle("Glacier Browser · 软件内更新")
        dlg.resize(460,270)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"❄ Glacier Browser  ·  macOS Apple Silicon v{CURRENT_VERSION}"))
        lay.addWidget(QLabel("更新通道：VPS / macos-arm64  ·  Ed25519 验签"))
        status = QLabel("点击「检查更新」获取最新版本。")
        status.setWordWrap(True)
        lay.addWidget(status)
        progress = QProgressBar()
        progress.setRange(0,100)
        progress.setValue(0)
        lay.addWidget(progress)
        row=QHBoxLayout()
        check=QPushButton("检查更新")
        download=QPushButton("下载更新")
        install=QPushButton("一键安装并重启" if writable_installed_app() else "打开 DMG 安装")
        download.setEnabled(False)
        install.setEnabled(False)
        check.clicked.connect(lambda: self.check_mac_updates(True))
        download.clicked.connect(self.download_mac_update)
        install.clicked.connect(self.open_verified_dmg)
        for widget in (check,download,install):row.addWidget(widget)
        lay.addLayout(row)
        auto_check=QCheckBox("启动时自动检查更新")
        auto_download=QCheckBox("检测到新版后自动下载（安装前仍需要确认）")
        auto_check.setChecked(bool(self._mac_update_settings.get("auto_check",True)))
        auto_download.setChecked(bool(self._mac_update_settings.get("auto_download",True)))
        auto_check.toggled.connect(lambda v:self._save_mac_setting("auto_check",v))
        auto_download.toggled.connect(lambda v:self._save_mac_setting("auto_download",v))
        lay.addWidget(auto_check)
        lay.addWidget(auto_download)
        lay.addWidget(QLabel("正式更新由自有 VPS HTTPS 提供；签名及 SHA256 均会校验。"))
        lay.addWidget(QLabel("未进行 Apple Developer ID 签名/公证，安装时需确认。"))
        self._mac_dialog=dlg
        self._mac_status=status
        self._mac_progress=progress
        self._mac_check_button=check
        self._mac_download_button=download
        self._mac_install_button=install
        if auto_check.isChecked():
            QTimer.singleShot(4500,lambda:self.check_mac_updates(False))

    def _save_mac_setting(self,key,value):
        self._mac_update_settings[key]=bool(value)
        try:
            self._mac_settings_path.write_text(
                json.dumps(self._mac_update_settings,ensure_ascii=False,indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def show_mac_updates(self):
        self._mac_dialog.show()
        self._mac_dialog.raise_()
        self._mac_dialog.activateWindow()


    def _set_busy(self,value):
        self._mac_update_busy=value
        self._mac_check_button.setEnabled(not value)
        self._mac_download_button.setEnabled(not value and self._mac_manifest is not None
                                            and self._mac_installer is None)
        self._mac_install_button.setEnabled(not value and self._mac_installer is not None)

    def check_mac_updates(self,show_ui=True):
        if self._mac_update_busy:return
        self._mac_installer=None
        self._mac_manifest=None
        self._set_busy(True)
        self._mac_status.setText("正在从 VPS 获取 Mac 签名更新…")
        if show_ui:self.show_mac_updates()
        port=getattr(self,"proxy_port",0)
        def job():
            try:
                manifest=get_manifest(port)
                self._mac_signal.checked.emit(manifest)
            except Exception as exc:
                self._mac_signal.failed.emit(str(exc))
        threading.Thread(target=job,name="glacier-mac-update-check",daemon=True).start()

    def _mac_checked(self,manifest):
        self._set_busy(False)
        try:
            outdated=newer_than(CURRENT_VERSION,manifest["version"])
        except (ValueError,UpdateError) as exc:
            self._mac_status.setText("更新版本无效："+str(exc))
            return
        if not outdated:
            self._mac_status.setText(f"当前已是最新版 v{CURRENT_VERSION}。")
            return
        self._mac_manifest=manifest
        self._mac_status.setText("发现 v"+manifest["version"]+"："+manifest["notes"])
        self._set_busy(False)
        if self._mac_update_settings.get("auto_download",True):
            self.download_mac_update()

    def download_mac_update(self):
        if self._mac_update_busy or self._mac_manifest is None:return
        self._mac_progress.setValue(0)
        self._set_busy(True)
        self._mac_status.setText("正在下载并验证新版 DMG…")
        manifest=self._mac_manifest.copy()
        port=getattr(self,"proxy_port",0)
        def job():
            try:
                path=download_dmg(manifest,port,self._mac_update_dir,
                                  lambda n:self._mac_signal.progress.emit(n))
                self._mac_signal.downloaded.emit(str(path))
            except Exception as exc:
                self._mac_signal.failed.emit(str(exc))
        threading.Thread(target=job,name="glacier-mac-update-download",daemon=True).start()

    def _mac_progress_changed(self,n):
        self._mac_progress.setValue(n)

    def _mac_downloaded(self,path):
        self._mac_installer=Path(path)
        self._set_busy(False)
        self._mac_progress.setValue(100)
        self._mac_status.setText("DMG 已下载，数字签名清单、文件大小及 SHA256 均已校验。")
        self.show_mac_updates()

    def _mac_failed(self,message):
        self._set_busy(False)
        self._mac_status.setText("更新失败：" + message)
        self.show_mac_updates()

    def open_verified_dmg(self):
        if self._mac_installer is None or not self._mac_installer.is_file():
            return
        try:
            if self._mac_manifest is None:
                raise UpdateError("没有可验证的更新清单")
            verify_local_dmg(self._mac_manifest, self._mac_installer)
        except UpdateError as exc:
            self._mac_installer = None
            self._set_busy(False)
            QMessageBox.warning(self, "Glacier Browser", "更新包验证失败：" + str(exc))
            return
        if writable_installed_app() is not None:
            answer=QMessageBox.question(
                self, "一键安装 Glacier Browser 更新",
                "已验证签名更新清单及 DMG SHA256。\n"
                "确认后将保存会话并退出当前浏览器，在可写的 Applications 目录"
                "替换应用，随后自动重启。\n"
                "钥匙串、浏览记录和账户数据保存在应用程序包之外，不会被清除。\n\n"
                "安装包尚无 Apple Developer ID 公证，macOS 仍可能要求授权。\n\n"
                "立即安装并重启？",
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                launch_user_confirmed_install(
                    self._mac_manifest, self._mac_installer, self._mac_update_dir
                )
            except UpdateError as exc:
                QMessageBox.warning(
                    self, "Glacier Browser", "无法启动一键安装：" + str(exc)
                    + "\n可改用 Finder 打开 DMG 手动替换。"
                )
                return
            self._mac_status.setText("安装助手已启动，正在保存浏览会话并退出…")
            QTimer.singleShot(200, self.close)
            return

        answer=QMessageBox.question(
            self,
            "安装 Glacier Browser 更新",
            "下载的 DMG 已根据已签名清单验证。\n"
            "将使用 Finder 打开安装盘。请关闭当前浏览器，然后将 GlacierBrowser.app "
            "拖入「应用程序」，并确认替换旧版。\n\n现在打开 DMG？",
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer!=QMessageBox.StandardButton.Yes:return
        try:
            subprocess.Popen(["/usr/bin/open",str(self._mac_installer)],close_fds=True)
        except OSError as exc:
            QMessageBox.warning(self,"Glacier Browser","无法打开 DMG："+str(exc))
