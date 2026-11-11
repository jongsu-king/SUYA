"""전 해역 염분 격자의 이온 환산이 DB 뷰, CSV, 엑셀, 지도 눈금으로 나가는 길을 검증합니다."""

import argparse
import csv
import math
import os
import subprocess
import sys
import types

import numpy as np
import openpyxl
import pytest

from antarctic_monitor import cli, composition, excel, exporter, ranges
from antarctic_monitor.collectors import hycom
from antarctic_monitor.db import (
    GRID_ALL,
    GRID_AREAS,
    GRID_CELL_ION_COLUMNS,
    GRID_DEPTH_PREFIX,
    GRID_ION_COLUMNS,
    ION_CHECK,
    ION_GRAM_COLUMNS,
    ION_MMOL_COLUMNS,
    Measurement,
    Store,
    grid_depth,
)
from antarctic_monitor.gridutil import ANTARCTIC_LAT, SECTORS, grid_from_triples, grid_stats
from antarctic_monitor.gui.scales import build_scale, legend_ticks, rescale
from antarctic_monitor.i18n import render, set_language

FIRST = "2026-11-03T00:00:00Z"
SECOND = "2026-11-04T00:00:00Z"
MID = [
    (-70.0, -30.0, 34.2), (-70.0, 170.0, 34.6),
    (-65.0, -30.0, 34.4), (-65.0, 170.0, None),
    (-55.0, -30.0, 33.9), (-55.0, 170.0, None),
]
DEEP = [(-70.0, -100.0, 35.2), (-70.0, -30.0, 34.7)]
SURFACE = [(-66.0, 30.0, 33.5), (-66.0, 100.0, 33.8)]
NORTH = [(-50.0, 0.0, 34.0)]
EXPECTED = [
    ("hycom_salt_100", GRID_ALL), ("hycom_salt_100", "weddell"), ("hycom_salt_100", "ross"),
    ("hycom_salt_2000", GRID_ALL), ("hycom_salt_2000", "weddell"), ("hycom_salt_2000", "amundsen_bell"),
    ("smos_sss", GRID_ALL), ("smos_sss", "indian"), ("smos_sss", "west_pacific"),
]


def _grids() -> list:
    return [
        grid_from_triples("hycom_salt_100", FIRST, "PSU", MID, {"depth_m": 100}),
        grid_from_triples("hycom_salt_2000", FIRST, "PSU", DEEP),
        grid_from_triples("hycom_temp_100", FIRST, "°C", [(-70.0, -30.0, 0.5), (-65.0, -30.0, 1.5)], {"depth_m": 100}),
        grid_from_triples("smos_sss", SECOND, "PSU", SURFACE),
        grid_from_triples("smap_sss", SECOND, "PSU", NORTH),
    ]


@pytest.fixture(autouse=True)
def korean():
    set_language("ko")
    yield
    set_language("ko")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "t.db")
    for grid in _grids():
        store.save_grid(grid)
    yield store
    store.close()


def _rows(store, **filters) -> dict:
    return {(row["layer"], row["area"]): row for row in store.iter_grid_ions(**filters)}


def _sheets(path) -> dict:
    book = openpyxl.load_workbook(path, read_only=True)
    return {sheet.title: list(sheet.iter_rows(values_only=True)) for sheet in book.worksheets}


def _cell(row, index):
    return row[index] if index < len(row) else None


