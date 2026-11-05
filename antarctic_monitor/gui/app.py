"""메인 창. 운영체제 기본 위젯 모양을 그대로 쓰고, 수집 엔진의 이벤트를 받아 화면을 계속 갱신합니다."""

from __future__ import annotations

import dataclasses
import re
import sys
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSlider, QSplitter, QStyle, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__, exporter, pointquery, queries, updates
from ..catalog import KIND_LABEL, LAYERS, OUTPUT_JOBS, SOURCES
from ..collectors import JOBS
from ..config import Settings, load_settings, save_user_settings
from ..db import iso, utcnow
from ..geo import parse_location_url, validate
from ..i18n import LANGUAGES, get_language, render, saved_language, set_language, tr
from ..instance import InstanceLock
from ..locations import LOCATIONS, location_label
from .backend import Backend
from .charts import Chart
from .dialogs import AboutDialog, LanguageDialog, SettingsDialog, SourcesDialog
from .help import HelpDialog
from .format import age, clock_time, coord_text, countdown, interval_text, num, percent, short_time, status_text
from .panels import AirPanel, DataTable, ProfilePanel, SeriesPanel, WaterPanel
from .polarmap import ColorBar, PolarMapWidget
from .scales import build_scale
from .theme import Theme, current_theme, series_color

DETAIL_TABS = ("water", "profile", "air", "series")
GRID_SOURCES = {
    "oisst": {"oisst_sst", "oisst_anom", "oisst_ice"},
    "smos": {"smos_sss"},
    "smap": {"smap_sss"},
    "hycom_grid": {"hycom_temp", "hycom_salt"},
    "gfs_grid": {"gfs_t2m"},
}
SECTOR_COLUMNS = (
    ("oisst_sst", "SST °C", 2), ("oisst_anom", "SST 편차 °C", 2), ("hycom_salt_0", "표층 염분", 2),
    ("hycom_temp_500", "500 m 수온 °C", 2), ("hycom_salt_500", "500 m 염분", 2), ("oisst_ice", "해빙 농도", None),
    ("gfs_t2m", "기온 °C", 1),
)
SUMMARY_ROWS = (
    ("oisst_sst", "표층 수온", "°C", 2), ("oisst_anom", "수온 편차", "°C", 2), ("hycom_salt_0", "표층 염분", "PSU", 2),
    ("hycom_salt_500", "500 m 염분", "PSU", 2), ("oisst_ice", "해빙 농도", "", None), ("gfs_t2m", "기온", "°C", 1),
)
COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_location_text(text: str) -> tuple[float, float, str | None]:
    """'위도, 경도' 또는 nullschool·Windy 링크를 해석합니다. 링크로 요청을 보내지는 않습니다."""
    match = COORDINATES.match(text)
    if match:
        lat, lon = validate(float(match.group(1)), float(match.group(2)))
        return lat, lon, None
    point = parse_location_url(text)
    site = "nullschool" if point.site == "nullschool" else "Windy"
    return point.lat, point.lon, f"{site} ({'view' if point.kind == 'view' else 'link'})"


