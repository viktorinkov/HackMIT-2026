from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class DeepgramSessionRequest(BaseModel):
    scan_id: str


class DeepgramSession(BaseModel):
    scan_id: str
    websocket_url: str
    # "Bearer": connect with `Authorization: Bearer <access_token>`.
    # "Token": no token could be minted; a demo build may use its own usage key.
    authorization: Literal["Bearer", "Token"]
    access_token: str | None = None
    expires_in: int | None = None
    grant_error: str | None = None
    settings: dict[str, Any]
    opening_messages: list[str]


class PlaygroundPrompt(BaseModel):
    scan_id: str
    prompt: str
    character_count: int
