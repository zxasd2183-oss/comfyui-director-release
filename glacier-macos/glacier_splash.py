"""Glacier standalone boot screen and strict one-window-at-a-time handoff.

Keep splash visible until browser initialization finishes. The main window is
created while hidden, and is revealed only after the splash is fully hidden.
"""
from time import monotonic
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap, QPen
from PySide6.QtWidgets import QApplication, QSplashScreen


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

    # Same three-peak mark as the offline home and browser window icon.
    center_x, center_y = width / 2, 102
    peak = QPainterPath()
    peak.moveTo(center_x - 79, center_y + 43)
    peak.lineTo(center_x - 33, center_y - 30)
    peak.lineTo(center_x - 13, center_y + 2)
    peak.lineTo(center_x + 17, center_y - 49)
    peak.lineTo(center_x + 82, center_y + 43)
    peak.closeSubpath()
    painter.fillPath(peak, QColor("#378fe6"))
    left_snow = QPainterPath()
    left_snow.moveTo(center_x - 33, center_y - 30)
    left_snow.lineTo(center_x - 13, center_y + 2)
    left_snow.lineTo(center_x - 28, center_y - 5)
    left_snow.lineTo(center_x - 46, center_y + 13)
    left_snow.closeSubpath()
    painter.fillPath(left_snow, QColor("#d6f5ff"))
    top_snow = QPainterPath()
    top_snow.moveTo(center_x + 17, center_y - 49)
    top_snow.lineTo(center_x + 49, center_y - 6)
    top_snow.lineTo(center_x + 24, center_y - 24)
    top_snow.lineTo(center_x + 11, center_y - 6)
    top_snow.lineTo(center_x + 1, center_y - 23)
    top_snow.closeSubpath()
    painter.fillPath(top_snow, QColor("#f0fbff"))
    wave = QPainterPath()
    wave.moveTo(center_x - 83, center_y + 50)
    wave.cubicTo(center_x - 38, center_y + 30,
                 center_x + 19, center_y + 64, center_x + 84, center_y + 43)
    painter.setPen(QPen(QColor("#57b7e9"), 4))
    painter.drawPath(wave)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setPen(QColor("#193e66"))
    title = QFont("Arial", 30, QFont.Weight.DemiBold)
    painter.setFont(title)
    painter.drawText(0, 185, width, 55, Qt.AlignmentFlag.AlignHCenter, "Glacier Browser")
    painter.setPen(QColor("#60859b"))
    painter.setFont(QFont("Arial", 12))
    painter.drawText(0, 247, width, 30, Qt.AlignmentFlag.AlignHCenter,
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

