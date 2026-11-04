"""Open-Meteo: GFS(nullschool와 같은 기온 원천)·ECMWF 등 수치모델과 해양 API.

무료 한도는 하루 10,000 호출이며 지점 하나가 한 호출로 계산됩니다.
자체 예산 카운터로 한도 초과를 미리 막습니다.
"""

from __future__ import annotations

import asyncio
from datetime import date

from ..db import Measurement, utcnow
from ..gridutil import grid_from_triples
from ..http import FetchError, Fetcher, RateLimited
from ..i18n import join, msg
from ..locations import LOCATIONS, OCEAN_LOCATIONS, Location
from .base import CollectResult, Context, finite, to_iso_utc

FORECAST = "https://api.open-meteo.com/v1/forecast"
MARINE = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

CURRENT_VARIABLES = {
    "temperature_2m": ("air_temperature", "°C", "2m"),
    "apparent_temperature": ("apparent_temperature", "°C", "2m"),
    "dew_point_2m": ("dew_point", "°C", "2m"),
    "wet_bulb_temperature_2m": ("wet_bulb_temperature", "°C", "2m"),
    "surface_temperature": ("surface_temperature", "°C", "surface"),
    "relative_humidity_2m": ("relative_humidity", "%", "2m"),
    "surface_pressure": ("surface_pressure", "hPa", "surface"),
    "wind_speed_10m": ("wind_speed", "km/h", "10m"),
}
PRESSURE_LEVELS = (1000, 925, 850, 700, 500, 300, 200, 100, 50, 30, 10)
MODELS = {
    "gfs_global": "GFS",
    "ecmwf_ifs025": "ECMWF IFS",
    "icon_global": "ICON",
    "gem_global": "GEM",
    "jma_gsm": "JMA GSM",
}
# 지도용 기온 격자: 2.5° x 10°, 87.5°S–50°S + 남극점
GRID_LATS = [-87.5 + 2.5 * i for i in range(16)]
GRID_LONS = [-180.0 + 10.0 * i for i in range(36)]
GRID_CHUNK = 100
GRID_CHUNK_DELAY = 5.0


class BudgetExceeded(RateLimited):
    """오늘 쓸 수 있는 호출 예산을 다 썼습니다."""


def consume_budget(ctx: Context, calls: int, reserve: float = 0.0) -> None:
    """예산을 차감합니다. reserve만큼은 더 중요한 수집을 위해 남겨 둡니다."""
    key = f"openmeteo_budget:{date.today().isoformat()}"
    used = int(ctx.store.kv_get(key) or 0)
    limit = ctx.settings.openmeteo_daily_budget
    if used + calls > limit * (1.0 - reserve):
        raise BudgetExceeded(msg("Open-Meteo 오늘 호출 예산 소진 ({used}/{limit})", used=used, limit=limit))
    ctx.store.kv_set(key, str(used + calls))


def budget_usage(ctx: Context) -> dict:
    key = f"openmeteo_budget:{date.today().isoformat()}"
    return {"used": int(ctx.store.kv_get(key) or 0), "limit": ctx.settings.openmeteo_daily_budget}


def as_list(payload) -> list[dict]:
    return payload if isinstance(payload, list) else [payload]


async def _get(fetcher: Fetcher, url: str, params: dict, timeout: float = 90.0):
    response = await fetcher.request("GET", url, params=params, timeout=timeout)
    if response.status_code >= 400:
        try:
            reason = response.json().get("reason", response.text)
        except ValueError:
            reason = response.text
        raise FetchError(f"Open-Meteo HTTP {response.status_code}: {str(reason)[:160]}")
    return response.json()


def _coordinates(locations) -> dict:
    return {
        "latitude": ",".join(f"{loc.lat:.3f}" for loc in locations),
        "longitude": ",".join(f"{loc.lon:.3f}" for loc in locations),
        "timezone": "UTC",
    }


def parse_current(payloads: list[dict], locations: tuple[Location, ...]) -> list[Measurement]:
    rows = []
    for payload, loc in zip(payloads, locations):
        current = payload.get("current") or {}
        if not current.get("time"):
            continue
        when = to_iso_utc(current["time"])
        for key, (variable, unit, level) in CURRENT_VARIABLES.items():
            value = finite(current.get(key))
            if value is not None:
                rows.append(
                    Measurement(
                        source="openmeteo", dataset="gfs_global", variable=variable, kind="model",
                        lat=loc.lat, lon=loc.lon, obs_time=when, value=value, unit=unit, level=level,
                        location_id=loc.id,
                    )
                )
    return rows


