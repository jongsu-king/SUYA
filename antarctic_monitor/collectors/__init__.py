"""소스별 수집 작업 등록표. 키는 config.DEFAULT_INTERVALS 및 catalog와 맞습니다."""

from __future__ import annotations

from typing import Awaitable, Callable

from . import argo, erddap, gosud, hycom, metar, openmeteo, windy
from .base import CollectResult, Context

Job = Callable[[Context], Awaitable[CollectResult]]


async def _excel(ctx: Context) -> CollectResult:
    # excel 모듈이 collectors를 쓰므로 순환 import를 피해 여기서 불러옵니다.
    from .. import excel

    return await excel.collect(ctx)


JOBS: dict[str, Job] = {
    "metar": metar.collect,
    "openmeteo_current": openmeteo.collect_current,
    "openmeteo_marine": openmeteo.collect_marine,
    "openmeteo_forecast": openmeteo.collect_forecast,
    "gfs_grid": openmeteo.collect_gfs_grid,
    "oisst": erddap.collect_oisst,
    "smos": erddap.collect_smos,
    "smap": erddap.collect_smap,
    "hycom_grid": hycom.collect_grid,
    "hycom_profiles": hycom.collect_profiles,
    "argo": argo.collect,
    "gosud": gosud.collect,
    "windy": windy.collect,
    "excel": _excel,
}
