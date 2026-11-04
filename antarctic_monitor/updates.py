"""GitHub 릴리스로 새 버전을 확인하고, 설치판이면 이 OS용 설치 파일을 받아 검증·설치·재시작합니다.

pip로 설치한 경우는 내려받기 페이지만 안내합니다.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

from . import __url__, __version__
from .config import app_data_dir
from .http import FetchError, Fetcher
from .i18n import msg

RELEASES_API = "https://api.github.com/repos/jongsu-king/SUYA/releases/latest"
RELEASES_PAGE = f"{__url__}/releases/latest"
CHECKSUMS = "SHA256SUMS.txt"
MODES = ("off", "notify", "auto")
DEFAULT_MODE = "notify"


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


async def latest_release(fetcher: Fetcher, system: str = sys.platform, machine: str = platform.machine()) -> dict:
    data = await fetcher.get_json(RELEASES_API, timeout=20.0, interactive=True)
    tag = str(data.get("tag_name") or "")
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


async def download(
    fetcher: Fetcher, release: dict, folder: Path | None = None, progress: Callable[[int, int], None] | None = None,
) -> Path:
    """설치 파일을 받아 릴리스의 SHA-256 목록과 대조합니다. 맞지 않으면 지우고 실패로 처리합니다."""
    asset = release.get("asset")
    if not asset:
        raise FetchError(msg("이 운영체제용 설치 파일이 릴리스에 없습니다"))
    folder = update_folder(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for leftover in folder.iterdir():
        if leftover.is_file():
            leftover.unlink(missing_ok=True)
    expected = None
    if release.get("checksums"):
        expected = parse_checksums(await fetcher.get_text(release["checksums"], timeout=30.0, interactive=True)).get(asset["name"])
    target = folder / asset["name"]
    partial = target.with_name(target.name + ".part")
    await fetcher.download(asset["url"], partial, progress=progress)
    if expected and sha256_of(partial) != expected:
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
