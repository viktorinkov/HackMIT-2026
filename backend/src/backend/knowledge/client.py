from __future__ import annotations

from elasticsearch import AsyncElasticsearch
from fastapi import Depends

from backend.config import Settings, get_settings

_client: AsyncElasticsearch | None = None


class KnowledgeError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def build_client(settings: Settings, request_timeout: float = 120) -> AsyncElasticsearch:
    if not settings.elasticsearch_url or not settings.elasticsearch_api_key:
        raise KnowledgeError("Elasticsearch URL and API key are not set", status_code=503)
    return AsyncElasticsearch(
        settings.elasticsearch_url.rstrip("/"),
        api_key=settings.elasticsearch_api_key,
        request_timeout=request_timeout,
        retry_on_timeout=True,
        max_retries=3,
        # A scan indexes pages, polls and searches concurrently; the default pool of
        # 10 starves pollers and surfaces as ConnectionTimeout.
        connections_per_node=32,
    )


def get_es(settings: Settings = Depends(get_settings)) -> AsyncElasticsearch:
    global _client
    if _client is None:
        _client = build_client(settings)
    return _client


async def close_es() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
