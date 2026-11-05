"""실시간 수집 엔진. 소스마다 자기 주기로 돌고, 결과를 이벤트로 내보냅니다.

- 재시작해도 저장된 next_run을 지켜서 원천 서버를 불필요하게 다시 치지 않습니다.
- 실패하면 지수적으로 빨리 재시도하되 정해진 주기를 넘기지 않습니다.
- 호출 한도에 걸리면 최소 1시간 쉽니다.
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
from .i18n import is_encoded, render
from .http import RateLimited

log = logging.getLogger(__name__)

JOB_TIMEOUT = 1800.0
BACKLOG_DELAY = 30.0
RATE_LIMIT_DELAY = 3600.0
STARTUP_STAGGER = 2.0
PRUNE_EVERY = 86400.0


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
                    yield await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield None
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
        self.started = False

    def start(self) -> None:
        self.started = True
        states = self.ctx.store.source_states()
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
        now = utcnow()
        planned = parse_iso(state.get("next_run")) if state else None
        delay = (planned - now).total_seconds() if planned and planned > now else index * STARTUP_STAGGER
        while True:
            self.ctx.store.set_next_run(name, iso(utcnow() + timedelta(seconds=delay)))
            await self._wait(name, delay)
            delay = await self.run_once(name)

    async def _wait(self, name: str, delay: float) -> None:
        event = self._wake[name]
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=max(0.0, delay))
        except asyncio.TimeoutError:
            pass

    async def run_once(self, name: str) -> float:
        """작업을 한 번 실행하고 다음 실행까지의 대기 시간을 돌려줍니다."""
        interval = float(self.ctx.settings.intervals.get(name, 3600))
        started_at = iso()
        result = CollectResult()
        status, delay = "ok", interval
        async with self._locks.setdefault(name, asyncio.Lock()):
            self.running.add(name)
            self.bus.publish({"type": "job", "source": name, "state": "running", "at": started_at})
            try:
                result = await asyncio.wait_for(JOBS[name](self.ctx), timeout=JOB_TIMEOUT)
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
                result.message = str(exc) if is_encoded(str(exc)) else f"{type(exc).__name__}: {exc}"[:400]
                log.warning("수집 실패 %s: %s", name, render(result.message))
                errors = (self.ctx.store.source_states().get(name) or {}).get("consecutive_errors") or 0
                delay = min(interval, 60.0 * 2 ** min(errors, 8))
            finally:
                self.running.discard(name)
        next_run = iso(utcnow() + timedelta(seconds=delay))
        await asyncio.to_thread(
            self.ctx.store.record_run,
            name, started_at, status, result.rows, result.data_time, result.message, next_run,
        )
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
            await asyncio.to_thread(self.ctx.store.prune)
