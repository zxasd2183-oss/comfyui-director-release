"""Interactive Safari-style macOS sidebar for Glacier Browser.

Uses existing tab, bookmark QActions and recent local navigation sources.
Persists only UI preferences (open/mode/width), never visited URLs or secrets.
The user remains in control of all navigation and account actions.
"""
from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import Qt, QSettings, QTimer, QUrl
from PySide6.QtWidgets import (
    QHBoxLayout, QLineEdit, QListWidgetItem, QPushButton, QWidget,
)


SAFARI_SIDEBAR_QSS39 = """
QWidget#GlacierSafariModes39 {
    background: #e3e7ed; border-radius: 9px;
}
QPushButton#GlacierSafariModeTabs39,
QPushButton#GlacierSafariBookmarks38,
QPushButton#GlacierSafariHistory38 {
    background: transparent; border: none; border-radius: 7px;
    color: #455366; padding: 6px 3px; min-height: 27px;
    text-align: center; font-size: 11px;
}
QPushButton#GlacierSafariModeTabs39:checked,
QPushButton#GlacierSafariBookmarks38:checked,
QPushButton#GlacierSafariHistory38:checked {
    background: #ffffff; color: #2a4e78; font-weight: 600;
}
QLineEdit#GlacierSafariSearch39 {
    background: #ffffff; border: 1px solid #d9dfe8;
    border-radius: 8px; padding: 6px 10px;
    color: #38495e; min-height: 27px; font-size: 12px;
}
QPushButton#GlacierSafariFooter39 {
    background: transparent; color: #4e6681;
    border: none; border-radius: 7px;
    padding: 7px; text-align: left; min-height: 27px;
}
QPushButton#GlacierSafariFooter39:hover { background: #dfe7f1; }
"""


def _safe_history_url39(value):
    """Never expose file/data/javascript, credentials in URLs, or local settings."""
    if isinstance(value, QUrl):
        url = value
    elif isinstance(value, str) and len(value) <= 8192:
        url = QUrl(value)
    else:
        return ""
    if (not url.isValid() or url.scheme().lower() not in ("http", "https")
            or not url.host() or url.userInfo()):
        return ""
    return url.toString()


def _truthy39(value):
    return value is True or str(value).strip().lower() in ("1", "true", "yes")


