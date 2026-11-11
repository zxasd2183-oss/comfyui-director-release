"""Glacier Browser v0.19 cross-platform tab actions.

Tab context menu works on the external Chrome-like QTabBar and the internal
QTabWidget bar. Operations use QWebEngine's existing tab objects, never
run JavaScript, browse the network directly, or persist credentials.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QMenu

from glacier_workspaces17 import _safe_url17


class GlacierTabs19:
    def setup_tabs19(self):
        self._tab_bars19 = []
        for bar in (self.tabs.tabBar(), getattr(self, "chrome_tab14", None)):
            if bar is None or bar in self._tab_bars19:
                continue
            bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            bar.customContextMenuRequested.connect(
                lambda pos, target=bar: self._open_tab_menu19(target, pos)
            )
            self._tab_bars19.append(bar)

    def _tab_index19(self, view):
        try:
            return self.tabs.indexOf(view)
        except (RuntimeError, AttributeError):
            return -1

    def _tab_address19(self, view):
        try:
            return _safe_url17(view.url().toString())
        except (RuntimeError, AttributeError, TypeError):
            return ""

    def _duplicate_tab19(self, view):
        if self._tab_index19(view) < 0:
            return False
        url = self._tab_address19(view)
        if not url:
            self.statusBar().showMessage("此页面不是可复制的 HTTPS/HTTP 网页", 3000)
            return False
        group_id = getattr(self, "_workspace_group_by_view17", {}).get(id(view))
        page = self.new_tab()
        if page is None:
            return False
        page.setUrl(QUrl(url))
        if group_id is not None and getattr(self, "_workspace_doc17", None):
            if any(group["id"] == group_id for group in self._active_workspace17()["groups"]):
                self._workspace_group_by_view17[id(page)] = group_id
                self._decorate_group_tabs17()
                self._queue_workspace_save17()
        return True

    def _copy_tab_url19(self, view):
        if self._tab_index19(view) < 0:
            return False
        url = self._tab_address19(view)
        if not url:
            self.statusBar().showMessage("此页面没有可复制的安全网页地址", 3000)
            return False
        QApplication.clipboard().setText(url)
        self.statusBar().showMessage("已复制网页地址", 2000)
        return True

    def _close_other_tabs19(self, view):
        if self._tab_index19(view) < 0:
            return False
        for index in reversed(range(self.tabs.count())):
            other = self.tabs.widget(index)
            if other is not view:
                self.close_tab(index)
        index = self._tab_index19(view)
        if index >= 0:
            self.tabs.setCurrentIndex(index)
        return True

    def _close_tabs_right19(self, view):
        index = self._tab_index19(view)
        if index < 0:
            return False
        for i in reversed(range(index + 1, self.tabs.count())):
            self.close_tab(i)
        return True

    def _assign_view_to_group19(self, view, group_id):
        index = self._tab_index19(view)
        if index < 0 or not callable(getattr(self, "assign_tab_group17", None)):
            return False
        previous = self.tabs.currentWidget()
        self.tabs.setCurrentIndex(index)
        result = self.assign_tab_group17(group_id)
        # Changing group should not unexpectedly switch browsing focus.
        old_index = self._tab_index19(previous)
        if old_index >= 0:
            self.tabs.setCurrentIndex(old_index)
        return result

    def _open_tab_menu19(self, bar, point):
        try:
            index = bar.tabAt(point)
        except (AttributeError, RuntimeError):
            return
        if index < 0 or index >= self.tabs.count():
            return
        view = self.tabs.widget(index)
        if view is None:
            return
        menu = QMenu(self)
        reload_action = menu.addAction("重新加载标签")
        reload_action.triggered.connect(
            lambda _checked=False, tab=view: tab.reload()
            if self._tab_index19(tab) >= 0 else None
        )
        safe = bool(self._tab_address19(view))
        duplicate = menu.addAction("复制此标签")
        duplicate.setEnabled(safe)
        duplicate.triggered.connect(
            lambda _checked=False, tab=view: self._duplicate_tab19(tab)
        )
        copy_url = menu.addAction("复制网页地址")
        copy_url.setEnabled(safe)
        copy_url.triggered.connect(
            lambda _checked=False, tab=view: self._copy_tab_url19(tab)
        )
        if hasattr(self, "_workspace_doc17"):
            submenu = menu.addMenu("加入标签分组")
            ungroup = submenu.addAction("不分组")
            ungroup.triggered.connect(
                lambda _checked=False, tab=view: self._assign_view_to_group19(tab, None))
            groups = self._active_workspace17()["groups"]
            if groups:
                submenu.addSeparator()
            for group in groups:
                gid = group["id"]
                a = submenu.addAction(group["name"])
                a.setCheckable(True)
                a.setChecked(self._workspace_group_by_view17.get(id(view)) == gid)
                a.triggered.connect(
                    lambda _checked=False, tab=view, chosen=gid:
                    self._assign_view_to_group19(tab, chosen)
                )
        menu.addSeparator()
        other = menu.addAction("关闭其他标签")
        other.setEnabled(self.tabs.count() > 1)
        other.triggered.connect(
            lambda _checked=False, tab=view: self._close_other_tabs19(tab))
        right = menu.addAction("关闭右侧标签")
        right.setEnabled(index < self.tabs.count() - 1)
        right.triggered.connect(
            lambda _checked=False, tab=view: self._close_tabs_right19(tab))
        close = menu.addAction("关闭此标签")
        close.triggered.connect(
            lambda _checked=False, tab=view:
            self.close_tab(self._tab_index19(tab))
            if self._tab_index19(tab) >= 0 else None
        )
        menu.exec(bar.mapToGlobal(point))
