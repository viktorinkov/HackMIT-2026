"""HTTP surface for past scans."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Scan
from backend.research.contract import scan_context_json, to_scan_context
from backend.scans.models import (
    ResearchAccepted,
    ResearchRequest,
    ScanCreate,
    ScanEnvelope,
    ScanListResponse,
    ScanSummary,
)
from backend.scans.store import ScanStore, get_scan_store

router = APIRouter(prefix="/scans", tags=["scans"])

StoreDep = Annotated[ScanStore, Depends(get_scan_store)]


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=ScanEnvelope)
async def create_scan(payload: ScanCreate, request: Request, store: StoreDep) -> ScanEnvelope:
    with _http_errors():
        doc = await store.create(payload)
    _launch_research(request.app, doc[Scan.SCAN_ID])
    return ScanEnvelope.from_doc(doc)


@router.get("", response_model=ScanListResponse)
async def list_scans(
    store: StoreDep,
    device_id: str | None = None,
    lot: str | None = None,
    ndc: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    after: str | None = None,
) -> ScanListResponse:
    lot_norm = normalize.normalize_lot(lot) if lot else None
    ndc_forms = normalize.normalize_ndc(ndc) if ndc else None
    ndc9 = ndc_forms.ndc9 if ndc_forms else None
    # A filter that normalizes to nothing can never match; do not silently drop it.
    if (lot and not lot_norm) or (ndc and not ndc9):
        return ScanListResponse(results=[], next=None)
    with _http_errors():
        docs, cursor = await store.list(
            device_id=device_id, lot=lot_norm, ndc9=ndc9, limit=limit, after=after
        )
    return ScanListResponse(results=[ScanSummary.from_doc(doc) for doc in docs], next=cursor)


@router.get("/{scan_id}", response_model=ScanEnvelope)
async def get_scan(scan_id: str, store: StoreDep) -> ScanEnvelope:
    return ScanEnvelope.from_doc(await _require_scan(store, scan_id))


@router.get("/{scan_id}/context")
async def get_scan_context(
    scan_id: str,
    store: StoreDep,
    as_string: bool = False,
) -> dict[str, Any]:
    doc = await _require_scan(store, scan_id)
    if as_string:
        return {"scan_context": scan_context_json(doc)}
    return to_scan_context(doc)


@router.post(
    "/{scan_id}/research",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResearchAccepted,
)
async def rerun_research(
    scan_id: str,
    payload: ResearchRequest,
    request: Request,
    store: StoreDep,
) -> ResearchAccepted:
    doc = await _require_scan(store, scan_id)
    started = _launch_research(request.app, scan_id, force=payload.force)
    if started is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the research pipeline is not available",
        )
    if not started:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"research is already running for {scan_id}; pass force=true to restart",
        )
    return ResearchAccepted(scan_id=scan_id, status=doc.get(Scan.STATUS, "pending"), started=True)


def _launch_research(app: Any, scan_id: str, *, force: bool = False) -> bool | None:
    """None when the pipeline module has not landed yet, so POST /scans still works."""
    try:
        from backend.research.pipeline import launch_research
    except ImportError:
        return None
    return launch_research(app, scan_id, force=force)


async def _require_scan(store: ScanStore, scan_id: str) -> dict[str, Any]:
    with _http_errors():
        doc = await store.get(scan_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no scan {scan_id}")
    return doc


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
