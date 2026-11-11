"""엑셀 저장이 실패하거나 중간에 멈춰도 조각 파일과 오류 창을 남기지 않는지 검증합니다."""

import argparse
import asyncio
import errno
import json
import os
import shutil
import sys
import time
import zipfile
from types import SimpleNamespace

import pytest
import xlsxwriter.workbook
from xlsxwriter.exceptions import FileCreateError

from antarctic_monitor import cli, excel
from antarctic_monitor.collectors.base import Context
from antarctic_monitor.config import Settings
from antarctic_monitor.db import Measurement, Store
from antarctic_monitor.http import FetchError
from antarctic_monitor.i18n import render, set_language

MAIN = "antarctic_db_2026-11.xlsx"
ARGO = "argo_levels_2026-11.xlsx"


@pytest.fixture(autouse=True)
def korean():
    set_language("ko")
    yield
    set_language("ko")


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "t.db")
    store.upsert_measurements([
        Measurement("oisst", "ds", "sea_water_temperature", "analysis", -68.0, -40.0, "2026-11-02T12:00:00Z", -1.5, "°C", location_id="weddell"),
        Measurement("metar", "NZSP", "air_temperature", "observation", -89.98, 180.0, "2026-11-03T06:00:00Z", -46.0, "°C", level="2m", location_id="metar:NZSP", quality="South Pole"),
    ])
    store.upsert_argo_listing([{
        "platform": "1", "cycle": 2, "time": "2026-11-01T00:00:00Z", "lat": -65.0, "lon": 0.0, "data_mode": "R",
        "position_qc": "1", "surface_temp": 1.0, "surface_salt": 34.0,
    }])
    store.save_argo_levels("1", 2, [{"pressure_dbar": 5.0, "depth_m": 5.0, "temp": 1.0, "salt": 34.0}])
    yield store
    store.close()


@pytest.fixture
def scratch(tmp_path):
    folder = tmp_path / "scratch"
    folder.mkdir()
    return folder


def _ctx(store, directory) -> Context:
    return Context(store, None, Settings(db_path=store.path, excel_dir=directory))


def _args(tmp_path, result=None) -> argparse.Namespace:
    return argparse.Namespace(
        db=str(tmp_path / "t.db"), dir=str(tmp_path / "xl"), month="2026-11", all=False,
        result=str(result) if result else None,
    )


def _settings(tmp_path) -> Settings:
    return Settings(db_path=tmp_path / "t.db", excel_dir=tmp_path / "xl")


def _one_sheet_book(target, scratch) -> excel.Book:
    book = excel.Book(target, scratch)
    sheet = excel.Sheet(book, "격자평균", [("값", 8)])
    for value in range(20):
        sheet.add([value])
    sheet.finish()
    return book


def test_pieces_are_kept_in_a_folder_of_their_own(tmp_path, scratch):
    target = tmp_path / "xl" / "a.xlsx"
    book = _one_sheet_book(target, scratch)
    pieces = [path for path in scratch.rglob("*") if path.is_file()]
    assert pieces and all(path.parent == book.pieces for path in pieces)
    assert book.pieces.parent == scratch and book.pieces.name.startswith(excel.SCRATCH_PREFIX)
    book.close()
    assert list(scratch.iterdir()) == []
    assert target.stat().st_size > 100
    assert not list(target.parent.glob(".*.tmp.xlsx"))


def test_failed_zip_write_leaves_no_pieces(tmp_path, scratch, monkeypatch):
    class Full(zipfile.ZipFile):
        def write(self, *args, **kwargs):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(xlsxwriter.workbook, "ZipFile", Full)
    target = tmp_path / "a.xlsx"
    target.write_bytes(b"old")
    book = _one_sheet_book(target, scratch)
    with pytest.raises(FileCreateError):
        book.close()
    assert list(scratch.iterdir()) == []
    assert target.read_bytes() == b"old"
    assert sys.platform == "win32" or not list(tmp_path.glob(".*.tmp.xlsx"))


