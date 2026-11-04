"""Argo 플로트 현장 관측(Ifremer ERDDAP). 수온·염분의 기준값입니다.

품질 플래그를 반드시 적용합니다. 실제로 psal=0.014(플래그 4) 같은 불량값이 그대로 내려옵니다.
- data_mode가 A·D면 보정값(adjusted)을, R이면 원시값을 씁니다.
- 플래그 1(양호)·2(대체로 양호)만 받아들입니다.
"""

from __future__ import annotations

import asyncio
import csv
import io
from urllib.parse import quote

from ..db import Measurement
from ..http import FetchError, Fetcher, NoData
from ..i18n import join, msg
from ..seawater import depth_from_pressure
from .base import CollectResult, Context, finite, to_iso_utc

BASE = "https://erddap.ifremer.fr/erddap/tabledap/ArgoFloats.csv"
LIST_LAT = -55.0
LIST_DAYS = 30
BATCH = 60
GOOD_QC = {"1", "2"}
VALID_TEMP = (-3.0, 40.0)
VALID_SALT = (20.0, 42.0)


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
    output = []
    for row in parse_csv(text):
        lat, lon = finite(row.get("latitude")), finite(row.get("longitude"))
        cycle = finite(row.get("cycle_number"))
        if lat is None or lon is None or cycle is None or not row.get("time"):
            continue
        mode = row.get("data_mode", "")
        temp, salt = row_values(row, mode)
        output.append(
            {
                "platform": row["platform_number"].strip(),
                "cycle": int(cycle),
                "time": to_iso_utc(row["time"]),
                "lat": lat,
                "lon": lon,
                "data_mode": mode.strip(),
                "position_qc": str(row.get("position_qc", "")).strip(),
                "surface_temp": temp,
                "surface_salt": salt,
            }
        )
    return output


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
            mode, row.get("pres"), row.get("pres_qc"), row.get("pres_adjusted"), row.get("pres_adjusted_qc"),
            (0.0, 12000.0),
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


async def fetch_listing(fetcher: Fetcher, lat_max: float = LIST_LAT, days: int = LIST_DAYS) -> list[dict]:
    url = _query(
        "platform_number,cycle_number,time,latitude,longitude,data_mode,position_qc,pres,"
        "temp,temp_qc,psal,psal_qc,temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc",
        f"latitude<={lat_max}",
        f"time>=now-{days}days",
        "pres<=100",
        'orderByLimit("platform_number,cycle_number,1")',
    )
    response = await fetcher.request("GET", url, timeout=180.0)
    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        raise FetchError(f"Argo HTTP {response.status_code}: {' '.join(response.text.split())[:160]}")
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
    if response.status_code == 404:
        # 갓 추가된 프로파일은 ERDDAP의 파일별 색인(사이클 최댓값)이 아직 옛 값이라 정확한 사이클 질의가
        # 빈 결과(404)로 끝나는 일이 있습니다(2026-11-04, 5905620/35). 바로 앞 사이클부터 범위로 물으면
        # 파일을 열어 주므로, 받아서 그 사이클 행만 골라 씁니다.
        url = _query(LEVEL_COLUMNS, f'platform_number="{platform}"', f"cycle_number>={max(cycle - 1, 0)}")
        response = await fetcher.request("GET", url, timeout=120.0, interactive=interactive)
        if response.status_code == 404:
            raise NoData(msg("프로파일 없음: {platform}/{cycle}", platform=platform, cycle=cycle))
    if response.status_code >= 400:
        raise FetchError(f"Argo HTTP {response.status_code}")
    return parse_levels(response.text, lat, cycle=cycle)


async def collect(ctx: Context) -> CollectResult:
    """목록을 갱신하고, 층별 값이 없는 프로파일을 최신순으로 조금씩 받습니다."""
    listing = await fetch_listing(ctx.fetcher)
    ctx.store.upsert_argo_listing(listing)
    pending = ctx.store.argo_missing_levels(BATCH)

    async def one(item: dict) -> str:
        try:
            levels, _ = await fetch_levels(ctx.fetcher, item["platform"], item["cycle"], item["lat"])
        except NoData:
            levels = []  # 서버에 층별 값이 없는 프로파일은 빈 값으로 적어 두고 매 주기 다시 묻지 않습니다
        ctx.store.save_argo_levels(item["platform"], item["cycle"], levels)
        return "ok" if levels else "empty"

    results = await asyncio.gather(*(one(p) for p in pending), return_exceptions=True)
    fetched = sum(1 for r in results if r == "ok")
    empty = sum(1 for r in results if r == "empty")
    failed = [r for r in results if isinstance(r, Exception)]
    remaining = ctx.store.argo_count_missing()

    ctx.store.upsert_measurements(_surface_measurements(ctx, listing))
    latest = max((p["time"] for p in listing), default=None)
    message = msg("최근 {days}일 프로파일 {listed}개, 층별 값 {fetched}개 수신, 대기 {remaining}개", days=LIST_DAYS, listed=len(listing), fetched=fetched, remaining=remaining)
    if empty:
        message = join(message, msg("층별 값 없음 {n}개", n=empty))
    if failed:
        message = join(message, msg("실패 {n}개", n=len(failed)))
    if pending and fetched == 0 and empty == 0 and failed:
        raise FetchError(msg("Argo 프로파일을 받지 못했습니다: {error}", error=str(failed[0])))
    return CollectResult(rows=fetched, data_time=latest, message=message, backlog=remaining > 0 and fetched > 0)


def _surface_measurements(ctx: Context, listing: list[dict]) -> list[Measurement]:
    rows = []
    for item in listing:
        dataset = f"{item['platform']}/{item['cycle']}"
        for key, variable, unit in (
            ("surface_temp", "sea_water_temperature", "°C"),
            ("surface_salt", "sea_water_salinity", "PSU"),
        ):
            if item.get(key) is not None:
                rows.append(
                    Measurement(
                        source="argo", dataset=dataset, variable=variable, kind="observation",
                        lat=item["lat"], lon=item["lon"], obs_time=item["time"], value=item[key], unit=unit,
                        quality=item["data_mode"],
                    )
                )
    return rows
