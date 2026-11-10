"""지점 상세 패널이 보이는 높이에 맞게 줄어드는지 확인합니다 (화면 없이 offscreen으로 그립니다)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from antarctic_monitor.gui.panels import ProfilePanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _levels() -> list[dict]:
    return [{"depth_m": d, "temp": 1.0 - d / 1000.0, "salt": 34.0 + d / 5000.0} for d in (0, 10, 50, 100, 200, 500, 1000)]


def _settle(app, times: int = 8) -> None:
    for _ in range(times):
        app.processEvents()


def test_profile_panel_fits_the_viewport_after_rendering(app):
    panel = ProfilePanel()
    panel.resize(900, 760)
    panel.show()
    _settle(app)
    panel.show_data(
        {
            "argo": {
                "levels": _levels(), "data_mode": "A", "platform": "5905620", "cycle": 35,
                "distance_km": 12.0, "time": "2026-11-04T00:00:00Z", "position_qc": "1",
            },
            "hycom": {"levels": _levels(), "lat": -62.0, "lon": 150.0, "time": "2026-11-04T00:00:00Z"},
            "woa": {"levels": _levels(), "month": 11},
            "errors": [{"source": "WOA23", "message": "no answer"}],
        }
    )
    _settle(app)
    assert panel.note.text() and panel.errors.isVisible()
    assert panel.widget().height() == panel.viewport().height()
    bottom = panel.ts_chart.y() + panel.ts_chart.height()
    assert bottom <= panel.viewport().height()
    assert panel.ts_chart.canvas.height() >= panel.ts_chart.canvas.minimumHeight()


def test_profile_panel_scrolls_only_below_its_minimum_height(app):
    panel = ProfilePanel()
    panel.resize(900, 400)
    panel.show()
    _settle(app)
    minimum = panel.widget().minimumSizeHint().height()
    assert panel.widget().height() == minimum > panel.viewport().height()


def test_air_values_are_listed_two_per_row(app):
    from antarctic_monitor.gui.panels import AIR_FIELDS, AirPanel

    panel = AirPanel()
    grid = panel.group.layout()
    assert grid.columnCount() == 4
    assert grid.rowCount() == (len(AIR_FIELDS) + 1) // 2


def _water(salinity) -> dict:
    from antarctic_monitor import composition

    rows = [
        {"source": "oisst", "label": "OISST v2.1", "kind": "analysis", "variable": "temperature", "unit": "°C", "value": -1.2, "time": "2026-11-04T12:00:00Z", "note": None},
        {"source": "hycom", "label": "HYCOM 0 m", "kind": "model", "variable": "salinity", "unit": "PSU", "value": salinity, "time": "2026-11-04T00:00:00Z", "note": None},
        {"source": "smos", "label": "SMOS", "kind": "satellite", "variable": "salinity", "unit": "PSU", "value": None, "time": "2026-11-03T00:00:00Z", "note": None},
    ]
    best = rows[1] if salinity is not None else None
    headline = {"temperature": rows[0], "salinity": best, "derived": None, "ions": composition.derive(salinity)}
    return {"headline": headline, "rows": rows, "errors": []}


def _column(table, column: int) -> list[str]:
    return [table.item(row, column).text() if table.item(row, column) else "" for row in range(table.rowCount())]


def test_ion_panel_lists_every_component_with_a_total(app):
    from antarctic_monitor import composition
    from antarctic_monitor.gui.panels import IonPanel

    panel = IonPanel()
    panel.resize(720, 700)
    panel.show()
    _settle(app)
    panel.show_data(_water(35.0))
    _settle(app)
    assert "환산값" in panel.note.text() and "직접 잰 값이 아니며" in panel.note.text()
    assert _column(panel.headline, 0) == ["표층 염분", "기준 염분 S_R", "염소량", "이온 세기"]
    assert _column(panel.headline, 1)[:3] == ["35.000 PSU", "35.1650 g/kg", "19.3739 g/kg"]
    assert "HYCOM 0 m" in panel.headline.item(0, 2).text()
    assert panel.table.rowCount() == len(composition.COMPONENTS) + 1
    assert _column(panel.table, 1)[:3] == ["Cl⁻", "Na⁺", "SO₄²⁻"]
    assert panel.table.item(0, 2).text() == "19.35271"
    assert _column(panel.table, 5)[:9] == ["DB·엑셀에 저장"] * 8 + [""]
    total = panel.table.rowCount() - 1
    assert panel.table.item(total, 0).text() == "합계" and panel.table.item(total, 2).text() == "35.16504"
    assert panel.table.item(total, 4).text() == "100.0000"
    assert _column(panel.sources, 0) == ["HYCOM 0 m", "SMOS"]
    assert panel.sources.item(0, 2).text() == "19.3527" and panel.sources.item(1, 1).text() == "결측"
    assert panel.sources.item(1, 2).text() == "–"
    for table in (panel.headline, panel.table):
        assert not table.verticalScrollBar().isVisible()


def test_ion_panel_says_when_no_salinity_is_available(app):
    from antarctic_monitor.gui.panels import IonPanel

    panel = IonPanel()
    panel.resize(720, 500)
    panel.show()
    _settle(app)
    panel.show_data(_water(35.0))
    panel.show_data(_water(None))
    _settle(app)
    assert panel.headline.rowCount() == 1 and "환산하지 못했습니다" in panel.headline.item(0, 2).text()
    assert panel.table.rowCount() == 0 and not panel.table.isVisible()
    assert _column(panel.sources, 1) == ["결측", "결측"]


TIME_SLIDER_SCRIPT = r'''
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from antarctic_monitor import i18n
from antarctic_monitor.config import Settings
from antarctic_monitor.gridutil import grid_from_triples
from antarctic_monitor.gui.app import MainWindow, short_time
from antarctic_monitor.gui.backend import Backend

i18n.set_language("en")
app = QApplication([])
folder = Path(tempfile.mkdtemp())
settings = Settings(db_path=folder / "t.db", excel_dir=folder / "x", update_mode="off")
backend = Backend(settings, collect=False)
backend.start()
times = [f"2026-11-0{day}T12:00:00Z" for day in (1, 2, 3)]
for day, moment in enumerate(times, start=1):
    backend.store.save_grid(
        grid_from_triples("oisst_sst", moment, "°C", [(-70.0, 0.0, float(day)), (-70.0, 10.0, float(day))])
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


def showing(moment):
    return short_time(moment) in window.layer_meta.text()


assert until(lambda: window.time_slider.maximum() == 2), "slider never got the frames"
assert window.time_row.isVisible() and window.time_slider.value() == 2
assert until(lambda: showing(times[2])), window.layer_meta.text()
window.time_slider.setValue(0)
assert until(lambda: showing(times[0])), window.layer_meta.text()
assert window.time_slider.maximum() == 2, "picking a frame must keep the slider"
window._toggle_play()
assert window.play_timer.isActive()
assert until(lambda: showing(times[2]) and not window.play_timer.isActive(), 20.0), window.layer_meta.text()
window.render_layer()
assert until(lambda: window.time_slider.value() == 2 and window.time_row.isVisible()), "latest view lost the slider"
print("frames ok", flush=True)
os._exit(0)
'''


def test_land_outline_follows_the_projection(app):
    import numpy as np
    from PySide6.QtCore import QPointF

    from antarctic_monitor.gui.polarmap import PolarMapWidget

    widget = PolarMapWidget()
    widget.resize(800, 500)
    ring = widget._land_rings[0]
    for zoom, offset in ((1.0, QPointF(0.0, 0.0)), (4.5, QPointF(120.0, -80.0))):
        widget.zoom = zoom
        widget.offset = offset
        widget._invalidate()
        path = widget._land()
        xs, ys = widget.project(ring[:, 1], ring[:, 0])
        elements = [path.elementAt(index) for index in range(len(ring))]
        assert path.elementCount() >= sum(len(item) for item in widget._land_rings)
        assert np.allclose([element.x for element in elements], xs)
        assert np.allclose([element.y for element in elements], ys)


def test_redrawing_the_land_keeps_references_to_none(app):
    """Python 3.11에서는 None의 참조 수가 바닥나면 프로그램이 죽습니다."""
    import sys

    from antarctic_monitor.gui.polarmap import PolarMapWidget

    widget = PolarMapWidget()
    widget.resize(500, 400)
    widget._land()
    before = sys.getrefcount(None)
    for _ in range(50):
        widget._invalidate()
        widget._land()
    assert sys.getrefcount(None) > before - 1000


def test_map_steps_through_stored_times():
    import subprocess
    import sys

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", TIME_SLIDER_SCRIPT], capture_output=True, text=True, errors="replace", timeout=120, env=env)
    assert done.returncode == 0 and "frames ok" in done.stdout, done.stderr


ION_TAB_SCRIPT = r'''
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from antarctic_monitor import composition, i18n
from antarctic_monitor.config import Settings
from antarctic_monitor.gui.app import DETAIL_TABS, MainWindow
from antarctic_monitor.gui.backend import Backend

i18n.set_language("en")
app = QApplication([])
folder = Path(tempfile.mkdtemp())
settings = Settings(db_path=folder / "t.db", excel_dir=folder / "x", update_mode="off")
backend = Backend(settings, collect=False)
backend.start()
window = MainWindow(backend, settings)
window.show()
row = {"source": "hycom", "label": "HYCOM 0 m", "kind": "model", "variable": "salinity", "unit": "PSU", "value": 34.5, "time": "2026-11-04T00:00:00Z", "note": None}
payload = {
    "query": {"lat": -65.0, "lon": 0.0}, "ocean": None, "rows": [row], "errors": [],
    "headline": {"temperature": None, "salinity": row, "derived": None, "ions": composition.derive(34.5)},
}
asked = []


def point(part, lat, lon, callback):
    asked.append(part)
    callback(payload, None)
    return 0


backend.point = point
assert DETAIL_TABS[-1] == "ions" and window.detail_tabs.count() == len(DETAIL_TABS)
assert window.detail_tabs.tabText(4) == "Ion composition"
window.select_point(-65.0, 0.0, "test")
window.detail_tabs.setCurrentIndex(4)
for _ in range(20):
    app.processEvents()
panel = window.panels["ions"]
assert asked == ["water", "water"], asked
assert panel.table.rowCount() == len(composition.COMPONENTS) + 1, panel.table.rowCount()
assert panel.table.item(0, 0).text() == "Chloride" and panel.headline.item(1, 0).text() == "Reference salinity S_R"
print("ion tab ok", flush=True)
os._exit(0)
'''


def test_ion_tab_reuses_the_surface_query():
    import subprocess
    import sys

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", ION_TAB_SCRIPT], capture_output=True, text=True, errors="replace", timeout=120, env=env)
    assert done.returncode == 0 and "ion tab ok" in done.stdout, done.stderr
