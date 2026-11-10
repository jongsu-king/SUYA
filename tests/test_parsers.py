"""조사 중 실제로 받은 응답 형태로 파서와 품질 필터를 검증합니다."""

from datetime import datetime, timezone

import pytest

from antarctic_monitor.collectors import argo, erddap, gosud, hycom, metar, openmeteo, windy, woa
from antarctic_monitor.collectors.base import to_iso_utc
from antarctic_monitor.locations import LOCATIONS


ARGO_HEADER = (
    "direction,data_mode,pres,pres_qc,temp,temp_qc,psal,psal_qc,"
    "pres_adjusted,pres_adjusted_qc,temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc\n"
    ",,decibar,,degree_Celsius,,PSU,,decibar,,degree_Celsius,,PSU,\n"
)


def test_argo_drops_bad_salinity_flagged_4():
    text = ARGO_HEADER + 'A,A,1.04,1,-0.565,1,0.014,4,1.04,1,-0.565,1,-0.019,4\n'
    levels, dropped = argo.parse_levels(text, -61.66)
    assert levels[0]["temp"] == -0.565
    assert levels[0]["salt"] is None
    assert dropped["salt"] == 1


def test_argo_uses_raw_in_realtime_mode():
    text = ARGO_HEADER + 'A,R,6.0,1,-0.82,1,34.411,1,NaN," ",NaN," ",NaN," "\n'
    levels, _ = argo.parse_levels(text, -63.44)
    assert levels[0]["temp"] == -0.82
    assert levels[0]["salt"] == 34.411


ARGO_RANGE_HEADER = (
    "cycle_number,direction,data_mode,pres,pres_qc,temp,temp_qc,psal,psal_qc,"
    "pres_adjusted,pres_adjusted_qc,temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc\n"
    ",,,decibar,,degree_Celsius,,PSU,,decibar,,degree_Celsius,,PSU,\n"
)
ARGO_RANGE_ROWS = (
    "34,A,A,5.0,1,1.0,1,34.0,1,5.0,1,1.0,1,34.0,1\n"
    "35,A,A,6.0,1,2.0,1,34.5,1,6.0,1,2.0,1,34.5,1\n"
)


def test_argo_levels_keep_only_the_requested_cycle():
    levels, _ = argo.parse_levels(ARGO_RANGE_HEADER + ARGO_RANGE_ROWS, -56.7, cycle=35)
    assert [lv["temp"] for lv in levels] == [2.0]


async def test_argo_fetch_levels_falls_back_to_a_cycle_range():
    from urllib.parse import unquote

    import httpx

    from antarctic_monitor.http import Fetcher

    queries = []

    def handler(request):
        queries.append(unquote(request.url.query.decode()))
        if "cycle_number=35" in queries[-1]:
            return httpx.Response(404, text='Error { code=404; message="Not Found: Your query produced no matching results. (nRows = 0)"; }')
        return httpx.Response(200, text=ARGO_RANGE_HEADER + ARGO_RANGE_ROWS)

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    levels, _ = await argo.fetch_levels(fetcher, "5905620", 35, -56.7)
    assert [lv["temp"] for lv in levels] == [2.0]
    assert len(queries) == 2 and "cycle_number>=34" in queries[1]
    await fetcher.aclose()


ERDDAP_NO_RESULTS = 'Error { code=404; message="Not Found: Your query produced no matching results. (nRows = 0)"; }'
ERDDAP_UNKNOWN_DATASET = 'Error { code=404; message="Not Found: Currently unknown datasetID=ArgoFloats"; }'
ARGO_LISTING_HEADER = (
    "platform_number,cycle_number,direction,time,latitude,longitude,data_mode,position_qc,"
    "pres,pres_qc,pres_adjusted,pres_adjusted_qc,temp,temp_qc,psal,psal_qc,"
    "temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc\n"
    ",,,UTC,degrees_north,degrees_east,,,decibar,,decibar,,degree_Celsius,,PSU,,degree_Celsius,,PSU,\n"
)
ARGO_LISTING = (
    ARGO_LISTING_HEADER
    + '1902700,78,A,2026-10-25T01:23:56Z,-62.83514,-62.96182,R,1,1.04,1,NaN," ",-1.372,1,33.834,1,NaN," ",NaN," "\n'
)


