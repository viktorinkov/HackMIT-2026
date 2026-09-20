"""`graph/reports_graph.py` — pure functions, so no fakes are needed at all.

The safety rules under test are the ones a report brings with it: a report is
one person's account, it is never evidence, its free-text fields never become
data, and it never touches anything the verdict already decided.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from backend.graph.builder import graph_from_scans
from backend.graph.models import REPORT_KINDS
from backend.graph.reports_graph import (
    attach_reports,
    clean_seller,
    normalise_report,
    place_key,
    place_label,
    seller_key,
)
from backend.reports.models import PurchaseLocation, Report

# The safety invariant with reports attached lives next to the original, in
# `test_builder.py`; what is below is everything else a report brings with it.
from tests.graph.test_builder import pack, reg_entry, scan

LEVO_EXACT = reg_entry("fda-enf-D-0785-2026", "exact_lot")


def report(
    scan_id: str = "scan-1",
    *,
    seller: str | None = "Riverside Demo Pharmacy",
    city: str | None = "Columbus",
    region: str | None = "Ohio",
    country: str | None = "United States",
    label: str | None = None,
    purchased_on: str | None = "2026-08-20",
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """The stored `peel-reports` document shape, coordinates and all."""
    location: dict[str, Any] = {}
    for name, value in (("label", label), ("city", city), ("region", region),
                        ("country", country)):
        if value is not None:
            location[name] = value
    if lat is not None and lon is not None:
        location["coordinates"] = {"lat": lat, "lon": lon}
    doc: dict[str, Any] = {
        "report_id": f"rep-{scan_id}-{seller or 'none'}",
        "scan_id": scan_id,
        "created_at": "2026-09-03T10:00:00Z",
    }
    if purchased_on is not None:
        doc["purchased_on"] = purchased_on
    if seller is not None:
        doc["seller"] = seller
    if location:
        doc["purchase_location"] = location
    return doc


def graph_of(*scans: dict[str, Any]) -> tuple[list[Any], list[Any], list[str]]:
    nodes, links, _truncated = graph_from_scans(list(scans))
    return nodes, links, [doc["scan_id"] for doc in scans]


def attached(scans: list[dict[str, Any]], reports: list[Any]) -> tuple[Any, Any]:
    nodes, links, scan_ids = graph_of(*scans)
    return attach_reports(nodes, links, reports, scan_ids)


def by_id(items: list[Any]) -> dict[str, Any]:
    return {item.id: item for item in items}


def kinds_of(links: list[Any], kind: str) -> list[Any]:
    return [link for link in links if link.kind == kind]


# --------------------------------------------------------------------------- keys


def test_a_report_adds_a_seller_and_a_place_to_the_scan_that_filed_it() -> None:
    nodes, links = attached([scan("scan-1")], [report("scan-1")])
    found = by_id(nodes)

    seller = found["seller:riverside demo pharmacy|columbus|ohio|united-states"]
    place = found["place:columbus|ohio|united-states"]
    assert seller.type == "seller" and seller.label == "Riverside Demo Pharmacy"
    assert seller.personal is True and seller.expandable is True
    assert seller.attrs["reports"] == 1
    assert seller.attrs["first_purchased_on"] == "2026-08-20"
    assert place.type == "place" and place.label == "Columbus, United States"

    bought_from = kinds_of(links, "bought_from")[0]
    assert bought_from.source == "scan:scan-1" and bought_from.target == seller.id
    assert bought_from.scan_ids == ["scan-1"]
    assert kinds_of(links, "located_in")[0].target == place.id
    # The purchase country reuses the regulatory country node.
    assert [link.target for link in kinds_of(links, "located_in")][-1] == "country:united-states"


def test_two_scans_that_name_the_same_seller_in_the_same_city_share_one_seller_node() -> None:
    nodes, links = attached(
        [scan("scan-1"), scan("scan-2", lot="D2402999")],
        [report("scan-1", purchased_on="2026-08-20"),
         report("scan-2", purchased_on="2026-09-02")],
    )
    sellers = [node for node in nodes if node.type == "seller"]
    assert len(sellers) == 1
    assert sellers[0].attrs["reports"] == 2
    assert sellers[0].count == 2
    assert sellers[0].scan_ids == ["scan-1", "scan-2"]
    assert sellers[0].attrs["first_purchased_on"] == "2026-08-20"
    assert sellers[0].attrs["last_purchased_on"] == "2026-09-02"
    assert len(kinds_of(links, "bought_from")) == 2
    # One seller, one place, and the seller->place edge merged rather than doubled.
    located = kinds_of(links, "located_in")
    assert [link.count for link in located if link.source == sellers[0].id] == [2]


def test_the_same_seller_name_in_two_cities_is_two_sellers() -> None:
    nodes, _links = attached(
        [scan("scan-1"), scan("scan-2", lot="D2402999")],
        [
            report("scan-1", city="Columbus", region="Ohio"),
            report("scan-2", city="Leeds", region="England", country="United Kingdom"),
        ],
    )
    sellers = [node for node in nodes if node.type == "seller"]
    places = [node for node in nodes if node.type == "place"]
    assert len(sellers) == 2
    assert len(places) == 2
    assert {node.label for node in sellers} == {"Riverside Demo Pharmacy"}


def test_a_seller_with_no_usable_place_still_gets_a_node_and_a_place_does_not() -> None:
    nodes, links = attached(
        [scan("scan-1")],
        [report("scan-1", city=None, region=None, country=None)],
    )
    assert [node.id for node in nodes if node.type == "seller"] == [
        "seller:riverside demo pharmacy"
    ]
    assert [node for node in nodes if node.type == "place"] == []
    assert kinds_of(links, "located_in") == []


def test_a_place_with_no_seller_is_reached_from_the_scan_directly() -> None:
    nodes, links = attached([scan("scan-1")], [report("scan-1", seller=None)])
    assert [node for node in nodes if node.type == "seller"] == []
    bought_in = kinds_of(links, "bought_in")
    assert len(bought_in) == 1
    assert bought_in[0].source == "scan:scan-1"
    assert bought_in[0].target == "place:columbus|ohio|united-states"
    assert kinds_of(links, "bought_from") == []


def test_a_report_with_nothing_usable_in_it_changes_nothing() -> None:
    before_nodes, before_links, scan_ids = graph_of(scan("scan-1"))
    nodes, links = attach_reports(
        before_nodes,
        before_links,
        [report("scan-1", seller=None, city=None, region=None, country=None),
         report("scan-1", seller="   ", city=None, region=None, country=None)],
        scan_ids,
    )
    assert [node.id for node in nodes] == [node.id for node in before_nodes]
    assert [link.id for link in links] == [link.id for link in before_links]


# --------------------------------------------------------------------------- safety


def test_a_report_link_is_never_strong_and_never_an_alert_whatever_the_verdict() -> None:
    for verdict in ("recall_match", "mismatch_found", "insufficient_evidence",
                    "no_adverse_findings"):
        _nodes, links = attached(
            [scan("scan-1", verdict=verdict, evidence_pack=pack(exact_lot_hits=[LEVO_EXACT]))],
            [report("scan-1")],
        )
        for link in links:
            if link.kind in REPORT_KINDS:
                assert link.strong is False, (verdict, link.id)
                assert link.alert is False, (verdict, link.id)


def test_a_seller_node_never_carries_a_severity_verdict_or_risk_level() -> None:
    nodes, _links = attached(
        [scan("scan-1", verdict="recall_match", evidence_pack=pack(exact_lot_hits=[LEVO_EXACT]))],
        [report("scan-1")],
    )
    for node in nodes:
        if node.type in ("seller", "place"):
            assert node.severity is None
            assert node.verdict is None
            assert node.risk_level is None
            assert node.match_tier is None


def test_a_free_text_location_label_never_becomes_a_node_or_a_key() -> None:
    secret = "my aunt's house, 12 Elm St"
    nodes, links = attached(
        [scan("scan-1")],
        [report("scan-1", seller=None, city=None, region=None, country="Cameroon",
                label=secret)],
    )
    blob = " ".join(
        [*(node.model_dump_json() for node in nodes), *(link.id for link in links)]
    )
    assert "Elm St" not in blob and "aunt" not in blob
    assert [node.label for node in nodes if node.type == "place"] == ["Cameroon"]


def test_coordinates_never_reach_the_graph() -> None:
    nodes, _links = attached(
        [scan("scan-1")], [report("scan-1", lat=4.0511, lon=9.7679)]
    )
    blob = " ".join(node.model_dump_json() for node in nodes)
    for leaked in ("4.0511", "9.7679", "coordinates", '"lat"', '"lon"'):
        assert leaked not in blob


def test_a_report_for_another_devices_scan_is_ignored() -> None:
    nodes, links = attached([scan("scan-1")], [report("scan-elsewhere")])
    assert [node for node in nodes if node.type in ("seller", "place")] == []
    assert [link for link in links if link.kind in REPORT_KINDS] == []


def test_a_control_character_or_a_long_name_never_reaches_a_label() -> None:
    assert clean_seller("Riverside\x00\x07  Demo\nPharmacy") == "Riverside Demo Pharmacy"
    assert clean_seller("   ") is None
    assert clean_seller(None) is None
    long_name = "Pharmacie " * 12
    cleaned = clean_seller(long_name)
    assert cleaned is not None and len(cleaned) <= 40


def test_a_bidi_override_never_reaches_a_label_or_a_key() -> None:
    """The label layer writes `node.label` straight to the DOM, so the strip
    happens here — and on the key too, which `cleanText` could never reach."""
    spoofed = "‮YCAMRAHP EDIS HTUOS"
    cleaned = clean_seller(spoofed)
    assert cleaned == "YCAMRAHP EDIS HTUOS"
    assert "‮" not in (seller_key(spoofed) or "")
    for char in ("‪", "‫", "‬", "‭", "⁦", "⁧", "⁨", "⁩"):
        assert char not in (clean_seller(f"Riverside{char}Pharmacy") or "")


def test_contact_details_typed_into_the_seller_box_mint_no_node() -> None:
    """A seller name becomes a projected label, a persistent id and the exact
    term matched against everybody else's reports. Somebody's phone number or
    email address is none of those things, so nothing is minted at all."""
    for personal in (
        "john.doe@example.com",
        "my neighbour John Smith, 555 0147",
        "call 555-0147",
        "+1 (614) 555-0147",
    ):
        assert clean_seller(personal) is None, personal
        assert seller_key(personal) is None, personal

    nodes, links = attached([scan("scan-1")], [report("scan-1", seller="ring 555 0147")])
    found = [node for node in nodes if node.type == "seller"]
    assert found == []
    # The place the person also gave still stands; only the seller is refused.
    assert [node.type for node in nodes if node.type == "place"] == ["place"]
    assert [link.kind for link in links if link.kind in REPORT_KINDS] == [
        "bought_in",
        "located_in",
    ]

    # A shop name that merely contains a number is still a shop name.
    assert clean_seller("Pharmacy 24/7") == "Pharmacy 24/7"
    assert clean_seller("Boots 1849 High Street") == "Boots 1849 High Street"


def test_a_seller_name_cannot_forge_the_place_half_of_its_own_key() -> None:
    """The place tail is fixed arity, so the separator is not the seller's to
    write: otherwise two different shops merge into one node with their report
    counts summed and both spellings in the list the crowd query terms on."""
    place = "columbus|ohio|united-states"
    honest = seller_key("Acme", place)
    forged = seller_key("Acme|Columbus|Ohio|United-States", None)
    assert honest == "acme|columbus|ohio|united-states"
    assert forged != honest
    assert "|" not in (forged or "")


def test_the_key_helpers_are_total_and_deterministic() -> None:
    assert place_key("Douala", "Littoral", "Cameroon") == "douala|littoral|cameroon"
    assert place_key(None, None, "Cameroon") == "||cameroon"
    assert place_key(None, None, None) is None
    assert place_label("Douala", "Littoral", "Cameroon") == "Douala, Cameroon"
    assert place_label(None, "Littoral", "Cameroon") == "Littoral, Cameroon"
    assert place_label("Douala", "Littoral", None) == "Douala, Littoral"
    assert place_label(None, None, None) is None
    assert seller_key("Riverside Demo Pharmacy") == "riverside demo pharmacy"
    assert seller_key("Riverside Demo Pharmacy", "columbus||") == (
        "riverside demo pharmacy|columbus||"
    )
    assert seller_key(None) is None
    assert seller_key("   ") is None
    # `company_key` refuses prose; a spoken shop name still deserves a node.
    prose = "the little shop next to the bus station on the main road out of town"
    assert seller_key(prose) is not None


# --------------------------------------------------------------------------- input shapes


def test_the_pydantic_report_and_the_stored_document_reduce_to_the_same_thing() -> None:
    stored = report("scan-1", lat=39.96, lon=-83.0)
    model = Report(
        report_id="rep-1",
        scan_id="scan-1",
        purchased_on=date(2026, 8, 20),
        purchase_location=PurchaseLocation(
            label="the corner shop", city="Columbus", region="Ohio",
            country="United States", lat=39.96, lon=-83.0,
        ),
        seller="Riverside Demo Pharmacy",
        created_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
    )
    assert normalise_report(stored) == normalise_report(model)
    filed = normalise_report(model)
    assert filed is not None
    assert filed.purchased_on == "2026-08-20"
    assert filed.city == "Columbus"


def test_a_report_without_a_scan_id_is_dropped() -> None:
    assert normalise_report({"seller": "Riverside Demo Pharmacy"}) is None
    assert normalise_report({"scan_id": "  "}) is None
