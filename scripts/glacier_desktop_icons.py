"""Render one Glacier desktop brand SVG to native Windows and macOS formats.

Run after installing PySide6: python scripts/glacier_desktop_icons.py windows|macos.
Icons are built deterministically by the packaging CI, not fetched at runtime.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "glacier-browser.svg"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MAC_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}

def renderer():
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer
    out = QSvgRenderer(QByteArray(SVG.read_bytes()))
    if not out.isValid():
        raise RuntimeError("Glacier SVG could not be rendered")
    return out

def png(size: int, svg_renderer) -> bytes:
    from PySide6.QtCore import Qt, QBuffer, QIODevice
    from PySide6.QtGui import QImage, QPainter
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    svg_renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise RuntimeError(f"Could not encode Glacier icon at {size} px")
    return bytes(buffer.data())

def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    if not images:
        raise ValueError("No icon sizes")
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = []
    payload = []
    for size, blob in images:
        if size < 1 or size > 256 or not blob.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid ICO embedded PNG")
        entries.append(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                   size if size < 256 else 0, 0, 0, 1, 32,
                                   len(blob), offset))
        payload.append(blob)
        offset += len(blob)
    path.write_bytes(header + b"".join(entries) + b"".join(payload))

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=("windows", "macos"))
    args = parser.parse_args()
    dest = ROOT / ("glacier-windows" if args.platform == "windows" else "glacier-macos") / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    source = renderer()
    (dest / "GlacierBrowser.png").write_bytes(png(1024, source))
    if args.platform == "windows":
        write_ico(dest / "GlacierBrowser.ico", [(size, png(size, source)) for size in ICO_SIZES])
    else:
        iconset = dest / "GlacierBrowser.iconset"
        iconset.mkdir(exist_ok=True)
        for name, size in MAC_SIZES.items():
            (iconset / name).write_bytes(png(size, source))
        subprocess.run(["iconutil", "-c", "icns", "--output", str(dest / "GlacierBrowser.icns"), str(iconset)], check=True)
    print(f"Glacier desktop {args.platform} icons generated in {dest}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
