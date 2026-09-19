from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Literal

from elasticsearch import ApiError, AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from fastapi import Depends

from backend.config import Settings, get_settings
from backend.drug_facts.models import DrugFactHit, DrugFactsError

SearchKind = Literal["imprint", "bottle"]

INDEX_NAME = "peel-drug-facts"
_CREATED_INFERENCE_ID = "peel-elser"
_INFERENCE_FALLBACKS = (".elser-2-elasticsearch", ".elser-2-elastic")
_MIN_CACHED_HITS = 3
_SEARCH_SIZE = 8

_store: ElasticStore | None = None


class ElasticStore:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.elasticsearch_url
        self._api_key = settings.elasticsearch_api_key
        self._client: AsyncElasticsearch | None = None
        self._ready = False
        self._lock = asyncio.Lock()

    def _es(self) -> AsyncElasticsearch:
        if not self._url or not self._api_key:
            raise DrugFactsError("Elasticsearch URL and API key are not set")
        if self._client is None:
            self._client = AsyncElasticsearch(
                self._url,
                api_key=self._api_key,
                request_timeout=120,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def cached_hits(self, kind: SearchKind, query_key: str) -> list[DrugFactHit]:
        await self.ensure_index()
        response = await self._es().search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "filter": [
                        {"term": {"search_kind": kind}},
                        {"term": {"query_key": query_key}},
                    ]
                }
            },
            size=_SEARCH_SIZE,
        )
        return _hits_from(response)

    def has_cache(self, hits: list[DrugFactHit]) -> bool:
        return len(hits) >= _MIN_CACHED_HITS

    async def upsert_chunks(
        self,
        kind: SearchKind,
        query: str,
        query_key: str,
        chunks: list[tuple[str, str | None, str]],
    ) -> None:
        await self.ensure_index()
        actions = [
            {
                "_op_type": "index",
                "_index": INDEX_NAME,
                "_id": _chunk_id(kind, url, index),
                "_source": {
                    "search_kind": kind,
                    "query": query,
                    "query_key": query_key,
                    "source_url": url,
                    "source_title": title,
                    "chunk_text": text,
                },
            }
            for index, (url, title, text) in enumerate(chunks)
        ]
        if not actions:
            return
        try:
            ok, errors = await async_bulk(
                self._es(),
                actions,
                refresh=True,
                raise_on_error=False,
            )
        except ApiError as exc:
            raise DrugFactsError(
                exc.message or "Elasticsearch failed to index drug facts"
            ) from exc
        if ok == 0:
            detail = errors[0] if errors else "no chunks accepted"
            raise DrugFactsError(f"Elasticsearch rejected drug-fact chunks: {detail}")

    async def search(self, kind: SearchKind, query: str) -> list[DrugFactHit]:
        await self.ensure_index()
        try:
            response = await self._es().search(
                index=INDEX_NAME,
                query={
                    "bool": {
                        "must": {"match": {"chunk_text": query}},
                        "filter": [{"term": {"search_kind": kind}}],
                    }
                },
                size=_SEARCH_SIZE,
            )
        except ApiError as exc:
            raise DrugFactsError(exc.message or "Elasticsearch search failed") from exc
        return _hits_from(response)

    async def ensure_index(self) -> None:
        async with self._lock:
            if self._ready:
                return
            client = self._es()
            if await client.indices.exists(index=INDEX_NAME):
                self._ready = True
                return
            errors: list[str] = []
            for inference_id in (None, *_INFERENCE_FALLBACKS):
                try:
                    await client.indices.create(
                        index=INDEX_NAME,
                        mappings=_mappings(inference_id),
                    )
                    self._ready = True
                    return
                except ApiError as exc:
                    errors.append(exc.message or str(exc))
            try:
                await client.inference.put_elser(
                    task_type="sparse_embedding",
                    elser_inference_id=_CREATED_INFERENCE_ID,
                    service="elser",
                    service_settings={"num_allocations": 1, "num_threads": 1},
                    timeout="120s",
                )
                await client.indices.create(
                    index=INDEX_NAME,
                    mappings=_mappings(_CREATED_INFERENCE_ID),
                )
                self._ready = True
            except ApiError as exc:
                joined = "; ".join(errors + [exc.message or str(exc)])
                raise DrugFactsError(
                    f"Could not create {INDEX_NAME} with semantic_text: {joined}"
                ) from exc


def get_elastic_store(settings: Settings = Depends(get_settings)) -> ElasticStore:
    global _store
    if _store is None:
        _store = ElasticStore(settings)
    return _store


async def close_elastic_store() -> None:
    global _store
    if _store is not None:
        await _store.aclose()
        _store = None


def _mappings(inference_id: str | None) -> dict[str, Any]:
    chunk_text: dict[str, Any] = {"type": "semantic_text"}
    if inference_id:
        chunk_text["inference_id"] = inference_id
    return {
        "properties": {
            "search_kind": {"type": "keyword"},
            "query": {"type": "text"},
            "query_key": {"type": "keyword"},
            "source_url": {"type": "keyword"},
            "source_title": {"type": "text"},
            "chunk_text": chunk_text,
        }
    }


def _chunk_id(kind: SearchKind, url: str, index: int) -> str:
    return hashlib.sha256(f"{kind}|{url}|{index}".encode()).hexdigest()


def _hits_from(response: Any) -> list[DrugFactHit]:
    hits: list[DrugFactHit] = []
    for hit in response["hits"]["hits"]:
        source = hit["_source"]
        passage = _passage(source)
        if not passage:
            continue
        hits.append(
            DrugFactHit(
                source_url=source["source_url"],
                source_title=source.get("source_title"),
                passage=passage,
                score=float(hit["_score"] or 0),
            )
        )
    return hits


def _passage(source: dict[str, Any]) -> str:
    value = source.get("chunk_text")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
    return ""
