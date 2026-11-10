"""Argo 플로트 현장 관측(Ifremer ERDDAP). 수온·염분의 기준값입니다.

품질 플래그를 반드시 적용합니다. 실제로 psal=0.014(플래그 4) 같은 불량값이 그대로 내려옵니다.
- data_mode가 A·D면 보정값(adjusted)을, R이면 원시값을 씁니다.
- 플래그 1(양호)·2(대체로 양호)만 받아들입니다.

표층 값은 받아 둔 층별 값에서 고릅니다(seawater.surface_values). 목록 질의의 값은 층별 값을 받기 전까지만
쓰는 임시값입니다.
"""

from __future__ import annotations

import asyncio
import csv
import io
from urllib.parse import quote

from ..db import Measurement, Store
from ..http import FetchError, Fetcher, NoData
from ..i18n import join, msg
from ..seawater import depth_from_pressure, surface_values
from .base import CollectResult, Context, finite, to_iso_utc

BASE = "https://erddap.ifremer.fr/erddap/tabledap/ArgoFloats.csv"
LIST_LAT = -55.0
LIST_DAYS = 30
BATCH = 120
GOOD_QC = {"1", "2"}
VALID_TEMP = (-3.0, 40.0)
VALID_SALT = (20.0, 42.0)
VALID_PRES = (0.0, 12000.0)
SURFACE_VARIABLES = (("temp", "sea_water_temperature", "°C"), ("salt", "sea_water_salinity", "PSU"))
SURFACE_KEY = "argo:surface"
SURFACE_RULE = "levels/1"


def _query(columns: str, *constraints: str) -> str:
    parts = [quote(columns, safe=",_")]
    parts.extend(quote(c, safe='=(),_-/') for c in constraints)
    return f"{BASE}?{'&'.join(parts)}"