def _argo_fetcher(answer):
    import httpx

    from antarctic_monitor.http import Fetcher

    calls = []

    def handler(request):
        calls.append(request)
        return answer(request)

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    return fetcher, calls


async def test_argo_unknown_dataset_is_a_failure_and_not_an_empty_answer():
    import httpx

    from antarctic_monitor.http import FetchError, NoData

    fetcher, calls = _argo_fetcher(lambda request: httpx.Response(404, text=ERDDAP_UNKNOWN_DATASET))
    with pytest.raises(FetchError, match="unknown datasetID"):
        await argo.fetch_listing(fetcher)
    calls.clear()
    with pytest.raises(FetchError, match="unknown datasetID") as caught:
        await argo.fetch_levels(fetcher, "5905620", 35, -56.7)
    assert not isinstance(caught.value, NoData)
    assert len(calls) == 1
    await fetcher.aclose()


async def test_argo_no_matching_results_still_means_no_data():
    import httpx

    from antarctic_monitor.http import NoData

    fetcher, calls = _argo_fetcher(lambda request: httpx.Response(404, text=ERDDAP_NO_RESULTS))
    assert await argo.fetch_listing(fetcher) == []
    calls.clear()
    with pytest.raises(NoData):
        await argo.fetch_levels(fetcher, "5905620", 35, -56.7)
    assert len(calls) == 2
    await fetcher.aclose()


async def test_argo_collect_reports_an_empty_listing_as_a_failure(tmp_path):
    import httpx

    from antarctic_monitor.collectors.base import Context
    from antarctic_monitor.config import Settings
    from antarctic_monitor.db import Store
    from antarctic_monitor.http import FetchError

    fetcher, _ = _argo_fetcher(lambda request: httpx.Response(404, text=ERDDAP_NO_RESULTS))
    store = Store(tmp_path / "t.db")
    with pytest.raises(FetchError):
        await argo.collect(Context(store, fetcher, Settings()))
    await fetcher.aclose()
    store.close()


async def test_argo_collect_keeps_profiles_open_while_the_dataset_is_missing(tmp_path):
    import httpx

    from antarctic_monitor.collectors.base import Context
    from antarctic_monitor.config import Settings
    from antarctic_monitor.db import Store
    from antarctic_monitor.http import FetchError

    def answer(request):
        if "orderByMin" in request.url.query.decode():
            return httpx.Response(200, text=ARGO_LISTING)
        return httpx.Response(404, text=ERDDAP_UNKNOWN_DATASET)

    fetcher, _ = _argo_fetcher(answer)
    store = Store(tmp_path / "t.db")
    with pytest.raises(FetchError):
        await argo.collect(Context(store, fetcher, Settings()))
    assert store.argo_count_missing() == 1
    await fetcher.aclose()
    store.close()


ARGO_LEVELS_78 = (
    ARGO_RANGE_HEADER
    + "78,A,R,5.5,1,-1.2,1,33.9,1,NaN,,NaN,,NaN,\n"
    + "78,A,R,20.0,1,-1.1,1,34.0,1,NaN,,NaN,,NaN,\n"
)


def _argo_answers(listing, levels):
    import httpx

    def answer(request):
        if "orderByMin" in request.url.query.decode():
            return httpx.Response(200, text=listing)
        if levels is None:
            return httpx.Response(404, text=ERDDAP_NO_RESULTS)
        return httpx.Response(200, text=levels)

    return answer


def _argo_points(store):
    return {
        row["variable"]: (row["value"], row["depth_m"], row["obs_time"])
        for row in store.iter_measurements(source="argo", dataset="1902700/78")
    }


async def test_argo_collect_writes_surface_rows_from_the_levels(tmp_path):
    from antarctic_monitor.collectors.base import Context
    from antarctic_monitor.config import Settings
    from antarctic_monitor.db import Store

    fetcher, _ = _argo_fetcher(_argo_answers(ARGO_LISTING, ARGO_LEVELS_78))
    store = Store(tmp_path / "t.db")
    result = await argo.collect(Context(store, fetcher, Settings()))
    assert result.rows == 1
    points = _argo_points(store)
    assert points["sea_water_salinity"][0] == 33.9
    assert points["sea_water_temperature"][0] == -1.2
    assert points["sea_water_salinity"][1] == pytest.approx(5.4, abs=0.1)
    [ion] = list(store.iter_ions(source="argo"))
    assert ion["practical_salinity"] == 33.9 and ion["depth_m"] == points["sea_water_salinity"][1]
    await fetcher.aclose()
    store.close()


