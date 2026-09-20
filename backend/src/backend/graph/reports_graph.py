"""Crowd reports -> `seller` and `place` nodes. Pure, offline, no I/O.

A report is one person's own account of where they bought a medicine, filed
from the results chat and joined to a scan by `scan_id` alone (`backend.reports`).
Attaching it to the graph is a different kind of act from attaching a recall,
and four rules carry the whole difference. Each has a test.

1. **A report is a statement, never evidence.** Every edge minted here is one of
   `models.REPORT_KINDS`, and those are never `strong` and never `alert`,
   whatever the scan's verdict says. A seller or place node carries no severity,
   verdict or risk level, so it can never be drawn as a risk. The graph may show
   that reports cluster around a seller; it must never say the seller did
   anything.
2. **Only this device's own reports.** `attach_reports` keeps a report only when
   its `scan_id` already has a scan node in the graph it was handed. Anything
   learned from other people's reports is a count, and that lives in
   `graph.expand`, never here.
3. **The free-text place never becomes data.** `purchase_location.label` is what
   someone typed or said ("my aunt's house, 12 Elm St"). It is never a label,
   never part of a key and never an attr; only `city`/`region`/`country` are.
   Coordinates are not read at all, whichever shape the report arrives in.
4. **A seller name is keyed with its place.** The text is transcribed speech, so
   it is cleaned and capped before it is used, and the same chain name in two
   cities is two different shops.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.graph import keys
from backend.graph.models import GraphLink, GraphNode, clip_label, link_id, node_id
from backend.knowledge import normalize

__all__ = [
    "REPORT_WEIGHT",
    "FiledReport",
    "attach_reports",
    "clean_seller",
    "normalise_report",
    "place_key",
    "place_label",
    "seller_key",
]

# Every report edge carries the same small weight. A report is provenance, not a
# claim with degrees of strength, so there is nothing here to rank.
REPORT_WEIGHT = 0.3

SELLER_VAL = 2.4
PLACE_VAL = 1.8
COUNTRY_VAL = 1.8

# Node types this module owns. Merging bookkeeping (report counts, purchase
# dates) is applied only to these, so a shared `country:` node keeps its own.
REPORT_NODE_TYPES = frozenset({"seller", "place"})

# Transcripts, OCR and pasted text all carry C0/C1 control characters, and the
# bidi overrides/isolates (U+202A-202E, U+2066-2069) that reverse a label's
# reading order on screen. The same set `static/js/safe.js: cleanText` strips,
# stripped here as well so the node *key* is clean too and not just the label.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩]")

# A seller is free text somebody typed or spoke. These two shapes are never a
# shop name and are always somebody's contact details, so a report carrying one
# mints no seller node at all — the same refusal `scans.normalizer` makes when
# it drops `pharmacy`/`rx_number`/`patient_name` off a stored bottle.
_EMAIL_HINT = "@"
_LONG_DIGIT_RUN_RE = re.compile(r"\d(?:[\s().+/-]*\d){6,}")


# --------------------------------------------------------------------------- keys


def clean_seller(value: Any) -> str | None:
    """A shop name fit to be a node label: one line, no control bytes, <= 40.

    `None` when nothing usable is left, and also when what is left is plainly
    contact details rather than a shop: an address with a phone number in it
    becomes a node label, a persistent node id and the exact term every other
    device's reports are matched against, so it is refused outright.
    """
    if value is None:
        return None
    text = normalize.clean_text(_CONTROL_RE.sub(" ", str(value)))
    if not text:
        return None
    if _EMAIL_HINT in text or _LONG_DIGIT_RUN_RE.search(text):
        return None
    return clip_label(text) or None


def place_key(
    city: Any = None, region: Any = None, country: Any = None
) -> str | None:
    """`"douala|littoral|cameroon"`, or `None` when no place field was answered.

    Fixed arity on purpose: the three slots always mean the same three fields,
    so two keys are equal exactly when the same answers were given.
    """
    city_slug = keys.slug(city)
    region_slug = keys.slug(region)
    country_slug = keys.country_key(country)
    if not (city_slug or region_slug or country_slug):
        return None
    return f"{city_slug or ''}|{region_slug or ''}|{country_slug or ''}"


def place_label(city: Any = None, region: Any = None, country: Any = None) -> str | None:
    """`"Douala, Cameroon"`. Built from the structured fields, never from `label`."""
    city_text = normalize.clean_text(city)
    region_text = normalize.clean_text(region)
    country_text = keys.country_label(country)
    head = city_text or region_text
    tail = country_text or (region_text if city_text else None)
    parts = [part for part in (head, tail) if part]
    if not parts:
        return None
    return clip_label(", ".join(parts)) or None


def seller_key(seller: Any, place: str | None = None) -> str | None:
    """`company_key` semantics, keyed together with the place when there is one.

    `company_key` returns `None` for prose rather than minting a node labelled
    with a sentence; a spoken shop name that it refuses still deserves a node,
    so the cleaned text is slugged instead. When nothing usable is left, no
    seller node is minted at all.

    `company_key` keeps "|" (it is not punctuation it strips), so the separator
    is removed from the seller half first: otherwise a shop literally named
    "Acme|Columbus|Ohio|United-States" keys to the same node as "Acme" bought in
    Columbus, and the two merge into one seller with their report counts summed.
    With the separator gone from the head, the tail is always exactly the three
    slots `place_key` writes.
    """
    cleaned = clean_seller(seller)
    if not cleaned:
        return None
    base = (keys.company_key(cleaned) or keys.slug(cleaned) or "").replace("|", "")
    if not base:
        return None
    return f"{base}|{place}" if place else base


# --------------------------------------------------------------------------- input


@dataclass(frozen=True)
class FiledReport:
    """One report, reduced to the fields the graph is allowed to see."""

    scan_id: str
    purchased_on: str | None = None
    seller: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None


def _attribute(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _iso_date(value: Any) -> str | None:
    text = normalize.clean_text(value)
    return text[:10] if text else None


def normalise_report(report: Any) -> FiledReport | None:
    """`reports.models.Report` or the stored document -> `FiledReport`.

    The two shapes differ (`lat`/`lon` against a `coordinates` geo_point) and
    neither is read: the reduction below names every field it keeps, so a new
    field on the report model cannot reach the graph by accident.
    """
    scan_id = normalize.clean_text(_attribute(report, "scan_id"))
    if not scan_id:
        return None
    location = _attribute(report, "purchase_location")
    return FiledReport(
        scan_id=scan_id,
        purchased_on=_iso_date(_attribute(report, "purchased_on")),
        seller=clean_seller(_attribute(report, "seller")),
        city=normalize.clean_text(_attribute(location, "city")),
        region=normalize.clean_text(_attribute(location, "region")),
        country=normalize.clean_text(_attribute(location, "country")),
    )


# --------------------------------------------------------------------------- nodes


def _report_attrs(filed: FiledReport) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "reports": 1,
        "city": filed.city,
        "region": filed.region,
        "country": filed.country,
    }
    if filed.purchased_on:
        attrs["first_purchased_on"] = filed.purchased_on
        attrs["last_purchased_on"] = filed.purchased_on
    return {name: value for name, value in attrs.items() if value is not None}


def _seller_node(
    filed: FiledReport, scan_node: GraphNode, key: str, place: str | None
) -> GraphNode:
    label = filed.seller or key
    attrs = _report_attrs(filed)
    # The cleaned text as stored on the node is what `graph.expand` matches on
    # `seller.kw`; a name longer than the label cap simply finds no crowd count.
    attrs["variants"] = [label]
    return GraphNode(
        id=node_id("seller", key),
        type="seller",
        label=clip_label(label),
        sublabel=place_label(filed.city, filed.region, filed.country) if place else None,
        val=SELLER_VAL,
        personal=True,
        expandable=True,
        count=1,
        date=filed.purchased_on,
        demo=scan_node.demo,
        scan_ids=[filed.scan_id],
        attrs=attrs,
    )


def _place_node(filed: FiledReport, scan_node: GraphNode, key: str) -> GraphNode:
    label = place_label(filed.city, filed.region, filed.country) or key
    return GraphNode(
        id=node_id("place", key),
        type="place",
        label=clip_label(label),
        val=PLACE_VAL,
        personal=True,
        # A place is a city, not a shop: the crowd count belongs on the seller.
        expandable=False,
        count=1,
        date=filed.purchased_on,
        demo=scan_node.demo,
        scan_ids=[filed.scan_id],
        attrs=_report_attrs(filed),
    )


def _country_node(country: str, key: str, scan_node: GraphNode) -> GraphNode:
    """The same `country:<slug>` id the builder mints, so the two merge."""
    return GraphNode(
        id=node_id("country", key),
        type="country",
        label=clip_label(keys.country_label(country) or country),
        val=COUNTRY_VAL,
        personal=True,
        expandable=True,
        demo=scan_node.demo,
    )


def _report_link(source: str, kind: str, target: str, scan_id: str) -> GraphLink:
    return GraphLink(
        id=link_id(source, kind, target),
        source=source,
        target=target,
        kind=kind,  # type: ignore[arg-type]
        strong=False,
        alert=False,
        weight=REPORT_WEIGHT,
        count=1,
        scan_ids=[scan_id],
    )


# --------------------------------------------------------------------------- merge


def _min_date(left: Any, right: Any) -> str | None:
    candidates = sorted(value for value in (left, right) if isinstance(value, str) and value)
    return candidates[0] if candidates else None


def _max_date(left: Any, right: Any) -> str | None:
    candidates = sorted(value for value in (left, right) if isinstance(value, str) and value)
    return candidates[-1] if candidates else None


def _merge_node(current: GraphNode, incoming: GraphNode) -> None:
    current.demo = current.demo or incoming.demo
    current.personal = current.personal or incoming.personal
    current.expandable = current.expandable or incoming.expandable
    for scan_id in incoming.scan_ids:
        if scan_id not in current.scan_ids:
            current.scan_ids.append(scan_id)
    if not current.sublabel and incoming.sublabel:
        current.sublabel = incoming.sublabel
    if incoming.type not in REPORT_NODE_TYPES:
        return
    total = int(current.attrs.get("reports") or 0) + int(incoming.attrs.get("reports") or 0)
    current.attrs["reports"] = total
    current.count = total
    first = _min_date(
        current.attrs.get("first_purchased_on"), incoming.attrs.get("first_purchased_on")
    )
    last = _max_date(
        current.attrs.get("last_purchased_on"), incoming.attrs.get("last_purchased_on")
    )
    if first:
        current.attrs["first_purchased_on"] = first
    if last:
        current.attrs["last_purchased_on"] = last
        current.date = last
    for name in ("city", "region", "country"):
        if not current.attrs.get(name) and incoming.attrs.get(name):
            current.attrs[name] = incoming.attrs[name]
    for variant in incoming.attrs.get("variants") or []:
        variants = current.attrs.setdefault("variants", [])
        if variant not in variants:
            variants.append(variant)


def _merge_link(current: GraphLink, incoming: GraphLink) -> None:
    current.count += incoming.count
    current.weight = max(current.weight, incoming.weight)
    for scan_id in incoming.scan_ids:
        if scan_id not in current.scan_ids:
            current.scan_ids.append(scan_id)


# --------------------------------------------------------------------------- entry point


def attach_reports(
    nodes: Sequence[GraphNode],
    links: Sequence[GraphLink],
    reports: Iterable[Any],
    scan_ids: Iterable[str],
) -> tuple[list[GraphNode], list[GraphLink]]:
    """Add this device's own purchase reports to an already-built graph.

    Additive and total: a report for a scan this graph does not hold, a report
    with nothing usable in it, and an empty report list all leave the graph
    exactly as it was. No existing node's severity, verdict, tier or alert edge
    is ever touched.
    """
    out_nodes = list(nodes)
    out_links = list(links)
    nodes_by_id = {node.id: node for node in out_nodes}

    owned: dict[str, GraphNode] = {}
    for raw in scan_ids or ():
        scan_id = normalize.clean_text(raw)
        if not scan_id:
            continue
        scan_node = nodes_by_id.get(node_id("scan", scan_id))
        if scan_node is not None and scan_node.type == "scan":
            owned[scan_id] = scan_node
    if not owned:
        return out_nodes, out_links

    links_by_id = {link.id: link for link in out_links}

    def upsert_node(node: GraphNode) -> str:
        current = nodes_by_id.get(node.id)
        if current is None:
            nodes_by_id[node.id] = node
            out_nodes.append(node)
            return node.id
        _merge_node(current, node)
        return current.id

    def upsert_link(link: GraphLink) -> None:
        current = links_by_id.get(link.id)
        if current is None:
            links_by_id[link.id] = link
            out_links.append(link)
            return
        _merge_link(current, link)

    for raw_report in reports or ():
        filed = normalise_report(raw_report)
        if filed is None or filed.scan_id not in owned:
            continue
        _attach_one(filed, owned[filed.scan_id], upsert_node, upsert_link)
    return out_nodes, out_links


def _attach_one(filed: FiledReport, scan_node: GraphNode, upsert_node: Any, upsert_link: Any) -> None:
    place = place_key(filed.city, filed.region, filed.country)
    seller = seller_key(filed.seller, place)
    if seller is None and place is None:
        # A report can be nothing but a date, or a location that reduced to
        # free text alone. There is no node to mint and no edge to draw.
        return

    place_id = upsert_node(_place_node(filed, scan_node, place)) if place else None
    seller_id = upsert_node(_seller_node(filed, scan_node, seller, place)) if seller else None

    if seller_id:
        upsert_link(_report_link(scan_node.id, "bought_from", seller_id, filed.scan_id))
        if place_id:
            upsert_link(_report_link(seller_id, "located_in", place_id, filed.scan_id))
    elif place_id:
        # No seller named: the scan reaches the place directly.
        upsert_link(_report_link(scan_node.id, "bought_in", place_id, filed.scan_id))

    if place_id and filed.country:
        country = keys.country_key(filed.country)
        if country:
            country_id = upsert_node(_country_node(filed.country, country, scan_node))
            upsert_link(_report_link(place_id, "located_in", country_id, filed.scan_id))
