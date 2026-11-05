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


def test_air_values_fit_a_narrow_panel_in_english(app):
    from antarctic_monitor.gui.panels import AirPanel
    from antarctic_monitor.i18n import set_language

    set_language("en")
    try:
        panel = AirPanel()
        assert panel.group.minimumSizeHint().width() <= 480
    finally:
        set_language("ko")