async def test_argo_collect_keeps_the_listed_value_until_levels_arrive(tmp_path):
    from antarctic_monitor.collectors.base import Context
    from antarctic_monitor.config import Settings
    from antarctic_monitor.db import Store

    fetcher, _ = _argo_fetcher(_argo_answers(ARGO_LISTING, None))
    store = Store(tmp_path / "t.db")
    await argo.collect(Context(store, fetcher, Settings()))
    points = _argo_points(store)
    assert points["sea_water_salinity"][0] == 33.834
    assert points["sea_water_salinity"][1] == pytest.approx(1.0, abs=0.1)
    await fetcher.aclose()
    store.close()


def test_argo_listing_prefers_the_ascending_row_of_a_cycle():
    text = (
        ARGO_LISTING_HEADER
        + '6903128,178,D,2026-10-28T12:08:00Z,-56.4625,68.5581,R,1,0.3,1,NaN," ",0.911,1,27.581,1,NaN," ",NaN," "\n'
        + '6903128,178,A,2026-11-07T11:03:00Z,-56.5047,68.5086,R,1,5.6,1,NaN," ",1.071,1,33.995,1,NaN," ",NaN," "\n'
        + '6903128,179,D,2026-11-08T12:00:00Z,-56.6,68.4,R,1,2.0,1,NaN," ",1.0,1,33.9,1,NaN," ",NaN," "\n'
    )
    rows = {row["cycle"]: row for row in argo.parse_listing(text)}
    assert set(rows) == {178, 179}
    assert rows[178]["direction"] == "A"
    assert rows[178]["time"] == "2026-11-07T11:03:00Z"
    assert rows[178]["surface_salt"] == 33.995
    assert rows[178]["surface_depth_m"] == pytest.approx(5.5, abs=0.1)
    assert rows[179]["direction"] == "D" and rows[179]["surface_salt"] == 33.9


def test_argo_listing_drops_values_at_a_bad_pressure():
    text = (
        ARGO_LISTING_HEADER
        + '1902700,78,A,2026-10-25T01:23:56Z,-62.83514,-62.96182,R,1,1.04,4,NaN," ",-1.372,1,33.834,1,NaN," ",NaN," "\n'
    )
    [row] = argo.parse_listing(text)
    assert row["surface_temp"] is None and row["surface_salt"] is None and row["surface_depth_m"] is None
    assert (row["platform"], row["cycle"], row["lat"]) == ("1902700", 78, -62.83514)


def test_argo_repair_rewrites_stored_surface_rows_from_the_levels(tmp_path):
    from antarctic_monitor.db import Measurement, Store

    store = Store(tmp_path / "t.db")
    base = {"time": "2026-10-28T12:08:00Z", "lat": -56.46, "lon": 68.56, "data_mode": "R", "position_qc": "1"}
    store.upsert_argo_listing([
        base | {"platform": "6903128", "cycle": 178, "surface_temp": 0.911, "surface_salt": 27.581},
        base | {"platform": "7901081", "cycle": 43, "surface_temp": 9.0, "surface_salt": 39.063},
        base | {"platform": "5900000", "cycle": 1, "surface_temp": 0.2, "surface_salt": 34.2},
    ])
    store.save_argo_levels("6903128", 178, [{"pressure_dbar": 5.6, "depth_m": 5.5, "temp": 1.071, "salt": 33.995}])
    store.save_argo_levels("7901081", 43, [{"pressure_dbar": 212.8, "depth_m": 210.7, "temp": 9.0, "salt": 39.063}])
    store.upsert_measurements(
        Measurement(
            source="argo", dataset=dataset, variable="sea_water_salinity", kind="observation",
            lat=-56.46, lon=68.56, obs_time="2026-10-28T12:08:00Z", value=value, unit="PSU", quality="R",
        )
        for dataset, value in (("6903128/178", 27.581), ("7901081/43", 39.063), ("5900000/1", 34.2))
    )
    assert argo.repair_surface(store) == 2
    rows = {
        r["dataset"]: (r["value"], r["depth_m"])
        for r in store.iter_measurements(source="argo", variable="sea_water_salinity")
    }
    assert rows == {"6903128/178": (33.995, 5.5), "5900000/1": (34.2, None)}
    assert store.argo_profile("7901081", 43)["surface_salt"] is None
    assert {r["dataset"]: r["practical_salinity"] for r in store.iter_ions(source="argo")} == {
        "6903128/178": 33.995, "5900000/1": 34.2,
    }
    assert store.kv_get(argo.SURFACE_KEY) == argo.SURFACE_RULE
    assert argo.repair_surface(store) == 0
    store.close()


