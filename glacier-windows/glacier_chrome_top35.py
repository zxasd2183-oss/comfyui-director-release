"""Glacier top chrome: native Windows integrated caption and balanced controls.

This module modifies only desktop Qt chrome. macOS keeps its real Apple title
bar and traffic lights; neither platform changes navigation, proxy, profiles,
download callbacks, or signed-update validation.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QEvent, QObject, QTimer, QSize, QRect, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QToolButton, QAbstractButton


TOP_CHROME_QSS35 = """
QWidget#GlacierTabStrip14 {
    background: #e1e5ec;
    border: none;
}
QTabBar#GlacierExternalTabs14 {
    background: transparent;
    border: none;
    font-size: 12px;
}
QTabBar#GlacierExternalTabs14::tab {
    background: #d4dce5;
    color: #425064;
    border: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    min-width: 160px;
    max-width: 230px;
    min-height: 29px;
    margin: 7px 3px 0 0;
    padding: 5px 15px 0 13px;
    font-weight: normal;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: #ffffff;
    color: #1f2937;
    font-weight: 500;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
    background: #edf0f5;
}
QFrame#GlacierNavigation32 {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e8edf3;
}
QFrame#GlacierOmniboxShell33 {
    background: #f0f3f7;
    border: 1px solid #eef1f6;
    border-radius: 19px;
}
QFrame#GlacierOmniboxShell33[glacierFocus="true"] {
    background: #ffffff;
    border: 2px solid #8ab4f8;
}
QPushButton#GlacierBack32, QPushButton#GlacierForward32,
QPushButton#GlacierReload32, QPushButton#GlacierBookmark14,
QToolButton#GlacierSiteInfo30, QToolButton#GlacierDownloads14,
QToolButton#GlacierHub20, QToolButton#GlacierMore14,
QToolButton#GlacierProxyStatus34, QPushButton#GlacierAccount26 {
    background: transparent;
    border: 0;
    min-width: 32px;
    min-height: 32px;
    max-width: 36px;
    max-height: 36px;
    border-radius: 18px;
    padding: 0;
}
QPushButton#GlacierBack32:hover, QPushButton#GlacierForward32:hover,
QPushButton#GlacierReload32:hover, QPushButton#GlacierBookmark14:hover,
QToolButton#GlacierSiteInfo30:hover, QToolButton#GlacierDownloads14:hover,
QToolButton#GlacierHub20:hover, QToolButton#GlacierMore14:hover,
QToolButton#GlacierProxyStatus34:hover, QPushButton#GlacierAccount26:hover {
    background: #eaf0f7;
}
QPushButton#GlacierAccount26 {
    background: #e8f0fe;
    border: none;
    border-radius: 18px;
    color: #37639d;
}
QFrame#GlacierCaptionGroup35 { background: transparent; border: none; }
QToolButton#GlacierCaptionMin35, QToolButton#GlacierCaptionMax35,
QToolButton#GlacierCaptionClose35 {
    background: transparent; border: none; border-radius: 0;
    min-width: 46px; max-width: 46px;
    min-height: 39px; max-height: 39px; padding: 0;
}
QToolButton#GlacierCaptionMin35:hover,
QToolButton#GlacierCaptionMax35:hover { background: #cfd6e1; }
QToolButton#GlacierCaptionClose35:hover { background: #e81123; }
QToolButton#GlacierCaptionMin35:pressed,
QToolButton#GlacierCaptionMax35:pressed { background: #bec8d5; }
QToolButton#GlacierCaptionClose35:pressed { background: #bf1224; }
"""


def top_icon35(kind: str, *, white: bool = False) -> QIcon:
    """Local vector-painted, high-DPI 20px symbols (no font emoji/assets)."""
    picture = QPixmap(48, 48)
    picture.fill(Qt.GlobalColor.transparent)
    picture.setDevicePixelRatio(2)
    p = QPainter(picture)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Qt already scales the painter for a pixmap with DPR=2.
    color = QColor("#ffffff" if white else "#546374")
    p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    if kind == "back":
        p.drawLine(19, 12, 5, 12)
        p.drawLine(5, 12, 11, 6)
        p.drawLine(5, 12, 11, 18)
    elif kind == "forward":
        p.drawLine(5, 12, 19, 12)
        p.drawLine(19, 12, 13, 6)
        p.drawLine(19, 12, 13, 18)
    elif kind == "reload":
        p.drawArc(5, 5, 14, 14, 45 * 16, 290 * 16)
        p.drawLine(19, 6, 19, 11)
        p.drawLine(19, 11, 14, 11)
    elif kind == "site":
        for y, x in ((7, 10), (12, 16), (17, 8)):
            p.drawLine(4, y, 20, y)
            p.setBrush(QColor("#f0f3f7"))
            p.drawEllipse(x - 2, y - 2, 4, 4)
    elif kind == "bookmark":
        shape = QPainterPath()
        pts = [(12, 3), (14.8, 9), (21, 9.4), (16, 14), (17.5, 21),
               (12, 17.6), (6.5, 21), (8, 14), (3, 9.4), (9.2, 9)]
        shape.moveTo(*pts[0])
        for xy in pts[1:]:
            shape.lineTo(*xy)
        shape.closeSubpath()
        p.drawPath(shape)
    elif kind == "download":
        p.drawLine(12, 4, 12, 16)
        p.drawLine(7, 12, 12, 17)
        p.drawLine(17, 12, 12, 17)
        p.drawLine(5, 20, 19, 20)
    elif kind == "hub":
        for x in (5, 13):
            for y in (5, 13):
                p.drawRoundedRect(QRectF(x, y, 6, 6), 1.3, 1.3)
    elif kind == "profile":
        p.drawEllipse(9, 4, 6, 6)
        p.drawArc(5, 12, 14, 9, 0, 180 * 16)
    elif kind == "menu":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        for y in (6, 12, 18):
            p.drawEllipse(QRectF(10.4, y - 1.6, 3.2, 3.2))
    elif kind == "min":
        p.drawLine(6, 12, 18, 12)
    elif kind == "max":
        p.drawRect(6, 6, 12, 12)
    elif kind == "restore":
        p.drawRect(6, 8, 10, 10)
        p.drawLine(9, 6, 18, 6)
        p.drawLine(18, 6, 18, 16)
    elif kind == "close":
        p.drawLine(7, 7, 17, 17)
        p.drawLine(17, 7, 7, 17)
    elif kind == "globe":
        p.drawEllipse(4, 4, 16, 16)
        p.drawEllipse(8, 4, 8, 16)
        p.drawLine(4, 12, 20, 12)
    elif kind == "glacier":
        peak = QPainterPath()
        peak.moveTo(2, 18)
        peak.lineTo(8.4, 7)
        peak.lineTo(11, 11.4)
        peak.lineTo(15.2, 4)
        peak.lineTo(22, 18)
        peak.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(peak, QColor("#358de9"))
        p.setPen(QPen(QColor("#59b7ef"), 1.8))
        p.drawArc(2, 15, 20, 6, 190*16, 155*16)
    else:
        p.end()
        raise ValueError("Unknown Glacier chrome icon " + kind)
    p.end()
    return QIcon(picture)


class _ResizeHandle35(QWidget):
    """Thin frameless hit zones delegate drag-resize to the operating system."""
    def __init__(self, owner, edges, cursor):
        super().__init__(owner)
        self.owner = owner
        self.edges = edges
        self.setCursor(cursor)
        self.setObjectName("GlacierResizeGrip35")
        self.setStyleSheet("background:transparent; border:0;")
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            if self.owner.windowHandle().startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)


class _WindowsCaption35(QObject):
    """Safe OS move/resize and accessible caption actions for a frameless window."""
    def __init__(self, owner, strip, controls):
        super().__init__(owner)
        self.owner = owner
        self.strip = strip
        self.controls = controls
        self.handles = []
        strip.installEventFilter(self)
        owner.installEventFilter(self)
        self._create_handles()
        self.sync_state()

    def _create_handles(self):
        QtEdge = Qt.Edge
        cursors = Qt.CursorShape
        descriptors = [
            (QtEdge.LeftEdge, cursors.SizeHorCursor),
            (QtEdge.RightEdge, cursors.SizeHorCursor),
            (QtEdge.TopEdge, cursors.SizeVerCursor),
            (QtEdge.BottomEdge, cursors.SizeVerCursor),
            (QtEdge.LeftEdge | QtEdge.TopEdge, cursors.SizeFDiagCursor),
            (QtEdge.RightEdge | QtEdge.TopEdge, cursors.SizeBDiagCursor),
            (QtEdge.LeftEdge | QtEdge.BottomEdge, cursors.SizeBDiagCursor),
            (QtEdge.RightEdge | QtEdge.BottomEdge, cursors.SizeFDiagCursor),
        ]
        for edges, cursor in descriptors:
            self.handles.append(_ResizeHandle35(self.owner, edges, cursor))
        self.place_handles()

    def place_handles(self):
        w, h = self.owner.width(), self.owner.height()
        if self.owner.isMaximized() or self.owner.isFullScreen():
            for handle in self.handles:
                handle.hide()
            return
        e, corner = 5, 9
        rects = [
            QRect(0, corner, e, max(0, h - 2*corner)),
            QRect(max(0, w-e), corner, e, max(0, h - 2*corner)),
            QRect(corner, 0, max(0, w-2*corner), e),
            QRect(corner, max(0, h-e), max(0, w-2*corner), e),
            QRect(0, 0, corner, corner),
            QRect(max(0, w-corner), 0, corner, corner),
            QRect(0, max(0, h-corner), corner, corner),
            QRect(max(0, w-corner), max(0, h-corner), corner, corner),
        ]
        for grip, rect in zip(self.handles, rects):
            grip.setGeometry(rect)
            grip.show()
            grip.raise_()

    def toggle_max(self):
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()
        QTimer.singleShot(0, self.sync_state)

    def sync_state(self):
        maximized = self.owner.isMaximized()
        btn = self.controls["max"]
        btn.setIcon(top_icon35("restore" if maximized else "max"))
        btn.setToolTip("还原窗口" if maximized else "最大化窗口")
        btn.setAccessibleName(btn.toolTip())
        self.place_handles()

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.strip:
            if kind == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                self.toggle_max()
                return True
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                handle = self.owner.windowHandle()
                if handle is not None and handle.startSystemMove():
                    return True
        if watched is self.owner and kind in (
            QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.WindowStateChange
        ):
            if kind == QEvent.Type.Resize:
                recalc = getattr(self.owner, "_resize_tabs_to_content33", None)
                if callable(recalc):
                    QTimer.singleShot(0, recalc)
            QTimer.singleShot(0, self.sync_state)
        return False


def install_top_chrome35(owner, strip, tabbar, navigation):
    """Once-only platform integration; original toolbar handlers stay wired."""
    if getattr(owner, "_glacier_top_chrome35_ready", False):
        raise RuntimeError("Glacier top chrome already installed")
    strip_layout = strip.layout()
    if not isinstance(strip_layout, QHBoxLayout):
        raise RuntimeError("Glacier tab strip does not have a horizontal layout")
    is_windows = sys.platform == "win32"
    tabbar.setIconSize(QSize(16, 16))
    tabbar.setUsesScrollButtons(True)
    tabbar.setExpanding(False)

    # Reuse original controls. An icon swap must never replace a click handler.
    buttons = (
        ("_site_button30", "site"),
        ("_hub_button20", "hub"),
        ("_account_button26", "profile"),
    )
    for attr, kind in buttons:
        widget = getattr(owner, attr, None)
        if isinstance(widget, QAbstractButton):
            widget.setIcon(top_icon35(kind))
            widget.setIconSize(QSize(19, 19))
            widget.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly) if isinstance(widget, QToolButton) else None
    for name, kind in (
        ("GlacierBack32", "back"), ("GlacierForward32", "forward"),
        ("GlacierReload32", "reload"), ("GlacierDownloads14", "download"),
        ("GlacierMore14", "menu"),
    ):
        widget = owner.findChild(QAbstractButton, name)
        if widget is not None:
            widget.setIcon(top_icon35(kind))
            widget.setIconSize(QSize(19, 19))

    def sync_tab_icons():
        pages = getattr(owner, "tabs", None)
        if pages is None:
            return
        for i in range(min(tabbar.count(), pages.count())):
            page = pages.widget(i)
            url_method = getattr(page, "url", None)
            url = url_method().toString() if callable(url_method) else ""
            local = not url or url == "about:blank" or "glacier-offline-home" in url
            if local:
                # Only alter the visible external strip; preserve underlying
                # QTabWidget's title and URL for restore/history logic.
                icon = top_icon35("glacier")
                if tabbar.tabText(i) != "新标签页":
                    tabbar.setTabText(i, "新标签页")
            else:
                icon_method = getattr(page, "icon", None)
                icon = icon_method() if callable(icon_method) else QIcon()
                if icon.isNull():
                    icon = top_icon35("globe")
            if tabbar.tabIcon(i).cacheKey() != icon.cacheKey():
                tabbar.setTabIcon(i, icon)

    owner._glacier_sync_tab_icons35 = sync_tab_icons
    owner.tabs.currentChanged.connect(lambda _: QTimer.singleShot(0, sync_tab_icons))
    icon_timer = QTimer(owner)
    icon_timer.setInterval(1800)
    icon_timer.timeout.connect(sync_tab_icons)
    icon_timer.start()
    owner._glacier_tab_icon_timer35 = icon_timer
    QTimer.singleShot(0, sync_tab_icons)

    if is_windows:
        # No extra Windows titlebar above the Chrome tab strip.
        # Production sets this flag before constructing Qt WebEngine.
        # In pure QWidget unit stubs there is no Chromium compositor.
        if not (owner.windowFlags() & Qt.WindowType.FramelessWindowHint):
            if hasattr(owner, "profile"):
                raise RuntimeError("Windows frameless flag must precede Qt WebEngine creation")
            owner.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        strip_layout.setContentsMargins(9, 3, 0, 0)
        group = QFrame(strip)
        group.setObjectName("GlacierCaptionGroup35")
        group.setFixedHeight(40)
        caption_layout = QHBoxLayout(group)
        caption_layout.setContentsMargins(0, 0, 0, 0)
        caption_layout.setSpacing(0)
        caption_buttons = {}
        for key, obj, tip in (
            ("min", "GlacierCaptionMin35", "最小化窗口"),
            ("max", "GlacierCaptionMax35", "最大化窗口"),
            ("close", "GlacierCaptionClose35", "关闭窗口"),
        ):
            button = QToolButton(group)
            button.setObjectName(obj)
            button.setIcon(top_icon35(key))
            button.setIconSize(QSize(17, 17))
            button.setFixedSize(46, 39)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setCursor(Qt.CursorShape.ArrowCursor)
            caption_layout.addWidget(button)
            caption_buttons[key] = button
        caption_buttons["min"].clicked.connect(owner.showMinimized)
        caption_buttons["close"].clicked.connect(owner.close)
        strip_layout.addWidget(group)
        caption = _WindowsCaption35(owner, strip, caption_buttons)
        caption_buttons["max"].clicked.connect(caption.toggle_max)
        owner._glacier_caption35 = caption
        owner._glacier_caption_buttons35 = caption_buttons
        owner._glacier_caption_group35 = group

    owner._glacier_top_chrome35_ready = True
    owner.setStyleSheet(owner.styleSheet() + "\n" + TOP_CHROME_QSS35)
