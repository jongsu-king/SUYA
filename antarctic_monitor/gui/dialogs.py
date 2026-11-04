"""언어 선택, 설정, 데이터 출처, 프로그램 정보 대화상자."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)

from .. import AUTHORS, __concept_doi__, __doi__, __email__, __url__, __version__
from ..catalog import KIND_LABEL, NOT_INCLUDED, ON_DEMAND_SOURCES, SOURCES
from ..config import Settings
from ..i18n import get_language, tr
from .help import HelpDialog
from .panels import DataTable


class LanguageDialog(QDialog):
    """첫 실행 때 언어를 고릅니다. 두 언어로 함께 적습니다."""

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("언어 / Language")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("언어를 선택하세요\nSelect a language"))
        self.combo = QComboBox()
        self.combo.addItem("한국어", "ko")
        self.combo.addItem("English", "en")
        self.combo.setCurrentIndex(max(0, self.combo.findData(current)))
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def language(self) -> str:
        return self.combo.currentData()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("설정"))
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.key = QLineEdit(settings.windy_api_key or "")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.tier = QComboBox()
        self.tier.addItem(tr("testing (무료, 변형된 값)"), "testing")
        self.tier.addItem(tr("professional (유료)"), "professional")
        self.tier.setCurrentIndex(max(0, self.tier.findData(settings.windy_key_tier)))
        self.excel_dir = QLineEdit(str(settings.excel_dir))
        browse = QPushButton(tr("찾아보기…"))
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.excel_dir, 1)
        folder_row.addWidget(browse)
        form.addRow(tr("Windy API 키"), self.key)
        form.addRow(tr("Windy 키 종류"), self.tier)
        form.addRow(tr("엑셀 저장 폴더"), folder_row)
        form.addRow(tr("데이터베이스"), QLabel(str(settings.db_path)))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("엑셀 저장 폴더"), self.excel_dir.text())
        if folder:
            self.excel_dir.setText(folder)

    def values(self) -> dict[str, str]:
        return {
            "WINDY_API_KEY": self.key.text().strip(),
            "WINDY_KEY_TIER": self.tier.currentData(),
            "MONITOR_EXCEL_DIR": str(Path(self.excel_dir.text().strip())),
        }


class SourcesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("데이터 출처"))
        self.resize(1040, 560)
        layout = QVBoxLayout(self)
        rows = [dict(s) for s in SOURCES] + [
            dict(s, cadence="지점 조회 시", relation="지점을 고를 때만 호출") for s in ON_DEMAND_SOURCES
        ]
        table = DataTable([tr("자료"), tr("제공처"), tr("종류"), tr("항목"), tr("갱신"), tr("nullschool·Windy와의 관계")])
        table.setRowCount(len(rows))
        for index, source in enumerate(rows):
            link = QLabel(f'<a href="{source["url"]}">{tr(source["name"])}</a>')
            link.setOpenExternalLinks(True)
            link.setContentsMargins(4, 0, 8, 0)
            table.setCellWidget(index, 0, link)
            table.put(index, 1, source["provider"])
            table.put(index, 2, tr(KIND_LABEL[source["kind"]]))
            table.put(index, 3, tr(source["measures"]))
            table.put(index, 4, tr(source["cadence"]))
            table.put(index, 5, tr(source["relation"]))
        table.resizeColumnsToContents()
        layout.addWidget(table, 1)
        layout.addWidget(QLabel(tr("수집하지 않는 자료")))
        for item in NOT_INCLUDED:
            label = QLabel(f"{tr(item['name'])}: {tr(item['reason'])}")
            label.setWordWrap(True)
            layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("프로그램 정보"))
        layout = QVBoxLayout(self)
        korean = get_language() == "ko"
        people = []
        for author in AUTHORS:
            name = f"{author['name_ko']} ({author['name']})" if korean else author["name"]
            affiliation = author["affiliation_ko"] if korean else author["affiliation"]
            line = f"&nbsp;&nbsp;{name} — <a href=\"mailto:{author['email']}\">{author['email']}</a>"
            if affiliation:
                line += f"<br>&nbsp;&nbsp;&nbsp;&nbsp;{affiliation}"
            extras = []
            if author.get("orcid"):
                extras.append(f"ORCID <a href=\"https://orcid.org/{author['orcid']}\">{author['orcid']}</a>")
            if author["url"]:
                extras.append(f"<a href=\"{author['url']}\">{author['url']}</a>")
            if extras:
                line += "<br>&nbsp;&nbsp;&nbsp;&nbsp;" + " · ".join(extras)
            people.append(line)
        text = QLabel(
            f"<b>SUYA</b> {__version__} — {tr('남극해 수온·염분 모니터')}<br><br>"
            f"{tr('저작권')}: Copyright © 2026 {' & '.join(a['name'] for a in AUTHORS)}<br>"
            + "<br>".join(people) + "<br>"
            f"{tr('문의')}: <a href=\"mailto:{__email__}\">{__email__}</a><br>"
            f"{tr('라이선스')}: {tr('MIT 라이선스')}<br>"
            f'<a href="{__url__}">{__url__}</a><br>'
            f'DOI: <a href="https://doi.org/{__doi__}">{__doi__}</a> · {tr("모든 버전")}: '
            f'<a href="https://doi.org/{__concept_doi__}">{__concept_doi__}</a><br>'
            f"{tr('인용')}: Lim, J. &amp; Park, S. (2026). <i>SUYA: Antarctic ocean temperature, salinity and air "
            f"temperature monitor</i> ({__version__}). Zenodo. https://doi.org/{__doi__}<br><br>"
            f"{tr('자료 출처')}: NOAA (GFS, OISST, METAR, WOA23), NASA JPL (MUR, SMAP), ESA (SMOS), "
            "US Navy / HYCOM.org, Argo Program (Ifremer), GOSUD, ECMWF ERA5, Open-Meteo (CC BY 4.0), "
            "Natural Earth, cmocean."
        )
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setOpenExternalLinks(True)
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        license_button = buttons.addButton(tr("라이선스…"), QDialogButtonBox.ButtonRole.ActionRole)
        license_button.clicked.connect(lambda: HelpDialog(self, HelpDialog.TAB_LICENSE).exec())
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
