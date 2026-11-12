"""자동 업데이트: 파일 고르기, 내려받기와 검증, 설치 명령, 재시작 명령."""

import hashlib
import json
import os
import subprocess
import sys
import time

import httpx
import pytest

from antarctic_monitor import __version__, cli, i18n, updates
from antarctic_monitor.config import load_settings
from antarctic_monitor.http import FetchError, Fetcher
from antarctic_monitor.i18n import msg, render


def test_asset_name_follows_the_release_naming():
    assert updates.asset_name("0.2.0", "win32", "AMD64") == "SUYA-0.2.0-windows-x64-setup.exe"
    assert updates.asset_name("0.2.0", "darwin", "arm64") == "SUYA-0.2.0-macos-arm64.dmg"
    assert updates.asset_name("0.2.0", "darwin", "x86_64") == "SUYA-0.2.0-macos-x86_64.dmg"
    assert updates.asset_name("0.2.0", "linux", "x86_64") == "SUYA-0.2.0-linux-x86_64.tar.gz"
    assert updates.asset_name("0.2.0", "linux", "aarch64") is None
    assert updates.can_self_update("darwin", frozen=True) and not updates.can_self_update("darwin", frozen=False)
    assert not updates.can_self_update("freebsd", frozen=True)


def _release(version: str, names: list[str]) -> dict:
    base = f"https://example.test/releases/download/v{version}/"
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://example.test/releases/tag/v{version}",
        "assets": [{"name": n, "size": 10, "browser_download_url": base + n} for n in names],
    }


async def test_latest_release_picks_the_asset_for_this_platform():
    payload = _release("9.0.0", ["SHA256SUMS.txt", "SUYA-9.0.0-macos-arm64.dmg", "SUYA-9.0.0-windows-x64-setup.exe"])
    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))), backoff=0.0)
    release = await updates.latest_release(fetcher, system="darwin", machine="arm64")
    assert release["newer"] and release["version"] == "9.0.0"
    assert release["asset"]["name"] == "SUYA-9.0.0-macos-arm64.dmg" and release["checksums"].endswith("SHA256SUMS.txt")
    linux = await updates.latest_release(fetcher, system="linux", machine="x86_64")
    assert linux["asset"] is None
    await fetcher.aclose()


async def test_latest_release_explains_the_github_rate_limit():
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 20 * 60)}
    body = {"message": "API rate limit exceeded for 203.0.113.9.", "documentation_url": "https://example.test/docs"}
    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=body, headers=headers))), backoff=0.0)
    with pytest.raises(FetchError) as caught:
        await updates.latest_release(fetcher, system="darwin", machine="arm64")
    text = render(str(caught.value))
    assert "GitHub" in text and "20" in text and "203.0.113.9" not in text
    await fetcher.aclose()

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, text="slow down"))), backoff=0.0)
    with pytest.raises(FetchError) as caught:
        await updates.latest_release(fetcher, system="darwin", machine="arm64")
    assert "GitHub" in render(str(caught.value)) and "slow down" not in str(caught.value)
    await fetcher.aclose()

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404, json={"message": "Not Found"}))), backoff=0.0)
    with pytest.raises(FetchError, match="HTTP 404"):
        await updates.latest_release(fetcher, system="darwin", machine="arm64")
    await fetcher.aclose()

    assert "1" in render(updates.rate_limit_message("130", now=100.0))
    assert "분" not in render(updates.rate_limit_message("not a number"))


async def test_download_verifies_the_checksum(tmp_path):
    body = b"installer bytes " * 5000
    good = hashlib.sha256(body).hexdigest()
    sums = f"{good}  SUYA-9.0.0-macos-arm64.dmg\n{'0' * 64}  other\n"

    def handler(request):
        if request.url.path.endswith("SHA256SUMS.txt"):
            return httpx.Response(200, text=sums)
        return httpx.Response(200, content=body, headers={"content-length": str(len(body))})

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    release = {
        "asset": {"name": "SUYA-9.0.0-macos-arm64.dmg", "url": "https://example.test/dl/SUYA-9.0.0-macos-arm64.dmg", "size": len(body)},
        "checksums": "https://example.test/dl/SHA256SUMS.txt",
    }
    seen = []
    path = await updates.download(fetcher, release, folder=tmp_path, progress=lambda done, total: seen.append((done, total)))
    assert path.read_bytes() == body and path.parent == tmp_path / "updates"
    assert seen and seen[-1] == (len(body), len(body))

    release["asset"]["name"] = "other"
    with pytest.raises(FetchError) as caught:
        await updates.download(fetcher, release, folder=tmp_path)
    assert "SHA-256" in render(str(caught.value))
    assert not list((tmp_path / "updates").glob("*.part"))
    await fetcher.aclose()


