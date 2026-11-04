"""패키지 메타데이터와 동봉 문서가 서로 맞는지 확인합니다."""

from pathlib import Path

import antarctic_monitor
from antarctic_monitor import help_text
from antarctic_monitor.i18n import set_language

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "antarctic_monitor" / "data"


def test_bundled_license_matches_repository_license():
    assert (DATA / "LICENSE.txt").read_text(encoding="utf-8") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert (DATA / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8") == (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")


def test_copyright_holders_everywhere():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    authors_md = (ROOT / "AUTHORS.md").read_text(encoding="utf-8")
    assert [a["name"] for a in antarctic_monitor.AUTHORS] == ["Jongsu Lim", "Suyeon Park"]
    assert "Copyright (c) 2026 Jongsu Lim <imjongsu1102@gmail.com> and Suyeon Park <dbsnt110@inu.ac.kr>" in license_text
    for author in antarctic_monitor.AUTHORS:
        assert author["email"] in pyproject and author["email"] in authors_md
        assert author["name"] in authors_md and author["name_ko"] in authors_md
        for language, html in (("ko", help_text.HELP_KO), ("en", help_text.HELP_EN)):
            assert author["name"] in html and author["email"] in html, (author["name"], language)
    assert "0009-0000-3395-1484" in authors_md and "0009-0000-3395-1484" in help_text.HELP_EN
    assert "HMOL" in help_text.HELP_EN and "CELLMATE" in help_text.HELP_EN
    assert "Incheon National University" in help_text.HELP_EN and "인천대학교" in help_text.HELP_KO
    lowercase_name = "j" + "ongsu Lim"  # 이름 표기는 Jongsu Lim으로 통일 (소문자 표기가 남지 않게)
    for name in ("README.md", "README.ko.md", "LICENSE", "AUTHORS.md", "pyproject.toml"):
        assert lowercase_name not in (ROOT / name).read_text(encoding="utf-8"), name


def test_help_switches_language():
    set_language("ko")
    assert "사용 설명서" in help_text.help_html()
    set_language("en")
    assert "user guide" in help_text.help_html().lower()
    set_language("ko")


def test_version_consistent():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{antarctic_monitor.__version__}"' in text
    assert antarctic_monitor.__version__ in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