async def collect_current(ctx: Context) -> CollectResult:
    consume_budget(ctx, len(LOCATIONS))
    params = _coordinates(LOCATIONS) | {"current": ",".join(CURRENT_VARIABLES), "models": "gfs_global"}
    payloads = as_list(await _get(ctx.fetcher, FORECAST, params))
    rows = parse_current(payloads, LOCATIONS)
    saved = ctx.store.upsert_measurements(rows)
    latest = max((r.obs_time for r in rows), default=None)
    return CollectResult(rows=saved, data_time=latest, message=msg("지점 {n}곳", n=len(payloads)))


def parse_hourly_models(payloads: list[dict], locations) -> list[Measurement]:
    rows = []
    for payload, loc in zip(payloads, locations):
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        for model in MODELS:
            series = hourly.get(f"temperature_2m_{model}")
            if not series:
                continue
            for moment, raw in zip(times, series):
                value = finite(raw)
                if value is not None:
                    rows.append(
                        Measurement(
                            source="openmeteo", dataset=model, variable="air_temperature", kind="forecast",
                            lat=loc.lat, lon=loc.lon, obs_time=to_iso_utc(moment), value=value, unit="°C",
                            level="2m", location_id=loc.id,
                        )
                    )
    return rows


async def collect_forecast(ctx: Context) -> CollectResult:
    consume_budget(ctx, len(LOCATIONS))
    params = _coordinates(LOCATIONS) | {
        "hourly": "temperature_2m",
        "models": ",".join(MODELS),
        "forecast_days": 7,
        "past_days": 1,
    }
    payloads = as_list(await _get(ctx.fetcher, FORECAST, params, timeout=180.0))
    rows = parse_hourly_models(payloads, LOCATIONS)
    saved = ctx.store.upsert_measurements(rows)
    return CollectResult(rows=saved, data_time=to_iso_utc(utcnow().strftime("%Y-%m-%dT%H:00")), message=msg("모델 {n}종", n=len(MODELS)))


def marine_value(payload: dict) -> tuple[float | None, str | None, bool]:
    """(값, 시각, 육지 격자 여부). 육지 격자에서도 -1.8 같은 값이 오므로 구분해야 합니다."""
    current = payload.get("current") or {}
    value = finite(current.get("sea_surface_temperature"))
    when = to_iso_utc(current["time"]) if current.get("time") else None
    elevation = finite(payload.get("elevation")) or 0.0
    return value, when, elevation > 0.0


async def fetch_marine_point(fetcher: Fetcher, lat: float, lon: float) -> dict:
    params = {
        "latitude": f"{lat:.3f}",
        "longitude": f"{lon:.3f}",
        "current": "sea_surface_temperature",
        "timezone": "UTC",
    }
    try:
        payload = await _get(fetcher, MARINE, params)
    except FetchError as exc:
        if "No data is available" in str(exc):
            return {"value": None, "time": None, "land_cell": True, "lat": None, "lon": None}
        raise
    value, when, land = marine_value(payload)
    return {
        "value": None if land else value,
        "time": when,
        "land_cell": land,
        "lat": payload.get("latitude"),
        "lon": payload.get("longitude"),
    }


async def collect_marine(ctx: Context) -> CollectResult:
    targets = OCEAN_LOCATIONS
    consume_budget(ctx, len(targets))
    results = await asyncio.gather(
        *(fetch_marine_point(ctx.fetcher, loc.lat, loc.lon) for loc in targets), return_exceptions=True
    )
    rows, land, failures = [], 0, []
    for loc, result in zip(targets, results):
        if isinstance(result, Exception):
            failures.append(f"{loc.id}: {result}")
            continue
        if result["land_cell"]:
            land += 1
        if result["value"] is None or not result["time"]:
            continue
        rows.append(
            Measurement(
                source="openmeteo_marine", dataset="marine", variable="sea_water_temperature", kind="model",
                lat=loc.lat, lon=loc.lon, obs_time=result["time"], value=result["value"], unit="°C",
                location_id=loc.id,
            )
        )
    if failures and not rows:
        raise FetchError(failures[0])
    saved = ctx.store.upsert_measurements(rows)
    latest = max((r.obs_time for r in rows), default=None)
    message = msg("해역 {n}곳", n=len(rows))
    if land:
        message = join(message, msg("육지 격자 제외 {n}곳", n=land))
    if failures:
        message = join(message, msg("실패 {n}곳", n=len(failures)))
    return CollectResult(rows=saved, data_time=latest, message=message)


