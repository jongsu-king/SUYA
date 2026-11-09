"""환경 변수, .env, 사용자 설정 파일에서 설정을 읽습니다."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_FOLDER = "SUYA"
SETTINGS_FILE = "settings.env"

DEFAULT_INTERVALS = {
    "metar": 300,
    "openmeteo_current": 900,
    "openmeteo_marine": 1800,
    "openmeteo_forecast": 10800,
    "gfs_grid": 10800,
    "oisst": 21600,
    "smos": 21600,
    "smap": 21600,
    "hycom_grid": 10800,
    "hycom_profiles": 86400,
    "argo": 3600,
    "gosud": 3600,
    "windy": 10800,
    "excel": 900,
}


def app_data_dir() -> Path:
    """설치판은 현재 폴더에 쓸 수 없으므로 사용자별 폴더에 저장합니다."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_FOLDER
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_FOLDER


def default_excel_dir() -> Path:
    return Path.home() / "Documents" / APP_FOLDER


def use_persistent_matplotlib_cache(base: Path | None = None) -> Path | None:
    """설치판에서 matplotlib 글꼴 캐시를 사용자 데이터 폴더에 두어 실행할 때마다 다시 만들지 않게 합니다.

    matplotlib를 import하기 전에 불러야 합니다.
    """
    directory = (base or app_data_dir()) / "matplotlib"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    os.environ["MPLCONFIGDIR"] = str(directory)
    return directory


def load_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE 형식만 읽는 최소 파서."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def save_user_settings(updates: dict[str, str], directory: Path | None = None) -> Path:
    """설정 창에서 바꾼 값을 저장합니다. API 키가 들어가므로 소유자만 읽게 합니다."""
    folder = directory or app_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SETTINGS_FILE
    values = load_dotenv(path)
    values.update(updates)
    text = "".join(f"{key}={value}\n" for key, value in values.items() if value != "")
    path.write_text(text, encoding="utf-8")
    if sys.platform != "win32":
        path.chmod(0o600)
    return path


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: app_data_dir() / "antarctic.db")
    excel_dir: Path = field(default_factory=default_excel_dir)
    windy_api_key: str | None = None
    windy_key_tier: str = "testing"
    windy_models: tuple[str, ...] = ("gfs",)
    openmeteo_daily_budget: int = 9000
    intervals: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_INTERVALS))
    update_mode: str = "auto"

    @property
    def windy_configured(self) -> bool:
        return bool(self.windy_api_key)

    @property
    def windy_is_testing(self) -> bool:
        return self.windy_key_tier != "professional"


def load_settings(env_file: Path | None = None, user_dir: Path | None = None) -> Settings:
    """우선순위: 환경 변수 > 현재 폴더의 .env > 사용자 설정 파일."""
    user_values = load_dotenv((user_dir or app_data_dir()) / SETTINGS_FILE)
    file_values = load_dotenv(env_file or Path(".env"))

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or file_values.get(key) or user_values.get(key) or default

    intervals = dict(DEFAULT_INTERVALS)
    for name in intervals:
        override = get(f"MONITOR_INTERVAL_{name.upper()}")
        if override:
            intervals[name] = max(30, int(override))

    db_path = get("MONITOR_DB_PATH")
    excel_dir = get("MONITOR_EXCEL_DIR")
    update_mode = get("MONITOR_UPDATE_MODE", "auto").lower()
    if update_mode not in ("off", "notify", "auto"):
        update_mode = "auto"
    return Settings(
        db_path=Path(db_path) if db_path else app_data_dir() / "antarctic.db",
        excel_dir=Path(excel_dir) if excel_dir else default_excel_dir(),
        windy_api_key=get("WINDY_API_KEY") or None,
        windy_key_tier=get("WINDY_KEY_TIER", "testing").lower(),
        windy_models=tuple(m.strip() for m in get("WINDY_MODELS", "gfs").split(",") if m.strip()),
        openmeteo_daily_budget=int(get("MONITOR_OPENMETEO_DAILY_BUDGET", "9000")),
        intervals=intervals,
        update_mode=update_mode,
    )
