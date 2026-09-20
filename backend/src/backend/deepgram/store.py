"""Concern reports. Mongo when `MONGODB_URI` is set, memory otherwise."""

from __future__ import annotations

from typing import Protocol

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from backend.config import Settings, get_settings
from backend.deepgram.models import ConcernReport
from backend.mongo import close_mongo, get_mongo_client, get_mongo_db, mongo_unreachable

CONCERN_REPORTS = "concern_reports"

_store: "ReportStore | None" = None


class ReportStore(Protocol):
    async def add(self, report: ConcernReport) -> ConcernReport: ...
    async def list(self, scan_id: str) -> list[ConcernReport]: ...


class MemoryReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, list[ConcernReport]] = {}

    async def add(self, report: ConcernReport) -> ConcernReport:
        self._reports.setdefault(report.scan_id, []).append(report)
        return report

    async def list(self, scan_id: str) -> list[ConcernReport]:
        return list(reversed(self._reports.get(scan_id, [])))


class MongoReportStore:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self._db = database

    async def ensure_indexes(self) -> None:
        await self._db[CONCERN_REPORTS].create_index([("scan_id", 1), ("created_at", -1)])

    async def add(self, report: ConcernReport) -> ConcernReport:
        await self._db[CONCERN_REPORTS].insert_one(report.model_dump(mode="json"))
        return report

    async def list(self, scan_id: str) -> list[ConcernReport]:
        cursor = (
            self._db[CONCERN_REPORTS]
            .find({"scan_id": scan_id}, {"_id": 0})
            .sort("created_at", -1)
        )
        return [ConcernReport.model_validate(doc) async for doc in cursor]


async def get_report_store(settings: Settings = Depends(get_settings)) -> ReportStore:
    global _store
    if _store is not None:
        return _store
    database = get_mongo_db(settings)
    if database is None:
        _store = MemoryReportStore()
        return _store
    mongo = MongoReportStore(database)
    client = get_mongo_client(settings)
    try:
        assert client is not None
        await client.admin.command("ping")
        await mongo.ensure_indexes()
    except PyMongoError as exc:
        await close_mongo()
        raise mongo_unreachable() from exc
    _store = mongo
    return _store


async def close_report_store() -> None:
    global _store
    _store = None
