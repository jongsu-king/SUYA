"""이온 환산값이 엑셀, CSV, 명령줄, 지점 조회로 나가는 길을 검증합니다."""

import argparse
import csv
import json
import types

import openpyxl
import pytest

from antarctic_monitor import cli, composition, excel, exporter, pointquery
from antarctic_monitor.db import ARGO_ION_COLUMNS, ION_GRAM_COLUMNS, ION_MMOL_COLUMNS, Measurement, Store
from antarctic_monitor.i18n import set_language


@pytest.fixture(autouse=True)
def korean():
    set_language("ko")
    yield
    set_language("ko")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_measurements([
        Measurement("hycom", "ESPC", "sea_water_salinity", "model", -68.0, -40.0, "2026-11-03T00:00:00Z", 34.1, "PSU", level="depth:100", depth_m=100.0, location_id="weddell"),
        Measurement("smos", "L3", "sea_water_salinity", "satellite", -62.2, -58.8, "2026-11-04T00:00:00Z", 33.6, "PSU", location_id="king_sejong"),
        Measurement("oisst", "ds", "sea_water_temperature", "analysis", -68.0, -40.0, "2026-11-02T12:00:00Z", -1.5, "°C", location_id="weddell"),
    ])
    store.upsert_argo_listing([{
        "platform": "1", "cycle": 2, "time": "2026-11-01T00:00:00Z", "lat": -65.0, "lon": 0.0, "data_mode": "R",
        "position_qc": "1", "surface_temp": 1.0, "surface_salt": 34.0,
    }])
    store.save_argo_levels("1", 2, [
        {"pressure_dbar": 5.0, "depth_m": 5.0, "temp": 1.0, "salt": 34.0},
        {"pressure_dbar": 50.0, "depth_m": 49.7, "temp": 0.5, "salt": 34.2},
        {"pressure_dbar": 100.0, "depth_m": 99.2, "temp": 0.4, "salt": None},
    ])
    yield store
    store.close()


def _sheets(path) -> dict:
    book = openpyxl.load_workbook(path, read_only=True)
    return {sheet.title: list(sheet.iter_rows(values_only=True)) for sheet in book.worksheets}


def test_main_workbook_has_the_ion_sheets(store, tmp_path):
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    sheets = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")
    ions = sheets["이온조성"]
    header = ions[0]
    assert header[:10] == ("시각 UTC", "지점", "위도", "경도", "자료", "종류", "층", "수심 m", "염분 PSU", "기준 염분 g/kg")
    assert header[10:18] == tuple(f"{item.symbol} g/kg" for item in composition.MAJOR)
    assert header[18:26] == tuple(f"{item.symbol} mmol/kg" for item in composition.MAJOR)
    assert len(ions) == 3
    row = next(line for line in ions[1:] if line[4] == "hycom")
    assert row[6:9] == ("depth:100", 100.0, 34.1)
    assert row[9] == pytest.approx(composition.reference_salinity(34.1), abs=1e-4)
    grams = composition.grams_per_kg(34.1, composition.MAJOR)
    mmol = composition.mmol_per_kg(34.1, composition.MAJOR)
    assert row[10:18] == pytest.approx([grams[item.key] for item in composition.MAJOR], abs=1e-5)
    assert row[18:26] == pytest.approx([mmol[item.key] for item in composition.MAJOR], abs=1e-4)


def test_factor_sheet_lists_every_component(store, tmp_path):
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    factors = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")["이온환산계수"]
    assert factors[0][:3] == ("성분", "기호", "전하") and factors[0][-1] == "DB 열"
    assert len(factors) == 1 + len(composition.COMPONENTS)
    chloride = factors[1]
    assert chloride[:3] == ("염화 이온", "Cl⁻", -1)
    assert chloride[7] == pytest.approx(19.3527, abs=1e-3) and chloride[-1] == "chloride_g_kg"
    assert sum(line[4] for line in factors[1:]) == pytest.approx(100.0, abs=1e-3)
    stored = [line[-1] for line in factors[1:] if line[-1]]
    assert stored == list(ION_GRAM_COLUMNS)


def test_info_sheet_says_the_ions_are_derived(store, tmp_path):
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    info = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")["정보"]
    note = next(line for line in info if line[0] == "이온 환산")
    assert "환산값" in note[1] and "직접 잰 값이 아님" in note[1]
    top = next(index for index, line in enumerate(info) if line[0] == "시트")
    counts = {line[0]: line[1] for line in info[top + 1:] if line[0]}
    assert counts["이온조성"] == 2 and counts["이온환산계수"] == len(composition.COMPONENTS)


def test_ion_sheets_in_english(store, tmp_path):
    set_language("en")
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    sheets = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")
    assert sheets["Ion composition"][0][8:10] == ("Salinity PSU", "Reference salinity g/kg")
    assert sheets["Ion factors"][1][0] == "Chloride"
    note = next(line for line in sheets["Info"] if line[0] == "Ion conversion")
    assert "not direct ion measurements" in note[1]


