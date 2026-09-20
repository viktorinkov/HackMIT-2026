from __future__ import annotations

import re
from typing import Any

import pytest

from backend.graph.builder import VERDICT_LABELS, graph_from_scans
from backend.graph.models import ALERT_CAPABLE_KINDS, MATCH_TIER_RANK, REPORT_KINDS
from backend.graph.reports_graph import attach_reports
from backend.research.evidence import verdict_from_evidence

# The ids, lots and NDCs below are the real seeded records, so a change in the
# corpus that breaks the demo also breaks these tests.
REC_LEVO = "fda-enf-D-0785-2026"
REC_CHLOR = "fda-enf-D-0361-2025"
REC_NAFDAC = "nafdac-17970"
REC_WHO = "who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd"


def reg_entry(
    record_id: str,
    match_kind: str,
    *,
    source_org: str = "FDA",
    doc_type: str = "recall",
    title: str = "Class II recall: Levothyroxine Sodium Tablets, USP, 200 mcg",
    severity: str = "high",
    manufacturer: str | None = "Accord Healthcare Inc.",
    drug_names: list[str] | None = None,
    countries: list[str] | None = None,
    covers_all_lots: bool = False,
    summary: str = "Subpotent Drug",
    **extra: Any,
) -> dict[str, Any]:
    entry = {
        "record_id": record_id,
        "url": f"https://api.fda.gov/drug/enforcement.json?search={record_id}",
        "source_org": source_org,
        "doc_type": doc_type,
        "title": title,
        "summary": summary,
        "severity": severity,
        "status": "ongoing",
        "drug_names": drug_names if drug_names is not None else ["levothyroxine sodium"],
        "manufacturer": manufacturer,
        "countries": countries if countries is not None else ["United States"],
        "recency_date": "2026-09-02T00:00:00Z",
        "age_days": 17,
        "freshness": "this_month",
        "match_kind": match_kind,
        "lots_shown": ["D2402430"],
        "lot_count": 4,
        "covers_all_lots": covers_all_lots,
    }
    entry.update(extra)
    return entry


def pack(
    *,
    lot: str | None = "D2402430",
    ndc9: str | None = "167290457",
    generic: str | None = "levothyroxine sodium",
    exact_lot_hits: list[dict[str, Any]] | None = None,
    all_lots_hits: list[dict[str, Any]] | None = None,
    ndc_hits: list[dict[str, Any]] | None = None,
    regulatory_hits: list[dict[str, Any]] | None = None,
    web_hits: list[dict[str, Any]] | None = None,
    ndc_directory: list[dict[str, Any]] | None = None,
    pill: dict[str, Any] | None = None,
    recall_lookup_failed: bool = False,
    imprint_norm: str | None = None,
) -> dict[str, Any]:
    return {
        "index_date": "2026-09-19",
        "label": {
            "lot": lot,
            "ndc9": ndc9,
            "ndc11": None,
            "imprint_norm": imprint_norm,
            "drug_names": [generic] if generic else [],
            "generic_name": generic,
        },
        "hardware": None,
        "exact_lot_hits": exact_lot_hits or [],
        "all_lots_hits": all_lots_hits or [],
        "ndc_hits": ndc_hits or [],
        "ndc_directory": ndc_directory or [],
        "ndc_status": None,
        "pill": pill or {"candidates": [], "rung": 0, "skipped": "not run"},
        "regulatory_hits": regulatory_hits or [],
        "web_hits": web_hits or [],
        "prior_scans": {"total": 0, "by_verdict": {}},
        "recall_lookup_failed": recall_lookup_failed,
    }


