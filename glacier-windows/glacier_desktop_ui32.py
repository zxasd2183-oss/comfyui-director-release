"""Glacier desktop UI 32: actual two-level browser layout, not just a new theme.

The Qt WebEngine tabs, VLESS routing, account vault and original click handlers
remain exactly the same. This takes ownership of *presentation* after every
legacy extension has been initialized, so old controls cannot keep expanding
the always-visible Chrome navigation bar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
)

CHROME_DESKTOP_QSS32 = """
QMainWindow { background: #ffffff; color: #202c38; }
QWidget#GlacierBrowserRoot32 { background: #ffffff; }
QWidget#GlacierTabStrip14 {
    background: #e8edf3; border: 0;
    border-bottom: 1px solid #d9e1e9;
}
QLabel#GlacierBrand14 { color: #366b8a; font-size: 18px;
    padding: 0 7px; background: transparent; }
QTabBar#GlacierExternalTabs14 {
    background: transparent; border: none; font-size: 13px;
}
QTabBar#GlacierExternalTabs14::tab {
    background: #dce3eb; color: #536274;
    border: 1px solid #d5dee8; border-bottom: 0;
    border-top-left-radius: 12px; border-top-right-radius: 12px;
    min-width: 136px; max-width: 236px; min-height: 33px;
    padding: 3px 15px 1px; margin-top: 5px; margin-right: 5px;
}
QTabBar#GlacierExternalTabs14::tab:selected {
    background: white; color: #1e344a;
    border-color: #cbd7e4; font-weight: 600;
}
QTabBar#GlacierExternalTabs14::tab:hover:!selected {
    background: #f4f7fb; color: #283e53;
}
QFrame#GlacierNavigation32 { background: #ffffff;
    border: none; border-bottom: 1px solid #e6ebf0; }
QFrame#GlacierUtility32 { background: #f8fafc;
    border: none; border-bottom: 1px solid #e8edf3; }
QPushButton#GlacierBack32, QPushButton#GlacierForward32,
QPushButton#GlacierReload32, QPushButton#GlacierBookmark14,
QToolButton#GlacierSiteInfo30, QToolButton#GlacierDownloads14,
QToolButton#GlacierHub20, QToolButton#GlacierMore14,
QToolButton#GlacierUtilityToggle32 {
    background: transparent; border: 1px solid transparent;
    border-radius: 17px; color: #435669;
    min-width: 34px; max-width: 38px;
    min-height: 34px; max-height: 38px;
    padding: 1px; font-size: 18px;
}
QPushButton#GlacierBack32:hover, QPushButton#GlacierForward32:hover,
QPushButton#GlacierReload32:hover, QPushButton#GlacierBookmark14:hover,
QToolButton#GlacierSiteInfo30:hover, QToolButton#GlacierDownloads14:hover,
QToolButton#GlacierHub20:hover, QToolButton#GlacierMore14:hover,
QToolButton#GlacierUtilityToggle32:hover { background: #eaf0f6; }
QLineEdit#GlacierOmnibox14 {
    background: #f0f3f7; color: #273c50;
    border: 1px solid #e8edf2; border-radius: 22px;
    min-height: 42px; max-height: 44px;
    padding: 0 17px; font-size: 14px;
    selection-background-color: #b3d7e9;
}
QLineEdit#GlacierOmnibox14:focus {
    background: white; border: 2px solid #8bbbd7;
    padding-left: 16px;
}
QPushButton#GlacierAccount26 {
    background: #e7f2fa; border: 1px solid #d0e5f3;
    border-radius: 18px; color: #2f6080;
    padding: 4px 11px; min-height: 31px;
    font-size: 12px; font-weight: 600;
}
QPushButton#GlacierAccount26:hover {
    background: #d7ecf8; border-color: #a9cee4;
}
QPushButton#GlacierProxyHealth29 {
    background: #f5f8fb; border: 1px solid #e5ebf1;
    border-radius: 15px; padding: 5px 8px;
    min-height: 30px; color: #46728b; font-size: 11px;
}
QLabel#GlacierProxyMac32 { color: #557789; padding: 3px 7px; }
QToolButton#GlacierUtilityToggle32 {
    min-width: 50px; max-width: 62px; font-size: 12px;
    color: #557083; font-weight: 600;
}
QTabWidget::pane { background: white; border: 0; }
QMenu { background: white; color: #293d4e; border: 1px solid #dbe5ed;
    border-radius: 10px; padding: 5px; }
