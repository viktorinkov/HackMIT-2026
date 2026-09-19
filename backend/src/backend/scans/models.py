"""Request and response models for the past-scans API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.knowledge.fields import Scan
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareResult

# Kept in lockstep with fields.SCAN_STATUSES by test_models.py.
ScanStatus = Literal["pending", "partial", "complete", "error"]
PhotoTarget = Literal["bottle", "imprint"]


class PhotoRef(BaseModel):
    """A photo's fingerprint. The bytes themselves are never sent to Elastic."""

    target: PhotoTarget
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=128)


class ScanCreate(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    bottle: BottlePhotoResult | None = None
    imprint: ImprintPhotoResult | None = None
    hardware: PillHardwareResult | None = None
    # PillHardwareResult carries no model name; it lives on PillHardwareAnalysis.
    hardware_model: str | None = None
    # ImprintPhotoResult has no size field; the app measures it separately.
    imprint_size_mm: float | None = None
    country: str | None = Field(default=None, max_length=64)
    demo: bool = False
    photos: list[PhotoRef] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _require_an_observation(self) -> ScanCreate:
        if self.bottle is None and self.imprint is None and self.hardware is None:
            raise ValueError("at least one of bottle, imprint or hardware is required")
        return self


class ScanEnvelope(BaseModel):
    """The whole stored scan, as the app polls it."""

    scan_id: str
    device_id: str
    country: str | None = None
    revision: int
    status: ScanStatus
    demo: bool
    created_at: str
    updated_at: str
    bottle: dict[str, Any] | None = None
    imprint: dict[str, Any] | None = None
    norm: dict[str, Any] = Field(default_factory=dict)
    hardware: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    stages: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> ScanEnvelope:
        return cls(
            scan_id=doc[Scan.SCAN_ID],
            device_id=doc[Scan.DEVICE_ID],
            country=doc.get(Scan.COUNTRY),
            revision=int(doc.get(Scan.REVISION, 1)),
            status=doc.get(Scan.STATUS, "pending"),
            demo=bool(doc.get(Scan.DEMO, False)),
            created_at=doc[Scan.CREATED_AT],
            updated_at=doc.get(Scan.UPDATED_AT, doc[Scan.CREATED_AT]),
            bottle=doc.get(Scan.BOTTLE),
            imprint=doc.get(Scan.IMPRINT),
            norm=doc.get(Scan.NORM) or {},
            hardware=doc.get(Scan.HARDWARE),
            research=doc.get(Scan.RESEARCH),
            evidence=doc.get(Scan.EVIDENCE) or {},
            stages=doc.get(Scan.STAGES) or {},
        )


class ScanSummary(BaseModel):
    """One row of GET /scans: enough to redraw a history list without a second fetch."""

    scan_id: str
    device_id: str
    revision: int
    status: ScanStatus
    demo: bool
    created_at: str
    updated_at: str
    generic_name: str | None = None
    brand_name: str | None = None
    lot: str | None = None
    ndc9: str | None = None
    imprint_norm: str | None = None
    verdict: str | None = None
    risk_level: str | None = None
    headline: str | None = None

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> ScanSummary:
        norm = doc.get(Scan.NORM) or {}
        research = doc.get(Scan.RESEARCH) or {}
        return cls(
            scan_id=doc[Scan.SCAN_ID],
            device_id=doc[Scan.DEVICE_ID],
            revision=int(doc.get(Scan.REVISION, 1)),
            status=doc.get(Scan.STATUS, "pending"),
            demo=bool(doc.get(Scan.DEMO, False)),
            created_at=doc[Scan.CREATED_AT],
            updated_at=doc.get(Scan.UPDATED_AT, doc[Scan.CREATED_AT]),
            generic_name=norm.get("generic_name"),
            brand_name=norm.get("brand_name"),
            lot=norm.get("lot"),
            ndc9=norm.get("ndc9"),
            imprint_norm=norm.get("imprint_norm"),
            verdict=research.get("verdict"),
            risk_level=research.get("risk_level"),
            headline=research.get("headline"),
        )


class ScanListResponse(BaseModel):
    results: list[ScanSummary]
    next: str | None = None


class ResearchRequest(BaseModel):
    force: bool = False


class ResearchAccepted(BaseModel):
    scan_id: str
    status: ScanStatus
    started: bool
