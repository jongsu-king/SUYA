"""OSMC 수집기의 파서와 품질 규칙, 수집 흐름, 엑셀 시트, 지점 조회를 검증합니다.

표본 행은 2026-11-11에 실제로 받은 응답에서 가져왔습니다.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

import httpx
import openpyxl
import pytest

from antarctic_monitor import catalog, excel, i18n, pointquery
from antarctic_monitor.collectors import JOBS, osmc
from antarctic_monitor.collectors.base import Context
from antarctic_monitor.config import DEFAULT_INTERVALS, Settings
from antarctic_monitor.db import Measurement, Store, iso, utcnow
from antarctic_monitor.http import HOST_LIMITS, FetchError, Fetcher
from antarctic_monitor.i18n import msg, render, set_language

HEAD = "platform_code,platform_type,time,latitude,longitude,"
SST_HEAD = HEAD + "sst\n,,UTC,degrees_north,degrees_east,Deg C\n"
SSS_HEAD = HEAD + "sss\n,,UTC,degrees_north,degrees_east,1\n"
DEPTH_HEAD = HEAD + "observation_depth,ztmp,zsal\n,,UTC,degrees_north,degrees_east,,Deg C,\n"
AIR_HEAD = HEAD + "atmp,dewpoint,slp\n,,UTC,degrees_north,degrees_east,Deg C,Deg C,hPa\n"
NO_RESULTS = 'Error { code=404; message="Not Found: Your query produced no matching results. (nRows = 0)"; }'
UNKNOWN_DATASET = 'Error { code=404; message="Not Found: Currently unknown datasetID=OSMC_30day"; }'

SAILDRONE = "1801608,UNCREWED SURFACE VEHICLE,2026-10-29T10:56:00Z,-50.00071,-136.7136,"
SEAL = "9902319,TAGGED ANIMAL,2026-10-20T13:10:00Z,-61.71,-57.05,"
TABLES = {
    "ztmp": DEPTH_HEAD + SEAL + "4.0,-0.34,34.6\n",
    "sst": SST_HEAD + SAILDRONE + "7.88\n",
    "sss": SSS_HEAD + SAILDRONE + "34.26\n",
    "slp": AIR_HEAD + SAILDRONE + "7.2,NaN,1015.8\n",
}


@pytest.fixture(autouse=True)
def korean():
    set_language("ko")
    yield
    set_language("ko")


def _hourly(code, kind, hours, value="1.5", drift=0.0, start=0):
    return "".join(
        f"{code},{kind},2026-10-20T{hour:02d}:30:00Z,{-62.0 + drift * hour:.5f},-58.00000,{value}\n"
        for hour in range(start, start + hours)
    )


def _answers(tables):
    def answer(request):
        query = unquote(str(request.url))
        for column, text in tables.items():
            if f"&{column}>=" in query:
                return httpx.Response(200, text=text)
        return httpx.Response(404, text=NO_RESULTS)

    return answer


def _fetcher(answer):
    calls = []

    def handler(request):
        calls.append(unquote(str(request.url)))
        return answer(request)

    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0), calls


def _count(store, variable):
    return len(list(store.iter_measurements(source="osmc", variable=variable)))


def _sample_rows():
    reports = [report for text in TABLES.values() for report in osmc.read_reports(text)]
    return osmc.build_rows(reports, osmc.stuck_hours(reports))


def test_osmc_is_a_scheduled_source():
    assert JOBS["osmc"] is osmc.collect
    assert DEFAULT_INTERVALS["osmc"] == 3600
    assert HOST_LIMITS["osmc.noaa.gov"] == 2
    entry = next(item for item in catalog.SOURCES if item["id"] == "osmc")
    assert entry["kind"] == "observation" and entry["url"].startswith("https://osmc.noaa.gov/erddap/")


def test_query_url_uses_a_numeric_floor_and_thins_on_the_server():
    url = osmc.query_url("sst", "sst>=-5", osmc.HOURLY, 3)
    assert url.startswith(osmc.BASE + "?platform_code,platform_type,time,latitude,longitude,sst&")
    assert " " not in url and '"' not in url and "<" not in url and ">" not in url
    query = unquote(url)
    assert "&latitude<=-50.0&" in query
    assert "&time>=now-3days&" in query
    assert '&platform_type!="PROFILING FLOATS AND GLIDERS"&' in query
    assert "&sst>=-5&" in query
    assert query.endswith('&orderByLimit("platform_code,time/1hour,1")')
    assert "NaN" not in query


def test_reports_need_a_platform_a_full_time_and_a_position_south_of_50():
    text = SST_HEAD + (
        "1801608,UNCREWED SURFACE VEHICLE,2026-11-08T15:25:00Z,-59.20761,-117.04255,3.16\n"
        ",DRIFTING BUOYS,2026-11-08T15:00:00Z,-60.0,10.0,1.0\n"
        "7900001,PROFILING FLOATS AND GLIDERS,2026-11-08T15:00:00Z,-60.0,10.0,1.0\n"
        "2101001,DRIFTING BUOYS,,-60.0,10.0,1.0\n"
        "2101002,DRIFTING BUOYS,2026-11-08T15,-60.0,10.0,1.0\n"
        "2101003,DRIFTING BUOYS,2026-11-08T15:00:00Z,-49.9,10.0,1.0\n"
        "2101004,DRIFTING BUOYS,2026-11-08T15:00:00Z,-60.0,181.0,1.0\n"
        "2101005,DRIFTING BUOYS,2026-11-08T15:00:00Z,NaN,10.0,1.0\n"
        "2101006,DRIFTING BUOYS,2026-11-09T02:00:01Z,-60.0,10.0,1.0\n"
    )
    assert [report["code"] for report in osmc.read_reports(text, latest="2026-11-09T02:00:00Z")] == ["1801608"]
    assert [report["code"] for report in osmc.read_reports(text)] == ["1801608", "2101006"]


def test_impossible_values_and_sea_values_south_of_79_are_dropped():
    text = DEPTH_HEAD + (
        "1897495,UNKNOWN,2026-10-28T06:10:00Z,-88.045,-179.99452,29.2,44.379997,76.84\n"
        "9902319,TAGGED ANIMAL,2026-10-20T13:10:00Z,-61.71,-57.05,4.0,44.379997,76.84\n"
        "9902319,TAGGED ANIMAL,2026-10-20T14:10:00Z,-79.01,-57.05,4.0,-1.2,34.5\n"
        "9902319,TAGGED ANIMAL,2026-10-20T15:10:00Z,-79.0,-57.05,4.0,-1.2,34.5\n"
        "9902319,TAGGED ANIMAL,2026-10-20T16:10:00Z,-61.71,-57.05,12000.5,-1.2,34.5\n"
        "9902319,TAGGED ANIMAL,2026-10-20T17:10:00Z,-61.71,-57.05,4.0,-3.01,19.99\n"
    )
    assert [(row.obs_time, row.variable, row.value) for row in osmc.parse_rows(text)] == [
        ("2026-10-20T15:10:00Z", "sea_water_temperature", -1.2),
        ("2026-10-20T15:10:00Z", "sea_water_salinity", 34.5),
    ]


def test_weather_values_pass_a_range_check_wherever_they_come_from():
    text = AIR_HEAD + (
        "1801608,UNCREWED SURFACE VEHICLE,2026-10-12T03:43:00Z,-53.26511,-167.42737,7.2,NaN,1015.8\n"
        "2KZJ7DD,VOLUNTEER OBSERVING SHIPS,2026-10-15T06:00:00Z,-55.0,-60.0,3.0,4.5,868.9\n"
        "ZSAA,VOLUNTEER OBSERVING SHIPS,2026-10-15T06:00:00Z,-70.0,-8.0,-96.0,NaN,929.8\n"
        "89001,UNKNOWN,2026-10-28T06:00:00Z,-89.98,0.0,-48.2,-52.0,1071.0\n"
    )
    assert {(row.dataset, row.variable, row.value, row.level) for row in osmc.parse_rows(text)} == {
        ("1801608", "air_temperature", 7.2, "2m"),
        ("1801608", "sea_level_pressure", 1015.8, "2m"),
        ("ZSAA", "sea_level_pressure", 929.8, "2m"),
        ("89001", "air_temperature", -48.2, "2m"),
        ("89001", "dew_point", -52.0, "2m"),
    }


def test_a_drifting_buoy_that_stopped_moving_loses_its_sea_values():
    text = SST_HEAD + (
        _hourly("2802071", "DRIFTING BUOYS", 12)
        + _hourly("2802072", "DRIFTING BUOYS", 11)
        + _hourly("2802073", "DRIFTING BUOYS", 12, drift=0.01)
        + _hourly("VMIC", "VOLUNTEER OBSERVING SHIPS", 12)
    )
    reports = osmc.read_reports(text)
    stuck = osmc.stuck_hours(reports)
    assert set(stuck) == {"2802071"} and len(stuck["2802071"]) == 12
    assert Counter(row.dataset for row in osmc.build_rows(reports, stuck)) == {"2802072": 11, "2802073": 12, "VMIC": 12}


def test_only_the_hours_a_drifter_stood_still_are_dropped():
    moving = "".join(
        f"2802071,DRIFTING BUOYS,2026-10-20T{hour:02d}:30:00Z,{-62.5 - 0.1 * hour:.5f},-58.00000,1.5\n" for hour in (12, 13)
    )
    rows = osmc.parse_rows(SST_HEAD + _hourly("2802071", "DRIFTING BUOYS", 12) + moving)
    assert sorted(row.obs_time for row in rows) == ["2026-10-20T12:30:00Z", "2026-10-20T13:30:00Z"]


def test_a_stuck_drifter_keeps_its_pressure():
    reports = osmc.read_reports(SST_HEAD + _hourly("2802071", "DRIFTING BUOYS", 12)) + osmc.read_reports(
        AIR_HEAD + _hourly("2802071", "DRIFTING BUOYS", 12, value="NaN,NaN,1002.4")
    )
    rows = osmc.build_rows(reports, osmc.stuck_hours(reports))
    assert Counter(row.variable for row in rows) == {"sea_level_pressure": 12}


def test_depth_reports_become_depth_levels_and_depth_zero_is_the_surface():
    text = DEPTH_HEAD + SEAL + "4.0,-0.34,34.6\n" + SEAL + "250.5,1.2,NaN\n" + SEAL + "0.0,-0.5,34.1\n"
    rows = osmc.parse_rows(text)
    assert [(row.variable, row.level, row.depth_m, row.value) for row in rows] == [
        ("sea_water_temperature", "depth:4", 4.0, -0.34),
        ("sea_water_salinity", "depth:4", 4.0, 34.6),
        ("sea_water_temperature", "depth:250.5", 250.5, 1.2),
        ("sea_water_temperature", "surface", None, -0.5),
        ("sea_water_salinity", "surface", None, 34.1),
    ]
    assert {(row.source, row.dataset, row.kind, row.quality) for row in rows} == {
        ("osmc", "9902319", "observation", "TAGGED ANIMAL")
    }


def test_the_same_key_keeps_the_later_report():
    reports = osmc.read_reports(DEPTH_HEAD + SAILDRONE + "0.0,7.5,NaN\n") + osmc.read_reports(SST_HEAD + SAILDRONE + "7.88\n")
    assert [(row.level, row.value) for row in osmc.build_rows(reports, {})] == [("surface", 7.88)]


def test_all_thirty_days_once_a_day_and_three_days_in_between():
    now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    assert osmc.window_days(None, now) == 30
    assert osmc.window_days("not a time", now) == 30
    assert osmc.window_days("2026-11-11T04:32:14Z", now) == 3
    assert osmc.window_days("2026-11-10T12:00:01Z", now) == 3
    assert osmc.window_days("2026-11-10T12:00:00Z", now) == 30
    assert osmc.window_days("2026-11-11T12:00:01Z", now) == 30


def test_platform_labels_cover_generic_names_and_both_languages():
    assert osmc.platform_label("VOLUNTEER OBSERVING SHIPS (GENERIC)") == "선박"
    assert osmc.platform_label("SHIPS (GENERIC)") == "선박"
    assert osmc.platform_label("TAGGED ANIMAL") == "계측 동물"
    assert osmc.platform_label("WEATHER BUOYS") == "WEATHER BUOYS"
    assert osmc.platform_label(None) == ""
    assert set(osmc.PLATFORM_LABEL.values()) <= set(i18n.EN)
    label = msg("OSMC {kind}", kind=msg(osmc.platform_label("DRIFTING BUOYS")))
    assert render(label) == "OSMC 표류 부이"
    set_language("en")
    assert render(label) == "OSMC Drifting buoy"


async def test_collect_stores_four_queries_and_narrows_the_window_after_a_full_pass(tmp_path):
    store = Store(tmp_path / "t.db")
    fetcher, calls = _fetcher(_answers(TABLES))
    ctx = Context(store, fetcher, Settings())
    result = await osmc.collect(ctx)
    assert len(calls) == 4 and all("&time>=now-30days&" in call for call in calls)
    assert "observation_depth,ztmp,zsal" in calls[0]
    assert result.rows == 6 and result.data_time == "2026-10-29T10:56:00Z"
    assert render(result.message) == "플랫폼 2개"
    stored = {(row["dataset"], row["variable"], row["level"]): row["value"] for row in store.iter_measurements(source="osmc")}
    assert stored == {
        ("9902319", "sea_water_temperature", "depth:4"): -0.34,
        ("9902319", "sea_water_salinity", "depth:4"): 34.6,
        ("1801608", "sea_water_temperature", "surface"): 7.88,
        ("1801608", "sea_water_salinity", "surface"): 34.26,
        ("1801608", "air_temperature", "2m"): 7.2,
        ("1801608", "sea_level_pressure", "2m"): 1015.8,
    }
    assert sorted(row["practical_salinity"] for row in store.iter_ions(source="osmc")) == [34.26, 34.6]
    assert store.kv_get(osmc.FULL_KEY) is not None

    await osmc.collect(ctx)
    assert len(calls) == 8 and all("&time>=now-3days&" in call for call in calls[4:])
    assert len(list(store.iter_measurements(source="osmc"))) == 6
    await fetcher.aclose()
    store.close()


async def test_collect_fails_on_an_unknown_dataset_and_is_empty_on_no_results(tmp_path):
    store = Store(tmp_path / "t.db")
    fetcher, _ = _fetcher(lambda request: httpx.Response(404, text=UNKNOWN_DATASET))
    with pytest.raises(FetchError, match="unknown datasetID"):
        await osmc.collect(Context(store, fetcher, Settings()))
    assert store.kv_get(osmc.FULL_KEY) is None
    await fetcher.aclose()

    fetcher, _ = _fetcher(lambda request: httpx.Response(400, text="Bad Request: Query error"))
    with pytest.raises(FetchError, match="OSMC HTTP 400"):
        await osmc.collect(Context(store, fetcher, Settings()))
    await fetcher.aclose()

    fetcher, calls = _fetcher(lambda request: httpx.Response(404, text=NO_RESULTS))
    result = await osmc.collect(Context(store, fetcher, Settings()))
    assert result.rows == 0 and len(calls) == 4
    assert render(result.message) == "최근 30일 이 해역의 OSMC 관측 없음"
    set_language("en")
    assert render(result.message) == "No OSMC observations here in the last 30 days"
    await fetcher.aclose()
    store.close()


async def test_collect_drops_reports_dated_more_than_six_hours_ahead(tmp_path):
    store = Store(tmp_path / "t.db")
    ahead, soon = iso(utcnow() + timedelta(hours=7)), iso(utcnow() + timedelta(hours=5))
    tables = {
        "sst": SST_HEAD + f"2101001,DRIFTING BUOYS,{ahead},-60.0,10.0,1.0\n2101002,DRIFTING BUOYS,{soon},-60.0,10.0,1.1\n"
    }
    fetcher, _ = _fetcher(_answers(tables))
    await osmc.collect(Context(store, fetcher, Settings()))
    assert [row["dataset"] for row in store.iter_measurements(source="osmc")] == ["2101002"]
    await fetcher.aclose()
    store.close()


async def test_collect_removes_sea_values_stored_before_a_drifter_was_seen_to_be_stuck(tmp_path):
    store = Store(tmp_path / "t.db")

    def tables_for(hours):
        return {
            "sst": SST_HEAD + _hourly("2802071", "DRIFTING BUOYS", hours) + _hourly("VMIC", "VOLUNTEER OBSERVING SHIPS", hours),
            "sss": SSS_HEAD + _hourly("2802071", "DRIFTING BUOYS", hours, value="34.2"),
            "slp": AIR_HEAD + _hourly("2802071", "DRIFTING BUOYS", hours, value="NaN,NaN,1002.4"),
        }

    tables = tables_for(11)
    fetcher, _ = _fetcher(_answers(tables))
    ctx = Context(store, fetcher, Settings())
    await osmc.collect(ctx)
    assert _count(store, "sea_water_temperature") == 22 and _count(store, "sea_water_salinity") == 11
    assert len(list(store.iter_ions(source="osmc"))) == 11

    tables.update(tables_for(12))
    result = await osmc.collect(ctx)
    assert result.rows == 24
    assert {row["dataset"] for row in store.iter_measurements(source="osmc", variable="sea_water_temperature")} == {"VMIC"}
    assert _count(store, "sea_water_temperature") == 12 and _count(store, "sea_water_salinity") == 0
    assert list(store.iter_ions(source="osmc")) == []
    assert _count(store, "sea_level_pressure") == 12
    await fetcher.aclose()
    store.close()


def test_delete_measurements_only_touches_the_named_rows(tmp_path):
    store = Store(tmp_path / "t.db")

    def row(source, dataset, variable, when, value):
        return Measurement(source, dataset, variable, "observation", -62.0, -58.0, when, value, "x")

    store.upsert_measurements([
        row("osmc", "A", "sea_water_temperature", "2026-10-20T00:30:00Z", 1.0),
        row("osmc", "A", "sea_water_salinity", "2026-10-20T00:59:59Z", 34.0),
        row("osmc", "A", "sea_level_pressure", "2026-10-20T00:30:00Z", 1000.0),
        row("osmc", "A", "sea_water_temperature", "2026-10-20T01:00:00Z", 1.1),
        row("osmc", "B", "sea_water_temperature", "2026-10-20T00:30:00Z", 1.2),
        row("gosud", "A", "sea_water_temperature", "2026-10-20T00:30:00Z", 1.3),
    ])
    assert len(list(store.iter_ions())) == 1
    span = [("2026-10-20T00:00:00Z", "2026-10-20T00:59:59Z")]
    assert store.delete_measurements("osmc", "A", osmc.SEA_VARIABLES, span) == 2
    assert store.delete_measurements("osmc", "A", osmc.SEA_VARIABLES, span) == 0
    assert sorted((item["source"], item["dataset"], item["variable"], item["value"]) for item in store.iter_measurements()) == [
        ("gosud", "A", "sea_water_temperature", 1.3),
        ("osmc", "A", "sea_level_pressure", 1000.0),
        ("osmc", "A", "sea_water_temperature", 1.1),
        ("osmc", "B", "sea_water_temperature", 1.2),
    ]
    assert list(store.iter_ions()) == []
    store.close()


def test_workbook_has_one_osmc_row_per_time_platform_position_and_depth(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_measurements(_sample_rows())
    excel.sync(store, tmp_path / "xl", ["2026-10"])
    book = openpyxl.load_workbook(tmp_path / "xl" / "antarctic_db_2026-10.xlsx", read_only=True)
    assert list(book["OSMC관측"].iter_rows(values_only=True)) == [
        ("시각 UTC", "플랫폼", "종류", "위도", "경도", "수심 m", "수온 °C", "염분 PSU", "기온 °C", "이슬점 °C", "해면 기압 hPa"),
        (datetime(2026, 10, 20, 13, 10), "9902319", "계측 동물", -61.71, -57.05, 4, -0.34, 34.6, None, None, None),
        (datetime(2026, 10, 29, 10, 56), "1801608", "무인 수상정", -50.00071, -136.7136, None, 7.88, 34.26, 7.2, None, 1015.8),
    ]
    ions = list(book["이온조성"].iter_rows(values_only=True))
    assert sum("osmc" in row for row in ions) == 2
    store.close()


def test_workbook_osmc_sheet_in_english(tmp_path):
    set_language("en")
    store = Store(tmp_path / "t.db")
    store.upsert_measurements(_sample_rows())
    excel.sync(store, tmp_path / "xl", ["2026-10"])
    book = openpyxl.load_workbook(tmp_path / "xl" / "antarctic_db_2026-10.xlsx", read_only=True)
    rows = list(book["OSMC obs"].iter_rows(values_only=True))
    assert rows[0] == (
        "Time UTC", "Platform", "Type", "Lat", "Lon", "Depth m", "Temp °C", "Salinity PSU", "Air temp °C", "Dew point °C",
        "Sea-level pressure hPa",
    )
    assert [row[2] for row in rows[1:]] == ["Tagged animal", "Uncrewed surface vehicle"]
    store.close()


def _recent_store(tmp_path):
    store = Store(tmp_path / "t.db")
    recent, old = iso(utcnow() - timedelta(hours=3)), iso(utcnow() - timedelta(days=31))

    def row(dataset, variable, lat, when, value, depth=None, kind="DRIFTING BUOYS"):
        level = "surface" if depth is None else f"depth:{depth:g}"
        unit = "°C" if variable == "sea_water_temperature" else "PSU"
        return Measurement(
            "osmc", dataset, variable, "observation", lat, -58.0, when, value, unit, level=level, depth_m=depth, quality=kind
        )

    store.upsert_measurements([
        row("NEAR", "sea_water_temperature", -62.1, recent, 1.5),
        row("FAR", "sea_water_temperature", -63.0, recent, 1.1),
        row("OLD", "sea_water_temperature", -62.01, old, 0.2),
        row("SEAL", "sea_water_temperature", -62.02, recent, 0.4, depth=50.0, kind="TAGGED ANIMAL"),
        row("SEAL", "sea_water_salinity", -62.2, recent, 34.3, depth=6.0, kind="TAGGED ANIMAL"),
        row("AWAY", "sea_water_salinity", -70.0, recent, 34.0),
    ])
    return store, recent


def test_nearest_osmc_takes_recent_surface_values_within_reach(tmp_path):
    store, _ = _recent_store(tmp_path)
    ctx = Context(store, None, Settings())
    found = {item["variable"]: item for item in pointquery.nearest_osmc(ctx, -62.0, -58.0)}
    assert {variable: item["dataset"] for variable, item in found.items()} == {
        "sea_water_temperature": "NEAR", "sea_water_salinity": "SEAL",
    }
    assert found["sea_water_temperature"]["distance_km"] == pytest.approx(11.1, abs=0.1)
    assert found["sea_water_salinity"]["distance_km"] == pytest.approx(22.2, abs=0.1)
    assert pointquery.nearest_osmc(ctx, -62.0, 100.0) == []
    store.close()


async def test_point_query_lists_osmc_for_comparison_without_storing_it_again(tmp_path):
    store, recent = _recent_store(tmp_path)
    fetcher, _ = _fetcher(lambda request: httpx.Response(404, text="not found"))
    result = await pointquery.water(Context(store, fetcher, Settings()), -62.0, -58.0)
    rows = [row for row in result["rows"] if row["source"] == "osmc"]
    assert [(render(row["label"]), row["variable"], row["value"], row["time"], render(row["note"])) for row in rows] == [
        ("OSMC 표류 부이", "temperature", 1.5, recent, "플랫폼 NEAR, 11 km"),
        ("OSMC 계측 동물", "salinity", 34.3, recent, "플랫폼 SEAL, 22 km"),
    ]
    assert result["headline"]["temperature"] is None and result["headline"]["salinity"] is None
    assert list(store.iter_measurements(dataset="point_query")) == []
    set_language("en")
    assert [(render(row["label"]), render(row["note"])) for row in rows] == [
        ("OSMC Drifting buoy", "platform NEAR, 11 km"), ("OSMC Tagged animal", "platform SEAL, 22 km"),
    ]
    await fetcher.aclose()
    store.close()
