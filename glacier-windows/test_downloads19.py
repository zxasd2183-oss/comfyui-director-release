"""v0.19 download center filename, path and state filters."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from glacier_downloads17 import _download_matches19
from test_downloads17 import Host, FakeDownload


class DownloadFilters19Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication(
            ["glacier-download-filters","-platform","offscreen"])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.win=Host(self.folder)

    def tearDown(self):
        self.win._downloads_timer17.stop()
        self.win.close()
        self.temp.cleanup()

    def test_pure_filters_and_casefold(self):
        row={"name":"Movie.MP4","directory":"/Downloads/Projects","state":"completed"}
        self.assertTrue(_download_matches19(row,"movie","all"))
        self.assertTrue(_download_matches19(row,"projects","completed"))
        self.assertFalse(_download_matches19(row,"other","all"))
        self.assertFalse(_download_matches19(row,"","active"))
        self.assertFalse(_download_matches19(row,"","other"))
        self.assertFalse(_download_matches19(row,"","bad-category"))

    def test_search_and_state_filter_do_not_modify_saved_records(self):
        first=FakeDownload(self.folder,"a-report.pdf")
        second=FakeDownload(self.folder,"b-photo.png")
        self.win.profile.downloadRequested.emit(first)
        self.win.profile.downloadRequested.emit(second)
        first.status="DownloadCompleted"
        first.stateChanged.emit()
        second.status="DownloadInterrupted"
        second.stateChanged.emit()
        self.win.show_download_center17()
        original=[dict(x) for x in self.win._downloads_items17]
        self.assertEqual(len(self.win._downloads_visible17),2)
        self.win._download_search19.setText("report")
        self.assertEqual(len(self.win._downloads_visible17),1)
        self.assertEqual(self.win._selected_download17()["name"],"a-report.pdf")
        self.win._download_category19.setCurrentIndex(3)
        self.assertEqual(len(self.win._downloads_visible17),0)
        self.win._download_search19.clear()
        self.assertEqual(len(self.win._downloads_visible17),1)
        self.assertEqual(self.win._selected_download17()["name"],"b-photo.png")
        self.win._download_category19.setCurrentIndex(0)
        self.assertEqual(len(self.win._downloads_visible17),2)
        self.assertEqual(original,self.win._downloads_items17)
        self.assertIn("共 2 项", self.win._download_count19.text())


if __name__=="__main__":
    unittest.main()
