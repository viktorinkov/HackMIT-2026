from fastapi import APIRouter, Depends

from backend.config import Settings, get_settings
from backend.deepgram.models import DeepgramSession, DeepgramSessionRequest
from backend.deepgram.session import build_voice_agent_settings
from backend.scans.service import ScanService, get_scan_service

router = APIRouter(prefix="/deepgram", tags=["deepgram"])


@router.post("/session", response_model=DeepgramSession)
async def create_deepgram_session(
    body: DeepgramSessionRequest,
    scans: ScanService = Depends(get_scan_service),
    settings: Settings = Depends(get_settings),
) -> DeepgramSession:
    report = await scans.get(body.scan_id)
    return DeepgramSession(
        scan_id=report.scan_id,
        websocket_url=settings.deepgram_websocket_url,
        authorization="Token",
        settings=build_voice_agent_settings(report, settings),
    )
