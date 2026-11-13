"""실시간 수집 엔진. 소스마다 자기 주기로 돌고, 결과를 이벤트로 내보냅니다.

- 재시작해도 저장된 next_run을 지켜서 원천 서버를 불필요하게 다시 치지 않습니다.
- 실패하면 지수적으로 빨리 재시도하되 정해진 주기를 넘기지 않습니다.
- 호출 한도에 걸리면 최소 1시간 쉽니다.
- 서버에 닿지 못한 실패는 5분 안에 다시 시도하고, 한 소스가 다시 받아 오면 같은 이유로 쉬던 소스를 바로 깨웁니다.
- 저장소가 기록을 받지 못해도 수집 루프는 멈추지 않습니다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from .collectors import JOBS
from .collectors.base import CollectResult, Context
from .db import iso, utcnow
from .i18n import is_encoded, msg, render
from .http import RateLimited, Unreachable

log = logging.getLogger(__name__)

JOB_TIMEOUT = 1800.0
JOB_TIMEOUTS = {"hycom_grid": 3600.0, "hycom_profiles": 3600.0}
BACKLOG_DELAY = 30.0
RATE_LIMIT_DELAY = 3600.0
UNREACHABLE_RETRY = 300.0
LOOP_RETRY_DELAY = 60.0
STARTUP_STAGGER = 2.0
PRUNE_EVERY = 86400.0


def job_timeout(name: str) -> float:
    """소스별 작업 시간 제한. HYCOM처럼 한 번에 많이 받는 소스는 더 깁니다."""
    return JOB_TIMEOUTS.get(name, JOB_TIMEOUT)


def failure_message(exc: BaseException, timeout: float = JOB_TIMEOUT) -> str:
    """실패 원인을 저장할 글로 만듭니다. 작업 시간 제한과 설명 없는 예외도 읽을 수 있는 글이 됩니다."""
    text = str(exc)
    if isinstance(exc, TimeoutError) and not text:
        return msg("{minutes}분 안에 끝나지 않아 중단했습니다", minutes=max(1, int(timeout // 60)))
    if is_encoded(text):
        return text
    return (f"{type(exc).__name__}: {text}" if text else type(exc).__name__)[:400]


class EventBus:
    """SSE 구독자에게 이벤트를 나눠 줍니다. 느린 구독자는 오래된 이벤트부터 버립니다."""

    def __init__(self, history: int = 100):
        self._subscribers: set[asyncio.Queue] = set()
        self.history: deque[dict] = deque(maxlen=history)

    def publish(self, event: dict) -> None:
        self.history.append(event)
        for queue in list(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[dict | None]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        try:
            while True:
                try:
                    async with asyncio.timeout(15.0):
                        event = await queue.get()
                except TimeoutError:
                    yield None
                else:
                    yield event
        finally:
            self._subscribers.discard(queue)


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Engine:
    def __init__(self, ctx: Context, bus: EventBus, sources: list[str] | None = None):
        self.ctx = ctx
        self.bus = bus
        self.sources = sources or list(JOBS)
        self.running: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self._wake: dict[str, asyncio.Event] = {name: asyncio.Event() for name in self.sources}
        self._locks: dict[str, asyncio.Lock] = {name: asyncio.Lock() for name in self.sources}
        self._failures: dict[str, int] = {}
        self._offline: set[str] = set()
        self._store_down = False
        self.started = False

    def start(self) -> None:
        self.started = True
        try:
            states = self.ctx.store.source_states()
        except Exception as exc:
            log.warning("저장된 수집 계획을 읽지 못해 바로 시작합니다: %s", render(failure_message(exc)))
            states = {}
        for index, name in enumerate(self.sources):
            self._tasks.append(asyncio.create_task(self._loop(name, index, states.get(name)), name=f"job:{name}"))
        self._tasks.append(asyncio.create_task(self._prune_loop(), name="prune"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.started = False

    def trigger(self, sources: list[str] | None = None) -> list[str]:
        """주기를 기다리지 않고 바로 수집합니다."""
        names = [n for n in (sources or self.sources) if n in self._wake]
        for name in names:
            self._wake[name].set()
        return names

    async def _loop(self, name: str, index: int, state: dict | None) -> None:
        """한 소스를 주기대로 돌립니다. 한 번의 실행이 예상하지 못한 오류로 끝나도 잠시 뒤 다시 돕니다."""
        delay = self._first_delay(index, state)
        while True:
            self._plan(name, delay)
            await self._wait(name, delay)
            try:
                delay = await self.run_once(name)
            except Exception:
                log.exception("수집 루프 오류 %s", name)
                delay = LOOP_RETRY_DELAY

    @staticmethod
    def _first_delay(index: int, state: dict | None) -> float:
        """저장된 다음 실행 시각까지 남은 시간. 시각이 없거나 지났거나 읽을 수 없으면 소스 순서대로 조금씩 띄워 시작합니다."""
        try:
            planned = parse_iso(state.get("next_run")) if state else None
        except (TypeError, ValueError):
            planned = None
        now = utcnow()
        return (planned - now).total_seconds() if planned and planned > now else index * STARTUP_STAGGER

    def _plan(self, name: str, delay: float) -> None:
        """다음 실행 시각을 저장합니다. 저장에 실패해도 수집은 이어집니다."""
        try:
            self.ctx.store.set_next_run(name, iso(utcnow() + timedelta(seconds=delay)))
        except Exception as exc:
            self._store_failed(f"다음 실행 시각 저장 {name}", exc)
        else:
            self._store_worked()

    def _store_failed(self, what: str, exc: BaseException) -> None:
        """저장 실패를 알립니다. 같은 고장이 이어지는 동안은 한 번만 경고로 남깁니다."""
        level = logging.DEBUG if self._store_down else logging.WARNING
        self._store_down = True
        log.log(level, "%s 실패: %s", what, render(failure_message(exc)))

    def _store_worked(self) -> None:
        if self._store_down:
            self._store_down = False
            log.info("저장이 다시 됩니다")

    def _error_count(self, name: str) -> int:
        """이어진 실패 횟수. 저장된 값과 이번 실행에서 센 값 중 큰 쪽이라, 저장소가 기록을 받지 못하는 동안에도 재시도 간격이 늘어납니다."""
        try:
            stored = (self.ctx.store.source_states().get(name) or {}).get("consecutive_errors") or 0
        except Exception:
            stored = 0
        return max(int(stored), self._failures.get(name, 0))

    def _track_network(self, name: str, status: str, unreachable: bool) -> None:
        """서버에 닿지 못한 소스를 기억해 두었다가, 그중 하나가 다시 받아 오면 나머지를 바로 깨웁니다."""
        if unreachable:
            self._offline.add(name)
            return
        if name not in self._offline:
            return
        self._offline.discard(name)
        if status not in ("ok", "unchanged"):
            return
        waiting = [other for other in self.sources if other in self._offline]
        self._offline.clear()
        loop = asyncio.get_running_loop()
        for index, other in enumerate(waiting):
            loop.call_later(index * STARTUP_STAGGER, self._wake[other].set)
        if waiting:
            log.info(
                "%s 수집이 다시 됩니다. 서버에 닿지 못해 쉬던 소스 %d개를 깨웁니다: %s",
                name, len(waiting), ", ".join(waiting),
            )
        else:
            log.info("%s 수집이 다시 됩니다", name)

    async def _wait(self, name: str, delay: float) -> None:
        event = self._wake[name]
        event.clear()
        try:
            async with asyncio.timeout(max(0.0, delay)):
                await event.wait()
        except TimeoutError:
            pass

    async def run_once(self, name: str) -> float:
        """작업을 한 번 실행하고 다음 실행까지의 대기 시간을 돌려줍니다."""
        interval = float(self.ctx.settings.intervals.get(name, 3600))
        timeout = job_timeout(name)
        started_at = iso()
        result = CollectResult()
        status, delay = "ok", interval
        unreachable = False
        async with self._locks.setdefault(name, asyncio.Lock()):
            self.running.add(name)
            self.bus.publish({"type": "job", "source": name, "state": "running", "at": started_at})
            try:
                async with asyncio.timeout(timeout):
                    result = await JOBS[name](self.ctx)
                if result.disabled:
                    status = "disabled"
                elif result.unchanged:
                    status = "unchanged"
                if result.backlog:
                    delay = BACKLOG_DELAY
            except asyncio.CancelledError:
                self.running.discard(name)
                raise
            except RateLimited as exc:
                status = "rate_limited"
                result.message = str(exc)
                delay = max(interval, RATE_LIMIT_DELAY)
            except Exception as exc:
                status = "error"
                unreachable = isinstance(exc, Unreachable)
                result.message = failure_message(exc, timeout)
                repeated = unreachable and name in self._offline
                log.log(
                    logging.DEBUG if repeated else logging.WARNING, "수집 실패 %s: %s", name, render(result.message)
                )
                delay = min(interval, 60.0 * 2 ** min(self._error_count(name), 8))
                if unreachable:
                    delay = min(delay, UNREACHABLE_RETRY)
            finally:
                self.running.discard(name)
        self._failures[name] = 0 if status in ("ok", "unchanged", "disabled") else self._failures.get(name, 0) + 1
        self._track_network(name, status, unreachable)
        next_run = iso(utcnow() + timedelta(seconds=delay))
        try:
            await asyncio.to_thread(
                self.ctx.store.record_run,
                name, started_at, status, result.rows, result.data_time, result.message, next_run,
            )
        except Exception as exc:
            self._store_failed(f"수집 기록 저장 {name}", exc)
        else:
            self._store_worked()
        self.bus.publish(
            {
                "type": "job",
                "source": name,
                "state": "done",
                "status": status,
                "rows": result.rows,
                "data_time": result.data_time,
                "message": result.message,
                "next_run": next_run,
                "at": iso(),
            }
        )
        return delay

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(PRUNE_EVERY)
            try:
                await asyncio.to_thread(self.ctx.store.prune)
            except Exception as exc:
                self._store_failed("오래된 기록 정리", exc)
            else:
                self._store_worked()
