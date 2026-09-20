from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


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


class ConcernReportCreate(BaseModel):
    concern_type: str | None = None
    summary: str | None = None
    user_description: str | None = None
    symptoms: str | None = None

    @model_validator(mode="before")
    @classmethod
    def unwrap_deepgram_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if any(
            key in data
            for key in ("concern_type", "summary", "user_description", "symptoms")
        ):
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


class ConcernReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    scan_id: str
    concern_type: str
    summary: str
    user_description: str
    symptoms: str | None = None
    snapshot: dict[str, Any]
    created_at: datetime