class MainWindow(QMainWindow):
    update_progress = Signal(int, int)

    def __init__(self, backend: Backend, settings: Settings):
        super().__init__()
        self.backend = backend
        self.settings_ = settings
        self.preferences = QSettings("SUYA", "monitor")
        self.theme: Theme = current_theme()
        self.layer_info: dict = {}
        self.layer_id = "oisst_sst"
        self.depth = 0
        self.selection: tuple[float, float, str | None] | None = None
        self.detail_tab = "water"
        self.detail_loaded: dict[str, tuple] = {}
        self.layer_request = 0
        self.layer_frames: list[dict] = []
        self.status_data: dict | None = None
        self.pending_sources: set[str] = set()
        self.overview_data: dict | None = None
        self.depth_stats: dict | None = None
        self.relaunch = False

        self.setWindowTitle(f"SUYA — {tr('남극해 수온·염분 모니터')}")
        self.resize(1440, 900)
        self.setMinimumSize(1000, 660)
        self._build_menu()
        self._build()
        self._restore_geometry()

        self.refresh_timer = QTimer(self, singleShot=True, interval=800)
        self.refresh_timer.timeout.connect(self._run_refresh)
        self.clock = QTimer(self, interval=1000)
        self.clock.timeout.connect(self._tick)
        self.clock.start()
        self.backend.event.connect(self.on_event)
        self.update_progress.connect(self._show_update_progress)
        self._deferred_update: str | None = None
        self._updating = False
        self.update_timer = QTimer(self, interval=24 * 3600 * 1000)
        self.update_timer.timeout.connect(lambda: self.check_updates(manual=False))
        if self.settings_.update_mode != "off":
            QTimer.singleShot(15_000, lambda: self.check_updates(manual=False))
            self.update_timer.start()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu(tr("파일"))
        file_menu.addAction(tr("설정…"), self.open_settings, QKeySequence.StandardKey.Preferences)
        file_menu.addSeparator()
        file_menu.addAction(tr("엑셀 DB 지금 저장"), self.save_excel_now)
        file_menu.addAction(tr("엑셀 폴더 열기"), lambda: self._open_folder(self.backend.ctx.settings.excel_dir))
        file_menu.addAction(tr("데이터 폴더 열기"), lambda: self._open_folder(self.backend.store.path.parent))
        export_menu = file_menu.addMenu(tr("CSV 내보내기"))
        export_menu.addAction(tr("측정값…"), self.export_measurements)
        export_menu.addAction(tr("Argo 전 층…"), self.export_argo)
        export_menu.addAction(tr("현재 레이어…"), self.export_layer)
        file_menu.addSeparator()
        file_menu.addAction(tr("종료"), self.close, QKeySequence.StandardKey.Quit)

        view_menu = bar.addMenu(tr("보기"))
        language_menu = view_menu.addMenu(tr("언어"))
        group = QActionGroup(self)
        for code, label in zip(LANGUAGES, ("한국어", "English")):
            action = QAction(label, self, checkable=True, checked=code == get_language())
            action.triggered.connect(lambda _checked, c=code: self.change_language(c))
            group.addAction(action)
            language_menu.addAction(action)

        collect_menu = bar.addMenu(tr("수집"))
        collect_menu.addAction(tr("지금 전체 수집"), self.collect_now, QKeySequence("F5"))
        source_menu = collect_menu.addMenu(tr("소스별 수집"))
        for source in SOURCES + OUTPUT_JOBS:
            source_menu.addAction(tr(source["name"]), lambda _checked=False, s=source["id"]: self.collect_source(s))

        help_menu = bar.addMenu(tr("도움말"))
        help_menu.addAction(tr("사용 설명서…"), lambda: HelpDialog(self, HelpDialog.TAB_GUIDE).exec(), QKeySequence.StandardKey.HelpContents)
        help_menu.addAction(tr("데이터 출처…"), lambda: SourcesDialog(self).exec())
        help_menu.addSeparator()
        help_menu.addAction(tr("라이선스…"), lambda: HelpDialog(self, HelpDialog.TAB_LICENSE).exec())
        help_menu.addAction(tr("제3자 고지…"), lambda: HelpDialog(self, HelpDialog.TAB_NOTICES).exec())
        help_menu.addSeparator()
        help_menu.addAction(tr("업데이트 확인…"), self.check_updates)
        help_menu.addAction(tr("프로그램 정보…"), lambda: AboutDialog(self).exec())

    def check_updates(self, manual: bool = True) -> None:
        if self._updating:
            return
        if manual:
            self.statusBar().showMessage(tr("업데이트 확인 중…"))

        def done(result, error):
            if error or not result:
                if manual:
                    self.statusBar().showMessage(tr("업데이트 확인 실패: {error}", error=render(str(error))), 8000)
                return
            if not result["newer"]:
                if manual:
                    self.statusBar().showMessage(tr("최신 버전입니다 ({version})", version=__version__), 6000)
                return
            if not manual and self._deferred_update == result["version"]:
                return
            self.statusBar().clearMessage()
            self._offer_update(result, automatic=not manual and self.settings_.update_mode == "auto")

        self.backend.call(lambda: updates.latest_release(self.backend.ctx.fetcher), done)

    def _offer_update(self, release: dict, automatic: bool) -> None:
        version = release["version"]
        if not (updates.can_self_update() and release.get("asset")):
            answer = QMessageBox.question(
                self, tr("업데이트 확인"),
                tr("이 설치본은 스스로 업데이트할 수 없습니다. 새 버전 {version}의 내려받기 페이지를 열까요?", version=version),
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(release["url"]))
            else:
                self._deferred_update = version
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("업데이트 확인"))
        box.setIcon(QMessageBox.Icon.Information)
        install = box.addButton(tr("지금 설치"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("나중에"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(install)
        if automatic:
            remaining = {"seconds": 20}
            countdown = QTimer(box, interval=1000)

            def tick() -> None:
                remaining["seconds"] -= 1
                if remaining["seconds"] <= 0:
                    countdown.stop()
                    install.click()
                else:
                    box.setText(tr("새 버전 {version}을 {seconds}초 뒤에 설치하고 다시 시작합니다.", version=version, seconds=remaining["seconds"]))

            countdown.timeout.connect(tick)
            box.setText(tr("새 버전 {version}을 {seconds}초 뒤에 설치하고 다시 시작합니다.", version=version, seconds=remaining["seconds"]))
            countdown.start()
        else:
            box.setText(tr("새 버전 {version}이 있습니다. 지금 내려받아 설치하고 다시 시작할까요?", version=version))
        box.exec()
        if box.clickedButton() is install:
            self._start_update(release)
        else:
            self._deferred_update = version

    def _start_update(self, release: dict) -> None:
        self._updating = True
        self.statusBar().showMessage(tr("업데이트 내려받는 중… {percent}%", percent=0))

        def progress(received: int, total: int) -> None:
            self.update_progress.emit(received, total)

        def downloaded(path, error):
            if error:
                self._updating = False
                self.statusBar().showMessage(tr("업데이트 실패: {error}", error=render(str(error))), 10000)
                return
            self.statusBar().showMessage(tr("업데이트 설치 중…"))
            self.backend.call_sync(updates.install, path, callback=installed)

        def installed(_result, error):
            if error:
                self._updating = False
                self.statusBar().showMessage(tr("업데이트 실패: {error}", error=render(str(error))), 10000)
                return
            self.relaunch = False
            self._updating = False
            self.close()

        fetcher = self.backend.ctx.fetcher
        self.backend.call(lambda: updates.download(fetcher, release, progress=progress), downloaded)

    def _show_update_progress(self, received: int, total: int) -> None:
        percent = int(received * 100 / total) if total else 0
        self.statusBar().showMessage(tr("업데이트 내려받는 중… {percent}%", percent=percent))

    def _build(self) -> None:
        self.cursor_label = QLabel()
        self.live_label = QLabel()
        self.statusBar().addWidget(self.cursor_label, 1)
        self.statusBar().addPermanentWidget(self.live_label)
        self.pages = QTabWidget()
        self.pages.addTab(self._build_map_page(), tr("지도"))
        self.pages.addTab(self._build_stats_page(), tr("해역 통계"))
        self.pages.addTab(self._build_points_page(), tr("지점 목록"))
        self.pages.addTab(self._build_status_page(), tr("수집 상태"))
        self.setCentralWidget(self.pages)

    def _build_map_page(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(tr("레이어")))
        self.layer_combo = QComboBox()
        for layer in LAYERS:
            self.layer_combo.addItem(tr(layer["label"]), layer["id"])
        self.layer_combo.currentIndexChanged.connect(self._on_layer_changed)
        controls.addWidget(self.layer_combo)
        self.depth_label = QLabel(tr("수심"))
        self.depth_combo = QComboBox()
        self.depth_combo.currentIndexChanged.connect(self._on_depth_changed)
        controls.addWidget(self.depth_label)
        controls.addWidget(self.depth_combo)
        controls.addStretch(1)
        self.argo_check = QCheckBox("Argo", checked=True)
        self.argo_check.toggled.connect(lambda on: self.map.set_visibility(argo=on))
        self.location_check = QCheckBox(tr("기지·해역"), checked=True)
        self.location_check.toggled.connect(lambda on: self.map.set_visibility(locations=on))
        controls.addWidget(self.argo_check)
        controls.addWidget(self.location_check)
        left_layout.addLayout(controls)
        self.map = PolarMapWidget()
        self.map.set_theme(self.theme)
        self.map.set_markers(locations=[loc.as_dict() for loc in LOCATIONS])
        self.map.pointSelected.connect(self.select_point)
        self.map.cursorText.connect(self.cursor_label.setText)
        left_layout.addWidget(self.map, 1)
        self.colorbar = ColorBar()
        left_layout.addWidget(self.colorbar)
        self.time_row = QWidget()
        time_layout = QHBoxLayout(self.time_row)
        time_layout.setContentsMargins(0, 0, 0, 0)
        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.setToolTip(tr("저장된 시각을 차례로 재생"))
        self.play_button.clicked.connect(self._toggle_play)
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setToolTip(tr("저장된 시각 고르기"))
        self.time_slider.valueChanged.connect(self._on_time_changed)
        time_layout.addWidget(self.play_button)
        time_layout.addWidget(self.time_slider, 1)
        self.time_row.setVisible(False)
        left_layout.addWidget(self.time_row)
        self.play_timer = QTimer(self, interval=900)
        self.play_timer.timeout.connect(self._next_frame)
        self.layer_meta = QLabel()
        self.layer_meta.setWordWrap(True)
        left_layout.addWidget(self.layer_meta)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)
        locator_row = QHBoxLayout()
        locator_row.addWidget(QLabel(tr("위치")))
        self.locator = QLineEdit()
        self.locator.setPlaceholderText(tr("위도, 경도 또는 nullschool·Windy 링크"))
        self.locator.returnPressed.connect(self.submit_locator)
        go = QPushButton("OK")
        go.clicked.connect(self.submit_locator)
        locator_row.addWidget(self.locator, 1)
        locator_row.addWidget(go)
        right_layout.addLayout(locator_row)
        self.point_title = QLabel(tr("선택한 지점"))
        self.point_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_layout.addWidget(self.point_title)
        self.ocean_note = QLabel()
        self.ocean_note.setWordWrap(True)
        self.ocean_note.setVisible(False)
        right_layout.addWidget(self.ocean_note)
        self.panels = {"water": WaterPanel(), "profile": ProfilePanel(), "air": AirPanel(), "series": SeriesPanel()}
        for panel in self.panels.values():
            panel.set_theme(self.theme)
        self.detail_tabs = QTabWidget()
        for key, label in zip(DETAIL_TABS, (tr("표층"), tr("수직 프로파일"), tr("기온"), tr("시계열"))):
            self.detail_tabs.addTab(self.panels[key], label)
        self.detail_tabs.currentChanged.connect(self._on_detail_tab)
        right_layout.addWidget(self.detail_tabs, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([700, 720])
        self._sync_depth_control()
        return splitter

    def _build_stats_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        summary = QGroupBox(tr("남극해 전체 (60°S 이남)"))
        form = QFormLayout(summary)
        form.setHorizontalSpacing(16)
        self.summary_values: dict[str, QLabel] = {}
        for key, label, _, _ in SUMMARY_ROWS:
            value = QLabel("–")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(tr(label), value)
            self.summary_values[key] = value
        self.summary_argo = QLabel("–")
        form.addRow("Argo", self.summary_argo)
        layout.addWidget(summary)
        self.sector_table = DataTable([tr("해역"), *[tr(c[1]) for c in SECTOR_COLUMNS]], numeric=set(range(1, len(SECTOR_COLUMNS) + 1)))
        self.sector_table.setMaximumHeight(190)
        layout.addWidget(self.sector_table)
        self.depth_note = QLabel()
        self.depth_note.setWordWrap(True)
        layout.addWidget(self.depth_note)
        pair = QHBoxLayout()
        self.region_temp = Chart(height=280)
        self.region_salt = Chart(height=280)
        for chart in (self.region_temp, self.region_salt):
            chart.set_theme(self.theme)
            pair.addWidget(chart, 1)
        layout.addLayout(pair, 1)
        return page

    def _build_points_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.location_table = DataTable(
            [tr("지점"), tr("좌표"), tr("기온 °C"), tr("체감 °C"), tr("표층 수온 °C"), tr("표층 염분 PSU"), tr("해빙"), tr("기온 갱신")],
            numeric={2, 3, 4, 5, 6},
        )
        self.location_table.cellDoubleClicked.connect(self._on_location_clicked)
        self.location_rows: dict[int, dict] = {}
        layout.addWidget(QLabel(tr("기지·해역")))
        layout.addWidget(self.location_table, 3)
        layout.addWidget(QLabel(tr("기지 관측")))
        self.metar_table = DataTable([tr("ICAO"), tr("기지명"), tr("좌표"), tr("기온 °C"), tr("자료 시각"), tr("경과")], numeric={3})
        layout.addWidget(self.metar_table, 2)
        return page

    def _build_status_page(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.status_note = QLabel()
        left_layout.addWidget(self.status_note)
        self.status_table = DataTable(
            [tr("소스"), tr("상태"), tr("주기"), tr("자료 시각"), tr("경과"), tr("최종 수집"), tr("다음 수집"), tr("행"), tr("메시지")],
            numeric={7},
        )
        left_layout.addWidget(self.status_table, 1)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel(tr("수집 로그")))
        self.feed_list = QListWidget()
        self.feed_list.setWordWrap(True)
        right_layout.addWidget(self.feed_list, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _restore_geometry(self) -> None:
        geometry = self.preferences.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def start(self) -> None:
        self._refresh_layers(then_render=True)
        self.refresh_overview()
        self.refresh_status()
        self.refresh_locations()
        self.refresh_argo_markers()
        start = next(loc for loc in LOCATIONS if loc.id == "link_windy")
        self.select_point(start.lat, start.lon, location_label(start))

    def _refresh_layers(self, then_render: bool = False) -> None:
        def done(info, error):
            if error:
                return
            self.layer_info = info
            if then_render:
                self.render_layer()

        self.backend.call_sync(self.backend.store.latest_grid_info, callback=done)

    def refresh_overview(self) -> None:
        def done(result, error):
            if error:
                return
            self.overview_data = result
            self._render_summary(result)
            self._render_sectors(result)
            self._render_metar(result)
            self.refresh_depth_stats()

        self.backend.call_sync(queries.overview, self.backend.store, callback=done)

    def refresh_depth_stats(self) -> None:
        def done(result, error):
            if error:
                return
            self.depth_stats = result
            self._render_region_depth()

        self.backend.call_sync(pointquery.argo_depth_stats, self.backend.ctx, callback=done)

    def refresh_status(self) -> None:
        backend = self.backend

        def build():
            return queries.status_snapshot(backend.ctx, backend.running, backend.collecting)

        def done(result, error):
            if error:
                return
            self.status_data = result
            self._render_status()
            self._render_live_status()

        backend.call_sync(build, callback=done)

    def refresh_locations(self) -> None:
        def done(rows, error):
            if not error:
                self._render_locations(rows)

        self.backend.call_sync(queries.locations_latest, self.backend.store, callback=done)

    def refresh_argo_markers(self) -> None:
        store = self.backend.store

        def build():
            return store.argo_list(since=iso(utcnow() - timedelta(days=30)), lat_max=-55.0)

        def done(rows, error):
            if not error:
                self.map.set_markers(argo=rows)

        self.backend.call_sync(build, callback=done)

    def on_event(self, event: dict) -> None:
        if event.get("type") != "job":
            return
        self._push_feed(event)
        if event["state"] == "done":
            self.pending_sources.add(event["source"])
            self.refresh_timer.start()
        if self.status_data is not None:
            running = set(self.status_data["running"])
            if event["state"] == "running":
                running.add(event["source"])
            else:
                running.discard(event["source"])
            self.status_data["running"] = sorted(running)
            self._render_status()
            self._render_live_status()

    def _run_refresh(self) -> None:
        sources, self.pending_sources = self.pending_sources, set()
        self.refresh_status()
        self.refresh_overview()
        self.refresh_locations()
        if sources & GRID_SOURCES.keys():
            changed = any(self.layer_id in GRID_SOURCES.get(s, ()) for s in sources)
            self._refresh_layers(then_render=changed or bool(self.map.empty_text))
        if "argo" in sources:
            self.refresh_argo_markers()
        if self.detail_tab == "air" and sources & {"metar", "openmeteo_current"}:
            self.load_detail("air", silent=True)

    def _tick(self) -> None:
        if not self.status_data:
            return
        running = set(self.status_data["running"])
        for row, source in enumerate(self.status_data["sources"]):
            item = self.status_table.item(row, 6)
            if item and source["id"] not in running:
                item.setText(countdown(source.get("next_run")))

    def collect_now(self) -> None:
        names = self.backend.trigger()
        self.statusBar().showMessage(tr("수집 꺼짐") if not names else f"{tr('지금 전체 수집')}: {len(names)}", 4000)

    def collect_source(self, source: str) -> None:
        names = self.backend.trigger([source])
        self.statusBar().showMessage(tr("수집 꺼짐") if not names else f"{tr('수집')}: {source}", 4000)

    def save_excel_now(self) -> None:
        self.backend.store.kv_set("excel:stamp", "")
        self.collect_source("excel")

    def _open_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.backend.ctx.settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        save_user_settings(values)
        current = self.backend.ctx.settings
        self.backend.ctx.settings = dataclasses.replace(
            current,
            windy_api_key=values["WINDY_API_KEY"] or None,
            windy_key_tier=values["WINDY_KEY_TIER"],
            excel_dir=Path(values["MONITOR_EXCEL_DIR"]),
            update_mode=values["MONITOR_UPDATE_MODE"],
        )
        self.settings_ = self.backend.ctx.settings
        if self.settings_.update_mode == "off":
            self.update_timer.stop()
        elif not self.update_timer.isActive():
            self.update_timer.start()
        self.statusBar().showMessage(tr("설정"), 3000)

    def change_language(self, code: str) -> None:
        if code == get_language():
            return
        save_user_settings({"MONITOR_LANG": code})
        set_language(code)
        self.relaunch = True
        self.close()

    def _layer_def(self) -> dict:
        return next(layer for layer in LAYERS if layer["id"] == self.layer_id)

    def grid_id(self) -> str:
        layer = self._layer_def()
        return f"{layer['id']}_{self.depth}" if layer.get("depths") else layer["id"]

    def _sync_depth_control(self) -> None:
        layer = self._layer_def()
        has_depths = bool(layer.get("depths"))
        self.depth_label.setVisible(has_depths)
        self.depth_combo.setVisible(has_depths)
        if has_depths:
            self.depth_combo.blockSignals(True)
            self.depth_combo.clear()
            for depth in layer["depths"]:
                self.depth_combo.addItem(f"{depth} m", depth)
            self.depth_combo.setCurrentIndex(max(0, self.depth_combo.findData(self.depth)))
            self.depth_combo.blockSignals(False)

    def _on_layer_changed(self) -> None:
        self.layer_id = self.layer_combo.currentData()
        self._sync_depth_control()
        self.render_layer()

    def _on_depth_changed(self) -> None:
        depth = self.depth_combo.currentData()
        if depth is not None:
            self.depth = depth
            self.render_layer()

    def _stop_play(self) -> None:
        self.play_timer.stop()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))

    def _toggle_play(self) -> None:
        if self.play_timer.isActive():
            self._stop_play()
            return
        if self.time_slider.value() >= self.time_slider.maximum():
            self.time_slider.setValue(0)
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.play_timer.start()

    def _next_frame(self) -> None:
        if self.time_slider.value() >= self.time_slider.maximum():
            self._stop_play()
        else:
            self.time_slider.setValue(self.time_slider.value() + 1)

    def _on_time_changed(self, index: int) -> None:
        if 0 <= index < len(self.layer_frames):
            self.render_layer(self.layer_frames[index])

    def _load_frames(self, grid_id: str) -> None:
        """이 레이어에 저장된 시각을 슬라이더에 올립니다. 시각이 둘 이상일 때만 보입니다."""

        def done(frames, error):
            if error or grid_id != self.grid_id():
                return
            self.layer_frames = frames or []
            self.time_slider.blockSignals(True)
            self.time_slider.setRange(0, max(len(self.layer_frames) - 1, 0))
            self.time_slider.setValue(self.time_slider.maximum())
            self.time_slider.blockSignals(False)
            self.time_row.setVisible(len(self.layer_frames) > 1)

        self.backend.call_sync(self.backend.store.grid_history, grid_id, callback=done)

    def render_layer(self, frame: dict | None = None) -> None:
        """최신 격자를 그립니다. frame을 주면 그 저장 시각을 같은 색 범위로 그립니다."""
        layer = self._layer_def()
        grid_id = self.grid_id()
        info = self.layer_info.get(grid_id)
        if frame is None:
            self._stop_play()
            self.layer_frames = []
            self.time_row.setVisible(False)
        label = f"{tr(layer['label'])} {self.depth} m" if layer.get("depths") else tr(layer["label"])
        self.layer_request += 1
        token = self.layer_request
        if not info:
            self.map.set_layer(None, None, label, tr("이 레이어는 수집 대기 중"))
            self.colorbar.set_scale(None, self.theme)
            self.layer_meta.setText("")
            return
        if frame is None:
            self._load_frames(grid_id)
        shown = frame or info

        def done(grid, error):
            if token != self.layer_request:
                return
            if error or grid is None:
                self.layer_meta.setText(tr("오류: {message}", message=str(error)))
                return
            unit = "" if grid.unit == "fraction" else grid.unit
            scale = build_scale(layer["scale"], info["stats"], unit)
            self.map.set_layer(grid, scale, label)
            self.colorbar.set_scale(scale, self.theme)
            parts = [
                tr(KIND_LABEL[layer["kind"]]),
                f"{short_time(shown['valid_time'])} ({age(shown['valid_time'])})",
                tr("유효 {pct}%", pct=round((shown["stats"].get("coverage") or 0) * 100)),
            ]
            rejected = grid.meta.get("rejected_out_of_range")
            if rejected:
                parts.append(tr("범위 밖 {n}개 제외", n=rejected))
            self.layer_meta.setText(" · ".join(parts))

        self.backend.call_sync(self.backend.store.load_grid, grid_id, shown["valid_time"], callback=done)

    def submit_locator(self) -> None:
        text = self.locator.text().strip()
        if not text:
            return
        try:
            lat, lon, name = parse_location_text(text)
        except ValueError as exc:
            QMessageBox.warning(self, tr("위치"), render(str(exc)))
            return
        self.select_point(lat, lon, name)

    def select_point(self, lat: float, lon: float, name: str | None = None) -> None:
        self.selection = (lat, lon, name)
        self.detail_loaded = {}
        self.map.set_selection(lat, lon)
        self.point_title.setText(f"{name or tr('선택한 지점')}   {coord_text(lat, lon)}")
        self.ocean_note.setVisible(False)
        self.load_detail(self.detail_tab)

    def _on_detail_tab(self, index: int) -> None:
        self.detail_tab = DETAIL_TABS[index]
        if self.selection:
            self.load_detail(self.detail_tab)

    def load_detail(self, tab: str, silent: bool = False) -> None:
        if not self.selection:
            return
        lat, lon, _ = self.selection
        key = (round(lat, 3), round(lon, 3))
        if not silent and self.detail_loaded.get(tab) == key:
            return
        self.detail_loaded[tab] = key
        panel = self.panels[tab]
        if not silent:
            panel.set_loading(tr("HYCOM 응답 대기 중 (최대 약 2분)…") if tab == "profile" else tr("받는 중…"))

        def done(data, error):
            if self.detail_loaded.get(tab) != key:
                return
            if error:
                self.detail_loaded.pop(tab, None)
                panel.show_error(str(error))
                return
            panel.show_data(data)
            self._update_ocean_note(data.get("ocean"))

        self.backend.point(tab, lat, lon, done)

    def _update_ocean_note(self, ocean: dict | None) -> None:
        if not ocean:
            return
        if ocean.get("is_ocean") is False and ocean.get("distance_km") is not None:
            self.ocean_note.setText(tr(
                "육지/빙붕. 최근접 해양 격자 {coord} ({km} km) 값 표시",
                coord=coord_text(ocean["lat"], ocean["lon"]), km=round(ocean["distance_km"]),
            ))
            self.ocean_note.setVisible(True)
        elif ocean.get("is_ocean") is False:
            self.ocean_note.setText(tr("육지/빙붕. 주변에 해양 격자 없음"))
            self.ocean_note.setVisible(True)
        else:
            self.ocean_note.setVisible(False)

    def _on_location_clicked(self, row: int, _column: int) -> None:
        item = self.location_rows.get(row)
        if item:
            self.pages.setCurrentIndex(0)
            self.select_point(item["lat"], item["lon"], location_label(item))

    def _render_summary(self, overview: dict) -> None:
        stats, argo = overview["stats"], overview["argo"]
        for key, _, unit, digits in SUMMARY_ROWS:
            item = stats.get(key)
            if not item:
                continue
            text = percent(item["mean"]) if digits is None else f"{num(item['mean'], digits)} {unit}"
            self.summary_values[key].setText(f"{text}    ({short_time(item['valid_time'])})")
        self.summary_argo.setText(tr("Argo {profiles}개 프로파일, 최근 {days}일, 60°S 이남", profiles=argo["profiles"], days=30))

    def _render_sectors(self, overview: dict) -> None:
        table = self.sector_table
        table.setRowCount(len(overview["sectors"]))
        for row, sector in enumerate(overview["sectors"]):
            table.put(row, 0, tr(sector["name"]))
            for column, (key, _, digits) in enumerate(SECTOR_COLUMNS, start=1):
                value = sector.get(key)
                table.put(row, column, percent(value) if digits is None else num(value, digits))

    def _render_metar(self, overview: dict) -> None:
        table = self.metar_table
        rows = overview["metar"]
        table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            table.put(index, 0, item["icao"])
            table.put(index, 1, item.get("name") or "")
            table.put(index, 2, coord_text(item["lat"], item["lon"]))
            table.put(index, 3, num(item["value"], 1))
            table.put(index, 4, short_time(item["time"]))
            table.put(index, 5, age(item["time"]))

    def _render_region_depth(self) -> None:
        stats, overview = self.depth_stats, self.overview_data
        if not stats or not overview:
            return
        self.depth_note.setText(tr("Argo {profiles}개 프로파일, 최근 {days}일, 60°S 이남", profiles=stats["profiles"], days=stats["days"]))
        t = self.theme

        def argo_series(key: str) -> dict:
            rows = [b for b in stats["bins"] if b[key]["mean"] is not None]
            return {"name": "Argo", "color": series_color(t, "argo"), "depths": [b["mid_m"] for b in rows], "values": [b[key]["mean"] for b in rows]}

        def hycom_series(key: str) -> dict:
            rows = [r for r in overview["depth_means"][key] if r["mean"] is not None]
            return {"name": "HYCOM", "color": series_color(t, "hycom"), "marker": "o", "depths": [r["depth_m"] for r in rows], "values": [r["mean"] for r in rows]}

        self.region_temp.depth(tr("층별 평균") + " — " + tr("수온"), [argo_series("temp"), hycom_series("temp")], tr("수온 (°C)"), unit="°C")
        self.region_salt.depth(tr("층별 평균") + " — " + tr("염분"), [argo_series("salt"), hycom_series("salt")], tr("염분 (PSU)"), unit="PSU")

    def _render_locations(self, rows: list[dict]) -> None:
        table = self.location_table
        table.clearSpans()
        table.setRowCount(0)
        self.location_rows = {}
        for group, label in (("link", "입력한 링크"), ("station", "기지"), ("ocean", "해역")):
            table.group_row(tr(label))
            for row in rows:
                if row["group"] != group:
                    continue
                index = table.rowCount()
                table.insertRow(index)
                self.location_rows[index] = row
                table.put(index, 0, location_label(row))
                table.put(index, 1, coord_text(row["lat"], row["lon"]))
                table.put(index, 2, num(row["air_temperature"], 1))
                table.put(index, 3, num(row["apparent_temperature"], 1))
                table.put(index, 4, num(row["oisst_sst"], 2))
                table.put(index, 5, num(row["hycom_salt_0"], 2))
                table.put(index, 6, percent(row["oisst_ice"]))
                table.put(index, 7, age(row["air_time"]))

    def _render_status(self) -> None:
        data = self.status_data
        if not data:
            return
        table = self.status_table
        table.setRowCount(len(data["sources"]))
        running = set(data["running"])
        for row, source in enumerate(data["sources"]):
            is_running = source["id"] in running
            status = "running" if is_running else (source.get("last_status") or "pending")
            color = self.theme.error if status in ("error", "rate_limited") else None
            table.put(row, 0, tr(source["name"]))
            table.put(row, 1, status_text(status), color=color)
            table.put(row, 2, interval_text(source.get("interval_s")))
            table.put(row, 3, short_time(source.get("data_time")))
            table.put(row, 4, age(source.get("data_time")))
            table.put(row, 5, age(source.get("last_attempt")))
            table.put(row, 6, "…" if is_running else countdown(source.get("next_run")))
            rows = source.get("last_rows")
            table.put(row, 7, "–" if rows is None else f"{rows:,}")
            table.put(row, 8, render(source.get("last_message")))
        budget = data["openmeteo_budget"]
        rows_text = tr("측정값 {rows}행", rows=f"{data['measurements']:,}")
        self.status_note.setText(
            f"{rows_text} · Open-Meteo {budget['used']:,}/{budget['limit']:,} · {self.backend.store.path}"
        )

    def _render_live_status(self) -> None:
        data = self.status_data
        if not data:
            return
        if not data["collecting"]:
            self.live_label.setText(tr("수집 꺼짐"))
            return
        sources = data["sources"]
        busy = len(data["running"])
        failing = sum(1 for s in sources if s.get("last_status") in ("error", "rate_limited"))
        healthy = sum(1 for s in sources if s.get("last_status") in ("ok", "unchanged"))
        parts = [tr("수집 중 {n}", n=busy) if busy else tr("정상 {ok}/{total}", ok=healthy, total=len(sources))]
        if failing:
            parts.append(tr("오류 {n}", n=failing))
        excel = next((s for s in sources if s["id"] == "excel"), None)
        if excel and excel.get("last_success"):
            parts.append(tr("엑셀 {time}", time=clock_time(excel["last_success"])))
        self.live_label.setText("  |  ".join(parts))

    def _push_feed(self, event: dict) -> None:
        source = next((s for s in SOURCES + OUTPUT_JOBS if s["id"] == event["source"]), None)
        name = tr(source["name"]) if source else event["source"]
        status = "running" if event["state"] == "running" else event.get("status")
        text = f"{clock_time(event.get('at'))}  [{status_text(status)}]  {name}"
        if event.get("rows"):
            text += f"  {event['rows']:,}"
        message = render(event.get("message"))
        if message:
            text += f"\n    {message}"
        item = QListWidgetItem(text)
        if status in ("error", "rate_limited"):
            item.setForeground(QColor(self.theme.error))
        self.feed_list.insertItem(0, item)
        while self.feed_list.count() > 300:
            self.feed_list.takeItem(self.feed_list.count() - 1)

    def _save_path(self, default_name: str) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(self, tr("CSV로 저장"), default_name, "CSV (*.csv)")
        return Path(path) if path else None

    def _export(self, function, path: Path, *args) -> None:
        self.statusBar().showMessage(tr("저장 중…"))

        def done(count, error):
            if error:
                self.statusBar().showMessage(tr("저장 실패: {error}", error=render(str(error))), 8000)
            else:
                self.statusBar().showMessage(tr("{path}: {count}행 저장", path=path, count=f"{count:,}"), 8000)

        self.backend.call_sync(function, self.backend.store, *args, callback=done)

    def export_measurements(self) -> None:
        path = self._save_path("antarctic-measurements.csv")
        if path:
            self._export(exporter.export_measurements, path, path)

    def export_argo(self) -> None:
        path = self._save_path("antarctic-argo-profiles.csv")
        if path:
            self._export(exporter.export_argo, path, path)

    def export_layer(self) -> None:
        grid_id = self.grid_id()
        path = self._save_path(f"{grid_id}.csv")
        if path:
            self._export(exporter.export_grid, path, grid_id, path)

    def _confirm_close(self) -> bool:
        """업데이트 중에 창을 닫으면 내려받던 파일과 수집이 함께 멈추므로 먼저 묻습니다."""
        if not self._updating:
            return True
        answer = QMessageBox.question(
            self, tr("업데이트 확인"),
            tr("업데이트를 받는 중입니다. 지금 닫으면 업데이트가 취소되고 수집도 멈춥니다. 닫을까요?"),
        )
        return answer == QMessageBox.StandardButton.Yes

    def closeEvent(self, event) -> None:
        if not self._confirm_close():
            event.ignore()
            return
        self.preferences.setValue("geometry", self.saveGeometry())
        self.clock.stop()
        self.refresh_timer.stop()
        try:
            self.backend.event.disconnect(self.on_event)
        except (RuntimeError, TypeError):
            pass
        if not self.relaunch:
            self.backend.stop()
        super().closeEvent(event)


def run_gui(
    collect: bool = True, sources: list[str] | None = None, snapshot: str | None = None, snapshot_after: float = 8.0,
    forced_language: str | None = None,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SUYA")
    app.setOrganizationName("SUYA")
    if not forced_language and saved_language() is None and not snapshot:
        dialog = LanguageDialog(get_language())
        dialog.exec()
        set_language(dialog.language())
        save_user_settings({"MONITOR_LANG": dialog.language()})
    settings = load_settings()
    lock = InstanceLock(settings.db_path.parent)
    if not lock.acquire():
        QMessageBox.information(None, "SUYA", tr("SUYA가 이미 실행 중입니다. 창이 보이지 않으면 Dock이나 작업 표시줄을 확인하세요."))
        return 0
    updates.cleanup()
    backend = Backend(settings, collect=collect, sources=sources)
    backend.start()
    code = 0
    try:
        while True:
            window = MainWindow(backend, settings)
            window.show()
            window.start()
            if snapshot:
                def capture() -> None:
                    window.grab().save(snapshot)
                    window.close()

                QTimer.singleShot(int(snapshot_after * 1000), capture)
            code = app.exec()
            if not window.relaunch:
                break
    finally:
        lock.release()
    return code
