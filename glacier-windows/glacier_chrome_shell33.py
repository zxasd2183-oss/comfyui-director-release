"""Glacier Browser desktop shell 33: native Chrome-inspired geometry.

Presentation-only. Existing QWebEngine tabs, account handlers, download menus,
VLESS routing and signed updater remain owned by their original components.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QPointF, QRectF, QTimer, QObject, QEvent
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QTabBar

CHROME_SHELL_QSS33 = """
QMainWindow, QWidget#GlacierBrowserRoot32 {
    background: #ffffff; color: #202124;
}
QWidget#GlacierTabStrip14 {
    background: #dfe3eb; border: none;
    border-bottom: 0;
}
QTabBar#GlacierExternalTabs14 {
    background: transparent; border: 0;
    font-size: 12px; color: #3c4043;
}
QTabBar#GlacierExternalTabs14::tab {
    background: #d5d9e0; color: #3c4043;
    border: 0; border-top-left-radius: 13px;
    border-top-right-radius: 13px;
    min-width: 125px; max-width: 225px; min-height: 32px;
    padding: 4px 12px 1px; margin-right: 3px; margin-top: 6px;
    font-weight: normal;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: #ffffff; color: #202124;
    border: 0; font-weight: 500;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
    background: #e8ebf0;
}
QFrame#GlacierNavigation32 {
    background: #ffffff; border: 0;
    border-bottom: 1px solid #dadce0;
}
QFrame#GlacierOmniboxShell33 {
    background: #f1f3f4; border: 1px solid #f1f3f4;
    border-radius: 19px;
}
QFrame#GlacierOmniboxShell33[focused="true"] {
    background: #ffffff; border: 1px solid #8ab4f8;
}
QToolButton#GlacierTabClose33 {
    background: transparent; border: none; border-radius: 9px;
    padding: 0; min-width: 18px; max-width: 18px;
    min-height: 18px; max-height: 18px;
}
QToolButton#GlacierTabClose33:hover { background: #bdc1c6; }
QAbstractButton#GlacierNewTab33 {
    background: transparent; border: none; border-radius: 15px;
    padding: 0; min-width: 30px; max-width: 30px;
    min-height: 30px; max-height: 30px;
}
QAbstractButton#GlacierNewTab33:hover { background: #c5cbd4; }
QToolButton#GlacierMore14::menu-indicator,
QToolButton#GlacierHub20::menu-indicator {
    image: none; width: 0px; height: 0px;
}
QLineEdit#GlacierOmnibox14 {
    background: transparent; border: none; color: #202124;
    border-radius: 0; padding: 0 5px; margin: 0;
    min-height: 30px; max-height: 35px;
    font-size: 13px; selection-background-color: #aecbfa;
}
QLineEdit#GlacierOmnibox14:focus {
    background: transparent; border: none; padding: 0 5px;
}
QPushButton#GlacierBack32, QPushButton#GlacierForward32,
QPushButton#GlacierReload32, QPushButton#GlacierBookmark14,
QToolButton#GlacierSiteInfo30, QToolButton#GlacierDownloads14,
QToolButton#GlacierHub20, QToolButton#GlacierMore14,
QToolButton#GlacierUtilityToggle32, QPushButton#GlacierAccount26 {
    background: transparent; border: none;
    border-radius: 17px; padding: 0;
    min-width: 32px; max-width: 38px;
    min-height: 32px; max-height: 38px;
    color: #5f6368;
}
QPushButton#GlacierBack32:hover, QPushButton#GlacierForward32:hover,
QPushButton#GlacierReload32:hover, QPushButton#GlacierBookmark14:hover,
QToolButton#GlacierSiteInfo30:hover, QToolButton#GlacierDownloads14:hover,
QToolButton#GlacierHub20:hover, QToolButton#GlacierMore14:hover,
QToolButton#GlacierUtilityToggle32:hover, QPushButton#GlacierAccount26:hover {
    background: #e8eaed;
}
QPushButton#GlacierAccount26 {
    background: #e8f0fe; border: 1px solid #d2e3fc; border-radius: 18px;
}
QPushButton#GlacierProxyHealth29 {
    background: transparent; border: none; color: #5f6368;
    font-size: 17px; min-height: 30px; max-width: 32px; padding: 0;
}
QLabel#GlacierProxyMac32 {
    background: transparent; border: none; color: #5f6368;
    font-size: 15px; min-width: 19px; max-width: 24px;
    padding: 0;
}
QFrame#GlacierUtility32 {
    background: #f8f9fa; border-bottom: 1px solid #e8eaed;
}
QMenu { background: #ffffff; color: #202124;
    border: 1px solid #dadce0; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 4px; }
QMenu::item:selected { background: #e8f0fe; color: #202124; }
QTabWidget::pane { background: #ffffff; border: 0; }
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
        p.setPen(QPen(QColor("#5f6368"), 2.7, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawLine(QPointF(10, 10), QPointF(34, 34))
        p.drawLine(QPointF(34, 10), QPointF(10, 34))
    elif kind == "newtab":
        p.drawLine(QPointF(22, 7), QPointF(22, 37))
        p.drawLine(QPointF(7, 22), QPointF(37, 22))
    elif kind == "secure":
        p.drawRoundedRect(QRectF(13, 19, 18, 16), 3, 3)
        p.drawArc(QRectF(16, 11, 12, 16), 0, 180*16)
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


def proxy_icon33(ready):
    """Draw a crisp status dot, not a fallback-font circle or red glyph."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#188038" if ready else "#b75b4b"))
    p.drawEllipse(QRectF(10, 10, 12, 12))
    p.end()
    return QIcon(pix)


class _AddressFocus33(QObject):
    """Qt style sheets have no reliable CSS :focus-within selector.

    Follow actual focus events, then repolish only the address shell. Neither
    focus changes nor visuals may modify browser URLs or proxy settings.
    """
    def __init__(self, frame):
        super().__init__(frame)
        self.frame = frame

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            focused = event.type() == QEvent.Type.FocusIn
            if self.frame.property("focused") != focused:
                self.frame.setProperty("focused", focused)
                self.frame.style().unpolish(self.frame)
                self.frame.style().polish(self.frame)
                self.frame.update()
        return False


def _install_tab_closers33(bar):
    """Replace native platform-specific tab X glyphs (including red squares).

    Compute the tab index on click, not at creation: tabs can be reordered.
    """
    if not bar.tabsClosable():
        return
    for index in range(bar.count()):
        previous = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if previous is not None and previous.objectName() == "GlacierTabClose33":
            continue
        button = QToolButton(bar)
        button.setObjectName("GlacierTabClose33")
        button.setAutoRaise(True)
        button.setFixedSize(18, 18)
        button.setIcon(shell_icon33("close"))
        button.setIconSize(QSize(18, 18))
        button.setToolTip("关闭标签页")
        def close_this_tab(_checked=False, owned_button=button):
            current_index = next(
                (i for i in range(bar.count())
                 if bar.tabButton(i, QTabBar.ButtonPosition.RightSide) is owned_button),
                -1)
            if current_index >= 0:
                bar.tabCloseRequested.emit(current_index)
        button.clicked.connect(close_this_tab)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)


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
        _install_tab_closers33(self.chrome_tab14)
        self._polish_tab_closers33 = lambda: _install_tab_closers33(self.chrome_tab14)

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
                new_tab_button.setObjectName("GlacierNewTab33")
                new_tab_button.setText("")
                new_tab_button.setIcon(shell_icon33("newtab"))
                new_tab_button.setIconSize(QSize(20, 20))
                new_tab_button.setFixedSize(30, 30)
                new_tab_button.setToolTip("打开新标签页 (Ctrl+T)")
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
            desired = max(150, bar.sizeHint().width() + 3)
            available = max(210, self.width()-200)
            bar.setMaximumWidth(min(desired, available))

        self._resize_tabs_to_content33 = resize_tabs_to_content
        def refresh_tabs():
            _install_tab_closers33(self.chrome_tab14)
            resize_tabs_to_content()
        self.tabs.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, refresh_tabs))
        QTimer.singleShot(0, refresh_tabs)

        surface.setFixedHeight(54)
        nav.setContentsMargins(12, 5, 12, 5)
        nav.setSpacing(6)

        site = self._site_button30
        address = self.address
        bookmark = self.bookmark_button
        shell = QFrame(surface)
        shell.setObjectName("GlacierOmniboxShell33")
        shell.setProperty("focused", False)
        shell.setMinimumWidth(220)
        shell.setFixedHeight(39)
        shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inner = QHBoxLayout(shell)
        inner.setContentsMargins(6, 1, 5, 1)
        inner.setSpacing(1)
        for widget in (site, address, bookmark):
            nav.removeWidget(widget)
        site.setText("")
        site.setIcon(shell_icon33("site"))
        site.setIconSize(QSize(25, 25))
        site.setFixedSize(32, 32)
        address.setMinimumHeight(32)
        address.setMaximumHeight(35)
        address.setFrame(False)
        self._address_focus33 = _AddressFocus33(shell)
        address.installEventFilter(self._address_focus33)
        address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        address.setPlaceholderText("在 Google 中搜索或输入网址")
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

        for name, kind in (("GlacierDownloads14", "download"),
                           ("GlacierHub20", "extensions"),
                           ("GlacierMore14", "menu")):
            btn = self.findChild(QToolButton, name)
            if btn is not None:
                btn.setIcon(shell_icon33(kind))
                btn.setIconSize(QSize(28, 28))
                btn.setText("")
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                if btn.menu() is not None and name in ("GlacierHub20", "GlacierMore14"):
                    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                btn.setFixedSize(36, 36)

        account = getattr(self, "_account_button26", None)
        if account is not None:
            account.setIcon(shell_icon33("profile"))
            account.setIconSize(QSize(29, 29))
            account.setMinimumWidth(36)
            account.setMaximumWidth(36)
            account.setFixedSize(36, 36)
            account.setText("")
            account.setAccessibleName("Glacier 账号中心")

        proxy = getattr(self, "proxy_label", None)
        if isinstance(proxy, QLabel):
            # macOS uses a QLabel, unlike the clickable Windows status button.
            prior = proxy.toolTip() or proxy.text()
            proxy.setToolTip(prior)
            proxy.setAccessibleName(prior)
            ready = getattr(self, "proc", None) is not None
            proxy.setText("●")
            proxy.setAlignment(Qt.AlignmentFlag.AlignCenter)
            proxy.setStyleSheet("QLabel#GlacierProxyMac32{background:transparent;"
                                "color:" + ("#188038" if ready else "#b75b4b") +
                                ";font-size:18px;border:none;}")
            proxy.setFixedWidth(25)
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
        # The live Windows connectivity indicator must be repainted now, not
        # only at its next periodic refresh after the screenshot is taken.
        refresh_proxy = getattr(self, "refresh_proxy_status29", None)
        if callable(refresh_proxy):
            refresh_proxy()
