"""저장된 데이터를 CSV로 내보냅니다. 엑셀에서 한글이 깨지지 않게 BOM을 붙입니다."""

from __future__ import annotations

import csv
from pathlib import Path

from . import composition, ranges
from .db import (
    ARGO_ION_COLUMNS,
    GRID_CELL_ION_COLUMNS,
    GRID_SALINITY_UNIT,
    ION_CHECK,
    ION_COLUMNS,
    ION_MMOL_COLUMNS,
    ION_VOLUME_COLUMNS,
    MEASUREMENT_COLUMNS,
    Store,
    grid_depth,
)
from .i18n import msg

ARGO_FIELDS = ("platform", "cycle", "obs_time", "lat", "lon", "data_mode", "pressure_dbar", "depth_m", "temp", "salt")
ION_FIELDS = (*ION_COLUMNS, *ION_MMOL_COLUMNS, *ION_VOLUME_COLUMNS, ION_CHECK)


def _open(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", newline="", encoding="utf-8-sig")


def export_measurements(
    store: Store, path: Path, source: str | None = None, variable: str | None = None, since: str | None = None
) -> int:
    count = 0
    with _open(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=MEASUREMENT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in store.iter_measurements(source=source, variable=variable, since=since):
            writer.writerow(row)
            count += 1
    return count


def export_argo(store: Store, path: Path, since: str | None = None) -> int:
    count = 0
    with _open(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=ARGO_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for profile in store.argo_with_levels(since=since):
            base = {key: profile[key] for key in ("platform", "cycle", "obs_time", "lat", "lon", "data_mode")}
            for level in profile["levels"]:
                writer.writerow(base | level)
                count += 1
    return count


def export_ions(store: Store, path: Path, source: str | None = None, since: str | None = None) -> int:
    """염분에서 환산한 이온 조성 (g/kg 와 mmol/kg). 측정값이 아니라 기준 조성으로 환산한 값입니다.

    같은 자료·위치·층·시각의 수온이 있으면 1기압 밀도와 mmol/L 도 쓰고, 마지막 열은 염분 범위 검사 결과입니다.
    """
    count = 0
    with _open(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=ION_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in store.iter_ions(source=source, since=since, mmol=True, temperature=True):
            writer.writerow(row)
            count += 1
    return count


def export_argo_ions(store: Store, path: Path, since: str | None = None) -> int:
    """Argo 층마다 염분에서 환산한 이온 조성 (g/kg)."""
    count = 0
    with _open(path) as handle:
        writer = csv.DictWriter(handle, fieldnames=ARGO_ION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in store.iter_argo_level_ions(since=since):
            writer.writerow(row)
            count += 1
    return count


def export_grid(store: Store, layer: str, path: Path) -> int:
    """값이 있는 격자만 씁니다. 레이어가 없으면 ValueError."""
    grid = store.load_grid(layer)
    if grid is None:
        raise ValueError(msg("아직 수집되지 않은 레이어입니다: {layer}", layer=layer))
    count = 0
    with _open(path) as handle:
        writer = csv.writer(handle)
        writer.writerow(["valid_time", "lat", "lon", "value", "unit"])
        for i, lat in enumerate(grid.lats):
            for j, lon in enumerate(grid.lons):
                value = grid.at(i, j)
                if value is not None:
                    writer.writerow([grid.valid_time, lat, lon, value, grid.unit])
                    count += 1
    return count


def export_grid_ions(store: Store, layer: str, path: Path) -> int:
    """염분 격자의 칸마다 환산한 이온 조성 (g/kg 와 mmol/kg). 값이 있는 칸만 씁니다.

    칸별 값은 저장하지 않고 여기서 계산합니다. 마지막 열은 그 층 수심의 염분 범위 검사 결과입니다.
    칸마다 짝이 되는 수온을 맞추지 않으므로 mmol/L 은 내지 않습니다.
    레이어가 없거나 염분 레이어가 아니면 ValueError.
    """
    grid = store.load_grid(layer)
    if grid is None:
        raise ValueError(msg("아직 수집되지 않은 레이어입니다: {layer}", layer=layer))
    if grid.unit != GRID_SALINITY_UNIT:
        raise ValueError(msg("염분 레이어가 아니어서 이온으로 환산할 수 없습니다: {layer}", layer=layer))
    depth = grid.meta.get("depth_m")
    depth = grid_depth(layer) if depth is None else float(depth)
    factors = [
        composition.REFERENCE_SALINITY_FACTOR,
        *[component.grams_per_salinity for component in composition.MAJOR],
        *[component.mmol_per_salinity for component in composition.MAJOR],
    ]
    count = 0
    with _open(path) as handle:
        writer = csv.writer(handle)
        writer.writerow(GRID_CELL_ION_COLUMNS)
        for i, lat in enumerate(grid.lats):
            for j, lon in enumerate(grid.lons):
                value = grid.at(i, j)
                if not composition.usable(value):
                    continue
                writer.writerow(
                    [
                        grid.valid_time, lat, lon, depth, value, *[value * factor for factor in factors],
                        ranges.check_salinity(value, depth),
                    ]
                )
                count += 1
    return count
