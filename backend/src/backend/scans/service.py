from uuid import uuid4

from fastapi import Depends, HTTPException, status

from backend.drug_facts.models import DrugFactsError
from backend.drug_facts.queries import bottle_search_query, imprint_search_query
from backend.drug_facts.service import ResearchService, get_research_service
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareRequest, mock_hardware_result
from backend.scans.compare import compare_channels
from backend.scans.fixtures import FIXTURE_NAMES, load_fixture
from backend.scans.models import BottleChannel, ImprintChannel, PillChannel, ScanReport
from backend.scans.store import ScanStore, get_scan_store


def _refresh_status(report: ScanReport) -> ScanReport:
    filled = [channel for channel in (report.bottle, report.imprint, report.pill) if channel]
    if not filled:
        report.status = "pending"
    elif len(filled) < 3:
        report.status = "partial"
    else:
        report.status = "complete"
    report.finding = compare_channels(report.bottle, report.imprint, report.pill)
    return report


class ScanService:
    def __init__(self, store: ScanStore, research: ResearchService) -> None:
        self._store = store
        self._research = research

    async def create(
        self,
        fixture: str | None = None,
        demo: bool = False,
    ) -> ScanReport:
        scan_id = str(uuid4())
        if fixture:
            if fixture not in FIXTURE_NAMES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown fixture. Use one of: {', '.join(FIXTURE_NAMES)}",
                )
            return await self._store.create(load_fixture(fixture, scan_id))
        return await self._store.create(ScanReport(scan_id=scan_id, demo=demo))

    async def get(self, scan_id: str) -> ScanReport:
        report = await self._store.get(scan_id)
        if report is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
        return report

    async def attach_bottle(self, scan_id: str, observation: BottlePhotoResult) -> ScanReport:
        report = await self.get(scan_id)
        research = None
        if observation.is_medication_container and bottle_search_query(observation):
            try:
                research = await self._research.research_bottle(observation)
            except DrugFactsError:
                research = None
        report.bottle = BottleChannel(observation=observation, research=research)
        return await self._store.save(_refresh_status(report))

    async def attach_imprint(self, scan_id: str, observation: ImprintPhotoResult) -> ScanReport:
        report = await self.get(scan_id)
        research = None
        if observation.is_pill and imprint_search_query(observation):
            try:
                research = await self._research.research_imprint(observation)
            except DrugFactsError:
                research = None
        report.imprint = ImprintChannel(observation=observation, research=research)
        return await self._store.save(_refresh_status(report))

    async def attach_pill(self, scan_id: str, request: PillHardwareRequest) -> ScanReport:
        report = await self.get(scan_id)
        hardware = mock_hardware_result(request)
        research = None
        skipped: str | None = None
        if hardware.status == "fake":
            skipped = "Hardware classified this pill as fake; contents facts are not looked up."
        elif hardware.status == "unknown":
            skipped = "Hardware did not identify a pill type to research."
        elif not hardware.pill_type or not hardware.pill_type.strip():
            skipped = "Need a hardware pill_type to research contents facts."
        else:
            try:
                research = await self._research.research_pill(hardware)
            except DrugFactsError as exc:
                skipped = exc.message
        report.pill = PillChannel(
            hardware=hardware,
            research=research,
            research_skipped_reason=skipped,
        )
        return await self._store.save(_refresh_status(report))


def get_scan_service(
    store: ScanStore = Depends(get_scan_store),
    research: ResearchService = Depends(get_research_service),
) -> ScanService:
    return ScanService(store, research)
