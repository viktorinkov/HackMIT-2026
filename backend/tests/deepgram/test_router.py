from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Settings, get_settings
from backend.deepgram.auth import TokenGrant, TokenGrantError, get_token_granter
from backend.deepgram.router import router
from backend.knowledge.client import KnowledgeError
from backend.scans.store import get_scan_store
from tests.deepgram.conftest import complete_scan


class StubStore:
    def __init__(self, doc: dict[str, Any] | None = None, error: KnowledgeError | None = None):
        self.doc = doc
        self.error = error

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        if self.error:
            raise self.error
        return self.doc


class StubGranter:
    def __init__(self, error: TokenGrantError | None = None) -> None:
        self.error = error
        self.calls = 0

    async def grant(self, *, ttl_seconds: int | None = None) -> TokenGrant:
        self.calls += 1
        if self.error:
            raise self.error
        return TokenGrant(access_token="jwt-123", expires_in=120)


@pytest.fixture
def stub() -> StubStore:
    return StubStore(doc=complete_scan())


@pytest.fixture
def granter() -> StubGranter:
    return StubGranter()


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_api_key="test", deepgram_api_key="dg-key")


@pytest.fixture
def client(stub: StubStore, settings: Settings, granter: StubGranter) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scan_store] = lambda: stub
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_token_granter] = lambda: granter
    with TestClient(app) as test_client:
        yield test_client


def test_session_returns_a_bearer_token_for_a_completed_scan(client: TestClient) -> None:
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["scan_id"] == "scan-1"
    assert body["authorization"] == "Bearer"
    assert body["access_token"] == "jwt-123"
    assert body["expires_in"] == 120
    assert body["grant_error"] is None
    assert body["settings"]["agent"]["greeting"].startswith(
        "Hi, I'm Peel. These findings are a simulated demo."
    )
    assert body["opening_messages"] == [
        "The label says acetaminophen 500 mg.",
        "The marking on the pill matches a reference for ibuprofen 200 mg.",
        "The sensor analysis reports ibuprofen.",
    ]


def test_session_falls_back_to_token_when_the_grant_fails(
    client: TestClient, granter: StubGranter
) -> None:
    granter.error = TokenGrantError("needs Member permission", status_code=403)
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["authorization"] == "Token"
    assert body["access_token"] is None
    assert body["grant_error"] == "needs Member permission"
    # Settings still ship so a demo build can connect with its own usage key.
    assert body["settings"]["type"] == "Settings"


def test_session_502s_when_a_temp_token_is_required(
    client: TestClient, granter: StubGranter, settings: Settings
) -> None:
    settings.deepgram_require_temp_token = True
    granter.error = TokenGrantError("needs Member permission", status_code=403)
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 502
    assert response.json()["detail"] == "needs Member permission"


def test_session_advertises_a_client_side_draft_report(client: TestClient) -> None:
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    # `think` is an ordered fallback chain; every provider gets the same tool.
    for think in response.json()["settings"]["agent"]["think"]:
        functions = think["functions"]
        assert [function["name"] for function in functions] == ["draft_report"]
        assert "endpoint" not in functions[0]


def test_session_needs_no_public_api_base_url(client: TestClient) -> None:
    # Deepgram no longer POSTs back to the API, so nothing here depends on it.
    assert client.post("/deepgram/session", json={"scan_id": "scan-1"}).status_code == 200


def test_session_allows_a_partial_scan_with_research(client: TestClient, stub: StubStore) -> None:
    stub.doc = complete_scan(status="partial")
    assert client.post("/deepgram/session", json={"scan_id": "scan-1"}).status_code == 200


def test_session_404s_when_the_scan_is_missing(client: TestClient, stub: StubStore) -> None:
    stub.doc = None
    assert client.post("/deepgram/session", json={"scan_id": "scan-x"}).status_code == 404


def test_session_409s_when_research_is_not_ready(client: TestClient, stub: StubStore) -> None:
    stub.doc = complete_scan(status="pending", research=None)
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 409


def test_session_surfaces_a_store_error(client: TestClient, stub: StubStore) -> None:
    stub.error = KnowledgeError("cluster down", status_code=503)
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 503
    assert response.json()["detail"] == "cluster down"


def test_reports_no_longer_live_under_deepgram(client: TestClient) -> None:
    assert client.post("/deepgram/scan-1/reports", json={}).status_code == 404
