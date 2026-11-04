"""matplotlib 차트 위젯. 축 눈금을 안쪽으로 둔 과학 그래프 양식이고, 기본 도구막대로 확대·저장합니다.

차트 하나에 축은 하나이며, 수온과 염분은 나눠서 그립니다.
"""

from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_API", "pyside6")

import matplotlib  # noqa: E402

matplotlib.use("QtAgg")

import matplotlib.dates as mdates  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.backends.backend_qt import NavigationToolbar2QT  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QCursor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QDialog, QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from ..i18n import tr  # noqa: E402
from ..seawater import density_surface, freezing_point_c  # noqa: E402
from .format import num  # noqa: E402
from .theme import LIGHT, Theme  # noqa: E402

KOREAN_FONTS = ("Apple SD Gothic Neo", "AppleGothic", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR")
DEPTH_TICKS = (0, 10, 50, 100, 200, 500, 1000, 2000, 3000, 4000, 5000)
PRESSURE_TICKS = (1000, 850, 700, 500, 300, 200, 100, 50, 30, 10)
LOCAL_TZ = datetime.now().astimezone().tzinfo
TOOLBAR_KEEP = {"Home", "Back", "Forward", "Pan", "Zoom", "Save"}
TOOLBAR_TIPS = {
    "Home": "처음 범위", "Back": "이전", "Forward": "다음", "Pan": "이동", "Zoom": "영역 확대", "Save": "그림 저장",
}


def _available_fonts() -> list[str]:
    """설치된 글꼴만 고릅니다. 없는 글꼴을 넣으면 그릴 때마다 경고가 쌓입니다."""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    return [name for name in KOREAN_FONTS if name in installed] + ["DejaVu Sans"]


matplotlib.rcParams["font.family"] = _available_fonts()
matplotlib.rcParams["axes.unicode_minus"] = False


class TableDialog(QDialog):
    def __init__(self, title: str, headers: list[str], rows: list[list[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        table = QTableWidget(len(rows), len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(20)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                item = QTableWidgetItem("–" if cell is None else str(cell))
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)


class Chart(QWidget):
    def __init__(self, height: int = 240, parent=None):
        super().__init__(parent)
        self.theme: Theme = LIGHT
        self.figure = Figure(layout="constrained", dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(height)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.toolbar.setIconSize(QSize(14, 14))
        self.toolbar.setMovable(False)
        for action in self.toolbar.actions():
            name = action.text()
            if name and name not in TOOLBAR_KEEP:
                self.toolbar.removeAction(action)
            elif name in TOOLBAR_TIPS:
                action.setToolTip(tr(TOOLBAR_TIPS[name]))
        self.table_action = self.toolbar.addAction(tr("표"))
        self.table_action.setToolTip(tr("값을 표로 보기"))
        self.table_action.triggered.connect(self._show_table)
        self.table_action.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self._title = ""
        self._table: tuple[list[str], list[list[str]]] | None = None
        self._hover = None
        self._crosshair = None
        self.canvas.mpl_connect("motion_notify_event", self._on_move)
        self.canvas.mpl_connect("axes_leave_event", self._on_leave)
        self.show_message("", tr("자료 없음"))

    def set_theme(self, theme: Theme) -> None:
        """색을 바꿉니다. 시리즈 색이 테마마다 달라서 다시 그리는 일은 패널이 맡습니다."""
        self.theme = theme
        self.figure.set_facecolor(theme.surface)
        self.canvas.draw_idle()

    def _begin(self, title: str):
        self._title = title
        self.figure.clear()
        t = self.theme
        self.figure.set_facecolor(t.surface)
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(t.surface)
        for spine in ax.spines.values():
            spine.set_color(t.ink)
            spine.set_linewidth(0.7)
        ax.tick_params(colors=t.ink, labelsize=8, direction="in", length=3, width=0.6, top=True, right=True)
        ax.grid(True, color=t.grid, linewidth=0.5)
        ax.set_axisbelow(True)
        ax.set_title(title, loc="left", fontsize=9, color=t.ink, pad=4)
        self._crosshair = None
        self._hover = None
        return ax

    def show_message(self, title: str, message: str) -> None:
        ax = self._begin(title)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center", fontsize=9, color=self.theme.muted, wrap=True)
        self._table = None
        self.table_action.setEnabled(False)
        self.canvas.draw_idle()

    def _legend(self, ax, handles: int) -> None:
        if handles < 2:
            return
        t = self.theme
        legend = ax.legend(
            fontsize=8, frameon=True, fancybox=False, framealpha=0.9, edgecolor=t.ink, facecolor=t.surface,
            labelcolor=t.ink, borderpad=0.3, handlelength=1.8, loc="best",
        )
        legend.get_frame().set_linewidth(0.5)

    def _set_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self._table = (headers, rows)
        self.table_action.setEnabled(bool(rows))

    def _show_table(self) -> None:
        if self._table:
            TableDialog(self._title, *self._table, parent=self).exec()

    # ---- 시간-값 ----
    def line(
        self, title: str, series: list[dict], unit: str = "", digits: int = 1, now_line: bool = False,
        empty: str | None = None, y_limits: tuple[float, float] | None = None,
    ) -> None:
        """series: [{name, color, times: [datetime], values: [float|None], low?, high?}]"""
        usable = [s for s in series if any(v is not None for v in s["values"])]
        if not usable:
            self.show_message(title, empty or tr("자료 없음"))
            return
        ax = self._begin(title)
        t = self.theme
        for s in usable:
            xs = mdates.date2num(s["times"])
            ys = np.array([np.nan if v is None else v for v in s["values"]], dtype=float)
            ax.plot(xs, ys, color=s["color"], linewidth=1.2, label=s["name"], linestyle=s.get("style", "-"))
            if s.get("low") is not None:
                low = np.array([np.nan if v is None else v for v in s["low"]], dtype=float)
                high = np.array([np.nan if v is None else v for v in s["high"]], dtype=float)
                ax.fill_between(xs, low, high, color=s["color"], alpha=0.15, linewidth=0)
        if now_line:
            ax.axvline(mdates.date2num(datetime.now(LOCAL_TZ)), color=t.ink, linewidth=0.8)
        ax.xaxis_date(tz=LOCAL_TZ)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=LOCAL_TZ, minticks=3, maxticks=8))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d", tz=LOCAL_TZ))
        if unit:
            ax.set_ylabel(unit, fontsize=8, color=t.ink)
        if y_limits:
            ax.set_ylim(*y_limits)
        self._legend(ax, len(usable))

        all_times = sorted({moment for s in usable for moment in s["times"]})
        lookups = [(s, dict(zip(s["times"], s["values"]))) for s in usable]
        positions = mdates.date2num(all_times)
        self._crosshair = ax.axvline(positions[0], color=t.muted, linewidth=0.6, visible=False)
        suffix = f" {unit}" if unit else ""

        def hover(event):
            index = int(np.argmin(np.abs(positions - event.xdata)))
            moment = all_times[index]
            self._crosshair.set_xdata([positions[index], positions[index]])
            self._crosshair.set_visible(True)
            rows = [moment.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")]
            for s, values in lookups:
                value = values.get(moment)
                if value is not None:
                    rows.append(f"{s['name']}: {num(value, digits)}{suffix}")
            return "\n".join(rows)

        self._hover = hover
        self._set_table(
            [tr("시각"), *[s["name"] for s in usable]],
            [
                [moment.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M"), *[num(values.get(moment), digits) for _, values in lookups]]
                for moment in all_times
            ],
        )
        self.canvas.draw_idle()

    # ---- 수심 프로파일 ----
    def depth(self, title: str, series: list[dict], xlabel: str, unit: str = "", digits: int = 2) -> None:
        """series: [{name, color, depths, values, style?, marker?}]. 표층을 넓게 보도록 제곱근 축을 씁니다."""
        usable = [s for s in series if len(s["depths"])]
        if not usable:
            self.show_message(title, tr("자료 없음"))
            return
        ax = self._begin(title)
        t = self.theme
        deepest = max(max(s["depths"]) for s in usable)
        for s in usable:
            ax.plot(
                s["values"], s["depths"], color=s["color"], linewidth=1.2, label=s["name"],
                linestyle=s.get("style", "-"), marker=s.get("marker"), markersize=2.5,
            )
        ax.set_yscale("function", functions=(lambda d: np.sqrt(np.maximum(d, 0)), np.square))
        ax.set_ylim(deepest, 0)
        ax.set_yticks([d for d in DEPTH_TICKS if d <= deepest])
        ax.set_ylabel(tr("수심 (m)"), fontsize=8, color=t.ink)
        ax.set_xlabel(xlabel, fontsize=8, color=t.ink)
        self._legend(ax, len(usable))
        self._crosshair = ax.axhline(0, color=t.muted, linewidth=0.6, visible=False)
        suffix = f" {unit}" if unit else ""

        def hover(event):
            depth = event.ydata
            self._crosshair.set_ydata([depth, depth])
            self._crosshair.set_visible(True)
            rows = [f"{round(depth)} m"]
            for s in usable:
                index = int(np.argmin(np.abs(np.asarray(s["depths"]) - depth)))
                nearest = s["depths"][index]
                if abs(nearest - depth) <= max(10.0, depth * 0.25):
                    rows.append(f"{s['name']} ({round(nearest)} m): {num(s['values'][index], digits)}{suffix}")
            return "\n".join(rows)

        self._hover = hover
        rows = []
        for s in usable:
            rows.extend([s["name"], f"{round(d)}", num(v, digits)] for d, v in zip(s["depths"], s["values"]))
        self._set_table([tr("자료"), tr("수심 m"), xlabel], rows)
        self.canvas.draw_idle()

    # ---- 기압 고도 ----
    def pressure(self, title: str, series: list[dict], digits: int = 1) -> None:
        """series: [{name, color, pressures, values}]"""
        usable = [s for s in series if len(s["pressures"])]
        if not usable:
            self.show_message(title, tr("자료 없음"))
            return
        ax = self._begin(title)
        t = self.theme
        for s in usable:
            ax.plot(s["values"], s["pressures"], color=s["color"], linewidth=1.2, marker="o", markersize=2.5, label=s["name"])
        ax.set_yscale("log")
        ax.set_ylim(1000, 10)
        ax.set_yticks(list(PRESSURE_TICKS))
        ax.set_yticklabels([str(p) for p in PRESSURE_TICKS])
        ax.minorticks_off()
        ax.set_ylabel("hPa", fontsize=8, color=t.ink)
        ax.set_xlabel(tr("기온 (°C)"), fontsize=8, color=t.ink)
        self._legend(ax, len(usable))
        self._crosshair = ax.axhline(1000, color=t.muted, linewidth=0.6, visible=False)
        levels = sorted({p for s in usable for p in s["pressures"]})

        def hover(event):
            pressure = min(levels, key=lambda p: abs(np.log(p / event.ydata)))
            self._crosshair.set_ydata([pressure, pressure])
            self._crosshair.set_visible(True)
            rows = [f"{pressure:g} hPa"]
            for s in usable:
                if pressure in s["pressures"]:
                    rows.append(f"{s['name']}: {num(s['values'][s['pressures'].index(pressure)], digits)} °C")
            return "\n".join(rows)

        self._hover = hover
        self._set_table(
            ["hPa", *[s["name"] for s in usable]],
            [
                [f"{p:g}", *[num(s["values"][s["pressures"].index(p)], digits) if p in s["pressures"] else "–" for s in usable]]
                for p in sorted(levels, reverse=True)
            ],
        )
        self.canvas.draw_idle()

    # ---- T-S 다이어그램 ----
    def ts(self, title: str, series: list[dict]) -> None:
        """series: [{name, color, salts, temps, depths}]. 회색 등치선은 σt, 가는 선은 어는점입니다."""
        usable = [s for s in series if len(s["salts"])]
        if not usable:
            self.show_message(title, tr("자료 없음"))
            return
        ax = self._begin(title)
        t = self.theme
        salts = np.concatenate([s["salts"] for s in usable])
        temps = np.concatenate([s["temps"] for s in usable])
        s_low, s_high = float(np.min(salts)) - 0.06, float(np.max(salts)) + 0.06
        t_low, t_high = min(float(np.min(temps)), -2.1) - 0.1, float(np.max(temps)) + 0.25
        s_axis, t_axis = np.meshgrid(np.linspace(s_low, s_high, 60), np.linspace(t_low, t_high, 60))
        sigma = density_surface(s_axis, t_axis) - 1000.0
        contour = ax.contour(s_axis, t_axis, sigma, levels=6, colors=t.muted, linewidths=0.4)
        ax.clabel(contour, fontsize=7, fmt=lambda v: f"{v:.1f}", colors=t.muted)
        freeze_s = np.linspace(s_low, s_high, 30)
        ax.plot(freeze_s, [freezing_point_c(float(v)) for v in freeze_s], color=t.ink, linewidth=0.7, label=tr("어는점"))
        for s in usable:
            ax.plot(s["salts"], s["temps"], color=s["color"], linewidth=0.9, marker="o", markersize=2.5, label=s["name"], linestyle=s.get("style", "-"))
        ax.set_xlim(s_low, s_high)
        ax.set_ylim(t_low, t_high)
        ax.set_xlabel(tr("염분 (PSU)"), fontsize=8, color=t.ink)
        ax.set_ylabel(tr("수온 (°C)"), fontsize=8, color=t.ink)
        self._legend(ax, len(usable) + 1)
        points = [(float(a), float(b), float(c), s["name"]) for s in usable for a, b, c in zip(s["salts"], s["temps"], s["depths"])]
        width = max(s_high - s_low, 1e-6)
        height = max(t_high - t_low, 1e-6)

        def hover(event):
            best = min(points, key=lambda p: ((p[0] - event.xdata) / width) ** 2 + ((p[1] - event.ydata) / height) ** 2)
            return (
                f"{best[3]}, {round(best[2])} m\nT {num(best[1], 2)} °C   S {num(best[0], 2)} PSU\n"
                f"σt {num(float(density_surface(best[0], best[1])) - 1000.0, 2)}"
            )

        self._hover = hover
        self._set_table(
            [tr("자료"), tr("수심 m"), tr("수온 °C"), tr("염분 PSU")],
            [[p[3], f"{round(p[2])}", num(p[1], 3), num(p[0], 3)] for p in points],
        )
        self.canvas.draw_idle()

    # ---- 마우스 ----
    def _on_move(self, event) -> None:
        if not self._hover or event.inaxes is None or event.xdata is None or event.ydata is None:
            return
        if self.toolbar.mode:  # 확대·이동 중에는 값을 띄우지 않습니다
            return
        text = self._hover(event)
        if text:
            QToolTip.showText(QCursor.pos(), text, self.canvas)
            self.canvas.draw_idle()

    def _on_leave(self, event) -> None:
        QToolTip.hideText()
        if self._crosshair is not None:
            self._crosshair.set_visible(False)
            self.canvas.draw_idle()
