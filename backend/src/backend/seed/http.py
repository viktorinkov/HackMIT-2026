from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

import httpx

T = TypeVar("T")
R = TypeVar("R")

USER_AGENT = "peel-seed/0.1 (HackMIT 2026 student project; medicine-safety research)"
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


def build_http(concurrency: int = 8) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=httpx.Timeout(connect=15, read=120, write=30, pool=30),
        limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency),
        follow_redirects=True,
    )


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 4,
) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                return response
            if response.status_code not in _RETRY_STATUS:
                raise FetchError(f"GET {url} -> HTTP {response.status_code}")
            last = FetchError(f"GET {url} -> HTTP {response.status_code}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
        await asyncio.sleep(min(2**attempt * 1.5, 20))
    raise FetchError(f"GET {url} failed after {attempts} attempts: {last}")


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
) -> Any:
    response = await get_with_retry(client, url, params=params, headers={"Accept": "application/json"})
    return response.json()


async def download_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    refresh: bool = False,
) -> Path:
    """Stream to disk; a non-empty cached file is reused unless refresh."""
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    async with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise FetchError(f"GET {url} -> HTTP {response.status_code}")
        with partial.open("wb") as handle:
            async for chunk in response.aiter_bytes(1 << 16):
                handle.write(chunk)
    partial.replace(dest)
    return dest


async def map_limited(
    items: Iterable[T],
    worker: Callable[[T], Awaitable[R]],
    concurrency: int = 8,
) -> list[R | None]:
    """Run worker over items with bounded concurrency. A failed item yields None
    so one bad page never sinks a whole source."""
    semaphore = asyncio.Semaphore(concurrency)

    async def run(item: T) -> R | None:
        async with semaphore:
            try:
                return await worker(item)
            except Exception:
                return None

    return list(await asyncio.gather(*(run(item) for item in items)))
