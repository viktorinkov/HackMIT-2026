from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from itertools import islice
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from backend.knowledge.indices import mapped_fields

# semantic_text runs inference inside the bulk request, so keep those chunks small.
SEMANTIC_CHUNK = 100
KEYWORD_CHUNK = 2000
_MAX_ERRORS_KEPT = 25


@dataclass
class BulkResult:
    index: str
    indexed: int = 0
    failed: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.indexed / self.seconds if self.seconds else 0.0


class UnmappedFieldError(ValueError):
    pass


def _chunks(items: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    iterator = iter(items)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _action(index: str, doc: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    source = {key: value for key, value in doc.items() if key != "_id" and value is not None}
    unknown = set(source) - allowed
    if unknown:
        # Strict mappings would reject the whole document; fail with a useful message.
        raise UnmappedFieldError(f"{index}: unmapped fields {sorted(unknown)} in doc {doc.get('_id')!r}")
    return {"_op_type": "index", "_index": index, "_id": doc["_id"], "_source": source}


async def bulk_index(
    es: AsyncElasticsearch,
    index: str,
    docs: Iterable[dict[str, Any]],
    *,
    semantic: bool,
    chunk_size: int | None = None,
    workers: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
) -> BulkResult:
    """Index docs with deterministic ids (re-runs converge). Errors are counted
    and surfaced, never swallowed."""
    size = chunk_size or (SEMANTIC_CHUNK if semantic else KEYWORD_CHUNK)
    allowed = mapped_fields(index)
    result = BulkResult(index=index)
    semaphore = asyncio.Semaphore(workers)
    started = time.monotonic()

    async def send(chunk: list[dict[str, Any]]) -> None:
        actions = [_action(index, doc, allowed) for doc in chunk]
        async with semaphore:
            ok, errors = await async_bulk(
                es.options(request_timeout=300),
                actions,
                chunk_size=len(actions),
                max_retries=5,
                initial_backoff=2,
                max_backoff=60,
                raise_on_error=False,
                raise_on_exception=False,
            )
        result.indexed += ok
        failures = errors if isinstance(errors, list) else []
        result.failed += len(failures)
        for item in failures[: _MAX_ERRORS_KEPT - len(result.errors)]:
            result.errors.append(str(item)[:500])
        if on_progress:
            on_progress(result.indexed, result.failed)

    pending: set[asyncio.Task[None]] = set()
    for chunk in _chunks(docs, size):
        pending.add(asyncio.create_task(send(chunk)))
        if len(pending) >= workers * 2:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    for task in asyncio.as_completed(pending):
        await task

    result.seconds = time.monotonic() - started
    return result
