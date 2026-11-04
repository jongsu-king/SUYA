"""NOAA ERDDAP 격자 데이터: OISST(수온·편차·해빙), SMOS·SMAP(표층 염분), MUR(고해상도 수온)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import quote

from ..db import Measurement
from ..gridutil import Grid, grid_from_triples, sample_nearest
from ..http import FetchError, Fetcher, NoData
from ..i18n import join, msg
from ..locations import OCEAN_LOCATIONS
from .base import CollectResult, Context, finite, to_iso_utc

PFEG = "https://coastwatch.pfeg.noaa.gov/erddap"
COASTWATCH = "https://coastwatch.noaa.gov/erddap"
GRID_TIMEOUT = 240.0


@dataclass(frozen=True)
class LayerSpec:
    layer: str
    variable: str  # measurements.variable
    unit: str
    low: float
    high: float


@dataclass(frozen=True)
class GriddedProduct:
    source: str
    base: str
    dataset: str
    kind: str
    z: str  # 고도·수심 차원 선택. 없으면 빈 문자열
    lat_range: tuple[float, float]
    lon_range: tuple[float, float]
    stride: int
    layers: dict[str, LayerSpec]


OISST = GriddedProduct(
    source="oisst",
    base=PFEG,
    dataset="ncdcOisst21NrtAgg_LonPM180",
    kind="analysis",
    z="[(0.0)]",
    lat_range=(-89.875, 89.875),
    lon_range=(-179.875, 179.875),
    stride=2,
    layers={
        "sst": LayerSpec("oisst_sst", "sea_water_temperature", "°C", -3.0, 40.0),
        "anom": LayerSpec("oisst_anom", "sst_anomaly", "°C", -15.0, 15.0),
        "ice": LayerSpec("oisst_ice", "sea_ice_fraction", "fraction", 0.0, 1.0),
    },
)
# 남극해에서 관측 가능한 염분을 크게 벗어나는 위성값(해빙 오염 등)은 저장하지 않습니다.
SSS_VALID = (28.0, 37.0)
SMOS = GriddedProduct(
    source="smos",
    base=COASTWATCH,
    dataset="noaacwSMOSsss3day",
    kind="satellite",
    z="[(0.0)]",
    lat_range=(-89.875, 89.875),
    lon_range=(-179.875, 179.875),
    stride=2,
    layers={"sss": LayerSpec("smos_sss", "sea_water_salinity", "PSU", *SSS_VALID)},
)
SMAP = GriddedProduct(
    source="smap",
    base=COASTWATCH,
    dataset="noaacwSMAPsssDaily",
    kind="satellite",
    z="[(0.0)]",
    lat_range=(-89.875, 89.875),
    lon_range=(-179.875, 179.875),
    stride=2,
    layers={"sss": LayerSpec("smap_sss", "sea_water_salinity", "PSU", *SSS_VALID)},
)
MUR = GriddedProduct(
    source="mur",
    base=PFEG,
    dataset="jplMURSST41",
    kind="analysis",
    z="",
    lat_range=(-89.99, 89.99),
    lon_range=(-179.99, 180.0),
    stride=1,
    layers={
        "analysed_sst": LayerSpec("mur_sst", "sea_water_temperature", "°C", -3.0, 40.0),
        "analysis_error": LayerSpec("mur_err", "sst_uncertainty", "°C", 0.0, 10.0),
        "sea_ice_fraction": LayerSpec("mur_ice", "sea_ice_fraction", "fraction", 0.0, 1.0),
    },
)
PRODUCTS = {p.source: p for p in (OISST, SMOS, SMAP, MUR)}

MAP_LAT = (-89.875, -40.125)


def griddap_url(base: str, dataset: str, query: str) -> str:
    return f"{base}/griddap/{dataset}.json?{quote(query, safe='(),:-._')}"


def parse_table(payload: dict) -> list[dict]:
    table = payload["table"]
    columns = table["columnNames"]
    return [dict(zip(columns, row)) for row in table["rows"]]


async def fetch_rows(fetcher: Fetcher, url: str, timeout: float = 90.0) -> list[dict]:
    response = await fetcher.request("GET", url, timeout=timeout)
    text = response.text
    if response.status_code >= 400:
        lowered = text.lower()
        if "no matching results" in lowered or "outside of the variable" in lowered:
            raise NoData(msg("해당 조건의 데이터가 없습니다"))
        raise FetchError(f"ERDDAP HTTP {response.status_code}: {' '.join(text.split())[:180]}")
    return parse_table(response.json())


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], value))


async def latest_time(fetcher: Fetcher, product: GriddedProduct) -> str:
    rows = await fetch_rows(fetcher, griddap_url(product.base, product.dataset, "time[(last)]"))
    return rows[0]["time"]


def build_grid_query(product: GriddedProduct, time_value: str) -> str:
    lat = f"[({MAP_LAT[0]}):{product.stride}:({MAP_LAT[1]})]"
    lon = f"[({product.lon_range[0]}):{product.stride}:({product.lon_range[1]})]"
    return ",".join(f"{var}[({time_value})]{product.z}{lat}{lon}" for var in product.layers)


def rows_to_grids(product: GriddedProduct, rows: list[dict], time_value: str) -> list[Grid]:
    grids = []
    for variable, spec in product.layers.items():
        triples, rejected = [], 0
        for row in rows:
            value = finite(row.get(variable))
            if value is not None and not spec.low <= value <= spec.high:
                value = None
                rejected += 1
            triples.append((row["latitude"], row["longitude"], value))
        meta = {"rejected_out_of_range": rejected, "valid_range": [spec.low, spec.high]}
        grids.append(grid_from_triples(spec.layer, to_iso_utc(time_value), spec.unit, triples, meta))
    return grids


async def collect_product(ctx: Context, product: GriddedProduct) -> CollectResult:
    time_value = await latest_time(ctx.fetcher, product)
    data_time = to_iso_utc(time_value)
    token_key = f"token:{product.source}"
    if ctx.store.kv_get(token_key) == data_time:
        return CollectResult(data_time=data_time, unchanged=True, message=msg("원천 갱신 없음"))

    url = griddap_url(product.base, product.dataset, build_grid_query(product, time_value))
    rows = await fetch_rows(ctx.fetcher, url, timeout=GRID_TIMEOUT)
    grids = await asyncio.to_thread(rows_to_grids, product, rows, time_value)

    measurements: list[Measurement] = []
    summaries = []
    for grid in grids:
        stats = await asyncio.to_thread(ctx.store.save_grid, grid)
        summaries.append(msg("{layer} 유효 {pct}%", layer=grid.layer, pct=round(stats["coverage"] * 100)))
        spec = next(s for s in product.layers.values() if s.layer == grid.layer)
        for loc in OCEAN_LOCATIONS:
            value = sample_nearest(grid, loc.lat, loc.lon)
            if value is not None:
                measurements.append(
                    Measurement(
                        source=product.source, dataset=product.dataset, variable=spec.variable,
                        kind=product.kind, lat=loc.lat, lon=loc.lon, obs_time=data_time, value=value,
                        unit=spec.unit, location_id=loc.id,
                    )
                )
    saved = ctx.store.upsert_measurements(measurements)
    ctx.store.kv_set(token_key, data_time)
    return CollectResult(
        rows=sum(len(g.values) for g in grids) + saved,
        data_time=data_time,
        message=join(*summaries),
    )


async def collect_oisst(ctx: Context) -> CollectResult:
    return await collect_product(ctx, OISST)


async def collect_smos(ctx: Context) -> CollectResult:
    return await collect_product(ctx, SMOS)


async def collect_smap(ctx: Context) -> CollectResult:
    return await collect_product(ctx, SMAP)


async def point_latest(fetcher: Fetcher, product: GriddedProduct, lat: float, lon: float) -> dict | None:
    """지점의 최신값. 격자가 결측이면 값은 None으로 돌아옵니다."""
    lat_c, lon_c = _clamp(lat, product.lat_range), _clamp(lon, product.lon_range)
    query = ",".join(
        f"{var}[(last)]{product.z}[({lat_c})][({lon_c})]" for var in product.layers
    )
    try:
        rows = await fetch_rows(fetcher, griddap_url(product.base, product.dataset, query))
    except NoData:
        return None
    if not rows:
        return None
    row = rows[0]
    result = {
        "time": to_iso_utc(row["time"]),
        "lat": row["latitude"],
        "lon": row["longitude"],
        "values": {},
    }
    for variable, spec in product.layers.items():
        value = finite(row.get(variable))
        result["values"][spec.layer] = value if value is None or spec.low <= value <= spec.high else None
    return result


async def point_series(
    fetcher: Fetcher, product: GriddedProduct, lat: float, lon: float, start_iso: str
) -> list[dict]:
    lat_c, lon_c = _clamp(lat, product.lat_range), _clamp(lon, product.lon_range)
    query = ",".join(
        f"{var}[({start_iso}):1:(last)]{product.z}[({lat_c})][({lon_c})]" for var in product.layers
    )
    try:
        rows = await fetch_rows(fetcher, griddap_url(product.base, product.dataset, query), timeout=120.0)
    except NoData:
        return []
    output = []
    for row in rows:
        entry = {"time": to_iso_utc(row["time"])}
        for variable, spec in product.layers.items():
            value = finite(row.get(variable))
            entry[spec.layer] = value if value is None or spec.low <= value <= spec.high else None
        output.append(entry)
    return output