def scan(
    scan_id: str = "scan-1",
    *,
    created_at: str = "2026-09-18T09:12:00Z",
    status: str = "complete",
    lot: str | None = "D2402430",
    ndc9: str | None = "167290457",
    ndc_raw: str | None = "16729-457-15",
    generic: str | None = "levothyroxine sodium",
    brand: str | None = None,
    manufacturer: str | None = "Accord Healthcare Inc.",
    imprint: str | None = None,
    country: str | None = "United States",
    verdict: str = "recall_match",
    evidence_pack: dict[str, Any] | None = None,
    research: dict[str, Any] | None = None,
    demo: bool = True,
    expired: bool | None = False,
    hardware: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "scan_id": scan_id,
        "device_id": "peel-graph-demo",
        "country": country,
        "status": status,
        "demo": demo,
        "created_at": created_at,
        "norm": {
            "lot": lot,
            "ndc9": ndc9,
            "ndc_raw": ndc_raw,
            "generic_name": generic,
            "brand_name": brand,
            "manufacturer": manufacturer,
            "imprint_norm": imprint,
            "strength": "200 mcg",
            "expired": expired,
            "colors": [],
            "shape": None,
        },
        "hardware": hardware
        if hardware is not None
        else {
            "status": "substandard",
            "degraded": True,
            "model": "mock-spectrometry",
            "limitations": "Simulated result; no physical measurement was performed.",
            "confidence": 0.4,
            "pill_type": "tablet",
        },
        "research": research
        if research is not None
        else {"verdict": verdict, "risk_level": "high", "headline": "A recall names this lot."},
        "evidence": {"evidence_pack": evidence_pack if evidence_pack is not None else pack()},
    }
    doc.update(extra)
    return doc


def by_id(items: list[Any]) -> dict[str, Any]:
    return {item.id: item for item in items}


# --------------------------------------------------------------------------- the invariant

LEVO_EXACT = reg_entry(REC_LEVO, "exact_lot")
LEVO_NDC_SIBLING = reg_entry(REC_LEVO, "ndc_in_description")
LEVO_HYBRID = reg_entry(REC_LEVO, "hybrid")

INVARIANT_PACKS: list[tuple[str, dict[str, Any]]] = [
    ("a corroborated lot hit", pack(exact_lot_hits=[LEVO_EXACT])),
    (
        "the hero record reached three ways at once",
        pack(
            exact_lot_hits=[LEVO_EXACT],
            ndc_hits=[LEVO_NDC_SIBLING],
            regulatory_hits=[LEVO_HYBRID],
        ),
    ),
    (
        "a bare lot-string collision",
        pack(lot="Z400069", exact_lot_hits=[reg_entry(REC_NAFDAC, "lot_only_match")]),
    ),
    (
        "an all-lots recall on this product",
        pack(all_lots_hits=[reg_entry(REC_LEVO, "all_lots_product", covers_all_lots=True)]),
    ),
    (
        "an all-lots recall reached only through a sibling NDC",
        pack(all_lots_hits=[reg_entry(REC_LEVO, "all_lots_sibling", covers_all_lots=True)]),
    ),
    # The third recall branch: no lot hit, no all-lots hit, but an NDC hit that
    # both covers all lots and was reached precisely.
    (
        "an ndc hit that covers all lots",
        pack(ndc_hits=[reg_entry(REC_LEVO, "ndc_in_description", covers_all_lots=True)]),
    ),
    (
        "an ndc hit that covers all lots but is only a sibling",
        pack(ndc_hits=[reg_entry(REC_LEVO, "product_line_match", covers_all_lots=True)]),
    ),
    ("nothing at all", pack()),
    ("a lookup that never ran", pack(recall_lookup_failed=True)),
    ("an unreadable label", pack(lot=None, ndc9=None, generic=None)),
]


@pytest.mark.parametrize(("name", "evidence"), INVARIANT_PACKS, ids=[n for n, _ in INVARIANT_PACKS])
def test_an_alert_link_exists_exactly_when_the_evidence_supports_recall_match(
    name: str, evidence: dict[str, Any]
) -> None:
    _, links, _ = graph_from_scans([scan(evidence_pack=evidence)])
    expected = verdict_from_evidence(evidence, has_mismatch=False)[0] == "recall_match"
    assert any(link.alert for link in links) is expected, name


