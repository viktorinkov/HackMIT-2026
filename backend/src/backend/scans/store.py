from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from fastapi import Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConfigurationError, PyMongoError

from backend.config import Settings, get_settings
from backend.scans.models import (
    BottleChannel,
    ConcernReport,
    ImprintChannel,
    PillChannel,
    ScanReport,
)

SCANS = "scans"
BOTTLE_FACTS = "bottle_facts"
IMPRINT_FACTS = "imprint_facts"
PILL_FACTS = "pill_facts"
CONCERN_REPORTS = "concern_reports"


def _now() -> datetime:
    return datetime.now(UTC)


class ScanStore(Protocol):
    async def create(self, report: ScanReport) -> ScanReport: ...
    async def get(self, scan_id: str) -> ScanReport | None: ...
    async def save(self, report: ScanReport) -> ScanReport: ...
    async def add_concern_report(self, report: ConcernReport) -> ConcernReport: ...
    async def list_concern_reports(self, scan_id: str) -> list[ConcernReport]: ...
    async def close(self) -> None: ...


class MemoryScanStore:
    def __init__(self) -> None:
        self._scans: dict[str, ScanReport] = {}
        self._reports: dict[str, list[ConcernReport]] = {}

    async def create(self, report: ScanReport) -> ScanReport:
        stamped = report.model_copy(
            update={"created_at": _now(), "updated_at": _now()}
        )
        self._scans[stamped.scan_id] = stamped
        return stamped

    async def get(self, scan_id: str) -> ScanReport | None:
        report = self._scans.get(scan_id)
        return report.model_copy(deep=True) if report else None

    async def save(self, report: ScanReport) -> ScanReport:
        existing = self._scans.get(report.scan_id)
        created = existing.created_at if existing else _now()
        stamped = report.model_copy(update={"created_at": created, "updated_at": _now()})
        self._scans[stamped.scan_id] = stamped
        return stamped

    async def add_concern_report(self, report: ConcernReport) -> ConcernReport:
        self._reports.setdefault(report.scan_id, []).append(report)
        return report

    async def list_concern_reports(self, scan_id: str) -> list[ConcernReport]:
        return list(reversed(self._reports.get(scan_id, [])))

    async def close(self) -> None:
        return None


class MongoScanStore:
    def __init__(self, database: AsyncIOMotorDatabase, client: AsyncIOMotorClient) -> None:
        self._db = database
        self._client = client

    async def ensure_indexes(self) -> None:
        await self._db[SCANS].create_index("scan_id", unique=True)
        await self._db[BOTTLE_FACTS].create_index("scan_id", unique=True)
        await self._db[IMPRINT_FACTS].create_index("scan_id", unique=True)
        await self._db[PILL_FACTS].create_index("scan_id", unique=True)
        await self._db[CONCERN_REPORTS].create_index([("scan_id", 1), ("created_at", -1)])

    async def create(self, report: ScanReport) -> ScanReport:
        return await self.save(report)

    async def get(self, scan_id: str) -> ScanReport | None:
        scan = await self._db[SCANS].find_one({"scan_id": scan_id}, {"_id": 0})
        if scan is None:
            return None
        bottle_doc = await self._db[BOTTLE_FACTS].find_one({"scan_id": scan_id}, {"_id": 0, "scan_id": 0})
        imprint_doc = await self._db[IMPRINT_FACTS].find_one({"scan_id": scan_id}, {"_id": 0, "scan_id": 0})
        pill_doc = await self._db[PILL_FACTS].find_one({"scan_id": scan_id}, {"_id": 0, "scan_id": 0})
        return ScanReport(
            scan_id=scan["scan_id"],
            status=scan["status"],
            demo=scan.get("demo", False),
            finding=scan.get("finding"),
            bottle=BottleChannel.model_validate(bottle_doc) if bottle_doc else None,
            imprint=ImprintChannel.model_validate(imprint_doc) if imprint_doc else None,
            pill=PillChannel.model_validate(pill_doc) if pill_doc else None,
            created_at=scan.get("created_at"),
            updated_at=scan.get("updated_at"),
        )

    async def save(self, report: ScanReport) -> ScanReport:
        now = _now()
        existing = await self._db[SCANS].find_one({"scan_id": report.scan_id})
        created = existing.get("created_at") if existing else now
        await self._db[SCANS].update_one(
            {"scan_id": report.scan_id},
            {
                "$set": {
                    "scan_id": report.scan_id,
                    "status": report.status,
                    "demo": report.demo,
                    "finding": report.finding,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": created},
            },
            upsert=True,
        )
        if report.bottle is not None:
            await self._db[BOTTLE_FACTS].update_one(
                {"scan_id": report.scan_id},
                {"$set": {"scan_id": report.scan_id, **report.bottle.model_dump(mode="json")}},
                upsert=True,
            )
        if report.imprint is not None:
            await self._db[IMPRINT_FACTS].update_one(
                {"scan_id": report.scan_id},
                {"$set": {"scan_id": report.scan_id, **report.imprint.model_dump(mode="json")}},
                upsert=True,
            )
        if report.pill is not None:
            await self._db[PILL_FACTS].update_one(
                {"scan_id": report.scan_id},
                {"$set": {"scan_id": report.scan_id, **report.pill.model_dump(mode="json")}},
                upsert=True,
            )
        saved = await self.get(report.scan_id)
        if saved is None:
            raise RuntimeError(f"Failed to reload scan {report.scan_id}")
        return saved

    async def add_concern_report(self, report: ConcernReport) -> ConcernReport:
        await self._db[CONCERN_REPORTS].insert_one(report.model_dump(mode="json"))
        return report

    async def list_concern_reports(self, scan_id: str) -> list[ConcernReport]:
        cursor = (
            self._db[CONCERN_REPORTS]
            .find({"scan_id": scan_id}, {"_id": 0})
            .sort("created_at", -1)
        )
        return [ConcernReport.model_validate(doc) async for doc in cursor]

    async def close(self) -> None:
        self._client.close()


_store: ScanStore | None = None


async def connect_scan_store(settings: Settings) -> ScanStore:
    uri = settings.mongodb_uri.strip()
    if not uri:
        return MemoryScanStore()
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
    )
    try:
        database = client.get_default_database()
    except ConfigurationError:
        database = client["peel"]
    mongo = MongoScanStore(database, client)
    try:
        await client.admin.command("ping")
        await mongo.ensure_indexes()
    except PyMongoError as exc:
        await mongo.close()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="MongoDB is unreachable",
        ) from exc
    return mongo


async def get_scan_store(settings: Settings = Depends(get_settings)) -> ScanStore:
    global _store
    if _store is not None:
        return _store
    _store = await connect_scan_store(settings)
    return _store


async def close_scan_store() -> None:
    global _store
    if _store is not None:
        await _store.close()
        _store = None
