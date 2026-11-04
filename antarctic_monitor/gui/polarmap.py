"""남극 중심 스테레오 지도 위젯. 화면 픽셀마다 역투영해 격자를 표본 추출합니다.

휠로 확대, 끌어서 이동, 더블클릭으로 원래 크기, 클릭으로 지점 선택.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..gridutil import Grid
from ..i18n import tr
from ..locations import location_label
from .format import coord_text, num, short_time
from .scales import Scale, legend_ticks
from .theme import LIGHT, Theme

LAND_FILE = Path(__file__).resolve().parent.parent / "data" / "southern-land.json"
RIM_LAT = -40.0
RING_LATS = (-80, -70, -60, -50)
MERIDIANS = range(-180, 180, 30)
PADDING = 22.0
MAX_ZOOM = 12.0
HIT_RADIUS = 8.0


def rho_of_lat(lat):
    """스테레오 투영 반지름(극에서 0). 배열과 스칼라 모두 받습니다."""
    return 2.0 * np.tan(np.radians(90.0 + np.asarray(lat, dtype=float)) / 2.0)


RHO_RIM = float(rho_of_lat(RIM_LAT))


def prepare_grid(grid: Grid) -> dict:
    values = np.array(grid.values, dtype=np.float64).reshape(len(grid.lats), len(grid.lons))
    return {
        "values": values,
        "lat0": grid.lats[0],
        "lon0": grid.lons[0],
        "dlat": (grid.lats[-1] - grid.lats[0]) / (len(grid.lats) - 1) if len(grid.lats) > 1 else 1.0,
        "dlon": (grid.lons[-1] - grid.lons[0]) / (len(grid.lons) - 1) if len(grid.lons) > 1 else 1.0,
    }


def sample_grid(prepared: dict, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """결측을 뺀 이중 선형 보간. 유효 가중치가 절반 미만이면 결측입니다."""
    values = prepared["values"]
    nlat, nlon = values.shape
    fi = (lat - prepared["lat0"]) / prepared["dlat"]
    fj = np.mod((lon - prepared["lon0"]) / prepared["dlon"], nlon)
    outside = (fi < -0.5) | (fi > nlat - 0.5)
    i0 = np.clip(np.floor(fi).astype(int), 0, nlat - 1)
    i1 = np.clip(i0 + 1, 0, nlat - 1)
    j0 = np.floor(fj).astype(int) % nlon
    j1 = (j0 + 1) % nlon
    ti = np.clip(fi - i0, 0.0, 1.0)
    tj = fj - np.floor(fj)
    total = np.zeros_like(lat, dtype=float)
    weight = np.zeros_like(lat, dtype=float)
    for ii, jj, w in (
        (i0, j0, (1 - ti) * (1 - tj)), (i0, j1, (1 - ti) * tj), (i1, j0, ti * (1 - tj)), (i1, j1, ti * tj),
    ):
        corner = values[ii, jj]
        valid = ~np.isnan(corner)
        total += np.where(valid, corner * w, 0.0)
        weight += np.where(valid, w, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = total / weight
    result[(weight < 0.5) | outside] = np.nan
    return result


class PolarMapWidget(QWidget):
    pointSelected = Signal(float, float, object)
    cursorText = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.theme: Theme = LIGHT
        self.prepared: dict | None = None
        self.scale: Scale | None = None
        self.layer_label = ""
        self.empty_text = ""
        self.locations: list[dict] = []
        self.argo: list[dict] = []
        self.show_argo = True
        self.show_locations = True
        self.selection: tuple[float, float] | None = None
        self.zoom = 1.0
        self.offset = QPointF(0.0, 0.0)
        self._press: QPointF | None = None
        self._dragging = False
        self._base: QPixmap | None = None
        self._land_rings = self._load_land()
        self._land_path: QPainterPath | None = None

    def sizeHint(self) -> QSize:
        return QSize(620, 620)

    @staticmethod
    def _load_land() -> list[np.ndarray]:
        data = json.loads(LAND_FILE.read_text(encoding="utf-8"))
        return [np.array(ring, dtype=float) for polygon in data["coordinates"] for ring in polygon]

    def _center(self) -> tuple[float, float]:
        return self.width() / 2.0 + self.offset.x(), self.height() / 2.0 + self.offset.y()

    def _pixels_per_rho(self) -> float:
        return (min(self.width(), self.height()) / 2.0 - PADDING) / RHO_RIM * self.zoom

    def project(self, lat, lon):
        """위경도를 위젯 좌표로 바꿉니다. 경도 0°가 위, 90°E가 오른쪽입니다."""
        cx, cy = self._center()
        rho = rho_of_lat(lat) * self._pixels_per_rho()
        theta = np.radians(lon)
        return cx + rho * np.sin(theta), cy - rho * np.cos(theta)

    def unproject(self, x, y):
        cx, cy = self._center()
        k = self._pixels_per_rho()
        dx, dy = (np.asarray(x, dtype=float) - cx) / k, (np.asarray(y, dtype=float) - cy) / k
        rho = np.hypot(dx, dy)
        lat = np.degrees(2.0 * np.arctan(rho / 2.0)) - 90.0
        lon = np.degrees(np.arctan2(dx, -dy))
        return lat, lon

    def rim_radius(self) -> float:
        return RHO_RIM * self._pixels_per_rho()

    def inside(self, x: float, y: float) -> bool:
        cx, cy = self._center()
        return math.hypot(x - cx, y - cy) <= self.rim_radius()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._invalidate()

    def set_layer(self, grid: Grid | None, scale: Scale | None, label: str, empty_text: str = "") -> None:
        self.prepared = prepare_grid(grid) if grid else None
        self.scale = scale
        self.layer_label = label
        self.empty_text = empty_text
        self._invalidate()

    def set_markers(self, locations: list[dict] | None = None, argo: list[dict] | None = None) -> None:
        if locations is not None:
            self.locations = locations
        if argo is not None:
            self.argo = argo
        self.update()

    def set_visibility(self, argo: bool | None = None, locations: bool | None = None) -> None:
        if argo is not None:
            self.show_argo = argo
        if locations is not None:
            self.show_locations = locations
        self.update()

    def set_selection(self, lat: float, lon: float) -> None:
        self.selection = (lat, lon)
        self.update()

    def _invalidate(self) -> None:
        self._base = None
        self._land_path = None
        self.update()

    def resizeEvent(self, event) -> None:
        self._invalidate()
        super().resizeEvent(event)

    def _render_raster(self) -> QImage | None:
        if not self.prepared or not self.scale:
            return None
        width, height = self.width(), self.height()
        xs, ys = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
        lat, lon = self.unproject(xs, ys)
        values = sample_grid(self.prepared, lat, lon)
        positions = np.clip(np.nan_to_num(self.scale.to_unit(values), nan=0.0) * 255.0, 0, 255).astype(np.uint8)
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., :3] = self.scale.lut[positions]
        rgba[..., 3] = np.where(np.isnan(values), 0, 255)
        image = QImage(rgba.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
        return image.copy()

    def _land(self) -> QPainterPath:
        if self._land_path is None:
            path = QPainterPath()
            for ring in self._land_rings:
                xs, ys = self.project(ring[:, 1], ring[:, 0])
                path.moveTo(float(xs[0]), float(ys[0]))
                for x, y in zip(xs[1:], ys[1:]):
                    path.lineTo(float(x), float(y))
                path.closeSubpath()
            self._land_path = path
        return self._land_path

    def _render_base(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QColor(self.theme.surface))
        t = self.theme
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        cx, cy = self._center()
        radius = self.rim_radius()
        disc = QPainterPath()
        disc.addEllipse(QPointF(cx, cy), radius, radius)
        painter.setClipPath(disc)
        painter.fillPath(disc, QColor(t.sea))
        land = self._land()
        painter.fillPath(land, QColor(t.land))
        image = self._render_raster()
        if image is not None:
            painter.drawImage(0, 0, image)
        painter.setPen(QPen(QColor(t.coast), 0.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(land)

        grid = QColor(t.ink)
        grid.setAlphaF(0.35)
        painter.setPen(QPen(grid, 0.5, Qt.PenStyle.DotLine))
        for lat in RING_LATS:
            ring = float(rho_of_lat(lat)) * self._pixels_per_rho()
            painter.drawEllipse(QPointF(cx, cy), ring, ring)
        inner = float(rho_of_lat(-85.0)) * self._pixels_per_rho()
        for lon in MERIDIANS:
            theta = math.radians(lon)
            painter.drawLine(
                QPointF(cx + inner * math.sin(theta), cy - inner * math.cos(theta)),
                QPointF(cx + radius * math.sin(theta), cy - radius * math.cos(theta)),
            )
        painter.setClipping(False)
        painter.setPen(QPen(QColor(t.ink), 1.0))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        self._draw_labels(painter)
        painter.end()
        return pixmap

    def _draw_labels(self, painter: QPainter) -> None:
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor(self.theme.ink))
        cx, cy = self._center()
        for lat in RING_LATS:
            x, y = self.project(lat, 180.0)
            painter.drawText(QRectF(float(x) + 2, float(y) - 13, 40, 12), Qt.AlignmentFlag.AlignLeft, f"{-lat}°S")
        if self.zoom < 1.5:
            radius = self.rim_radius() + 11
            for lon, text in ((0, "0°"), (90, "90°E"), (180, "180°"), (-90, "90°W")):
                theta = math.radians(lon)
                x, y = cx + radius * math.sin(theta), cy - radius * math.cos(theta)
                painter.drawText(QRectF(x - 22, y - 7, 44, 14), Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, event) -> None:
        if self._base is None:
            self._base = self._render_base()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._base)
        t = self.theme
        cx, cy = self._center()
        disc = QPainterPath()
        disc.addEllipse(QPointF(cx, cy), self.rim_radius(), self.rim_radius())
        painter.setClipPath(disc)
        ink, surface = QColor(t.ink), QColor(t.surface)
        if self.show_argo:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ink)
            for item in self.argo:
                x, y = self.project(item["lat"], item["lon"])
                painter.drawEllipse(QPointF(float(x), float(y)), 1.8, 1.8)
        if self.show_locations:
            painter.setPen(QPen(ink, 1.0))
            painter.setBrush(surface)
            for item in self.locations:
                x, y = self.project(item["lat"], item["lon"])
                x, y = float(x), float(y)
                if item.get("group") == "ocean":
                    painter.drawRect(QRectF(x - 3, y - 3, 6, 6))
                else:
                    painter.drawPolygon([QPointF(x, y - 4), QPointF(x + 4, y + 3), QPointF(x - 4, y + 3)])
        if self.selection:
            x, y = self.project(*self.selection)
            x, y = float(x), float(y)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ff0000"), 1.5))
            painter.drawLine(QPointF(x - 9, y), QPointF(x + 9, y))
            painter.drawLine(QPointF(x, y - 9), QPointF(x, y + 9))
        painter.setClipping(False)
        if self.empty_text:
            painter.setPen(QColor(t.ink))
            box = QRectF(self.width() * 0.2, self.height() / 2 - 16, self.width() * 0.6, 32)
            painter.fillRect(box, surface)
            painter.drawRect(box)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.empty_text)
        painter.end()

    def _nearest_marker(self, x: float, y: float) -> tuple[str, dict] | None:
        best, best_distance = None, HIT_RADIUS
        if self.show_locations:
            for item in self.locations:
                px, py = self.project(item["lat"], item["lon"])
                distance = math.hypot(float(px) - x, float(py) - y)
                if distance < best_distance:
                    best, best_distance = ("location", item), distance
        if self.show_argo:
            for item in self.argo:
                px, py = self.project(item["lat"], item["lon"])
                distance = math.hypot(float(px) - x, float(py) - y)
                if distance < best_distance:
                    best, best_distance = ("argo", item), distance
        return best

    def readout(self, x: float, y: float) -> str | None:
        """커서 위치의 좌표와 값. 상태 표시줄에 보여 줍니다."""
        if not self.inside(x, y):
            return None
        lat, lon = self.unproject(x, y)
        lat, lon = float(lat), float(lon)
        value_text = tr("결측")
        if self.prepared and self.scale:
            value = float(sample_grid(self.prepared, np.array([lat]), np.array([lon]))[0])
            if not math.isnan(value):
                unit = f" {self.scale.unit}" if self.scale.unit else ""
                value_text = f"{num(value, self.scale.digits)}{unit}"
        return f"{coord_text(lat, lon)}    {self.layer_label}: {value_text}"

    def marker_tip(self, kind: str, item: dict) -> str:
        if kind == "argo":
            return (
                f"Argo {item['platform']} #{item['cycle']}\n{short_time(item['obs_time'])}\n"
                f"T {num(item.get('surface_temp'), 2)} °C   S {num(item.get('surface_salt'), 2)} PSU"
            )
        return f"{location_label(item)}\n{coord_text(item['lat'], item['lon'])}"

    def mouseMoveEvent(self, event) -> None:
        position = event.position()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = position - self._press
            if self._dragging or delta.manhattanLength() > 4:
                self._dragging = True
                self.offset += delta
                self._press = position
                self._invalidate()
            return
        x, y = position.x(), position.y()
        text = self.readout(x, y)
        self.cursorText.emit(text or "")
        marker = self._nearest_marker(x, y) if text else None
        if marker:
            QToolTip.showText(event.globalPosition().toPoint(), self.marker_tip(*marker), self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position()
            self._dragging = False

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        was_drag, self._press = self._dragging, None
        self._dragging = False
        if was_drag:
            return
        x, y = event.position().x(), event.position().y()
        if not self.inside(x, y):
            return
        marker = self._nearest_marker(x, y)
        if marker:
            kind, item = marker
            name = f"Argo {item['platform']}" if kind == "argo" else location_label(item)
            self.pointSelected.emit(float(item["lat"]), float(item["lon"]), name)
            return
        lat, lon = self.unproject(x, y)
        self.pointSelected.emit(float(lat), float(lon), None)

    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        new_zoom = max(1.0, min(MAX_ZOOM, self.zoom * 1.2 ** steps))
        applied = new_zoom / self.zoom
        position = event.position()
        cx, cy = self._center()
        self.offset += QPointF((position.x() - cx) * (1 - applied), (position.y() - cy) * (1 - applied))
        self.zoom = new_zoom
        if self.zoom == 1.0:
            self.offset = QPointF(0.0, 0.0)
        self._invalidate()

    def mouseDoubleClickEvent(self, event) -> None:
        self.zoom = 1.0
        self.offset = QPointF(0.0, 0.0)
        self._invalidate()


class ColorBar(QWidget):
    """현재 레이어의 색상 범례."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.scale: Scale | None = None
        self.theme: Theme = LIGHT

    def set_scale(self, scale: Scale | None, theme: Theme) -> None:
        self.scale = scale
        self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:
        if not self.scale:
            return
        painter = QPainter(self)
        pixels = np.column_stack([self.scale.lut, np.full(256, 255, np.uint8)]).tobytes()
        image = QImage(pixels, 256, 1, 1024, QImage.Format.Format_RGBA8888)
        margin = 24.0
        unit_width = 44.0 if self.scale.unit else 0.0
        bar = QRectF(margin, 2, self.width() - 2 * margin - unit_width, 11)
        painter.drawImage(bar, image)
        painter.setPen(QPen(QColor(self.theme.ink), 0.8))
        painter.drawRect(bar)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        digits = 2 if self.scale.kind in ("salinity", "ice") else 1
        for at, value in legend_ticks(self.scale):
            x = bar.left() + at * bar.width()
            painter.drawLine(QPointF(x, bar.bottom()), QPointF(x, bar.bottom() + 3))
            painter.drawText(QRectF(x - 30, bar.bottom() + 3, 60, 14), Qt.AlignmentFlag.AlignCenter, num(value, digits))
        if self.scale.unit:
            painter.drawText(
                QRectF(bar.right() + 6, bar.top() - 2, unit_width, 15),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.scale.unit,
            )
        painter.end()