def test_only_alert_capable_kinds_ever_carry_an_alert() -> None:
    for _, evidence in INVARIANT_PACKS:
        _, links, _ = graph_from_scans([scan(evidence_pack=evidence)])
        for link in links:
            if link.alert:
                assert link.kind in ALERT_CAPABLE_KINDS


PURCHASE_REPORT = {
    "report_id": "rep-1",
    "scan_id": "scan-1",
    "purchased_on": "2026-08-20",
    "seller": "Riverside Demo Pharmacy",
    "purchase_location": {"city": "Columbus", "region": "Ohio", "country": "United States"},
    "created_at": "2026-09-03T10:00:00Z",
}


@pytest.mark.parametrize(("name", "evidence"), INVARIANT_PACKS, ids=[n for n, _ in INVARIANT_PACKS])
def test_reports_never_change_which_links_are_alerts(name: str, evidence: dict[str, Any]) -> None:
    """R5: attaching a purchase report is additive, and the invariant still holds."""
    nodes, links, _ = graph_from_scans([scan(evidence_pack=evidence)])
    before = {link.id for link in links if link.alert}

    with_reports, links_after = attach_reports(nodes, links, [PURCHASE_REPORT], ["scan-1"])
    expected = verdict_from_evidence(evidence, has_mismatch=False)[0] == "recall_match"

    assert {link.id for link in links_after if link.alert} == before, name
    assert any(link.alert for link in links_after) is expected, name
    # And nothing the report minted is strong, alerting or tiered.
    for link in links_after:
        if link.kind in REPORT_KINDS:
            assert link.alert is False and link.strong is False, name
    for node in with_reports:
        if node.type in ("seller", "place"):
            assert node.match_tier is None and node.severity is None, name


def test_an_ndc_hit_covering_all_lots_is_the_alert_the_verdict_counts() -> None:
    evidence = pack(ndc_hits=[reg_entry(REC_LEVO, "ndc_in_description", covers_all_lots=True)])
    _, links, _ = graph_from_scans([scan(evidence_pack=evidence)])
    alerts = [link for link in links if link.alert]
    assert [link.kind for link in alerts] == ["ndc_in_description"]
    assert alerts[0].source == "product:167290457"
    assert alerts[0].target == f"rec:{REC_LEVO}"


# --------------------------------------------------------------------------- merge


def test_one_record_reached_three_ways_keeps_its_best_tier_and_one_alert() -> None:
    evidence = pack(
        exact_lot_hits=[LEVO_EXACT], ndc_hits=[LEVO_NDC_SIBLING], regulatory_hits=[LEVO_HYBRID]
    )
    nodes, links, _ = graph_from_scans([scan(evidence_pack=evidence)])
    record = by_id(nodes)[f"rec:{REC_LEVO}"]
    assert record.match_tier == "match"
    assert record.severity == "high"
    alerts = [link for link in links if link.alert]
    assert len(alerts) == 1
    assert alerts[0].kind == "exact_lot"
    # The same record node, also reached weakly from the product line.
    weak = [link for link in links if link.target == record.id and not link.alert]
    assert {link.kind for link in weak} == {"ndc_in_description", "related"}


def test_a_sibling_ndc_hit_on_the_same_record_is_never_an_alert() -> None:
    hero = scan("scan-hero", evidence_pack=pack(exact_lot_hits=[LEVO_EXACT],
                                                ndc_hits=[LEVO_NDC_SIBLING]))
    sibling = scan(
        "scan-sibling",
        lot="D2402999",
        verdict="no_adverse_findings",
        evidence_pack=pack(lot="D2402999", ndc_hits=[LEVO_NDC_SIBLING]),
    )
    _, links, _ = graph_from_scans([hero, sibling])
    product_edge = by_id(links)[f"product:167290457>ndc_in_description>rec:{REC_LEVO}"]
    assert product_edge.alert is False
    assert product_edge.strong is False
    assert product_edge.count == 2
    assert set(product_edge.scan_ids) == {"scan-hero", "scan-sibling"}
    # The sibling's own lot node reaches no record at all.
    assert not [link for link in links if link.source == "lot:D2402999"]