def test_argo_workbook_carries_ions_for_each_level(store, tmp_path):
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    levels = next(iter(_sheets(tmp_path / "xl" / "argo_levels_2026-11.xlsx").values()))
    header = levels[0]
    start = header.index("기준 염분 g/kg")
    assert header[start + 1:start + 9] == tuple(f"{item.symbol} g/kg" for item in composition.MAJOR)
    assert len(levels) == 4
    first = levels[1]
    grams = composition.grams_per_kg(34.0, composition.MAJOR)
    assert first[start] == pytest.approx(composition.reference_salinity(34.0), abs=1e-4)
    assert first[start + 1:start + 9] == pytest.approx([grams[item.key] for item in composition.MAJOR], abs=1e-5)
    missing = levels[3]
    assert all(value is None for value in missing[start:start + 9])


def test_argo_level_ions_are_read_in_batches(store):
    rows = list(store.iter_argo_level_ions(batch=1))
    assert [row["pressure_dbar"] for row in rows] == [5.0, 50.0]
    assert set(ARGO_ION_COLUMNS) <= set(rows[0])
    assert rows[1]["chloride_g_kg"] == pytest.approx(composition.grams_per_kg(34.2)["chloride"], abs=1e-9)
    assert store.count_argo_level_ions() == 2
    assert list(store.iter_argo_level_ions(since="2026-12-01T00:00:00Z")) == []


def test_export_ions_writes_grams_and_mmol(store, tmp_path):
    out = tmp_path / "ions.csv"
    assert exporter.export_ions(store, out) == 2
    with out.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert set(ION_GRAM_COLUMNS) | set(ION_MMOL_COLUMNS) <= set(rows[0])
    hycom = next(row for row in rows if row["source"] == "hycom")
    assert float(hycom["practical_salinity"]) == 34.1
    assert float(hycom["sodium_g_kg"]) == pytest.approx(composition.grams_per_kg(34.1)["sodium"], abs=1e-9)
    assert float(hycom["sodium_mmol_kg"]) == pytest.approx(composition.mmol_per_kg(34.1)["sodium"], abs=1e-9)
    assert exporter.export_ions(store, out, source="smos") == 1


def test_export_argo_ions_writes_one_row_per_level(store, tmp_path):
    out = tmp_path / "argo_ions.csv"
    assert exporter.export_argo_ions(store, out) == 2
    with out.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == list(ARGO_ION_COLUMNS)
    assert float(rows[0]["practical_salinity"]) == 34.0


def test_cli_export_reaches_both_ion_files(store, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: types.SimpleNamespace(db_path=tmp_path / "t.db"))
    for what, expected in (("ions", 2), ("argo-ions", 2)):
        out = tmp_path / f"{what}.csv"
        cli._export(argparse.Namespace(what=what, out=str(out), source=None, variable=None, since=None, layer=None))
        assert f"{expected} rows" in capsys.readouterr().out and out.exists()


def test_cli_converts_one_salinity(capsys):
    cli._ions(argparse.Namespace(salinity=35.0, json=False))
    out = capsys.readouterr().out
    assert "35.1650" in out and "19.35271" in out and "Cl⁻" in out and "염화 이온" in out
    assert "이온을 직접 잰 값이 아닙니다" in out
    set_language("en")
    cli._ions(argparse.Namespace(salinity=35.0, json=False))
    out = capsys.readouterr().out
    assert "Reference salinity S_R: 35.1650 g/kg" in out and "Chloride" in out and "not direct ion measurements" in out


def test_cli_ion_json_matches_the_module(capsys):
    cli._ions(argparse.Namespace(salinity=34.5, json=True))
    result = json.loads(capsys.readouterr().out)
    assert result["method"] == composition.METHOD and len(result["ions"]) == len(composition.COMPONENTS)
    assert result["ions"][0]["g_per_kg"] == pytest.approx(composition.grams_per_kg(34.5)["chloride"])


@pytest.mark.parametrize("salinity", [0.0, -1.0, float("nan")])
def test_cli_rejects_a_salinity_that_cannot_be_converted(salinity):
    with pytest.raises(SystemExit):
        cli._ions(argparse.Namespace(salinity=salinity, json=False))


def test_ion_self_check_reads_back_the_database_row(tmp_path):
    assert cli._ion_check(tmp_path) == "ions ok Cl 19.3527 g/kg at salinity 35"


def test_point_query_salinity_adds_ion_rows(tmp_path):
    store = Store(tmp_path / "p.db")
    ctx = types.SimpleNamespace(store=store)
    rows = [
        {"source": "hycom", "label": "HYCOM 0 m", "kind": "model", "variable": "salinity", "unit": "PSU", "value": 34.3, "time": "2026-11-04T00:00:00Z", "note": None},
        {"source": "smos", "label": "SMOS", "kind": "satellite", "variable": "salinity", "unit": "PSU", "value": None, "time": "2026-11-04T00:00:00Z", "note": None},
        {"source": "argo", "label": "Argo", "kind": "observation", "variable": "salinity", "unit": "PSU", "value": 34.0, "time": "2026-11-03T00:00:00Z", "note": None},
        {"source": "oisst", "label": "OISST", "kind": "analysis", "variable": "temperature", "unit": "°C", "value": -1.2, "time": "2026-11-04T00:00:00Z", "note": None},
    ]
    pointquery._store_water_rows(ctx, rows, -65.1234, 10.5678)
    ions = list(store.iter_ions())
    store.close()
    assert len(ions) == 1
    assert (ions[0]["source"], ions[0]["lat"], ions[0]["lon"]) == ("hycom", -65.123, 10.568)
    assert ions[0]["chloride_g_kg"] == pytest.approx(composition.grams_per_kg(34.3)["chloride"], abs=1e-9)
