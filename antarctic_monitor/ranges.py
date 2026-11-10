"""남극해 염분 범위 검사. 값이 그 수심에서 나올 수 있는 넓은 범위 안에 있는지만 봅니다.

범위는 Boyer & Levitus (1994), Quality Control and Processing of Historical Oceanographic Temperature,
Salinity, and Oxygen Data, NOAA Technical Report NESDIS 81 의 표 3f(Southern Ocean)입니다.
같은 보고서 3.2c 절의 규칙대로 표준 수심마다 창을 둡니다. 창은 위로 앞 표준 수심까지 거리의 3/4,
아래로 다음 표준 수심까지 거리의 1/4 이고, 경계에 정확히 놓인 수심은 얕은 쪽 범위를 따릅니다.

보고서가 밝힌 대로 범위는 일부러 넓습니다(맞는 값을 버리기보다 틀린 값을 남기는 쪽). 그래서 큰 오류만 걸립니다.
판정은 표시일 뿐이고 값을 지우거나 고치지 않습니다.
"""

from __future__ import annotations

from bisect import bisect_left

SOURCE = "boyer1994-so/1"
OK, LOW, HIGH = "ok", "low", "high"

SALINITY_RANGES = (
    (0.0, 0.0, 40.0), (10.0, 26.0, 36.75), (20.0, 28.0, 36.75), (30.0, 29.0, 36.5), (50.0, 30.0, 36.5),
    (75.0, 30.5, 36.5), (100.0, 30.5, 36.5), (125.0, 30.5, 36.5), (150.0, 31.0, 36.5), (200.0, 31.0, 36.25),
    (250.0, 31.0, 36.0), (300.0, 31.0, 36.0), (400.0, 31.5, 35.75), (500.0, 32.0, 35.5), (600.0, 33.0, 35.5),
    (700.0, 33.8, 35.35), (800.0, 33.8, 35.0), (900.0, 34.0, 35.0), (1000.0, 34.0, 35.0), (1100.0, 34.0, 35.0),
    (1200.0, 34.0, 35.0), (1300.0, 34.0, 34.9), (1400.0, 34.3, 34.9), (1500.0, 34.3, 34.9), (1750.0, 34.4, 34.9),
    (2000.0, 34.4, 34.9), (2500.0, 34.4, 34.9), (3000.0, 34.4, 34.9), (3500.0, 34.4, 34.9), (4000.0, 34.4, 34.9),
    (4500.0, 34.4, 34.9), (5000.0, 34.4, 34.9), (5500.0, 34.4, 34.9),
)


def _windows() -> tuple[tuple[float, float | None, float | None, float, float], ...]:
    output = []
    depths = [row[0] for row in SALINITY_RANGES]
    for index, (depth, low, high) in enumerate(SALINITY_RANGES):
        top = None if index == 0 else depth - 0.75 * (depth - depths[index - 1])
        bottom = None if index + 1 == len(depths) else depth + 0.25 * (depths[index + 1] - depth)
        output.append((depth, top, bottom, low, high))
    return tuple(output)


WINDOWS = _windows()
"""(표준 수심, 창의 위 경계, 창의 아래 경계, 하한, 상한). 맨 위 창과 맨 아래 창은 바깥 경계가 없어 None."""

_BOTTOMS = [row[2] for row in WINDOWS[:-1]]


def salinity_range(depth_m: float | None = None) -> tuple[float, float]:
    """그 수심에 적용하는 (하한, 상한). 수심을 모르면 표층(0 m) 범위를 씁니다."""
    row = WINDOWS[bisect_left(_BOTTOMS, 0.0 if depth_m is None else depth_m)]
    return row[3], row[4]


def check_salinity(salinity: float | None, depth_m: float | None = None) -> str | None:
    """범위 안이면 'ok', 하한보다 낮으면 'low', 상한보다 높으면 'high'. 염분이 없으면 None."""
    if salinity is None:
        return None
    low, high = salinity_range(depth_m)
    if salinity < low:
        return LOW
    return HIGH if salinity > high else OK


def _sql_bound(depth: str, column: int) -> str:
    """수심 식에서 하한(열 3) 또는 상한(열 4)을 고르는 SQL CASE. 값이 같은 이웃 창은 한 줄로 합칩니다."""
    parts = [
        f"WHEN {depth} <= {row[2]!r} THEN {row[column]!r}"
        for row, following in zip(WINDOWS, WINDOWS[1:])
        if following[column] != row[column]
    ]
    return f"CASE {' '.join(parts)} ELSE {WINDOWS[-1][column]!r} END"


def sql_check(salinity: str, depth: str) -> str:
    """check_salinity 와 같은 판정을 내는 SQL 식. 데이터베이스의 트리거와 뷰가 씁니다."""
    known = f"COALESCE({depth}, 0)"
    return (
        f"CASE WHEN {salinity} < {_sql_bound(known, 3)} THEN '{LOW}' "
        f"WHEN {salinity} > {_sql_bound(known, 4)} THEN '{HIGH}' ELSE '{OK}' END"
    )
