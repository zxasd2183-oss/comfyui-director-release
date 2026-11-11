"""v0.17 download-center smoke tests, without starting real downloads."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QWidget

from glacier_downloads17 import (
    GlacierDownloads17, _clean_download_history17, _safe_download_path17
)


def cipher(data, decrypt=False):
    if decrypt:
        if not data.startswith(b"X-ENC:"):
            raise ValueError("invalid cipher data")
        return data[6:][::-1]
    return b"X-ENC:" + data[::-1]


class Profile(QObject):
    downloadRequested = Signal(object)


class FakeState:
    def __init__(self, name):
        self.name = name


class FakeDownload(QObject):
    stateChanged = Signal()
    receivedBytesChanged = Signal()
    totalBytesChanged = Signal()
    isPausedChanged = Signal()

    def __init__(self, directory, name="file.txt"):
        super().__init__()
        self.folder = str(directory)
        self.filename = name
        self.status = "DownloadRequested"
        self.bytes = 0
        self.total = 1000
        self.paused = False
        self.accepted = False

    def downloadFileName(self):
        return self.filename

    def downloadDirectory(self):
        return self.folder

    def receivedBytes(self):
        return self.bytes

    def totalBytes(self):
        return self.total

    def state(self):
        return FakeState(self.status)

    def isPaused(self):
        return self.paused

    def pause(self):
        self.paused = True
        self.isPausedChanged.emit()

    def resume(self):
        self.paused = False
        self.isPausedChanged.emit()

    def cancel(self):
        self.status = "DownloadCancelled"
        self.stateChanged.emit()

    def accept(self):
        self.accepted = True


class Host(GlacierDownloads17, QMainWindow):
    def __init__(self, folder):
        super().__init__()
        self.profile = Profile(self)
        holder = QWidget(self)
        self.setCentralWidget(holder)
        self.nav = QHBoxLayout(holder)
        self.setup_downloads17(self.nav, folder, cipher)


class Downloads17Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(
            ["Glacier-downloads-test", "-platform", "offscreen"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.win = Host(self.folder)

    def tearDown(self):
        self.win._downloads_timer17.stop()
        self.win.close()
        self.temp.cleanup()

    def test_observer_never_accepts_without_user_consent(self):
        req = FakeDownload(self.folder)
        self.win.profile.downloadRequested.emit(req)
        self.assertFalse(req.accepted)
        self.assertEqual(len(self.win._downloads_items17), 1)
        self.assertEqual(self.win._downloads_items17[0]["state"], "requested")
        req.status = "DownloadInProgress"
        req.bytes = 250
        req.stateChanged.emit()
        self.assertEqual(self.win._downloads_items17[0]["received"], 250)
        self.assertIn("下载 1", self.win._downloads_button17.text())
        self.win.show_download_center17()
        self.win.pause_download17()
        self.assertTrue(req.isPaused())
        self.win.resume_download17()
        self.assertFalse(req.isPaused())

    def test_completion_is_encrypted_and_stores_no_source_url(self):
        req = FakeDownload(self.folder, "report.txt")
        self.win.profile.downloadRequested.emit(req)
        req.status = "DownloadCompleted"
        req.bytes = req.total
        req.stateChanged.emit()
        self.win._save_downloads17()
        blob = (self.folder / "downloads-v17.enc").read_bytes()
        self.assertNotIn(b"report.txt", blob)
        self.assertIn(b"report.txt", cipher(blob, True))
        second = Host(self.folder)
        try:
            self.assertEqual(second._downloads_items17[0]["name"], "report.txt")
            self.assertEqual(second._downloads_items17[0]["state"], "completed")
        finally:
            second._downloads_timer17.stop()
            second.close()

    def test_interrupted_state_restored_safely(self):
        req = FakeDownload(self.folder)
        self.win.profile.downloadRequested.emit(req)
        req.status = "DownloadInProgress"
        req.stateChanged.emit()
        self.win._save_downloads17()
        second = Host(self.folder)
        try:
            self.assertEqual(second._downloads_items17[0]["state"], "interrupted")
        finally:
            second._downloads_timer17.stop()
            second.close()

    def test_only_completed_existing_safe_files_may_be_opened(self):
        (self.folder / "report.txt").write_text("ok", encoding="utf-8")
        row = {"state": "completed", "directory": str(self.folder),
               "name": "report.txt"}
        self.assertEqual(_safe_download_path17(row), self.folder / "report.txt")
        self.assertIsNone(_safe_download_path17({**row, "state": "in_progress"}))
        self.assertIsNone(_safe_download_path17({**row, "name": "../secret.txt"}))
        self.assertIsNone(_safe_download_path17({**row, "name": r"C:\secret.txt"}))

    def test_invalid_history_raises(self):
        with self.assertRaises(ValueError):
            _clean_download_history17({"schema": 5, "items": []})


if __name__ == "__main__":
    unittest.main()
