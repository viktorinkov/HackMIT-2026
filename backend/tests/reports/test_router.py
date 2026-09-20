from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.knowledge.client import KnowledgeError
from backend.reports.router import router
from backend.reports.store import MemoryReportStore, get_report_store
from backend.scans.store import get_scan_store


class StubScans:
    def __init__(self, doc: dict[str, Any] | None = None, error: KnowledgeError | None = None):
        self.doc = doc
        self.error = error

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        if self.error:
            raise self.error
        return self.doc


class FailingReports(MemoryReportStore):
    async def add(self, report: Any) -> Any:
        raise KnowledgeError("could not store the report: cluster down", status_code=503)

    async def list_for_scan(self, scan_id: str) -> list[Any]:
        raise KnowledgeError("could not list reports: boom", status_code=502)


@pytest.fixture
def scans() -> StubScans:
    return StubScans(doc={"scan_id": "scan-1", "status": "complete"})


@pytest.fixture
def reports() -> MemoryReportStore:
    return MemoryReportStore()


@pytest.fixture
def client(scans: StubScans, reports: MemoryReportStore) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scan_store] = lambda: scans
    app.dependency_overrides[get_report_store] = lambda: reports
    with TestClient(app) as test_client:
        yield test_client


def test_submit_stores_only_provenance(client: TestClient, reports: MemoryReportStore) -> None:
    response = client.post(
        "/scans/scan-1/reports",
        json={
            "purchased_on": "2026-03-12",
            "purchase_location": {
                "label": "CVS on Mass Ave",
                "city": "Cambridge",
                "region": "MA",
                "country": "US",
            },
            "seller": "CVS Pharmacy",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "report_id",
        "scan_id",
        "purchased_on",
        "purchase_location",
        "seller",
        "created_at",
    }
    assert body["scan_id"] == "scan-1"
    assert body["purchased_on"] == "2026-03-12"
    assert body["purchase_location"]["city"] == "Cambridge"
    assert body["seller"] == "CVS Pharmacy"
    assert [stored.report_id for stored in reports._reports.values()] == [body["report_id"]]


def test_submit_with_nothing_known_is_valid(client: TestClient) -> None:
    response = client.post("/scans/scan-1/reports", json={})
    assert response.status_code == 201
    body = response.json()
    assert body["purchased_on"] is None
    assert body["purchase_location"] is None
    assert body["seller"] is None


def test_submit_twice_files_two_reports(client: TestClient) -> None:
    first = client.post("/scans/scan-1/reports", json={"seller": "CVS Pharmacy"})
    second = client.post("/scans/scan-1/reports", json={"seller": "a friend"})
    assert first.status_code == second.status_code == 201
    assert first.json()["report_id"] != second.json()["report_id"]


def test_submit_keeps_scan_id_from_the_path(client: TestClient) -> None:
    response = client.post(
        "/scans/scan-1/reports",
        json={"scan_id": "scan-other", "seller": "a friend"},
    )
    assert response.status_code == 201
    assert response.json()["scan_id"] == "scan-1"


def test_submit_404s_when_the_scan_is_missing(client: TestClient, scans: StubScans) -> None:
    scans.doc = None
    assert client.post("/scans/scan-x/reports", json={}).status_code == 404


def test_submit_surfaces_a_scan_store_error(client: TestClient, scans: StubScans) -> None:
    scans.error = KnowledgeError("cluster down", status_code=503)
    response = client.post("/scans/scan-1/reports", json={})
    assert response.status_code == 503
    assert response.json()["detail"] == "cluster down"


def test_submit_surfaces_a_report_store_error(scans: StubScans) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scan_store] = lambda: scans
    app.dependency_overrides[get_report_store] = lambda: FailingReports()
    with TestClient(app) as client:
        response = client.post("/scans/scan-1/reports", json={"seller": "CVS"})
        assert response.status_code == 503
        assert "could not store the report" in response.json()["detail"]
        assert client.get("/scans/scan-1/reports").status_code == 502


def test_list_is_empty_before_any_submit(client: TestClient) -> None:
    response = client.get("/scans/scan-1/reports")
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_list_returns_newest_first(client: TestClient) -> None:
    first = client.post("/scans/scan-1/reports", json={"seller": "first"}).json()
    second = client.post("/scans/scan-1/reports", json={"seller": "second"}).json()
    listed = client.get("/scans/scan-1/reports").json()["results"]
    assert [item["report_id"] for item in listed] == [second["report_id"], first["report_id"]]
    assert listed[0]["seller"] == "second"


def test_list_404s_when_the_scan_is_missing(client: TestClient, scans: StubScans) -> None:
    scans.doc = None
    assert client.get("/scans/scan-x/reports").status_code == 404
