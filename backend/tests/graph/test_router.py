from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.graph.builder import graph_from_scans
from backend.graph.router import router
from backend.graph.service import (
    GraphContext,
    GraphService,
    get_graph_service,
    reset_graph_service,
)
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import REPORTS_INDEX, SCANS_INDEX


class FakeEs:
    """Just enough of AsyncElasticsearch for `scan_docs` and `report_docs`."""

    def __init__(self, docs: list[dict[str, Any]] | None = None,
                 error: Exception | None = None,
                 reports: list[dict[str, Any]] | None = None,
                 reports_error: Exception | None = None) -> None:
        self.docs = docs or []
        self.reports = reports or []
        self.error = error
        self.reports_error = reports_error
        self.calls: list[dict[str, Any]] = []

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if kwargs.get("index") == REPORTS_INDEX:
            if self.reports_error:
                raise self.reports_error
            rows = self.reports
        else:
            if self.error:
                raise self.error
            rows = self.docs
        return {"hits": {"hits": [{"_source": doc} for doc in rows]}}

    def calls_on(self, index: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call.get("index") == index]


def scan_doc(scan_id: str = "scan-live-1") -> dict[str, Any]:
    return {
        "scan_id": scan_id,
        "device_id": "dev-1",
        "country": "United States",
        "status": "complete",
        "demo": False,
        "created_at": "2026-09-18T09:12:00Z",
        "norm": {"lot": "D2402430", "ndc9": "167290457", "generic_name": "ibuprofen",
                 "strength": "200 mg"},
        "research": {"verdict": "no_adverse_findings", "risk_level": "low"},
        "evidence": {"evidence_pack": {}},
    }


def make_app(service: GraphService) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_graph_service] = lambda: service
    return app


@pytest.fixture
def demo_client() -> Iterator[TestClient]:
    # An empty context is exactly the laptop with no .env and no cluster.
    service = GraphService(GraphContext())
    with TestClient(make_app(service)) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    reset_graph_service()


# --------------------------------------------------------------------------- demo path


