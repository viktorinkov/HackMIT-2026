from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from backend.config import Settings, get_settings
from backend.deepgram.models import (
    ConcernReport,
    ConcernReportCreate,
    DeepgramSession,
    DeepgramSessionRequest,
)
from backend.deepgram.session import build_voice_agent_settings
from backend.deepgram.store import ReportStore, get_report_store
from backend.knowledge.client import KnowledgeError
from backend.research.contract import to_scan_context
from backend.scans.store import ScanStore, get_scan_store

READY_STATUSES = frozenset({"complete", "partial"})

router = APIRouter(prefix="/deepgram", tags=["deepgram"])

StoreDep = Annotated[ScanStore, Depends(get_scan_store)]
ReportsDep = Annotated[ReportStore, Depends(get_report_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/session", response_model=DeepgramSession)
async def create_deepgram_session(
    body: DeepgramSessionRequest,
    store: StoreDep,
    settings: SettingsDep,
) -> DeepgramSession:
    if not settings.public_api_base_url.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PUBLIC_API_BASE_URL is not set",
        )
    doc = await _require_scan(store, body.scan_id)
    if doc.get("status") not in READY_STATUSES or not doc.get("research"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scan {body.scan_id} is not ready for a voice session",
        )
    try:
        agent_settings = build_voice_agent_settings(doc, settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    return DeepgramSession(
        scan_id=str(doc["scan_id"]),
        websocket_url=settings.deepgram_websocket_url,
        authorization="Token",
        settings=agent_settings,
    )


@router.post("/{scan_id}/reports", response_model=ConcernReport)
async def create_concern_report(
    scan_id: str,
    body: ConcernReportCreate,
    store: StoreDep,
    reports: ReportsDep,
) -> ConcernReport:
    doc = await _require_scan(store, scan_id)
    report = ConcernReport(
        report_id=str(uuid4()),
        scan_id=scan_id,
        concern_type=body.concern_type,
        summary=body.summary,
        user_description=body.user_description,
        symptoms=body.symptoms,
        snapshot=to_scan_context(doc),
        created_at=datetime.now(UTC),
    )
    return await reports.add(report)


@router.get("/{scan_id}/reports", response_model=list[ConcernReport])
async def list_concern_reports(
    scan_id: str,
    store: StoreDep,
    reports: ReportsDep,
) -> list[ConcernReport]:
    await _require_scan(store, scan_id)
    return await reports.list(scan_id)


async def _require_scan(store: ScanStore, scan_id: str) -> dict[str, Any]:
    try:
        doc = await store.get(scan_id)
    except KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no scan {scan_id}")
    return doc
