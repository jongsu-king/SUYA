"""지도 색상 척도. 해양학에서 쓰는 cmocean 컬러맵: 수온 thermal, 염분 haline, 편차 balance, 해빙 ice."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

COLORMAP_FILE = Path(__file__).resolve().parent.parent / "data" / "colormaps.json"


@lru_cache(maxsize=1)
def _tables() -> dict[str, np.ndarray]:
    raw = json.loads(COLORMAP_FILE.read_text(encoding="utf-8"))
    return {name: np.array(table, dtype=np.uint8) for name, table in raw.items()}


@dataclass
class Scale:
    kind: str
    domain: tuple[float, ...]
    digits: int
    unit: str
    lut: np.ndarray

    def to_unit(self, values: np.ndarray) -> np.ndarray:
        if len(self.domain) == 3:  # 0을 중심으로 양쪽을 따로 늘립니다
            low, middle, high = self.domain
            return np.where(
                values < middle,
                0.5 * (values - low) / (middle - low),
                0.5 + 0.5 * (values - middle) / (high - middle),
            )
        low, high = self.domain
        return (values - low) / (high - low)


def build_scale(kind: str, stats: dict | None, unit: str) -> Scale:
    """수온은 어는점 근처(-2°C)부터 고정해 깊이끼리 비교하기 쉽게 합니다."""
    stats = stats or {}
    p02, p98 = stats.get("p02"), stats.get("p98")
    tables = _tables()
    if kind == "water_temp":
        return Scale(kind, (-2.0, float(max(4, math.ceil(p98 if p98 is not None else 12)))), 1, unit, tables["thermal"])
    if kind == "air_temp":
        low = float(min(-30, math.floor(p02 if p02 is not None else -60)))
        high = float(max(5, math.ceil(p98 if p98 is not None else 10)))
        return Scale(kind, (low, 0.0, high), 1, unit, tables["balance"])
    if kind == "anomaly":
        a = abs(p02) if p02 is not None else 2.0
        b = abs(p98) if p98 is not None else 2.0
        limit = max(1.0, math.ceil(max(a, b) * 2) / 2)
        return Scale(kind, (-limit, 0.0, limit), 1, unit, tables["balance"])
    if kind == "salinity":
        low = math.floor((p02 if p02 is not None else 33.0) * 5) / 5
        high = math.ceil((p98 if p98 is not None else 35.0) * 5) / 5
        if high - low < 0.4:
            middle = (low + high) / 2
            low, high = middle - 0.2, middle + 0.2
        return Scale(kind, (low, high), 2, unit, tables["haline"])
    return Scale(kind, (0.0, 1.0), 2, unit, tables["ice"])


def legend_ticks(scale: Scale) -> list[tuple[float, float]]:
    """(0~1 위치, 값) 목록."""
    if len(scale.domain) == 3:
        low, middle, high = scale.domain
        return [(0.0, low), (0.25, (low + middle) / 2), (0.5, middle), (0.75, (middle + high) / 2), (1.0, high)]
    low, high = scale.domain
    return [(at, low + (high - low) * at) for at in (0.0, 0.25, 0.5, 0.75, 1.0)]
