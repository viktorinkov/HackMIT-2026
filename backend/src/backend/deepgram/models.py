from typing import Any, Literal

from pydantic import BaseModel


class DeepgramSessionRequest(BaseModel):
    scan_id: str


class DeepgramSession(BaseModel):
    scan_id: str
    websocket_url: str
    authorization: Literal["Token"] = "Token"
    settings: dict[str, Any]
