"""Uniform Glacier window/taskbar icon in source and frozen PyInstaller app."""
from pathlib import Path
import sys
from PySide6.QtGui import QIcon

def glacier_icon() -> QIcon:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return QIcon(str(root / "assets" / "GlacierBrowser.png"))
