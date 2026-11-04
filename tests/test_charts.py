"""시계열 차트가 표본이 적을 때도 보이는지 확인합니다 (화면 없이 offscreen으로 그립니다)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtWidgets import QApplication

from antarctic_monitor.gui.charts import Chart


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _dots(chart: Chart):
    return [line for line in chart.figure.axes[0].get_lines() if line.get_marker() == "o"]


def test_single_sample_is_drawn_as_a_dot(app):
    chart = Chart(height=120)
    now = datetime.now(timezone.utc)
    chart.line("t", [{"name": "SST", "color": "#123456", "times": [now], "values": [1.5]}], unit="°C")
    dots = _dots(chart)
    assert len(dots) == 1 and list(dots[0].get_ydata()) == [1.5]
    notes = [text.get_text() for text in chart.figure.axes[0].texts]
    assert any("1" in note and ("표본" in note or "sample" in note) for note in notes)


def test_isolated_points_between_gaps_get_dots(app):
    chart = Chart(height=120)
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    times = [start + timedelta(days=i) for i in range(6)]
    values = [1.0, None, 2.0, None, 3.0, 3.5]
    chart.line("t", [{"name": "x", "color": "#123456", "times": times, "values": values}])
    dots = _dots(chart)
    assert len(dots) == 1 and sorted(dots[0].get_ydata()) == [1.0, 2.0]
    assert not chart.figure.axes[0].texts


def test_legend_sits_outside_the_axes(app):
    chart = Chart(height=120)
    now = datetime.now(timezone.utc)
    times = [now - timedelta(hours=i) for i in range(3)]
    chart.line(
        "t",
        [
            {"name": "a", "color": "#123456", "times": times, "values": [1.0, 2.0, 3.0]},
            {"name": "b", "color": "#654321", "times": times, "values": [2.0, 3.0, 4.0]},
        ],
    )
    assert chart.figure.axes[0].get_legend() is None
    assert chart.figure.legends and [t.get_text() for t in chart.figure.legends[0].get_texts()] == ["a", "b"]


def test_all_missing_shows_message(app):
    chart = Chart(height=120)
    chart.line("t", [{"name": "x", "color": "#123456", "times": [datetime.now(timezone.utc)], "values": [None]}])
    assert not chart.figure.axes[0].get_lines()
