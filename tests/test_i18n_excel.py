"""다국어 메시지와 월별 엑셀 축적을 검증합니다."""

from datetime import datetime, timezone

import openpyxl
import pytest

from antarctic_monitor import excel, i18n
from antarctic_monitor.db import Measurement, Store
from antarctic_monitor.gridutil import grid_from_triples
from antarctic_monitor.i18n import join, msg, render, set_language, tr


@pytest.fixture(autouse=True)
def korean():
    set_language("ko")
    yield
    set_language("ko")


def test_tr_switches_language_and_formats():
    assert tr("해역 {n}곳", n=3) == "해역 3곳"
    set_language("en")
    assert tr("해역 {n}곳", n=3) == "3 sea areas"
    assert tr("없는 문장") == "없는 문장"


def test_every_english_entry_keeps_placeholders():
    import re

    for korean_text, english in i18n.EN.items():
        assert set(re.findall(r"{(\w+)}", korean_text)) == set(re.findall(r"{(\w+)}", english)), korean_text


def test_stored_messages_render_in_both_languages():
    stored = join(msg("해역 {n}곳", n=10), msg("실패 {n}곳", n=1), "plain text")
    assert render(stored) == "해역 10곳, 실패 1곳, plain text"
    set_language("en")
    assert render(stored) == "10 sea areas, 1 failed, plain text"
    assert render(None) == ""
    assert render("legacy message") == "legacy message"


def test_nested_messages_render_in_both_languages():
    inner = msg("프로파일 없음: {platform}/{cycle}", platform="5905620", cycle=35)
    outer = msg("Argo 프로파일을 받지 못했습니다: {error}", error=inner)
    assert render(outer) == "Argo 프로파일을 받지 못했습니다: 프로파일 없음: 5905620/35"
    set_language("en")
    assert render(outer) == "Could not fetch Argo profiles: Profile not found: 5905620/35"
    assert "\x1f" not in render(outer)
    plain = msg("Argo 프로파일을 받지 못했습니다: {error}", error="HTTP 500")
    assert render(plain) == "Could not fetch Argo profiles: HTTP 500"


def test_unsupported_language_rejected():
    with pytest.raises(ValueError):
        set_language("fr")


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "t.db")
    store.upsert_measurements([
        Measurement("oisst", "ds", "sea_water_temperature", "analysis", -68.0, -40.0, "2026-11-02T12:00:00Z", -1.5, "°C", location_id="weddell"),
        Measurement("hycom", "ESPC", "sea_water_salinity", "model", -68.0, -40.0, "2026-11-03T00:00:00Z", 34.1, "PSU", level="depth:100", depth_m=100.0, location_id="weddell"),
        Measurement("hycom", "ESPC", "sea_water_temperature", "model", -68.0, -40.0, "2026-11-03T00:00:00Z", 0.2, "°C", level="depth:100", depth_m=100.0, location_id="weddell"),
        Measurement("metar", "NZSP", "air_temperature", "observation", -89.98, 180.0, "2026-11-03T06:00:00Z", -46.0, "°C", level="2m", location_id="metar:NZSP", quality="South Pole"),
        Measurement("gosud", "SHIP1", "sea_water_temperature", "observation", -60.0, 0.0, "2026-10-20T00:00:00Z", 2.0, "°C", quality="1"),
        Measurement("openmeteo", "gfs_global", "air_temperature", "model", -62.2, -58.8, "2026-11-03T06:00:00Z", -3.0, "°C", level="2m", location_id="king_sejong"),
        Measurement("openmeteo", "ecmwf_ifs025", "air_temperature", "forecast", -62.2, -58.8, "2026-11-05T06:00:00Z", -2.0, "°C", level="2m", location_id="king_sejong"),
        Measurement("oisst", "point_query", "sea_water_temperature", "analysis", -66.0, -66.0, "2026-11-02T12:00:00Z", -1.6, "°C"),
    ])
    store.save_grid(grid_from_triples("oisst_sst", "2026-11-02T12:00:00Z", "°C", [(-70.0, 0.0, -1.0), (-70.0, 10.0, -1.2)]))
    store.upsert_argo_listing([{
        "platform": "1", "cycle": 2, "time": "2026-11-01T00:00:00Z", "lat": -65.0, "lon": 0.0, "data_mode": "R",
        "position_qc": "1", "surface_temp": 1.0, "surface_salt": 34.0,
    }])
    store.save_argo_levels("1", 2, [{"pressure_dbar": 5.0, "depth_m": 5.0, "temp": 1.0, "salt": 34.0}, {"pressure_dbar": 50.0, "depth_m": 49.7, "temp": 0.5, "salt": 34.2}])
    return store


