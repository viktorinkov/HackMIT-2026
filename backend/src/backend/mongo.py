"""MongoDB client. Concern reports (and later GridFS photos) live here.

Scans themselves are in Elasticsearch. An empty `MONGODB_URI` leaves the
client unset so report storage can fall back to memory.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConfigurationError

from backend.config import Settings, get_settings

_client: AsyncIOMotorClient | None = None


def build_client(settings: Settings) -> AsyncIOMotorClient | None:
    uri = settings.mongodb_uri.strip()
    if not uri:
        return None
    return AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
    )


def get_mongo_client(settings: Settings = Depends(get_settings)) -> AsyncIOMotorClient | None:
    global _client
    if _client is None:
        _client = build_client(settings)
    return _client


def get_mongo_db(settings: Settings = Depends(get_settings)) -> AsyncIOMotorDatabase | None:
    client = get_mongo_client(settings)
    if client is None:
        return None
    try:
        return client.get_default_database()
    except ConfigurationError:
        return client["peel"]


async def close_mongo() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def mongo_unreachable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="MongoDB is unreachable",
    )
