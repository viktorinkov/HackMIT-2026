from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.knowledge.normalize import parse_date

_CREATE_KEYS = (
    "purchased_on",
    "purchase_location",
    "seller",
    "concern_type",
    "summary",
    "user_description",
)


class DeepgramSessionRequest(BaseModel):
    scan_id: str


class DeepgramSession(BaseModel):
    scan_id: str
    websocket_url: str
    authorization: Literal["Token"] = "Token"
    settings: dict[str, Any]
    opening_messages: list[str]


class PlaygroundPrompt(BaseModel):
    scan_id: str
    prompt: str
    character_count: int


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


class ConcernReportCreate(BaseModel):
    purchased_on: date | None = None
    purchase_location: PurchaseLocation | None = None
    seller: str | None = None
    concern_type: str | None = None
    summary: str | None = None
    user_description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def unwrap_deepgram_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if any(key in data for key in _CREATE_KEYS):
            return data
        for key in ("input", "arguments", "parameters"):
            inner = data.get(key)
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except json.JSONDecodeError:
                    continue
            if isinstance(inner, dict):
                return inner
        return data

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


class ConcernReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_id: str
    concern_type: str
    summary: str
    user_description: str
    seller: str | None = None
    purchased_on: date | None = None
    purchase_location: PurchaseLocation | None = None
    snapshot: dict[str, Any]
    created_at: datetime
