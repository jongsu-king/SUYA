"""수집을 맡은 프로그램이 언제 켜지고 꺼졌는지 남깁니다.

켤 때 시작 표시를 저장하고 끌 때 종료 시각을 더합니다. 다음에 켰을 때 종료 시각이 없으면 지난 실행이 종료 절차를
거치지 못했다는 뜻이므로, 수집이 비어 있는 구간이 왜 생겼는지 로그에서 찾을 수 있습니다.
"""

from __future__ import annotations

import json
import logging
import os

from . import __version__
from .db import Store, iso

log = logging.getLogger(__name__)


def _key(role: str) -> str:
    return f"session:{role}"


def _read(store: Store, role: str) -> dict | None:
    try:
        mark = json.loads(store.kv_get(_key(role)) or "null")
    except Exception:
        return None
    return mark if isinstance(mark, dict) else None


def _last_attempt(store: Store) -> str | None:
    """소스들이 마지막으로 수집을 시도한 시각. 지난 실행이 언제까지 살아 있었는지 가늠하는 데 씁니다."""
    try:
        attempts = [state.get("last_attempt") for state in store.source_states().values()]
    except Exception:
        return None
    return max((attempt for attempt in attempts if attempt), default=None)


def begin(store: Store, role: str) -> dict | None:
    """시작을 기록합니다. 지난 실행에 종료 기록이 없으면 그 표시를 돌려주고, 없으면 None 입니다."""
    previous = _read(store, role)
    unclean = previous if previous and not previous.get("stopped_at") else None
    log.info("프로그램 시작 (%s): 버전 %s, pid %d", role, __version__, os.getpid())
    if unclean:
        log.warning(
            "지난 실행(버전 %s, pid %s, %s 시작)의 종료 기록이 없습니다. 마지막 수집 시도: %s",
            unclean.get("version") or "?", unclean.get("pid") or "?", unclean.get("started_at") or "?",
            _last_attempt(store) or "-",
        )
    elif previous:
        log.info("지난 실행은 %s 에 종료했습니다", previous.get("stopped_at"))
    try:
        store.kv_set(_key(role), json.dumps({"started_at": iso(), "version": __version__, "pid": os.getpid()}))
    except Exception as exc:
        log.warning("시작 기록을 남기지 못했습니다: %s", exc)
    return unclean


def end(store: Store, role: str) -> None:
    """종료를 기록합니다."""
    mark = _read(store, role) or {}
    mark["stopped_at"] = iso()
    try:
        store.kv_set(_key(role), json.dumps(mark))
    except Exception as exc:
        log.warning("종료 기록을 남기지 못했습니다: %s", exc)
    log.info("프로그램 종료 (%s)", role)
