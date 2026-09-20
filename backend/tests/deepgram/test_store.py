from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from elastic_transport import ApiResponseMeta
from elasticsearch import ApiError, TransportError

from backend.deepgram.models import ConcernReport, PurchaseLocation
from backend.deepgram.store import (
    ElasticReportStore,
    document_from_report,
    report_from_document,
)
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import REPORTS_INDEX, Report
from backend.knowledge.indices import mappings_for


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


def report() -> ConcernReport:
    return ConcernReport(
        report_id="rep-1",
        scan_id="scan-1",
        concern_type="mismatch",
        summary="The names do not match.",
        user_description="Bottle and imprint disagree.",
        seller="CVS Pharmacy",
        purchased_on=date(2026, 3, 12),
        purchase_location=PurchaseLocation(
            label="CVS on Mass Ave",
            city="Cambridge",
            region="MA",
            country="US",
            lat=42.3736,
            lon=-71.1097,
        ),
        snapshot={"scan_id": "scan-1"},
        created_at=datetime(2026, 9, 19, 23, 0, tzinfo=UTC),
    )


def test_mapping_uses_date_geo_and_text() -> None:
    properties = mappings_for(REPORTS_INDEX)["properties"]
    assert set(properties) == {
        Report.REPORT_ID,
        Report.SCAN_ID,
        Report.CONCERN_TYPE,
        Report.SUMMARY,
        Report.USER_DESCRIPTION,
        Report.SELLER,
        Report.PURCHASED_ON,
        Report.PURCHASE_LOCATION,
        Report.SNAPSHOT,
        Report.CREATED_AT,
    }
    assert properties[Report.SCAN_ID]["type"] == "keyword"
    assert properties[Report.PURCHASED_ON]["type"] == "date"
    assert properties[Report.SELLER]["type"] == "text"
    assert properties[Report.PURCHASE_LOCATION]["properties"]["coordinates"]["type"] == "geo_point"
    assert properties[Report.SNAPSHOT]["enabled"] is False


def test_document_roundtrip_moves_coordinates() -> None:
    source = document_from_report(report())
    assert source[Report.SCAN_ID] == "scan-1"
    assert source[Report.PURCHASED_ON] == "2026-03-12"
    assert source[Report.SELLER] == "CVS Pharmacy"
    assert "lat" not in source[Report.PURCHASE_LOCATION]
    assert source[Report.PURCHASE_LOCATION]["coordinates"] == {
        "lat": 42.3736,
        "lon": -71.1097,
    }
    restored = report_from_document(source)
    assert restored.purchased_on == date(2026, 3, 12)
    assert restored.purchase_location is not None
    assert restored.purchase_location.lat == 42.3736
    assert restored.purchase_location.label == "CVS on Mass Ave"


@pytest.mark.asyncio
async def test_add_indexes_without_refresh() -> None:
    es = FakeEs(index={"result": "created"})
    stored = await ElasticReportStore(es).add(report())
    call = es.call("index")
    assert stored.report_id == "rep-1"
    assert call["index"] == REPORTS_INDEX
    assert call["id"] == "rep-1"
    assert call["refresh"] is False
    assert call["document"][Report.SCAN_ID] == "scan-1"


@pytest.mark.asyncio
async def test_list_searches_by_scan_id() -> None:
    es = FakeEs(
        search={"hits": {"hits": [{"_source": document_from_report(report())}]}}
    )
    listed = await ElasticReportStore(es).list("scan-1")
    call = es.call("search")
    assert call["index"] == REPORTS_INDEX
    assert call["query"] == {"term": {Report.SCAN_ID: "scan-1"}}
    assert listed[0].report_id == "rep-1"
    assert listed[0].seller == "CVS Pharmacy"


@pytest.mark.asyncio
async def test_add_surfaces_a_cluster_error() -> None:
    es = FakeEs(
        index=ApiError("boom", meta=_meta(500), body={}),
    )
    with pytest.raises(KnowledgeError, match="could not store the concern report"):
        await ElasticReportStore(es).add(report())


@pytest.mark.asyncio
async def test_list_surfaces_an_unreachable_cluster() -> None:
    es = FakeEs(search=TransportError("timeout"))
    with pytest.raises(KnowledgeError, match="unreachable"):
        await ElasticReportStore(es).list("scan-1")
