"""Request and response models for the past-scans API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.knowledge.fields import Scan
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareResult

# Kept in lockstep with fields.SCAN_STATUSES by test_models.py.
ScanStatus = Literal["pending", "partial", "complete", "error"]
PhotoTarget = Literal["bottle", "imprint"]

# A real hardware scan is a few hundred to a couple thousand points; 4096 is
# generous headroom without letting one POST embed megabytes of floats that
# get re-served on every 1 Hz poll and shipped whole into the agent prompt.
MAX_SPECTRUM_LEN = 4096
# A label photo carries a handful of warning strings, not hundreds.
MAX_VISIBLE_WARNINGS = 50
MAX_WARNING_LEN = 500
# Generous bound for any single free-text field read off a label/imprint photo;
# storage applies its own tighter cap (normalizer.TEXT_CAP), this just keeps a
# single malicious field from blowing up the request body / agent prompt.
MAX_TEXT_FIELD_LEN = 4000


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
    hardware_model: str | None = Field(default=None, max_length=128)
    # ImprintPhotoResult has no size field; the app measures it separately.
    imprint_size_mm: float | None = None
    country: str | None = Field(default=None, max_length=64)
    demo: bool = False
    photos: list[PhotoRef] = Field(default_factory=list, max_length=8)

    @field_validator("bottle")
    @classmethod
    def _bound_bottle(cls, value: BottlePhotoResult | None) -> BottlePhotoResult | None:
        if value is None:
            return value
        if len(value.visible_warnings) > MAX_VISIBLE_WARNINGS:
            raise ValueError(
                f"bottle.visible_warnings must have at most {MAX_VISIBLE_WARNINGS} items"
            )
        for warning in value.visible_warnings:
            if warning is not None and len(warning) > MAX_WARNING_LEN:
                raise ValueError(
                    f"each bottle.visible_warnings item must be at most "
                    f"{MAX_WARNING_LEN} characters"
                )
        _bound_text_fields(value, exclude={"visible_warnings"})
        return value

    @field_validator("imprint")
    @classmethod
    def _bound_imprint(cls, value: ImprintPhotoResult | None) -> ImprintPhotoResult | None:
        if value is not None:
            _bound_text_fields(value)
        return value

    @field_validator("hardware")
    @classmethod
    def _bound_hardware(cls, value: PillHardwareResult | None) -> PillHardwareResult | None:
        if value is not None and len(value.spectrum) > MAX_SPECTRUM_LEN:
            raise ValueError(f"hardware.spectrum must have at most {MAX_SPECTRUM_LEN} values")
        return value

    @model_validator(mode="after")
    def _require_an_observation(self) -> ScanCreate:
        if self.bottle is None and self.imprint is None and self.hardware is None:
            raise ValueError("at least one of bottle, imprint or hardware is required")
        return self


def _bound_text_fields(model: BaseModel, *, exclude: frozenset[str] = frozenset()) -> None:
    """Reject any free-text string field longer than MAX_TEXT_FIELD_LEN.

    Iterates the already-validated nested model's fields generically so this
    keeps working if photo_identification adds another free-text field later.
    """
    for name, value in model:
        if name in exclude or not isinstance(value, str):
            continue
        if len(value) > MAX_TEXT_FIELD_LEN:
            raise ValueError(f"{name} must be at most {MAX_TEXT_FIELD_LEN} characters")


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
