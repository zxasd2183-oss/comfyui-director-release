"""Safari-inspired macOS presentation for Glacier Browser.

Mac only. The existing tab model, navigation signals, network/VLESS engine,
encrypted vault, and signed-update publisher are not replaced.
"""
from __future__ import annotations

import sys
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QShortcut, QKeySequence
from mac_safari_sidebar39 import SafariSidebar39, SAFARI_SIDEBAR_QSS39
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QSplitter, QToolButton, QVBoxLayout, QWidget,
)


SAFARI_MAC_QSS38 = """
/* macOS: native traffic lights remain managed by the operating system. */
QWidget#GlacierBrowserRoot32 { background: #ffffff; color: #28323d; }
QFrame#GlacierNavigation32 {
    background: #eef0f3; border: none;
    border-bottom: 1px solid #d9dce2;
}
QWidget#GlacierTabStrip14 {
    background: #f3f4f6; border: none;
    border-bottom: 1px solid #d9dce2;
}
QTabBar#GlacierExternalTabs14 { border: none; background: transparent; }
QTabBar#GlacierExternalTabs14::tab {
    background: transparent; color: #68707d; border: none;
    border-right: 1px solid #d9dce2;
    border-radius: 7px; min-width: 132px; max-width: 224px;
    min-height: 24px; margin: 3px 2px 3px 2px;
    padding: 3px 13px 3px 13px;
    font-size: 12px;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: #ffffff; color: #28323d;
    border: 1px solid #e2e5eb; border-radius: 7px; font-weight: 550;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
    background: #e8ebf0; color: #344250;
}
QFrame#GlacierOmniboxShell33 {
    background: #ffffff; border: 1px solid #d5dbe4;
    border-radius: 9px;
}
QFrame#GlacierOmniboxShell33[glacierFocus="true"] {
    background: #ffffff; border: 2px solid #6ca9ed;
    border-radius: 9px;
}
QLineEdit#GlacierOmnibox14 {
    background: transparent; border: none; border-radius: 0;
    min-height: 29px; max-height: 33px;
    padding: 0 5px; font-size: 13px; color: #28323d;
}
QLineEdit#GlacierOmnibox14:focus {
    background: transparent; border: none; padding: 0 5px;
}
QToolButton#GlacierSafariSidebarToggle38,
QToolButton#GlacierSafariShare38 {
    background: transparent; color: #475d75; border: none;
    border-radius: 7px; padding: 0;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
}
QToolButton#GlacierSafariSidebarToggle38:hover,
QToolButton#GlacierSafariShare38:hover {
    background: #dbe2ea;
}
QToolButton#GlacierSafariSidebarToggle38:checked {
    background: #d2deec; color: #265f9f;
}
QFrame#GlacierSafariSidebar38 {
    background: #f1f3f7; border: none;
    border-right: 1px solid #d8dfe9;
}
QLabel#GlacierSafariSidebarTitle38 {
    color: #35445b; font-size: 13px; font-weight: 650;
    padding: 8px 5px 4px 5px;
}
QListWidget#GlacierSafariTabs38 {
    background: transparent; border: none; outline: none;
    color: #37465c; font-size: 12px;
}
QListWidget#GlacierSafariTabs38::item {
    padding: 11px 10px; border-radius: 8px;
    margin: 2px 7px; min-height: 19px;
}
QListWidget#GlacierSafariTabs38::item:selected {
    background: #dce7f6; color: #24466c;
}
QListWidget#GlacierSafariTabs38::item:hover:!selected {
    background: #e2e8ef;
}
QPushButton#GlacierSafariBookmarks38,
QPushButton#GlacierSafariHistory38,
QPushButton#GlacierSafariGroups38 {
    background: transparent; color: #46556b; border: none;
    border-radius: 8px; padding: 7px 12px;
    text-align: left; font-size: 12px; min-height: 27px;
}
QPushButton#GlacierSafariBookmarks38:hover,
QPushButton#GlacierSafariHistory38:hover,
QPushButton#GlacierSafariGroups38:hover {
    background: #e0e8f2;
}
QSplitter#GlacierSafariSplit38::handle {
    background: #e0e5ec;
}
"""


