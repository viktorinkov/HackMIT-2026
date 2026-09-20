from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from elastic_transport import ApiResponseMeta
from elasticsearch import ApiError, NotFoundError, TransportError

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


def _not_found() -> NotFoundError:
    return NotFoundError("missing", meta=_meta(404), body={})


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

    async def get(self, **kwargs: Any) -> Any:
        return await self._run("get", kwargs)

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
    assert REPORTS_INDEX == "peel-reports"
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
async def test_add_indexes_by_scan_id_without_refresh() -> None:
    es = FakeEs(get=_not_found(), index={"result": "created"})
    stored = await ElasticReportStore(es).add(report())
    call = es.call("index")
    assert stored.report_id == "rep-1"
    assert call["index"] == REPORTS_INDEX
    assert call["id"] == "scan-1"
    assert call["refresh"] is False
    assert call["document"][Report.SCAN_ID] == "scan-1"


@pytest.mark.asyncio
async def test_add_replaces_the_document_for_the_same_scan() -> None:
    existing = document_from_report(report())
    es = FakeEs(get={"_source": existing}, index={"result": "updated"})
    incoming = report().model_copy(update={"seller": "a friend", "report_id": "rep-new"})
    stored = await ElasticReportStore(es).add(incoming)
    assert stored.report_id == "rep-1"
    assert stored.created_at == report().created_at
    assert stored.seller == "a friend"
    assert es.call("index")["id"] == "scan-1"


@pytest.mark.asyncio
async def test_get_is_realtime() -> None:
    es = FakeEs(get={"_source": document_from_report(report())})
    found = await ElasticReportStore(es).get("scan-1")
    assert found is not None
    assert found.seller == "CVS Pharmacy"
    assert es.call("get") == {"index": REPORTS_INDEX, "id": "scan-1", "realtime": True}


@pytest.mark.asyncio
async def test_get_returns_none_when_missing() -> None:
    es = FakeEs(get=_not_found())
    assert await ElasticReportStore(es).get("scan-1") is None


@pytest.mark.asyncio
async def test_add_surfaces_a_cluster_error() -> None:
    es = FakeEs(get=_not_found(), index=ApiError("boom", meta=_meta(500), body={}))
    with pytest.raises(KnowledgeError, match="could not store the report"):
        await ElasticReportStore(es).add(report())


@pytest.mark.asyncio
async def test_get_surfaces_an_unreachable_cluster() -> None:
    es = FakeEs(get=TransportError("timeout"))
    with pytest.raises(KnowledgeError, match="unreachable"):
        await ElasticReportStore(es).get("scan-1")
