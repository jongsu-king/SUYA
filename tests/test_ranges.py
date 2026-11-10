"""남극해 염분 범위 검사: 표의 모양, 수심 창의 경계, 파이썬 판정과 SQL 판정의 일치."""

import sqlite3

import pytest

from antarctic_monitor import ranges


def test_table_is_the_southern_ocean_set_of_the_report():
    depths = [row[0] for row in ranges.SALINITY_RANGES]
    assert len(depths) == 33 and depths[0] == 0.0 and depths[-1] == 5500.0
    assert depths == sorted(set(depths))
    assert all(low < high for _, low, high in ranges.SALINITY_RANGES)
    assert ranges.SALINITY_RANGES[0] == (0.0, 0.0, 40.0)
    assert ranges.SALINITY_RANGES[6] == (100.0, 30.5, 36.5)
    assert ranges.SALINITY_RANGES[-1] == (5500.0, 34.4, 34.9)


def test_windows_reach_three_quarters_up_and_one_quarter_down():
    by_depth = {row[0]: row for row in ranges.WINDOWS}
    assert by_depth[0.0][1:3] == (None, 2.5)
    assert by_depth[10.0][1:3] == (2.5, 12.5)
    assert by_depth[200.0][1:3] == (162.5, 212.5)
    assert by_depth[1200.0][1:3] == (1125.0, 1225.0)
    assert by_depth[5500.0][1:3] == (5125.0, None)
    for upper, lower in zip(ranges.WINDOWS, ranges.WINDOWS[1:]):
        assert upper[2] == lower[1]


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        (None, (0.0, 40.0)), (-1.0, (0.0, 40.0)), (0.0, (0.0, 40.0)), (2.5, (0.0, 40.0)), (2.6, (26.0, 36.75)),
        (100.0, (30.5, 36.5)), (211.0, (31.0, 36.25)), (212.5, (31.0, 36.25)), (212.6, (31.0, 36.0)),
        (1200.0, (34.0, 35.0)), (9000.0, (34.4, 34.9)),
    ],
)
def test_range_for_a_depth(depth, expected):
    assert ranges.salinity_range(depth) == expected


def test_verdicts():
    assert ranges.check_salinity(None, 100.0) is None
    assert ranges.check_salinity(34.5, 100.0) == ranges.OK
    assert ranges.check_salinity(30.5, 100.0) == ranges.OK
    assert ranges.check_salinity(36.5, 100.0) == ranges.OK
    assert ranges.check_salinity(30.49, 100.0) == ranges.LOW
    assert ranges.check_salinity(36.51, 100.0) == ranges.HIGH
    assert ranges.check_salinity(39.063, 211.0) == ranges.HIGH
    assert ranges.check_salinity(33.2, 1200.0) == ranges.LOW
    assert ranges.check_salinity(39.063) == ranges.OK


def test_sql_expression_gives_the_same_verdict_as_python():
    connection = sqlite3.connect(":memory:")
    statement = f"SELECT {ranges.sql_check('?1', '?2')}"
    depths = [None, 0.0, 1.0, 7000.0]
    for _, top, bottom, _, _ in ranges.WINDOWS:
        for border in (top, bottom):
            if border is not None:
                depths += [border - 0.01, border, border + 0.01]
    salinities = sorted(
        {0.5, 41.0}
        | {bound + step for _, low, high in ranges.SALINITY_RANGES for bound in (low, high) for step in (-0.01, 0.0, 0.01)}
    )
    compared = 0
    for depth in depths:
        for salinity in salinities:
            verdict = connection.execute(statement, (salinity, depth)).fetchone()[0]
            assert verdict == ranges.check_salinity(salinity, depth), (salinity, depth)
            compared += 1
    connection.close()
    assert compared > 5000
