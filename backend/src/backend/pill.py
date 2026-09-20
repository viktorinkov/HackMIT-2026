from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from truepill import PEEL_BENCH_RIG, classify_capture, load_library, to_pill_hardware_result
from truepill.backend_bridge import HARDWARE_MODEL as REAL_HARDWARE_MODEL

PillStatus = Literal["real", "substandard", "fake", "unknown"]

# Retained only to recognize historical simulated scans.
HARDWARE_MODEL = "mock-spectrometry"
HARDWARE_LIMITATION = (
    "Experimental three-color comparison against measured Advil and Pepto references. "
    "Confidence is a match score, not a probability. This does not prove authenticity "
    "or measure the labeled dose in milligrams."
)


class SweepChannels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    red: FiniteFloat
    yellow: FiniteFloat
    green: FiniteFloat


class PillSweep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    swept: Literal[True]
    sweep: SweepChannels


class PillHardwareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rig: Literal["peel-bench-17_stream"] = "peel-bench-17_stream"
    blank: list[PillSweep] = Field(min_length=5, max_length=5)
    sample: list[PillSweep] = Field(min_length=5, max_length=5)
    pill_type: str | None = Field(default=None, max_length=200)


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
    verdict: str = "UNKNOWN"
    flags: list[str] = Field(default_factory=list)
    limitations: str = HARDWARE_LIMITATION


router = APIRouter(tags=["pill"])


@router.post("/pill", response_model=PillHardwareAnalysis)
def analyze_pill(request: PillHardwareRequest) -> PillHardwareAnalysis:
    # FastAPI runs this synchronous scientific computation in its thread pool.
    for name, captures, floor in (
        ("water", request.blank, PEEL_BENCH_RIG.classifier.min_dynamic_range),
        ("sample", request.sample, 0.0),
    ):
        if any(
            value <= floor or value > PEEL_BENCH_RIG.classifier.full_scale
            for capture in captures for value in capture.sweep.model_dump().values()
        ):
            return PillHardwareAnalysis(
                model=REAL_HARDWARE_MODEL,
                result=PillHardwareResult(
                    status="unknown", spectrum=[], pill_type=None, degraded=False, confidence=0.0,
                ),
                verdict="INVALID_READING",
                flags=[f"Invalid {name} sweep. Inspect the instrument and take a fresh water capture."],
            )
    aliases = {
        "advil": "advil", "ibuprofen": "advil",
        "pepto": "pepto", "pepto-bismol": "pepto", "pepto bismol": "pepto",
        "bismuth subsalicylate": "pepto",
    }
    label = " ".join((request.pill_type or "").casefold().split())
    expected = aliases.get(label)
    result = classify_capture(
        [s.model_dump() for s in request.blank],
        [s.model_dump() for s in request.sample],
        load_library(),
        expected_drug=expected,
    )
    payload = to_pill_hardware_result(result, PEEL_BENCH_RIG.classifier)
    flags = list(result.flags)
    verdict = result.verdict
    if expected is None:
        # A two-entry library cannot validate an absent or unsupported label.
        payload.update(status="unknown", pill_type=None, degraded=False, confidence=0.0)
        verdict = "UNKNOWN"
        flags.append("No measured reference for this label. Supported labels: Advil and Pepto.")
    return PillHardwareAnalysis(
        model=REAL_HARDWARE_MODEL,
        result=PillHardwareResult(**payload),
        verdict=verdict,
        flags=flags,
    )
