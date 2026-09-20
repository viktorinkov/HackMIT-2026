"""The committed demo fixtures are a product surface, not test data.

They are what a judge sees when the venue network is gone, so they are held to the
same rules as builder output: model-valid, no dangling edges, no sensitive label
fields, no assurance wording, and short labels.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest

from backend.graph.models import (
    MAX_LABEL_CHARS,
    REPORT_KINDS,
    ExpandResponse,
    GraphResponse,
    NodeDetail,
    SearchGraphResponse,
)
from backend.graph.service import FIXTURES, GraphContext, GraphService

PRESENTER_LOTS = ("lot:D2402430", "lot:D2402999", "lot:Z400069", "lot:H02605")
REC_LEVO = "rec:fda-enf-D-0785-2026"
REC_WHO = "rec:who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd"
REC_NAFDAC_HEALMOXY = "rec:nafdac-18658"

ASSURANCE_RE = re.compile(r"\b(?:safe|genuine|verified|authentic|authenticated)\b", re.I)
# Fields `scans/normalizer.sanitize_bottle` drops at the API boundary.
SENSITIVE_KEYS = ("rx_number", "pharmacy", "directions", "other_label_text", "notes",
                  "patient_name")


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def graph() -> GraphResponse:
    return GraphResponse.model_validate(load("demo_graph.json"))


@pytest.fixture(scope="module")
def details() -> dict[str, NodeDetail]:
    return {key: NodeDetail.model_validate(value) for key, value in load("demo_nodes.json").items()}


@pytest.fixture(scope="module")
def expansions() -> dict[str, ExpandResponse]:
    return {
        key: ExpandResponse.model_validate(value)
        for key, value in load("demo_expansions.json").items()
    }


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


# --------------------------------------------------------------------------- shape


def test_all_four_fixture_files_are_committed() -> None:
    assert sorted(path.name for path in Path(FIXTURES).glob("*.json")) >= [
        "demo_expansions.json", "demo_graph.json", "demo_nodes.json", "demo_search.json",
    ]


def test_the_committed_fixtures_validate_against_the_models(
    graph: GraphResponse, details: dict[str, NodeDetail], expansions: dict[str, ExpandResponse]
) -> None:
    SearchGraphResponse.model_validate(load("demo_search.json"))
    assert len(graph.nodes) >= 40
    assert all(key == value.id for key, value in details.items())
    assert all(key == value.anchor for key, value in expansions.items())


def test_the_demo_graph_declares_itself_as_demo_data(graph: GraphResponse) -> None:
    assert graph.meta.source == "demo"
    assert graph.meta.demo is True
    assert graph.meta.device_id == "peel-graph-demo"
    assert graph.meta.notice
    scans = [node for node in graph.nodes if node.type == "scan"]
    assert len(scans) == 6
    assert all(node.demo is True for node in scans)
    # The records themselves are real regulator documents, not staged ones.
    assert all(node.demo is False for node in graph.nodes if node.type == "record")


def test_node_ids_and_link_ids_are_unique_and_every_endpoint_exists(
    graph: GraphResponse,
) -> None:
    ids = [node.id for node in graph.nodes]
    assert len(ids) == len(set(ids))
    link_ids = [link.id for link in graph.links]
    assert len(link_ids) == len(set(link_ids))
    known = set(ids)
    for link in graph.links:
        assert link.source in known, link.id
        assert link.target in known, link.id
        assert link.id == f"{link.source}>{link.kind}>{link.target}"


def test_no_expansion_or_search_response_has_a_dangling_endpoint(
    graph: GraphResponse, expansions: dict[str, ExpandResponse]
) -> None:
    base = {node.id for node in graph.nodes}
    for anchor, response in expansions.items():
        known = base | {node.id for node in response.nodes}
        assert anchor in known, anchor
        for link in response.links:
            assert link.source in known, (anchor, link.id)
            assert link.target in known, (anchor, link.id)
    search = SearchGraphResponse.model_validate(load("demo_search.json"))
    known = base | {node.id for node in search.nodes}
    for hit in search.hits:
        assert hit.node_id in known, hit.node_id
    for node_id in search.highlight:
        assert node_id in known, node_id


def test_every_label_fits_the_contract(graph: GraphResponse,
                                       expansions: dict[str, ExpandResponse]) -> None:
    for node in graph.nodes:
        assert len(node.label) <= MAX_LABEL_CHARS, node.id
    for response in expansions.values():
        for node in response.nodes:
            assert len(node.label) <= MAX_LABEL_CHARS, node.id


def test_the_four_presenter_lot_ids_exist_with_expansions_and_notes(
    graph: GraphResponse, details: dict[str, NodeDetail],
    expansions: dict[str, ExpandResponse]
) -> None:
    known = {node.id for node in graph.nodes}
    for lot in PRESENTER_LOTS:
        assert lot in known, lot
        assert lot in details, lot
        assert lot in expansions, lot
    assert "reg:fda" in expansions


# --------------------------------------------------------------------------- safety


def test_no_fixture_string_ever_says_safe_genuine_or_verified() -> None:
    for name in ("demo_graph.json", "demo_nodes.json", "demo_expansions.json",
                 "demo_search.json"):
        for text in _strings(load(name)):
            assert not ASSURANCE_RE.search(text), (name, text)


def test_no_fixture_carries_a_sensitive_label_field() -> None:
    # The rule is about the *fields* `sanitize_bottle` drops, not about the
    # words in them. A shop somebody names in their own purchase report may
    # perfectly well be called "… Pharmacy"; that text is theirs, and it
    # reaches the graph through `peel-reports`, never through a bottle label.
    for name in ("demo_graph.json", "demo_nodes.json", "demo_expansions.json",
                 "demo_search.json"):
        blob = (FIXTURES / name).read_text(encoding="utf-8").casefold()
        for key in SENSITIVE_KEYS:
            assert f'"{key}":' not in blob, (name, key)


def test_every_alert_edge_runs_from_a_lot_to_a_record(graph: GraphResponse) -> None:
    alerts = [link for link in graph.links if link.alert]
    assert alerts
    for link in alerts:
        assert link.source.startswith("lot:"), link.id
        assert link.target.startswith("rec:"), link.id
        assert link.kind == "exact_lot"
        assert link.strong is True
        assert link.scan_ids, link.id


def test_the_uncorroborated_edges_are_weak_and_carry_no_alert(graph: GraphResponse) -> None:
    weak_kinds = {"lot_only_match", "lot_listed", "all_lots_sibling", "product_line_match"}
    for link in graph.links:
        if link.kind in weak_kinds:
            assert link.alert is False, link.id
            assert link.strong is False, link.id


def test_the_sibling_bottle_has_no_lot_edge_but_shares_the_record(
    graph: GraphResponse,
) -> None:
    from_sibling = [link for link in graph.links if link.source == "lot:D2402999"]
    assert from_sibling == []
    product_edge = next(
        link for link in graph.links
        if link.source == "product:167290457" and link.target == REC_LEVO
    )
    assert product_edge.kind == "ndc_in_description"
    assert product_edge.alert is False and product_edge.strong is False
    assert len(product_edge.scan_ids) == 2


def test_the_chlorpromazine_lot_carries_one_alert_and_one_collision(
    graph: GraphResponse,
) -> None:
    edges = {link.kind: link for link in graph.links if link.source == "lot:Z400069"}
    assert edges["exact_lot"].alert is True
    assert edges["lot_only_match"].alert is False
    assert edges["exact_lot"].target != edges["lot_only_match"].target


def test_two_regulators_converge_on_the_healmoxy_batch(graph: GraphResponse) -> None:
    edges = [link for link in graph.links if link.source == "lot:H02605"]
    assert {link.target for link in edges} == {REC_WHO, REC_NAFDAC_HEALMOXY}
    assert all(link.alert for link in edges)


def test_a_falsified_alert_only_states_the_manufacturer(graph: GraphResponse) -> None:
    maker = next(node for node in graph.nodes if node.id == "mfr:maxheal pharmaceuticals")
    assert maker.sublabel == "name printed on the label"
    edges = [link for link in graph.links if link.target == maker.id
             and link.source.startswith("rec:")]
    assert edges
    assert {link.kind for link in edges} == {"stated_manufacturer"}
    assert all(link.alert is False and link.strong is False for link in edges)


def test_the_mismatch_scan_produces_a_conflicts_with_edge(graph: GraphResponse) -> None:
    conflict = next(link for link in graph.links if link.kind == "conflicts_with")
    assert {conflict.source, conflict.target} == {"med:temazepam", "med:ibuprofen"}
    assert conflict.alert is False


def test_no_report_edge_is_ever_strong_or_alerting(graph: GraphResponse) -> None:
    edges = [link for link in graph.links if link.kind in REPORT_KINDS]
    assert edges, "the demo graph should show where the medicines were bought"
    for link in edges:
        assert link.alert is False, link.id
        assert link.strong is False, link.id


def test_a_seller_is_never_styled_as_a_risk(graph: GraphResponse) -> None:
    for node in graph.nodes:
        if node.type in ("seller", "place"):
            assert node.severity is None, node.id
            assert node.verdict is None, node.id
            assert node.risk_level is None, node.id
            assert node.match_tier is None, node.id
            assert node.demo is True, node.id
    sellers = [node for node in graph.nodes if node.type == "seller"]
    places = [node for node in graph.nodes if node.type == "place"]
    assert len(sellers) == 2 and len(places) == 3
    # One shop joins the two levothyroxine scans; that is the whole point of it.
    riverside = next(node for node in sellers if "Riverside" in node.label)
    assert len(riverside.scan_ids) == 2


def test_a_purchase_country_merges_with_the_regulatory_country_node(
    graph: GraphResponse,
) -> None:
    known = {node.id for node in graph.nodes}
    country_edges = [
        link for link in graph.links
        if link.kind == "located_in" and link.target.startswith("country:")
    ]
    assert country_edges
    for link in country_edges:
        assert link.target in known, link.id
    assert "country:cameroon" in {link.target for link in country_edges}


def test_the_crowd_cluster_carries_counts_and_no_one_elses_scan(
    graph: GraphResponse, details: dict[str, NodeDetail]
) -> None:
    cluster = next(
        node for node in graph.nodes
        if node.type == "cluster" and node.attrs.get("relation") == "reports"
    )
    assert cluster.count == 4
    assert cluster.attrs["flagged"] == 2
    assert cluster.scan_ids == []
    # Every number the fixture shows is one the live code could publish: a
    # group of one on either side of the flagged/unflagged split is suppressed
    # (`expand._publishable_flagged`), and there is no per-medicine breakdown.
    assert cluster.attrs["count"] - cluster.attrs["flagged"] >= 2
    assert "medicines" not in cluster.attrs
    assert cluster.id in details
    note = details[cluster.id]
    assert note.badges == []
    assert note.properties == []
    assert "has not checked" in (note.body or "")


def test_the_seller_notes_never_say_anything_about_the_seller(
    details: dict[str, NodeDetail]
) -> None:
    sellers = [detail for detail in details.values() if detail.type == "seller"]
    assert sellers
    for detail in sellers:
        assert detail.badges == [], detail.id
        assert detail.next_steps == [], detail.id
        assert "report you filed" in (detail.body or ""), detail.id
        assert "has not checked" in (detail.body or ""), detail.id


def test_the_clean_scan_is_neutral_not_positive(graph: GraphResponse) -> None:
    clean = [node for node in graph.nodes if node.verdict == "no_adverse_findings"]
    assert clean
    for node in clean:
        assert node.risk_level == "low"
        assert not {"ok", "clear", "pass", "good"} & set(node.attrs)


# --------------------------------------------------------------------------- notes


def test_every_scan_record_lot_regulator_seller_and_place_node_has_a_note(
    graph: GraphResponse, details: dict[str, NodeDetail]
) -> None:
    wanted = [node for node in graph.nodes
              if node.type in ("scan", "record", "lot", "regulator", "seller", "place")]
    missing = [node.id for node in wanted if node.id not in details]
    assert missing == []
    assert all(detail.notice for detail in details.values())


def test_who_notes_carry_the_licence_line_and_never_the_body(
    details: dict[str, NodeDetail]
) -> None:
    who = details[REC_WHO]
    assert who.sources
    assert who.sources[0].attribution == "World Health Organization, CC BY-NC-SA 3.0 IGO"
    assert who.body and len(who.body) <= 400
    assert details["reg:who"].properties


def test_fda_sources_are_labelled_as_json(details: dict[str, NodeDetail]) -> None:
    fda = details[REC_LEVO]
    assert fda.sources[0].link_label == "openFDA record (JSON)"
    assert fda.sources[0].url.startswith("https://api.fda.gov/")


def test_recall_scans_carry_next_steps_and_the_clean_scan_does_not_claim_anything(
    details: dict[str, NodeDetail]
) -> None:
    for node_id, detail in details.items():
        if detail.type == "scan" and "recall" in " ".join(detail.badges).casefold():
            assert len(detail.next_steps) >= 3, node_id
            assert any("pharmacist" in step for step in detail.next_steps), node_id
    clean = details["scan:demo-ibuprofen-i2"]
    assert clean.next_steps
    assert not ASSURANCE_RE.search(clean.body or "")


def test_every_source_url_is_http_or_https(details: dict[str, NodeDetail]) -> None:
    for detail in details.values():
        for item in detail.sources:
            assert item.url is None or item.url.startswith(("http://", "https://")), item.url


# --------------------------------------------------------------------------- served


def test_the_service_serves_every_fixture_without_elasticsearch() -> None:
    service = GraphService(GraphContext())
    assert service.demo_personal().meta.source == "demo"
    for lot in PRESENTER_LOTS:
        assert service.demo_expand(lot).anchor == lot
    assert service.demo_node(REC_LEVO).id == REC_LEVO
    answered = service.demo_search("subpotent thyroid tablets")
    assert answered.query == "subpotent thyroid tablets"
    assert REC_LEVO in [hit.node_id for hit in answered.hits]
    assert answered.highlight[-1].startswith("scan:")
    assert asyncio.run(service.universe(demo=True)).meta.source in ("snapshot", "live", "demo")