def test_argo_repair_does_not_count_a_rounding_difference(tmp_path):
    from antarctic_monitor.db import Measurement, Store

    store = Store(tmp_path / "t.db")
    store.upsert_argo_listing([{
        "platform": "5906915", "cycle": 149, "time": "2026-10-20T03:11:51Z", "lat": -57.1, "lon": 30.2,
        "data_mode": "A", "position_qc": "1", "surface_temp": None, "surface_salt": 34.0617,
    }])
    store.save_argo_levels("5906915", 149, [{"pressure_dbar": 0.6, "depth_m": 0.6, "temp": None, "salt": 34.062}])
    store.upsert_measurements([
        Measurement(
            source="argo", dataset="5906915/149", variable="sea_water_salinity", kind="observation",
            lat=-57.1, lon=30.2, obs_time="2026-10-20T03:11:51Z", value=34.0617, unit="PSU", quality="A",
        )
    ])
    assert argo.repair_surface(store) == 0
    [row] = store.iter_measurements(source="argo", variable="sea_water_salinity")
    assert (row["value"], row["depth_m"]) == (34.062, 0.6)
    store.close()


def test_argo_prefers_adjusted_in_delayed_mode():
    text = ARGO_HEADER + "A,D,100.0,1,0.5,1,34.0,1,100.1,1,0.52,1,34.2,1\n"
    levels, _ = argo.parse_levels(text, -65.0)
    assert levels[0]["pressure_dbar"] == 100.1
    assert levels[0]["temp"] == 0.52
    assert levels[0]["salt"] == 34.2


def test_argo_ignores_descending_when_ascending_exists():
    text = ARGO_HEADER + "D,R,10.0,1,9.9,1,30.0,1,NaN,,NaN,,NaN,\nA,R,10.0,1,0.1,1,34.0,1,NaN,,NaN,,NaN,\n"
    levels, _ = argo.parse_levels(text, -65.0)
    assert len(levels) == 1
    assert levels[0]["temp"] == 0.1


def test_argo_rejects_physically_impossible_values_even_with_good_flag():
    assert argo.select_value("R", "99.0", "1", None, None, argo.VALID_TEMP) is None


def test_argo_listing_parses_coordinates_and_mode():
    text = (
        ARGO_LISTING_HEADER
        + '1902700,78,A,2026-10-25T01:23:56Z,-62.83514,-62.96182,R,8,1.04,1,NaN," ",-1.372,1,33.834,1,NaN," ",NaN," "\n'
    )
    [row] = argo.parse_listing(text)
    assert row["platform"] == "1902700"
    assert row["cycle"] == 78
    assert row["surface_salt"] == 33.834
    assert row["position_qc"] == "8"


def test_gosud_drops_flag_4():
    text = (
        "ship_call_sign,time,latitude,longitude,SSTP,SSTP_QC,SSPS,SSPS_QC\n,UTC,,,,,,\n"
        "9V5255,2026-06-19T05:00:00Z,-59.3,20.8,26,4,NaN,0\n"
        "RCLKYXB,2026-08-09T11:00:00Z,-60,-146.1,11.8,1,34.1,1\n"
    )
    rows = gosud.parse_rows(text)
    assert {(r.dataset, r.variable) for r in rows} == {
        ("RCLKYXB", "sea_water_temperature"), ("RCLKYXB", "sea_water_salinity"),
    }


