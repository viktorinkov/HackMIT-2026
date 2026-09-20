from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.config import Settings, get_settings
from backend.deepgram.models import DeepgramSession, DeepgramSessionRequest
from backend.deepgram.session import (
    build_voice_agent_settings,
    opening_messages_from_scan,
)
from backend.knowledge.client import KnowledgeError
from backend.scans.store import ScanStore, get_scan_store

READY_STATUSES = frozenset({"complete", "partial"})

router = APIRouter(prefix="/deepgram", tags=["deepgram"])

StoreDep = Annotated[ScanStore, Depends(get_scan_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/session", response_model=DeepgramSession)
async def create_deepgram_session(
    body: DeepgramSessionRequest,
    store: StoreDep,
    settings: SettingsDep,
) -> DeepgramSession:
    doc = await _require_scan(store, body.scan_id)
    if doc.get("status") not in READY_STATUSES or not doc.get("research"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scan {body.scan_id} is not ready for a voice session",
        )
    try:
        agent_settings = build_voice_agent_settings(doc)
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
        opening_messages=opening_messages_from_scan(doc),
    )


async def _require_scan(store: ScanStore, scan_id: str) -> dict[str, Any]:
    try:
        doc = await store.get(scan_id)
    except KnowledgeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no scan {scan_id}")
    return doc
