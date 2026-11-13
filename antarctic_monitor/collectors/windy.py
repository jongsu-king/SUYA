"""Windy 공식 Point Forecast API.

- 키가 있어야 동작합니다. 없으면 'disabled'로 건너뜁니다.
- 무료 testing 키의 응답은 Windy가 값을 섞고 변형한 것이므로 quality로 표시합니다.
- 이 API에는 수온·염분 항목이 없습니다. 기온 계열만 받습니다.
- Windy 이용약관 4.6.1이 자동 수집을 금지하므로 웹사이트 내부 엔드포인트는 쓰지 않습니다.
"""

from __future__ import annotations

import asyncio
from datetime import date

from ..db import Measurement
from ..http import FetchError, Fetcher, RateLimited, Unreachable, failure_of
from ..i18n import join, msg
from ..locations import LOCATIONS
from .base import CollectResult, Context, epoch_to_iso, finite

URL = "https://api.windy.com/api/point-forecast/v2"
PARAMETERS = ["temp", "dewpoint", "rh", "pressure"]
LEVELS = ["surface", "1000h", "950h", "925h", "900h", "850h", "800h", "700h", "600h", "500h", "400h", "300h", "200h", "150h"]
VARIABLE_NAMES = {
    "temp": "air_temperature",
    "dewpoint": "dew_point",
    "rh": "relative_humidity",
    "pressure": "surface_pressure",
}
DAILY_LIMIT = {"testing": 450, "professional": 9500}


def convert(value: float, unit: str | None) -> tuple[float, str]:
    """Windy 단위(K, Pa)를 다른 소스와 같은 단위로 바꿉니다."""
    if unit == "K":
        return round(value - 273.15, 2), "°C"
    if unit == "Pa":
        return round(value / 100.0, 2), "hPa"
    return value, unit or ""


def parse_response(payload: dict) -> list[dict]:
    """키 형식은 ``temp-surface``, ``temp-850h`` 입니다."""
    times = payload.get("ts") or []
    units = payload.get("units") or {}
    output = []
    for key, series in payload.items():
        if key in ("ts", "units", "warning") or "-" not in key or not isinstance(series, list):
            continue
        parameter, level = key.split("-", 1)
        if parameter not in VARIABLE_NAMES:
            continue
        for moment, raw in zip(times, series):
            value = finite(raw)
            if value is None:
                continue
            converted, unit = convert(value, units.get(key))
            output.append(
                {
                    "time": epoch_to_iso(moment / 1000.0),
                    "variable": VARIABLE_NAMES[parameter],
                    "level": level,
                    "value": converted,
                    "unit": unit,
                }
            )
    return output


async def fetch_point(fetcher: Fetcher, key: str, lat: float, lon: float, model: str) -> list[dict]:
    body = {
        "lat": round(lat, 2),
        "lon": round(lon, 2),
        "model": model,
        "parameters": PARAMETERS,
        "levels": LEVELS,
        "key": key,
    }
    response = await fetcher.request("POST", URL, json=body, timeout=60.0)
    if response.status_code == 204:
        return []
    if response.status_code == 400:
        try:
            detail = response.json().get("message")
        except ValueError:
            detail = response.text[:120]
        raise FetchError(msg("Windy가 요청을 거부했습니다: {detail}", detail=str(detail)))
    if response.status_code >= 400:
        raise FetchError(f"Windy HTTP {response.status_code}")
    return parse_response(response.json())


def quality_label(ctx: Context) -> str:
    return "windy_testing_shuffled" if ctx.settings.windy_is_testing else "official"


def _consume(ctx: Context, calls: int) -> None:
    tier = "testing" if ctx.settings.windy_is_testing else "professional"
    key = f"windy_budget:{date.today().isoformat()}"
    used = int(ctx.store.kv_get(key) or 0)
    if used + calls > DAILY_LIMIT[tier]:
        raise RateLimited(msg("Windy 오늘 호출 예산 소진 ({used}/{limit})", used=used, limit=DAILY_LIMIT[tier]))
    ctx.store.kv_set(key, str(used + calls))


def _refund(ctx: Context, calls: int) -> None:
    """서버에 닿지 못한 호출은 한도에 들어가지 않으므로 돌려줍니다."""
    key = f"windy_budget:{date.today().isoformat()}"
    used = int(ctx.store.kv_get(key) or 0)
    ctx.store.kv_set(key, str(max(0, used - calls)))


async def collect(ctx: Context) -> CollectResult:
    key = ctx.settings.windy_api_key
    if not key:
        return CollectResult(disabled=True, message=msg("WINDY_API_KEY가 없어 건너뜀"))
    models = ctx.settings.windy_models
    _consume(ctx, len(LOCATIONS) * len(models))
    quality = quality_label(ctx)
    tasks = [(loc, model, fetch_point(ctx.fetcher, key, loc.lat, loc.lon, model)) for loc in LOCATIONS for model in models]
    results = await asyncio.gather(*(t[2] for t in tasks), return_exceptions=True)
    _refund(ctx, sum(isinstance(result, Unreachable) for result in results))
    rows, failures = [], []
    for (loc, model, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            failures.append(str(result))
            continue
        for item in result:
            pressure = float(item["level"][:-1]) if item["level"].endswith("h") else None
            rows.append(
                Measurement(
                    source="windy", dataset=model, variable=item["variable"], kind="forecast", lat=loc.lat,
                    lon=loc.lon, obs_time=item["time"], value=item["value"], unit=item["unit"],
                    level=f"hpa:{pressure:g}" if pressure else item["level"], pressure_hpa=pressure,
                    location_id=loc.id, quality=quality,
                )
            )
    if failures and not rows:
        raise failure_of((result for result in results if isinstance(result, Exception)), failures[0])
    saved = await asyncio.to_thread(ctx.store.upsert_measurements, rows)
    message = msg("지점 {n}곳", n=len(LOCATIONS) - len(failures))
    if ctx.settings.windy_is_testing:
        message = join(message, msg("testing 키: 변형된 값"))
    return CollectResult(rows=saved, data_time=max((r.obs_time for r in rows), default=None), message=message)