HYCOM_ASCII = """Dataset {
    Grid {
     ARRAY:
        Float32 water_temp[time = 1][depth = 1][lat = 3][lon = 3];
    } water_temp;
} FMRC_ESPC-D-V02_t3z/FMRC_ESPC-D-V02_t3z_best.ncd;
---------------------------------------------
water_temp.water_temp[1][1][3][3]
[0][0][0], -0.05600095, -1.2550011, NaN
[0][0][1], 1.6539991, 0.124999054, -1.183001
[0][0][2], 2.077999, 2.554999, -1.231001

water_temp.time[1]
180.0

water_temp.depth[1]
100.0

water_temp.lat[3]
-65.0, -63.0, -61.0

water_temp.lon[3]
240.0, 288.0, 336.0

"""


def test_hycom_ascii_parser_reads_values_and_axes():
    parsed = hycom.parse_opendap_ascii(HYCOM_ASCII)
    assert parsed["values"][0] == pytest.approx(-0.05600095)
    assert parsed["values"][2] is None
    assert len(parsed["values"]) == 9
    assert parsed["maps"]["lat"] == [-65.0, -63.0, -61.0]
    assert parsed["maps"]["lon"] == [240.0, 288.0, 336.0]
    assert parsed["maps"]["depth"] == [100.0]


def test_hycom_error_response_raises():
    with pytest.raises(Exception, match="오류"):
        hycom.parse_opendap_ascii('Error {\n    code = 500;\n    message = "null";\n};\n')


def test_hycom_time_origin_and_nearest():
    das = 'Attributes {\n tau { String units "hours since analysis"; }\n time {\n String units "hours since 2026-10-25T12:00:00Z";\n }\n}'
    origin = hycom.parse_time_origin(das)
    assert origin == datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    index, valid = hycom.nearest_time([0.0, 3.0, 6.0], origin, datetime(2026, 10, 25, 16, 0, tzinfo=timezone.utc))
    assert index == 1
    assert valid == datetime(2026, 10, 25, 15, tzinfo=timezone.utc)


def test_hycom_indices():
    assert hycom.lat_index(-65.0) == 375
    assert hycom.lon_index(-60.0) == 3750
    assert hycom.lon_index(0.0) == 0


def test_satellite_salinity_rejects_impossible_values():
    rows = [
        {"latitude": -60.0, "longitude": 0.0, "sss": 0.0},
        {"latitude": -60.0, "longitude": 1.0, "sss": 42.83},
        {"latitude": -60.0, "longitude": 2.0, "sss": 34.1},
        {"latitude": -60.0, "longitude": 3.0, "sss": None},
    ]
    [grid] = erddap.rows_to_grids(erddap.SMAP, rows, "2026-11-01T12:00:00Z")
    assert grid.values == [None, None, 34.1, None]
    assert grid.meta["rejected_out_of_range"] == 2


def test_oisst_splits_into_three_layers():
    rows = [{"latitude": -70.0, "longitude": 0.0, "sst": -1.5, "anom": 0.2, "ice": 0.8}]
    grids = {g.layer: g for g in erddap.rows_to_grids(erddap.OISST, rows, "2026-11-02T12:00:00Z")}
    assert set(grids) == {"oisst_sst", "oisst_anom", "oisst_ice"}
    assert grids["oisst_ice"].values == [0.8]


def test_griddap_url_encodes_brackets():
    url = erddap.griddap_url("https://x/erddap", "ds", "time[(last)]")
    assert url == "https://x/erddap/griddap/ds.json?time%5B(last)%5D"


def test_marine_flags_land_cell():
    payload = {"elevation": 1023.0, "current": {"time": "2026-11-04T02:15", "sea_surface_temperature": -1.8}}
    assert openmeteo.marine_value(payload) == (-1.8, "2026-11-04T02:15:00Z", True)
    ocean = {"elevation": 0.0, "current": {"time": "2026-11-04T02:15", "sea_surface_temperature": -1.7}}
    assert openmeteo.marine_value(ocean)[2] is False


def test_current_parser_maps_variables_and_units():
    loc = LOCATIONS[0]
    payload = {"current": {"time": "2026-11-04T02:30", "temperature_2m": -13.3, "relative_humidity_2m": 72, "dew_point_2m": None}}
    rows = {r.variable: r for r in openmeteo.parse_current([payload], (loc,))}
    assert rows["air_temperature"].value == -13.3
    assert rows["air_temperature"].obs_time == "2026-11-04T02:30:00Z"
    assert rows["relative_humidity"].unit == "%"
    assert "dew_point" not in rows


