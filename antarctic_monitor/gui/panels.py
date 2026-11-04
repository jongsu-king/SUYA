"""공용 표와 지점 상세 탭 네 개: 표층, 수직 프로파일, 기온, 시계열."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..catalog import KIND_LABEL
from ..i18n import render, tr
from .charts import Chart
from .format import age, coord_text, num, parse_time, percent, short_time
from .theme import LIGHT, Theme, series_color

VARIABLE_GROUPS = (("temperature", "수온"), ("salinity", "염분"), ("anomaly", "수온 편차"), ("ice", "해빙"))


class DataTable(QTableWidget):
    """격자 표. 선택한 행을 복사하면 탭으로 구분되어 엑셀에 바로 붙습니다."""

    def __init__(self, headers: list[str], numeric: set[int] = frozenset()):
        super().__init__(0, len(headers))
        self.numeric = set(numeric)
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(21)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def put(self, row: int, column: int, text: str, *, color: str | None = None, bold: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if column in self.numeric:
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if color:
            item.setForeground(QColor(color))
        if bold:
            font = QFont(self.font())
            font.setBold(True)
            item.setFont(font)
        self.setItem(row, column, item)
        return item

    def group_row(self, text: str) -> int:
        row = self.rowCount()
        self.insertRow(row)
        self.put(row, 0, text, bold=True)
        self.setSpan(row, 0, 1, self.columnCount())
        return row

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            rows = sorted({index.row() for index in self.selectedIndexes()})
            lines = []
            for row in rows:
                cells = [self.item(row, c).text() if self.item(row, c) else "" for c in range(self.columnCount())]
                lines.append("\t".join(cells))
            QGuiApplication.clipboard().setText("\n".join(lines))
            return
        super().keyPressEvent(event)


class DetailPanel(QScrollArea):
    """지점 상세 탭의 공통 뼈대. 응답을 기다리는 동안 이전 내용을 유지합니다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.theme: Theme = LIGHT
        self.data: dict | None = None
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(4, 4, 4, 4)
        self.body.setSpacing(4)
        self.loading = QLabel()
        self.loading.setVisible(False)
        self.body.addWidget(self.loading)
        self.setWidget(body)
        self.errors = QLabel()
        self.errors.setWordWrap(True)
        self.errors.setVisible(False)

    def charts(self) -> list[Chart]:
        return self.findChildren(Chart)

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        for chart in self.charts():
            chart.set_theme(theme)
        if self.data is not None:
            self.show_data(self.data)

    def set_loading(self, text: str) -> None:
        self.loading.setText(text)
        self.loading.setVisible(bool(text))

    def show_error(self, message: str) -> None:
        self.set_loading(tr("오류: {message}", message=render(message)))

    def show_data(self, data: dict) -> None:
        self.data = data
        self.set_loading("")
        self.render(data)
        problems = data.get("errors") or []
        self.errors.setText(
            tr("응답 없음: {items}", items=", ".join(f"{e['source']} ({render(e['message'])})" for e in problems))
            if problems else ""
        )
        self.errors.setStyleSheet(f"color: {self.theme.error}")
        self.errors.setVisible(bool(problems))

    def render(self, data: dict) -> None:
        raise NotImplementedError


