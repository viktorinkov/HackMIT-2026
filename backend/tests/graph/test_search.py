from __future__ import annotations

from typing import Any

from backend.graph.models import GraphMeta, GraphNode, GraphResponse
from backend.graph.search import search_graph
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Reg
from backend.knowledge.search import Hit

LOT = "D2402430"


def record(
    record_id: str,
    *,
    title: str = "Recall notice",
    org: str = "FDA",
    severity: str = "high",
    **extra: Any,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        Reg.RECORD_ID: record_id,
        Reg.TITLE: title,
        Reg.SOURCE_ORG: org,
        Reg.SEVERITY: severity,
        Reg.RECENCY_DATE: "2026-09-01",
        Reg.URL: f"https://example.test/{record_id}",
        Reg.DOC_TYPE: "recall",
        Reg.MANUFACTURER: "Accord Healthcare Inc.",
        Reg.COUNTRIES: ["United States"],
    }
    doc.update(extra)
    return doc


def hit(source: dict[str, Any], match_kind: str, score: float = 1.0) -> Hit:
    return Hit(
        index="peel-regulatory",
        id=source[Reg.RECORD_ID],
        score=score,
        source=source,
        match_kind=match_kind,
        highlight="…subpotent levothyroxine tablets…",
    )


class StubSearch:
    def __init__(
        self,
        *,
        regulatory: list[Hit] | None = None,
        lot_hits: list[Hit] | None = None,
        ndc_hits: list[Hit] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._regulatory = regulatory or []
        self._lot_hits = lot_hits or []
        self._ndc_hits = ndc_hits or []

    async def search_regulatory(
        self,
        query: str,
        filters: Any = None,
        *,
        size: int = 10,
        rerank: bool | None = None,
    ) -> list[Hit]:
        self.calls.append(
            (
                "search_regulatory",
                {"query": query, "filters": filters, "size": size, "rerank": rerank},
            )
        )
        return list(self._regulatory)

    async def recalls_by_lot(
        self, lot: str, *, ndc9: str | None = None, drug_names: list[str] | None = None
    ) -> list[Hit]:
        self.calls.append(
            ("recalls_by_lot", {"lot": lot, "ndc9": ndc9, "drug_names": drug_names})
        )
        return list(self._lot_hits)

    async def recalls_by_ndc(self, ndc: Any) -> list[Hit]:
        self.calls.append(("recalls_by_ndc", {"ndc": ndc}))
        return list(self._ndc_hits)

    def called(self, name: str) -> bool:
        return any(called == name for called, _ in self.calls)

    def call(self, name: str) -> dict[str, Any]:
        return next(kwargs for called, kwargs in self.calls if called == name)


def personal_graph(*nodes: GraphNode) -> GraphResponse:
    return GraphResponse(nodes=list(nodes), links=[], meta=GraphMeta())


class Ctx:
    def __init__(self, *, search: Any = None, personal: Any = None, fail: bool = False) -> None:
        self.es = None
        self.search = search or StubSearch()
        self.scans = None
        self.settings = None
        self._personal = personal
        self._fail = fail

    async def personal(self, device_id: str) -> GraphResponse:
        if self._fail:
            raise KnowledgeError("Elasticsearch is unreachable", status_code=503)
        return self._personal or personal_graph()


def links_by_kind(response: Any, kind: str) -> list[Any]:
    return [link for link in response.links if link.kind == kind]


async def test_search_unions_an_exact_lot_lookup_for_a_code_shaped_query() -> None:
    search = StubSearch(
        regulatory=[hit(record("fda-enf-hybrid", title="Levothyroxine recall"), "hybrid", 2.2)],
        lot_hits=[hit(record("fda-enf-D-0785-2026", title="Exact lot"), "exact_lot", 10.0)],
    )
    response = await search_graph(Ctx(search=search), LOT, device_id=None)

    assert search.call("recalls_by_lot")["lot"] == LOT
    assert not search.called("recalls_by_ndc")
    assert {h.node_id for h in response.hits} == {
        "rec:fda-enf-hybrid",
        "rec:fda-enf-D-0785-2026",
    }
    # The lot leg carries no product context, so it can only say "lists the lot".
    lot_links = links_by_kind(response, "lot_listed")
    assert len(lot_links) == 1
    assert lot_links[0].source == f"lot:{LOT}"
    assert lot_links[0].alert is False and lot_links[0].strong is False
    assert not any(link.alert for link in response.links)


async def test_a_prose_query_runs_only_the_hybrid_leg() -> None:
    search = StubSearch(regulatory=[hit(record("fda-enf-1"), "hybrid", 2.2)])
    await search_graph(Ctx(search=search), "subpotent thyroid tablets", device_id=None)
    assert not search.called("recalls_by_lot")
    assert not search.called("recalls_by_ndc")


async def test_search_unions_the_product_lookup_for_an_ndc_shaped_query() -> None:
    search = StubSearch(
        ndc_hits=[
            hit(record("fda-enf-D-0785-2026"), "ndc_in_description", 10.0),
            hit(record("fda-enf-D-0999-2026"), "product_line_match", 1.0),
        ]
    )
    response = await search_graph(Ctx(search=search), "16729-457-15", device_id=None)

    assert search.called("recalls_by_ndc")
    kinds = {link.kind for link in response.links if link.source.startswith("product:")}
    assert kinds == {"ndc_in_description", "product_line_match"}
    assert not any(link.alert for link in response.links)
    assert any(node.id == "product:167290457" for node in response.nodes)


async def test_hit_scores_are_normalised_into_zero_to_one() -> None:
    search = StubSearch(
        regulatory=[
            hit(record("rec-a"), "hybrid", 2.2),
            hit(record("rec-b"), "hybrid", 1.1),
            hit(record("rec-c"), "hybrid", 0.0),
        ]
    )
    response = await search_graph(Ctx(search=search), "levothyroxine", device_id=None)
    scores = {h.node_id: h.score for h in response.hits}
    assert scores["rec:rec-a"] == 1.0
    assert scores["rec:rec-b"] == 0.5
    assert all(0.0 <= score <= 1.0 for score in scores.values())
    assert [h.node_id for h in response.hits] == ["rec:rec-a", "rec:rec-b", "rec:rec-c"]


async def test_search_never_returns_another_devices_scan_ids() -> None:
    search = StubSearch(regulatory=[hit(record("fda-enf-D-0785-2026"), "hybrid", 2.2)])
    mine = personal_graph(
        GraphNode(
            id="scan:scan-mine",
            type="scan",
            label="Levothyroxine 200 mcg",
            personal=True,
            scan_ids=["scan-mine"],
        ),
        GraphNode(
            id="rec:fda-enf-D-0785-2026",
            type="record",
            label="Levothyroxine recall",
            personal=True,
            scan_ids=["scan-mine"],
        ),
    )
    response = await search_graph(
        Ctx(search=search, personal=mine), "levothyroxine", device_id="dev-1"
    )

    assert set(response.highlight) == {"scan:scan-mine", "rec:fda-enf-D-0785-2026"}
    every_scan_id = {
        scan_id
        for node in response.nodes
        for scan_id in node.scan_ids
    } | {scan_id for link in response.links for scan_id in link.scan_ids}
    assert every_scan_id <= {"scan-mine"}
    assert "scan-theirs" not in response.model_dump_json()


async def test_highlight_is_empty_without_a_device_id() -> None:
    search = StubSearch(regulatory=[hit(record("rec-a"), "hybrid", 2.2)])
    response = await search_graph(Ctx(search=search), "levothyroxine", device_id=None)
    assert response.highlight == []


async def test_search_survives_an_unavailable_personal_graph() -> None:
    search = StubSearch(regulatory=[hit(record("rec-a"), "hybrid", 2.2)])
    response = await search_graph(
        Ctx(search=search, fail=True), "levothyroxine", device_id="dev-1"
    )
    assert response.highlight == []
    assert len(response.hits) == 1


async def test_the_hybrid_leg_is_capped_and_never_reranks() -> None:
    search = StubSearch(regulatory=[])
    await search_graph(Ctx(search=search), "levothyroxine", device_id=None, size=99)
    call = search.call("search_regulatory")
    assert call["size"] == 12 and call["rerank"] is False


async def test_a_falsified_hit_names_its_maker_as_stated_manufacturer() -> None:
    search = StubSearch(
        regulatory=[
            hit(
                record(
                    "who-mpa-1",
                    title="Falsified HEALMOXY",
                    org="WHO",
                    **{
                        Reg.DOC_TYPE: "falsified_alert",
                        Reg.MANUFACTURER: "MAXHEAL PHARMACEUTICALS (India) Limited",
                    },
                ),
                "hybrid",
                2.0,
            )
        ]
    )
    response = await search_graph(Ctx(search=search), "healmoxy", device_id=None)
    stated = links_by_kind(response, "stated_manufacturer")
    assert len(stated) == 1 and stated[0].alert is False
    assert not links_by_kind(response, "names_maker")
