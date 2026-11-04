"""지도와 차트의 색. 창 자체는 운영체제 기본 모양을 그대로 씁니다."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    dark: bool
    surface: str
    ink: str
    muted: str
    grid: str
    land: str
    coast: str
    sea: str
    error: str
    series: tuple[str, ...]


LIGHT = Theme(
    dark=False, surface="#ffffff", ink="#000000", muted="#555555", grid="#dddddd", land="#c9c9c4", coast="#222222",
    sea="#f4f4f2", error="#c00000",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"),
)
DARK = Theme(
    dark=True, surface="#1e1e1e", ink="#e8e8e8", muted="#a0a0a0", grid="#3c3c3c", land="#4a4a46", coast="#c8c8c8",
    sea="#282828", error="#ff6b6b",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"),
)

# 같은 대상은 항상 같은 색을 씁니다.
SERIES_INDEX = {
    "argo": 0, "hycom": 1, "woa": 2,
    "gfs_global": 0, "ecmwf_ifs025": 1, "icon_global": 2, "gem_global": 3, "jma_gsm": 4, "windy": 5,
    "smos": 0, "smap": 1,
}


def current_theme() -> Theme:
    palette = QApplication.palette()
    return DARK if palette.color(QPalette.ColorRole.Window).lightness() < 128 else LIGHT


def series_color(theme: Theme, key: str) -> str:
    return theme.series[SERIES_INDEX[key]]