def test_the_demo_graph_is_served_without_elasticsearch_configured(
    demo_client: TestClient,
) -> None:
    response = demo_client.get("/graph", params={"demo": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "demo"
    assert body["meta"]["demo"] is True
    assert body["meta"]["device_id"] == "peel-graph-demo"
    assert len(body["nodes"]) >= 40
    assert any(link["alert"] for link in body["links"])


def test_graph_requires_a_device_id_unless_demo_is_set(demo_client: TestClient) -> None:
    assert demo_client.get("/graph").status_code == 422
    assert demo_client.get("/graph", params={"demo": 1}).status_code == 200


def test_a_live_request_never_falls_back_to_demo_data(demo_client: TestClient) -> None:
    response = demo_client.get("/graph", params={"device_id": "dev-1"})
    assert response.status_code == 503
    assert "demo=1" in response.json()["detail"]


def test_the_demo_expansions_cover_the_four_presenter_lots(demo_client: TestClient) -> None:
    for lot in ("lot:D2402430", "lot:D2402999", "lot:Z400069", "lot:H02605"):
        response = demo_client.get("/graph/expand", params={"id": lot, "demo": 1})
        assert response.status_code == 200, lot
        assert response.json()["anchor"] == lot


def test_an_uncanned_demo_expansion_is_an_empty_neighbourhood(demo_client: TestClient) -> None:
    response = demo_client.get("/graph/expand", params={"id": "med:ibuprofen", "demo": 1})
    assert response.status_code == 200
    assert response.json() == {
        "anchor": "med:ibuprofen",
        "nodes": [],
        "links": [],
        "meta": response.json()["meta"],
    }


def test_the_demo_note_panel_answers_for_a_record_and_404s_otherwise(
    demo_client: TestClient,
) -> None:
    ok = demo_client.get(
        "/graph/node", params={"id": "rec:fda-enf-D-0785-2026", "demo": 1}
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["sources"][0]["link_label"] == "openFDA record (JSON)"
    assert demo_client.get(
        "/graph/node", params={"id": "med:nothing-here", "demo": 1}
    ).status_code == 404


def test_the_demo_search_answers_the_scripted_query(demo_client: TestClient) -> None:
    response = demo_client.get(
        "/graph/search", params={"q": "subpotent thyroid tablets", "demo": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "subpotent thyroid tablets"
    assert "rec:fda-enf-D-0785-2026" in [hit["node_id"] for hit in body["hits"]]
    assert body["highlight"][-1].startswith("scan:")


def test_the_demo_universe_degrades_instead_of_failing(demo_client: TestClient) -> None:
    response = demo_client.get("/graph/universe", params={"demo": 1})
    assert response.status_code == 200
    assert response.json()["meta"]["source"] in ("snapshot", "live", "demo")


# --------------------------------------------------------------------------- live path


async def test_the_live_graph_reads_scans_through_the_source_allow_list() -> None:
    es = FakeEs([scan_doc()])
    service = GraphService(GraphContext(es=es))  # type: ignore[arg-type]
    with TestClient(make_app(service)) as client:
        response = client.get("/graph", params={"device_id": "dev-1", "fresh": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "live"
    assert body["meta"]["scans"] == 1
    assert "scan:scan-live-1" in {node["id"] for node in body["nodes"]}

    sent = es.calls_on(SCANS_INDEX)[0]
    includes = sent["source"]["includes"]
    assert "bottle" not in includes and "imprint" not in includes
    assert "hardware.spectrum" not in includes
    assert "evidence.evidence_pack" in includes
    assert sent["query"]["bool"]["filter"] == [{"term": {"device_id": "dev-1"}}]
    assert sent["sort"][0] == {"created_at": "desc"}


async def test_the_personal_graph_is_cached_and_fresh_bypasses_the_cache() -> None:
    es = FakeEs([scan_doc()])
    service = GraphService(GraphContext(es=es))  # type: ignore[arg-type]
    with TestClient(make_app(service)) as client:
        client.get("/graph", params={"device_id": "dev-1"})
        client.get("/graph", params={"device_id": "dev-1"})
        # One build is one scans query (and one reports query behind it).
        assert len(es.calls_on(SCANS_INDEX)) == 1
        client.get("/graph", params={"device_id": "dev-1", "fresh": 1})
        assert len(es.calls_on(SCANS_INDEX)) == 2


def _purchase_report(scan_id: str = "scan-live-1") -> dict[str, Any]:
    return {
        "report_id": "rep-1",
        "scan_id": scan_id,
        "purchased_on": "2026-08-20",
        "seller": "Riverside Demo Pharmacy",
        "purchase_location": {"city": "Columbus", "region": "Ohio",
                              "country": "United States"},
        "created_at": "2026-09-03T10:00:00Z",
    }


async def test_the_personal_graph_carries_the_reports_filed_against_its_own_scans() -> None:
    es = FakeEs([scan_doc()], reports=[_purchase_report()])
    service = GraphService(GraphContext(es=es))  # type: ignore[arg-type]
    with TestClient(make_app(service)) as client:
        response = client.get("/graph", params={"device_id": "dev-1"})

    body = response.json()
    types = {node["id"]: node["type"] for node in body["nodes"]}
    assert "seller:riverside demo pharmacy|columbus|ohio|united-states" in types
    assert body["meta"]["counts"]["seller"] == 1
    assert body["meta"]["counts"]["place"] == 1
    report_edges = [link for link in body["links"] if link["kind"] == "bought_from"]
    assert report_edges and all(
        not link["strong"] and not link["alert"] for link in report_edges
    )

    sent = es.calls_on(REPORTS_INDEX)[0]
    assert sent["query"] == {"bool": {"filter": [{"terms": {"scan_id": ["scan-live-1"]}}]}}
    # An allow-list, like every other read in this package: `peel-reports` is
    # the index holding free text people typed, so a field added to it later
    # must not become readable here just by existing. These six are exactly
    # what `reports_graph.normalise_report` reads.
    assert sorted(sent["source"]["includes"]) == [
        "purchase_location.city",
        "purchase_location.country",
        "purchase_location.region",
        "purchased_on",
        "scan_id",
        "seller",
    ]
    # And the two fields the graph must never be able to read, refused by name
    # as well as left out.
    assert sorted(sent["source"]["excludes"]) == [
        "purchase_location.coordinates",
        "purchase_location.label",
    ]


async def test_a_field_added_to_the_reports_index_is_not_fetched_by_the_graph() -> None:
    """The allow-list is the boundary, so a new report field is unreachable."""
    from backend.graph.service import REPORT_SOURCE_INCLUDES

    for field in ("report_id", "created_at", "notes", "contact_email",
                  "purchase_location.lat", "purchase_location.lon"):
        assert field not in REPORT_SOURCE_INCLUDES, field


async def test_a_reports_outage_degrades_to_a_graph_without_sellers() -> None:
    from elasticsearch import TransportError

    es = FakeEs([scan_doc()], reports_error=TransportError("connection refused"))
    service = GraphService(GraphContext(es=es))  # type: ignore[arg-type]
    with TestClient(make_app(service)) as client:
        response = client.get("/graph", params={"device_id": "dev-1"})

    assert response.status_code == 200
    body = response.json()
    assert "scan:scan-live-1" in {node["id"] for node in body["nodes"]}
    assert not [node for node in body["nodes"] if node["type"] in ("seller", "place")]
    assert "seller" not in body["meta"]["counts"]


async def test_an_elasticsearch_failure_keeps_its_status_code() -> None:
    from elasticsearch import TransportError

    es = FakeEs(error=TransportError("connection refused"))
    service = GraphService(GraphContext(es=es))  # type: ignore[arg-type]
    with TestClient(make_app(service)) as client:
        response = client.get("/graph", params={"device_id": "dev-1"})
    assert response.status_code == 503


def test_a_read_path_without_a_search_client_is_a_clean_503() -> None:
    # `expand`, `node` and `search` dereference `ctx.search`; the service checks it
    # first so a half-built context is a 503 rather than a 500.
    es = FakeEs([])
    service = GraphService(GraphContext(es=es))  # type: ignore[arg-type]
    with TestClient(make_app(service)) as client:
        for path, params in (
            ("/graph/expand", {"id": "lot:D2402430"}),
            ("/graph/node", {"id": "rec:fda-enf-D-0785-2026"}),
            ("/graph/search", {"q": "levothyroxine"}),
        ):
            response = client.get(path, params=params)
            assert response.status_code == 503, (path, response.status_code)


def test_a_module_this_build_does_not_have_is_a_501() -> None:
    from backend.graph.service import _lazy

    with pytest.raises(KnowledgeError) as caught:
        _lazy("backend.graph.not_built_yet", "anything")
    assert caught.value.status_code == 501
    with pytest.raises(KnowledgeError) as missing_attr:
        _lazy("backend.graph.builder", "no_such_function")
    assert missing_attr.value.status_code == 501


def test_knowledge_errors_keep_their_status_code() -> None:
    class Failing(GraphService):
        async def personal(self, *args: Any, **kwargs: Any):  # type: ignore[override]
            raise KnowledgeError("the query was rejected", status_code=502)

    service = Failing(GraphContext())
    with TestClient(make_app(service)) as client:
        response = client.get("/graph", params={"device_id": "dev-1"})
    assert response.status_code == 502
    assert response.json()["detail"] == "the query was rejected"


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/graph/expand", {"id": "not-a-node-id", "demo": 1}),
        ("/graph/expand", {"id": "lot:" + "x" * 400, "demo": 1}),
        ("/graph/expand", {"demo": 1}),
        ("/graph/expand", {"id": "lot:D2402430", "limit": 99, "demo": 1}),
        ("/graph/node", {"id": "Rec:UPPER", "demo": 1}),
        ("/graph/search", {"q": "a", "demo": 1}),
        ("/graph/search", {"q": "levothyroxine", "size": 0, "demo": 1}),
        ("/graph", {"demo": 1, "max_nodes": 10}),
        ("/graph", {"demo": 1, "max_nodes": 5000}),
        ("/graph", {"device_id": "", "demo": 1}),
    ],
)
def test_out_of_bounds_parameters_are_rejected(
    demo_client: TestClient, path: str, params: dict[str, Any]
) -> None:
    assert demo_client.get(path, params=params).status_code == 422


def test_health_reports_what_this_build_can_serve(demo_client: TestClient) -> None:
    body = demo_client.get("/graph/health").json()
    assert body["online"] is False
    assert body["demo_device_id"] == "peel-graph-demo"
    assert "demo_graph.json" in body["fixtures"]
    assert set(body["modules"]) == {"universe", "expand", "detail", "search"}


def test_the_router_declares_no_catch_all_path() -> None:
    paths = {route.path for route in router.routes if hasattr(route, "path")}
    assert not any("{" in path for path in paths), paths
    assert {"/graph", "/graph/universe", "/graph/expand", "/graph/node", "/graph/search",
            "/graph/health"} <= paths


def test_the_one_dependency_resolves_without_touching_elasticsearch() -> None:
    reset_graph_service()
    service = get_graph_service()
    assert isinstance(service, GraphService)
    # Whether or not a .env exists here, the demo half must answer.
    assert service.demo_personal().meta.source == "demo"


# --------------------------------------------------------------------------- settings


def test_graph_settings_ignore_the_unrelated_keys_in_the_shared_dotenv(tmp_path) -> None:
    from backend.graph.settings import GraphSettings

    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=sk-not-a-real-key\n"
        "ELASTICSEARCH_URL=https://example.invalid\n"
        "FIRECRAWL_API_KEY=fc-nope\n"
        "GRAPH_PERSONAL_TTL_S=7\n",
        encoding="utf-8",
    )
    settings = GraphSettings(_env_file=str(env))  # type: ignore[call-arg]
    assert settings.personal_ttl_s == 7
    assert settings.demo_device_id == "peel-graph-demo"


def test_graph_settings_construct_against_this_checkouts_env_files() -> None:
    from backend.graph.settings import GraphSettings

    settings = GraphSettings()
    assert settings.universe_ttl_s == 21600
    assert settings.max_nodes >= 50


# --------------------------------------------------------------------------- cache


async def test_the_cache_single_flights_concurrent_callers() -> None:
    import asyncio

    from backend.graph.cache import TTLCache

    cache = TTLCache()
    calls = 0

    async def slow() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "value"

    results = await asyncio.gather(*(cache.get_or_set("k", 60, slow) for _ in range(10)))
    assert results == ["value"] * 10
    assert calls == 1
    assert await cache.get_or_set("k", 60, slow, fresh=True) == "value"
    assert calls == 2


async def test_the_cache_expires_entries_and_stays_bounded() -> None:
    from backend.graph.cache import TTLCache

    cache = TTLCache(max_entries=4)

    async def factory() -> int:
        return 1

    for index in range(12):
        await cache.get_or_set(f"k{index}", 60, factory)
    assert len(cache._values) <= 4
    cache.set("gone", "x", ttl_s=-1)
    assert cache.get("gone") is None
    cache.clear()
    assert cache.get("k11") is None


def test_graph_from_scans_is_what_the_live_path_returns() -> None:
    nodes, links, truncated = graph_from_scans([scan_doc()])
    assert truncated is False
    assert {node.id for node in nodes} >= {"scan:scan-live-1", "lot:D2402430"}
    assert all(link.alert is False for link in links)
