from __future__ import annotations

import math
import sqlite3

import pytest

from antarctic_monitor import composition
from antarctic_monitor.db import ION_GRAM_COLUMNS, ION_METHOD_KEY, ION_OBJECTS, Measurement, Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "test.db")
    yield instance
    instance.close()


def _salt(value=34.5, when="2026-11-04T00:00:00Z", level="surface", depth=None, source="hycom", location="weddell"):
    return Measurement(
        source=source, dataset="ESPC", variable="sea_water_salinity", kind="model", lat=-68.0, lon=-40.0,
        obs_time=when, value=value, unit="PSU", level=level, depth_m=depth, location_id=location,
    )


def _temp(value=-1.2, when="2026-11-04T00:00:00Z"):
    return Measurement(
        source="hycom", dataset="ESPC", variable="sea_water_temperature", kind="model", lat=-68.0, lon=-40.0,
        obs_time=when, value=value, unit="°C", location_id="weddell",
    )


def _ions(store: Store) -> list[dict]:
    return list(store.iter_ions())


def test_reference_composition_check_values():
    assert sum(c.mass_fraction for c in composition.COMPONENTS) == pytest.approx(1.0, abs=1e-9)
    assert composition.reference_salinity(35.0) == pytest.approx(35.16504, abs=1e-9)

    grams = composition.grams_per_kg(35.0)
    expected = {
        "chloride": 19.3527, "sodium": 10.7815, "sulfate": 2.7123, "magnesium": 1.2837,
        "calcium": 0.4121, "potassium": 0.3991, "bicarbonate": 0.1048, "bromide": 0.0673,
    }
    for key, value in expected.items():
        assert grams[key] == pytest.approx(value, abs=5e-5)
    assert sum(grams.values()) == pytest.approx(35.16504, abs=1e-6)

    mmol = composition.mmol_per_kg(35.0)
    assert mmol["chloride"] == pytest.approx(545.87, abs=0.005)
    assert mmol["sodium"] == pytest.approx(468.97, abs=0.005)
    assert mmol["sulfate"] == pytest.approx(28.235, abs=0.005)
    assert mmol["magnesium"] == pytest.approx(52.817, abs=0.005)
    assert sum(mmol.values()) == pytest.approx(1119.77, abs=0.01)

    assert composition.chlorinity(35.0) == pytest.approx(19.37394, abs=1e-5)
    assert composition.ionic_strength(35.0) == pytest.approx(0.7226, abs=1e-4)


def test_reference_composition_is_electrically_neutral():
    mmol = composition.mmol_per_kg(35.0)
    positive = sum(mmol[c.key] * c.charge for c in composition.COMPONENTS if c.charge > 0)
    negative = -sum(mmol[c.key] * c.charge for c in composition.COMPONENTS if c.charge < 0)
    assert positive == pytest.approx(605.55, abs=0.01)
    assert positive == pytest.approx(negative, abs=1e-3)


def test_composition_scales_with_salinity_and_keeps_ratios():
    low, high = composition.grams_per_kg(33.0), composition.grams_per_kg(35.0)
    for key in high:
        assert low[key] == pytest.approx(high[key] * 33.0 / 35.0)
    assert low["sodium"] / low["chloride"] == pytest.approx(high["sodium"] / high["chloride"])
    assert set(composition.grams_per_kg(34.0, composition.MAJOR)) == {c.key for c in composition.MAJOR}
    assert sum(c.mass_fraction for c in composition.MAJOR) == pytest.approx(0.99853, abs=1e-5)


@pytest.mark.parametrize("bad", [None, 0, 0.0, -1.0, math.nan, math.inf, "abc", True])
def test_composition_rejects_missing_or_impossible_salinity(bad):
    assert composition.reference_salinity(bad) is None
    assert composition.grams_per_kg(bad) == {}
    assert composition.mmol_per_kg(bad) == {}
    assert composition.chlorinity(bad) is None
    assert composition.ionic_strength(bad) is None
    assert composition.derive(bad) is None


def test_derive_lists_every_component_with_both_units():
    result = composition.derive(34.0)
    assert result["method"] == composition.METHOD
    assert result["reference_salinity"] == pytest.approx(34.16033, abs=1e-5)
    assert [ion["key"] for ion in result["ions"]] == [c.key for c in composition.COMPONENTS]
    chloride = result["ions"][0]
    assert chloride["symbol"] == "Cl⁻"
    assert chloride["g_per_kg"] == pytest.approx(18.7998, abs=5e-5)
    assert chloride["mmol_per_kg"] == pytest.approx(chloride["g_per_kg"] / 35.453 * 1000.0)
    assert chloride["mass_percent"] == pytest.approx(55.03396)


