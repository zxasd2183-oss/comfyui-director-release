"""Glacier Browser v0.16 cross-platform tab finder and page zoom.

Qt-only UI layer shared by Windows and macOS. No networking, telemetry,
credential access, updater changes, or filesystem writes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QToolButton, QVBoxLayout,
)


ZOOM_STEPS16 = (0.50, 0.67, 0.75, 0.80, 0.90, 1.00, 1.10, 1.25,
                1.50, 1.75, 2.00, 2.50, 3.00)


class GlacierProductivity16:
    """Small UI-only feature layer, compatible with v0.15 desktop mixins."""

    def setup_productivity16(self, nav, *, mac=False):
        self._productivity_shortcuts16 = []
        self._tab_search_dialog16 = None
        self._tab_search_results16 = []

        # Search lives beside the existing + button, on the external tab bar.
        search = QToolButton(self)
        search.setObjectName("GlacierTabSearch16")
        search.setText("⌕")
        search.setToolTip("搜索当前与最近关闭的标签页")
        search.setMinimumWidth(35)
        search.clicked.connect(self.show_tab_search16)
        self.chrome_tab14.parentWidget().layout().addWidget(search)
        self._tab_search_button16 = search

        # Per-tab zoom via a compact native menu, never JavaScript injection.
        zoom = QToolButton(self)
        zoom.setObjectName("GlacierZoom16")
        zoom.setText("100%")
        zoom.setToolTip("网页缩放")
        zoom.setMinimumWidth(62)
        zoom.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(zoom)
        zoom_in = menu.addAction("放大网页")
        zoom_in.triggered.connect(lambda checked=False: self.change_zoom16(1))
        zoom_out = menu.addAction("缩小网页")
        zoom_out.triggered.connect(lambda checked=False: self.change_zoom16(-1))
        menu.addSeparator()
        zoom_reset = menu.addAction("恢复 100%")
        zoom_reset.triggered.connect(lambda checked=False: self.reset_zoom16())
        zoom.setMenu(menu)
        nav.addWidget(zoom)
        self._zoom_button16 = zoom
        self.tabs.currentChanged.connect(lambda _index: self._refresh_zoom16())
        self._refresh_zoom16()

        prefix = "Meta" if mac else "Ctrl"
        self._make_shortcut16(f"{prefix}+Shift+A", self.show_tab_search16)
        self._make_shortcut16(f"{prefix}+Equal", lambda: self.change_zoom16(1))
        self._make_shortcut16(f"{prefix}+Shift+Equal", lambda: self.change_zoom16(1))
        self._make_shortcut16(f"{prefix}+Minus", lambda: self.change_zoom16(-1))
        self._make_shortcut16(f"{prefix}+0", self.reset_zoom16)

        # Keep controls matched to Glacier's existing pastel palette.
        self.setStyleSheet(self.styleSheet() + """
QToolButton#GlacierTabSearch16, QToolButton#GlacierZoom16 {
    color: #2d617f; background: #e8f4fb; border: 1px solid #cfdfec;
    border-radius: 9px; padding: 5px 9px; min-height: 24px;
}
QToolButton#GlacierTabSearch16:hover, QToolButton#GlacierZoom16:hover {
    background: #d5ebfa;
}
QDialog#GlacierTabFinder16 { background: #f4faff; }
QLineEdit#GlacierTabFinderInput16 { background: #fff; padding: 10px;
    border: 1px solid #a5cfe9; border-radius: 12px; }
QListWidget#GlacierTabFinderResults16 { background: #fff;
    border: 1px solid #deebf4; border-radius: 10px; }