def test_hourly_models_skip_missing_values():
    loc = LOCATIONS[0]
    payload = {"hourly": {"time": ["2026-11-04T00:00", "2026-11-04T01:00"], "temperature_2m_gfs_global": [-26.7, None]}}
    rows = openmeteo.parse_hourly_models([payload], (loc,))
    assert len(rows) == 1
    assert rows[0].dataset == "gfs_global"


def test_metar_keeps_station_without_dewpoint():
    payload = [{"icaoId": "NZSP", "obsTime": 1793757000, "temp": -46, "dewp": None, "lat": -89.98, "lon": 180, "altim": 690.0, "name": "Amundsen-South Pole, NZ, AQ"}]
    rows = metar.parse_reports(payload)
    assert {r.variable for r in rows} == {"air_temperature", "sea_level_pressure"}
    assert rows[0].location_id == "metar:NZSP"


def _metar_report(temp, dewp, altim=987):
    return {"icaoId": "SAWB", "obsTime": 1793934000, "temp": temp, "dewp": dewp, "lat": -64.2383, "lon": -56.6308, "altim": altim, "name": "Gustavo Marambio Arpt, U-A, AQ"}


def test_metar_drops_temperature_outside_the_plausible_range():
    rows = metar.parse_reports([_metar_report(48, -8)])
    assert {r.variable: r.value for r in rows} == {"dew_point": -8.0, "sea_level_pressure": 987.0}


def test_metar_drops_both_when_dew_point_is_above_temperature():
    rows = metar.parse_reports([_metar_report(-4, 9, altim=974)])
    assert {r.variable: r.value for r in rows} == {"sea_level_pressure": 974.0}


def test_metar_keeps_saturated_air_and_real_extremes():
    rows = metar.parse_reports([_metar_report(-2, -2), _metar_report(-89, None)])
    assert sorted(r.value for r in rows if r.variable == "air_temperature") == [-89.0, -2.0]
    assert [r.value for r in rows if r.variable == "dew_point"] == [-2.0]


def test_woa_csv_and_deep_fill():
    text = (
        'time,alt[unit="meters"],station,latitude[unit="degrees_north"],longitude[unit="degrees_east"],s_an[unit="1"]\n'
        "1988-11-15T13:54:27.393Z,1.25,GridPointRequestedAt[65.000S_50.000W],-64.875,-49.875,34.38221\n"
        "1988-11-15T13:54:27.393Z,5.0,GridPointRequestedAt[65.000S_50.000W],-64.875,-49.875,NaN\n"
    )
    assert woa.parse_csv_profile(text) == {1.25: 34.38221}
    assert woa._merge({0.0: 1.0, 1500.0: 2.0}, {0.0: 9.0, 2000.0: 3.0}) == {0.0: 1.0, 1500.0: 2.0, 2000.0: 3.0}


def test_windy_converts_kelvin_and_pascal():
    payload = {
        "ts": [1793757000000, 1793767800000],
        "units": {"temp-surface": "K", "temp-850h": "K", "pressure-surface": "Pa", "rh-surface": "%"},
        "temp-surface": [260.65, None],
        "temp-850h": [250.0, 251.0],
        "pressure-surface": [98500.0, 98400.0],
        "rh-surface": [70.0, 71.0],
        "warning": "test key",
    }
    rows = windy.parse_response(payload)
    surface = [r for r in rows if r["variable"] == "air_temperature" and r["level"] == "surface"]
    assert len(surface) == 1
    assert surface[0]["value"] == pytest.approx(-12.5)
    assert surface[0]["unit"] == "°C"
    pressure = next(r for r in rows if r["variable"] == "surface_pressure")
    assert pressure["value"] == 985.0
    assert pressure["unit"] == "hPa"


def test_time_normalization():
    assert to_iso_utc("2026-11-04T02:15") == "2026-11-04T02:15:00Z"
    assert to_iso_utc("2026-11-04") == "2026-11-04T00:00:00Z"
    assert to_iso_utc("2026-11-04T02:00:00.000Z") == "2026-11-04T02:00:00Z"