def test_an_alert_links_scan_ids_name_only_the_scans_that_qualified_it() -> None:
    hero = scan("scan-hero", evidence_pack=pack(exact_lot_hits=[LEVO_EXACT]))
    # A second device scan touches the same lot node without a corroborated hit.
    other = scan(
        "scan-other",
        ndc9=None,
        ndc_raw=None,
        generic="metformin",
        verdict="no_adverse_findings",
        evidence_pack=pack(
            ndc9=None,
            generic="metformin",
            exact_lot_hits=[reg_entry(REC_NAFDAC, "lot_only_match", source_org="NAFDAC")],
        ),
    )
    _, links, _ = graph_from_scans([hero, other])
    alert = next(link for link in links if link.alert)
    assert alert.scan_ids == ["scan-hero"]


def test_lot_only_match_and_exact_lot_live_on_one_lot_node() -> None:
    evidence = pack(
        lot="Z400069",
        ndc9="707101129",
        generic="chlorpromazine hydrochloride",
        exact_lot_hits=[
            reg_entry(REC_CHLOR, "exact_lot", drug_names=["chlorpromazine hydrochloride"]),
            reg_entry(
                REC_NAFDAC,
                "lot_only_match",
                source_org="NAFDAC",
                title="Recall of Various Products by Sun Pharma, Glenmark, and Zydus",
                drug_names=["various products"],
                manufacturer=None,
                countries=["Nigeria"],
            ),
        ],
    )
    doc = scan(lot="Z400069", ndc9="707101129", ndc_raw="70710-1129-1",
               generic="chlorpromazine hydrochloride", evidence_pack=evidence)
    nodes, links, _ = graph_from_scans([doc])
    out = {link.id: link for link in links if link.source == "lot:Z400069"}
    exact = out[f"lot:Z400069>exact_lot>rec:{REC_CHLOR}"]
    collision = out[f"lot:Z400069>lot_only_match>rec:{REC_NAFDAC}"]
    assert exact.alert is True and exact.strong is True
    assert collision.alert is False and collision.strong is False
    assert by_id(nodes)[f"rec:{REC_NAFDAC}"].match_tier == "context"


def test_an_unknown_match_kind_is_a_weak_related_link() -> None:
    evidence = pack(ndc_hits=[reg_entry(REC_LEVO, "a_kind_invented_next_week")])
    _, links, _ = graph_from_scans([scan(evidence_pack=evidence)])
    link = next(item for item in links if item.target == f"rec:{REC_LEVO}")
    assert link.kind == "related"
    assert link.strong is False and link.alert is False
    assert link.match_kind == "a_kind_invented_next_week"


def test_two_scans_of_one_ndc_share_one_product_node() -> None:
    first = scan("scan-1", evidence_pack=pack(exact_lot_hits=[LEVO_EXACT]))
    second = scan("scan-2", lot="D2402999", verdict="no_adverse_findings",
                  evidence_pack=pack(lot="D2402999"))
    nodes, _, _ = graph_from_scans([first, second])
    products = [node for node in nodes if node.type == "product"]
    assert len(products) == 1
    assert set(products[0].scan_ids) == {"scan-1", "scan-2"}
    makers = [node for node in nodes if node.type == "manufacturer"]
    assert [node.id for node in makers] == ["mfr:accord healthcare"]


def test_link_ids_are_deterministic_so_a_second_build_is_identical() -> None:
    docs = [scan("scan-1", evidence_pack=pack(exact_lot_hits=[LEVO_EXACT],
                                              ndc_hits=[LEVO_NDC_SIBLING]))]
    first = graph_from_scans(docs)
    second = graph_from_scans(docs)
    assert [n.model_dump() for n in first[0]] == [n.model_dump() for n in second[0]]
    assert [l.model_dump() for l in first[1]] == [l.model_dump() for l in second[1]]


# --------------------------------------------------------------------------- wording and risk