QMenu::item { padding: 8px 22px; }
QMenu::item:selected { background: #eaf3fa; color: #2e6787; }
"""

def nav_icon32(kind):
    """Paint native-resolution outline glyphs instead of platform-dependent emoji."""
    pix = QPixmap(40, 40)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#455c70"), 2.5, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == "back":
        painter.drawLine(QPointF(28, 20), QPointF(12, 20))
        painter.drawLine(QPointF(12, 20), QPointF(20, 12))
        painter.drawLine(QPointF(12, 20), QPointF(20, 28))
    elif kind == "forward":
        painter.drawLine(QPointF(12, 20), QPointF(28, 20))
        painter.drawLine(QPointF(28, 20), QPointF(20, 12))
        painter.drawLine(QPointF(28, 20), QPointF(20, 28))
    elif kind == "reload":
        painter.drawArc(QRectF(11, 11, 18, 18), 42 * 16, 302 * 16)
        painter.drawLine(QPointF(29, 13), QPointF(29, 20))
        painter.drawLine(QPointF(29, 13), QPointF(22, 13))
    else:
        raise ValueError("Unsupported navigation icon")
    painter.end()
    return QIcon(pix)


class GlacierDesktopUI32:
    """Shared, functional Chrome-style Windows/macOS two-row native toolbar."""

    def setup_desktop_ui32(self, layout, old_nav):
        central = self.centralWidget()
        if central is None or getattr(self, "_desktop_ui_ready32", False):
            raise RuntimeError("Browser UI shell can only be installed once")
        central.setObjectName("GlacierBrowserRoot32")
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tab_strip = self.chrome_tab14.parentWidget()
        if tab_strip is None or tab_strip.objectName() != "GlacierTabStrip14":
            raise RuntimeError("Chrome external tab strip must be initialized first")
        tab_strip.setMinimumHeight(43)
        strip_row = tab_strip.layout()
        if isinstance(strip_row, QHBoxLayout):
            strip_row.setContentsMargins(15, 3, 15, 0)
            strip_row.setSpacing(6)
        self.chrome_tab14.setMinimumHeight(36)
        self.chrome_tab14.setUsesScrollButtons(True)
        self.chrome_tab14.setExpanding(False)
        self.tabs.tabBar().hide()  # External strip is the one and only visible tab row.

        nav_index = next(
            (i for i in range(layout.count()) if layout.itemAt(i).layout() is old_nav), -1
        )
        if nav_index < 0:
            raise RuntimeError("Existing navigation row missing")

        # Capture only original widget instances, keeping all their signals.
        items = []
        while old_nav.count():
            piece = old_nav.takeAt(0)
            widget = piece.widget() if piece else None
            if widget is not None and widget not in items:
                items.append(widget)
        old_nav.setContentsMargins(0, 0, 0, 0)
        old_nav.setSpacing(0)

        nav_surface = QFrame(central)
        nav_surface.setObjectName("GlacierNavigation32")
        nav_surface.setMinimumHeight(58)
        nav = QHBoxLayout(nav_surface)
        nav.setContentsMargins(14, 7, 14, 7)
        nav.setSpacing(6)
        layout.insertWidget(nav_index, nav_surface)

        def nav_button(label, kind, name, tooltip):
            button = next((w for w in items
                           if isinstance(w, QPushButton) and w.text() == label), None)
            if button is None:
                raise RuntimeError("Missing original " + kind + " navigation button")
            button.setObjectName(name)
            button.setText("")
            button.setIcon(nav_icon32(kind))
            button.setIconSize(QSize(19, 19))
            button.setToolTip(tooltip)
            button.setFixedSize(38, 38)
            return button

        back = nav_button("←", "back", "GlacierBack32", "后退 (Alt+←)")
        forward = nav_button("→", "forward", "GlacierForward32", "前进 (Alt+→)")
        reload = nav_button("↻", "reload", "GlacierReload32", "重新加载 (Ctrl+R)")
        site = self._site_button30
        address = self.address
        bookmark = self.bookmark_button
        downloads = self.findChild(QToolButton, "GlacierDownloads14")
        hub = self._hub_button20
        account = self._account_button26
        more = self.findChild(QToolButton, "GlacierMore14")
        proxy = getattr(self, "proxy_label", None)
        address.setMinimumHeight(44)
        address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        primary = [w for w in (
            back, forward, reload, site, address, bookmark, downloads,
            hub, proxy, account, more
        ) if w is not None]
        if len(primary) != len(set(primary)):
            raise RuntimeError("Toolbar contains a duplicate primary widget")
        for w in primary:
            if w not in items:
                raise RuntimeError("Primary browser control absent from old toolbar")
        hidden_status = {w: w.isHidden() for w in items}
        # Everything beyond these canonical Chrome controls is preserved in a
        # collapsible extension shelf rather than filling the address row.
        utility = QFrame(central)
        utility.setObjectName("GlacierUtility32")
        utility_row = QHBoxLayout(utility)
        utility_row.setContentsMargins(14, 5, 14, 5)
        utility_row.setSpacing(7)
        utility_visible = []
        for w in items:
            if w in primary:
                continue
            utility_row.addWidget(w)
            if hidden_status[w]:
                w.hide()  # Respect the existing hidden actions/feature gates.
            else:
                utility_visible.append(w)
                w.show()
        utility_row.addStretch(1)
        utility.hide()

        # Reserve one prominent, wide, real omnibox; keep all old callbacks.
        for w in (back, forward, reload, site, address, bookmark, downloads, hub):
            if w is None:
                continue
            nav.addWidget(w, 1 if w is address else 0)
            w.show()
        if utility_visible:
            toggle = QToolButton(nav_surface)
            toggle.setObjectName("GlacierUtilityToggle32")
            toggle.setText("工具 ▾")
            toggle.setToolTip("显示或收起旧版扩展操作")
            toggle.setCheckable(True)
            toggle.toggled.connect(utility.setVisible)
            nav.addWidget(toggle)
            self._utility_toggle32 = toggle
        if proxy is not None:
            if isinstance(proxy, QLabel):
                proxy.setObjectName("GlacierProxyMac32")
                proxy.setToolTip(proxy.text())
                proxy.setMaximumWidth(90)
            else:
                # The Windows status refresh renders a 40px status dot and
                # puts the full offline/online text in the tooltip.
                proxy.setFixedWidth(42)
            nav.addWidget(proxy)
            proxy.show()
        if account is not None:
            account.setMaximumWidth(125)
            nav.addWidget(account)
            account.show()
        if more is not None:
            more.setToolTip("更多设置与浏览器操作")
            nav.addWidget(more)
            more.show()

        # Keep the utility shelf separate from the main toolbar.
        layout.insertWidget(nav_index + 2, utility)
        self._navigation32 = nav
        self._navigation_surface32 = nav_surface
        self._utility_shelf32 = utility
        self._utility_legacy32 = tuple(utility_visible)
        self._desktop_ui_ready32 = True
        self.setStyleSheet(self.styleSheet() + "\n" + CHROME_DESKTOP_QSS32)
        refresher = getattr(self, "refresh_proxy_status29", None)
        if callable(refresher):
            refresher()