QListWidget#GlacierTabFinderResults16::item { padding: 9px; }
QListWidget#GlacierTabFinderResults16::item:selected {
    background: #d5ebfa; color: #255776;
}
""")

    def _make_shortcut16(self, sequence, callback):
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(callback)
        self._productivity_shortcuts16.append(shortcut)

    def _current_page16(self):
        page = self.current()
        if page is None or not callable(getattr(page, "zoomFactor", None)):
            return None
        return page

    def _refresh_zoom16(self):
        page = self._current_page16()
        factor = page.zoomFactor() if page is not None else 1.0
        self._zoom_button16.setText(f"{round(factor * 100)}%")

    def change_zoom16(self, direction):
        page = self._current_page16()
        if page is None:
            return
        current = page.zoomFactor()
        if direction > 0:
            target = next((x for x in ZOOM_STEPS16 if x > current + 0.001),
                          ZOOM_STEPS16[-1])
        elif direction < 0:
            target = next((x for x in reversed(ZOOM_STEPS16)
                           if x < current - 0.001), ZOOM_STEPS16[0])
        else:
            return
        page.setZoomFactor(target)
        self._refresh_zoom16()

    def reset_zoom16(self):
        page = self._current_page16()
        if page is not None:
            page.setZoomFactor(1.0)
        self._refresh_zoom16()

    def _init_tab_finder16(self):
        dialog = QDialog(self)
        dialog.setObjectName("GlacierTabFinder16")
        dialog.setWindowTitle("❄ 搜索标签页")
        dialog.resize(550, 440)
        layout = QVBoxLayout(dialog)
        title = QLabel("搜索当前标签页和最近关闭的标签页", dialog)
        layout.addWidget(title)
        search = QLineEdit(dialog)
        search.setObjectName("GlacierTabFinderInput16")
        search.setPlaceholderText("输入标签名称或网站域名，回车快速切换")
        layout.addWidget(search)
        results = QListWidget(dialog)
        results.setObjectName("GlacierTabFinderResults16")
        layout.addWidget(results, 1)
        row = QHBoxLayout()
        hint = QLabel("仅在本机搜索，不会上传浏览记录", dialog)
        row.addWidget(hint, 1)
        open_button = QPushButton("切换 / 打开", dialog)
        row.addWidget(open_button)
        layout.addLayout(row)
        self._tab_search_dialog16 = dialog
        self._tab_search_input16 = search
        self._tab_search_list16 = results
        search.textChanged.connect(self._filter_tab_search16)
        search.returnPressed.connect(self._activate_tab_search16)
        results.itemActivated.connect(lambda _item: self._activate_tab_search16())
        results.itemDoubleClicked.connect(lambda _item: self._activate_tab_search16())
        open_button.clicked.connect(self._activate_tab_search16)

    def show_tab_search16(self):
        if self._tab_search_dialog16 is None:
            self._init_tab_finder16()
        self._tab_search_input16.clear()
        self._filter_tab_search16("")
        self._tab_search_dialog16.show()
        self._tab_search_dialog16.raise_()
        self._tab_search_dialog16.activateWindow()
        self._tab_search_input16.setFocus()

    def _filter_tab_search16(self, query):
        if self._tab_search_dialog16 is None:
            return
        self._tab_search_results16 = []
        results = self._tab_search_list16
        results.clear()
        tokens = query.strip().casefold().split()
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            title = self.tabs.tabText(index).strip() or "新标签"
            try:
                url = view.url()
                host = url.host() if isinstance(url, QUrl) else ""
            except (AttributeError, RuntimeError):
                host = ""
            searchable = (title + " " + host).casefold()
            if all(token in searchable for token in tokens):
                self._tab_search_results16.append(("open", view))
                results.addItem(QListWidgetItem(f"当前  ·  {title}  ·  {host or '本地页面'}"))

        # Recent closed URLs already pass the HTTP(S)-only validation of v0.15.
        for url in reversed(getattr(self, "_recently_closed15", [])[-20:]):
            parsed = QUrl(url)
            if parsed.scheme().lower() not in ("http", "https") or not parsed.host():
                continue
            host = parsed.host()
            if all(token in host.casefold() for token in tokens):
                self._tab_search_results16.append(("closed", url))
                results.addItem(QListWidgetItem(f"最近关闭  ·  {host}"))

        if self._tab_search_results16:
            results.setCurrentRow(0)
        else:
            no_match = QListWidgetItem("没有符合条件的标签页")
            no_match.setFlags(Qt.ItemFlag.NoItemFlags)
            results.addItem(no_match)

    def _activate_tab_search16(self):
        row = self._tab_search_list16.currentRow()
        if not 0 <= row < len(self._tab_search_results16):
            return
        kind, value = self._tab_search_results16[row]
        if kind == "open":
            try:
                index = self.tabs.indexOf(value)
            except RuntimeError:
                index = -1
            if index < 0:
                return
            self.tabs.setCurrentIndex(index)
        else:
            parsed = QUrl(value)
            if parsed.scheme().lower() not in ("http", "https") or not parsed.host():
                return
            recent = getattr(self, "_recently_closed15", [])
            if value in recent:
                recent.remove(value)
            view = self.new_tab()
            if view is None:
                return
            view.setUrl(parsed)
        self._tab_search_dialog16.accept()
