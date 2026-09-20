"""Reports in `peel-reports`: one document per scan, keyed by `scan_id`."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from elasticsearch import ApiError, AsyncElasticsearch, NotFoundError, TransportError
from fastapi import Depends

from backend.deepgram.models import ConcernReport, PurchaseLocation
from backend.knowledge.client import KnowledgeError, get_es
from backend.knowledge.fields import REPORTS_INDEX, Report


class ReportStore(Protocol):
    async def add(self, report: ConcernReport) -> ConcernReport: ...
    async def get(self, scan_id: str) -> ConcernReport | None: ...


class MemoryReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, ConcernReport] = {}

    async def add(self, report: ConcernReport) -> ConcernReport:
        existing = self._reports.get(report.scan_id)
        if existing is not None:
            report = report.model_copy(
                update={"report_id": existing.report_id, "created_at": existing.created_at}
            )
        self._reports[report.scan_id] = report
        return report

    async def get(self, scan_id: str) -> ConcernReport | None:
        return self._reports.get(scan_id)


class ElasticReportStore:
    def __init__(self, es: AsyncElasticsearch) -> None:
        self._es = es

    async def add(self, report: ConcernReport) -> ConcernReport:
        existing = await self.get(report.scan_id)
        if existing is not None:
            report = report.model_copy(
                update={"report_id": existing.report_id, "created_at": existing.created_at}
            )
        with _api_errors("could not store the report", status_code=503):
            # `_id` is scan_id so GET is realtime; no search, no refresh wait.
            await self._es.index(
                index=REPORTS_INDEX,
                id=report.scan_id,
                document=document_from_report(report),
                refresh=False,
            )
        return report

    async def get(self, scan_id: str) -> ConcernReport | None:
        try:
            response = await self._es.get(index=REPORTS_INDEX, id=scan_id, realtime=True)
        except NotFoundError:
            return None
        except ApiError as exc:
            raise _wrapped("could not read the report", exc) from exc
        except TransportError as exc:
            raise _unreachable("could not read the report", exc) from exc
        return report_from_document(dict(response["_source"]))


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
