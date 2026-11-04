"""화면과 수집 엔진을 잇습니다. 엔진은 별도 스레드의 asyncio 루프에서 돌고, 결과는 Qt 시그널로 넘어옵니다."""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from typing import Any, Awaitable, Callable

from PySide6.QtCore import QObject, Signal

from .. import pointquery
from ..collectors.base import Context
from ..config import Settings
from ..db import Store
from ..engine import Engine, EventBus
from ..http import Fetcher

log = logging.getLogger(__name__)


class Backend(QObject):
    event = Signal(dict)  # 수집 엔진의 진행 상황
    finished = Signal(int, object, object)  # 요청 번호, 결과, 오류

    def __init__(self, settings: Settings, collect: bool = True, sources: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.collecting = collect
        self.sources = sources
        self.store = Store(settings.db_path)
        self.cache = pointquery.TTLCache()
        self.ctx: Context | None = None
        self.engine: Engine | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hub-engine", daemon=True)
        self._ids = itertools.count(1)
        self._callbacks: dict[int, Callable[[Any, Exception | None], None]] = {}
        self.finished.connect(self._dispatch)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=10)

    def stop(self) -> None:
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=10)
        self.store.close()

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        fetcher = Fetcher()
        self.ctx = Context(self.store, fetcher, self.settings)
        bus = EventBus()
        self.engine = Engine(self.ctx, bus, self.sources)
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        relay = asyncio.create_task(self._relay(bus))
        if self.collecting:
            self.engine.start()
        self._ready.set()
        await self._stop.wait()
        relay.cancel()
        await self.engine.stop()
        await fetcher.aclose()

    async def _relay(self, bus: EventBus) -> None:
        async for event in bus.subscribe():
            if event is not None:
                self.event.emit(event)

    # ---- 요청 ----
    def call(self, factory: Callable[[], Awaitable[Any]], callback: Callable[[Any, Exception | None], None]) -> int:
        """코루틴을 엔진 스레드에서 실행하고, 결과를 화면 스레드의 callback으로 돌려줍니다."""
        request_id = next(self._ids)
        self._callbacks[request_id] = callback

        async def runner() -> None:
            try:
                result = await factory()
            except Exception as exc:  # 화면에 그대로 알립니다
                log.warning("요청 실패: %s", exc)
                self.finished.emit(request_id, None, exc)
            else:
                self.finished.emit(request_id, result, None)

        asyncio.run_coroutine_threadsafe(runner(), self._loop)
        return request_id

    def call_sync(self, function: Callable[..., Any], *args, callback: Callable[[Any, Exception | None], None]) -> int:
        """블로킹 함수(DB 조회 등)를 화면을 멈추지 않고 실행합니다."""

        async def factory():
            return await asyncio.to_thread(function, *args)

        return self.call(factory, callback)

    def _dispatch(self, request_id: int, result: Any, error: Any) -> None:
        callback = self._callbacks.pop(request_id, None)
        if callback:
            callback(result, error)

    def point(self, part: str, lat: float, lon: float, callback) -> int:
        """지점 상세 조회. 같은 지점은 캐시를 씁니다."""
        builders = {
            "air": pointquery.air, "water": pointquery.water, "profile": pointquery.profile, "series": pointquery.series,
        }
        key = (part, round(lat, 2), round(lon, 2))

        async def factory():
            return await self.cache.get(key, pointquery.TTL[part], lambda: builders[part](self.ctx, lat, lon))

        return self.call(factory, callback)

    def trigger(self, sources: list[str] | None = None) -> list[str]:
        if not (self.engine and self.engine.started):
            return []
        names = [n for n in (sources or self.engine.sources)]
        self._loop.call_soon_threadsafe(self.engine.trigger, names)
        return names

    @property
    def running(self) -> set[str]:
        return set(self.engine.running) if self.engine else set()
