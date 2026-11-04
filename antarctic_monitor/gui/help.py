"""도움말 창: 사용 설명서, 라이선스, 제3자 고지."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QTextBrowser, QVBoxLayout

from ..help_text import help_html
from ..i18n import tr

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _read(name: str) -> str:
    path = DATA_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else f"{name} not found"


class HelpDialog(QDialog):
    TAB_GUIDE, TAB_LICENSE, TAB_NOTICES = range(3)

    def __init__(self, parent=None, tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle(tr("도움말"))
        self.resize(860, 680)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        guide = QTextBrowser()
        guide.setOpenExternalLinks(True)
        guide.setHtml(help_html())
        tabs.addTab(guide, tr("사용 설명서"))
        license_view = QTextBrowser()
        license_view.setPlainText(_read("LICENSE.txt"))
        tabs.addTab(license_view, tr("라이선스"))
        notices = QTextBrowser()
        notices.setOpenExternalLinks(True)
        notices.setMarkdown(_read("THIRD_PARTY_NOTICES.md"))
        tabs.addTab(notices, tr("제3자 고지"))
        tabs.setCurrentIndex(tab)
        layout.addWidget(tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