async def collect_gfs_grid(ctx: Context) -> CollectResult:
    """GFS 2 m 기온 지도. 호출을 많이 쓰므로 일일 예산의 30%를 남겨 두고 동작합니다."""
    points = [(-90.0, 0.0)] + [(lat, lon) for lat in GRID_LATS for lon in GRID_LONS]
    consume_budget(ctx, len(points), reserve=0.3)
    triples = []
    valid_time = None
    chunks = [points[i : i + GRID_CHUNK] for i in range(0, len(points), GRID_CHUNK)]
    for index, chunk in enumerate(chunks):
        if index:
            await asyncio.sleep(GRID_CHUNK_DELAY)
        params = {
            "latitude": ",".join(f"{p[0]:.2f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.2f}" for p in chunk),
            "current": "temperature_2m",
            "models": "gfs_global",
            "timezone": "UTC",
        }
        payloads = as_list(await _get(ctx.fetcher, FORECAST, params, timeout=120.0))
        for point, payload in zip(chunk, payloads):
            current = payload.get("current") or {}
            if current.get("time"):
                valid_time = to_iso_utc(current["time"])
            value = finite(current.get("temperature_2m"))
            if point[0] == -90.0:  # 남극점은 모든 경도에서 같은 값
                triples.extend((-90.0, lon, value) for lon in GRID_LONS)
            else:
                triples.append((point[0], point[1], value))
    if valid_time is None:
        raise FetchError(msg("GFS 격자 응답에 시각이 없습니다"))
    grid = await asyncio.to_thread(grid_from_triples, "gfs_t2m", valid_time, "°C", triples)
    await asyncio.to_thread(ctx.store.save_grid, grid)
    return CollectResult(rows=len(grid.values), data_time=valid_time, message=msg("격자 {n}지점", n=len(points)))


async def fetch_air_point(ctx: Context, lat: float, lon: float) -> dict:
    """클릭한 지점의 기온 전체: 현재값, 모델별 예보, 고도별 기온."""
    consume_budget(ctx, 3)
    base = {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "timezone": "UTC"}
    pressure_vars = [f"temperature_{p}hPa" for p in PRESSURE_LEVELS]
    current, forecast, levels = await asyncio.gather(
        _get(ctx.fetcher, FORECAST, base | {"current": ",".join(CURRENT_VARIABLES), "models": "gfs_global"}),
        _get(
            ctx.fetcher, FORECAST,
            base | {"hourly": "temperature_2m", "models": ",".join(MODELS), "forecast_days": 7, "past_days": 1},
        ),
        _get(ctx.fetcher, FORECAST, base | {"current": ",".join(pressure_vars), "models": "gfs_global,ecmwf_ifs025"}),
    )
    hourly = forecast.get("hourly") or {}
    times = [to_iso_utc(t) for t in hourly.get("time", [])]
    series = []
    for model, label in MODELS.items():
        values = hourly.get(f"temperature_2m_{model}")
        if values:
            series.append({"id": model, "label": label, "values": [finite(v) for v in values]})
    profile = []
    level_current = levels.get("current") or {}
    for pressure in PRESSURE_LEVELS:
        profile.append(
            {
                "pressure_hpa": pressure,
                "gfs_global": finite(level_current.get(f"temperature_{pressure}hPa_gfs_global")),
                "ecmwf_ifs025": finite(level_current.get(f"temperature_{pressure}hPa_ecmwf_ifs025")),
            }
        )
    now_values = current.get("current") or {}
    return {
        "elevation_m": finite(current.get("elevation")),
        "grid_lat": current.get("latitude"),
        "grid_lon": current.get("longitude"),
        "current_time": to_iso_utc(now_values["time"]) if now_values.get("time") else None,
        "current": {
            CURRENT_VARIABLES[k][0]: {"value": finite(now_values.get(k)), "unit": CURRENT_VARIABLES[k][1]}
            for k in CURRENT_VARIABLES
        },
        "forecast": {"times": times, "series": series},
        "pressure_profile": profile,
        "pressure_time": to_iso_utc(level_current["time"]) if level_current.get("time") else None,
    }


async def fetch_era5_daily(ctx: Context, lat: float, lon: float, start: str, end: str) -> dict:
    consume_budget(ctx, 1)
    params = {
        "latitude": f"{lat:.3f}",
        "longitude": f"{lon:.3f}",
        "start_date": start,
        "end_date": end,
        "daily": "temperature_2m_mean,temperature_2m_min,temperature_2m_max",
        "timezone": "UTC",
    }
    daily = (await _get(ctx.fetcher, ARCHIVE, params, timeout=120.0)).get("daily") or {}
    return {
        "times": [to_iso_utc(t) for t in daily.get("time", [])],
        "mean": [finite(v) for v in daily.get("temperature_2m_mean", [])],
        "min": [finite(v) for v in daily.get("temperature_2m_min", [])],
        "max": [finite(v) for v in daily.get("temperature_2m_max", [])],
    }
