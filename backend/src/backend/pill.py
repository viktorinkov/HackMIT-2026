from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat

PillStatus = Literal["real", "substandard", "fake", "unknown"]

# Pill is the physical tablet: hardware spectrometry of contents, not the imprint photo.
# Legacy stored scans remain explicitly marked as simulated. No mock route exists.
HARDWARE_MODEL = "mock-spectrometry"


class SensorReading(BaseModel):
    t: FiniteFloat | None = None
    trans: FiniteFloat | None = None
    scat: FiniteFloat | None = None
    absT: FiniteFloat | None = None
    absS: FiniteFloat | None = None
    tC: FiniteFloat | None = None
    darkTrans: FiniteFloat | None = None
    darkScat: FiniteFloat | None = None
    stir: FiniteFloat | None = None
    swept: bool = False
    sweep: dict[Literal["ir", "red", "yellow", "green", "blue", "violet"], FiniteFloat | None] = Field(default_factory=dict)
    sweepS: dict[Literal["ir", "red", "yellow", "green", "blue", "violet"], FiniteFloat | None] = Field(default_factory=dict)


class PillHardwareResult(BaseModel):
    status: PillStatus
    spectrum: list[FiniteFloat]
    sensor_readings: list[SensorReading] = Field(default_factory=list, max_length=256)
    sensor_sample_count: int | None = Field(default=None, ge=0, le=1000000)
    pill_type: str | None = None
    degraded: bool
    confidence: float = Field(ge=0, le=1)


class PillHardwareAnalysis(BaseModel):
    identification_method: Literal["hardware"] = "hardware"
    target: Literal["pill"] = "pill"
    model: str
    result: PillHardwareResult
