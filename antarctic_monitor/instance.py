"""같은 데이터 폴더로 프로그램이 두 번 돌지 않게 합니다. 두 번째 실행은 같은 수집을 두 배로 할 뿐입니다.

창이 있는 설치본은 Qt의 QLockFile을, 화면 구성 요소 없이 설치한 서버용 복사본은 운영체제의 파일 잠금을 씁니다.
둘 다 프로세스가 죽으면 잠금이 풀리므로 남은 파일이 다음 실행을 막지 않습니다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QLockFile
except ImportError:
    QLockFile = None

LOCK_NAME = "suya.lock"


class _FileLock:
    """fcntl(POSIX) 또는 msvcrt(Windows)로 suya.lock의 첫 바이트를 잠급니다."""

    def __init__(self, path: Path):
        self._path = path
        self._handle = None

    def acquire(self) -> bool:
        handle = open(self._path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._handle.close()
        self._handle = None


class InstanceLock:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / LOCK_NAME
        if QLockFile is None:
            self._lock = _FileLock(path)
        else:
            self._lock = QLockFile(str(path))
            self._lock.setStaleLockTime(0)

    def acquire(self) -> bool:
        if isinstance(self._lock, _FileLock):
            return self._lock.acquire()
        return self._lock.tryLock(200)

    def release(self) -> None:
        if isinstance(self._lock, _FileLock):
            self._lock.release()
        elif self._lock.isLocked():
            self._lock.unlock()