def _read(path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_layer_depth_follows_the_hycom_layer_names():
    assert GRID_DEPTH_PREFIX == f"{hycom.LAYER_PREFIX['salinity']}_"
    for depth in hycom.MAP_DEPTHS:
        assert grid_depth(f"{GRID_DEPTH_PREFIX}{depth}") == float(depth)
    assert grid_depth("smos_sss") == grid_depth("smap_sss") == 0.0
    assert grid_depth("hycom_temp_100") == 0.0
    assert GRID_AREAS == (GRID_ALL, *(key for key, *_ in SECTORS))


def test_view_has_one_row_per_area_with_a_mean(store):
    rows = list(store.iter_grid_ions())
    assert [(row["layer"], row["area"]) for row in rows] == EXPECTED
    assert store.count_grid_ions() == len(EXPECTED)
    assert all(tuple(row) == GRID_ION_COLUMNS for row in rows)
    kind = store._conn.execute("SELECT type FROM sqlite_master WHERE name = 'grid_ions'").fetchone()[0]
    assert kind == "view"


def test_view_rows_convert_the_stored_means(store):
    rows = _rows(store)
    for grid in _grids():
        if grid.unit != "PSU":
            continue
        stats = grid_stats(grid)
        means = {GRID_ALL: stats, **stats["sectors"]}
        for area, part in means.items():
            row = rows.get((grid.layer, area))
            if part["mean"] is None:
                assert row is None
                continue
            salinity = part["mean"]
            assert row["practical_salinity"] == salinity and row["valid_cells"] == part["valid_cells"]
            assert row["depth_m"] == grid_depth(grid.layer)
            assert row["reference_salinity"] == pytest.approx(composition.reference_salinity(salinity))
            grams = composition.grams_per_kg(salinity, composition.MAJOR)
            mmol = composition.mmol_per_kg(salinity, composition.MAJOR)
            assert [row[column] for column in ION_GRAM_COLUMNS] == pytest.approx(list(grams.values()))
            assert [row[column] for column in ION_MMOL_COLUMNS] == pytest.approx(list(mmol.values()))
            assert row[ION_CHECK] == ranges.check_salinity(salinity, grid_depth(grid.layer))


def test_grids_without_a_southern_mean_or_in_another_unit_stay_out(store):
    layers = {row["layer"] for row in store.iter_grid_ions()}
    assert layers == {"hycom_salt_100", "hycom_salt_2000", "smos_sss"}
    assert store.load_grid("smap_sss") is not None and store.load_grid("hycom_temp_100") is not None


def test_range_check_uses_the_depth_of_the_layer(store):
    rows = _rows(store)
    assert rows[("hycom_salt_100", GRID_ALL)][ION_CHECK] == ranges.OK
    assert rows[("hycom_salt_2000", GRID_ALL)][ION_CHECK] == ranges.HIGH
    assert rows[("hycom_salt_2000", "weddell")][ION_CHECK] == ranges.OK
    assert rows[("hycom_salt_2000", "amundsen_bell")][ION_CHECK] == ranges.HIGH
    assert rows[("hycom_salt_2000", GRID_ALL)]["depth_m"] == 2000.0


def test_ions_of_the_mean_equal_the_mean_of_the_cell_ions(store):
    """환산이 염분에 비례하므로, 평균 염분을 환산한 값과 칸마다 환산해 같은 가중치로 평균한 값은 반올림 폭 안에서 같습니다."""
    grid = store.load_grid("hycom_salt_100")
    row = _rows(store)[("hycom_salt_100", "weddell")]
    for component, column in zip(composition.MAJOR, ION_GRAM_COLUMNS):
        factor = component.grams_per_salinity
        total = weight_sum = 0.0
        for i, lat in enumerate(grid.lats):
            for j, lon in enumerate(grid.lons):
                value = grid.at(i, j)
                if lat <= ANTARCTIC_LAT and lon == -30.0 and value is not None:
                    weight = math.cos(math.radians(lat))
                    total += value * factor * weight
                    weight_sum += weight
        assert row[column] == pytest.approx(total / weight_sum, abs=factor * 0.0005 + 1e-12)


def test_reader_filters_by_time_and_layer(store):
    assert len(list(store.iter_grid_ions(until=FIRST))) == 6
    assert [row["layer"] for row in store.iter_grid_ions(since=SECOND)] == ["smos_sss"] * 3
    assert [row["area"] for row in store.iter_grid_ions(layer="hycom_salt_2000")] == [GRID_ALL, "weddell", "amundsen_bell"]
    assert list(store.iter_grid_ions(layer="hycom_temp_100")) == []


def test_every_stored_time_of_a_layer_gets_its_own_rows(store):
    store.save_grid(grid_from_triples("hycom_salt_100", SECOND, "PSU", [(-70.0, -30.0, 34.0)], {"depth_m": 100}))
    rows = list(store.iter_grid_ions(layer="hycom_salt_100"))
    assert [(row["valid_time"], row["area"]) for row in rows] == [
        (FIRST, GRID_ALL), (FIRST, "weddell"), (FIRST, "ross"), (SECOND, GRID_ALL), (SECOND, "weddell"),
    ]


def test_database_without_the_view_gains_it_on_open(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    store.upsert_measurements([
        Measurement("smos", "L3", "sea_water_salinity", "satellite", -62.2, -58.8, SECOND, 33.6, "PSU", location_id="king_sejong"),
    ])
    for grid in _grids():
        store.save_grid(grid)
    store._conn.execute("DROP VIEW grid_ions")
    store._conn.commit()
    store.close()

    reopened = Store(path)
    try:
        assert reopened.count_grid_ions() == len(EXPECTED)
        assert reopened.count_ions() == 1
    finally:
        reopened.close()


def test_cell_export_converts_every_cell_with_a_value(store, tmp_path):
    out = tmp_path / "cells.csv"
    assert exporter.export_grid_ions(store, "hycom_salt_100", out) == 4
    rows = _read(out)
    assert list(rows[0]) == list(GRID_CELL_ION_COLUMNS)
    cells = {(float(row["lat"]), float(row["lon"])): row for row in rows}
    assert set(cells) == {(lat, lon) for lat, lon, value in MID if value is not None}
    for lat, lon, value in MID:
        if value is None:
            continue
        row = cells[(lat, lon)]
        assert row["valid_time"] == FIRST and float(row["depth_m"]) == 100.0
        assert float(row["practical_salinity"]) == value
        assert float(row["reference_salinity"]) == pytest.approx(composition.reference_salinity(value))
        grams = composition.grams_per_kg(value, composition.MAJOR)
        mmol = composition.mmol_per_kg(value, composition.MAJOR)
        assert [float(row[column]) for column in ION_GRAM_COLUMNS] == pytest.approx(list(grams.values()))
        assert [float(row[column]) for column in ION_MMOL_COLUMNS] == pytest.approx(list(mmol.values()))
        assert row[ION_CHECK] == ranges.OK


def test_cell_export_reads_the_depth_from_the_layer_name_when_the_grid_has_none(store, tmp_path):
    out = tmp_path / "deep.csv"
    assert exporter.export_grid_ions(store, "hycom_salt_2000", out) == 2
    rows = {float(row["lon"]): row for row in _read(out)}
    assert {float(row["depth_m"]) for row in rows.values()} == {2000.0}
    assert rows[-100.0][ION_CHECK] == ranges.HIGH and rows[-30.0][ION_CHECK] == ranges.OK


def test_cell_export_keeps_cells_north_of_the_antarctic_limit(store, tmp_path):
    out = tmp_path / "north.csv"
    assert exporter.export_grid_ions(store, "smap_sss", out) == 1
    row = _read(out)[0]
    assert float(row["lat"]) == -50.0 and float(row["depth_m"]) == 0.0
    assert float(row["chloride_g_kg"]) == pytest.approx(34.0 * composition.BY_KEY["chloride"].grams_per_salinity)


def test_cell_export_refuses_a_missing_or_non_salinity_layer(store, tmp_path):
    out = tmp_path / "none.csv"
    with pytest.raises(ValueError) as missing:
        exporter.export_grid_ions(store, "hycom_salt_500", out)
    assert "hycom_salt_500" in render(str(missing.value)) and "수집되지 않은" in render(str(missing.value))
    with pytest.raises(ValueError) as wrong:
        exporter.export_grid_ions(store, "hycom_temp_100", out)
    assert "염분 레이어가 아니어서" in render(str(wrong.value)) and "hycom_temp_100" in render(str(wrong.value))
    assert not out.exists()


def test_cli_exports_the_cell_ions(store, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: types.SimpleNamespace(db_path=tmp_path / "t.db"))
    out = tmp_path / "cli.csv"
    cli._export(argparse.Namespace(what="grid-ions", out=str(out), source=None, variable=None, since=None, layer="hycom_salt_100"))
    assert "4 rows" in capsys.readouterr().out and len(_read(out)) == 4


def test_cli_explains_a_missing_or_wrong_layer(store, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: types.SimpleNamespace(db_path=tmp_path / "t.db"))
    out = tmp_path / "cli.csv"
    arguments = {"what": "grid-ions", "out": str(out), "source": None, "variable": None, "since": None}
    with pytest.raises(SystemExit) as missing:
        cli._export(argparse.Namespace(**arguments, layer=None))
    assert "--layer is required for grid-ions" in str(missing.value)
    set_language("en")
    with pytest.raises(SystemExit) as wrong:
        cli._export(argparse.Namespace(**arguments, layer="hycom_temp_100"))
    assert str(wrong.value) == "Not a salinity layer, so it cannot be converted to ions: hycom_temp_100"
    assert not out.exists()


def test_workbook_has_the_grid_ion_sheet(store, tmp_path):
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    sheets = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")
    titles = list(sheets)
    assert titles.index("격자이온") == titles.index("이온조성") + 1
    sheet = sheets["격자이온"]
    header = sheet[0]
    assert header[:7] == ("시각 UTC", "레이어", "해역", "수심 m", "유효 격자 수", "염분 PSU", "기준 염분 g/kg")
    assert header[7:15] == tuple(f"{item.symbol} g/kg" for item in composition.MAJOR)
    assert header[15:23] == tuple(f"{item.symbol} mmol/kg" for item in composition.MAJOR)
    assert header[23] == "범위 검사"
    assert [(line[1], line[2]) for line in sheet[1:]] == [
        ("hycom_salt_100", "남극해 전체 (60°S 이남)"), ("hycom_salt_100", "웨델해"), ("hycom_salt_100", "로스해"),
        ("hycom_salt_2000", "남극해 전체 (60°S 이남)"), ("hycom_salt_2000", "웨델해"),
        ("hycom_salt_2000", "아문젠·벨링스하우젠해"),
        ("smos_sss", "남극해 전체 (60°S 이남)"), ("smos_sss", "인도양"), ("smos_sss", "서태평양"),
    ]
    rows = _rows(store)
    for line, key in zip(sheet[1:], EXPECTED):
        row = rows[key]
        assert line[3:6] == (row["depth_m"], row["valid_cells"], row["practical_salinity"])
        assert line[6] == pytest.approx(row["reference_salinity"], abs=1e-4)
        assert line[7:15] == pytest.approx([row[column] for column in ION_GRAM_COLUMNS], abs=1e-5)
        assert line[15:23] == pytest.approx([row[column] for column in ION_MMOL_COLUMNS], abs=1e-4)
        assert _cell(line, 23) == ("높음" if row[ION_CHECK] == ranges.HIGH else None)
    assert sum(1 for line in sheet[1:] if _cell(line, 23) == "높음") == 2


def test_info_sheet_explains_the_grid_ions(store, tmp_path):
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    info = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")["정보"]
    note = next(line for line in info if line[0] == "격자 이온 환산")
    assert "60°S 이남 평균" in note[1] and "mmol/L 은 없음" in note[1]
    top = next(index for index, line in enumerate(info) if line[0] == "시트")
    counts = {line[0]: line[1] for line in info[top + 1:] if line[0]}
    assert counts["격자이온"] == len(EXPECTED)


def test_grid_ion_sheet_only_takes_the_month_asked_for(store, tmp_path):
    store.save_grid(grid_from_triples("smos_sss", "2026-12-01T00:00:00Z", "PSU", SURFACE))
    excel.sync(store, tmp_path / "xl", ["2026-11", "2026-12"])
    november = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")["격자이온"]
    december = _sheets(tmp_path / "xl" / "antarctic_db_2026-12.xlsx")["격자이온"]
    assert len(november) == 1 + len(EXPECTED) and len(december) == 1 + 3


def test_grid_ion_sheet_in_english(store, tmp_path):
    set_language("en")
    excel.sync(store, tmp_path / "xl", ["2026-11"])
    sheets = _sheets(tmp_path / "xl" / "antarctic_db_2026-11.xlsx")
    sheet = sheets["Grid ions"]
    assert sheet[0][:7] == ("Time UTC", "Layer", "Area", "Depth m", "Valid cells", "Salinity PSU", "Reference salinity g/kg")
    assert sheet[0][23] == "Range check"
    assert [line[2] for line in sheet[1:4]] == ["Southern Ocean (south of 60°S)", "Weddell Sea", "Ross Sea"]
    assert _cell(sheet[4], 23) == "high"
    labels = [line[0] for line in sheets["Info"]]
    assert labels.count("Grid ions") == 1 and labels.count("Grid ion conversion") == 1
    note = next(line for line in sheets["Info"] if line[0] == "Grid ion conversion")
    assert "proportional to salinity" in note[1] and "no mmol/L" in note[1]


def test_rescaled_scale_keeps_the_colours_and_changes_the_numbers():
    base = build_scale("salinity", {"p02": 33.0, "p98": 35.0}, "PSU")
    chloride = composition.BY_KEY["chloride"]
    scale = rescale(base, chloride.grams_per_salinity, "g/kg", "Cl⁻ g/kg")
    values = np.array([32.5, 33.0, 34.0, 35.0, 35.5])
    assert np.array_equal(scale.to_unit(values), base.to_unit(values))
    assert scale.domain == base.domain and scale.lut is base.lut and scale.kind == base.kind
    assert (scale.unit, scale.legend, scale.factor) == ("g/kg", "Cl⁻ g/kg", chloride.grams_per_salinity)
    assert (base.unit, base.legend, base.factor) == ("PSU", "", 1.0)
    assert [at for at, _ in legend_ticks(scale)] == [at for at, _ in legend_ticks(base)]
    assert [value for _, value in legend_ticks(scale)] == pytest.approx(
        [value * chloride.grams_per_salinity for _, value in legend_ticks(base)]
    )
    assert [value for _, value in legend_ticks(base)] == pytest.approx([33.0, 33.5, 34.0, 34.5, 35.0])


def test_rescaled_scale_shows_enough_digits_for_every_ion():
    wide = build_scale("salinity", {"p02": 33.0, "p98": 35.0}, "PSU")
    narrow = build_scale("salinity", {"p02": 34.0, "p98": 34.0}, "PSU")
    assert rescale(wide, composition.BY_KEY["chloride"].grams_per_salinity, "g/kg").digits == 2
    assert rescale(wide, composition.BY_KEY["sodium"].mmol_per_salinity, "mmol/kg").digits == 2
    assert rescale(wide, composition.BY_KEY["bromide"].grams_per_salinity, "g/kg").digits == 5
    for base in (wide, narrow):
        for component in composition.MAJOR:
            for factor in (component.grams_per_salinity, component.mmol_per_salinity):
                scale = rescale(base, factor, "x")
                shown = [f"{value:.{scale.digits}f}" for _, value in legend_ticks(scale)]
                assert len(set(shown)) == len(shown), (component.key, factor, shown)
    assert rescale(wide, 0.0, "x").digits == wide.digits


MAP_ION_SCRIPT = r'''
import csv
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from antarctic_monitor import composition, i18n
from antarctic_monitor.config import Settings
from antarctic_monitor.gridutil import grid_from_triples
from antarctic_monitor.gui.app import ION_VIEWS, MainWindow
from antarctic_monitor.gui.backend import Backend
from antarctic_monitor.gui.format import num
from antarctic_monitor.gui.scales import legend_ticks

i18n.set_language("en")
app = QApplication([])
folder = Path(tempfile.mkdtemp())
settings = Settings(db_path=folder / "t.db", excel_dir=folder / "x", update_mode="off")
backend = Backend(settings, collect=False)
backend.start()
moment = "2026-11-03T00:00:00Z"
cells = [(lat, lon) for lat in (-72.0, -70.0, -68.0) for lon in (0.0, 10.0, 20.0)]
backend.store.save_grid(grid_from_triples("oisst_sst", moment, "°C", [(lat, lon, 1.0) for lat, lon in cells]))
backend.store.save_grid(
    grid_from_triples("hycom_salt_0", moment, "PSU", [(lat, lon, 34.0) for lat, lon in cells], {"depth_m": 0})
)
window = MainWindow(backend, settings)
window.show()
window.start()


def until(check, seconds=30.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if check():
            return True
        time.sleep(0.02)
    return False


def pick(combo, data):
    index = combo.findData(data)
    assert index >= 0, data
    combo.setCurrentIndex(index)


def factor():
    return window.map.scale.factor if window.map.scale else None


chloride = composition.MAJOR[0]
assert len(ION_VIEWS) == 2 * len(composition.MAJOR)
assert until(lambda: "hycom_salt_0" in window.layer_info), "the salinity grid never showed up"
assert until(lambda: window.map.scale is not None and window.map.scale.kind == "water_temp")
assert not window.quantity_combo.isVisible() and window.ion_view() is None

pick(window.layer_combo, "hycom_salt")
assert window.quantity_combo.isVisible() and window.quantity_label.isVisible()
assert window.quantity_combo.itemText(0) == "Salinity (PSU)" and window.quantity_label.text() == "Show"
assert until(lambda: window.map.scale is not None and window.map.scale.kind == "salinity")
assert factor() == 1.0 and window.colorbar.scale.legend == "" and window.map.scale.unit == "PSU"
assert "salinity ×" not in window.layer_meta.text()
plain = legend_ticks(window.map.scale)

pick(window.quantity_combo, 0)
assert until(lambda: factor() == chloride.grams_per_salinity), factor()
scale = window.map.scale
assert window.colorbar.scale is scale and scale.legend == "Cl⁻ g/kg" and scale.unit == "g/kg"
assert [at for at, _ in legend_ticks(scale)] == [at for at, _ in plain]
assert all(abs(new - old * chloride.grams_per_salinity) < 1e-9 for (_, new), (_, old) in zip(legend_ticks(scale), plain))
assert window.map.layer_label.endswith("· Cl⁻"), window.map.layer_label
meta = window.layer_meta.text()
assert "Cl⁻ g/kg = salinity × 0.55293" in meta and "not measured" in meta, meta
x, y = window.map.project(-70.0, 10.0)
text = window.map.readout(float(x), float(y))
assert text and text.endswith(f"Cl⁻: {num(34.0 * chloride.grams_per_salinity, scale.digits)} g/kg"), text

pick(window.quantity_combo, len(composition.MAJOR))
assert until(lambda: factor() == chloride.mmol_per_salinity), factor()
assert window.colorbar.scale.legend == "Cl⁻ mmol/kg" and "Cl⁻ mmol/kg = salinity ×" in window.layer_meta.text()

pick(window.layer_combo, "oisst_sst")
assert not window.quantity_combo.isVisible() and window.ion_view() is None
assert until(lambda: window.map.scale is not None and window.map.scale.kind == "water_temp")
assert factor() == 1.0 and "salinity ×" not in window.layer_meta.text()
shown = []
QMessageBox.information = staticmethod(lambda *args: shown.append(args[2]))
window._save_path = lambda name: folder / name
window.export_layer_ions()
assert shown == ["Not a salinity layer, so it cannot be converted to ions: oisst_sst"], shown
assert not (folder / "oisst_sst-ions.csv").exists()

pick(window.layer_combo, "hycom_salt")
assert until(lambda: factor() == chloride.mmol_per_salinity), "the chosen ion view did not come back"
pick(window.quantity_combo, -1)
assert until(lambda: factor() == 1.0 and window.map.scale.kind == "salinity")
assert window.colorbar.scale.legend == "" and "salinity ×" not in window.layer_meta.text()

window.export_layer_ions()
saved = folder / "hycom_salt_0-ions.csv"
assert until(lambda: "rows saved" in window.statusBar().currentMessage()), window.statusBar().currentMessage()
with saved.open(encoding="utf-8-sig", newline="") as handle:
    rows = list(csv.DictReader(handle))
assert len(rows) == len(cells) and shown == shown[:1]
assert abs(float(rows[0]["chloride_g_kg"]) - 34.0 * chloride.grams_per_salinity) < 1e-9
print("map ions ok", flush=True)
os._exit(0)
'''


def test_map_reads_a_salinity_layer_as_an_ion_concentration():
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", MAP_ION_SCRIPT], capture_output=True, text=True, errors="replace", timeout=120, env=env)
    assert done.returncode == 0 and "map ions ok" in done.stdout, done.stderr
