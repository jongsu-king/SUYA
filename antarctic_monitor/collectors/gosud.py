"""GOSUD 선박 항해 중 표층 관측(Ifremer ERDDAP). 수온은 자주, 염분은 일부 선박만 제공합니다."""

from __future__ import annotations

from urllib.parse import quote

from ..db import Measurement
from ..http import FetchError
from ..i18n import msg
from .argo import VALID_SALT, VALID_TEMP, _no_results, parse_csv
from .base import CollectResult, Context, finite, to_iso_utc

BASE = "https://erddap.ifremer.fr/erddap/tabledap/gosud.csv"
GOOD_QC = {"1", "2"}
LAT_MAX = -50.0
DAYS = 30


def parse_rows(text: str) -> list[Measurement]:
    rows = []
    for row in parse_csv(text):
        lat, lon = finite(row.get("latitude")), finite(row.get("longitude"))
        if lat is None or lon is None or not row.get("time"):
            continue
        when = to_iso_utc(row["time"])
        ship = (row.get("ship_call_sign") or "").strip()
        for column, qc_column, variable, unit, valid in (
            ("SSTP", "SSTP_QC", "sea_water_temperature", "°C", VALID_TEMP),
            ("SSPS", "SSPS_QC", "sea_water_salinity", "PSU", VALID_SALT),
        ):
            value = finite(row.get(column))
            if value is None or str(row.get(qc_column, "")).strip() not in GOOD_QC:
                continue
            if not valid[0] <= value <= valid[1]:
                continue
            rows.append(
                Measurement(
                    source="gosud", dataset=ship, variable=variable, kind="observation", lat=lat, lon=lon,
                    obs_time=when, value=value, unit=unit, quality=str(row.get(qc_column)).strip(),
                )
            )
    return rows


async def collect(ctx: Context) -> CollectResult:
    """최근 30일 선박 관측을 받습니다. ERDDAP이 데이터셋을 잠시 찾지 못해 내는 404는 관측 없음이 아니라 실패입니다."""
    query = "&".join(
        [
            "ship_call_sign,time,latitude,longitude,SSTP,SSTP_QC,SSPS,SSPS_QC",
            quote(f"latitude<={LAT_MAX}", safe="=_-."),
            quote(f"time>=now-{DAYS}days", safe="=_-"),
            quote('orderByLimit("ship_call_sign,time/1hour,1")', safe="(),_/"),
        ]
    )
    response = await ctx.fetcher.request("GET", f"{BASE}?{query}", timeout=120.0)
    if _no_results(response):
        return CollectResult(message=msg("최근 30일 이 해역의 선박 관측 없음"))
    if response.status_code >= 400:
        raise FetchError(f"GOSUD HTTP {response.status_code}: {' '.join(response.text.split())[:160]}")
    rows = parse_rows(response.text)
    saved = ctx.store.upsert_measurements(rows)
    ships = len({r.dataset for r in rows})
    latest = max((r.obs_time for r in rows), default=None)
    return CollectResult(rows=saved, data_time=latest, message=msg("선박 {n}척", n=ships))