def test_salinity_rows_fill_the_ion_table(store):
    store.upsert_measurements([_salt(35.0), _temp()])
    rows = _ions(store)
    assert len(rows) == 1 and store.count_ions() == 1
    row = rows[0]
    assert (row["source"], row["level"], row["kind"], row["location_id"]) == ("hycom", "surface", "model", "weddell")
    assert row["practical_salinity"] == 35.0
    assert row["reference_salinity"] == pytest.approx(35.16504)
    for component in composition.MAJOR:
        assert row[f"{component.key}_g_kg"] == pytest.approx(composition.grams_per_kg(35.0)[component.key], rel=1e-12)


def test_ion_row_follows_a_corrected_salinity(store):
    store.upsert_measurements([_salt(35.0)])
    store.upsert_measurements([_salt(34.0)])
    rows = _ions(store)
    assert len(rows) == 1
    assert rows[0]["practical_salinity"] == 34.0
    assert rows[0]["chloride_g_kg"] == pytest.approx(18.7998, abs=5e-5)


def test_each_depth_and_time_gets_its_own_ion_row(store):
    store.upsert_measurements([
        _salt(34.1, level="depth:0", depth=0.0),
        _salt(34.6, level="depth:100", depth=100.0),
        _salt(34.2, when="2026-11-05T00:00:00Z", level="depth:0", depth=0.0),
        _salt(33.9, source="argo"),
    ])
    rows = _ions(store)
    assert len(rows) == 4
    assert [row["obs_time"] for row in rows] == sorted(row["obs_time"] for row in rows)
    assert {row["depth_m"] for row in rows} == {0.0, 100.0, None}
    assert len(list(store.iter_ions(source="argo"))) == 1
    assert len(list(store.iter_ions(since="2026-11-05T00:00:00Z"))) == 1
    assert len(list(store.iter_ions(until="2026-11-04T23:59:59Z", limit=2))) == 2


def test_ion_rows_disappear_with_their_salinity(store):
    store.upsert_measurements([_salt(34.5), _salt(34.7, when="2026-11-05T00:00:00Z"), _temp()])
    store._conn.execute("DELETE FROM measurements WHERE obs_time = '2026-11-05T00:00:00Z'")
    store._conn.commit()
    assert [row["practical_salinity"] for row in _ions(store)] == [34.5]
    store._conn.execute("DELETE FROM measurements")
    store._conn.commit()
    assert store.count_ions() == 0


def test_ion_rows_follow_direct_edits(store):
    store.upsert_measurements([_salt(34.5), _temp()])
    store._conn.execute("UPDATE measurements SET value = 0 WHERE variable = 'sea_water_salinity'")
    assert store.count_ions() == 0
    store._conn.execute("UPDATE measurements SET value = 33.0, obs_time = '2026-11-06T00:00:00Z' WHERE variable = 'sea_water_salinity'")
    rows = _ions(store)
    assert [(row["obs_time"], row["practical_salinity"]) for row in rows] == [("2026-11-06T00:00:00Z", 33.0)]
    store._conn.execute("UPDATE measurements SET variable = 'retired' WHERE variable = 'sea_water_salinity'")
    assert store.count_ions() == 0
    store._conn.execute("UPDATE measurements SET variable = 'sea_water_salinity' WHERE variable = 'retired'")
    store._conn.commit()
    assert store.count_ions() == 1


def test_replace_and_ignore_inserts_keep_one_ion_row(store):
    store.upsert_measurements([_salt(34.5)])
    columns = "source, dataset, variable, kind, lat, lon, level, obs_time, value, unit, fetched_at"
    values = "'hycom', 'ESPC', 'sea_water_salinity', 'model', -68.0, -40.0, 'surface', '2026-11-04T00:00:00Z', {}, 'PSU', 'now'"
    store._conn.execute(f"INSERT OR IGNORE INTO measurements ({columns}) VALUES ({values.format(30.0)})")
    assert [row["practical_salinity"] for row in _ions(store)] == [34.5]
    store._conn.execute(f"INSERT OR REPLACE INTO measurements ({columns}) VALUES ({values.format(33.5)})")
    store._conn.commit()
    assert [row["practical_salinity"] for row in _ions(store)] == [33.5]


def test_salinity_that_cannot_be_converted_is_left_out(store):
    store.upsert_measurements([_salt(0.0), _salt(-2.0, when="2026-11-05T00:00:00Z")])
    assert store.count_measurements() == 2
    assert store.count_ions() == 0


