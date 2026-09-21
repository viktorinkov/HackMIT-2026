"""Pydantic models for the TruePill time-resolved ingestion path.

A run is a sequence of ~1 Hz readings taken while the tablet dissolves.
The legacy single-scan event is still accepted and is treated as a run with
one reading (see `ScanEvent.as_run`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import math

from pydantic import BaseModel, Field, field_validator


class Reading(BaseModel):
    """One ~1 Hz spectrometer reading during a dissolution run."""

    t_seconds: float = Field(ge=0)
    absorbance: list[float]
    dark: list[float]
    blank_ref: list[float]
    temperature: float
    led_current_mA: float = Field(gt=0)

    @field_validator("t_seconds", "temperature", "led_current_mA")
    @classmethod
    def _finite_scalar(cls, v: float, info) -> float:
        if not math.isfinite(v):
            raise ValueError(f"{info.field_name} must be finite, got {v}")
        return v

    @field_validator("absorbance", "dark", "blank_ref")
    @classmethod
    def _finite_channels(cls, v: list[float], info) -> list[float]:
        if not all(math.isfinite(x) for x in v):
            raise ValueError(f"{info.field_name} contains NaN or infinite values")
        return v

    @field_validator("dark", "blank_ref")
    @classmethod
    def _same_length_as_absorbance(cls, v: list[float], info) -> list[float]:
        absorbance = info.data.get("absorbance")
        if absorbance is not None and len(v) != len(absorbance):
            raise ValueError(f"{info.field_name} length {len(v)} != absorbance length {len(absorbance)}")
        return v


class SampleMetadata(BaseModel):
    """What the operator says the sample is."""

    expected_drug: str | None = None
    label_dose_mg: float | None = None
    lot: str | None = None
    notes: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DissolutionRun(BaseModel):
    """A full (or in-progress) time-resolved run."""

    run_id: str
    sample: SampleMetadata = Field(default_factory=SampleMetadata)
    wavelengths: list[float]
    t0: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    readings: list[Reading] = Field(default_factory=list)

    @property
    def n_channels(self) -> int:
        return len(self.wavelengths)

    def add_reading(self, reading: Reading) -> None:
        if len(reading.absorbance) != self.n_channels:
            raise ValueError(
                f"reading has {len(reading.absorbance)} channels, run expects {self.n_channels}"
            )
        if self.readings and reading.t_seconds < self.readings[-1].t_seconds:
            raise ValueError("readings must arrive in time order")
        self.readings.append(reading)


class ScanEvent(BaseModel):
    """Legacy single-snapshot scan event emitted by older firmware."""

    scan_id: str
    timestamp: datetime
    wavelengths: list[float]
    absorbance: list[float]
    dark: list[float]
    blank_ref: list[float]
    temperature: float

    def as_run(self) -> DissolutionRun:
        """Adapt the legacy payload to a run with a single reading."""
        return DissolutionRun(
            run_id=self.scan_id,
            wavelengths=self.wavelengths,
            t0=self.timestamp,
            readings=[
                Reading(
                    t_seconds=0.0,
                    absorbance=self.absorbance,
                    dark=self.dark,
                    blank_ref=self.blank_ref,
                    temperature=self.temperature,
                    led_current_mA=DEFAULT_LED_CURRENT_MA,
                )
            ],
        )


# Assumed drive current for legacy payloads that predate the field.
DEFAULT_LED_CURRENT_MA = 20.0


# ---------------------------------------------------------------------------
# WebSocket protocol messages (client -> server)
# ---------------------------------------------------------------------------

class StartRunMessage(BaseModel):
    type: Literal["start_run"]
    run_id: str
    wavelengths: list[float]
    sample: SampleMetadata = Field(default_factory=SampleMetadata)
    max_duration_seconds: float = Field(default=3600.0, gt=0)


class ReadingMessage(BaseModel):
    type: Literal["reading"]
    reading: Reading


class EndRunMessage(BaseModel):
    type: Literal["end_run"]


class LegacyScanMessage(BaseModel):
    type: Literal["scan"]
    scan: ScanEvent