def test_parse_checksums_accepts_both_separators():
    one, two = "a" * 64, "B" * 64
    text = f"{one}  SUYA-1.dmg\n{two} *SUYA-2.exe\n\nnot a line\n"
    assert updates.parse_checksums(text) == {"SUYA-1.dmg": one, "SUYA-2.exe": two.lower()}


def test_swap_directories_keeps_the_old_folder(tmp_path):
    current = tmp_path / "SUYA.app"
    (current / "Contents").mkdir(parents=True)
    (current / "Contents" / "v").write_text("old")
    new = tmp_path / "SUYA.app.update"
    (new / "Contents").mkdir(parents=True)
    (new / "Contents" / "v").write_text("new")
    old = updates.swap_directories(new, current)
    assert (current / "Contents" / "v").read_text() == "new"
    assert old == tmp_path / "SUYA.app.old" and (old / "Contents" / "v").read_text() == "old"
    assert not new.exists()


def test_install_commands(tmp_path):
    args = updates.windows_install_args(tmp_path / "setup.exe")
    assert args[0].endswith("setup.exe") and "/VERYSILENT" in args and "/relaunch=1" in args
    script = updates.relaunch_script(4321, ["/usr/bin/open", "-a", "/Applications/SUYA.app"])
    assert script[0] == "/bin/sh" and "kill -0 4321" in script[2] and script[-3:] == ["/usr/bin/open", "-a", "/Applications/SUYA.app"]
    assert updates.current_bundle("/Applications/SUYA.app/Contents/MacOS/suya").name == "SUYA.app"
    assert updates.current_bundle("/usr/local/bin/suya") is None


def test_cleanup_removes_leftovers(tmp_path):
    folder = updates.update_folder(tmp_path)
    folder.mkdir()
    (folder / "SUYA-9.dmg").write_bytes(b"x")
    updates.cleanup(tmp_path)
    assert not folder.exists()


def test_update_mode_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("MONITOR_UPDATE_MODE", raising=False)
    assert load_settings(env_file=tmp_path / "none", user_dir=tmp_path).update_mode == "auto"
    monkeypatch.setenv("MONITOR_UPDATE_MODE", "AUTO")
    assert load_settings(env_file=tmp_path / "none", user_dir=tmp_path).update_mode == "auto"
    monkeypatch.setenv("MONITOR_UPDATE_MODE", "sometimes")
    assert load_settings(env_file=tmp_path / "none", user_dir=tmp_path).update_mode == "auto"
    monkeypatch.setenv("MONITOR_UPDATE_MODE", "notify")
    assert load_settings(env_file=tmp_path / "none", user_dir=tmp_path).update_mode == "notify"
    assert json.dumps(updates.MODES)


async def test_latest_release_falls_back_to_the_release_page_when_the_api_is_rate_limited():
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 20 * 60)}
    seen = []

    def handler(request):
        seen.append((request.method, request.url.host, request.url.path))
        if request.url.host == "api.github.com":
            return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers=headers)
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(302, headers={"location": "https://github.com/jongsu-king/SUYA/releases/tag/v9.1.2"})
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    fetcher = Fetcher(client, backoff=0.0)
    release = await updates.latest_release(fetcher, system="darwin", machine="arm64")
    assert release["version"] == "9.1.2" and release["newer"]
    assert release["url"] == "https://github.com/jongsu-king/SUYA/releases/tag/v9.1.2"
    base = "https://github.com/jongsu-king/SUYA/releases/download/v9.1.2/"
    assert release["asset"] == {"name": "SUYA-9.1.2-macos-arm64.dmg", "url": base + "SUYA-9.1.2-macos-arm64.dmg", "size": 0}
    assert release["checksums"] == base + "SHA256SUMS.txt"
    assert ("HEAD", "github.com", "/jongsu-king/SUYA/releases/latest") in seen
    await fetcher.aclose()

    def no_tag(request):
        if request.url.host == "api.github.com":
            return httpx.Response(403, json={"message": "API rate limit exceeded"}, headers=headers)
        return httpx.Response(200)

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(no_tag), follow_redirects=True), backoff=0.0)
    with pytest.raises(FetchError) as caught:
        await updates.latest_release(fetcher, system="darwin", machine="arm64")
    assert "GitHub" in render(str(caught.value)) and "20" in render(str(caught.value))
    await fetcher.aclose()


