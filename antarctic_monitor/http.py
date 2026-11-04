"""재시도, 호스트별 동시성 제한, 공통 오류를 담은 HTTP 계층."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"suya/{__version__} (Antarctic ocean monitor; https://github.com/jongsu-king/SUYA)"
HOST_LIMITS = {
    "erddap.ifremer.fr": 2,
    "coastwatch.pfeg.noaa.gov": 2,
    "coastwatch.noaa.gov": 2,
    "tds.hycom.org": 2,
    "ncss.hycom.org": 2,
    "www.ncei.noaa.gov": 2,
    "api.windy.com": 2,
}
DEFAULT_HOST_LIMIT = 4
RETRYABLE_STATUS = {500, 502, 503, 504}


class FetchError(Exception):
    """요청이 재시도 후에도 실패했습니다."""


class RateLimited(FetchError):
    """호출 한도에 걸렸습니다. 재시도하지 않고 다음 주기로 넘깁니다."""


class NoData(FetchError):
    """서버가 '해당 조건에 데이터 없음'이라고 답했습니다. 실패가 아닙니다."""


class Fetcher:
    def __init__(self, client: httpx.AsyncClient | None = None, retries: int = 3, backoff: float = 2.0):
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=20.0),
        )
        self._retries = retries
        self._backoff = backoff
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _semaphore(self, url: str) -> asyncio.Semaphore:
        host = urlparse(url).netloc
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(HOST_LIMITS.get(host, DEFAULT_HOST_LIMIT))
        return self._semaphores[host]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float = 60.0,
    ) -> httpx.Response:
        last_error = "알 수 없는 오류"
        for attempt in range(self._retries):
            if attempt:
                await asyncio.sleep(self._backoff * 2 ** (attempt - 1))
            try:
                async with self._semaphore(url):
                    response = await self._client.request(method, url, params=params, json=json, timeout=timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                continue
            if response.status_code == 429:
                raise RateLimited(_short_body(response) or "HTTP 429")
            if response.status_code in RETRYABLE_STATUS:
                last_error = f"HTTP {response.status_code}"
                continue
            return response
        raise FetchError(f"{urlparse(url).netloc}: {last_error}")

    async def get_text(self, url: str, *, params: dict | None = None, timeout: float = 60.0) -> str:
        response = await self.request("GET", url, params=params, timeout=timeout)
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}: {_short_body(response)}")
        return response.text

    async def get_json(self, url: str, *, params: dict | None = None, timeout: float = 60.0):
        response = await self.request("GET", url, params=params, timeout=timeout)
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}: {_short_body(response)}")
        return response.json()


def _short_body(response: httpx.Response, limit: int = 200) -> str:
    return " ".join(response.text.split())[:limit]
