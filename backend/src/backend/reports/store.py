"""Reads and writes for `peel-reports`."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from elasticsearch import ApiError, AsyncElasticsearch, TransportError
from fastapi import Depends

from backend.knowledge.client import KnowledgeError, get_es
from backend.knowledge.fields import REPORTS_INDEX
from backend.knowledge.fields import Report as ReportFields
from backend.reports.models import PurchaseLocation, Report

# A scan collects a handful of reports at most; no cursor needed.
MAX_REPORTS = 100


class ReportStore(Protocol):
    async def add(self, report: Report) -> Report: ...

    async def list_for_scan(self, scan_id: str) -> list[Report]: ...


class MemoryReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, Report] = {}

    async def add(self, report: Report) -> Report:
        self._reports[report.report_id] = report
        return report

    async def list_for_scan(self, scan_id: str) -> list[Report]:
        matching = [report for report in self._reports.values() if report.scan_id == scan_id]
        by_id = sorted(matching, key=lambda report: report.report_id)
        return sorted(by_id, key=lambda report: report.created_at, reverse=True)


class ElasticReportStore:
    def __init__(self, es: AsyncElasticsearch) -> None:
        self._es = es

    async def add(self, report: Report) -> Report:
        # Refuse the submit rather than accept one we cannot persist.
        with _api_errors("could not store the report", status_code=503):
            # No refresh wait (3-5 s per write on Serverless). The app renders the
            # confirmation from the response; the list catches up within a second.
            await self._es.index(
                index=REPORTS_INDEX,
                id=report.report_id,
                document=document_from_report(report),
                refresh=False,
            )
        return report

    async def list_for_scan(self, scan_id: str) -> list[Report]:
        # report_id breaks created_at ties so the order is stable between calls.
        sort = [{ReportFields.CREATED_AT: "desc"}, {ReportFields.REPORT_ID: "asc"}]
        with _api_errors("could not list reports"):
            response = await self._es.search(
                index=REPORTS_INDEX,
                query={"term": {ReportFields.SCAN_ID: scan_id}},
                sort=sort,
                size=MAX_REPORTS,
                track_total_hits=False,
            )
        return [report_from_document(hit["_source"]) for hit in response["hits"]["hits"]]


def get_report_store(es: AsyncElasticsearch = Depends(get_es)) -> ElasticReportStore:
    return ElasticReportStore(es)


def document_from_report(report: Report) -> dict[str, Any]:
    doc = report.model_dump(mode="json", exclude_none=True)
    location = doc.get(ReportFields.PURCHASE_LOCATION)
    if isinstance(location, dict):
        # The mapping stores lat/lon as one geo_point under `coordinates`.
        lat = location.pop("lat", None)
        lon = location.pop("lon", None)
        if lat is not None and lon is not None:
            location["coordinates"] = {"lat": lat, "lon": lon}
        cleaned = {key: value for key, value in location.items() if value is not None}
        if cleaned:
            doc[ReportFields.PURCHASE_LOCATION] = cleaned
        else:
            doc.pop(ReportFields.PURCHASE_LOCATION, None)
    return doc


def report_from_document(source: dict[str, Any]) -> Report:
    doc = dict(source)
    location = doc.get(ReportFields.PURCHASE_LOCATION)
    if isinstance(location, dict):
        coords = location.get("coordinates") or {}
        doc[ReportFields.PURCHASE_LOCATION] = PurchaseLocation(
            label=location.get("label"),
            city=location.get("city"),
            region=location.get("region"),
            country=location.get("country"),
            lat=coords.get("lat"),
            lon=coords.get("lon"),
        )
    return Report.model_validate(doc)


def _unreachable(message: str, exc: TransportError) -> KnowledgeError:
    # Timeouts and dropped connections are retryable: tell the app so with a 503.
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