def test_failed_sheet_leaves_no_pieces(tmp_path, scratch, store, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(excel, "_sheet_summary", broken)
    with pytest.raises(RuntimeError, match="boom"):
        excel.write_main_workbook(store, tmp_path / "xl" / MAIN, "2026-11", scratch)
    assert list(scratch.iterdir()) == []
    assert list((tmp_path / "xl").iterdir()) == []


def test_open_workbook_is_reported_and_cleaned_up(tmp_path, scratch, monkeypatch):
    def locked(source, target):
        raise PermissionError(errno.EACCES, "Permission denied")

    target = tmp_path / "a.xlsx"
    target.write_bytes(b"old")
    book = _one_sheet_book(target, scratch)
    monkeypatch.setattr(excel.os, "replace", locked)
    with pytest.raises(PermissionError, match="a.xlsx 파일이 열려 있어 저장하지 못했습니다"):
        book.close()
    assert list(scratch.iterdir()) == []
    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob(".*.tmp.xlsx"))


def test_sync_refuses_to_start_without_space(tmp_path, scratch, store, monkeypatch):
    monkeypatch.setattr(excel.shutil, "disk_usage", lambda place: SimpleNamespace(total=0, used=0, free=10 * excel.MIB))
    need = (excel.PIECES_FLOOR + excel.OUTPUT_FLOOR) // excel.MIB
    with pytest.raises(OSError, match=f"저장할 공간이 부족합니다.*여유 10 MB, 필요 {need} MB"):
        excel.sync(store, tmp_path / "xl", ["2026-11"], scratch=scratch)
    assert list((tmp_path / "xl").iterdir()) == []
    assert list(scratch.iterdir()) == []
    set_language("en")
    with pytest.raises(OSError, match=f"Not enough disk space to save.*has 10 MB free, {need} MB needed"):
        excel.sync(store, tmp_path / "xl", ["2026-11"], scratch=scratch)


def test_sync_writes_when_there_is_space(tmp_path, scratch, store):
    result = excel.sync(store, tmp_path / "xl", ["2026-11"], scratch=scratch)
    assert result["files"] == [MAIN, ARGO] and result["rows"] > 0
    assert list(scratch.iterdir()) == []
    assert sorted(path.name for path in (tmp_path / "xl").iterdir()) == [MAIN, ARGO]


def test_space_needed_follows_the_largest_workbook_of_the_months(tmp_path):
    assert excel.space_needed(tmp_path, ["2026-11"]) == (excel.PIECES_FLOOR, excel.OUTPUT_FLOOR)
    size = 20 * excel.MIB
    with open(tmp_path / ARGO, "wb") as handle:
        handle.truncate(size)
    (tmp_path / MAIN).write_bytes(b"x" * 10)
    with open(tmp_path / "antarctic_db_2026-09.xlsx", "wb") as handle:
        handle.truncate(2 * size)
    pieces, output = excel.space_needed(tmp_path, ["2026-11"])
    assert pieces == size * excel.PIECES_PER_BYTE > excel.PIECES_FLOOR
    assert output == 2 * size > excel.OUTPUT_FLOOR


def test_sweep_removes_only_old_folders_of_this_program(tmp_path):
    now = time.time()
    old = tmp_path / (excel.SCRATCH_PREFIX + "old")
    fresh = tmp_path / (excel.SCRATCH_PREFIX + "fresh")
    other = tmp_path / "tmpabcd1234"
    for folder in (old, fresh, other):
        folder.mkdir()
        (folder / "piece").write_text("x", encoding="utf-8")
    lookalike = tmp_path / (excel.SCRATCH_PREFIX + "file")
    lookalike.write_text("x", encoding="utf-8")
    stale = now - excel.SCRATCH_MAX_AGE - 60
    for path in (old, other, lookalike):
        os.utime(path, (stale, stale))
    assert excel.sweep_scratch(tmp_path, now) == 1
    assert not old.exists()
    assert fresh.exists() and other.exists() and lookalike.exists()
    assert excel.sweep_scratch(tmp_path / "missing", now) == 0


