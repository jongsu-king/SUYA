"""화면 요약용 조회. 저장소만 읽고 원천 서버에 요청하지 않습니다."""

from __future__ import annotations

from datetime import timedelta

from .catalog import OUTPUT_JOBS, SOURCES
from .collectors import openmeteo
from .collectors.base import Context
from .db import Store, iso, utcnow
from .gridutil import SECTORS, sample_nearest
from .locations import LOCATIONS

SECTOR_LAYERS = (
    "oisst_sst", "oisst_anom", "oisst_ice", "hycom_salt_0", "hycom_temp_500", "hycom_salt_500", "gfs_t2m",
)
OVERVIEW_LAYERS = (*SECTOR_LAYERS, "smos_sss", "smap_sss")


def latest_metar(store: Store) -> list[dict]:
    since = iso(utcnow() - timedelta(hours=24))
    latest: dict[str, dict] = {}
    for row in store.iter_measurements(source="metar", variable="air_temperature", since=since):
        latest[row["dataset"]] = row
    return [
        {
            "icao": icao, "name": row["quality"], "lat": row["lat"], "lon": row["lon"],
            "value": row["value"], "time": row["obs_time"],
        }
        for icao, row in sorted(latest.items(), key=lambda kv: kv[1]["value"])
    ]


def depth_means(info: dict, variable: str) -> list[dict]:
    """HYCOM 지도 격자에서 구한 남극해 평균을 깊이순으로 정리합니다."""
    prefix = f"hycom_{variable}_"
    rows = [
        {"depth_m": int(layer[len(prefix):]), "mean": item["stats"]["mean"], "valid_time": item["valid_time"]}
        for layer, item in info.items()
        if layer.startswith(prefix)
    ]
    return sorted(rows, key=lambda r: r["depth_m"])


def overview(store: Store) -> dict:
    info = store.latest_grid_info()

    def stat(layer: str) -> dict | None:
        item = info.get(layer)
        if not item:
            return None
        stats = item["stats"]
        return {
            "valid_time": item["valid_time"],
            "mean": stats["mean"],
            "min": stats["min"],
            "max": stats["max"],
            "coverage": stats["coverage"],
        }

    sectors = []
    for key, name, west, east in SECTORS:
        row = {"id": key, "name": name, "west": west, "east": east}
        for layer in SECTOR_LAYERS:
            item = info.get(layer)
            row[layer] = item["stats"]["sectors"][key]["mean"] if item else None
        sectors.append(row)
    argo_items = store.argo_list(since=iso(utcnow() - timedelta(days=30)), lat_max=-60.0)
    return {
        "stats": {layer: stat(layer) for layer in OVERVIEW_LAYERS},
        "sectors": sectors,
        "argo": {
            "profiles": len(argo_items),
            "with_salinity": sum(1 for a in argo_items if a["surface_salt"] is not None),
            "floats": len({a["platform"] for a in argo_items}),
            "latest": argo_items[0]["obs_time"] if argo_items else None,
        },
        "metar": latest_metar(store),
        "depth_means": {variable: depth_means(info, variable) for variable in ("temp", "salt")},
    }


def locations_latest(store: Store) -> list[dict]:
    grids = {name: store.load_grid(name) for name in ("oisst_sst", "hycom_temp_0", "hycom_salt_0", "oisst_ice")}
    output = []
    for loc in LOCATIONS:
        latest = store.latest_for_location(loc.id)
        air = latest.get("openmeteo|gfs_global|air_temperature|2m")
        apparent = latest.get("openmeteo|gfs_global|apparent_temperature|2m")
        output.append(
            loc.as_dict()
            | {
                "air_temperature": air["value"] if air else None,
                "apparent_temperature": apparent["value"] if apparent else None,
                "air_time": air["obs_time"] if air else None,
                **{
                    name: (sample_nearest(grid, loc.lat, loc.lon) if grid else None)
                    for name, grid in grids.items()
                },
            }
        )
    return output


def status_snapshot(ctx: Context, running: set[str], collecting: bool) -> dict:
    states = ctx.store.source_states()
    fields = (
        "last_attempt", "last_success", "last_status", "last_message", "last_rows", "data_time", "next_run",
        "consecutive_errors",
    )
    return {
        "now": iso(),
        "collecting": collecting,
        "running": sorted(running),
        "sources": [
            {
                "id": source["id"],
                "name": source["name"],
                "interval_s": ctx.settings.intervals.get(source["id"]),
                **{key: (states.get(source["id"]) or {}).get(key) for key in fields},
            }
            for source in SOURCES + OUTPUT_JOBS
        ],
        "windy": {"configured": ctx.settings.windy_configured, "testing": ctx.settings.windy_is_testing},
        "openmeteo_budget": openmeteo.budget_usage(ctx),
        "measurements": ctx.store.count_measurements(),
    }
