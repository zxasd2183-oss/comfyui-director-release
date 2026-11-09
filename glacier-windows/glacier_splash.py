"""Glacier unified light startup splash for Windows and macOS.

Shown while the main browser window initializes; no blocking delay and no
network access. Keep this module independent of the browser profile.
"""
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
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

    # Stylized ice peak: original geometric brand mark, drawn locally.
    center_x, center_y = width / 2, 102
    peak = QPainterPath()
    peak.moveTo(center_x - 67, center_y + 44)
    peak.lineTo(center_x - 15, center_y - 40)
    peak.lineTo(center_x + 5, center_y - 7)
    peak.lineTo(center_x + 26, center_y - 29)
    peak.lineTo(center_x + 78, center_y + 44)
    peak.closeSubpath()
    painter.fillPath(peak, QColor("#67b2d9"))
    ridge = QPainterPath()
    ridge.moveTo(center_x - 15, center_y - 40)
    ridge.lineTo(center_x + 5, center_y - 7)
    ridge.lineTo(center_x + 26, center_y - 29)
    ridge.lineTo(center_x + 10, center_y + 10)
    ridge.closeSubpath()
    painter.fillPath(ridge, QColor("#dff5ff"))
    painter.setPen(QColor("#254e68"))
    title = QFont("Arial", 33, QFont.Weight.DemiBold)
    painter.setFont(title)
    painter.drawText(0, 185, width, 55, Qt.AlignmentFlag.AlignHCenter, "Glacier")
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
    # Keep credential/network dialogs in front of the splash at first launch.
    splash.setWindowOpacity(0.0)
    splash.show()
    fade = QPropertyAnimation(splash, b"windowOpacity", splash)
    fade.setDuration(650)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutCubic)
    splash._glacier_fade = fade
    fade.start()
    QApplication.processEvents()
    return splash
