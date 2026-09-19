from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, Query

from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareRequest
from backend.scans.models import (
    ConcernReport,
    ConcernReportCreate,
    CreateScanRequest,
    PlaygroundPrompt,
    ScanReport,
)
from backend.scans.prompt import build_playground_prompt
from backend.scans.service import ScanService, get_scan_service
from backend.scans.store import ScanStore, get_scan_store

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanReport)
async def create_scan(
    body: CreateScanRequest | None = None,
    fixture: str | None = Query(default=None),
    scans: ScanService = Depends(get_scan_service),
) -> ScanReport:
    payload = body or CreateScanRequest()
    return await scans.create(fixture=fixture or payload.fixture, demo=payload.demo)


@router.get("/{scan_id}", response_model=ScanReport)
async def get_scan(
    scan_id: str,
    scans: ScanService = Depends(get_scan_service),
) -> ScanReport:
    return await scans.get(scan_id)


@router.put("/{scan_id}/bottle", response_model=ScanReport)
async def attach_bottle(
    scan_id: str,
    observation: BottlePhotoResult,
    scans: ScanService = Depends(get_scan_service),
) -> ScanReport:
    return await scans.attach_bottle(scan_id, observation)


@router.put("/{scan_id}/imprint", response_model=ScanReport)
async def attach_imprint(
    scan_id: str,
    observation: ImprintPhotoResult,
    scans: ScanService = Depends(get_scan_service),
) -> ScanReport:
    return await scans.attach_imprint(scan_id, observation)


@router.put("/{scan_id}/pill", response_model=ScanReport)
async def attach_pill(
    scan_id: str,
    request: PillHardwareRequest,
    scans: ScanService = Depends(get_scan_service),
) -> ScanReport:
    return await scans.attach_pill(scan_id, request)


@router.get("/{scan_id}/playground-prompt", response_model=PlaygroundPrompt)
async def playground_prompt(
    scan_id: str,
    scans: ScanService = Depends(get_scan_service),
) -> PlaygroundPrompt:
    return build_playground_prompt(await scans.get(scan_id))


@router.post("/{scan_id}/reports", response_model=ConcernReport)
async def create_concern_report(
    scan_id: str,
    body: ConcernReportCreate,
    scans: ScanService = Depends(get_scan_service),
    store: ScanStore = Depends(get_scan_store),
) -> ConcernReport:
    snapshot = await scans.get(scan_id)
    report = ConcernReport(
        report_id=str(uuid4()),
        scan_id=scan_id,
        concern_type=body.concern_type,
        summary=body.summary,
        user_description=body.user_description,
        symptoms=body.symptoms,
        snapshot=snapshot,
        created_at=datetime.now(UTC),
    )
    return await store.add_concern_report(report)


@router.get("/{scan_id}/reports", response_model=list[ConcernReport])
async def list_concern_reports(
    scan_id: str,
    scans: ScanService = Depends(get_scan_service),
    store: ScanStore = Depends(get_scan_store),
) -> list[ConcernReport]:
    await scans.get(scan_id)
    return await store.list_concern_reports(scan_id)
