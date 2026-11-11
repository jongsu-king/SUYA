"""SQLite에 쌓인 값을 월별 엑셀 파일로 축적합니다.

- antarctic_db_YYYY-MM.xlsx : 수온·염분·기온과 염분에서 환산한 이온 조성을 시트별로 정리한 파일
- argo_levels_YYYY-MM.xlsx  : Argo 프로파일의 모든 층과 층별 이온 환산값. 행이 많아 따로 둡니다.

파일은 SQLite에서 다시 생성합니다. 추가 쓰기는 파일 전체를 읽어야 해서 행이 늘수록 느려지고,
중간에 끊기면 파일이 깨질 수 있기 때문입니다. 임시 파일을 다 쓴 뒤 교체하므로 파일이 깨지지 않습니다.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import xlsxwriter

from . import composition, ranges
from .collectors.base import CollectResult, Context
from .collectors.openmeteo import MODELS
from .db import (
    GRID_ALL,
    ION_CHECK,
    ION_DENSITY,
    ION_GRAM_COLUMNS,
    ION_LITRE_COLUMNS,
    ION_MMOL_COLUMNS,
    Store,
    iso,
    utcnow,
)
from .gridutil import SECTORS
from .http import FetchError
from .i18n import get_language, join, msg, tr
from .locations import LOCATION_BY_ID, location_label

EXCEL_ROW_LIMIT = 1_048_576
WATER_VARIABLES = {
    "sea_water_temperature": "수온",
    "sea_water_salinity": "염분",
    "sst_anomaly": "수온 편차",
    "sea_ice_fraction": "해빙 농도",
    "sst_uncertainty": "수온 오차",
}
AIR_CURRENT = (
    ("air_temperature", "기온 °C"),
    ("apparent_temperature", "체감 °C"),
    ("dew_point", "이슬점 °C"),
    ("wet_bulb_temperature", "습구 °C"),
    ("surface_temperature", "지표 온도 °C"),
    ("relative_humidity", "습도 %"),
    ("surface_pressure", "기압 hPa"),
    ("wind_speed", "풍속 km/h"),
)
WATER_SOURCES = ("oisst", "smos", "smap", "hycom", "openmeteo_marine")
POINT_SOURCES = ("oisst", "mur", "smos", "smap", "hycom", "openmeteo", "openmeteo_marine")
SUMMARY_SOURCES = WATER_SOURCES + ("openmeteo", "metar")
SUMMARY_VARIABLES = {**WATER_VARIABLES, "air_temperature": "기온"}
MAIN_FILE = "antarctic_db_{month}.xlsx"
ARGO_FILE = "argo_levels_{month}.xlsx"
ION_GRAM_HEADERS = [(f"{component.symbol} g/kg", 11) for component in composition.MAJOR]
ION_MMOL_HEADERS = [(f"{component.symbol} mmol/kg", 13) for component in composition.MAJOR]
ION_GRAM_FACTORS = tuple(component.grams_per_salinity for component in composition.MAJOR)
ION_NOTE = "이온 시트와 이온 열은 염분에 기준 조성(Millero 외 2008)을 곱한 환산값. 이온을 직접 잰 값이 아님"
ION_LITRE_HEADERS = [(f"{component.symbol} mmol/L", 12) for component in composition.MAJOR]
CHECK_LABELS = {ranges.LOW: "낮음", ranges.HIGH: "높음"}
RANGE_NOTE = (
    "범위 검사 열은 염분이 남극해 수심별 범위(Boyer & Levitus 1994, NOAA NESDIS 81)를 벗어난 행에만 낮음·높음을 적음. "
    "범위가 넓어 큰 오류만 걸리며 값은 지우거나 고치지 않음"
)
VOLUME_NOTE = (
    "mmol/L 과 밀도는 같은 자료·위치·층·시각의 수온이 있는 행만 계산. 밀도는 그 수온과 염분의 1기압 값이고 현장 압력은 넣지 않음"
)
GRID_ION_NOTE = (
    "격자이온 시트는 염분 격자의 60°S 이남 평균과 해역 평균에 같은 계수를 곱한 값. 환산이 염분에 비례하므로 "
    "칸마다 환산해 평균한 값과 같음. 평균 염분은 소수 셋째 자리까지 저장된 값이고, 짝이 되는 수온이 없어 mmol/L 은 없음"
)
GRID_AREA_LABELS = {GRID_ALL: "남극해 전체 (60°S 이남)", **{key: name for key, name, *_ in SECTORS}}


def parse_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def month_bounds(month: str) -> tuple[str, str]:
    year, number = int(month[:4]), int(month[5:7])
    following = f"{year + 1}-01" if number == 12 else f"{year}-{number + 1:02d}"
    return f"{month}-01T00:00:00Z", f"{following}-01T00:00:00Z"


def _before(end: str) -> str:
    """iter_measurements의 until은 경계를 포함하므로 1초 앞으로 당깁니다."""
    return (parse_time(end) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def previous_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:7])
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def location_name(location_id: str | None) -> str:
    location = LOCATION_BY_ID.get(location_id or "")
    return location_label(location) if location else (location_id or "")


class Sheet:
    """머리글, 틀 고정, 필터를 갖춘 시트. 엑셀 행 한도를 넘으면 다음 시트로 이어 씁니다."""

    def __init__(self, book: "Book", name: str, columns: list[tuple[str, int]]):
        self.book, self.name, self.columns = book, tr(name), [(tr(label), width) for label, width in columns]
        self.part = 0
        self.total = 0
        self._open()

    def _open(self) -> None:
        self.part += 1
        title = self.name if self.part == 1 else f"{self.name}_{self.part}"
        self.sheet = self.book.workbook.add_worksheet(title)
        for index, (label, width) in enumerate(self.columns):
            self.sheet.set_column(index, index, width)
            self.sheet.write_string(0, index, label, self.book.header)
        self.sheet.freeze_panes(1, 0)
        self.row = 1

    def add(self, values: list) -> None:
        if self.row >= EXCEL_ROW_LIMIT:
            self._finish_part()
            self._open()
        for index, value in enumerate(values):
            if value is None or value == "":
                continue
            if isinstance(value, datetime):
                self.sheet.write_datetime(self.row, index, value, self.book.time)
            elif isinstance(value, (int, float)):
                self.sheet.write_number(self.row, index, value)
            else:
                self.sheet.write_string(self.row, index, str(value))
        self.row += 1
        self.total += 1

    def _finish_part(self) -> None:
        self.sheet.autofilter(0, 0, max(self.row - 1, 0), len(self.columns) - 1)

    def finish(self) -> int:
        self._finish_part()
        return self.total


class Book:
    """임시 파일에 쓰고 끝나면 교체합니다. 엑셀에서 파일을 열어 두면 Windows에서는 교체가 실패합니다."""

    def __init__(self, path: Path):
        self.path = path
        self.temp = path.with_name(f".{path.stem}.tmp.xlsx")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.workbook = xlsxwriter.Workbook(str(self.temp), {"constant_memory": True})
        self.header = self.workbook.add_format({"bold": True, "bottom": 1})
        self.time = self.workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"})

    def close(self) -> None:
        self.workbook.close()
        try:
            os.replace(self.temp, self.path)
        except PermissionError as exc:
            self.temp.unlink(missing_ok=True)
            raise PermissionError(tr("{name} 파일이 열려 있어 저장하지 못했습니다", name=self.path.name)) from exc


def write_main_workbook(store: Store, path: Path, month: str) -> dict[str, int]:
    start, end = month_bounds(month)
    until = _before(end)
    book = Book(path)
    info = book.workbook.add_worksheet(tr("정보"))
    counts = {
        "월간요약": _sheet_summary(book, store, month),
        "격자평균": _sheet_grids(book, store, start, end),
        "수온염분_해역": _sheet_water(book, store, start, until),
        "수온염분_수직": _sheet_vertical(book, store, start, until),
        "Argo_목록": _sheet_argo_list(book, store, start, end),
        "선박관측": _sheet_ships(book, store, start, until),
        "기지기온": _sheet_metar(book, store, start, until),
        "GFS기온": _sheet_air(book, store, start, until),
        "모델예보": _sheet_forecast(book, store, start, until),
        "Windy": _sheet_windy(book, store, start, until),
        "지점조회": _sheet_points(book, store, start, until),
        "이온조성": _sheet_ions(book, store, start, until),
        "격자이온": _sheet_grid_ions(book, store, start, until),
        "이온환산계수": _sheet_ion_factors(book),
        "염분범위": _sheet_ranges(book),
    }
    info.set_column(0, 0, 18)
    info.set_column(1, 1, 70)
    rows = (
        ("기간", month),
        ("생성 시각 UTC", iso()),
        ("시각 기준", tr("모든 시각은 UTC")),
        ("주의", tr("SQLite에서 다시 생성되는 파일. 직접 고친 내용은 다음 저장 때 덮어씀")),
        ("이온 환산", tr(ION_NOTE)),
        ("범위 검사", tr(RANGE_NOTE)),
        ("부피 기준", tr(VOLUME_NOTE)),
        ("격자 이온 환산", tr(GRID_ION_NOTE)),
    )
    for index, (label, value) in enumerate(rows):
        info.write_string(index, 0, tr(label), book.header)
        info.write_string(index, 1, value)
    top = len(rows) + 1
    info.write_string(top, 0, tr("시트"), book.header)
    info.write_string(top, 1, tr("행 수"), book.header)
    for index, (name, count) in enumerate(counts.items(), start=top + 1):
        info.write_string(index, 0, tr(name))
        info.write_number(index, 1, count)
    book.close()
    return counts


def _sheet_summary(book: Book, store: Store, month: str) -> int:
    """지점·자료·항목별 월간 통계와 전월 대비. 축적한 값이 그대로 요약이 되게 합니다."""
    start, end = month_bounds(month)
    earlier_start, earlier_end = month_bounds(previous_month(month))
    sheet = Sheet(
        book, "월간요약",
        [("지점", 20), ("자료", 18), ("항목", 11), ("단위", 9), ("표본 수", 8), ("평균", 9), ("최소", 8), ("최대", 8),
         ("표준편차", 9), ("첫 시각 UTC", 17), ("마지막 시각 UTC", 17), ("전월 평균", 9), ("전월 대비", 9)],
    )
    variables = tuple(SUMMARY_VARIABLES)
    earlier = {
        (row["location_id"], row["source"], row["variable"]): row["mean"]
        for row in store.location_stats(earlier_start, _before(earlier_end), SUMMARY_SOURCES, variables)
    }
    for row in store.location_stats(start, _before(end), SUMMARY_SOURCES, variables):
        spread = math.sqrt(max(0.0, row["mean_square"] - row["mean"] ** 2))
        before = earlier.get((row["location_id"], row["source"], row["variable"]))
        sheet.add(
            [
                location_name(row["location_id"]).removeprefix("metar:"), row["source"],
                tr(SUMMARY_VARIABLES[row["variable"]]), row["unit"],
                row["n"], round(row["mean"], 3), row["low"], row["high"], round(spread, 3),
                parse_time(row["first_time"]), parse_time(row["last_time"]),
                None if before is None else round(before, 3),
                None if before is None else round(row["mean"] - before, 3),
            ]
        )
    return sheet.finish()


def _sheet_grids(book: Book, store: Store, start: str, end: str) -> int:
    columns = [("시각 UTC", 17), ("레이어", 16), ("단위", 8), ("60°S 이남 평균", 13), ("최소", 8), ("최대", 8), ("유효 비율", 9)]
    columns += [(name, 11) for _, name, *_ in SECTORS]
    sheet = Sheet(book, "격자평균", columns)
    for row in store.grid_summaries(start, end):
        stats = json.loads(row["stats_json"])
        sheet.add(
            [
                parse_time(row["valid_time"]), row["layer"], row["unit"], stats["mean"], stats["min"], stats["max"],
                stats["coverage"], *[stats["sectors"][key]["mean"] for key, *_ in SECTORS],
            ]
        )
    return sheet.finish()


def _sheet_water(book: Book, store: Store, start: str, until: str) -> int:
    sheet = Sheet(
        book, "수온염분_해역",
        [("시각 UTC", 17), ("지점", 20), ("위도", 9), ("경도", 9), ("자료", 18), ("종류", 11), ("항목", 11), ("값", 9), ("단위", 9)],
    )
    for source in WATER_SOURCES:
        for row in store.iter_measurements(source=source, since=start, until=until):
            if row["location_id"] and row["variable"] in WATER_VARIABLES and row["level"] in ("surface", "depth:0"):
                sheet.add(
                    [
                        parse_time(row["obs_time"]), location_name(row["location_id"]), row["lat"], row["lon"], source,
                        row["kind"], tr(WATER_VARIABLES[row["variable"]]), row["value"], row["unit"],
                    ]
                )
    return sheet.finish()


def _sheet_vertical(book: Book, store: Store, start: str, until: str) -> int:
    sheet = Sheet(
        book, "수온염분_수직",
        [("시각 UTC", 17), ("지점", 20), ("위도", 9), ("경도", 9), ("수심 m", 8), ("수온 °C", 9), ("염분 PSU", 9)],
    )
    merged: dict[tuple, dict] = defaultdict(dict)
    for row in store.iter_measurements(source="hycom", since=start, until=until):
        if row["depth_m"] is None or not row["location_id"] or row["variable"] not in ("sea_water_temperature", "sea_water_salinity"):
            continue
        key = (row["obs_time"], row["location_id"], row["lat"], row["lon"], row["depth_m"])
        merged[key][row["variable"]] = row["value"]
    for key in sorted(merged, key=lambda k: (k[0], k[1], k[4])):
        values = merged[key]
        sheet.add(
            [
                parse_time(key[0]), location_name(key[1]), key[2], key[3], key[4],
                values.get("sea_water_temperature"), values.get("sea_water_salinity"),
            ]
        )
    return sheet.finish()


def _sheet_argo_list(book: Book, store: Store, start: str, end: str) -> int:
    sheet = Sheet(
        book, "Argo_목록",
        [("시각 UTC", 17), ("플로트", 10), ("회차", 6), ("위도", 9), ("경도", 9), ("모드", 6), ("위치 QC", 7),
         ("표층 수온 °C", 11), ("표층 염분 PSU", 12), ("최대 수심 m", 10), ("층 수", 6)],
    )
    for row in reversed(store.argo_list(since=start)):
        if row["obs_time"] < end:
            sheet.add(
                [
                    parse_time(row["obs_time"]), row["platform"], row["cycle"], row["lat"], row["lon"], row["data_mode"],
                    row["position_qc"], row["surface_temp"], row["surface_salt"], row["max_depth_m"], row["n_levels"],
                ]
            )
    return sheet.finish()


def _sheet_ships(book: Book, store: Store, start: str, until: str) -> int:
    sheet = Sheet(book, "선박관측", [("시각 UTC", 17), ("호출부호", 11), ("위도", 9), ("경도", 9), ("수온 °C", 9), ("염분 PSU", 9)])
    merged: dict[tuple, dict] = defaultdict(dict)
    for row in store.iter_measurements(source="gosud", since=start, until=until):
        merged[(row["obs_time"], row["dataset"], row["lat"], row["lon"])][row["variable"]] = row["value"]
    for key in sorted(merged):
        values = merged[key]
        sheet.add([parse_time(key[0]), key[1], key[2], key[3], values.get("sea_water_temperature"), values.get("sea_water_salinity")])
    return sheet.finish()


def _sheet_metar(book: Book, store: Store, start: str, until: str) -> int:
    sheet = Sheet(
        book, "기지기온",
        [("시각 UTC", 17), ("ICAO", 7), ("기지", 30), ("위도", 9), ("경도", 9), ("기온 °C", 8), ("이슬점 °C", 9), ("해면 기압 hPa", 12)],
    )
    merged: dict[tuple, dict] = defaultdict(dict)
    for row in store.iter_measurements(source="metar", since=start, until=until):
        entry = merged[(row["obs_time"], row["dataset"], row["lat"], row["lon"])]
        entry[row["variable"]] = row["value"]
        entry["name"] = row["quality"]
    for key in sorted(merged):
        values = merged[key]
        sheet.add(
            [
                parse_time(key[0]), key[1], values.get("name"), key[2], key[3], values.get("air_temperature"),
                values.get("dew_point"), values.get("sea_level_pressure"),
            ]
        )
    return sheet.finish()


def _sheet_air(book: Book, store: Store, start: str, until: str) -> int:
    columns = [("시각 UTC", 17), ("지점", 20), ("위도", 9), ("경도", 9)] + [(label, 10) for _, label in AIR_CURRENT]
    sheet = Sheet(book, "GFS기온", columns)
    merged: dict[tuple, dict] = defaultdict(dict)
    for row in store.iter_measurements(source="openmeteo", dataset="gfs_global", since=start, until=until):
        if row["kind"] == "model" and row["location_id"]:
            merged[(row["obs_time"], row["location_id"], row["lat"], row["lon"])][row["variable"]] = row["value"]
    for key in sorted(merged):
        values = merged[key]
        sheet.add([parse_time(key[0]), location_name(key[1]), key[2], key[3], *[values.get(v) for v, _ in AIR_CURRENT]])
    return sheet.finish()


def _sheet_forecast(book: Book, store: Store, start: str, until: str) -> int:
    columns = [("예보 시각 UTC", 17), ("지점", 20), ("위도", 9), ("경도", 9)] + [(f"{label} °C", 10) for label in MODELS.values()]
    sheet = Sheet(book, "모델예보", columns)
    merged: dict[tuple, dict] = defaultdict(dict)
    for row in store.iter_measurements(source="openmeteo", variable="air_temperature", since=start, until=until):
        if row["kind"] == "forecast" and row["location_id"]:
            merged[(row["obs_time"], row["location_id"], row["lat"], row["lon"])][row["dataset"]] = row["value"]
    for key in sorted(merged):
        values = merged[key]
        sheet.add([parse_time(key[0]), location_name(key[1]), key[2], key[3], *[values.get(m) for m in MODELS]])
    return sheet.finish()


def _sheet_windy(book: Book, store: Store, start: str, until: str) -> int:
    sheet = Sheet(
        book, "Windy",
        [("예보 시각 UTC", 17), ("지점", 20), ("위도", 9), ("경도", 9), ("모델", 7), ("층", 9), ("항목", 18), ("값", 9), ("단위", 7), ("키 구분", 22)],
    )
    for row in store.iter_measurements(source="windy", since=start, until=until):
        sheet.add(
            [
                parse_time(row["obs_time"]), location_name(row["location_id"]), row["lat"], row["lon"], row["dataset"],
                row["level"], row["variable"], row["value"], row["unit"], row["quality"],
            ]
        )
    return sheet.finish()


def _sheet_points(book: Book, store: Store, start: str, until: str) -> int:
    """지도에서 고른 지점의 조회 결과."""
    sheet = Sheet(
        book, "지점조회",
        [("시각 UTC", 17), ("위도", 9), ("경도", 9), ("자료", 18), ("종류", 11), ("층", 10), ("항목", 22), ("값", 9), ("단위", 9)],
    )
    for source in POINT_SOURCES:
        for row in store.iter_measurements(source=source, since=start, until=until):
            if row["location_id"]:
                continue
            sheet.add(
                [
                    parse_time(row["obs_time"]), row["lat"], row["lon"], source, row["kind"], row["level"],
                    row["variable"], row["value"], row["unit"],
                ]
            )
    return sheet.finish()


def _rounded(value, digits: int):
    return None if value is None else round(value, digits)


def _check_cell(verdict: str | None) -> str | None:
    """범위 검사 칸. 범위 안이거나 판정이 없으면 비우고, 벗어난 값만 낮음·높음으로 적습니다."""
    label = CHECK_LABELS.get(verdict)
    return tr(label) if label else None


def _ion_cells(salinity, depth_m=None) -> list:
    """기준 염분, 주요 이온 여덟 가지의 g/kg, 범위 검사 칸. 환산할 수 없는 염분이면 칸을 비웁니다."""
    if not composition.usable(salinity):
        return []
    value = float(salinity)
    return [
        round(value * composition.REFERENCE_SALINITY_FACTOR, 4),
        *[round(value * factor, 5) for factor in ION_GRAM_FACTORS],
        _check_cell(ranges.check_salinity(value, depth_m)),
    ]


def _sheet_ions(book: Book, store: Store, start: str, until: str) -> int:
    """염분이 있는 모든 행의 이온 환산값. DB의 seawater_ions 표를 그대로 옮깁니다.

    짝이 되는 수온이 있는 행은 1기압 밀도와 mmol/L 을 더하고, 마지막 칸은 염분 범위 검사 표시입니다.
    """
    sheet = Sheet(
        book, "이온조성",
        [("시각 UTC", 17), ("지점", 20), ("위도", 9), ("경도", 9), ("자료", 18), ("종류", 11), ("층", 10), ("수심 m", 8),
         ("염분 PSU", 9), ("기준 염분 g/kg", 13), *ION_GRAM_HEADERS, *ION_MMOL_HEADERS,
         ("수온 °C", 8), ("1기압 밀도 kg/m³", 15), *ION_LITRE_HEADERS, ("범위 검사", 9)],
    )
    for row in store.iter_ions(since=start, until=until, mmol=True, temperature=True):
        sheet.add(
            [
                parse_time(row["obs_time"]), location_name(row["location_id"]), row["lat"], row["lon"], row["source"],
                row["kind"], row["level"], row["depth_m"], row["practical_salinity"], round(row["reference_salinity"], 4),
                *[round(row[column], 5) for column in ION_GRAM_COLUMNS],
                *[round(row[column], 4) for column in ION_MMOL_COLUMNS],
                row["temperature_c"], _rounded(row[ION_DENSITY], 3),
                *[_rounded(row[column], 4) for column in ION_LITRE_COLUMNS],
                _check_cell(row[ION_CHECK]),
            ]
        )
    return sheet.finish()


def _sheet_grid_ions(book: Book, store: Store, start: str, until: str) -> int:
    """염분 격자의 60°S 이남 평균과 해역 평균에서 환산한 이온 조성. DB의 grid_ions 뷰를 그대로 옮깁니다.

    평균 염분에 계수를 곱한 값이고, 범위 검사는 그 층의 수심으로 봅니다.
    """
    sheet = Sheet(
        book, "격자이온",
        [("시각 UTC", 17), ("레이어", 16), ("해역", 22), ("수심 m", 8), ("유효 격자 수", 11), ("염분 PSU", 9),
         ("기준 염분 g/kg", 13), *ION_GRAM_HEADERS, *ION_MMOL_HEADERS, ("범위 검사", 9)],
    )
    for row in store.iter_grid_ions(since=start, until=until):
        sheet.add(
            [
                parse_time(row["valid_time"]), row["layer"], tr(GRID_AREA_LABELS.get(row["area"], row["area"])),
                row["depth_m"], row["valid_cells"], row["practical_salinity"], round(row["reference_salinity"], 4),
                *[round(row[column], 5) for column in ION_GRAM_COLUMNS],
                *[round(row[column], 4) for column in ION_MMOL_COLUMNS],
                _check_cell(row[ION_CHECK]),
            ]
        )
    return sheet.finish()


def _sheet_ion_factors(book: Book) -> int:
    """환산에 쓴 기준 조성. 이 시트만 있으면 어느 염분이든 같은 값을 다시 계산할 수 있습니다."""
    sheet = Sheet(
        book, "이온환산계수",
        [("성분", 16), ("기호", 9), ("전하", 6), ("몰질량 g/mol", 12), ("질량 비율 %", 11), ("염분 1당 g/kg", 14),
         ("염분 1당 mmol/kg", 16), ("염분 35에서 g/kg", 15), ("염분 35에서 mmol/kg", 17), ("DB 열", 20)],
    )
    stored = {component.key for component in composition.MAJOR}
    for component in composition.COMPONENTS:
        sheet.add(
            [
                tr(component.name), component.symbol, component.charge, component.molar_mass,
                round(component.mass_fraction * 100.0, 5), component.grams_per_salinity, component.mmol_per_salinity,
                round(35.0 * component.grams_per_salinity, 5), round(35.0 * component.mmol_per_salinity, 4),
                f"{component.key}_g_kg" if component.key in stored else None,
            ]
        )
    return sheet.finish()


def _sheet_ranges(book: Book) -> int:
    """범위 검사에 쓴 수심별 염분 범위. 표준 수심마다 그 범위를 적용하는 수심 구간을 함께 적습니다."""
    sheet = Sheet(
        book, "염분범위",
        [("표준 수심 m", 12), ("적용 수심 초과 m", 15), ("적용 수심 이하 m", 15), ("염분 하한", 10), ("염분 상한", 10)],
    )
    for row in ranges.WINDOWS:
        sheet.add(list(row))
    return sheet.finish()


def write_argo_workbook(store: Store, path: Path, month: str) -> int:
    start, end = month_bounds(month)
    book = Book(path)
    sheet = Sheet(
        book, "Argo층별",
        [("시각 UTC", 17), ("플로트", 10), ("회차", 6), ("위도", 9), ("경도", 9), ("모드", 6), ("압력 dbar", 9), ("수심 m", 8),
         ("수온 °C", 8), ("염분 PSU", 9), ("기준 염분 g/kg", 13), *ION_GRAM_HEADERS, ("범위 검사", 9)],
    )
    profiles = [p for p in store.argo_with_levels(since=start) if p["obs_time"] < end]
    for profile in sorted(profiles, key=lambda p: (p["obs_time"], p["platform"])):
        when = parse_time(profile["obs_time"])
        for level in profile["levels"]:
            salt = level.get("salt")
            sheet.add(
                [
                    when, profile["platform"], profile["cycle"], profile["lat"], profile["lon"], profile["data_mode"],
                    level.get("pressure_dbar"), level.get("depth_m"), level.get("temp"), salt,
                    *_ion_cells(salt, level.get("depth_m")),
                ]
            )
    count = sheet.finish()
    book.close()
    return count


def months_to_write(store: Store, directory: Path, now: datetime | None = None) -> list[str]:
    """이번 달과 그 이후, 지난달, 아직 파일이 없는 달을 다시 씁니다. 끝난 달은 건드리지 않습니다."""
    moment = now or utcnow()
    previous = previous_month(moment.strftime("%Y-%m"))
    output = [
        month for month in store.months_with_data()
        if month >= previous or not (directory / MAIN_FILE.format(month=month)).exists()
    ]
    return output or [moment.strftime("%Y-%m")]


def sync(store: Store, directory: Path, months: list[str] | None = None) -> dict:
    written, rows = [], 0
    for month in months or months_to_write(store, directory):
        name = MAIN_FILE.format(month=month)
        rows += sum(write_main_workbook(store, directory / name, month).values())
        written.append(name)
        start, end = month_bounds(month)
        if any(p["obs_time"] < end for p in store.argo_with_levels(since=start)):
            name = ARGO_FILE.format(month=month)
            rows += write_argo_workbook(store, directory / name, month)
            written.append(name)
    return {"files": written, "rows": rows}


def sync_command(store_path: Path, directory: Path, result_path: Path | None = None) -> list[str]:
    """별도 프로세스에서 sync를 돌릴 명령줄. 설치판에서는 실행 파일 자체가 명령을 받습니다."""
    base = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "antarctic_monitor"]
    command = [*base, "--lang", get_language(), "excel-sync", "--db", str(store_path), "--dir", str(directory)]
    if result_path:
        command += ["--result", str(result_path)]
    return command


async def collect(ctx: Context) -> CollectResult:
    """바뀐 내용이 있을 때만 별도 프로세스에서 파일을 만듭니다. 화면과 수집을 막지 않기 위함입니다."""
    stamp = ctx.store.data_stamp()
    directory = ctx.settings.excel_dir
    if stamp and ctx.store.kv_get("excel:stamp") == stamp and any(directory.glob("antarctic_db_*.xlsx")):
        return CollectResult(unchanged=True, message=msg("새 자료 없음"))
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        result_path = Path(temp) / "result.json"
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = await asyncio.create_subprocess_exec(
            *sync_command(ctx.store.path, directory, result_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=flags,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not result_path.exists():
            lines = stderr.decode("utf-8", "replace").strip().splitlines()
            raise FetchError(lines[-1] if lines else msg("엑셀 저장 프로세스 종료 코드 {code}", code=process.returncode))
        result = json.loads(result_path.read_text(encoding="utf-8"))
    ctx.store.kv_set("excel:stamp", stamp or "")
    return CollectResult(rows=result["rows"], data_time=iso(), message=join(*result["files"]))
