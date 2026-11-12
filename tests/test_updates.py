"""자동 업데이트: 파일 고르기, 내려받기와 검증, 설치 명령, 재시작 명령."""

import hashlib
import json
import time

import httpx
import pytest

from antarctic_monitor import updates
from antarctic_monitor.config import load_settings
from antarctic_monitor.http import FetchError, Fetcher
from antarctic_monitor.i18n import render


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