def test_a_falsified_alert_names_the_manufacturer_without_blaming_it() -> None:
    who = reg_entry(
        REC_WHO,
        "exact_lot",
        source_org="WHO",
        doc_type="falsified_alert",
        title="Medical Product Alert N°2/2025: Falsified HEALMOXY (Amoxicillin) Capsules 500mg",
        severity="critical",
        manufacturer="MAXHEAL PHARMACEUTICALS (India) Limited",
        drug_names=["amoxicillin", "healmoxy"],
        countries=["Cameroon", "Central African Republic", "India"],
        summary="Falsified HEALMOXY capsules detected in Cameroon.",
    )
    nafdac = reg_entry(
        "nafdac-18658",
        "exact_lot",
        source_org="NAFDAC",
        doc_type="falsified_alert",
        title="Public Alert No. 17/2025 – Falsified Batches of Healmoxy Capsules 500mg",
        severity="critical",
        manufacturer=(
            "Maxheal Pharmaceuticals (India), with batch numbers 023011 and H02605, "
            "found in Cameroon and H02605 in the Central African Republic (CAR)"
        ),
        drug_names=["batches of healmoxy"],
        countries=["Nigeria", "India", "Cameroon", "Central African Republic"],
    )
    doc = scan(
        "scan-healmoxy",
        lot="H02605",
        ndc9=None,
        ndc_raw=None,
        generic="amoxicillin",
        brand="HEALMOXY",
        manufacturer="MAXHEAL PHARMACEUTICALS",
        country="Cameroon",
        evidence_pack=pack(
            lot="H02605", ndc9=None, generic="amoxicillin",
            exact_lot_hits=[who, nafdac],
        ),
    )
    nodes, links, _ = graph_from_scans([doc])
    index = by_id(nodes)
    maker = index["mfr:maxheal pharmaceuticals"]
    assert maker.sublabel == "name printed on the label"
    maker_edges = [link for link in links if link.target == maker.id and link.source.startswith("rec:")]
    assert {link.kind for link in maker_edges} == {"stated_manufacturer"}
    assert all(link.strong is False and link.alert is False for link in maker_edges)
    # Both regulators converge on one lot node, and both edges are alerts.
    alerts = [link for link in links if link.alert]
    assert {link.target for link in alerts} == {f"rec:{REC_WHO}", "rec:nafdac-18658"}
    assert all(link.source == "lot:H02605" for link in alerts)
    assert {"country:cameroon", "country:central-african-republic"} <= set(index)


def test_a_record_only_links_to_a_medicine_a_scan_already_minted() -> None:
    entry = reg_entry(
        REC_NAFDAC,
        "lot_only_match",
        source_org="NAFDAC",
        drug_names=["various products", "batches of healmoxy"],
        manufacturer=None,
    )
    nodes, links, _ = graph_from_scans([scan(evidence_pack=pack(exact_lot_hits=[entry]))])
    assert "med:healmoxy" not in by_id(nodes)
    assert not [link for link in links if link.kind == "about"]


def test_a_manufacturer_node_is_not_minted_from_a_prose_fragment() -> None:
    entry = reg_entry(
        REC_NAFDAC,
        "lot_only_match",
        source_org="NAFDAC",
        manufacturer="recall of various products by three drug manufacturing companies",
    )
    nodes, _, _ = graph_from_scans(
        [scan(manufacturer=None, evidence_pack=pack(exact_lot_hits=[entry]))]
    )
    assert [node for node in nodes if node.type == "manufacturer"] == []


ASSURANCE_RE = re.compile(r"\b(?:safe|genuine|verified|authentic)\b", re.I)


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def test_no_label_or_attribute_the_builder_emits_ever_says_safe_or_genuine() -> None:
    docs = [
        scan("scan-1", evidence_pack=pack(exact_lot_hits=[LEVO_EXACT], ndc_hits=[LEVO_NDC_SIBLING])),
        scan("scan-2", verdict="no_adverse_findings", evidence_pack=pack()),
        scan("scan-3", verdict="mismatch_found", evidence_pack=pack()),
        scan("scan-4", verdict="insufficient_evidence", status="error", evidence_pack={}),
        scan("scan-5", status="pending", research={}, evidence_pack={}),
    ]
    nodes, links, _ = graph_from_scans(docs)
    for node in nodes:
        for text in _strings([node.label, node.sublabel, node.attrs, node.verdict]):
            assert not ASSURANCE_RE.search(text), text
    for link in links:
        for text in _strings([link.kind, link.match_kind]):
            assert not ASSURANCE_RE.search(text), text
    for text in VERDICT_LABELS.values():
        assert not ASSURANCE_RE.search(text), text


