"""Temporary Deepgram tokens for the app.

The app never holds the Deepgram API key. `POST /deepgram/session` mints a
short-lived JWT with `POST /v1/auth/grant` and the app connects to the Voice
Agent socket with `Authorization: Bearer <jwt>`. The token only has to be valid
for the WebSocket handshake; the socket stays open after it expires.

The key that mints tokens needs Member permission on the Deepgram project. A
usage-only key gets `403 FORBIDDEN` here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends

from backend.config import Settings, get_settings

GRANT_TIMEOUT_S = 5.0


class TokenGrantError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    expires_in: int


class TokenGranter:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def grant(self, *, ttl_seconds: int | None = None) -> TokenGrant:
        key = self._settings.deepgram_api_key
        if not key:
            raise TokenGrantError("DEEPGRAM_API_KEY is not configured on the server")
        ttl = ttl_seconds or self._settings.deepgram_token_ttl_seconds
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=GRANT_TIMEOUT_S) as client:
                    response = await self._post(client, key, ttl)
            else:
                response = await self._post(self._client, key, ttl)
        except httpx.HTTPError as exc:
            raise TokenGrantError(f"Deepgram token grant failed: {exc}") from exc
        if response.status_code == 403:
            raise TokenGrantError(
                "Deepgram refused to mint a token (403). The DEEPGRAM_API_KEY needs "
                "Member permission; create such a key in the Deepgram console.",
                status_code=403,
            )
        if response.status_code >= 400:
            raise TokenGrantError(
                f"Deepgram token grant returned {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )
        body = response.json()
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise TokenGrantError("Deepgram token grant returned no access_token")
        return TokenGrant(access_token=token, expires_in=int(body.get("expires_in") or ttl))

    async def _post(self, client: httpx.AsyncClient, key: str, ttl: int) -> httpx.Response:
        return await client.post(
            self._settings.deepgram_grant_url,
            headers={"Authorization": f"Token {key}"},
            json={"ttl_seconds": ttl},
        )


def get_token_granter(settings: Annotated[Settings, Depends(get_settings)]) -> TokenGranter:
    return TokenGranter(settings)
