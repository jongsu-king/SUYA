"""Render the application icon from the bundled coastline: Antarctica on a dark polar disc.

Writes packaging/icons/icon.png (1024 px), icon.ico and, on macOS, icon.icns.
Usage: python packaging/make_icon.py
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QRadialGradient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAND = ROOT / "antarctic_monitor" / "data" / "southern-land.json"
OUT = ROOT / "packaging" / "icons"
RIM_LAT = -52.0


def project(lat: float, lon: float, size: float) -> QPointF:
    rim = 2.0 * math.tan(math.radians(90.0 + RIM_LAT) / 2.0)
    rho = 2.0 * math.tan(math.radians(90.0 + lat) / 2.0) / rim * (size * 0.44)
    theta = math.radians(lon)
    return QPointF(size / 2 + rho * math.sin(theta), size / 2 - rho * math.cos(theta))


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    radius = size * 0.47
    center = QPointF(size / 2, size / 2)
    gradient = QRadialGradient(center, radius)
    gradient.setColorAt(0.0, QColor("#1f5fa8"))
    gradient.setColorAt(0.7, QColor("#0d366b"))
    gradient.setColorAt(1.0, QColor("#071d3a"))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor("#9ec5f4"), size * 0.012))
    painter.drawEllipse(center, radius, radius)
    clip = QPainterPath()
    clip.addEllipse(center, radius, radius)
    painter.setClipPath(clip)
    land = QPainterPath()
    for polygon in json.loads(LAND.read_text(encoding="utf-8"))["coordinates"]:
        for ring in polygon:
            if max(lat for _, lat in ring) > RIM_LAT + 4:
                continue
            land.moveTo(project(ring[0][1], ring[0][0], size))
            for lon, lat in ring[1:]:
                land.lineTo(project(lat, lon, size))
            land.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#f4f6f8"))
    painter.drawPath(land)
    painter.end()
    return image


def main() -> None:
    QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    master = render(1024)
    master.save(str(OUT / "icon.png"))
    sizes = (16, 24, 32, 48, 64, 128, 256)
    ico = [master.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) for s in sizes]
    for image, s in zip(ico, sizes):
        image.save(str(OUT / f"icon_{s}.png"))
    if not ico[-1].save(str(OUT / "icon.ico")):
        raise SystemExit("ICO write failed; is the Qt ico plugin available?")
    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as temp:
            iconset = Path(temp) / "icon.iconset"
            iconset.mkdir()
            for s in (16, 32, 128, 256, 512):
                for scale in (1, 2):
                    px = s * scale
                    name = f"icon_{s}x{s}{'@2x' if scale == 2 else ''}.png"
                    master.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(str(iconset / name))
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True)
    print(sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