class SafariSidebar39:
    """Controller for one live QListWidget; no extra WebEngine browser instance."""

    def __init__(self, browser, side, column, title, tab_list, toggle, splitter,
                 bookmarks_button, history_button):
        self.browser = browser
        self.side = side
        self.column = column
        self.title = title
        self.list = tab_list
        self.toggle = toggle
        self.splitter = splitter
        self.settings = getattr(browser, "_safari_settings39", None)
        if self.settings is None:
            self.settings = QSettings("Borealos", "GlacierBrowser")
        saved = str(self.settings.value("ui/macSafariSidebar39/mode", "tabs"))
        self.mode = saved if saved in ("tabs", "bookmarks", "history") else "tabs"
        self.width = self._coerce_width(self.settings.value(
            "ui/macSafariSidebar39/width", 248))
        self.entries = []
        self._rendering = False

        modes = QWidget(side)
        modes.setObjectName("GlacierSafariModes39")
        line = QHBoxLayout(modes)
        line.setContentsMargins(3, 3, 3, 3)
        line.setSpacing(2)
        self.tabs_button = QPushButton("标签", modes)
        self.tabs_button.setObjectName("GlacierSafariModeTabs39")
        # Repurpose the original buttons without replacing their object IDs.
        for button in (self.tabs_button, bookmarks_button, history_button):
            column.removeWidget(button)
            button.setParent(modes)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            line.addWidget(button, 1)
        bookmarks_button.setText("书签")
        history_button.setText("历史")
        self.bookmarks_button = bookmarks_button
        self.history_button = history_button
        column.insertWidget(1, modes)

        search = QLineEdit(side)
        search.setObjectName("GlacierSafariSearch39")
        search.setClearButtonEnabled(True)
        search.setPlaceholderText("搜索标签页")
        column.insertWidget(2, search)
        self.search = search

        footer = QPushButton(side)
        footer.setObjectName("GlacierSafariFooter39")
        footer.setCursor(Qt.CursorShape.PointingHandCursor)
        footer.hide()
        column.insertWidget(column.indexOf(self.list) + 1, footer)
        self.footer = footer

        self.tabs_button.clicked.connect(lambda: self.set_mode("tabs"))
        bookmarks_button.clicked.connect(lambda: self.set_mode("bookmarks"))
        history_button.clicked.connect(lambda: self.set_mode("history"))
        search.textChanged.connect(lambda _: self.refresh())
        tab_list.itemClicked.connect(self.activate)
        tab_list.itemActivated.connect(self.activate)
        footer.clicked.connect(self.open_full_view)
        browser.tabs.currentChanged.connect(lambda _: QTimer.singleShot(0, self.refresh))
        splitter.splitterMoved.connect(self._save_width)

        self.set_mode(self.mode)
        if _truthy39(self.settings.value("ui/macSafariSidebar39/open", False)):
            # Needs the real post-show splitter width to restore correctly.
            QTimer.singleShot(0, lambda: self.toggle.setChecked(True))

    @staticmethod
    def _coerce_width(value):
        try:
            return min(340, max(205, int(value)))
        except (TypeError, ValueError):
            return 248

    def _save_width(self, *_):
        if self.side.isVisible() and self.side.width() >= 205:
            self.width = self._coerce_width(self.side.width())
            self.settings.setValue("ui/macSafariSidebar39/width", self.width)

    def set_mode(self, mode):
        if mode not in ("tabs", "bookmarks", "history"):
            raise ValueError("Invalid sidebar mode")
        self.mode = mode
        self.settings.setValue("ui/macSafariSidebar39/mode", mode)
        for button, value in ((self.tabs_button, "tabs"),
                              (self.bookmarks_button, "bookmarks"),
                              (self.history_button, "history")):
            button.setChecked(mode == value)
        self.title.setText({"tabs": "标签页", "bookmarks": "书签",
                            "history": "最近浏览"}[mode])
        self.search.setPlaceholderText({
            "tabs": "搜索当前标签",
            "bookmarks": "搜索书签",
            "history": "搜索最近浏览",
        }[mode])
        self.search.clear()
        self.footer.setVisible(mode in ("bookmarks", "history"))
        self.footer.setText("打开完整书签菜单" if mode == "bookmarks"
                            else "打开完整历史记录")
        self.refresh()

    def _bookmark_entries(self):
        menu = getattr(self.browser, "bookmarks_menu", None)
        if menu is None:
            return []
        # Trigger the same refresh used by the existing browser menu; never
        # deserialize its vault/store or duplicate bookmark URLs.
        try:
            menu.aboutToShow.emit()
        except (RuntimeError, AttributeError):
            return []
        result = []
        def visit(actions, depth):
            for action in actions:
                if action.isSeparator() or not action.text().strip():
                    continue
                submenu = action.menu()
                if submenu is not None and depth < 2:
                    visit(submenu.actions(), depth + 1)
                elif submenu is None and action.isEnabled():
                    result.append((action.text().strip(), ("bookmark", action)))
                if len(result) >= 150:
                    return
        visit(menu.actions(), 0)
        return result[:150]

    def _history_entries(self):
        result = []
        seen = set()
        def add(address, label):
            uri = _safe_history_url39(address)
            if uri and uri not in seen and len(result) < 150:
                seen.add(uri)
                result.append(((label or QUrl(uri).host()).strip()[:120],
                               ("history", uri)))
        # The existing encrypted workspace/session sources remain authoritative.
        # Read only in-memory, current-page visit history and recent closed URLs.
        recent = getattr(self.browser, "_recently_closed15", ())
        if isinstance(recent, (tuple, list)):
            for address in reversed(recent[-60:]):
                add(address, "")
        for index in range(self.browser.tabs.count()):
            page = self.browser.tabs.widget(index)
            getter = getattr(page, "history", None)
            if not callable(getter):
                continue
            try:
                items = getter().items()
            except (AttributeError, RuntimeError):
                continue
            for item in reversed(items[-75:]):
                try:
                    add(item.url(), item.title())
                except (AttributeError, RuntimeError):
                    continue
        return result[:150]

    def _tab_entries(self):
        result = []
        tabs = self.browser.tabs
        for i in range(tabs.count()):
            title = tabs.tabText(i).strip() or "新标签页"
            page = tabs.widget(i)
            url = _safe_history_url39(page.url()) if callable(
                getattr(page, "url", None)) else ""
            result.append((title, ("tab", i, url)))
        return result

    def refresh(self):
        if self._rendering or not self.side.isVisible():
            return
        self._rendering = True
        try:
            original = {
                "tabs": self._tab_entries,
                "bookmarks": self._bookmark_entries,
                "history": self._history_entries,
            }[self.mode]()
            term = self.search.text().strip().casefold()
            matching = []
            for title, payload in original:
                address = payload[2] if payload[0] == "tab" else (
                    payload[1] if payload[0] == "history" else "")
                if not term or term in title.casefold() or term in str(address).casefold():
                    matching.append((title, payload))
            # Do not clear/rebuild needlessly; no WebEngine rerender on timer.
            signature = [(title, payload[0], payload[1] if payload[0] != "bookmark" else id(payload[1]))
                         for title, payload in matching]
            if signature != getattr(self, "_signature", None):
                self.list.blockSignals(True)
                self.list.clear()
                self.entries = matching
                for title, payload in matching:
                    item = QListWidgetItem(title, self.list)
                    if payload[0] == "tab" and payload[2]:
                        item.setToolTip(payload[2])
                    elif payload[0] == "history":
                        item.setToolTip(payload[1])
                self.list.blockSignals(False)
                self._signature = signature
            if self.mode == "tabs":
                index = self.browser.tabs.currentIndex()
                chosen = next((i for i, (_, payload) in enumerate(self.entries)
                               if payload[0] == "tab" and payload[1] == index), -1)
                self.list.blockSignals(True)
                self.list.setCurrentRow(chosen)
                self.list.blockSignals(False)
        finally:
            self._rendering = False

    def activate(self, item):
        index = self.list.row(item)
        if index < 0 or index >= len(self.entries):
            return
        _title, payload = self.entries[index]
        if payload[0] == "tab":
            self.browser.tabs.setCurrentIndex(payload[1])
        elif payload[0] == "bookmark":
            action = payload[1]
            if action.isEnabled():
                action.trigger()  # Existing trusted browser callback.
        elif payload[0] == "history":
            url = _safe_history_url39(payload[1])
            if url:
                page = self.browser.new_tab()
                if page is not None:
                    page.setUrl(QUrl(url))

    def open_full_view(self):
        if self.mode == "bookmarks":
            menu = getattr(self.browser, "bookmarks_menu", None)
            if menu is not None:
                menu.popup(self.footer.mapToGlobal(self.footer.rect().bottomLeft()))
        elif self.mode == "history":
            callback = getattr(self.browser, "show_history", None)
            if callable(callback):
                callback()

    def on_visibility(self, visible):
        self.side.setVisible(bool(visible))
        self.settings.setValue("ui/macSafariSidebar39/open", bool(visible))
        if visible:
            self.splitter.setSizes([
                self.width, max(400, self.splitter.width() - self.width)
            ])
            self.refresh()
        else:
            self.splitter.setSizes([0, max(400, self.splitter.width())])
