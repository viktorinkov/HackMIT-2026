"""Report models.

A report is the three optional provenance answers, joined to a scan by
`scan_id`. Peel drafts them in the chat, the app previews them, and the Submit
button POSTs them. The scan itself is never copied here; read it by `scan_id`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.knowledge.normalize import parse_date


class PurchaseLocation(BaseModel):
    """Where they bought it. `label` is the spoken place; the rest drive a map chip."""

    label: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    lat: float | None = None
    lon: float | None = None

    @model_validator(mode="before")
    @classmethod
    def coerce_spoken_place(cls, data: Any) -> Any:
        # The LLM sometimes sends the place as one string; keep it as the label.
        if data is None or data == "":
            return None
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                text = data.strip()
                return {"label": text} if text else None
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, str):
                text = parsed.strip()
                return {"label": text} if text else None
            return None
        return data

    @field_validator("label", "city", "region", "country", mode="before")
    @classmethod
    def blank_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def is_empty(self) -> bool:
        return not any(
            (
                self.label,
                self.city,
                self.region,
                self.country,
                self.lat is not None,
                self.lon is not None,
            )
        )


class ReportCreate(BaseModel):
    """The Submit body. Every field is optional; blanks are dropped, not stored."""

    purchased_on: date | None = None
    purchase_location: PurchaseLocation | None = None
    seller: str | None = None

    @field_validator("purchased_on", mode="before")
    @classmethod
    def parse_purchased_on(cls, value: Any) -> date | None:
        parsed = parse_date(value)
        return parsed.date() if parsed else None

    @field_validator("seller", mode="before")
    @classmethod
    def blank_seller(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @model_validator(mode="after")
    def drop_empty_location(self) -> Self:
        if self.purchase_location is not None and self.purchase_location.is_empty():
            self.purchase_location = None
        return self


class Report(BaseModel):
    """One stored filing. `scan_id` is the join; nothing from the scan is copied."""

    report_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_id: str
    purchased_on: date | None = None
    purchase_location: PurchaseLocation | None = None
    seller: str | None = None
    created_at: datetime


class ReportListResponse(BaseModel):
    results: list[Report]
