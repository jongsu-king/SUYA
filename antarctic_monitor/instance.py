"""같은 데이터 폴더로 프로그램이 두 번 돌지 않게 합니다. 두 번째 실행은 같은 수집을 두 배로 할 뿐입니다."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class InstanceLock:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(folder / "suya.lock"))
        self._lock.setStaleLockTime(0)

    def acquire(self) -> bool:
        return self._lock.tryLock(200)

    def release(self) -> None:
        if self._lock.isLocked():
            self._lock.unlock()