def _page_handler(api):
    """API 요청은 api에 맡기고, 릴리스 페이지 요청은 9.1.2 태그 주소로 넘겨 주는 응답기."""

    def handler(request):
        if request.url.host == "api.github.com":
            return api(request)
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(302, headers={"location": "https://github.com/jongsu-king/SUYA/releases/tag/v9.1.2"})
        return httpx.Response(200)

    return handler


def _unreachable(request):
    raise httpx.ConnectError("no route", request=request)


@pytest.mark.parametrize(
    "api",
    [
        lambda request: httpx.Response(503, text="unavailable"),
        lambda request: httpx.Response(404, json={"message": "Not Found"}),
        lambda request: httpx.Response(200, text="<html>not json</html>"),
        lambda request: httpx.Response(200, json={"message": "no tag here"}),
        _unreachable,
    ],
    ids=["server error", "not found", "not json", "no tag", "unreachable"],
)
async def test_latest_release_reads_the_release_page_whenever_the_api_fails(api):
    client = httpx.AsyncClient(transport=httpx.MockTransport(_page_handler(api)), follow_redirects=True)
    fetcher = Fetcher(client, backoff=0.0)
    release = await updates.latest_release(fetcher, system="win32", machine="AMD64")
    base = "https://github.com/jongsu-king/SUYA/releases/download/v9.1.2/"
    assert release["version"] == "9.1.2" and release["newer"]
    assert release["asset"] == {"name": "SUYA-9.1.2-windows-x64-setup.exe", "url": base + "SUYA-9.1.2-windows-x64-setup.exe", "size": 0}
    assert release["checksums"] == base + "SHA256SUMS.txt"
    await fetcher.aclose()


async def test_latest_release_keeps_the_api_error_when_the_page_fails_too():
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(502, text="bad gateway")
        raise httpx.ConnectError("no route", request=request)

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True), backoff=0.0)
    with pytest.raises(FetchError, match="502"):
        await updates.latest_release(fetcher, system="darwin", machine="arm64")
    await fetcher.aclose()


def test_schedule_retries_sooner_after_a_failure_and_backs_off():
    schedule = updates.Schedule(first=1000.0)
    assert not schedule.due(999.0) and schedule.due(1000.0)
    schedule.started(1000.0)
    assert schedule.next_at == 1000.0 + updates.CHECK_INTERVAL and not schedule.due(1001.0)
    now, delays = 1000.0, []
    for _ in range(6):
        delays.append(schedule.failed(now) - now)
        assert not schedule.due(schedule.next_at - 1) and schedule.due(schedule.next_at)
        now = schedule.next_at
    assert delays == [600, 1800, 3600, 7200, 7200, 7200] and schedule.failures == 6
    assert schedule.succeeded(now) == now + updates.CHECK_INTERVAL and schedule.failures == 0
    assert schedule.failed(now) == now + 600 and schedule.failures == 1
    assert updates.CHECK_INTERVAL == 6 * 3600 and updates.RETRY_DELAYS == (600, 1800, 3600, 7200)


def test_schedule_checks_again_when_the_clock_was_set_back():
    schedule = updates.Schedule(first=0.0)
    schedule.succeeded(1_000_000.0)
    assert not schedule.due(1_000_000.0) and not schedule.due(1_000_060.0)
    assert schedule.due(1_000_000.0 + updates.CHECK_INTERVAL)
    assert schedule.due(1_000_000.0 - 3 * 86400)


class _Broken(httpx.AsyncByteStream):
    """data를 내준 뒤 연결이 끊긴 것처럼 오류를 내는 응답 본문."""

    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        yield self.data
        raise httpx.ReadError("connection lost")