def test_no_adverse_findings_carries_no_positive_styling_hint() -> None:
    nodes, _, _ = graph_from_scans(
        [scan(verdict="no_adverse_findings", evidence_pack=pack())]
    )
    node = by_id(nodes)["scan:scan-1"]
    assert node.verdict == "no_adverse_findings"
    assert node.attrs["verdict_label"] == "Nothing found in the records searched"
    assert not {"ok", "clear", "pass", "good"} & set(node.attrs)


def test_expiry_and_hardware_degradation_are_separate_attributes() -> None:
    nodes, _, _ = graph_from_scans([scan(expired=True)])
    attrs = by_id(nodes)["scan:scan-1"].attrs
    assert attrs["expired"] is True
    assert attrs["hardware"]["degraded"] is True
    assert attrs["hardware"]["simulated"] is True
    assert attrs["hardware"]["model"] == "mock-spectrometry"


def test_scan_nodes_carry_demo_and_gain_no_thumb_url_today() -> None:
    nodes, _, _ = graph_from_scans([scan(demo=True), scan("scan-2", demo=False)])
    index = by_id(nodes)
    assert index["scan:scan-1"].demo is True
    assert index["scan:scan-2"].demo is False
    assert "thumb_url" not in index["scan:scan-1"].attrs


def test_a_thumb_url_is_passed_through_if_a_scan_ever_carries_one() -> None:
    nodes, _, _ = graph_from_scans([scan(thumb_url="blob:local/abc")])
    assert by_id(nodes)["scan:scan-1"].attrs["thumb_url"] == "blob:local/abc"


# --------------------------------------------------------------------------- degradation


def test_a_pending_scan_degrades_to_label_nodes_only() -> None:
    doc = scan("scan-pending", status="pending", research={}, evidence_pack={})
    nodes, links, _ = graph_from_scans([doc])
    types = {node.type for node in nodes}
    assert types == {"scan", "medicine", "product", "lot", "manufacturer", "country"}
    assert by_id(nodes)["scan:scan-pending"].status == "pending"
    assert by_id(nodes)["scan:scan-pending"].verdict is None
    assert all(link.alert is False for link in links)


def test_an_errored_scan_with_no_pack_still_gets_its_label_nodes() -> None:
    doc = scan("scan-error", status="error", research={"verdict": None}, evidence_pack=None)
    doc["evidence"] = {}
    nodes, _, _ = graph_from_scans([doc])
    assert "scan:scan-error" in by_id(nodes)
    assert "lot:D2402430" in by_id(nodes)
    assert not [node for node in nodes if node.type == "record"]


def test_a_scan_without_a_pack_falls_back_to_its_report_sources() -> None:
    research = {
        "verdict": "no_adverse_findings",
        "risk_level": "low",
        "sources": [
            {"id": REC_LEVO, "title": "Class II recall", "url": "https://api.fda.gov/x",
             "source_org": "FDA", "published_at": "2026-09-02"},
            {"id": "web-abc123", "title": "WHO alert", "url": "https://www.who.int/news/item/x",
             "source_org": "WHO", "published_at": "2025-04-23"},
        ],
    }
    doc = scan("scan-old", status="complete", research=research, evidence_pack={})
    nodes, links, _ = graph_from_scans([doc])
    index = by_id(nodes)
    assert index[f"rec:{REC_LEVO}"].match_tier == "context"
    assert any(node.type == "web_page" for node in nodes)
    cited = [link for link in links if link.kind == "cited"]
    assert len(cited) == 2
    assert all(link.strong is False and link.alert is False for link in cited)