def test_leftovers_of_a_stopped_save_are_removed(tmp_path):
    keep = [tmp_path / MAIN, tmp_path / ARGO, tmp_path / ".note.tmp.xlsx"]
    drop = [tmp_path / ".antarctic_db_2026-11.tmp.xlsx", tmp_path / ".argo_levels_2026-10.tmp.xlsx"]
    for path in keep + drop:
        path.write_bytes(b"x")
    excel._remove_leftovers(tmp_path)
    assert all(path.exists() for path in keep)
    assert not any(path.exists() for path in drop)


def test_child_writes_rows_and_files_into_the_result_file(tmp_path, store, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(tmp_path))
    out = tmp_path / "out"
    out.mkdir()
    cli._excel_sync(_args(tmp_path, out / "result.json"))
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert result["files"] == [MAIN, ARGO] and result["rows"] > 0
    assert [path.name for path in out.iterdir()] == ["result.json"]


def test_child_survives_a_result_folder_that_was_removed(tmp_path, store, monkeypatch, capsys):
    gone = tmp_path / "gone"
    gone.mkdir()
    real = excel.sync

    def sync(*args, **kwargs):
        result = real(*args, **kwargs)
        shutil.rmtree(gone)
        return result

    monkeypatch.setattr(excel, "sync", sync)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(tmp_path))
    with pytest.raises(SystemExit) as stop:
        cli._excel_sync(_args(tmp_path, gone / "result.json"))
    assert stop.value.code == 1
    assert "FileNotFoundError" in capsys.readouterr().err
    assert (tmp_path / "xl" / MAIN).exists()


def test_child_writes_the_failure_into_the_result_file(tmp_path, monkeypatch, capsys):
    def locked(*args, **kwargs):
        raise PermissionError(f"{MAIN} 파일이 열려 있어 저장하지 못했습니다")

    monkeypatch.setattr(excel, "sync", locked)
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(tmp_path))
    result = tmp_path / "result.json"
    with pytest.raises(SystemExit) as stop:
        cli._excel_sync(_args(tmp_path, result))
    assert stop.value.code == 1
    assert json.loads(result.read_text(encoding="utf-8")) == {
        "error": f"PermissionError: {MAIN} 파일이 열려 있어 저장하지 못했습니다",
    }
    assert "Traceback" in capsys.readouterr().err


def test_child_without_a_result_file_prints_a_summary(tmp_path, store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: _settings(tmp_path))
    cli._excel_sync(_args(tmp_path))
    assert f"{MAIN}, {ARGO}" in capsys.readouterr().out


async def test_cancelled_save_stops_the_child_before_removing_its_folder(tmp_path, store, monkeypatch):
    seen = {}
    spawn = asyncio.create_subprocess_exec

    def command(store_path, directory, result_path=None):
        seen["result"] = result_path
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    async def watched(*args, **kwargs):
        seen["process"] = await spawn(*args, **kwargs)
        return seen["process"]

    monkeypatch.setattr(excel, "sync_command", command)
    monkeypatch.setattr(excel.asyncio, "create_subprocess_exec", watched)
    directory = tmp_path / "xl"
    directory.mkdir()
    leftover = directory / ".antarctic_db_2026-11.tmp.xlsx"
    leftover.write_bytes(b"x")
    task = asyncio.create_task(excel.collect(_ctx(store, directory)))
    async with asyncio.timeout(30):
        while "process" not in seen:
            await asyncio.sleep(0.01)
    assert seen["result"].parent.is_dir()
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 30
    assert seen["process"].returncode is not None
    assert not seen["result"].parent.exists()
    assert not leftover.exists()
    assert not store.kv_get("excel:stamp")


