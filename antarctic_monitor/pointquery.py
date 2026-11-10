"""지도에서 고른 임의 지점의 상세 조회. 부분별로 나눠서 느린 소스가 화면을 막지 않게 합니다."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import Any, Awaitable, Callable

from . import composition, seawater
from .collectors import argo as argo_collector
from .collectors import erddap, hycom, openmeteo, windy, woa
from .collectors.base import Context
from .db import Measurement, iso, utcnow
from .i18n import msg
from .engine import parse_iso
from .geo import haversine_km
from .gridutil import find_nearest_valid, sample_nearest

ARGO_RADIUS_KM = 500.0
ARGO_WINDOW_DAYS = 45
ARGO_REPRESENTATIVE_KM = 100.0
ARGO_REPRESENTATIVE_DAYS = 10
OBS_RADIUS_KM = 400.0
TTL = {"air": 900.0, "water": 1800.0, "profile": 10800.0, "series": 3600.0}
PARTIAL_TTL = 120.0
GUARD_TIMEOUT = {"HYCOM": 120.0, "WOA23": 60.0}
DEFAULT_GUARD_TIMEOUT = 90.0


class TTLCache:
    """같은 지점을 다시 눌러도 원천 서버를 또 치지 않게 합니다. 동시 요청은 하나로 묶습니다."""

    def __init__(self):
        self._values: dict[tuple, tuple[float, Any]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    async def get(self, key: tuple, ttl: float, build: Callable[[], Awaitable[Any]]) -> Any:
        cached = self._values.get(key)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._values.get(key)
            if cached and time.monotonic() < cached[0]:
                return cached[1]
            value = await build()
            keep = min(ttl, PARTIAL_TTL) if isinstance(value, dict) and value.get("errors") else ttl
            self._values[key] = (time.monotonic() + keep, value)
            if len(self._values) > 500:
                oldest = min(self._values, key=lambda k: self._values[k][0])
                self._values.pop(oldest, None)
            return value


async def _guard(label: str, coro: Awaitable[Any], errors: list[dict], timeout: float | None = None) -> Any:
    """소스 하나가 실패하거나 답이 없어도 나머지는 보여 주고, 그 사실은 화면에 남깁니다."""
    limit = GUARD_TIMEOUT.get(label, DEFAULT_GUARD_TIMEOUT) if timeout is None else timeout
    try:
        async with asyncio.timeout(limit):
            return await coro
    except TimeoutError:
        errors.append({"source": label, "message": msg("응답 시간 초과 ({seconds}초)", seconds=int(limit))})
        return None
    except Exception as exc:
        errors.append({"source": label, "message": f"{exc}"[:240] or type(exc).__name__})
        return None


def ocean_lookup(ctx: Context, lat: float, lon: float) -> dict:
    """그 지점이 바다인지 확인하고, 아니면 가장 가까운 해양 격자를 돌려줍니다."""
    grid = ctx.store.load_grid("oisst_sst")
    if grid is None:
        return {"lat": lat, "lon": lon, "is_ocean": None, "distance_km": 0.0, "known": False}
    if sample_nearest(grid, lat, lon) is not None:
        return {"lat": lat, "lon": lon, "is_ocean": True, "distance_km": 0.0, "known": True}
    nearest = find_nearest_valid(grid, lat, lon)
    if nearest is None:
        return {"lat": lat, "lon": lon, "is_ocean": False, "distance_km": None, "known": True}
    return {
        "lat": nearest["lat"], "lon": nearest["lon"], "is_ocean": False,
        "distance_km": nearest["distance_km"], "known": True,
    }


async def air(ctx: Context, lat: float, lon: float) -> dict:
    errors: list[dict] = []
    data, observations, windy_data = await asyncio.gather(
        _guard("Open-Meteo", openmeteo.fetch_air_point(ctx, lat, lon), errors),
        asyncio.to_thread(nearest_observations, ctx, lat, lon),
        _guard("Windy", _windy_point(ctx, lat, lon), errors),
    )
    if data and data.get("current_time"):
        rows = [
            Measurement(
                source="openmeteo", dataset="gfs_global", variable=variable, kind="model", lat=lat, lon=lon,
                obs_time=data["current_time"], value=item["value"], unit=item["unit"],
            )
            for variable, item in data["current"].items()
            if item["value"] is not None
        ]
        await asyncio.to_thread(ctx.store.upsert_measurements, rows)
    return {"air": data, "observations": observations, "windy": windy_data, "errors": errors}


async def _windy_point(ctx: Context, lat: float, lon: float) -> dict:
    if not ctx.settings.windy_api_key:
        return {"configured": False}
    windy._consume(ctx, 1)
    rows = await windy.fetch_point(ctx.fetcher, ctx.settings.windy_api_key, lat, lon, "gfs")
    surface = [r for r in rows if r["level"] == "surface" and r["variable"] == "air_temperature"]
    levels = {}
    for row in rows:
        if row["variable"] == "air_temperature" and row["level"].endswith("h"):
            levels.setdefault(row["level"], row)
    now = iso()
    upcoming = next((r for r in surface if r["time"] >= now), surface[-1] if surface else None)
    return {
        "configured": True,
        "testing": ctx.settings.windy_is_testing,
        "forecast": [{"time": r["time"], "value": r["value"]} for r in surface],
        "current": upcoming,
        "pressure_profile": [
            {"pressure_hpa": float(level[:-1]), "value": row["value"]} for level, row in levels.items()
        ],
    }


def nearest_observations(ctx: Context, lat: float, lon: float) -> list[dict]:
    """가까운 METAR 기지의 최근 48시간 관측."""
    since = iso(utcnow() - timedelta(hours=48))
    rows = ctx.store.query_measurements(source="metar", variable="air_temperature", since=since)
    stations: dict[str, dict] = {}
    for row in rows:
        distance = haversine_km(lat, lon, row["lat"], row["lon"])
        if distance > OBS_RADIUS_KM:
            continue
        entry = stations.setdefault(
            row["dataset"],
            {"icao": row["dataset"], "name": row["quality"], "distance_km": round(distance, 1), "history": []},
        )
        entry["history"].append({"time": row["obs_time"], "value": row["value"]})
    return sorted(stations.values(), key=lambda s: s["distance_km"])[:3]


async def water(ctx: Context, lat: float, lon: float) -> dict:
    """표층 수온·염분을 소스별로 나란히 보여 줍니다. 육지면 가장 가까운 바다 값을 씁니다."""
    errors: list[dict] = []
    ocean = await asyncio.to_thread(ocean_lookup, ctx, lat, lon)
    query_lat, query_lon = ocean["lat"], ocean["lon"]
    oisst, mur, smos, smap, marine = await asyncio.gather(
        _guard("OISST", erddap.point_latest(ctx.fetcher, erddap.OISST, query_lat, query_lon), errors),
        _guard("MUR", erddap.point_latest(ctx.fetcher, erddap.MUR, query_lat, query_lon), errors),
        _guard("SMOS", erddap.point_latest(ctx.fetcher, erddap.SMOS, query_lat, query_lon), errors),
        _guard("SMAP", erddap.point_latest(ctx.fetcher, erddap.SMAP, query_lat, query_lon), errors),
        _guard("Open-Meteo Marine", openmeteo.fetch_marine_point(ctx.fetcher, query_lat, query_lon), errors),
    )

    def add(rows, source, label, kind, variable, unit, value, when, extra=None):
        rows.append(
            {
                "source": source, "label": label, "kind": kind, "variable": variable, "unit": unit,
                "value": value, "time": when, "note": extra,
            }
        )

    rows: list[dict] = []
    if oisst:
        add(rows, "oisst", "OISST v2.1", "analysis", "temperature", "°C", oisst["values"]["oisst_sst"], oisst["time"])
        add(rows, "oisst", msg("OISST 편차"), "analysis", "anomaly", "°C", oisst["values"]["oisst_anom"], oisst["time"], msg("1971–2000 대비"))
        add(rows, "oisst", msg("OISST 해빙"), "analysis", "ice", "", oisst["values"]["oisst_ice"], oisst["time"])
    if mur:
        add(rows, "mur", "MUR 0.01°", "analysis", "temperature", "°C", mur["values"]["mur_sst"], mur["time"],
            msg("분석 오차 ±{err}°C", err=f"{mur['values']['mur_err']:.2f}") if mur["values"].get("mur_err") is not None else None)
        add(rows, "mur", msg("MUR 해빙"), "analysis", "ice", "", mur["values"]["mur_ice"], mur["time"])
    if marine:
        add(rows, "openmeteo_marine", "Open-Meteo Marine", "model", "temperature", "°C", marine["value"], marine["time"],
            msg("육지 격자라 제외") if marine["land_cell"] else None)

    hycom_time = ctx.store.latest_grid_info().get("hycom_temp_0", {}).get("valid_time")
    hycom_salt_time = ctx.store.latest_grid_info().get("hycom_salt_0", {}).get("valid_time")
    temp_grid = await asyncio.to_thread(ctx.store.load_grid, "hycom_temp_0")
    salt_grid = await asyncio.to_thread(ctx.store.load_grid, "hycom_salt_0")
    hycom_temp = sample_nearest(temp_grid, query_lat, query_lon) if temp_grid else None
    hycom_salt = sample_nearest(salt_grid, query_lat, query_lon) if salt_grid else None
    if temp_grid:
        add(rows, "hycom", "HYCOM 0 m", "model", "temperature", "°C", hycom_temp, hycom_time, msg("지도 격자(약 0.5°)"))
    if salt_grid:
        add(rows, "hycom", "HYCOM 0 m", "model", "salinity", "PSU", hycom_salt, hycom_salt_time, msg("지도 격자(약 0.5°)"))
    if smos:
        add(rows, "smos", msg("SMOS 3일 합성"), "satellite", "salinity", "PSU", smos["values"]["smos_sss"], smos["time"],
            None if smos["values"]["smos_sss"] is not None else msg("해빙·연안 결측"))
    if smap:
        add(rows, "smap", msg("SMAP 일별"), "satellite", "salinity", "PSU", smap["values"]["smap_sss"], smap["time"],
            None if smap["values"]["smap_sss"] is not None else msg("해빙·연안 결측"))

    argo = await asyncio.to_thread(nearest_argo, ctx, query_lat, query_lon)
    representative_argo = False
    if argo:
        when = argo["obs_time"]
        note = msg("플로트 {platform}, {km} km", platform=argo["platform"], km=round(argo["distance_km"]))
        add(rows, "argo", msg("Argo 현장 관측"), "observation", "temperature", "°C", argo["surface_temp"], when, note)
        add(rows, "argo", msg("Argo 현장 관측"), "observation", "salinity", "PSU", argo["surface_salt"], when, note)
        representative_argo = is_representative(argo["distance_km"], when)
    ship = await asyncio.to_thread(nearest_ship, ctx, query_lat, query_lon)
    for item in ship:
        add(rows, "gosud", msg("선박 {ship}", ship=item["dataset"]), "observation",
            "temperature" if item["variable"] == "sea_water_temperature" else "salinity",
            item["unit"], item["value"], item["obs_time"], f"{item['distance_km']:.0f} km")

    lead = ("argo",) if representative_argo else ()
    best_temp = _first_value(rows, "temperature", (*lead, "oisst", "mur", "hycom"))
    best_salt = _first_value(rows, "salinity", (*lead, "hycom", "smos", "smap"))
    derived = seawater.derive(best_temp["value"] if best_temp else None, best_salt["value"] if best_salt else None)
    ions = composition.derive(best_salt["value"] if best_salt else None)
    await asyncio.to_thread(_store_water_rows, ctx, rows, query_lat, query_lon)
    return {
        "query": {"lat": lat, "lon": lon},
        "ocean": ocean,
        "rows": rows,
        "headline": {"temperature": best_temp, "salinity": best_salt, "derived": derived, "ions": ions},
        "errors": errors,
    }


def is_representative(distance_km: float, when: str, now=None) -> bool:
    """Argo를 그 지점의 대표값으로 쓸 수 있는지 판단합니다. 멀거나 오래된 관측은 표에만 남깁니다."""
    observed = parse_iso(when)
    if observed is None:
        return False
    return distance_km <= ARGO_REPRESENTATIVE_KM and (now or utcnow()) - observed <= timedelta(days=ARGO_REPRESENTATIVE_DAYS)


def _first_value(rows: list[dict], variable: str, order: tuple[str, ...]) -> dict | None:
    for source in order:
        for row in rows:
            if row["source"] == source and row["variable"] == variable and row["value"] is not None:
                return row
    return None


def _store_water_rows(ctx: Context, rows: list[dict], lat: float, lon: float) -> None:
    names = {
        "temperature": "sea_water_temperature", "salinity": "sea_water_salinity",
        "ice": "sea_ice_fraction", "anomaly": "sst_anomaly",
    }
    output = []
    for row in rows:
        if row["value"] is None or not row["time"] or row["source"] in ("argo", "gosud"):
            continue
        output.append(
            Measurement(
                source=row["source"], dataset="point_query", variable=names[row["variable"]], kind=row["kind"],
                lat=round(lat, 3), lon=round(lon, 3), obs_time=row["time"], value=row["value"],
                unit=row["unit"] or "fraction",
            )
        )
    ctx.store.upsert_measurements(output)


def nearest_argo(ctx: Context, lat: float, lon: float, radius_km: float = ARGO_RADIUS_KM) -> dict | None:
    since = iso(utcnow() - timedelta(days=ARGO_WINDOW_DAYS))
    best = None
    for item in ctx.store.argo_list(since=since):
        if item.get("n_levels") == 0:
            continue
        distance = haversine_km(lat, lon, item["lat"], item["lon"])
        if distance > radius_km:
            continue
        if best is None or distance < best["distance_km"]:
            best = item | {"distance_km": round(distance, 1)}
    return best


def nearest_ship(ctx: Context, lat: float, lon: float, radius_km: float = 300.0) -> list[dict]:
    since = iso(utcnow() - timedelta(days=30))
    closest: dict[str, dict] = {}
    for row in ctx.store.iter_measurements(source="gosud", since=since):
        distance = haversine_km(lat, lon, row["lat"], row["lon"])
        if distance <= radius_km and (
            row["variable"] not in closest or distance < closest[row["variable"]]["distance_km"]
        ):
            closest[row["variable"]] = row | {"distance_km": distance}
    return list(closest.values())


def _with_derived(levels: list[dict], lat: float) -> list[dict]:
    output = []
    for level in levels:
        pressure = level.get("pressure_dbar", level["depth_m"])
        output.append(level | seawater.derive(level.get("temp"), level.get("salt"), pressure))
    return output


async def _climatology(ctx: Context, lat: float, lon: float, month: int, errors: list[dict]) -> dict | None:
    """기후값은 바뀌지 않으므로 한 번 받은 격자점은 데이터베이스에 두고 다시 묻지 않습니다.

    NCEI 서버가 느리거나 멈춰 있어도 이미 본 지점은 바로 나옵니다.
    """
    key = f"woa23:{lat:.3f}:{lon:.3f}:{month:02d}"
    cached = await asyncio.to_thread(ctx.store.kv_get, key)
    if cached:
        return json.loads(cached)
    climate = await _guard("WOA23", woa.fetch_profile(ctx.fetcher, lat, lon, month), errors)
    if climate:
        await asyncio.to_thread(ctx.store.kv_set, key, json.dumps(climate))
    return climate


async def profile(ctx: Context, lat: float, lon: float) -> dict:
    """깊이별 수온·염분: 모델, 기후값, 가장 가까운 현장 관측을 함께 돌려줍니다."""
    errors: list[dict] = []
    ocean = await asyncio.to_thread(ocean_lookup, ctx, lat, lon)
    query_lat, query_lon = ocean["lat"], ocean["lon"]
    month = utcnow().month
    model, climate = await asyncio.gather(
        _guard("HYCOM", hycom.fetch_profile(ctx.fetcher, query_lat, query_lon), errors),
        _climatology(ctx, query_lat, query_lon, month, errors),
    )
    near = await asyncio.to_thread(nearest_argo, ctx, query_lat, query_lon)
    argo_series = None
    if near:
        stored = await asyncio.to_thread(ctx.store.argo_profile, near["platform"], near["cycle"])
        levels = stored.get("levels") if stored else None
        if not levels:
            fetched = await _guard(
                "Argo",
                argo_collector.fetch_levels(ctx.fetcher, near["platform"], near["cycle"], near["lat"], interactive=True),
                errors,
            )
            if fetched:
                levels = fetched[0]
                await asyncio.to_thread(ctx.store.save_argo_levels, near["platform"], near["cycle"], levels)
        if levels:
            argo_series = {
                "platform": near["platform"], "cycle": near["cycle"], "time": near["obs_time"],
                "lat": near["lat"], "lon": near["lon"], "distance_km": near["distance_km"],
                "data_mode": near["data_mode"], "position_qc": near["position_qc"],
                "levels": _with_derived(levels, near["lat"]),
            }
    if model and model["levels"]:
        rows = hycom.profile_measurements(model, None)
        await asyncio.to_thread(ctx.store.upsert_measurements, rows)
        model = model | {"levels": _with_derived(model["levels"], query_lat)}
    if climate and climate["levels"]:
        climate = climate | {"levels": _with_derived(climate["levels"], query_lat)}
    return {"ocean": ocean, "hycom": model, "woa": climate, "argo": argo_series, "errors": errors}


async def series(ctx: Context, lat: float, lon: float, days: int = 30) -> dict:
    errors: list[dict] = []
    ocean = await asyncio.to_thread(ocean_lookup, ctx, lat, lon)
    query_lat, query_lon = ocean["lat"], ocean["lon"]
    start = iso(utcnow() - timedelta(days=days))
    end_date = (utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    start_date = start[:10]
    oisst, smos, smap, era5 = await asyncio.gather(
        _guard("OISST", erddap.point_series(ctx.fetcher, erddap.OISST, query_lat, query_lon, start), errors),
        _guard("SMOS", erddap.point_series(ctx.fetcher, erddap.SMOS, query_lat, query_lon, start), errors),
        _guard("SMAP", erddap.point_series(ctx.fetcher, erddap.SMAP, query_lat, query_lon, start), errors),
        _guard("ERA5", openmeteo.fetch_era5_daily(ctx, lat, lon, start_date, end_date), errors),
    )
    return {"ocean": ocean, "days": days, "oisst": oisst or [], "smos": smos or [], "smap": smap or [], "era5": era5, "errors": errors}


DEPTH_BINS = ((0, 10), (10, 50), (50, 100), (100, 200), (200, 500), (500, 1000), (1000, 1500), (1500, 2100))


def argo_depth_stats(ctx: Context, lat_max: float = -60.0, days: int = 30) -> dict:
    """남극해 전체의 층별 수온·염분 통계. 플로트가 있는 곳만 반영하는 표본 값입니다."""
    since = iso(utcnow() - timedelta(days=days))
    bins = [{"temp": [], "salt": []} for _ in DEPTH_BINS]
    profiles = 0
    for item in ctx.store.argo_with_levels(since=since, lat_max=lat_max):
        profiles += 1
        for index, (low, high) in enumerate(DEPTH_BINS):
            temps = [lv["temp"] for lv in item["levels"] if low <= lv["depth_m"] < high and lv.get("temp") is not None]
            salts = [lv["salt"] for lv in item["levels"] if low <= lv["depth_m"] < high and lv.get("salt") is not None]
            if temps:
                bins[index]["temp"].append(sum(temps) / len(temps))
            if salts:
                bins[index]["salt"].append(sum(salts) / len(salts))

    def summary(values: list[float]) -> dict:
        if not values:
            return {"mean": None, "min": None, "max": None, "n": 0}
        return {
            "mean": round(sum(values) / len(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "n": len(values),
        }

    return {
        "profiles": profiles,
        "lat_max": lat_max,
        "days": days,
        "bins": [
            {
                "from_m": low, "to_m": high, "mid_m": (low + high) / 2,
                "temp": summary(bins[i]["temp"]), "salt": summary(bins[i]["salt"]),
            }
            for i, (low, high) in enumerate(DEPTH_BINS)
        ],
    }