def safari_icon38(kind):
    """Draw monochrome 24px Mac toolbar icons with correct retina DPR."""
    pic = QPixmap(48, 48)
    pic.fill(Qt.GlobalColor.transparent)
    pic.setDevicePixelRatio(2.0)
    p = QPainter(pic)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor("#52708b"), 1.7, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "sidebar":
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
        p.drawLine(9, 5, 9, 19)
        p.drawLine(5, 9, 7, 9)
        p.drawLine(5, 12, 7, 12)
    elif kind == "share":
        p.drawRoundedRect(QRectF(5, 10, 14, 11), 2, 2)
        p.drawLine(12, 3, 12, 15)
        p.drawLine(8, 7, 12, 3)
        p.drawLine(16, 7, 12, 3)
    else:
        p.end()
        raise ValueError("Unknown Safari toolbar icon")
    p.end()
    return QIcon(pic)


def install_mac_safari38(browser):
    """Add Safari's separated-toolbar layout and sidebar to live Qt widgets."""
    if sys.platform != "darwin":
        raise RuntimeError("Safari Mac layout must not run on Windows or Linux")
    if getattr(browser, "_mac_safari_ready38", False):
        raise RuntimeError("Safari presentation must be installed only once")
    if not getattr(browser, "_chrome_ui33_ready", False):
        raise RuntimeError("Install existing browser UI before Safari layout")

    central = browser.centralWidget()
    root = central.layout()
    nav_surface = browser._navigation_surface32
    nav = browser._navigation32
    tabstrip = browser.chrome_tab14.parentWidget()
    tabs = browser.tabs
    if min(root.indexOf(nav_surface), root.indexOf(tabstrip), root.indexOf(tabs)) < 0:
        raise RuntimeError("Safari layout requires the live browser controls")

    # Safari's "Separate" mode: navigation/address above tabs, unlike Chrome.
    # Reparent only lightweight toolbar widgets; WebEngine tab views stay intact.
    root.removeWidget(nav_surface)
    root.insertWidget(0, nav_surface)
    root.removeWidget(tabstrip)
    root.insertWidget(1, tabstrip)
    nav_surface.setFixedHeight(53)
    nav.setContentsMargins(13, 6, 15, 6)
    nav.setSpacing(7)
    browser._chrome_omnibox_shell33.setFixedHeight(35)
    tabstrip.setFixedHeight(39)
    tabrow = tabstrip.layout()
    if isinstance(tabrow, QHBoxLayout):
        tabrow.setContentsMargins(14, 3, 14, 2)
        tabrow.setSpacing(4)
    browser.chrome_tab14.setMinimumHeight(32)
    browser.chrome_tab14.setMaximumHeight(33)
    browser.chrome_tab14.setDrawBase(False)

    sidebar_button = QToolButton(nav_surface)
    sidebar_button.setObjectName("GlacierSafariSidebarToggle38")
    sidebar_button.setCheckable(True)
    sidebar_button.setFixedSize(32, 32)
    sidebar_button.setIcon(safari_icon38("sidebar"))
    sidebar_button.setIconSize(QSize(21, 21))
    sidebar_button.setToolTip("显示或隐藏侧边栏 (⌘⇧L)")
    sidebar_button.setAccessibleName("显示或隐藏 Safari 风格侧边栏")
    nav.insertWidget(0, sidebar_button)

    share_button = QToolButton(nav_surface)
    share_button.setObjectName("GlacierSafariShare38")
    share_button.setFixedSize(32, 32)
    share_button.setIcon(safari_icon38("share"))
    share_button.setIconSize(QSize(20, 20))
    share_button.setToolTip("复制当前网页链接")
    share_button.setAccessibleName("复制当前网页链接")
    account = getattr(browser, "_account_button26", None)
    idx = nav.indexOf(account) if account is not None else -1
    nav.insertWidget(idx if idx >= 0 else nav.count(), share_button)

    def copy_link():
        page = tabs.currentWidget()
        if page is None or not callable(getattr(page, "url", None)):
            return
        url = page.url()
        if url.isValid() and url.scheme().lower() in ("https", "http"):
            QApplication.clipboard().setText(url.toString())
            browser.statusBar().showMessage("当前网页链接已复制", 1800)

    share_button.clicked.connect(copy_link)

    side = QFrame(central)
    side.setObjectName("GlacierSafariSidebar38")
    side.setMinimumWidth(205)
    side.setMaximumWidth(340)
    side.resize(248, 600)
    side_col = QVBoxLayout(side)
    side_col.setContentsMargins(10, 12, 10, 12)
    side_col.setSpacing(7)
    title = QLabel("标签页", side)
    title.setObjectName("GlacierSafariSidebarTitle38")
    side_col.addWidget(title)
    tab_list = QListWidget(side)
    tab_list.setObjectName("GlacierSafariTabs38")
    tab_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
    side_col.addWidget(tab_list, 1)

    def action_button(title_text, object_name, callback):
        widget = QPushButton(title_text, side)
        widget.setObjectName(object_name)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.clicked.connect(callback)
        side_col.addWidget(widget)
        return widget

    # The mode-aware sidebar owns the clicks; existing QActions and the full
    # history dialog remain accessible through its footer.
    bookmarks = action_button("☆   书签", "GlacierSafariBookmarks38", lambda: None)
    history = action_button("◷   历史记录", "GlacierSafariHistory38",
                            lambda: None)
    groups = getattr(browser, "_group_menu17", None)
    if groups is not None:
        def open_groups():
            # The original group tool is in the hidden utility shelf:
            # anchor its real QMenu to the visible sidebar button instead.
            groups.popup(group_button.mapToGlobal(QPoint(0, group_button.height())))
        group_button = action_button(
            "▦   标签组", "GlacierSafariGroups38", open_groups)

    # This happens before Browser.show(); no WebEngine surface is live yet.
    tab_index = root.indexOf(tabs)
    root.removeWidget(tabs)
    splitter = QSplitter(Qt.Orientation.Horizontal, central)
    splitter.setObjectName("GlacierSafariSplit38")
    splitter.setHandleWidth(1)
    splitter.addWidget(side)
    splitter.addWidget(tabs)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    root.insertWidget(tab_index, splitter, 1)
    side.hide()

    sidebar_controller = SafariSidebar39(
        browser, side, side_col, title, tab_list, sidebar_button, splitter,
        bookmarks, history)
    sidebar_button.toggled.connect(sidebar_controller.on_visibility)
    refresh_timer = QTimer(browser)
    refresh_timer.setInterval(1800)
    refresh_timer.timeout.connect(sidebar_controller.refresh)
    refresh_timer.start()
    shortcut = QShortcut(QKeySequence("Meta+Shift+L"), browser)
    shortcut.activated.connect(sidebar_button.toggle)

    browser._safari_sidebar_button38 = sidebar_button
    browser._safari_share_button38 = share_button
    browser._safari_sidebar38 = side
    browser._safari_tab_list38 = tab_list
    browser._safari_split38 = splitter
    browser._safari_refresh_timer38 = refresh_timer
    browser._safari_shortcut38 = shortcut
    browser._safari_refresh38 = sidebar_controller.refresh
    browser._safari_controller39 = sidebar_controller
    browser._mac_safari_ready38 = True
    browser.setStyleSheet(browser.styleSheet() + "\n" + SAFARI_MAC_QSS38
                          + "\n" + SAFARI_SIDEBAR_QSS39)
