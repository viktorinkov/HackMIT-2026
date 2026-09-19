from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

PillStatus = Literal["real", "substandard", "fake", "unknown"]

# Pill is the physical tablet: hardware spectrometry of contents, not the imprint photo.
HARDWARE_MODEL = "mock-spectrometry"


class PillHardwareRequest(BaseModel):
    status: PillStatus = "unknown"
    pill_type: str | None = None


class PillHardwareResult(BaseModel):
    status: PillStatus
    spectrum: list[float]
    pill_type: str | None = None
    degraded: bool
    confidence: float = Field(ge=0, le=1)


class PillHardwareAnalysis(BaseModel):
    identification_method: Literal["hardware"] = "hardware"
    target: Literal["pill"] = "pill"
    model: str
    result: PillHardwareResult


router = APIRouter(tags=["pill"])


@router.post("/pill", response_model=PillHardwareAnalysis)
async def analyze_pill(request: PillHardwareRequest) -> PillHardwareAnalysis:
    return PillHardwareAnalysis(model=HARDWARE_MODEL, result=mock_hardware_result(request))


def mock_hardware_result(request: PillHardwareRequest) -> PillHardwareResult:
    degraded = request.status == "substandard"
    confidence = {
        "real": 0.92,
        "substandard": 0.78,
        "fake": 0.88,
        "unknown": 0.2,
    }[request.status]
    return PillHardwareResult(
        status=request.status,
        spectrum=_mock_spectrum(request.status, request.pill_type),
        pill_type=request.pill_type,
        degraded=degraded,
        confidence=confidence,
    )


def _mock_spectrum(status: PillStatus, pill_type: str | None) -> list[float]:
    seed = f"{status}|{pill_type or ''}".encode()
    digest = hashlib.sha256(seed).digest()
    return [round(b / 255.0, 4) for b in digest[:16]]