async def test_stopped_save_is_written_again_without_new_data(tmp_path, store, monkeypatch):
    directory = tmp_path / "xl"
    first = directory / MAIN
    script = tmp_path / "child.py"
    script.write_text(
        "import pathlib, sys, time\npathlib.Path(sys.argv[1]).write_bytes(b'x')\ntime.sleep(60)\n", encoding="utf-8",
    )
    real = excel.sync_command
    store.kv_set("excel:stamp", store.data_stamp())
    monkeypatch.setattr(
        excel, "sync_command",
        lambda store_path, target, result_path=None: [sys.executable, str(script), str(first)],
    )
    task = asyncio.create_task(excel.collect(_ctx(store, directory)))
    async with asyncio.timeout(30):
        while not first.exists():
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first.exists()
    assert store.kv_get("excel:stamp") != store.data_stamp()
    monkeypatch.setattr(excel, "sync_command", real)
    result = await excel.collect(_ctx(store, directory))
    assert not result.unchanged
    assert zipfile.is_zipfile(first) and zipfile.is_zipfile(directory / ARGO)
    assert store.kv_get("excel:stamp") == store.data_stamp()
    assert (await excel.collect(_ctx(store, directory))).unchanged


def _fake_child(tmp_path, monkeypatch, body: str) -> None:
    script = tmp_path / "child.py"
    script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(
        excel, "sync_command",
        lambda store_path, directory, result_path=None: [sys.executable, str(script), str(result_path)],
    )


REPORTED = """
import pathlib, sys
pathlib.Path(sys.argv[1]).write_text('{"error": "PermissionError: 파일이 열려 있음"}', encoding="utf-8")
sys.stderr.write("Traceback (most recent call last):\\nPermissionError: another line\\n")
sys.exit(1)
"""

STDERR_ONLY = """
import sys
sys.stderr.write("first line\\nlast line\\n")
sys.exit(1)
"""

SILENT = ""


@pytest.mark.parametrize("body, expected", [
    (REPORTED, "PermissionError: 파일이 열려 있음"),
    (STDERR_ONLY, "last line"),
    (SILENT, "엑셀 저장 프로세스 종료 코드 0"),
], ids=["result-file", "stderr-only", "silent"])
async def test_failed_child_is_reported_in_its_own_words(tmp_path, store, monkeypatch, body, expected):
    _fake_child(tmp_path, monkeypatch, body)
    directory = tmp_path / "xl"
    directory.mkdir()
    leftover = directory / ".argo_levels_2026-11.tmp.xlsx"
    leftover.write_bytes(b"x")
    store.kv_set("excel:stamp", store.data_stamp())
    with pytest.raises(FetchError) as failure:
        await excel.collect(_ctx(store, directory))
    assert render(str(failure.value)) == expected
    assert not leftover.exists()
    assert store.kv_get("excel:stamp") == ""


async def test_save_runs_in_a_child_and_leaves_only_the_workbooks(tmp_path, store, monkeypatch):
    seen = {}
    real = excel.sync_command

    def command(store_path, directory, result_path=None):
        seen["result"] = result_path
        return real(store_path, directory, result_path)

    monkeypatch.setattr(excel, "sync_command", command)
    directory = tmp_path / "xl"
    result = await excel.collect(_ctx(store, directory))
    assert result.rows > 0
    assert MAIN in render(result.message) and ARGO in render(result.message)
    assert sorted(path.name for path in directory.iterdir()) == [MAIN, ARGO]
    assert not seen["result"].parent.exists()
    assert store.kv_get("excel:stamp") == store.data_stamp()
    assert (await excel.collect(_ctx(store, directory))).unchanged


async def test_failure_inside_the_real_child_reaches_the_caller(tmp_path, store, monkeypatch):
    real = excel.sync_command
    folder = tmp_path / "not-a-database"
    folder.mkdir()
    monkeypatch.setattr(
        excel, "sync_command",
        lambda store_path, directory, result_path=None: real(folder, directory, result_path),
    )
    with pytest.raises(FetchError, match="unable to open database file"):
        await excel.collect(_ctx(store, tmp_path / "xl"))
    assert not store.kv_get("excel:stamp")
