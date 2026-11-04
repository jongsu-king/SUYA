"""GitHub의 최신 릴리스와 현재 버전을 비교합니다. 사용자가 도움말 메뉴에서 눌렀을 때만 묻습니다."""

from __future__ import annotations

import re

from . import __url__, __version__
from .http import Fetcher

RELEASES_API = "https://api.github.com/repos/jongsu-king/SUYA/releases/latest"
RELEASES_PAGE = f"{__url__}/releases/latest"


def parse_version(text: str) -> tuple[int, int, int]:
    numbers = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


async def latest_release(fetcher: Fetcher) -> dict:
    data = await fetcher.get_json(RELEASES_API, timeout=20.0, interactive=True)
    tag = str(data.get("tag_name") or "")
    version = tag[1:] if tag.startswith("v") else tag
    return {"version": version, "url": data.get("html_url") or RELEASES_PAGE, "newer": is_newer(version)}
