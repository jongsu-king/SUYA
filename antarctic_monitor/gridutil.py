"""위경도 격자의 표본 추출, 면적 가중 통계, 해역별 집계."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

from .geo import haversine_km, normalize_lon

SECTORS: tuple[tuple[str, str, float, float], ...] = (
    ("weddell", "웨델해", -60.0, 20.0),
    ("indian", "인도양", 20.0, 90.0),
    ("west_pacific", "서태평양", 90.0, 160.0),
    ("ross", "로스해", 160.0, -130.0),
    ("amundsen_bell", "아문젠·벨링스하우젠해", -130.0, -60.0),
)
ANTARCTIC_LAT = -60.0


@dataclass
class Grid:
    layer: str
    valid_time: str
    unit: str
    lats: list[float]
    lons: list[float]
    values: list[float | None]
    meta: dict = field(default_factory=dict)

    def at(self, i: int, j: int) -> float | None:
        return self.values[i * len(self.lons) + j]

    def as_dict(self) -> dict:
        return {
            "layer": self.layer,
            "valid_time": self.valid_time,
            "unit": self.unit,
            "lats": self.lats,
            "lons": self.lons,
            "values": self.values,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Grid":
        return cls(
            layer=data["layer"],
            valid_time=data["valid_time"],
            unit=data["unit"],
            lats=data["lats"],
            lons=data["lons"],
            values=data["values"],
            meta=data.get("meta", {}),
        )


def grid_from_triples(
    layer: str,
    valid_time: str,
    unit: str,
    triples: list[tuple[float, float, float | None]],
    meta: dict | None = None,
) -> Grid:
    """(위도, 경도, 값) 목록을 정렬된 격자로 바꿉니다. 경도는 [-180, 180)으로 맞춥니다."""
    normalized = [(lat, round(normalize_lon(lon), 4), value) for lat, lon, value in triples]
    lats = sorted({t[0] for t in normalized})
    lons = sorted({t[1] for t in normalized})
    lat_index = {v: i for i, v in enumerate(lats)}
    lon_index = {v: i for i, v in enumerate(lons)}
    values: list[float | None] = [None] * (len(lats) * len(lons))
    for lat, lon, value in normalized:
        if value is not None:
            values[lat_index[lat] * len(lons) + lon_index[lon]] = value
    return Grid(layer, valid_time, unit, lats, lons, values, meta or {})


def nearest_index(axis: list[float], value: float) -> int:
    pos = bisect.bisect_left(axis, value)
    if pos <= 0:
        return 0
    if pos >= len(axis):
        return len(axis) - 1
    return pos if axis[pos] - value < value - axis[pos - 1] else pos - 1


def sample_nearest(grid: Grid, lat: float, lon: float) -> float | None:
    """가장 가까운 격자의 값. 격자 간격을 벗어난 지점이면 None."""
    if not grid.lats or not grid.lons:
        return None
    i = nearest_index(grid.lats, lat)
    spacing = abs(grid.lats[1] - grid.lats[0]) if len(grid.lats) > 1 else 1.0
    if abs(grid.lats[i] - lat) > spacing:
        return None
    return grid.at(i, nearest_index(grid.lons, normalize_lon(lon)))


def find_nearest_valid(grid: Grid, lat: float, lon: float, max_km: float = 2000.0) -> dict | None:
    """값이 있는 가장 가까운 격자를 찾습니다. 육지 지점에서 바다 값을 찾을 때 씁니다."""
    best: dict | None = None
    nlon = len(grid.lons)
    for i, grid_lat in enumerate(grid.lats):
        lat_km = abs(grid_lat - lat) * 111.2
        if lat_km > max_km or (best and lat_km > best["distance_km"]):
            continue
        offset = i * nlon
        for j, grid_lon in enumerate(grid.lons):
            value = grid.values[offset + j]
            if value is None:
                continue
            distance = haversine_km(lat, lon, grid_lat, grid_lon)
            if distance <= max_km and (best is None or distance < best["distance_km"]):
                best = {"lat": grid_lat, "lon": grid_lon, "value": value, "distance_km": round(distance, 1)}
    return best


def _in_sector(lon: float, west: float, east: float) -> bool:
    if west < east:
        return west <= lon < east
    return lon >= west or lon < east


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return math.nan
    index = fraction * (len(sorted_values) - 1)
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low)


def grid_stats(grid: Grid, lat_limit: float = ANTARCTIC_LAT) -> dict:
    """위도 lat_limit 이남의 면적 가중 평균과 범위, 해역별 평균을 계산합니다."""
    weighted = 0.0
    weight_sum = 0.0
    total_cells = 0
    collected: list[float] = []
    every_value: list[float] = []
    sectors = {key: [0.0, 0.0, 0] for key, *_ in SECTORS}
    nlon = len(grid.lons)
    for i, lat in enumerate(grid.lats):
        weight = math.cos(math.radians(lat))
        offset = i * nlon
        for j, lon in enumerate(grid.lons):
            value = grid.values[offset + j]
            if value is not None:
                every_value.append(value)
            if lat > lat_limit:
                continue
            total_cells += 1
            if value is None:
                continue
            collected.append(value)
            weighted += value * weight
            weight_sum += weight
            for key, _, west, east in SECTORS:
                if _in_sector(lon, west, east):
                    bucket = sectors[key]
                    bucket[0] += value * weight
                    bucket[1] += weight
                    bucket[2] += 1
                    break
    collected.sort()
    every_value.sort()
    return {
        "lat_limit": lat_limit,
        "mean": round(weighted / weight_sum, 3) if weight_sum else None,
        "min": round(collected[0], 3) if collected else None,
        "max": round(collected[-1], 3) if collected else None,
        "valid_cells": len(collected),
        "total_cells": total_cells,
        "coverage": round(len(collected) / total_cells, 3) if total_cells else 0.0,
        "p02": round(_percentile(every_value, 0.02), 3) if every_value else None,
        "p98": round(_percentile(every_value, 0.98), 3) if every_value else None,
        "sectors": {
            key: {
                "mean": round(bucket[0] / bucket[1], 3) if bucket[1] else None,
                "valid_cells": bucket[2],
            }
            for key, bucket in sectors.items()
        },
    }
