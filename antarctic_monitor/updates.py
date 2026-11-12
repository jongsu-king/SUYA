"""GitHub 릴리스로 새 버전을 확인하고, 설치판이면 이 OS용 설치 파일을 받아 검증·설치·재시작합니다.

pip로 설치한 경우는 내려받기 페이지만 안내합니다. 확인이 실패하면 간격을 늘려 가며 다시 확인하고,
내려받기가 끊기면 받은 데서 이어 받습니다.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import __url__, __version__
from .config import app_data_dir
from .http import FetchError, Fetcher, RateLimited
from .i18n import msg, render

log = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/jongsu-king/SUYA/releases/latest"
RELEASES_PAGE = f"{__url__}/releases/latest"
CHECKSUMS = "SHA256SUMS.txt"
MODES = ("off", "notify", "auto")
DEFAULT_MODE = "auto"
CHECK_INTERVAL = 6 * 3600
RETRY_DELAYS = (600, 1800, 3600, 7200)
DOWNLOAD_ATTEMPTS = 3


def parse_version(text: str) -> tuple[int, int, int]:
    numbers = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def asset_name(version: str, system: str = sys.platform, machine: str = platform.machine()) -> str | None:
    """이 운영체제에 맞는 릴리스 파일 이름. release.yml이 만드는 이름과 같아야 합니다."""
    arch = machine.lower()
    if system == "win32":
        return f"SUYA-{version}-windows-x64-setup.exe"
    if system == "darwin":
        return f"SUYA-{version}-macos-{'arm64' if arch in ('arm64', 'aarch64') else 'x86_64'}.dmg"
    if system.startswith("linux") and arch in ("x86_64", "amd64"):
        return f"SUYA-{version}-linux-x86_64.tar.gz"
    return None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def can_self_update(system: str = sys.platform, frozen: bool | None = None) -> bool:
    return (is_frozen() if frozen is None else frozen) and asset_name("0", system) is not None


def self_update_blocker(system: str = sys.platform, executable: str | Path = sys.executable) -> str | None:
    """설치 파일을 받기 전에 알 수 있는, 스스로 바꿀 수 없는 이유. 없으면 None입니다.

    macOS에서 프로그램이 임시 위치에서 실행 중이거나 프로그램이 든 폴더에 쓸 수 없으면, 다 받은 뒤에야 설치가
    실패합니다. 그 전에 알아내 내려받기 페이지로 안내합니다.
    """
    if system != "darwin":
        return None
    bundle = current_bundle(executable)
    if bundle is None or not bundle.exists():
        return msg("실행 중인 프로그램의 .app 폴더를 찾을 수 없습니다")
    if "AppTranslocation" in bundle.parts:
        return msg("프로그램이 응용 프로그램 폴더 밖에서 임시로 실행되고 있습니다. 응용 프로그램 폴더로 옮긴 뒤 다시 여세요")
    if not os.access(bundle.parent, os.W_OK):
        return msg("{folder} 폴더에 쓸 수 없어 프로그램을 바꿀 수 없습니다", folder=str(bundle.parent))
    return None


class Schedule:
    """자동 확인 시각을 정합니다. 성공하면 interval 뒤에, 실패하면 retries의 간격으로 점점 늦춰 다시 확인합니다."""

    def __init__(self, first: float, interval: float = CHECK_INTERVAL, retries: tuple[float, ...] = RETRY_DELAYS):
        self.interval = interval
        self.retries = retries
        self.next_at = first
        self.failures = 0

    def due(self, now: float) -> bool:
        """확인할 때가 되었는지. 시계가 뒤로 돌아가 다음 시각이 가장 긴 간격보다 멀어진 경우도 때가 된 것으로 봅니다."""
        return now >= self.next_at or self.next_at - now > max(self.interval, *self.retries)

    def started(self, now: float) -> None:
        """확인을 시작할 때 부릅니다. 결과가 돌아오지 않아도 다음 확인이 잡혀 있게 합니다."""
        self.next_at = now + self.interval

    def succeeded(self, now: float) -> float:
        self.failures = 0
        self.next_at = now + self.interval
        return self.next_at

    def failed(self, now: float) -> float:
        self.failures += 1
        self.next_at = now + self.retries[min(self.failures, len(self.retries)) - 1]
        return self.next_at


def rate_limit_message(reset: str | None = None, now: float | None = None) -> str:
    """GitHub가 알려 준 한도 해제 시각(Unix 초)을 '몇 분 뒤'로 바꿔 안내문을 만듭니다."""
    try:
        remaining = int(reset) - (now if now is not None else time.time()) if reset else 0
    except ValueError:
        remaining = 0
    if remaining > 0:
        return msg("GitHub 요청 한도에 걸렸습니다. 약 {minutes}분 뒤에 다시 확인하세요", minutes=max(1, int((remaining + 59) // 60)))
    return msg("GitHub 요청 한도에 걸렸습니다. 잠시 후 다시 확인하세요")


def _rate_limited(response) -> bool:
    return response.status_code == 403 and (
        response.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in response.text.lower()
    )


async def release_from_page(fetcher: Fetcher, system: str = sys.platform, machine: str = platform.machine()) -> dict | None:
    """API가 답하지 못할 때 쓰는 대안. 릴리스 페이지가 넘겨 주는 태그 주소에서 버전을 읽고, 파일 주소는 이름 규칙으로 만듭니다."""
    try:
        response = await fetcher.request("HEAD", RELEASES_PAGE, timeout=20.0, interactive=True)
    except FetchError:
        return None
    found = re.search(r"/releases/tag/(v?(\d+\.\d+\.\d+[^/?#]*))$", response.url.path) if response.status_code < 400 else None
    if not found:
        return None
    tag, version = found.group(1), found.group(2)
    base = f"{__url__}/releases/download/{tag}/"
    wanted = asset_name(version, system, machine)
    return {
        "version": version,
        "url": f"{__url__}/releases/tag/{tag}",
        "newer": is_newer(version),
        "asset": {"name": wanted, "url": base + wanted, "size": 0} if wanted else None,
        "checksums": base + CHECKSUMS,
    }


async def _release_from_api(fetcher: Fetcher, system: str, machine: str) -> dict:
    try:
        response = await fetcher.request("GET", RELEASES_API, timeout=20.0, interactive=True)
    except RateLimited as exc:
        raise FetchError(rate_limit_message()) from exc
    if _rate_limited(response):
        raise FetchError(rate_limit_message(response.headers.get("x-ratelimit-reset")))
    if response.status_code >= 400:
        raise FetchError(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise FetchError(msg("GitHub의 답을 읽을 수 없습니다")) from exc
    tag = str(data.get("tag_name") or "") if isinstance(data, dict) else ""
    if not re.match(r"v?\d", tag):
        raise FetchError(msg("GitHub의 답을 읽을 수 없습니다"))
    version = tag[1:] if tag.startswith("v") else tag
    assets = {item.get("name"): item for item in data.get("assets") or [] if item.get("name")}
    wanted = asset_name(version, system, machine)
    asset = assets.get(wanted) if wanted else None
    checksums = assets.get(CHECKSUMS)
    return {
        "version": version,
        "url": data.get("html_url") or RELEASES_PAGE,
        "newer": is_newer(version),
        "asset": {"name": asset["name"], "url": asset["browser_download_url"], "size": int(asset.get("size") or 0)} if asset else None,
        "checksums": checksums["browser_download_url"] if checksums else None,
    }


async def latest_release(fetcher: Fetcher, system: str = sys.platform, machine: str = platform.machine()) -> dict:
    """최신 릴리스를 GitHub API에 묻습니다. 한도, 서버 오류, 연결 실패, 읽을 수 없는 답이면 릴리스 페이지에서 읽습니다."""
    try:
        return await _release_from_api(fetcher, system, machine)
    except FetchError as error:
        release = await release_from_page(fetcher, system, machine)
        if release is None:
            raise
        log.info("GitHub API가 답하지 못해 릴리스 페이지에서 버전을 읽었습니다: %s", render(str(error)))
        return release


def parse_checksums(text: str) -> dict[str, str]:
    output = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            output[parts[-1].lstrip("*")] = parts[0].lower()
    return output


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_folder(base: Path | None = None) -> Path:
    return (base or app_data_dir()) / "updates"


async def _fetch_asset(fetcher: Fetcher, url: str, partial: Path, progress, attempts: int, pause: float) -> bool:
    """전송이 끊기면 받은 데서 이어 받으며 attempts번까지 시도합니다. 앞서 받은 부분에 이어 붙였으면 True를 돌려줍니다."""
    pieced = False
    for attempt in range(1, attempts + 1):
        pieced = pieced or (partial.exists() and partial.stat().st_size > 0)
        try:
            await fetcher.download(url, partial, progress=progress, resume=True, timeout=60.0)
            break
        except FetchError as error:
            if attempt >= attempts:
                raise
            log.warning("업데이트 내려받기 %d번째 시도 실패: %s", attempt, render(str(error)))
            await asyncio.sleep(pause)
    return pieced


async def download(
    fetcher: Fetcher, release: dict, folder: Path | None = None, progress: Callable[[int, int], None] | None = None,
    attempts: int = DOWNLOAD_ATTEMPTS, pause: float = 3.0,
) -> Path:
    """설치 파일을 받아 릴리스의 SHA-256 목록과 대조합니다. 목록에 이 파일이 없거나 값이 다르면 실패로 처리합니다.

    전송이 끊기면 받은 데서 이어 받습니다. 끝내 실패하면 받은 부분을 남겨 다음 시도가 이어 받게 하고,
    이어 붙인 파일의 값이 다르면 지우고 처음부터 한 번 더 받습니다. 앞서 받아 둔 파일의 값이 목록과 같으면
    다시 받지 않습니다.
    """
    asset = release.get("asset")
    if not asset:
        raise FetchError(msg("이 운영체제용 설치 파일이 릴리스에 없습니다"))
    folder = update_folder(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / asset["name"]
    partial = target.with_name(target.name + ".part")
    for leftover in folder.iterdir():
        if leftover.is_file() and leftover not in (partial, target):
            leftover.unlink(missing_ok=True)
    listed = {}
    if release.get("checksums"):
        listed = parse_checksums(await fetcher.get_text(release["checksums"], timeout=30.0, interactive=True))
    expected = listed.get(asset["name"])
    if not expected:
        raise FetchError(msg("릴리스의 SHA-256 목록에서 이 파일을 찾을 수 없습니다"))
    if target.exists():
        if sha256_of(target) == expected:
            partial.unlink(missing_ok=True)
            return target
        target.unlink()
    pieced = await _fetch_asset(fetcher, asset["url"], partial, progress, attempts, pause)
    digest = sha256_of(partial)
    if digest != expected and pieced:
        log.warning("이어 받은 업데이트 파일의 SHA-256이 달라 처음부터 다시 받습니다")
        partial.unlink(missing_ok=True)
        await _fetch_asset(fetcher, asset["url"], partial, progress, attempts, pause)
        digest = sha256_of(partial)
    if digest != expected:
        partial.unlink(missing_ok=True)
        raise FetchError(msg("내려받은 파일의 SHA-256이 다릅니다"))
    partial.replace(target)
    return target


def current_bundle(executable: str | Path = sys.executable) -> Path | None:
    path = Path(executable).resolve()
    return next((parent for parent in path.parents if parent.suffix == ".app"), None)


def swap_directories(new: Path, current: Path) -> Path:
    """새 폴더를 현재 자리로 옮기고, 이전 폴더는 .old로 남겨 다음 시작 때 지웁니다."""
    old = current.with_name(current.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    current.rename(old)
    new.rename(current)
    return old


def windows_install_args(installer: Path) -> list[str]:
    return [
        str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
        "/NORESTARTAPPLICATIONS", "/relaunch=1",
    ]


def relaunch_script(pid: int, command: list[str]) -> list[str]:
    """현재 프로세스가 끝난 뒤 command를 실행하는 셸 명령. 프로그램이 스스로를 다시 띄울 때 씁니다."""
    waiter = f"while kill -0 {int(pid)} 2>/dev/null; do sleep 0.5; done; exec \"$@\""
    return ["/bin/sh", "-c", waiter, "suya-relaunch", *command]


def _spawn_detached(command: list[str]) -> None:
    subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise OSError(f"{command[0]}: {detail[-1] if detail else result.returncode}")


def _install_windows(installer: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(windows_install_args(installer), close_fds=True, creationflags=flags)


def _install_macos(dmg: Path) -> None:
    bundle = current_bundle()
    if bundle is None:
        raise OSError(msg("이 설치본은 스스로 업데이트할 수 없습니다"))
    mount = Path(tempfile.mkdtemp(prefix="suya-update-"))
    _run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mount), str(dmg)])
    try:
        source = next((item for item in mount.iterdir() if item.suffix == ".app"), None)
        if source is None:
            raise OSError("no .app in the disk image")
        staged = bundle.with_name(bundle.name + ".update")
        shutil.rmtree(staged, ignore_errors=True)
        _run(["ditto", str(source), str(staged)])
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(staged)], capture_output=True)
        swap_directories(staged, bundle)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], capture_output=True)
    _spawn_detached(relaunch_script(os.getpid(), ["/usr/bin/open", "-a", str(bundle)]))


def _install_linux(archive: Path) -> None:
    folder = Path(tempfile.mkdtemp(prefix="suya-update-"))
    with tarfile.open(archive) as tar:
        tar.extractall(folder, filter="data")
    root = next((item for item in folder.iterdir() if item.is_dir()), None)
    if root is None or not (root / "install.sh").exists():
        raise OSError("install.sh not found in the archive")
    _run(["bash", str(root / "install.sh")])
    _spawn_detached(relaunch_script(os.getpid(), [str(Path.home() / ".local" / "bin" / "suya")]))


def install(path: Path, system: str = sys.platform) -> None:
    """설치를 시작합니다. 돌아온 뒤 호출한 쪽이 프로그램을 끝내면, 설치 프로그램이나 대기 셸이 새 버전을 띄웁니다."""
    if system == "win32":
        _install_windows(path)
    elif system == "darwin":
        _install_macos(path)
    else:
        _install_linux(path)


def cleanup(base: Path | None = None) -> None:
    """지난 업데이트가 남긴 설치 파일과 .old 번들을 지웁니다. 시작할 때 부릅니다."""
    folder = update_folder(base)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    bundle = current_bundle()
    if bundle is not None:
        shutil.rmtree(bundle.with_name(bundle.name + ".old"), ignore_errors=True)
