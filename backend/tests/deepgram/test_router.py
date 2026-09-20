from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Settings, get_settings
from backend.deepgram.router import router
from backend.deepgram.store import MemoryReportStore, get_report_store
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


@pytest.fixture
def stub() -> StubStore:
    return StubStore(doc=complete_scan())


@pytest.fixture
def reports() -> MemoryReportStore:
    return MemoryReportStore()


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_api_key="test", public_api_base_url="https://api.example")


@pytest.fixture
def client(stub: StubStore, reports: MemoryReportStore, settings: Settings) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scan_store] = lambda: stub
    app.dependency_overrides[get_report_store] = lambda: reports
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


def test_session_returns_200_for_a_completed_scan(client: TestClient) -> None:
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["scan_id"] == "scan-1"
    assert body["authorization"] == "Token"
    assert body["settings"]["agent"]["greeting"] == (
        "Hi, I'm Peel. These findings are a simulated demo."
    )
    assert body["opening_messages"] == [
        "Bottle: the label says acetaminophen 500 mg.",
        "Imprint: the marking lookup returned ibuprofen 200 mg.",
        "Pill: the hardware analysis reports the contents as ibuprofen.",
        "The label and the reference records do not agree.",
    ]


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


def test_session_503s_without_a_public_api_base_url(
    client: TestClient, settings: Settings
) -> None:
    settings.public_api_base_url = ""
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 503
    assert "PUBLIC_API_BASE_URL" in response.json()["detail"]


def test_session_surfaces_a_store_error(client: TestClient, stub: StubStore) -> None:
    stub.error = KnowledgeError("cluster down", status_code=503)
    response = client.post("/deepgram/session", json={"scan_id": "scan-1"})
    assert response.status_code == 503
    assert response.json()["detail"] == "cluster down"


def test_create_report_stores_the_scan_context(
    client: TestClient, reports: MemoryReportStore
) -> None:
    response = client.post(
        "/deepgram/scan-1/reports",
        json={
            "concern_type": "wrong_pill",
            "summary": "The names do not match.",
            "user_description": "The bottle and the imprint disagree.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scan_id"] == "scan-1"
    assert body["snapshot"]["scan_id"] == "scan-1"
    assert body["snapshot"]["bottle"]["generic_name"] == "acetaminophen"
    listed = client.get("/deepgram/scan-1/reports").json()
    assert len(listed) == 1
    assert listed[0]["report_id"] == body["report_id"]


def test_create_report_unwraps_a_deepgram_payload(client: TestClient) -> None:
    response = client.post(
        "/deepgram/scan-1/reports",
        json={
            "arguments": {
                "concern_type": "quality",
                "summary": "Looks off.",
                "user_description": "Color is wrong.",
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["concern_type"] == "quality"


def test_create_report_autofills_the_problem_from_the_scan(client: TestClient) -> None:
    response = client.post("/deepgram/scan-1/reports", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["concern_type"] == "mismatch"
    assert body["summary"] == "The label and the reference records do not agree."
    assert body["user_description"].startswith("Bottle: the label says acetaminophen 500 mg.")
    assert "Imprint:" in body["user_description"]
    assert "Pill:" in body["user_description"]


def test_create_report_autofills_an_empty_deepgram_call(client: TestClient) -> None:
    response = client.post("/deepgram/scan-1/reports", json={"arguments": {}})
    assert response.status_code == 200
    assert response.json()["concern_type"] == "mismatch"


def test_reports_404_when_the_scan_is_missing(client: TestClient, stub: StubStore) -> None:
    stub.doc = None
    assert client.get("/deepgram/scan-x/reports").status_code == 404
