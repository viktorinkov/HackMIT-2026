from __future__ import annotations

import json
import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Scan
from backend.scans import router as router_module
from backend.scans.models import ScanCreate
from backend.scans.router import router
from backend.scans.store import get_scan_store

# Captured before the autouse fixture swaps it out.
REAL_LAUNCH = router_module._launch_research

BOTTLE = {
    "is_medication_container": True,
    "generic_name": "ibuprofen",
    "lot_number": "ab-1234",
    "ndc": "16729-457-01",
    "confidence": 0.9,
}


def scan_doc(scan_id: str = "scan-1", **kwargs: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        Scan.SCAN_ID: scan_id,
        Scan.DEVICE_ID: "dev-1",
        Scan.REVISION: 2,
        Scan.STATUS: "complete",
        Scan.DEMO: False,
        Scan.CREATED_AT: "2026-09-19T00:00:00Z",
        Scan.UPDATED_AT: "2026-09-19T00:01:00Z",
        Scan.BOTTLE: dict(BOTTLE) | {"rx_number_present": True},
        Scan.NORM: {"lot": "AB1234", "ndc9": "167290457", "generic_name": "ibuprofen"},
        Scan.RESEARCH: {"verdict": "no_adverse_findings", "risk_level": "low"},
    }
    doc.update(kwargs)
    return doc


class StubStore:
    def __init__(self, doc: dict[str, Any] | None = None, error: KnowledgeError | None = None):
        self.doc = doc
        self.error = error
        self.created: list[ScanCreate] = []
        self.list_kwargs: dict[str, Any] = {}
        self.listed: list[dict[str, Any]] = []
        self.cursor: str | None = None

    async def create(self, payload: ScanCreate) -> dict[str, Any]:
        if self.error:
            raise self.error
        self.created.append(payload)
        return dict(self.doc or scan_doc()) | {Scan.STATUS: "pending", Scan.REVISION: 1}

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        if self.error:
            raise self.error
        return self.doc

    async def list(self, **kwargs: Any) -> tuple[list[dict[str, Any]], str | None]:
        if self.error:
            raise self.error
        self.list_kwargs = kwargs
        return self.listed, self.cursor


@pytest.fixture
def stub() -> StubStore:
    return StubStore(doc=scan_doc())


@pytest.fixture
def client(stub: StubStore) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_scan_store] = lambda: stub
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def launched(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """The research pipeline is another engineer's module; never call the real one."""
    calls: list[tuple[str, bool]] = []

    def fake(app: Any, scan_id: str, *, force: bool = False) -> bool:
        calls.append((scan_id, force))
        return True

    monkeypatch.setattr(router_module, "_launch_research", fake)
    return calls


def test_post_scan_returns_202_and_starts_research(
    client: TestClient, stub: StubStore, launched: list[tuple[str, bool]]
) -> None:
    response = client.post("/scans", json={"device_id": "dev-1", "bottle": BOTTLE})
    assert response.status_code == 202
    body = response.json()
    assert body["scan_id"] == "scan-1"
    assert body["status"] == "pending"
    assert stub.created[0].device_id == "dev-1"
    assert launched == [("scan-1", False)]


def test_post_scan_rejects_an_empty_observation(client: TestClient) -> None:
    assert client.post("/scans", json={"device_id": "dev-1"}).status_code == 422


def test_post_scan_survives_a_missing_research_pipeline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_module, "_launch_research", lambda *a, **k: None)
    assert client.post("/scans", json={"device_id": "dev-1", "bottle": BOTTLE}).status_code == 202


def test_post_scan_surfaces_the_store_status_code(client: TestClient, stub: StubStore) -> None:
    stub.error = KnowledgeError("cluster down", status_code=503)
    response = client.post("/scans", json={"device_id": "dev-1", "bottle": BOTTLE})
    assert response.status_code == 503
    assert response.json()["detail"] == "cluster down"


def test_get_scan_returns_the_envelope(client: TestClient) -> None:
    body = client.get("/scans/scan-1").json()
    assert body["revision"] == 2
    assert body["norm"]["lot"] == "AB1234"
    assert body["research"]["verdict"] == "no_adverse_findings"


