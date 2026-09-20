from __future__ import annotations

import json

import httpx
import pytest

from backend.config import Settings
from backend.deepgram.auth import TokenGranter, TokenGrantError


def _settings(**kwargs: object) -> Settings:
    return Settings(openai_api_key="test", deepgram_api_key="dg-key", **kwargs)


def _granter(handler, settings: Settings | None = None) -> TokenGranter:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return TokenGranter(settings or _settings(), client=client)


async def test_grant_sends_the_key_and_ttl_and_returns_the_token() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "jwt-abc", "expires_in": 120})

    grant = await _granter(handler).grant()
    assert grant.access_token == "jwt-abc"
    assert grant.expires_in == 120
    assert seen["url"] == "https://api.deepgram.com/v1/auth/grant"
    assert seen["auth"] == "Token dg-key"
    # The field is ttl_seconds, not ttl.
    assert seen["body"] == {"ttl_seconds": 120}


async def test_grant_honours_a_custom_ttl() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"ttl_seconds": 60}
        return httpx.Response(200, json={"access_token": "jwt", "expires_in": 60})

    assert (await _granter(handler).grant(ttl_seconds=60)).expires_in == 60


async def test_grant_explains_a_403_as_a_permissions_problem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"err_code": "FORBIDDEN", "err_msg": "Insufficient permissions."}
        )

    with pytest.raises(TokenGrantError) as excinfo:
        await _granter(handler).grant()
    assert excinfo.value.status_code == 403
    assert "Member permission" in excinfo.value.message


async def test_grant_fails_without_a_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be made without a key")

    # Explicit empty key: Settings would otherwise read one from backend/.env.
    granter = _granter(handler, Settings(openai_api_key="test", deepgram_api_key=""))
    with pytest.raises(TokenGrantError) as excinfo:
        await granter.grant()
    assert "not configured" in excinfo.value.message


async def test_grant_rejects_a_body_without_a_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_in": 30})

    with pytest.raises(TokenGrantError):
        await _granter(handler).grant()


async def test_grant_wraps_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(TokenGrantError) as excinfo:
        await _granter(handler).grant()
    assert "grant failed" in excinfo.value.message