def parse_csv(text: str) -> list[dict]:
    """ERDDAP CSV는 둘째 줄이 단위입니다."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return []
    next(reader, None)
    return [dict(zip(header, row)) for row in reader if row]


def select_value(mode: str, raw, raw_qc, adjusted, adjusted_qc, valid: tuple[float, float]) -> float | None:
    """data_mode에 맞는 값을 고르고 품질 플래그와 물리 범위를 확인합니다."""
    if (mode or "").strip() in ("A", "D"):
        value, qc = adjusted, adjusted_qc
    else:
        value, qc = raw, raw_qc
    if str(qc).strip() not in GOOD_QC:
        return None
    number = finite(value)
    if number is None or not valid[0] <= number <= valid[1]:
        return None
    return number


def row_values(row: dict, mode: str) -> tuple[float | None, float | None]:
    temp = select_value(
        mode, row.get("temp"), row.get("temp_qc"), row.get("temp_adjusted"), row.get("temp_adjusted_qc"), VALID_TEMP
    )
    salt = select_value(
        mode, row.get("psal"), row.get("psal_qc"), row.get("psal_adjusted"), row.get("psal_adjusted_qc"), VALID_SALT
    )
    return temp, salt


def parse_listing(text: str) -> list[dict]:
    """프로파일마다 행 하나를 고릅니다. 같은 사이클에 상승·하강 관측이 다 있으면 상승 쪽을 씁니다.

    압력 품질 플래그가 나쁜 행에서는 표층 값을 쓰지 않습니다. 그 값은 층별 값을 받기 전까지만 쓰는 임시값입니다.
    """
    chosen: dict[tuple[str, int], dict] = {}
    for row in parse_csv(text):
        lat, lon = finite(row.get("latitude")), finite(row.get("longitude"))
        cycle = finite(row.get("cycle_number"))
        if lat is None or lon is None or cycle is None or not row.get("time"):
            continue
        mode = row.get("data_mode", "")
        direction = (row.get("direction") or "").strip().upper() or "A"
        pressure = select_value(
            mode, row.get("pres"), row.get("pres_qc"), row.get("pres_adjusted"), row.get("pres_adjusted_qc"), VALID_PRES
        )
        temp, salt = row_values(row, mode) if pressure is not None else (None, None)
        item = {
            "platform": row["platform_number"].strip(),
            "cycle": int(cycle),
            "time": to_iso_utc(row["time"]),
            "lat": lat,
            "lon": lon,
            "data_mode": mode.strip(),
            "position_qc": str(row.get("position_qc", "")).strip(),
            "direction": direction,
            "surface_temp": temp,
            "surface_salt": salt,
            "surface_depth_m": None if pressure is None else round(depth_from_pressure(pressure, lat), 1),
        }
        key = (item["platform"], item["cycle"])
        held = chosen.get(key)
        if held is None or (held["direction"] != "A" and direction == "A"):
            chosen[key] = item
    return list(chosen.values())


def parse_levels(text: str, lat: float, cycle: int | None = None) -> tuple[list[dict], dict]:
    """프로파일 한 개의 층별 값을 고릅니다. 상승 관측이 있으면 그것만 씁니다.

    cycle을 주면 cycle_number 열이 있는 응답에서 그 사이클 행만 씁니다(범위 질의로 받은 경우).
    """
    rows = parse_csv(text)
    if cycle is not None and rows and "cycle_number" in rows[0]:
        rows = [r for r in rows if _as_int(r.get("cycle_number")) == cycle]
    if any((r.get("direction") or "").strip() == "A" for r in rows):
        rows = [r for r in rows if (r.get("direction") or "").strip() == "A"]
    levels, seen, dropped = [], set(), {"temp": 0, "salt": 0}
    for row in rows:
        mode = (row.get("data_mode") or "").strip()
        pres = select_value(
            mode, row.get("pres"), row.get("pres_qc"), row.get("pres_adjusted"), row.get("pres_adjusted_qc"), VALID_PRES
        )
        if pres is None or pres in seen:
            continue
        temp, salt = row_values(row, mode)
        dropped["temp"] += temp is None
        dropped["salt"] += salt is None
        if temp is None and salt is None:
            continue
        seen.add(pres)
        levels.append(
            {
                "pressure_dbar": round(pres, 2),
                "depth_m": round(depth_from_pressure(pres, lat), 1),
                "temp": None if temp is None else round(temp, 3),
                "salt": None if salt is None else round(salt, 3),
            }
        )
    levels.sort(key=lambda lv: lv["pressure_dbar"])
    return levels, dropped


def _no_results(response) -> bool:
    """ERDDAP은 결과가 없을 때도, 데이터셋을 잠시 찾지 못할 때도 404로 답합니다. 앞의 경우만 빈 응답입니다."""
    return response.status_code == 404 and "no matching results" in response.text.lower()


def _failure(response) -> FetchError:
    return FetchError(f"Argo HTTP {response.status_code}: {' '.join(response.text.split())[:160]}")


LIST_COLUMNS = (
    "platform_number,cycle_number,direction,time,latitude,longitude,data_mode,position_qc,"
    "pres,pres_qc,pres_adjusted,pres_adjusted_qc,temp,temp_qc,psal,psal_qc,"
    "temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc"
)


async def fetch_listing(fetcher: Fetcher, lat_max: float = LIST_LAT, days: int = LIST_DAYS) -> list[dict]:
    """최근 프로파일 목록. 사이클과 관측 방향마다 100 dbar 안에서 압력이 가장 낮은 행 하나를 받습니다."""
    url = _query(
        LIST_COLUMNS,
        f"latitude<={lat_max}",
        f"time>=now-{days}days",
        "pres<=100",
        'orderByMin("platform_number,cycle_number,direction,pres")',
    )
    response = await fetcher.request("GET", url, timeout=180.0)
    if _no_results(response):
        return []
    if response.status_code >= 400:
        raise _failure(response)
    return parse_listing(response.text)


LEVEL_COLUMNS = (
    "cycle_number,direction,data_mode,pres,pres_qc,temp,temp_qc,psal,psal_qc,"
    "pres_adjusted,pres_adjusted_qc,temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc"
)


def _as_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


async def fetch_levels(
    fetcher: Fetcher, platform: str, cycle: int, lat: float, interactive: bool = False
) -> tuple[list[dict], dict]:
    url = _query(LEVEL_COLUMNS, f'platform_number="{platform}"', f"cycle_number={cycle}")
    response = await fetcher.request("GET", url, timeout=120.0, interactive=interactive)
    if _no_results(response):
        url = _query(LEVEL_COLUMNS, f'platform_number="{platform}"', f"cycle_number>={max(cycle - 1, 0)}")
        response = await fetcher.request("GET", url, timeout=120.0, interactive=interactive)
        if _no_results(response):
            raise NoData(msg("프로파일 없음: {platform}/{cycle}", platform=platform, cycle=cycle))
    if response.status_code >= 400:
        raise _failure(response)
    return parse_levels(response.text, lat, cycle=cycle)


def dataset_name(profile: dict) -> str:
    return f"{profile['platform']}/{profile['cycle']}"


def surface_rows(profile: dict, surface: dict) -> list[Measurement]:
    """프로파일 하나의 표층 수온·염분 측정 행. surface 는 seawater.surface_values 가 돌려주는 모양입니다."""
    return [
        Measurement(
            source="argo", dataset=dataset_name(profile), variable=variable, kind="observation",
            lat=profile["lat"], lon=profile["lon"], obs_time=profile.get("obs_time") or profile["time"],
            value=surface[key], unit=unit, depth_m=surface.get(f"{key}_depth_m"), quality=profile.get("data_mode"),
        )
        for key, variable, unit in SURFACE_VARIABLES
        if surface.get(key) is not None
    ]


def listed_surface(item: dict) -> dict:
    """목록 행의 임시 표층 값을 seawater.surface_values 와 같은 모양으로 돌려줍니다."""
    depth = item.get("surface_depth_m")
    return {
        "temp": item.get("surface_temp"), "temp_depth_m": depth,
        "salt": item.get("surface_salt"), "salt_depth_m": depth,
    }


def store_levels(store: Store, profile: dict, levels: list[dict]) -> None:
    """층별 값을 저장하고, 그 프로파일의 표층 측정 행을 층에서 고른 값으로 바꿉니다.

    받은 층이 하나도 없으면 측정 행은 그대로 둡니다. 100 dbar 안에 쓸 값이 없는 프로파일은 표층 행이 없어집니다.
    """
    store.save_argo_levels(profile["platform"], profile["cycle"], levels)
    if levels:
        store.replace_datasets("argo", {dataset_name(profile): surface_rows(profile, surface_values(levels))})


def repair_surface(store: Store) -> int:
    """이전 버전이 목록의 첫 행으로 적어 둔 표층 값을, 저장된 층별 값에서 다시 골라 바꿉니다. 한 번만 합니다.

    층별 값이 없는 프로파일은 건드리지 않습니다. 돌려주는 값은 측정 행의 값이 달라진 프로파일 수입니다.
    층별 값은 소수 셋째 자리까지 저장하므로, 그 자리까지 같은 값은 달라진 것으로 세지 않습니다.
    """
    if store.kv_get(SURFACE_KEY) == SURFACE_RULE:
        return 0
    stored: dict[str, dict[str, float]] = {}
    for row in store.iter_measurements(source="argo"):
        stored.setdefault(row["dataset"], {})[row["variable"]] = round(row["value"], 3)
    groups, surfaces, changed = {}, [], 0
    for profile in store.argo_with_levels():
        if not profile["levels"]:
            continue
        surface = surface_values(profile["levels"])
        rows = surface_rows(profile, surface)
        name = dataset_name(profile)
        changed += stored.get(name, {}) != {row.variable: round(row.value, 3) for row in rows}
        surfaces.append((surface["temp"], surface["salt"], profile["platform"], profile["cycle"]))
        groups[name] = rows
    store.set_argo_surface(surfaces)
    store.replace_datasets("argo", groups)
    store.kv_set(SURFACE_KEY, SURFACE_RULE)
    return changed


async def collect(ctx: Context) -> CollectResult:
    """목록을 갱신하고, 층별 값이 없는 프로파일을 최신순으로 조금씩 받습니다.

    이 해역의 30일치 목록은 평소 수백 개이므로, 통째로 비면 정상 결과가 아니라 실패로 기록합니다.
    표층 측정 행은 층별 값에서 고르고, 층별 값이 아직 없는 프로파일만 목록의 임시값으로 적습니다.
    """
    repaired = repair_surface(ctx.store)
    listing = await fetch_listing(ctx.fetcher)
    if not listing:
        raise FetchError(msg("Argo 목록이 비어 있습니다"))
    ctx.store.upsert_argo_listing(listing)
    pending = ctx.store.argo_missing_levels(BATCH)

    async def one(item: dict) -> str:
        try:
            levels, _ = await fetch_levels(ctx.fetcher, item["platform"], item["cycle"], item["lat"])
        except NoData:
            levels = []
        store_levels(ctx.store, item, levels)
        return "ok" if levels else "empty"

    results = await asyncio.gather(*(one(p) for p in pending), return_exceptions=True)
    fetched = sum(1 for r in results if r == "ok")
    empty = sum(1 for r in results if r == "empty")
    failed = [r for r in results if isinstance(r, Exception)]
    remaining = ctx.store.argo_count_missing()

    waiting = ctx.store.argo_without_levels()
    ctx.store.replace_datasets(
        "argo",
        {
            dataset_name(item): surface_rows(item, listed_surface(item))
            for item in listing
            if (item["platform"], item["cycle"]) in waiting
        },
    )
    latest = max((p["time"] for p in listing), default=None)
    message = msg("최근 {days}일 프로파일 {listed}개, 층별 값 {fetched}개 수신, 대기 {remaining}개", days=LIST_DAYS, listed=len(listing), fetched=fetched, remaining=remaining)
    if empty:
        message = join(message, msg("층별 값 없음 {n}개", n=empty))
    if failed:
        message = join(message, msg("실패 {n}개", n=len(failed)))
    if repaired:
        message = join(message, msg("표층 값 {n}개를 층별 값으로 바로잡음", n=repaired))
    if pending and fetched == 0 and empty == 0 and failed:
        raise FetchError(msg("Argo 프로파일을 받지 못했습니다: {error}", error=str(failed[0])))
    return CollectResult(rows=fetched, data_time=latest, message=message, backlog=remaining > 0 and fetched > 0)