def _installer(size: int = 200_000):
    """설치 파일 내용, 그 파일을 가리키는 릴리스 정보, SHA-256 목록을 돌려줍니다."""
    body = bytes(index % 251 for index in range(size))
    name = "SUYA-9.0.0-macos-arm64.dmg"
    release = {
        "asset": {"name": name, "url": f"https://example.test/dl/{name}", "size": size},
        "checksums": "https://example.test/dl/SHA256SUMS.txt",
    }
    return body, release, f"{hashlib.sha256(body).hexdigest()}  {name}\n"


def _asset_server(sums, answer):
    """SHA-256 목록은 그대로 주고, 설치 파일 요청은 answer(몇 번째 요청, Range 값)에 맡기는 응답기. Range 값은 calls에 쌓입니다."""
    calls = []

    def handler(request):
        if request.url.path.endswith("SHA256SUMS.txt"):
            return httpx.Response(200, text=sums)
        calls.append(request.headers.get("range"))
        return answer(len(calls), calls[-1])

    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0), calls


def _range_start(wanted: str) -> int:
    return int(wanted.removeprefix("bytes=").rstrip("-"))


def _rest(body: bytes, wanted: str) -> httpx.Response:
    """Range 요청에 남은 부분을 206으로 답합니다."""
    start = _range_start(wanted)
    return httpx.Response(206, content=body[start:], headers={"content-range": f"bytes {start}-{len(body) - 1}/{len(body)}"})


def _cut_off(body: bytes) -> httpx.Response:
    """150,000바이트를 보낸 뒤 끊기는 응답."""
    return httpx.Response(200, stream=_Broken(body[:150_000]), headers={"content-length": str(len(body))})


async def test_download_continues_where_the_connection_broke(tmp_path):
    body, release, sums = _installer()
    fetcher, calls = _asset_server(sums, lambda count, wanted: _cut_off(body) if count == 1 else _rest(body, wanted))
    seen = []
    path = await updates.download(fetcher, release, folder=tmp_path, progress=lambda done, total: seen.append((done, total)), pause=0)
    assert path.read_bytes() == body
    assert len(calls) == 2 and calls[0] is None and 0 < _range_start(calls[1]) <= 150_000
    assert seen[-1] == (len(body), len(body)) and all(total == len(body) for _, total in seen)
    assert [item.name for item in path.parent.iterdir()] == [path.name]
    await fetcher.aclose()


async def test_download_starts_over_when_the_server_ignores_the_range(tmp_path):
    body, release, sums = _installer()
    fetcher, calls = _asset_server(
        sums, lambda count, wanted: _cut_off(body) if count == 1 else httpx.Response(200, content=body)
    )
    path = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert path.read_bytes() == body and len(calls) == 2 and calls[1] is not None
    await fetcher.aclose()


async def test_download_drops_a_part_that_does_not_fit(tmp_path):
    body, release, sums = _installer()

    def answer(count, wanted):
        if not wanted:
            return httpx.Response(200, content=body)
        if _range_start(wanted) >= len(body):
            return httpx.Response(416, headers={"content-range": f"bytes */{len(body)}"})
        return _rest(body, wanted)

    fetcher, calls = _asset_server(sums, answer)
    folder = updates.update_folder(tmp_path)
    folder.mkdir()
    partial = folder / (release["asset"]["name"] + ".part")
    partial.write_bytes(b"x" * (len(body) + 10))
    path = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert path.read_bytes() == body and calls == [f"bytes={len(body) + 10}-", None]

    calls.clear()
    path.unlink()
    partial.write_bytes(b"x" * 1000)
    path = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert path.read_bytes() == body and calls == ["bytes=1000-", None]
    assert not partial.exists()
    await fetcher.aclose()


async def test_download_keeps_the_part_for_the_next_try(tmp_path):
    body, release, sums = _installer()
    online = []

    def answer(count, wanted):
        if count == 1:
            return _cut_off(body)
        if not online:
            raise httpx.ConnectError("no route")
        return _rest(body, wanted)

    fetcher, calls = _asset_server(sums, answer)
    with pytest.raises(FetchError):
        await updates.download(fetcher, release, folder=tmp_path, attempts=2, pause=0)
    partial = updates.update_folder(tmp_path) / (release["asset"]["name"] + ".part")
    kept = partial.stat().st_size
    assert 0 < kept <= 150_000 and calls == [None, f"bytes={kept}-"]
    online.append(True)
    path = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert path.read_bytes() == body and calls == [None, f"bytes={kept}-", f"bytes={kept}-"]
    assert not partial.exists()
    await fetcher.aclose()


