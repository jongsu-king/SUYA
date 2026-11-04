"""저장된 데이터를 CSV로 내보냅니다. 엑셀에서 한글이 깨지지 않게 BOM을 붙입니다."""

from __future__ import annotations

import csv
from pathlib import Path

from .db import MEASUREMENT_COLUMNS, Store

ARGO_FIELDS = ("platform", "cycle", "obs_time", "lat", "lon", "data_mode", "pressure_dbar", "depth_m", "temp", "salt")


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


def export_grid(store: Store, layer: str, path: Path) -> int:
    """값이 있는 격자만 씁니다. 레이어가 없으면 ValueError."""
    grid = store.load_grid(layer)
    if grid is None:
        raise ValueError(f"아직 수집되지 않은 레이어입니다: {layer}")
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