def test_get_scan_404s_when_unknown(client: TestClient, stub: StubStore) -> None:
    stub.doc = None
    assert client.get("/scans/scan-x").status_code == 404


def test_get_context_returns_the_handoff_object(client: TestClient) -> None:
    body = client.get("/scans/scan-1/context").json()
    assert set(body) >= {
        "scan_id", "revision", "status", "demo",
        "bottle", "imprint", "hardware", "drug_facts", "sources",
    }
    assert body["bottle"]["status"] == "read"
    assert "rx_number" not in json.dumps(body)


def test_get_context_as_string_wraps_a_json_string(client: TestClient) -> None:
    body = client.get("/scans/scan-1/context", params={"as_string": "true"}).json()
    assert set(body) == {"scan_context"}
    assert isinstance(body["scan_context"], str)
    assert json.loads(body["scan_context"])["scan_id"] == "scan-1"


def test_get_context_404s_when_unknown(client: TestClient, stub: StubStore) -> None:
    stub.doc = None
    assert client.get("/scans/scan-x/context").status_code == 404


def test_list_normalizes_the_filters(client: TestClient, stub: StubStore) -> None:
    stub.listed = [scan_doc(), scan_doc("scan-2")]
    stub.cursor = "cursor-1"
    body = client.get(
        "/scans",
        params={"device_id": "dev-1", "lot": "lot# ab-12 34", "ndc": "16729-457-01", "limit": 2},
    ).json()
    assert stub.list_kwargs == {
        "device_id": "dev-1",
        "lot": "AB1234",
        "ndc9": "167290457",
        "limit": 2,
        "after": None,
    }
    assert [row["scan_id"] for row in body["results"]] == ["scan-1", "scan-2"]
    assert body["results"][0]["lot"] == "AB1234"
    assert body["next"] == "cursor-1"


def test_list_without_filters_passes_none(client: TestClient, stub: StubStore) -> None:
    client.get("/scans")
    assert stub.list_kwargs == {
        "device_id": None, "lot": None, "ndc9": None, "limit": 20, "after": None
    }


@pytest.mark.parametrize("params", [{"lot": "??"}, {"ndc": "not-an-ndc"}])
def test_list_returns_nothing_for_an_unmatchable_filter(
    client: TestClient, stub: StubStore, params: dict[str, str]
) -> None:
    body = client.get("/scans", params=params).json()
    assert body == {"results": [], "next": None}
    assert stub.list_kwargs == {}


def test_list_rejects_an_out_of_range_limit(client: TestClient) -> None:
    assert client.get("/scans", params={"limit": 500}).status_code == 422


def test_research_endpoint_accepts_a_rerun(
    client: TestClient, launched: list[tuple[str, bool]]
) -> None:
    response = client.post("/scans/scan-1/research", json={"force": True})
    assert response.status_code == 202
    assert response.json() == {"scan_id": "scan-1", "status": "complete", "started": True}
    assert launched == [("scan-1", True)]


def test_research_endpoint_409s_when_already_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_module, "_launch_research", lambda *a, **k: False)
    response = client.post("/scans/scan-1/research", json={})
    assert response.status_code == 409
    assert "force=true" in response.json()["detail"]


def test_research_endpoint_503s_without_a_pipeline(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_module, "_launch_research", lambda *a, **k: None)
    assert client.post("/scans/scan-1/research", json={}).status_code == 503


def test_research_endpoint_404s_when_unknown(client: TestClient, stub: StubStore) -> None:
    stub.doc = None
    assert client.post("/scans/scan-x/research", json={}).status_code == 404


def test_launch_research_returns_none_without_the_pipeline_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Imported lazily so POST /scans works before research/pipeline.py lands."""
    monkeypatch.setitem(sys.modules, "backend.research.pipeline", None)
    assert REAL_LAUNCH(object(), "scan-1") is None


def test_launch_research_delegates_to_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []
    module = types.ModuleType("backend.research.pipeline")

    def launch_research(app: Any, scan_id: str, *, force: bool = False) -> bool:
        calls.append((scan_id, force))
        return True

    module.launch_research = launch_research  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "backend.research.pipeline", module)
    assert REAL_LAUNCH(object(), "scan-1", force=True) is True
    assert calls == [("scan-1", True)]
