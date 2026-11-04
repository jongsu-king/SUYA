"""World Ocean Atlas 2023 기후값. 지금 값이 평년과 얼마나 다른지 비교하는 기준입니다.

월별 파일은 1500 m까지만 있어서, 더 깊은 층은 연평균 파일로 채웁니다.
"""

from __future__ import annotations

import asyncio
import csv
import io

from ..http import FetchError, Fetcher
from ..i18n import msg
from .base import finite, in_range

BASE = "https://www.ncei.noaa.gov/thredds-ocean/ncss/grid/woa23/DATA"
FILES = {
    "temp": ("temperature", "t", (-3.0, 40.0)),
    "salt": ("salinity", "s", (20.0, 42.0)),
}


def parse_csv_profile(text: str) -> dict[float, float]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return {}
    depth_column = next(i for i, name in enumerate(header) if name.startswith("alt"))
    output = {}
    for row in reader:
        if len(row) > depth_column:
            depth, value = finite(row[depth_column]), finite(row[-1])
            if depth is not None and value is not None:
                output[depth] = value
    return output


async def _fetch_one(fetcher: Fetcher, key: str, period: int, lat: float, lon: float) -> dict[float, float]:
    folder, letter, _ = FILES[key]
    url = f"{BASE}/{folder}/netcdf/decav/0.25/woa23_decav_{letter}{period:02d}_04.nc"
    params = {"var": f"{letter}_an", "latitude": lat, "longitude": lon, "accept": "csv"}
    response = await fetcher.request("GET", url, params=params, timeout=60.0, interactive=True)  # 지점 조회 전용
    if response.status_code >= 400:
        raise FetchError(f"WOA HTTP {response.status_code}")
    return parse_csv_profile(response.text)


async def fetch_profile(fetcher: Fetcher, lat: float, lon: float, month: int) -> dict:
    jobs = [_fetch_one(fetcher, key, period, lat, lon) for key in FILES for period in (month, 0)]
    temp_month, temp_year, salt_month, salt_year = await asyncio.gather(*jobs)
    temperature = _merge(temp_month, temp_year)
    salinity = _merge(salt_month, salt_year)
    levels = []
    for depth in sorted(set(temperature) | set(salinity)):
        temp = in_range(temperature.get(depth), *FILES["temp"][2])
        salt = in_range(salinity.get(depth), *FILES["salt"][2])
        if temp is not None or salt is not None:
            levels.append({"depth_m": depth, "temp": temp, "salt": salt})
    return {"levels": levels, "month": month, "reason": None if levels else msg("기후값 격자상 육지입니다")}


def _merge(monthly: dict[float, float], annual: dict[float, float]) -> dict[float, float]:
    deepest = max(monthly, default=-1.0)
    merged = dict(monthly)
    merged.update({d: v for d, v in annual.items() if d > deepest})
    return merged