def test_database_from_an_older_version_is_backfilled(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    store.upsert_measurements([_salt(34.5), _temp()])
    for name in ION_OBJECTS[:3]:
        store._conn.execute(f"DROP TRIGGER {name}")
    for name in ION_OBJECTS[3:]:
        store._conn.execute(f"DROP VIEW {name}")
    store._conn.execute("DROP TABLE seawater_ions")
    store._conn.execute("DELETE FROM kv WHERE key = ?", (ION_METHOD_KEY,))
    store._conn.commit()
    store.upsert_measurements([_salt(34.9, when="2026-11-05T00:00:00Z")])
    store.close()

    reopened = Store(path)
    try:
        assert [row["practical_salinity"] for row in _ions(reopened)] == [34.5, 34.9]
        assert reopened.kv_get(ION_METHOD_KEY) == composition.METHOD
        reopened.upsert_measurements([_salt(35.1, when="2026-11-06T00:00:00Z")])
        assert reopened.count_ions() == 3
    finally:
        reopened.close()


def test_ion_table_is_recomputed_when_the_method_changes(tmp_path):
    path = tmp_path / "method.db"
    store = Store(path)
    store.upsert_measurements([_salt(35.0)])
    store._conn.execute("UPDATE seawater_ions SET chloride_g_kg = 1.0")
    store.kv_set(ION_METHOD_KEY, "older-method")
    store.close()

    reopened = Store(path)
    try:
        assert _ions(reopened)[0]["chloride_g_kg"] == pytest.approx(19.3527, abs=5e-5)
        assert reopened.kv_get(ION_METHOD_KEY) == composition.METHOD
    finally:
        reopened.close()


def test_reopening_a_current_database_writes_nothing(tmp_path):
    path = tmp_path / "steady.db"
    store = Store(path)
    store.upsert_measurements([_salt(35.0)])
    store.close()
    before = sqlite3.connect(path).execute("PRAGMA data_version").fetchone()[0]

    watcher = sqlite3.connect(path)
    first = watcher.execute("PRAGMA data_version").fetchone()[0]
    reopened = Store(path)
    reopened.close()
    assert watcher.execute("PRAGMA data_version").fetchone()[0] == first
    watcher.close()
    assert before is not None


def test_mmol_view_matches_the_module(store):
    store.upsert_measurements([_salt(35.0)])
    row = dict(store._conn.execute("SELECT * FROM seawater_ions_mmol").fetchone())
    assert row["practical_salinity"] == 35.0
    for component in composition.MAJOR:
        assert row[f"{component.key}_mmol_kg"] == pytest.approx(composition.mmol_per_kg(35.0)[component.key], rel=1e-12)
    with_mmol = next(store.iter_ions(mmol=True))
    assert with_mmol["chloride_mmol_kg"] == pytest.approx(545.87, abs=0.005)
    assert with_mmol["chloride_g_kg"] == pytest.approx(19.3527, abs=5e-5)


def test_argo_level_view_converts_every_level_with_salinity(store):
    store.upsert_argo_listing([{
        "platform": "1", "cycle": 2, "time": "2026-11-01T00:00:00Z", "lat": -65.0, "lon": 0.0, "data_mode": "R",
        "position_qc": "1", "surface_temp": 1.0, "surface_salt": 34.0,
    }])
    store.save_argo_levels("1", 2, [
        {"pressure_dbar": 5.0, "depth_m": 5.0, "temp": 1.0, "salt": 34.0},
        {"pressure_dbar": 50.0, "depth_m": 49.7, "temp": 0.5, "salt": 34.2},
        {"pressure_dbar": 100.0, "depth_m": 99.1, "temp": 0.4, "salt": None},
    ])
    rows = [dict(r) for r in store._conn.execute("SELECT * FROM argo_level_ions ORDER BY pressure_dbar")]
    assert [(r["platform"], r["cycle"], r["pressure_dbar"], r["practical_salinity"]) for r in rows] == [
        ("1", 2, 5.0, 34.0), ("1", 2, 50.0, 34.2),
    ]
    assert rows[1]["temperature_c"] == 0.5
    assert rows[1]["reference_salinity"] == pytest.approx(composition.reference_salinity(34.2))
    for name, component in zip(ION_GRAM_COLUMNS, composition.MAJOR):
        assert rows[1][name] == pytest.approx(composition.grams_per_kg(34.2)[component.key], rel=1e-12)
    assert store.count_ions() == 0
