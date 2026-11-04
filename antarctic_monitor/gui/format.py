"""화면에 보여 줄 숫자·시각·상태 글자."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from ..i18n import tr

STATUS_TEXT = {
    "ok": "정상",
    "unchanged": "갱신 없음",
    "error": "오류",
    "rate_limited": "호출 한도",
    "disabled": "꺼짐",
    "running": "수집 중",
    "pending": "대기",
}


def parse_time(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def num(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    return f"{value:.{digits}f}"


def percent(value, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    return f"{value * 100:.{digits}f}%"


def coord_text(lat: float, lon: float) -> str:
    return f"{abs(lat):.2f}°{'S' if lat < 0 else 'N'} {abs(lon):.2f}°{'W' if lon < 0 else 'E'}"


def short_time(iso: str | None) -> str:
    moment = parse_time(iso)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M") if moment else "–"


def clock_time(iso: str | None) -> str:
    moment = parse_time(iso)
    return moment.astimezone().strftime("%H:%M:%S") if moment else "–"


def age(iso: str | None, now: datetime | None = None) -> str:
    moment = parse_time(iso)
    if not moment:
        return "–"
    seconds = ((now or datetime.now(timezone.utc)) - moment).total_seconds()
    future = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        key, value = "{n}초", round(seconds)
    elif seconds < 3600:
        key, value = "{n}분", round(seconds / 60)
    elif seconds < 172800:
        key, value = "{n}시간", round(seconds / 3600)
    else:
        key, value = "{n}일", round(seconds / 86400)
    text = tr(key, n=value)
    return f"+{text}" if future else text


def countdown(iso: str | None, now: datetime | None = None) -> str:
    moment = parse_time(iso)
    if not moment:
        return "–"
    seconds = round((moment - (now or datetime.now(timezone.utc))).total_seconds())
    if seconds <= 0:
        return "00:00"
    if seconds < 3600:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def interval_text(seconds: int | None) -> str:
    if not seconds:
        return "–"
    return tr("{n}분", n=round(seconds / 60)) if seconds < 3600 else tr("{n}시간", n=round(seconds / 3600))


def status_text(status: str | None) -> str:
    return tr(STATUS_TEXT.get(status or "pending", "대기"))
