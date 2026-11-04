"""좌표 계산과 nullschool·Windy 링크 해석."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ParsedPoint:
    lat: float
    lon: float
    site: str
    kind: str


def normalize_lon(lon: float) -> float:
    """경도를 [-180, 180) 범위로 맞춥니다."""
    return ((lon + 180.0) % 360.0) - 180.0


def validate(lat: float, lon: float) -> tuple[float, float]:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("좌표가 숫자가 아닙니다")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"위도 범위를 벗어났습니다: {lat}")
    return lat, normalize_lon(lon)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


_NUM = r"-?\d+(?:\.\d+)?"


def parse_location_url(url: str) -> ParsedPoint:
    """nullschool·Windy 링크에서 좌표를 뽑습니다.

    nullschool: ``#.../orthographic=경도,위도,축척/loc=경도,위도``
    Windy: ``/위도/경도?...`` 또는 ``?레이어,위도,경도,줌``
    """
    text = url.strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.netloc.lower()

    if "nullschool" in host:
        fragment = parsed.fragment
        loc = re.search(rf"loc=({_NUM}),({_NUM})", fragment)
        if loc:
            lat, lon = validate(float(loc.group(2)), float(loc.group(1)))
            return ParsedPoint(lat, lon, "nullschool", "marker")
        view = re.search(rf"=({_NUM}),({_NUM}),{_NUM}", fragment)
        if view:
            lat, lon = validate(float(view.group(2)), float(view.group(1)))
            return ParsedPoint(lat, lon, "nullschool", "view")
        raise ValueError("nullschool 링크에서 좌표를 찾지 못했습니다")

    if "windy.com" in host:
        path = re.fullmatch(rf"/({_NUM})/({_NUM})/?", parsed.path)
        if path:
            lat, lon = validate(float(path.group(1)), float(path.group(2)))
            return ParsedPoint(lat, lon, "windy", "marker")
        view = re.search(rf"(?:^|,)({_NUM}),({_NUM}),\d+(?:\.\d+)?(?:,|$)", parsed.query)
        if view:
            lat, lon = validate(float(view.group(1)), float(view.group(2)))
            return ParsedPoint(lat, lon, "windy", "view")
        raise ValueError("Windy 링크에서 좌표를 찾지 못했습니다")

    raise ValueError("nullschool 또는 Windy 링크만 해석할 수 있습니다")