def test_sensitive_label_fields_never_reach_a_node() -> None:
    doc = scan()
    # Whatever is on the document, the builder does not open these keys.
    doc["bottle"] = {
        "rx_number": "RX-99887766",
        "pharmacy": "Mercy Pharmacy, Cambridge MA",
        "patient_name": "A. Real Person",
        "directions": "Take one tablet daily",
        "other_label_text": "DR SMITH",
    }
    doc["imprint"] = {"notes": "photo taken at home"}
    doc["hardware"]["spectrum"] = [0.123456, 0.654321]
    nodes, links, _ = graph_from_scans([doc])
    blob = repr([node.model_dump() for node in nodes] + [link.model_dump() for link in links])
    for secret in ("RX-99887766", "Mercy Pharmacy", "A. Real Person", "Take one tablet",
                   "DR SMITH", "photo taken at home", "0.123456", "spectrum"):
        assert secret not in blob, secret


# --------------------------------------------------------------------------- caps


def test_ndc_hits_over_the_cap_become_one_cluster_node() -> None:
    hits = [reg_entry(f"fda-enf-D-{n:04d}-2026", "product_line_match") for n in range(9)]
    nodes, links, _ = graph_from_scans([scan(evidence_pack=pack(ndc_hits=hits))])
    records = [node for node in nodes if node.type == "record"]
    clusters = [node for node in nodes if node.type == "cluster"]
    assert len(records) == 5
    assert len(clusters) == 1
    assert clusters[0].count == 4
    assert clusters[0].label == "+4 more records"
    assert any(link.kind == "more" for link in links)


def test_the_global_cap_drops_context_nodes_of_the_oldest_scans_first() -> None:
    old = scan(
        "scan-old",
        created_at="2026-08-01T00:00:00Z",
        evidence_pack=pack(
            regulatory_hits=[
                reg_entry(f"fda-enf-OLD-{n}", "hybrid", countries=["Canada"]) for n in range(4)
            ]
        ),
    )
    new = scan(
        "scan-new",
        created_at="2026-09-18T00:00:00Z",
        lot="D2402431",
        evidence_pack=pack(lot="D2402431", exact_lot_hits=[LEVO_EXACT]),
    )
    full, _, truncated_full = graph_from_scans([old, new])
    assert truncated_full is False
    capped, links, truncated = graph_from_scans([old, new], max_nodes=len(full) - 3)
    assert truncated is True
    assert len(capped) <= len(full) - 3
    index = by_id(capped)
    # The scans and the corroborated record survive; only the old scan's context goes.
    assert "scan:scan-old" in index and "scan:scan-new" in index
    assert f"rec:{REC_LEVO}" in index
    dropped = {node.id for node in full} - set(index)
    assert dropped
    assert all(node_id.startswith("rec:fda-enf-OLD-") for node_id in dropped), dropped
    endpoints = {node.id for node in capped}
    assert all(link.source in endpoints and link.target in endpoints for link in links)


def test_the_link_cap_sheds_the_faintest_edges_and_keeps_alerts() -> None:
    docs = [
        scan(
            f"scan-{n}",
            created_at=f"2026-09-{10 + n:02d}T00:00:00Z",
            lot=f"D240240{n}",
            evidence_pack=pack(
                lot=f"D240240{n}",
                exact_lot_hits=[LEVO_EXACT],
                regulatory_hits=[reg_entry(f"fda-enf-CTX-{n}", "hybrid")],
            ),
        )
        for n in range(4)
    ]
    _, links, truncated = graph_from_scans(docs, max_links=12)
    assert truncated is True
    assert len(links) == 12
    assert any(link.alert for link in links)


# --------------------------------------------------------------------------- extras


