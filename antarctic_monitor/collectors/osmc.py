"""NOAA OSMC가 모아 둔 GTS 실시간 현장 관측(OSMC ERDDAP).

표류 부이, 해빙 부이, 선박, 무인 수상정, 계측 동물이 보낸 표층 수온·염분, 수심별 수온·염분,
기온·이슬점·해면 기압을 받습니다. 이 자료에는 품질 플래그가 없어서 물리 범위와 위치로만 거릅니다.
Argo와 겹치는 프로파일링 플로트는 받지 않습니다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from ..db import Measurement, iso, utcnow
from ..http import FetchError
from ..i18n import msg
from .argo import VALID_SALT, VALID_TEMP, _no_results, parse_csv
from .base import CollectResult, Context, finite, in_range, to_iso_utc
from .metar import VALID_AIR

BASE = "https://osmc.noaa.gov/erddap/tabledap/OSMC_30day.csv"
SOURCE = "osmc"
LAT_MAX = -50.0
SEA_LAT_MIN = -79.0
VALID_DEPTH = (0.0, 12000.0)
VALID_PRESSURE = (890.0, 1070.0)
FULL_DAYS = 30
RECENT_DAYS = 3
FULL_EVERY = timedelta(hours=24)
FULL_KEY = "osmc:last_full"
CLOCK_SLACK = timedelta(hours=6)
FLOATS = "PROFILING FLOATS AND GLIDERS"
DRIFTER = "DRIFTING BUOYS"
STUCK_REPORTS = 12
STUCK_SPAN_DEG = 0.002
SEA_VARIABLES = ("sea_water_temperature", "sea_water_salinity")
TIME_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
HOURLY = "platform_code,time/1hour,1"
QUERIES = (
    ("observation_depth,ztmp,zsal", "ztmp>=-5", "platform_code,observation_depth,time/1hour,1"),
    ("sst", "sst>=-5", HOURLY),
    ("sss", "sss>=0", HOURLY),
    ("atmp,dewpoint,slp", "slp>=800", HOURLY),
)
SURFACE_FIELDS = (
    ("sst", "sea_water_temperature", "°C", VALID_TEMP),
    ("sss", "sea_water_salinity", "PSU", VALID_SALT),
)
DEPTH_FIELDS = (
    ("ztmp", "sea_water_temperature", "°C", VALID_TEMP),
    ("zsal", "sea_water_salinity", "PSU", VALID_SALT),
)
PLATFORM_LABEL = {
    "DRIFTING BUOYS": "표류 부이",
    "ICE BUOYS": "해빙 부이",
    "MOORED BUOYS": "계류 부이",
    "VOLUNTEER OBSERVING SHIPS": "선박",
    "SHIPS": "선박",
    "UNCREWED SURFACE VEHICLE": "무인 수상정",
    "TAGGED ANIMAL": "계측 동물",
    "GLIDERS": "글라이더",
    "UNKNOWN": "종류 미상",
}


def platform_label(kind: str | None) -> str:
    """OSMC 플랫폼 종류의 한국어 이름. 표에 없는 종류는 원래 이름을 그대로 씁니다."""
    name = (kind or "").strip()
    return PLATFORM_LABEL.get(name.removesuffix(" (GENERIC)"), name)


def query_url(columns: str, floor: str, thin: str, days: int) -> str:
    """결측을 뜻하는 NaN은 조건으로 걸 수 없어서 값의 아래 한계를 조건으로 씁니다."""
    parts = [
        f"platform_code,platform_type,time,latitude,longitude,{columns}",
        quote(f"latitude<={LAT_MAX}", safe="=_-."),
        quote(f"time>=now-{days}days", safe="=_-"),
        quote(f'platform_type!="{FLOATS}"', safe="=_"),
        quote(floor, safe="=_-."),
        quote(f'orderByLimit("{thin}")', safe="(),_/"),
    ]
    return f"{BASE}?{'&'.join(parts)}"


def read_reports(text: str, latest: str | None = None) -> list[dict]:
    """플랫폼, 시각, 위치가 온전한 50°S 이남 보고만 남깁니다. ``latest`` 뒤의 시각은 시계가 틀린 보고로 봅니다."""
    reports = []
    for row in parse_csv(text):
        code = (row.get("platform_code") or "").strip()
        kind = (row.get("platform_type") or "").strip()
        when = to_iso_utc(row.get("time") or "")
        lat, lon = finite(row.get("latitude")), finite(row.get("longitude"))
        if not code or kind == FLOATS or not TIME_FORMAT.fullmatch(when):
            continue
        if lat is None or lon is None or not -90.0 <= lat <= LAT_MAX or not -180.0 <= lon <= 180.0:
            continue
        if latest is not None and when > latest:
            continue
        reports.append(row | {"code": code, "kind": kind, "when": when, "lat": lat, "lon": lon})
    return reports


def stuck_hours(reports: list[dict]) -> dict[str, set[str]]:
    """제자리에 멈춘 표류 부이와 그 시각(시 단위)을 찾습니다.

    한 시간에 한 번으로 줄인 보고가 연속 12회 동안 위도와 경도 모두 0.002° 안에 있으면 좌초했거나 회수된 부이로 봅니다.
    정박한 선박이나 계류 부이는 멈춰 있는 것이 정상이라 표류 부이만 봅니다.
    """
    tracks: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    for report in reports:
        if report["kind"] == DRIFTER:
            tracks[report["code"]].setdefault(report["when"][:13], (report["lat"], report["lon"]))
    stuck = {}
    for code, track in tracks.items():
        hours = sorted(track)
        marked: set[str] = set()
        for first in range(len(hours) - STUCK_REPORTS + 1):
            run = hours[first:first + STUCK_REPORTS]
            lats = [track[hour][0] for hour in run]
            lons = [track[hour][1] for hour in run]
            if max(lats) - min(lats) < STUCK_SPAN_DEG and max(lons) - min(lons) < STUCK_SPAN_DEG:
                marked.update(run)
        if marked:
            stuck[code] = marked
    return stuck


def _sea_rows(report: dict, common: dict) -> list[Measurement]:
    rows = []
    for column, variable, unit, valid in SURFACE_FIELDS:
        value = in_range(finite(report.get(column)), *valid)
        if value is not None:
            rows.append(Measurement(variable=variable, value=value, unit=unit, **common))
    depth = in_range(finite(report.get("observation_depth")), *VALID_DEPTH)
    if depth is None:
        return rows
    level, depth_m = ("surface", None) if depth == 0 else (f"depth:{depth:g}", depth)
    for column, variable, unit, valid in DEPTH_FIELDS:
        value = in_range(finite(report.get(column)), *valid)
        if value is not None:
            rows.append(Measurement(variable=variable, value=value, unit=unit, level=level, depth_m=depth_m, **common))
    return rows


def _air_rows(report: dict, common: dict) -> list[Measurement]:
    temp = in_range(finite(report.get("atmp")), *VALID_AIR)
    dewp = in_range(finite(report.get("dewpoint")), *VALID_AIR)
    if temp is not None and dewp is not None and dewp > temp:
        temp = dewp = None
    pressure = in_range(finite(report.get("slp")), *VALID_PRESSURE)
    return [
        Measurement(variable=variable, value=value, unit=unit, level="2m", **common)
        for variable, value, unit in (
            ("air_temperature", temp, "°C"), ("dew_point", dewp, "°C"), ("sea_level_pressure", pressure, "hPa"),
        )
        if value is not None
    ]


def build_rows(reports: list[dict], stuck: dict[str, set[str]]) -> list[Measurement]:
    """보고를 측정 행으로 바꿉니다. 같은 키가 겹치면 뒤에 온 보고의 값을 남깁니다.

    해수 값은 79°S 이북이고 멈춘 표류 부이의 것이 아닐 때만 남깁니다. 기상 값은 위치와 무관하게 범위 검사만 합니다.
    """
    kept: dict[tuple, Measurement] = {}
    for report in reports:
        common = {
            "source": SOURCE, "dataset": report["code"], "kind": "observation", "lat": report["lat"],
            "lon": report["lon"], "obs_time": report["when"], "quality": report["kind"] or None,
        }
        rows = _air_rows(report, common)
        if report["lat"] >= SEA_LAT_MIN and report["when"][:13] not in stuck.get(report["code"], ()):
            rows += _sea_rows(report, common)
        for row in rows:
            kept[(row.dataset, row.variable, row.lat, row.lon, row.level, row.obs_time)] = row
    return list(kept.values())


def parse_rows(text: str, latest: str | None = None) -> list[Measurement]:
    reports = read_reports(text, latest)
    return build_rows(reports, stuck_hours(reports))


def window_days(last_full: str | None, now: datetime) -> int:
    """하루에 한 번은 30일 전체를 받고 그 사이에는 최근 3일만 받습니다. 늦게 들어온 보고는 전체 수집 때 채워집니다."""
    try:
        previous = datetime.strptime(last_full or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return FULL_DAYS
    return RECENT_DAYS if timedelta(0) <= now - previous < FULL_EVERY else FULL_DAYS


async def collect(ctx: Context) -> CollectResult:
    """질의 네 개를 차례로 받아 한 번에 저장합니다. 수심별 질의를 먼저 받아 같은 키에서는 표층 항목의 값이 남게 합니다.

    ERDDAP이 데이터셋을 잠시 찾지 못해 내는 404는 관측 없음이 아니라 실패입니다.
    """
    now = utcnow()
    days = window_days(ctx.store.kv_get(FULL_KEY), now)
    latest = iso(now + CLOCK_SLACK)
    reports: list[dict] = []
    for columns, floor, thin in QUERIES:
        response = await ctx.fetcher.request("GET", query_url(columns, floor, thin, days), timeout=120.0)
        if _no_results(response):
            continue
        if response.status_code >= 400:
            raise FetchError(f"OSMC HTTP {response.status_code}: {' '.join(response.text.split())[:160]}")
        reports += read_reports(response.text, latest)
    stuck = stuck_hours(reports)
    rows = build_rows(reports, stuck)
    saved = ctx.store.upsert_measurements(rows)
    for code, hours in stuck.items():
        spans = [(f"{hour}:00:00Z", f"{hour}:59:59Z") for hour in sorted(hours)]
        ctx.store.delete_measurements(SOURCE, code, SEA_VARIABLES, spans)
    if days == FULL_DAYS:
        ctx.store.kv_set(FULL_KEY, iso(now))
    if not rows:
        return CollectResult(message=msg("최근 {days}일 이 해역의 OSMC 관측 없음", days=days))
    newest = max(row.obs_time for row in rows)
    return CollectResult(rows=saved, data_time=newest, message=msg("플랫폼 {n}개", n=len({row.dataset for row in rows})))
