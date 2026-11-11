"""패키지 메타데이터와 동봉 문서가 서로 맞는지 확인합니다."""

import os
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
    lowercase_name = "j" + "ongsu Lim"
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
    assert f"version: {antarctic_monitor.__version__}\n" in (ROOT / "CITATION.cff").read_text(encoding="utf-8")


def test_citation_metadata_lists_both_authors():
    import json

    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert cff.startswith("# Citation metadata") and "cff-version: 1.2.0" in cff
    for author in antarctic_monitor.AUTHORS:
        family, given = author["name"].split()[-1], author["name"].split()[0]
        assert f"family-names: {family}" in cff and f"given-names: {given}" in cff
        assert author["email"] in cff
    assert "0009-0000-3395-1484" in cff and "date-released: " in cff and "license: MIT" in cff
    concept_doi = antarctic_monitor.__concept_doi__
    assert concept_doi == "10.5281/zenodo.23937852"
    assert f"doi: {concept_doi}\n" in cff and f"value: {concept_doi}\n" in cff
    assert "value: 10.5281/zenodo.23937853\n" in cff and "value: 10.5281/zenodo.23945830\n" in cff
    assert "value: 10.5281/zenodo.23967499\n" in cff
    assert "value: 10.5281/zenodo.23981834\n" in cff
    assert "value: 10.5281/zenodo.24054813\n" in cff
    assert "value: 10.5281/zenodo.24096560\n" in cff
    assert "value: 10.5281/zenodo.24106903\n" in cff
    assert "value: 10.5281/zenodo.24123936\n" in cff
    assert "value: 10.5281/zenodo.24131554\n" in cff
    for name in ("README.md", "README.ko.md", "AUTHORS.md", "CHANGELOG.md"):
        assert concept_doi in (ROOT / name).read_text(encoding="utf-8"), name
    for html in (help_text.HELP_KO, help_text.HELP_EN):
        assert concept_doi in html

    zenodo = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in zenodo["creators"]] == ["Lim, Jongsu", "Park, Suyeon"]
    assert zenodo["creators"][0]["orcid"] == "0009-0000-3395-1484"
    assert all("Incheon National University" in c["affiliation"] for c in zenodo["creators"])
    assert zenodo["upload_type"] == "software" and zenodo["license"].lower() == "mit"
    for name in ("CITATION.cff", ".zenodo.json"):
        assert "Academy-ro" not in (ROOT / name).read_text(encoding="utf-8"), name


def test_frozen_build_keeps_the_matplotlib_cache(tmp_path, monkeypatch):
    from antarctic_monitor.config import use_persistent_matplotlib_cache

    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    directory = use_persistent_matplotlib_cache(tmp_path)
    assert directory == tmp_path / "matplotlib" and directory.is_dir()
    assert os.environ["MPLCONFIGDIR"] == str(directory)