async def test_download_refuses_a_file_the_checksum_list_does_not_name(tmp_path):
    body, release, _ = _installer()
    fetcher, calls = _asset_server(f"{'0' * 64}  another-file.dmg\n", lambda count, wanted: httpx.Response(200, content=body))
    missing = msg("릴리스의 SHA-256 목록에서 이 파일을 찾을 수 없습니다")
    with pytest.raises(FetchError) as caught:
        await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert str(caught.value) == missing and "SHA-256" in render(missing)
    with pytest.raises(FetchError) as caught:
        await updates.download(fetcher, dict(release, checksums=None), folder=tmp_path, pause=0)
    assert str(caught.value) == missing
    assert calls == [] and list(updates.update_folder(tmp_path).iterdir()) == []
    await fetcher.aclose()


async def test_download_does_not_fetch_a_verified_file_twice(tmp_path):
    body, release, sums = _installer()
    fetcher, calls = _asset_server(sums, lambda count, wanted: httpx.Response(200, content=body))
    first = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    again = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert again == first and again.read_bytes() == body and calls == [None]
    first.write_bytes(b"damaged")
    repaired = await updates.download(fetcher, release, folder=tmp_path, pause=0)
    assert repaired.read_bytes() == body and calls == [None, None]
    await fetcher.aclose()


def test_self_update_blocker_names_what_stops_a_macos_copy(tmp_path, monkeypatch):
    installed = tmp_path / "Applications" / "SUYA.app" / "Contents" / "MacOS" / "suya"
    moved = tmp_path / "AppTranslocation" / "1A2B" / "d" / "SUYA.app" / "Contents" / "MacOS" / "suya"
    for executable in (installed, moved):
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"")
    assert updates.self_update_blocker("darwin", installed) is None
    assert updates.self_update_blocker("win32", tmp_path / "suya.exe") is None
    assert updates.self_update_blocker("linux", tmp_path / "suya") is None
    assert updates.can_self_update("darwin", frozen=True)

    not_found = msg("실행 중인 프로그램의 .app 폴더를 찾을 수 없습니다")
    assert updates.self_update_blocker("darwin", tmp_path / "bin" / "suya") == not_found
    assert updates.self_update_blocker("darwin", tmp_path / "Gone" / "SUYA.app" / "Contents" / "MacOS" / "suya") == not_found
    assert updates.self_update_blocker("darwin", moved) == msg(
        "프로그램이 응용 프로그램 폴더 밖에서 임시로 실행되고 있습니다. 응용 프로그램 폴더로 옮긴 뒤 다시 여세요"
    )

    monkeypatch.setattr(updates.os, "access", lambda path, mode: False)
    applications = str((tmp_path / "Applications").resolve())
    locked = updates.self_update_blocker("darwin", installed)
    assert locked == msg("{folder} 폴더에 쓸 수 없어 프로그램을 바꿀 수 없습니다", folder=applications)
    assert applications in render(locked)


def test_update_check_command(monkeypatch, capsys):
    monkeypatch.setattr(i18n, "_language", i18n.get_language())
    monkeypatch.setattr(cli, "_configure_logging", lambda command: None)
    answers = []

    async def latest_release(fetcher):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def run():
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--lang", "en", "update-check"])
        return exit_info.value.code, capsys.readouterr()

    monkeypatch.setattr(updates, "latest_release", latest_release)
    page = "https://example.test/releases/tag/v99.0.0"
    answers.append({"version": "99.0.0", "url": page, "newer": True, "asset": None, "checksums": None})
    code, output = run()
    assert code == 0 and output.err == ""
    assert output.out.splitlines() == [
        f"This program: {__version__}", "Latest release: 99.0.0", "Version 99.0.0 is available", page,
    ]

    answers.append({"version": __version__, "url": page, "newer": False, "asset": None, "checksums": None})
    code, output = run()
    assert code == 0 and output.out.splitlines()[-1] == f"You have the latest version ({__version__})"
    assert page not in output.out

    answers.append(FetchError("HTTP 503"))
    code, output = run()
    assert code == 1 and output.out == "" and output.err.strip() == "Update check failed: HTTP 503"


