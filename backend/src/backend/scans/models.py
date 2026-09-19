import json
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from backend.drug_facts.models import DrugFactsResearch
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareResult

ScanStatus = Literal["pending", "partial", "complete", "error"]
Finding = Literal["agree", "conflict", "inconclusive", "quality_concern"]


class BottleChannel(BaseModel):
    observation: BottlePhotoResult
    research: DrugFactsResearch | None = None


class ImprintChannel(BaseModel):
    observation: ImprintPhotoResult
    research: DrugFactsResearch | None = None


class PillChannel(BaseModel):
    hardware: PillHardwareResult
    research: DrugFactsResearch | None = None
    research_skipped_reason: str | None = None


class ScanReport(BaseModel):
    scan_id: str
    status: ScanStatus = "pending"
    demo: bool = False
    finding: Finding | None = None
    bottle: BottleChannel | None = None
    imprint: ImprintChannel | None = None
    pill: PillChannel | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateScanRequest(BaseModel):
    fixture: Literal["pending", "mismatch", "suspected_degradation", "nitroglycerin"] | None = (
        None
    )
    demo: bool = False


class ConcernReportCreate(BaseModel):
    concern_type: str
    summary: str
    user_description: str
    symptoms: str | None = None

    @model_validator(mode="before")
    @classmethod
    def unwrap_deepgram_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "concern_type" in data:
            return data
        for key in ("input", "arguments", "parameters"):
            inner = data.get(key)
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except json.JSONDecodeError:
                    continue
            if isinstance(inner, dict) and "concern_type" in inner:
                return inner
        return data


class ConcernReport(ConcernReportCreate):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_id: str
    snapshot: ScanReport
    created_at: datetime


class PlaygroundPrompt(BaseModel):
    scan_id: str
    prompt: str
    character_count: int
