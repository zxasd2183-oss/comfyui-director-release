"""One Glacier window/taskbar icon in source and frozen PyInstaller applications."""
from pathlib import Path
import sys
from PySide6.QtGui import QIcon


def glacier_icon() -> QIcon:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon = QIcon(str(root / "assets" / "GlacierBrowser.png"))
    if not icon.isNull():
        return icon
    # Tests and developer runs start before CI has generated native icons.
    # Fall back to the SAME vector artwork, never an empty/OS default icon.
    svg_path = Path(__file__).resolve().parents[1] / "assets" / "glacier-browser.svg"
    if svg_path.exists():
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtGui import QImage, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(svg_path.read_bytes()))
        if renderer.isValid():
            canvas = QImage(128, 128, QImage.Format.Format_ARGB32)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter)
            painter.end()
            icon.addPixmap(QPixmap.fromImage(canvas))
    return icon
