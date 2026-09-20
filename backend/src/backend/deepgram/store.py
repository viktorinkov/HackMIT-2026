"""Concern reports in `peel-concern-reports`, joined to scans by `scan_id`."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from elasticsearch import ApiError, AsyncElasticsearch, TransportError
from fastapi import Depends

from backend.deepgram.models import ConcernReport, PurchaseLocation
from backend.knowledge.client import KnowledgeError, get_es
from backend.knowledge.fields import REPORTS_INDEX, Report

LIST_SIZE = 50


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


class ElasticReportStore:
    def __init__(self, es: AsyncElasticsearch) -> None:
        self._es = es

    async def add(self, report: ConcernReport) -> ConcernReport:
        with _api_errors("could not store the concern report", status_code=503):
            # No refresh wait: Serverless refresh is slow, and POST returns the
            # document immediately. GET /reports is a search and can lag.
            await self._es.index(
                index=REPORTS_INDEX,
                id=report.report_id,
                document=document_from_report(report),
                refresh=False,
            )
        return report

    async def list(self, scan_id: str) -> list[ConcernReport]:
        with _api_errors("could not list concern reports"):
            response = await self._es.search(
                index=REPORTS_INDEX,
                query={"term": {Report.SCAN_ID: scan_id}},
                sort=[{Report.CREATED_AT: {"order": "desc"}}],
                size=LIST_SIZE,
            )
        hits = response.get("hits", {}).get("hits", [])
        return [report_from_document(hit["_source"]) for hit in hits]


def get_report_store(es: AsyncElasticsearch = Depends(get_es)) -> ElasticReportStore:
    return ElasticReportStore(es)


async def close_report_store() -> None:
    return None


def document_from_report(report: ConcernReport) -> dict[str, Any]:
    doc = report.model_dump(mode="json", exclude_none=True)
    location = doc.get(Report.PURCHASE_LOCATION)
    if isinstance(location, dict):
        lat = location.pop("lat", None)
        lon = location.pop("lon", None)
        if lat is not None and lon is not None:
            location["coordinates"] = {"lat": lat, "lon": lon}
        cleaned = {key: value for key, value in location.items() if value is not None}
        if cleaned:
            doc[Report.PURCHASE_LOCATION] = cleaned
        else:
            doc.pop(Report.PURCHASE_LOCATION, None)
    return doc


def report_from_document(source: dict[str, Any]) -> ConcernReport:
    doc = dict(source)
    location = doc.get(Report.PURCHASE_LOCATION)
    if isinstance(location, dict):
        coords = location.get("coordinates") or {}
        doc[Report.PURCHASE_LOCATION] = PurchaseLocation(
            label=location.get("label"),
            city=location.get("city"),
            region=location.get("region"),
            country=location.get("country"),
            lat=coords.get("lat"),
            lon=coords.get("lon"),
        )
    return ConcernReport.model_validate(doc)


def _wrapped(message: str, exc: ApiError) -> KnowledgeError:
    return KnowledgeError(f"{message}: {exc.message}", status_code=502)


def _unreachable(message: str, exc: TransportError) -> KnowledgeError:
    return KnowledgeError(
        f"{message}: Elasticsearch is unreachable ({type(exc).__name__})",
        status_code=503,
    )


@contextmanager
def _api_errors(message: str, status_code: int = 502) -> Iterator[None]:
    try:
        yield
    except ApiError as exc:
        raise KnowledgeError(f"{message}: {exc.message}", status_code=status_code) from exc
    except TransportError as exc:
        raise _unreachable(message, exc) from exc
