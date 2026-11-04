"""수집기 공통 타입."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings
from ..db import Store
from ..http import Fetcher


@dataclass
class Context:
    store: Store
    fetcher: Fetcher
    settings: Settings


@dataclass
class CollectResult:
    rows: int = 0
    data_time: str | None = None
    message: str = ""
    unchanged: bool = False
    backlog: bool = False
    disabled: bool = False


def to_iso_utc(text: str) -> str:
    """API마다 다른 시각 표기를 ``YYYY-MM-DDTHH:MM:SSZ`` 로 통일합니다."""
    value = text.strip().replace(" ", "T")
    if value.endswith("Z"):
        value = value[:-1]
    if "." in value:
        value = value.split(".", 1)[0]
    if len(value) == 16:
        value += ":00"
    elif len(value) == 10:
        value += "T00:00:00"
    return f"{value}Z"


def epoch_to_iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def finite(value) -> float | None:
    """숫자로 바꿀 수 없거나 NaN·무한대면 None."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def in_range(value: float | None, low: float, high: float) -> float | None:
    if value is None or value < low or value > high:
        return None
    return value