def test_a_mismatch_becomes_a_conflicts_with_edge_between_two_medicines() -> None:
    pill = {
        "candidates": [
            {
                "pill_id": "471fa2f1-73a0-49be-89f3-d3e2cfdaeca0-0603-5892-0",
                "generic_name": "temazepam",
                "strength": "TEMAZEPAM 15 mg",
                "labeler": "Qualitest Pharmaceuticals",
                "match_kind": "imprint_exact",
            }
        ],
        "rung": 1,
        "shape_relaxed": False,
    }
    research = {
        "verdict": "mismatch_found",
        "risk_level": "medium",
        "headline": "The imprint does not match the label.",
        "mismatches": [
            {
                "field": "imprint",
                "bottle_claim": "ibuprofen 200 mg",
                "imprint_reference": "temazepam 15 mg",
                "hardware_report": None,
                "explanation": "The imprint 5892 V is listed as temazepam.",
                "source_ids": [],
            }
        ],
    }
    doc = scan(
        "scan-mismatch",
        lot=None,
        ndc9=None,
        ndc_raw=None,
        generic="ibuprofen",
        manufacturer=None,
        imprint="5892V",
        verdict="mismatch_found",
        research=research,
        evidence_pack=pack(lot=None, ndc9=None, generic="ibuprofen", imprint_norm="5892V",
                           pill=pill),
    )
    nodes, links, _ = graph_from_scans([doc])
    index = by_id(nodes)
    assert "imprint:5892V" in index and "med:temazepam" in index
    conflict = next(link for link in links if link.kind == "conflicts_with")
    assert {conflict.source, conflict.target} == {"med:temazepam", "med:ibuprofen"}
    assert conflict.alert is False
    identifies = next(link for link in links if link.kind == "identifies_as")
    assert identifies.strong is True


def test_findings_are_attached_to_the_node_their_source_id_names() -> None:
    research = {
        "verdict": "recall_match",
        "risk_level": "high",
        "headline": "A recall names this lot.",
        "findings": [
            {
                "statement": "FDA recall D-0785-2026 lists lot D2402430.",
                "evidence_type": "exact_lot_match",
                "source_ids": [REC_LEVO],
                "severity": "serious",
                "country_scope": None,
            }
        ],
    }
    nodes, _, _ = graph_from_scans(
        [scan(research=research, evidence_pack=pack(exact_lot_hits=[LEVO_EXACT]))]
    )
    record = by_id(nodes)[f"rec:{REC_LEVO}"]
    assert record.attrs["findings"][0]["evidence_type"] == "exact_lot_match"


def test_a_web_page_that_lists_the_lot_gets_a_lists_lot_edge() -> None:
    web = {
        "page_id": "62a8176ee4a9b3b015e7d3df9fc32aec",
        "source_id": "web-62a8176ee4a9",
        "url": "https://www.who.int/news/item/x",
        "domain": "who.int",
        "source_tier": "regulator",
        "source_org": "WHO",
        "title": "WHO alert page",
        "lots_shown": ["D2402430"],
        "lot_count": 1,
        "flags": ["recall"],
        "match_kind": "fetched_for_this_scan",
    }
    nodes, links, _ = graph_from_scans([scan(evidence_pack=pack(web_hits=[web]))])
    page = "web:62a8176ee4a9b3b015e7d3df9fc32aec"
    assert page in by_id(nodes)
    kinds = {link.kind for link in links if page in (link.source, link.target)}
    assert {"fetched_for", "lists_lot", "published_by"} <= kinds


def test_an_empty_input_builds_an_empty_graph() -> None:
    assert graph_from_scans([]) == ([], [], False)
    assert graph_from_scans([{}, {"scan_id": None}]) == ([], [], False)


def test_every_node_keeps_the_label_length_the_contract_promises() -> None:
    long_title = "Class II recall: " + "Levothyroxine Sodium Tablets USP 200 mcg " * 4
    nodes, _, _ = graph_from_scans(
        [scan(evidence_pack=pack(exact_lot_hits=[reg_entry(REC_LEVO, "exact_lot",
                                                           title=long_title)]))]
    )
    assert all(len(node.label) <= 40 for node in nodes)


def test_match_tier_rank_is_the_order_the_builder_merges_by() -> None:
    assert MATCH_TIER_RANK["match"] > MATCH_TIER_RANK["product"] > MATCH_TIER_RANK["context"]
