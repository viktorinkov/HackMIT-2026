"""HTTP surface for reports: the Submit button and the history list.

Deepgram never calls these. Peel's `draft_report` is a client-side function, so
the draft only reaches the app; the app POSTs here when the user taps Submit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.knowledge.client import KnowledgeError
from backend.reports.models import Report, ReportCreate, ReportListResponse
from backend.reports.store import ReportStore, get_report_store
from backend.scans.store import ScanStore, get_scan_store

router = APIRouter(prefix="/scans/{scan_id}/reports", tags=["reports"])

ScansDep = Annotated[ScanStore, Depends(get_scan_store)]
ReportsDep = Annotated[ReportStore, Depends(get_report_store)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Report)
async def submit_report(
    scan_id: str,
    body: ReportCreate,
    scans: ScansDep,
    reports: ReportsDep,
) -> Report:
    """Every tap is a new document; the path's scan_id wins over any in the body."""
    await _require_scan(scans, scan_id)
    report = Report(
        scan_id=scan_id,
        purchased_on=body.purchased_on,
        purchase_location=body.purchase_location,
        seller=body.seller,
        created_at=datetime.now(UTC),
    )
    with _http_errors():
        return await reports.add(report)


@router.get("", response_model=ReportListResponse)
async def list_reports(scan_id: str, scans: ScansDep, reports: ReportsDep) -> ReportListResponse:
    """Filed reports for this scan, newest first."""
    await _require_scan(scans, scan_id)
    with _http_errors():
        return ReportListResponse(results=await reports.list_for_scan(scan_id))


async def _require_scan(scans: ScanStore, scan_id: str) -> None:
    with _http_errors():
        doc = await scans.get(scan_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no scan {scan_id}")


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
