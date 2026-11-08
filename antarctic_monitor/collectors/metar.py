"""NOAA Aviation Weather Center의 METAR: 남극 기지의 실제 기온 관측입니다.

bbox 조회만으로는 일부 기지가 빠져서, ICAO 코드 목록과 합쳐서 받습니다.
원문이 깨진 보고(``M048/M08``, ``M04/09``)는 부호를 잃은 채 JSON으로 오므로 범위와 이슬점으로 거릅니다.
기압은 해면 보정값(``slp``, 없으면 QNH ``altim``)이라 ``surface_pressure``가 아닌 ``sea_level_pressure``로 저장합니다.
"""

from __future__ import annotations

from ..db import Measurement
from ..i18n import msg
from .base import CollectResult, Context, epoch_to_iso, finite, in_range

URL = "https://aviationweather.gov/api/data/metar"
ANTARCTIC_IDS = ("NZSP", "NZCM", "NZFX", "NZWD", "NZPG", "NZIR", "SAWB", "SCRM")
BBOX = "-90,-180,-60,180"
VALID_AIR = (-95.0, 30.0)


def parse_reports(payload: list[dict]) -> list[Measurement]:
    rows = []
    for report in payload:
        icao = report.get("icaoId")
        lat, lon = finite(report.get("lat")), finite(report.get("lon"))
        obs = finite(report.get("obsTime"))
        if not icao or lat is None or lon is None or obs is None:
            continue
        when = epoch_to_iso(obs)
        pressure = finite(report.get("slp")) or finite(report.get("altim"))
        temp = in_range(finite(report.get("temp")), *VALID_AIR)
        dewp = in_range(finite(report.get("dewp")), *VALID_AIR)
        if temp is not None and dewp is not None and dewp > temp:
            temp = dewp = None
        for variable, value, unit in (
            ("air_temperature", temp, "°C"),
            ("dew_point", dewp, "°C"),
            ("sea_level_pressure", pressure, "hPa"),
        ):
            if value is not None:
                rows.append(
                    Measurement(
                        source="metar", dataset=icao, variable=variable, kind="observation", lat=lat, lon=lon,
                        obs_time=when, value=value, unit=unit, level="2m", location_id=f"metar:{icao}",
                        quality=report.get("name"),
                    )
                )
    return rows


async def collect(ctx: Context) -> CollectResult:
    by_ids = await ctx.fetcher.get_json(
        URL, params={"ids": ",".join(ANTARCTIC_IDS), "format": "json", "hours": 6}
    )
    by_box = await ctx.fetcher.get_json(URL, params={"bbox": BBOX, "format": "json", "hours": 6})
    rows = parse_reports(list(by_ids or []) + list(by_box or []))
    saved = ctx.store.upsert_measurements(rows)
    ctx.store.drop_invalid_metar(*VALID_AIR)
    ctx.store.relabel_metar_pressure()
    stations = {r.dataset for r in rows}
    latest = max((r.obs_time for r in rows), default=None)
    return CollectResult(rows=saved, data_time=latest, message=msg("기지 {n}곳", n=len(stations)))