UPDATE_CHECK_SCRIPT = r'''
import dataclasses
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from antarctic_monitor import __version__, i18n, updates
from antarctic_monitor.config import Settings
from antarctic_monitor.gui.app import MainWindow
from antarctic_monitor.gui.backend import Backend
from antarctic_monitor.gui.dialogs import SettingsDialog
from antarctic_monitor.http import FetchError

i18n.set_language("en")
app = QApplication([])
folder = Path(tempfile.mkdtemp())
settings = Settings(db_path=folder / "t.db", excel_dir=folder / "x", update_mode="off")
backend = Backend(settings, collect=False)
backend.start()
window = MainWindow(backend, settings)
answers = []
offered = []


async def latest_release(fetcher):
    answer = answers.pop(0)
    if isinstance(answer, Exception):
        raise answer
    return answer


def until(check, seconds=30.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if check():
            return True
        time.sleep(0.02)
    return False


def found(version, newer):
    return {"version": version, "url": "https://example.test/v" + version, "newer": newer, "asset": None, "checksums": None}


updates.latest_release = latest_release
window._offer_update = lambda release, automatic: offered.append((release["version"], automatic))
schedule = window._update_schedule
assert window.update_status_text() == "Not checked yet", window.update_status_text()

for count, delay in enumerate((600, 1800, 3600), start=1):
    answers.append(FetchError("HTTP 503"))
    before = time.time()
    window.check_updates(manual=False)
    assert until(lambda: schedule.failures == count), schedule.failures
    assert before + delay - 1 <= schedule.next_at <= time.time() + delay + 1, (count, schedule.next_at - before)
    shown = window.statusBar().currentMessage()
    assert ("failed 3 times in a row: HTTP 503" in shown) == (count == 3), (count, shown)
assert window.update_status_text().endswith("Failed: HTTP 503"), window.update_status_text()

answers.append(FetchError("HTTP 503"))
window.check_updates(manual=True)
assert until(lambda: schedule.failures == 4), schedule.failures
assert window.statusBar().currentMessage() == "Update check failed: HTTP 503", window.statusBar().currentMessage()

answers.append(found(__version__, False))
before = time.time()
window.check_updates(manual=True)
assert until(lambda: schedule.failures == 0), schedule.failures
assert schedule.next_at >= before + updates.CHECK_INTERVAL - 1
latest = f"You have the latest version ({__version__})"
assert window.statusBar().currentMessage() == latest, window.statusBar().currentMessage()
assert window.update_status_text().endswith(latest) and "\n" not in window.update_status_text()

window.settings_ = dataclasses.replace(settings, update_mode="notify")
status = window.update_status_text().splitlines()
assert len(status) == 2 and status[1].startswith("Next automatic check 20"), status
dialog = SettingsDialog(window.settings_, window, update_status=window.update_status_text())
assert dialog.update_status.text() == window.update_status_text()

answers.append(found("99.0.0", True))
window.check_updates(manual=False)
assert until(lambda: offered == [("99.0.0", False)]), offered
assert "Version 99.0.0 is available" in window.update_status_text()

window._deferred_update = "99.0.0"
schedule.failures = 2
answers.append(found("99.0.0", True))
window.check_updates(manual=False)
assert until(lambda: schedule.failures == 0), schedule.failures
assert offered == [("99.0.0", False)], offered
answers.append(found("99.0.0", True))
window.check_updates(manual=True)
assert until(lambda: len(offered) == 2), offered

window._updating = True
answers.append(found("99.0.0", True))
window.check_updates(manual=True)
window._update_tick()
assert not until(lambda: not answers, 0.5), "a check ran during an update"
print("update check ok", flush=True)
os._exit(0)
'''


def test_window_repeats_a_failed_check_and_shows_the_last_result():
    pytest.importorskip("PySide6")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", UPDATE_CHECK_SCRIPT], capture_output=True, text=True, errors="replace", timeout=120, env=env)
    assert done.returncode == 0 and "update check ok" in done.stdout, done.stderr
