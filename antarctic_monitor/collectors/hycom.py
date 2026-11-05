"""HYCOM ESPC-D-V02: 전 층 수온·염분 모델 (1/12°, 3시간 간격, 40개 층).

위성이 닿지 않는 해빙 아래와 심층까지 빈틈없는 값을 주는 유일한 공개 소스입니다.
tds 호스트가 일부 요청에 500을 돌려줘서 ncss 호스트를 우선 쓰고 실패하면 넘어갑니다.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone

from ..db import Measurement, iso, utcnow
from ..gridutil import grid_from_triples, sample_nearest
from ..http import FetchError, Fetcher
from ..i18n import join, msg
from ..locations import OCEAN_LOCATIONS
from .base import CollectResult, Context, finite, in_range

HOSTS = ("ncss.hycom.org", "tds.hycom.org")
VARIABLES = {
    "water_temp": {"path": "FMRC_ESPC-D-V02_t3z/FMRC_ESPC-D-V02_t3z_best.ncd", "low": -3.0, "high": 40.0, "unit": "°C"},
    "salinity": {"path": "FMRC_ESPC-D-V02_s3z/FMRC_ESPC-D-V02_s3z_best.ncd", "low": 20.0, "high": 42.0, "unit": "PSU"},
}
MEASURE_NAME = {"water_temp": "sea_water_temperature", "salinity": "sea_water_salinity"}
LAYER_PREFIX = {"water_temp": "hycom_temp", "salinity": "hycom_salt"}
MAP_DEPTHS = (0, 100, 200, 500, 1000, 2000)
GRID_SOFT_LIMIT = 1200.0

LAT_ORIGIN, LAT_STEP = -80.0, 0.04
LON_STEP = 0.08
NLON = 4500
MAP_LAT_LAST, MAP_LAT_STRIDE, MAP_LON_STRIDE = 1000, 12, 6


def parse_opendap_ascii(text: str) -> dict:
    """OPeNDAP .ascii 응답을 값 목록과 좌표 축으로 풉니다."""
    if text.lstrip().startswith("Error"):
        raise FetchError(msg("HYCOM 오류 응답: {detail}", detail=" ".join(text.split())[:120]))
    _, _, body = text.partition("---------------------------------------------")
    values: list[float | None] = []
    maps: dict[str, list[float]] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        row = re.match(r"^(?:\[\d+\])+,\s*(.*)$", line)
        if row:
            values.extend(finite(v) for v in row.group(1).split(","))
            continue
        header = re.match(r"^(?:\w+\.)?(\w+)\[(\d+)\](?:\[\d+\])*$", line)
        if header and i < len(lines) and "[" not in lines[i]:
            numbers = lines[i].strip()
            if numbers:
                maps[header.group(1)] = [float(v) for v in numbers.split(",")]
                i += 1
    return {"values": values, "maps": maps}


def parse_time_origin(das_text: str) -> datetime:
    match = re.search(r"\btime \{.*?units \"hours since (\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", das_text, re.S)
    if not match:
        raise FetchError(msg("HYCOM 시간 기준을 해석하지 못했습니다"))
    return datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}+00:00")


def nearest_time(hours: list[float], origin: datetime, now: datetime) -> tuple[int, datetime]:
    target = (now - origin).total_seconds() / 3600.0
    index = min(range(len(hours)), key=lambda k: abs(hours[k] - target))
    return index, origin + timedelta(hours=hours[index])


def lat_index(lat: float) -> int:
    return max(0, round((lat - LAT_ORIGIN) / LAT_STEP))


def lon_index(lon: float) -> int:
    return round((lon % 360.0) / LON_STEP) % NLON


async def _fetch(fetcher: Fetcher, variable: str, suffix: str, timeout: float, interactive: bool = False) -> str:
    """호스트를 차례로 시도합니다. 첫 호스트의 500이 곧 실패를 뜻하지 않기 때문입니다."""
    path = VARIABLES[variable]["path"]
    errors = []
    for host in HOSTS:
        url = f"https://{host}/thredds/dodsC/{path}{suffix}"
        try:
            response = await fetcher.request("GET", url, timeout=timeout, interactive=interactive)
        except FetchError as exc:
            errors.append(str(exc))
            continue
        if response.status_code == 200 and not response.text.lstrip().startswith("Error"):
            return response.text
        errors.append(f"{host}: HTTP {response.status_code}")
    raise FetchError("; ".join(errors))


async def time_axis(fetcher: Fetcher, variable: str, interactive: bool = False) -> tuple[list[float], datetime]:
    das, axis = await asyncio.gather(
        _fetch(fetcher, variable, ".das", 60.0, interactive),
        _fetch(fetcher, variable, ".ascii?time", 60.0, interactive),
    )
    return parse_opendap_ascii(axis)["maps"]["time"], parse_time_origin(das)


async def depth_axis(fetcher: Fetcher, variable: str) -> list[float]:
    return parse_opendap_ascii(await _fetch(fetcher, variable, ".ascii?depth", 60.0))["maps"]["depth"]


async def fetch_map_layer(
    fetcher: Fetcher, variable: str, time_index: int, depth_index: int
) -> tuple[list[float], list[float], list[float | None]]:
    selector = (
        f"{variable}%5B{time_index}%5D%5B{depth_index}%5D"
        f"%5B0:{MAP_LAT_STRIDE}:{MAP_LAT_LAST}%5D%5B0:{MAP_LON_STRIDE}:{NLON - 1}%5D"
    )
    parsed = parse_opendap_ascii(await _fetch(fetcher, variable, f".ascii?{selector}", 300.0))
    return parsed["maps"]["lat"], parsed["maps"]["lon"], parsed["values"]


async def collect_grid(ctx: Context) -> CollectResult:
    """변수마다 깊이별 격자를 받습니다. 레이어마다 저장하고 토큰을 남기므로 중단돼도 받은 것은 남고,
    서버가 느려 GRID_SOFT_LIMIT를 넘기면 남은 변수는 잠시 뒤의 다음 실행으로 넘깁니다."""
    now = utcnow()
    started = time.monotonic()
    total, latest, skipped, messages, deferred = 0, None, 0, [], 0
    for index, (variable, config) in enumerate(VARIABLES.items()):
        if index and time.monotonic() - started > GRID_SOFT_LIMIT:
            deferred = len(VARIABLES) - index
            break
        hours, origin = await time_axis(ctx.fetcher, variable)
        depths = await depth_axis(ctx.fetcher, variable)
        time_index, valid = nearest_time(hours, origin, now)
        valid_iso = iso(valid)
        latest = max(latest or valid_iso, valid_iso)

        async def one(depth: int) -> int:
            layer = f"{LAYER_PREFIX[variable]}_{depth}"
            if ctx.store.kv_get(f"token:{layer}") == valid_iso:
                return -1
            depth_index = min(range(len(depths)), key=lambda k: abs(depths[k] - depth))
            lats, lons, values = await fetch_map_layer(ctx.fetcher, variable, time_index, depth_index)
            nlat, nlon = len(lats), len(lons)
            triples = [
                (lats[i], lons[j], in_range(values[i * nlon + j], config["low"], config["high"]))
                for i in range(nlat)
                for j in range(nlon)
            ]
            grid = await asyncio.to_thread(
                grid_from_triples, layer, valid_iso, config["unit"], triples, {"depth_m": depth}
            )
            await asyncio.to_thread(ctx.store.save_grid, grid)
            ctx.store.kv_set(f"token:{layer}", valid_iso)
            if depth == 0:
                ctx.store.upsert_measurements(
                    Measurement(
                        source="hycom", dataset="ESPC-D-V02", variable=MEASURE_NAME[variable], kind="model",
                        lat=loc.lat, lon=loc.lon, obs_time=valid_iso, value=value, unit=config["unit"],
                        level="depth:0", depth_m=0.0, location_id=loc.id,
                    )
                    for loc in OCEAN_LOCATIONS
                    if (value := sample_nearest(grid, loc.lat, loc.lon)) is not None
                )
            return len(values)

        results = await asyncio.gather(*(one(d) for d in MAP_DEPTHS), return_exceptions=True)
        for depth, result in zip(MAP_DEPTHS, results):
            if isinstance(result, Exception):
                messages.append(f"{LAYER_PREFIX[variable]}_{depth}: {result}")
            elif result < 0:
                skipped += 1
            else:
                total += result
    expected = (len(VARIABLES) - deferred) * len(MAP_DEPTHS)
    if len(messages) == expected:
        raise FetchError("; ".join(messages[:2]))
    if skipped == expected and not deferred:
        return CollectResult(data_time=latest, unchanged=True, message=msg("같은 시각의 격자를 이미 보유"))
    note = msg("격자 {n}개 갱신", n=expected - skipped - len(messages))
    if messages:
        note = join(note, msg("실패 {n}개", n=len(messages)), messages[0])
    if deferred:
        note = join(note, msg("시간이 길어져 남은 변수 {n}개는 잠시 뒤 이어받습니다", n=deferred))
    return CollectResult(rows=total, data_time=latest, message=note, backlog=bool(deferred))


async def fetch_profile(fetcher: Fetcher, lat: float, lon: float) -> dict:
    """한 지점의 깊이별 수온·염분. 육지면 levels가 비어 돌아옵니다."""
    if lat < LAT_ORIGIN:
        return {"levels": [], "time": None, "lat": None, "lon": None, "reason": msg("HYCOM은 80°S 이남을 다루지 않습니다")}
    li, lj = lat_index(lat), lon_index(lon)
    now = utcnow()

    async def one(variable: str) -> dict:
        hours, origin = await time_axis(fetcher, variable, interactive=True)
        time_index, valid = nearest_time(hours, origin, now)
        selector = f"{variable}%5B{time_index}%5D%5B0:1:39%5D%5B{li}%5D%5B{lj}%5D"
        parsed = parse_opendap_ascii(await _fetch(fetcher, variable, f".ascii?{selector}", 150.0, interactive=True))
        return {"parsed": parsed, "valid": valid}

    temperature, salinity = await asyncio.gather(one("water_temp"), one("salinity"))
    depths = temperature["parsed"]["maps"]["depth"]
    levels = []
    for k, depth in enumerate(depths):
        temp = in_range(temperature["parsed"]["values"][k], -3.0, 40.0)
        salt = in_range(salinity["parsed"]["values"][k], 20.0, 42.0)
        if temp is not None or salt is not None:
            levels.append({"depth_m": depth, "temp": temp, "salt": salt})
    return {
        "levels": levels,
        "time": iso(temperature["valid"]),
        "lat": round(LAT_ORIGIN + li * LAT_STEP, 3),
        "lon": round(((lj * LON_STEP + 180.0) % 360.0) - 180.0, 3),
        "reason": None if levels else msg("모델 격자상 육지이거나 빙붕입니다"),
    }


def profile_measurements(profile: dict, location_id: str | None) -> list[Measurement]:
    rows = []
    for level in profile["levels"]:
        for key, variable, unit in (
            ("temp", "sea_water_temperature", "°C"),
            ("salt", "sea_water_salinity", "PSU"),
        ):
            if level[key] is not None:
                rows.append(
                    Measurement(
                        source="hycom", dataset="ESPC-D-V02", variable=variable, kind="model",
                        lat=profile["lat"], lon=profile["lon"], obs_time=profile["time"], value=level[key],
                        unit=unit, level=f"depth:{level['depth_m']:g}", depth_m=level["depth_m"],
                        location_id=location_id,
                    )
                )
    return rows


async def collect_profiles(ctx: Context) -> CollectResult:
    """해역 대표 지점의 깊이 프로파일을 쌓습니다. 시계열 분석의 바탕이 됩니다."""
    total, latest, failures = 0, None, []
    for loc in OCEAN_LOCATIONS:
        try:
            profile = await fetch_profile(ctx.fetcher, loc.lat, loc.lon)
        except FetchError as exc:
            failures.append(f"{loc.id}: {exc}")
            continue
        total += ctx.store.upsert_measurements(profile_measurements(profile, loc.id))
        if profile["time"]:
            latest = max(latest or profile["time"], profile["time"])
    if failures and not total:
        raise FetchError(failures[0])
    message = msg("해역 {n}곳", n=len(OCEAN_LOCATIONS) - len(failures))
    if failures:
        message = join(message, msg("실패 {n}곳", n=len(failures)))
    return CollectResult(rows=total, data_time=latest, message=message)