def test_month_bounds_and_listing():
    assert excel.month_bounds("2026-11") == ("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
    assert excel.month_bounds("2026-12") == ("2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z")


def test_sync_writes_month_files_with_expected_sheets(tmp_path):
    store = _store(tmp_path)
    assert store.months_with_data() == ["2026-10", "2026-11"]
    result = excel.sync(store, tmp_path / "xl", ["2026-11"])
    assert result["files"] == ["antarctic_db_2026-11.xlsx", "argo_levels_2026-11.xlsx"]
    book = openpyxl.load_workbook(tmp_path / "xl" / "antarctic_db_2026-11.xlsx", read_only=True)
    names = {ws.title: ws for ws in book.worksheets}
    assert "정보" in names and "격자평균" in names and "Argo_목록" in names
    water = list(names["수온염분_해역"].iter_rows(values_only=True))
    assert water[0][:3] == ("시각 UTC", "지점", "위도")
    assert water[1][1] == "웨델해" and water[1][7] == -1.5
    assert water[1][0] == datetime(2026, 11, 2, 12, 0)
    vertical = list(names["수온염분_수직"].iter_rows(values_only=True))
    assert vertical[1][4:7] == (100.0, 0.2, 34.1)
    forecast = list(names["모델예보"].iter_rows(values_only=True))
    assert forecast[1][5] == -2.0
    assert list(names["선박관측"].iter_rows(values_only=True)) [1:] == []
    points = list(names["지점조회"].iter_rows(values_only=True))
    assert points[1][3] == "oisst"
    argo = openpyxl.load_workbook(tmp_path / "xl" / "argo_levels_2026-11.xlsx", read_only=True).worksheets[0]
    assert argo.max_row == 3
    store.close()


def test_sync_english_headers(tmp_path):
    set_language("en")
    store = _store(tmp_path)
    excel.sync(store, tmp_path / "xl", ["2026-10"])
    book = openpyxl.load_workbook(tmp_path / "xl" / "antarctic_db_2026-10.xlsx", read_only=True)
    titles = [ws.title for ws in book.worksheets]
    assert titles[:4] == ["Info", "Monthly summary", "Grid means", "Water by area"]
    ships = list(book["Ships"].iter_rows(values_only=True))
    assert ships[0][1] == "Call sign" and ships[1][1] == "SHIP1"
    store.close()


def test_monthly_summary_sheet_compares_with_the_previous_month(tmp_path):
    store = Store(tmp_path / "t.db")

    def oisst(when, value):
        return Measurement("oisst", "ds", "sea_water_temperature", "analysis", -68.0, -40.0, when, value, "°C", location_id="weddell")

    store.upsert_measurements([
        oisst("2026-10-31T12:00:00Z", -1.0),
        oisst("2026-11-01T12:00:00Z", -1.0),
        oisst("2026-11-02T12:00:00Z", -2.0),
        Measurement("hycom", "ESPC", "sea_water_salinity", "model", -68.0, -40.0, "2026-11-03T00:00:00Z", 34.0, "PSU", level="depth:0", depth_m=0.0, location_id="weddell"),
        Measurement("hycom", "ESPC", "sea_water_salinity", "model", -68.0, -40.0, "2026-11-03T00:00:00Z", 34.5, "PSU", level="depth:100", depth_m=100.0, location_id="weddell"),
        Measurement("openmeteo", "ecmwf_ifs025", "air_temperature", "forecast", -62.2, -58.8, "2026-11-05T06:00:00Z", -2.0, "°C", level="2m", location_id="king_sejong"),
        Measurement("oisst", "point_query", "sea_water_temperature", "analysis", -66.0, -66.0, "2026-11-02T12:00:00Z", -1.6, "°C"),
    ])
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    book = openpyxl.load_workbook(tmp_path / "xl" / "antarctic_db_2026-11.xlsx", read_only=True)
    assert book.sheetnames[:2] == ["정보", "월간요약"]
    rows = list(book["월간요약"].iter_rows(values_only=True))
    assert rows[0][:6] == ("지점", "자료", "항목", "단위", "표본 수", "평균")
    assert len(rows) == 3
    salinity = next(row for row in rows[1:] if row[1] == "hycom")
    assert salinity[2] == "염분" and salinity[5] == 34.0 and salinity[4] == 1
    assert salinity[11] is None and salinity[12] is None
    water = next(row for row in rows[1:] if row[1] == "oisst")
    assert water[0] == "웨델해" and water[2] == "수온" and water[3] == "°C" and water[4] == 2
    assert water[5:9] == (-1.5, -2.0, -1.0, 0.5)
    assert water[9] == datetime(2026, 11, 1, 12, 0) and water[10] == datetime(2026, 11, 2, 12, 0)
    assert water[11] == -1.0 and water[12] == -0.5
    store.close()


def test_previous_month_crosses_the_year():
    assert excel.previous_month("2027-01") == "2026-12"
    assert excel.previous_month("2026-11") == "2026-10"


def test_months_to_write_skips_finished_months(tmp_path):
    store = _store(tmp_path)
    folder = tmp_path / "xl"
    now = datetime(2027, 3, 15, tzinfo=timezone.utc)
    assert excel.months_to_write(store, folder, now) == ["2026-10", "2026-11"]
    excel.sync(store, folder, ["2026-10", "2026-11"])
    assert excel.months_to_write(store, folder, now) == ["2027-03"]
    store.close()


def test_sheet_splits_at_excel_row_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(excel, "EXCEL_ROW_LIMIT", 4)
    book = excel.Book(tmp_path / "split.xlsx")
    sheet = excel.Sheet(book, "격자평균", [("값", 8)])
    for value in range(6):
        sheet.add([value])
    assert sheet.finish() == 6
    book.close()
    titles = [ws.title for ws in openpyxl.load_workbook(tmp_path / "split.xlsx").worksheets]
    assert titles == ["격자평균", "격자평균_2"]


def test_book_replaces_file_atomically(tmp_path):
    target = tmp_path / "x.xlsx"
    target.write_bytes(b"old")
    book = excel.Book(target)
    book.workbook.add_worksheet("a")
    book.close()
    assert target.stat().st_size > 100
    assert not list(tmp_path.glob(".*.tmp.xlsx"))
