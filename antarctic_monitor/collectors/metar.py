"""NOAA Aviation Weather Center의 METAR: 남극 기지의 실제 기온 관측입니다.

bbox 조회만으로는 일부 기지가 빠져서, ICAO 코드 목록과 합쳐서 받습니다.
"""

from __future__ import annotations

from ..db import Measurement
from ..i18n import msg
from .base import CollectResult, Context, epoch_to_iso, finite

URL = "https://aviationweather.gov/api/data/metar"
ANTARCTIC_IDS = ("NZSP", "NZCM", "NZFX", "NZWD", "NZPG", "NZIR", "SAWB", "SCRM")
BBOX = "-90,-180,-60,180"


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
        for variable, value, unit in (
            ("air_temperature", finite(report.get("temp")), "°C"),
            ("dew_point", finite(report.get("dewp")), "°C"),
            ("surface_pressure", pressure, "hPa"),
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
    stations = {r.dataset for r in rows}
    latest = max((r.obs_time for r in rows), default=None)
    return CollectResult(rows=saved, data_time=latest, message=msg("기지 {n}곳", n=len(stations)))
