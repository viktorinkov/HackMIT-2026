from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from elastic_transport import ApiResponseMeta
from elasticsearch import ApiError

from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import REPORTS_INDEX
from backend.knowledge.fields import Report as ReportFields
from backend.knowledge.indices import mappings_for
from backend.reports.models import PurchaseLocation, Report
from backend.reports.store import (
    MAX_REPORTS,
    ElasticReportStore,
    MemoryReportStore,
    document_from_report,
    report_from_document,
)


def _meta(status: int) -> ApiResponseMeta:
    return ApiResponseMeta(
        status=status, http_version="1.1", headers={}, duration=0.0, node=None
    )


class FakeEs:
    def __init__(self, **responses: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses

    async def _run(self, name: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((name, kwargs))
        value = self.responses.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    async def index(self, **kwargs: Any) -> Any:
        return await self._run("index", kwargs)

    async def search(self, **kwargs: Any) -> Any:
        return await self._run("search", kwargs)

    def call(self, name: str) -> dict[str, Any]:
        return next(kwargs for called, kwargs in self.calls if called == name)


def report(report_id: str = "rep-1", **overrides: Any) -> Report:
    fields: dict[str, Any] = {
        "report_id": report_id,
        "scan_id": "scan-1",
        "seller": "CVS Pharmacy",
        "purchased_on": date(2026, 3, 12),
        "purchase_location": PurchaseLocation(
            label="CVS on Mass Ave",
            city="Cambridge",
            region="MA",
            country="US",
            lat=42.3736,
            lon=-71.1097,
        ),
        "created_at": datetime(2026, 9, 19, 23, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return Report(**fields)


def test_mapping_is_provenance_only() -> None:
    properties = mappings_for(REPORTS_INDEX)["properties"]
    assert REPORTS_INDEX == "peel-reports"
    assert set(properties) == {
        ReportFields.REPORT_ID,
        ReportFields.SCAN_ID,
        ReportFields.PURCHASED_ON,
        ReportFields.PURCHASE_LOCATION,
        ReportFields.SELLER,
        ReportFields.CREATED_AT,
    }
    assert properties[ReportFields.SCAN_ID]["type"] == "keyword"
    assert properties[ReportFields.PURCHASED_ON]["type"] == "date"
    assert properties[ReportFields.SELLER]["type"] == "text"
    location = properties[ReportFields.PURCHASE_LOCATION]["properties"]
    assert location["coordinates"]["type"] == "geo_point"


def test_document_roundtrip_moves_coordinates() -> None:
    source = document_from_report(report())
    assert set(source) == {
        "report_id",
        "scan_id",
        "seller",
        "purchased_on",
        "purchase_location",
        "created_at",
    }
    assert source["purchased_on"] == "2026-03-12"
    assert "lat" not in source["purchase_location"]
    assert source["purchase_location"]["coordinates"] == {"lat": 42.3736, "lon": -71.1097}
    restored = report_from_document(source)
    assert restored == report()


def test_document_omits_blank_provenance() -> None:
    source = document_from_report(
        report(seller=None, purchased_on=None, purchase_location=PurchaseLocation())
    )
    assert set(source) == {"report_id", "scan_id", "created_at"}


@pytest.mark.asyncio
async def test_add_indexes_by_report_id_without_refresh() -> None:
    es = FakeEs(index={"result": "created"})
    stored = await ElasticReportStore(es).add(report())
    call = es.call("index")
    assert stored.report_id == "rep-1"
    assert call["index"] == REPORTS_INDEX
    assert call["id"] == "rep-1"
    assert call["refresh"] is False
    assert call["document"]["scan_id"] == "scan-1"


@pytest.mark.asyncio
async def test_add_surfaces_a_cluster_error_as_503() -> None:
    es = FakeEs(index=ApiError("boom", meta=_meta(500), body={}))
    with pytest.raises(KnowledgeError, match="could not store the report") as info:
        await ElasticReportStore(es).add(report())
    assert info.value.status_code == 503


@pytest.mark.asyncio
async def test_list_for_scan_filters_and_sorts_newest_first() -> None:
    newer = document_from_report(report("rep-2", created_at=datetime(2026, 9, 20, tzinfo=UTC)))
    older = document_from_report(report("rep-1"))
    es = FakeEs(search={"hits": {"hits": [{"_source": newer}, {"_source": older}]}})
    listed = await ElasticReportStore(es).list_for_scan("scan-1")
    call = es.call("search")
    assert call["index"] == REPORTS_INDEX
    assert call["query"] == {"term": {"scan_id": "scan-1"}}
    assert call["sort"] == [{"created_at": "desc"}, {"report_id": "asc"}]
    assert call["size"] == MAX_REPORTS
    assert [item.report_id for item in listed] == ["rep-2", "rep-1"]
    assert listed[1].purchase_location is not None
    assert listed[1].purchase_location.lat == 42.3736


@pytest.mark.asyncio
async def test_list_for_scan_surfaces_a_cluster_error() -> None:
    es = FakeEs(search=ApiError("boom", meta=_meta(500), body={}))
    with pytest.raises(KnowledgeError, match="could not list reports"):
        await ElasticReportStore(es).list_for_scan("scan-1")


@pytest.mark.asyncio
async def test_memory_store_lists_only_the_scan_newest_first() -> None:
    store = MemoryReportStore()
    await store.add(report("rep-1"))
    await store.add(report("rep-2", created_at=datetime(2026, 9, 20, tzinfo=UTC)))
    await store.add(report("rep-3", scan_id="scan-other"))
    listed = await store.list_for_scan("scan-1")
    assert [item.report_id for item in listed] == ["rep-2", "rep-1"]
    assert await store.list_for_scan("scan-none") == []
