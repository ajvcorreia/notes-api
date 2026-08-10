"""Shared cache of every item's parsed fields, used by /search and
/notebooks - the two endpoints that need to look at the whole library
rather than one item.

Joplin Server has no metadata-listing or search endpoint, so answering
either of those means downloading and parsing every item's raw content.
Fetching is I/O-bound and already runs concurrently; parsing is CPU-bound
and was previously done inline on the event loop, one item at a time, on a
single core. This module fixes both: fetches stay concurrent via asyncio,
parsing is spread across a process pool so it actually uses multiple
cores, and the result is cached for `settings.item_cache_ttl_seconds` so
repeated calls don't redo either at all.
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ProcessPoolExecutor

from .config import settings
from .joplin_client import JoplinNotFound, joplin_client
from .note_format import parse_item

_FETCH_CONCURRENCY = 20

_cache: list[dict[str, str]] | None = None
_cache_time: float = 0.0
_refresh_lock = asyncio.Lock()
_pool: ProcessPoolExecutor | None = None


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor()
    return _pool


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def invalidate() -> None:
    global _cache, _cache_time
    _cache = None
    _cache_time = 0.0


async def _fetch_all_raw_content() -> list[str]:
    ids = await joplin_client.list_all_item_names()
    semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def fetch(item_id: str) -> str | None:
        async with semaphore:
            try:
                return await joplin_client.get_content(item_id)
            except JoplinNotFound:
                return None

    results = await asyncio.gather(*(fetch(item_id) for item_id in ids))
    return [content for content in results if content is not None]


async def get_all_fields() -> list[dict[str, str]]:
    global _cache, _cache_time
    if _cache is not None and (time.monotonic() - _cache_time) < settings.item_cache_ttl_seconds:
        return _cache

    async with _refresh_lock:
        if _cache is not None and (time.monotonic() - _cache_time) < settings.item_cache_ttl_seconds:
            return _cache

        raw_contents = await _fetch_all_raw_content()
        loop = asyncio.get_running_loop()
        pool = _get_pool()
        parsed = await asyncio.gather(
            *(loop.run_in_executor(pool, parse_item, content) for content in raw_contents)
        )
        _cache = list(parsed)
        _cache_time = time.monotonic()
        return _cache