class WaterPanel(DetailPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = DataTable([tr("항목"), tr("값"), tr("종류"), tr("자료 시각"), tr("경과"), tr("비고")], numeric={1})
        self.table.setMinimumHeight(420)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(self.errors)

    def render(self, data: dict) -> None:
        table = self.table
        table.clearSpans()
        table.setRowCount(0)
        headline = data["headline"]
        temp, salt, derived = headline["temperature"], headline["salinity"], headline.get("derived") or {}

        def summary(label: str, value: str, source: dict | None = None, note: str = "") -> None:
            row = table.rowCount()
            table.insertRow(row)
            table.put(row, 0, label)
            table.put(row, 1, value)
            if source:
                table.put(row, 2, tr(KIND_LABEL.get(source["kind"], source["kind"])))
                table.put(row, 3, short_time(source["time"]))
                table.put(row, 4, age(source["time"]))
                note = render(source["label"])
            table.put(row, 5, note)

        table.group_row(tr("대표값"))
        summary(tr("표층 수온"), f"{num(temp['value'], 2)} °C" if temp else "–", temp)
        summary(tr("표층 염분"), f"{num(salt['value'], 2)} PSU" if salt else "–", salt)
        summary(tr("어는점"), f"{num(derived.get('freezing_point_c'), 2)} °C", note="Millero 1978")
        summary(tr("어는점과의 차"), f"{num(derived.get('above_freezing_c'), 2)} °C")
        summary("σt", f"{num(derived.get('sigma_t'), 2)} kg/m³", note="EOS-80")

        for variable, label in VARIABLE_GROUPS:
            group = [row for row in data["rows"] if row["variable"] == variable]
            if not group:
                continue
            table.group_row(tr(label))
            for item in group:
                row = table.rowCount()
                table.insertRow(row)
                value = item["value"]
                if value is None:
                    text = tr("결측")
                elif variable == "ice":
                    text = percent(value)
                else:
                    text = f"{num(value, 2)} {item['unit']}".strip()
                table.put(row, 0, render(item["label"]))
                table.put(row, 1, text, color=self.theme.muted if value is None else None)
                table.put(row, 2, tr(KIND_LABEL.get(item["kind"], item["kind"])))
                table.put(row, 3, short_time(item["time"]))
                table.put(row, 4, age(item["time"]))
                table.put(row, 5, render(item.get("note")))


def _levels(levels: list[dict] | None, key: str) -> tuple[list[float], list[float]]:
    pairs = [(lv["depth_m"], lv[key]) for lv in (levels or []) if lv.get(key) is not None]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def _ts_points(levels: list[dict] | None) -> dict:
    rows = [lv for lv in (levels or []) if lv.get("temp") is not None and lv.get("salt") is not None]
    return {
        "salts": np.array([lv["salt"] for lv in rows], dtype=float),
        "temps": np.array([lv["temp"] for lv in rows], dtype=float),
        "depths": np.array([lv["depth_m"] for lv in rows], dtype=float),
    }


PROFILE_STYLE = {"argo": {"style": "-"}, "hycom": {"style": "-", "marker": "o"}, "woa": {"style": "--"}}


class ProfilePanel(DetailPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        pair = QHBoxLayout()
        pair.setSpacing(4)
        self.temp_chart = Chart(height=280)
        self.salt_chart = Chart(height=280)
        pair.addWidget(self.temp_chart, 1)
        pair.addWidget(self.salt_chart, 1)
        self.ts_chart = Chart(height=260)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addLayout(pair, 5)
        self.body.addWidget(self.ts_chart, 4)
        self.body.addWidget(self.note)
        self.body.addWidget(self.errors)

    def render(self, data: dict) -> None:
        argo, hycom, woa = data.get("argo"), data.get("hycom"), data.get("woa")
        t = self.theme
        names = (("argo", "Argo", argo), ("hycom", "HYCOM", hycom), ("woa", tr("WOA23 기후값"), woa))

        def depth_series(key: str) -> list[dict]:
            output = []
            for source, name, item in names:
                depths, values = _levels(item.get("levels") if item else None, key)
                output.append({"name": name, "color": series_color(t, source), "depths": depths, "values": values, **PROFILE_STYLE[source]})
            return output

        self.temp_chart.depth(tr("수온"), depth_series("temp"), tr("수온 (°C)"), unit="°C")
        self.salt_chart.depth(tr("염분"), depth_series("salt"), tr("염분 (PSU)"), unit="PSU")
        self.ts_chart.ts(
            tr("T-S 다이어그램 (등치선: σt)"),
            [
                {"name": name, "color": series_color(t, source), "style": PROFILE_STYLE[source]["style"], **_ts_points(item.get("levels") if item else None)}
                for source, name, item in names
            ],
        )
        lines = []
        if argo:
            mode = {"R": tr("실시간"), "A": tr("보정"), "D": tr("지연 보정")}.get(argo["data_mode"], argo["data_mode"])
            estimated = tr(", 추정 위치") if argo.get("position_qc") == "8" else ""
            lines.append(
                f"Argo {argo['platform']} #{argo['cycle']}: {round(argo['distance_km'])} km, "
                f"{short_time(argo['time'])}, {mode}{estimated}"
            )
        else:
            lines.append(tr("Argo: 500 km 이내 최근 45일 프로파일 없음"))
        if hycom:
            lines.append(
                f"HYCOM: {coord_text(hycom['lat'], hycom['lon'])}, {short_time(hycom['time'])}"
                if hycom["levels"] else f"HYCOM: {render(hycom['reason'])}"
            )
        if woa:
            lines.append(
                tr("WOA23: {month}월 기후값 (1500 m 아래 연평균)", month=woa["month"])
                if woa["levels"] else f"WOA23: {render(woa['reason'])}"
            )
        self.note.setText("\n".join(lines))


AIR_FIELDS = (
    ("air_temperature", "기온", 1), ("apparent_temperature", "체감", 1), ("dew_point", "이슬점", 1),
    ("wet_bulb_temperature", "습구", 1), ("surface_temperature", "지표 온도", 1), ("relative_humidity", "상대 습도", 0),
    ("surface_pressure", "지표 기압", 0), ("wind_speed", "풍속", 0),
)


class AirPanel(DetailPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.group = QGroupBox(tr("현재 (GFS)"))
        grid = QGridLayout(self.group)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        self.values: dict[str, QLabel] = {}
        for index, (key, label, _) in enumerate(AIR_FIELDS):
            value = QLabel("–")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(QLabel(tr(label)), index // 4, (index % 4) * 2)
            grid.addWidget(value, index // 4, (index % 4) * 2 + 1)
            self.values[key] = value
        self.forecast_chart = Chart(height=230)
        self.obs_chart = Chart(height=170)
        self.pressure_chart = Chart(height=270)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.body.addWidget(self.group)
        self.body.addWidget(self.forecast_chart)
        self.body.addWidget(self.obs_chart)
        self.body.addWidget(self.pressure_chart)
        self.body.addWidget(self.note)
        self.body.addWidget(self.errors)
        self.body.addStretch(1)

    def render(self, data: dict) -> None:
        air, observations, windy = data.get("air"), data.get("observations"), data.get("windy")
        t = self.theme
        if windy and windy.get("configured"):
            self.note.setText(tr("Windy: testing 키, 값이 변형되어 있음") if windy.get("testing") else tr("Windy: 공식 API 값"))
        else:
            self.note.setText(tr("Windy: API 키 없음 (파일 > 설정)"))
        windy_name = tr("Windy GFS (변형값)") if windy and windy.get("testing") else "Windy GFS"
        if air:
            self.group.setTitle(tr("현재 (GFS, {time})", time=short_time(air["current_time"])))
            for key, _, digits in AIR_FIELDS:
                item = air["current"][key]
                self.values[key].setText(f"{num(item['value'], digits)} {item['unit']}")
            times = [parse_time(moment) for moment in air["forecast"]["times"]]
            series = [
                {"name": s["label"], "color": series_color(t, s["id"]), "times": times, "values": s["values"]}
                for s in air["forecast"]["series"]
            ]
            if windy and windy.get("forecast"):
                series.append({
                    "name": windy_name, "color": series_color(t, "windy"),
                    "times": [parse_time(row["time"]) for row in windy["forecast"]],
                    "values": [row["value"] for row in windy["forecast"]],
                })
            self.forecast_chart.line(tr("2 m 기온 예보, 모델별"), series, unit="°C", now_line=True)
            levels = []
            for key, name in (("gfs_global", "GFS"), ("ecmwf_ifs025", "ECMWF IFS")):
                rows = [row for row in air["pressure_profile"] if row[key] is not None]
                levels.append({
                    "name": name, "color": series_color(t, key),
                    "pressures": [row["pressure_hpa"] for row in rows], "values": [row[key] for row in rows],
                })
            if windy and windy.get("pressure_profile"):
                rows = sorted(windy["pressure_profile"], key=lambda r: -r["pressure_hpa"])
                levels.append({
                    "name": windy_name, "color": series_color(t, "windy"),
                    "pressures": [row["pressure_hpa"] for row in rows], "values": [row["value"] for row in rows],
                })
            self.pressure_chart.pressure(tr("고도별 기온"), levels)
        else:
            self.forecast_chart.show_message(tr("2 m 기온 예보, 모델별"), tr("자료 없음"))
            self.pressure_chart.show_message(tr("고도별 기온"), tr("자료 없음"))

        if observations:
            station = observations[0]
            self.obs_chart.line(
                tr("기지 실측: {station} ({km} km)", station=station.get("name") or station["icao"], km=round(station["distance_km"])),
                [{
                    "name": station["icao"], "color": t.series[0],
                    "times": [parse_time(row["time"]) for row in station["history"]],
                    "values": [row["value"] for row in station["history"]],
                }],
                unit="°C",
            )
        else:
            self.obs_chart.show_message(tr("기지 실측"), tr("400 km 이내 METAR 기지 없음"))


class SeriesPanel(DetailPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sst_chart = Chart(height=180)
        self.sss_chart = Chart(height=180)
        self.ice_chart = Chart(height=150)
        self.era_chart = Chart(height=190)
        for chart in (self.sst_chart, self.sss_chart, self.ice_chart, self.era_chart):
            self.body.addWidget(chart)
        self.body.addWidget(self.errors)
        self.body.addStretch(1)

    def render(self, data: dict) -> None:
        t = self.theme

        def points(rows: list[dict], key: str, factor: float = 1.0) -> dict:
            return {
                "times": [parse_time(row["time"]) for row in rows],
                "values": [None if row.get(key) is None else row[key] * factor for row in rows],
            }

        days = data["days"]
        self.sst_chart.line(
            tr("표층 수온, OISST ({days}일)", days=days),
            [{"name": "SST", "color": t.series[0], **points(data["oisst"], "oisst_sst")}], unit="°C", digits=2,
        )
        self.sss_chart.line(
            tr("표층 염분, 위성 ({days}일)", days=days),
            [
                {"name": "SMOS", "color": series_color(t, "smos"), **points(data["smos"], "smos_sss")},
                {"name": "SMAP", "color": series_color(t, "smap"), **points(data["smap"], "smap_sss")},
            ],
            unit="PSU", digits=2, empty=tr("결측 (해빙 또는 연안)"),
        )
        self.ice_chart.line(
            tr("해빙 농도, OISST ({days}일)", days=days),
            [{"name": tr("해빙"), "color": t.series[0], **points(data["oisst"], "oisst_ice", 100.0)}],
            unit="%", digits=0, y_limits=(0, 100), empty=tr("해빙 없음"),
        )
        era5 = data.get("era5")
        if era5 and era5["times"]:
            self.era_chart.line(
                tr("기온, ERA5 일평균·최저·최고"),
                [{
                    "name": tr("일평균"), "color": t.series[0], "times": [parse_time(m) for m in era5["times"]],
                    "values": era5["mean"], "low": era5["min"], "high": era5["max"],
                }],
                unit="°C",
            )
        else:
            self.era_chart.show_message(tr("기온, ERA5 일평균·최저·최고"), tr("자료 없음"))
