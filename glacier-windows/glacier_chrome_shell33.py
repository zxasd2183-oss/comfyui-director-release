"""Glacier Browser desktop shell 33: native Chrome-inspired geometry.

Presentation-only. Existing QWebEngine tabs, account handlers, download menus,
VLESS routing and signed updater remain owned by their original components.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QPointF, QRectF, QTimer, QEvent, QObject
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QTabBar, QToolButton

CHROME_SHELL_QSS33 = """
/* Glacier's browser chrome uses neutral surfaces; site content is untouched. */
QMainWindow, QWidget#GlacierBrowserRoot32 {
    background: #ffffff; color: #202124;
}
QWidget#GlacierTabStrip14 {
    background: #dfe3e9; border: none;
    border-bottom: 0;
}
QTabBar#GlacierExternalTabs14 {
    background: transparent; border: 0;
    color: #3c4043; font-size: 12px;
}
QTabBar#GlacierExternalTabs14::tab {
    background: #cfd4dc; color: #414750;
    border: none; border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    min-width: 106px; max-width: 216px;
    min-height: 31px; padding: 4px 15px 1px;
    margin-right: 5px; margin-top: 6px;
    font-weight: normal;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: #ffffff; color: #202124;
    border: none; font-weight: 500;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
    background: #e7ebf1;
}
QTabBar#GlacierExternalTabs14::close-button {
    border-radius: 8px;
    margin-left: 7px; width: 16px; height: 16px;
}
QTabBar#GlacierExternalTabs14::close-button:hover {
    background: #d7dce4;
}
QFrame#GlacierNavigation32 {
    background: #ffffff; border: 0;
    border-bottom: 1px solid #e5e8ed;
}
QFrame#GlacierOmniboxShell33 {
    background: #f0f2f5; border: 1px solid #f0f2f5;
    border-radius: 20px;
}
QFrame#GlacierOmniboxShell33[glacierFocus="true"] {
    background: #ffffff; border: 2px solid #8ab4f8;
}
QLineEdit#GlacierOmnibox14 {
    background: transparent; border: 0; color: #202124;
    border-radius: 0; padding: 0 5px; margin: 0;
    min-height: 30px; max-height: 35px;
    font-size: 13px; selection-background-color: #c2d7fa;
}
QLineEdit#GlacierOmnibox14:focus {
    background: transparent; border: 0; padding: 0 5px;
}
QPushButton#GlacierBack32, QPushButton#GlacierForward32,
QPushButton#GlacierReload32, QPushButton#GlacierBookmark14,
QToolButton#GlacierSiteInfo30, QToolButton#GlacierDownloads14,
QToolButton#GlacierHub20, QToolButton#GlacierMore14,
QToolButton#GlacierUtilityToggle32, QPushButton#GlacierAccount26 {
    background: transparent; border: none;
    border-radius: 18px; padding: 0;
    min-width: 32px; max-width: 38px;
    min-height: 32px; max-height: 38px;
    color: #5f6368;
}
QPushButton#GlacierBack32:hover, QPushButton#GlacierForward32:hover,
QPushButton#GlacierReload32:hover, QPushButton#GlacierBookmark14:hover,
QToolButton#GlacierSiteInfo30:hover, QToolButton#GlacierDownloads14:hover,
QToolButton#GlacierHub20:hover, QToolButton#GlacierMore14:hover,
QToolButton#GlacierUtilityToggle32:hover, QPushButton#GlacierAccount26:hover {
    background: #edf0f4;
}
QPushButton#GlacierBack32:pressed, QPushButton#GlacierForward32:pressed,
QPushButton#GlacierReload32:pressed, QToolButton#GlacierMore14:pressed {
    background: #dce3ed;
}
QPushButton#GlacierBack32:disabled, QPushButton#GlacierForward32:disabled {
    color: #b0b5bb;
}
QPushButton#GlacierAccount26 {
    background: #e6effe; border-radius: 18px;
}
QPushButton#GlacierProxyHealth29 {
    background: transparent; border: none; color: #5f6368;
    font-size: 16px; min-height: 30px; max-width: 32px; padding: 0;
}
QLabel#GlacierProxyMac32 {
    background: transparent; border: none; color: #5f6368;
    font-size: 14px; min-width: 19px; max-width: 24px; padding: 0;
}
QFrame#GlacierUtility32 {
    background: #f6f8fb; border-bottom: 1px solid #e9edf2;
}
QTabWidget::pane { background: #ffffff; border: 0; }
QMenu {
    background: #ffffff; color: #202124;
    border: 1px solid #e0e4e9; border-radius: 10px; padding: 6px;
}
QMenu::item {
    background: transparent; border-radius: 5px;
    padding: 7px 28px 7px 16px; margin: 1px 4px;
    font-size: 12px;
}
QMenu::item:selected { background: #e8f0fe; color: #174ea6; }
QMenu::separator { height: 1px; background: #eceff3; margin: 5px 10px; }
QToolTip {
    background: #30343a; color: #ffffff; border: 0;
    padding: 6px 8px; font-size: 11px;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #c5cad2; min-height: 26px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #9ca4ae; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def shell_icon33(kind):
    """Draw familiar monochrome symbols locally; keep assets resolution independent."""
    pic = QPixmap(44, 44)
    pic.fill(Qt.GlobalColor.transparent)
    p = QPainter(pic)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(QColor("#5f6368"), 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "site":
        for y, x in ((13, 17), (22, 28), (31, 19)):
            p.drawLine(QPointF(9, y), QPointF(35, y))
            p.setBrush(QColor("#f1f3f4"))
            p.drawEllipse(QRectF(x-3, y-3, 6, 6))
    elif kind == "insecure":
        p.drawEllipse(QRectF(10, 10, 24, 24))
        p.drawLine(QPointF(22, 16), QPointF(22, 24))
        p.drawPoint(QPointF(22, 29))
    elif kind == "download":
        p.drawLine(QPointF(22, 9), QPointF(22, 29))
        p.drawLine(QPointF(15, 22), QPointF(22, 29))
        p.drawLine(QPointF(29, 22), QPointF(22, 29))
        p.drawLine(QPointF(12, 33), QPointF(32, 33))
    elif kind == "extensions":
        p.drawRoundedRect(QRectF(11, 16, 22, 20), 3, 3)
        p.drawArc(QRectF(18, 9, 9, 13), 0, 180*16)
        p.drawLine(QPointF(11, 24), QPointF(8, 24))
    elif kind == "profile":
        p.drawEllipse(QRectF(17, 11, 10, 10))
        p.drawArc(QRectF(11, 21, 22, 15), 0, 180*16)
    elif kind == "close":
        p.setPen(QPen(QColor("#5f6368"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(15, 15), QPointF(29, 29))
        p.drawLine(QPointF(29, 15), QPointF(15, 29))
    elif kind == "menu":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#5f6368"))
        for y in (13, 22, 31):
            p.drawEllipse(QRectF(20, y-2, 4, 4))
    else:
        p.end()
        raise ValueError("Unsupported shell icon: " + kind)
    p.end()
    return QIcon(pic)


class _OmniboxFocusGuard33(QObject):
    """Qt does not implement CSS :focus-within; track input focus explicitly."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            active = event.type() == QEvent.Type.FocusIn
            self.shell.setProperty("glacierFocus", active)
            style = self.shell.style()
            style.unpolish(self.shell)
            style.polish(self.shell)
            self.shell.update()
        return False


class GlacierChromeShell33:
    """Reparent live controls into genuine grouped Chrome-style address row."""

    def setup_chrome_shell33(self):
        if not getattr(self, "_desktop_ui_ready32", False):
            raise RuntimeError("Install the existing desktop UI before Chrome shell")
        if getattr(self, "_chrome_ui33_ready", False):
            raise RuntimeError("Chrome shell must only be installed once")
        nav = self._navigation32
        surface = self._navigation_surface32
        strip = self.chrome_tab14.parentWidget()
        if strip is None or strip.objectName() != "GlacierTabStrip14":
            raise RuntimeError("Missing real Chrome tab strip")

        strip.setFixedHeight(44)
        strip_layout = strip.layout()
        if isinstance(strip_layout, QHBoxLayout):
            strip_layout.setContentsMargins(11, 3, 11, 0)
            strip_layout.setSpacing(4)
        brand = self.findChild(QLabel, "GlacierBrand14")
        if brand is not None:
            brand.hide()  # A second giant Glacier logo is not a browser tab.
        self.chrome_tab14.setMinimumHeight(38)
        self.chrome_tab14.setElideMode(Qt.TextElideMode.ElideRight)
        self.chrome_tab14.setExpanding(False)
        self.chrome_tab14.setUsesScrollButtons(True)

        # Chrome's + belongs immediately beside the last tab, not pinned to
        # the far right edge by an old expanding layout/spacer.
        if isinstance(strip_layout, QHBoxLayout):
            new_tab_button = None
            for i in range(strip_layout.count()):
                part = strip_layout.itemAt(i)
                button = part.widget() if part else None
                if isinstance(button, QAbstractButton) and (
                        button.text().strip() in ("+", "＋") or
                        "新标签" in button.toolTip()):
                    new_tab_button = button
                    break
            if new_tab_button is not None:
                strip_layout.removeWidget(new_tab_button)
                for i in range(strip_layout.count()-1, -1, -1):
                    piece = strip_layout.itemAt(i)
                    if piece is not None and piece.spacerItem() is not None:
                        strip_layout.takeAt(i)
                strip_layout.insertWidget(
                    strip_layout.indexOf(self.chrome_tab14)+1, new_tab_button)
                strip_layout.addStretch(1)

        def resize_tabs_to_content():
            bar = self.chrome_tab14
            # Fixed-width tab content: keep the + adjacent to the last
            # actual tab, and allow native scroll buttons when crowded.
            desired = max(124, bar.sizeHint().width() + 3)
            available = max(155, self.width()-180)
            bar.setMaximumWidth(min(desired, available))

        self._resize_tabs_to_content33 = resize_tabs_to_content

        def polish_close_buttons():
            """Replace native platform-red X tiles without changing close signals."""
            bar = self.chrome_tab14
            for i in range(bar.count()):
                for side in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide):
                    button = bar.tabButton(i, side)
                    if not isinstance(button, QAbstractButton):
                        continue
                    button.setIcon(shell_icon33("close"))
                    button.setIconSize(QSize(15, 15))
                    button.setFixedSize(20, 20)
                    button.setToolTip("关闭标签")
                    button.setStyleSheet(
                        "QAbstractButton{background:transparent;border:0;"
                        "border-radius:10px;padding:0;}"
                        "QAbstractButton:hover{background:#d8dde5;}"
                        "QAbstractButton:pressed{background:#c8d0da;}")
                    break

        self._polish_close_buttons33 = polish_close_buttons
        self.tabs.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, lambda: (
                resize_tabs_to_content(), polish_close_buttons())))
        QTimer.singleShot(0, resize_tabs_to_content)
        QTimer.singleShot(0, polish_close_buttons)

        surface.setFixedHeight(54)
        nav.setContentsMargins(12, 5, 12, 5)
        nav.setSpacing(6)

        site = self._site_button30
        address = self.address
        bookmark = self.bookmark_button
        shell = QFrame(surface)
        shell.setObjectName("GlacierOmniboxShell33")
        shell.setMinimumWidth(220)
        shell.setFixedHeight(40)
        shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inner = QHBoxLayout(shell)
        inner.setContentsMargins(7, 1, 6, 1)
        inner.setSpacing(1)
        for widget in (site, address, bookmark):
            nav.removeWidget(widget)
        site.setText("")
        site.setIcon(shell_icon33("site"))
        site.setIconSize(QSize(18, 18))
        site.setFixedSize(32, 32)
        address.setMinimumHeight(32)
        address.setMaximumHeight(35)
        address.setFrame(False)
        address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        address.setPlaceholderText("搜索或输入网址")
        bookmark.setMinimumWidth(32)
        bookmark.setMaximumWidth(36)
        bookmark.setFixedHeight(32)
        inner.addWidget(site)
        inner.addWidget(address, 1)
        inner.addWidget(bookmark)
        nav.insertWidget(3, shell, 1)
        for widget in (site, address, bookmark):
            widget.show()
        self._chrome_omnibox_shell33 = shell
        self._omnibox_focus_guard33 = _OmniboxFocusGuard33(shell)
        address.installEventFilter(self._omnibox_focus_guard33)

        for name, kind in (("GlacierDownloads14", "download"),
                           ("GlacierHub20", "extensions"),
                           ("GlacierMore14", "menu")):
            btn = self.findChild(QToolButton, name)
            if btn is not None:
                btn.setIcon(shell_icon33(kind))
                btn.setIconSize(QSize(21, 21))
                btn.setText("")
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                btn.setFixedSize(36, 36)
                # Chromium has one menu glyph; Qt's MenuButtonPopup adds an
                # unattractive second arrow alongside the three-dot icon.
                if name in ("GlacierHub20", "GlacierMore14") and btn.menu() is not None:
                    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        account = getattr(self, "_account_button26", None)
        if account is not None:
            account.setIcon(shell_icon33("profile"))
            account.setIconSize(QSize(20, 20))
            account.setMinimumWidth(36)
            account.setMaximumWidth(36)
            account.setFixedSize(36, 36)

        proxy = getattr(self, "proxy_label", None)
        if isinstance(proxy, QLabel):
            proxy.setMaximumWidth(24)
            proxy.setMinimumWidth(19)
            proxy.setToolTip(proxy.toolTip() or proxy.text())
        elif proxy is not None:
            proxy.setMinimumWidth(30)
            proxy.setMaximumWidth(30)

        # The Chrome menu owns rarely used options; no separate '工具 ▾'
        # permanently squeezes the address bar. Keep old handlers accessible.
        toggle = getattr(self, "_utility_toggle32", None)
        more = self.findChild(QToolButton, "GlacierMore14")
        if toggle is not None and more is not None and more.menu() is not None:
            nav.removeWidget(toggle)
            toggle.hide()
            menu = more.menu()

            def append_utility_action():
                # Old menu builders can clear their actions on aboutToShow.
                # Append after them, without replacing their original callbacks.
                if any(a.objectName() == "GlacierUtilityMenuAction33" for a in menu.actions()):
                    return
                menu.addSeparator()
                action = menu.addAction("显示扩展工具栏")
                action.setObjectName("GlacierUtilityMenuAction33")
                action.setCheckable(True)
                action.setChecked(toggle.isChecked())
                action.toggled.connect(toggle.setChecked)

            menu.aboutToShow.connect(append_utility_action)

        # Chrome has no permanent legacy footer. Temporary application
        # notifications still become visible as needed.
        status = self.statusBar()
        status.hide()
        status.messageChanged.connect(
            lambda message: status.setVisible(bool(message.strip())))

        self._chrome_ui33_ready = True
        refresh = getattr(self, "refresh_account_center26", None)
        if callable(refresh):
            refresh()
        self.setStyleSheet(self.styleSheet() + "\n" + CHROME_SHELL_QSS33)
        site_update = getattr(self, "update_site_info30", None)
        if callable(site_update):
            site_update()
