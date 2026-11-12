"""Glacier standalone boot screen and strict one-window-at-a-time handoff.

Keep splash visible until browser initialization finishes. The main window is
created while hidden, and is revealed only after the splash is fully hidden.
"""
from time import monotonic
from PySide6.QtCore import Qt, QTimer, QByteArray, QRectF
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtSvg import QSvgRenderer
from glacier_brand35 import GLACIER_BRAND_SVG35


def show_glacier_splash(version):
    width, height = 600, 345
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#f4fafe"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    background = QLinearGradient(0, 0, width, height)
    background.setColorAt(0, QColor("#ffffff"))
    background.setColorAt(0.6, QColor("#edf7fe"))
    background.setColorAt(1, QColor("#d9edf9"))
    painter.fillRect(0, 0, width, height, background)

    # The SAME vector wordmark as the offline new-tab page. No emoji,
    # platform font fallback or separate hand-drawn title.
    vector = QSvgRenderer(QByteArray(GLACIER_BRAND_SVG35.encode("utf-8")))
    if not vector.isValid():
        painter.end()
        raise RuntimeError("Glacier vector brand logo failed to load")
    vector.render(painter, QRectF(89, 80, 422, 90))
    painter.setPen(QColor("#60859b"))
    painter.setFont(QFont("Arial", 12))
    painter.drawText(0, 214, width, 30, Qt.AlignmentFlag.AlignHCenter,
                     "冰川浏览器  ·  安全 · 纯净 · 自由")
    painter.setPen(QColor("#829aaa"))
    painter.setFont(QFont("Arial", 10))
    painter.drawText(0, 298, width, 25, Qt.AlignmentFlag.AlignHCenter,
                     "正在初始化浏览器  ·  " + str(version))
    painter.end()
    splash = QSplashScreen(canvas)
    # Paint the separate startup window BEFORE potentially blocking proxy and
    # Qt WebEngine initialization. Never show the browser behind this splash.
    splash.show()
    splash._glacier_started = monotonic()
    QApplication.processEvents()
    return splash


def reveal_browser_after_splash(splash, browser, *, min_visible_ms=850,
                                on_reveal=None):
    """Complete startup in strict order: splash hides -> browser shows.

    This callback runs once on Qt's main thread after Browser.__init__ finished.
    A short minimum makes very fast launches visually distinguishable, but
    slow launches are never delayed beyond their actual initialization.
    """
    if browser.isVisible():
        raise RuntimeError("Browser must stay hidden during the startup splash")
    if getattr(splash, "_glacier_reveal_pending", False):
        raise RuntimeError("Splash handoff already scheduled")
    splash._glacier_reveal_pending = True
    elapsed_ms = (monotonic() - getattr(splash, "_glacier_started", monotonic())) * 1000
    remaining_ms = max(0, int(min_visible_ms - elapsed_ms))

    def reveal():
        if browser.isVisible():
            raise RuntimeError("Browser appeared before splash was dismissed")
        splash.hide()
        QApplication.processEvents()  # Flush the hide before showing the app.
        browser.show()
        splash.close()
        if callable(on_reveal):
            on_reveal()

    # Preserve a live Python callback until Qt fires the one-shot timer.
    splash._glacier_reveal_callback = reveal
    QTimer.singleShot(remaining_ms, reveal)
    return remaining_ms

