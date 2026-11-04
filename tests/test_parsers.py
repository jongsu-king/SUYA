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
        "platform_number,cycle_number,time,latitude,longitude,data_mode,position_qc,pres,temp,temp_qc,psal,psal_qc,"
        "temp_adjusted,temp_adjusted_qc,psal_adjusted,psal_adjusted_qc\n"
        ",,UTC,degrees_north,degrees_east,,,decibar,degree_Celsius,,PSU,,degree_Celsius,,PSU,\n"
        '1902700,78,2026-10-25T01:23:56Z,-62.83514,-62.96182,R,8,1.04,-1.372,1,33.834,1,NaN," ",NaN," "\n'
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
    assert {r.variable for r in rows} == {"air_temperature", "surface_pressure"}
    assert rows[0].location_id == "metar:NZSP"


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
