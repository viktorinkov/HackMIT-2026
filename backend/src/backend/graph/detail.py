"""`GET /graph/node`: the note panel behind one node.

Three families of node get a real detail; nothing gets a bare id-only stub
unless it truly falls outside what this device knows (design-data-api.md §6):

* **`scan:`** — headline, verdict wording, findings, mismatches, gaps and
  `next_steps` come only from the scan's stored `norm`/`research`/`hardware`;
  `bottle`/`imprint` are never read, mirroring the builder's own allow-list.
  A finding with `evidence_type == "prior_scan_signal"` is dropped when the
  scan is a demo scan — a seeded/rehearsal scan must never present a fake
  crowd signal as evidence.
* **`rec:`** — fetched fresh with `GraphQueries.record()` (which already
  excludes `raw`/`body_semantic`/`body`), so the regulator's full text is
  structurally unreachable here, never just filtered on the way out.
  `body` follows `graph.licensing`'s per-source policy. `next_steps` are
  reused verbatim from one of this device's own scans that has an alert
  edge to this exact record (the same predicate the safety invariant uses:
  `evidence.qualifying_lot_hits` / `_qualifying_all_lots`); otherwise the
  panel says plainly that the record is shown for context only.
* **`seller:` / `place:`** — a note about a report this person filed, never
  about the seller. The copy says where it came from, that Peel has not
  checked it and that it says nothing about what the seller did; a seller
  never gets a badge. Every number on these notes is this person's own: a
  note is rebuilt from this device's scans and reports on each request, so no
  other person's count is in reach. Other people's reports arrive as the
  `cluster:` node `/graph/expand` mints, whose own note is counts only.
* **everything else** (`medicine`, `product`, `lot`, `manufacturer`,
  `regulator`, `country`, `web_page`, `imprint`, `topic`, ...) — derived from
  this device's own PERSONAL GRAPH (`graph.builder.graph_from_scans` over
  `ctx.scan_docs`). The node's own fields and `attrs`, plus every link that
  touches it, are enough to build a subtitle, properties, badges, a short
  body, backlinks ("linked mentions") and, for a lot/product with an alert
  edge, the same guardrailed `next_steps` its owning scan already computed.
  A node that is not in this device's personal graph (or a request with no
  `device_id`) falls back to a minimal, honestly-titled context note.

Wording rule, tested: never "safe", "genuine", "verified" or "authentic";
never a "low risk"/"all clear" phrasing; expiry and hardware degradation are
never merged into one fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from backend.graph.builder import graph_from_scans
from backend.graph.licensing import attribution_for, licensed_body, link_label_for
from backend.graph.models import (
    ID_PREFIX,
    Backlink,
    DetailFinding,
    DetailProperty,
    GraphLink,
    GraphNode,
    NodeDetail,
    SourceAttribution,
)
from backend.graph.models import node_id as _make_node_id
from backend.graph.queries import GraphQueries
from backend.graph.reports_graph import attach_reports
from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Reg, Scan
from backend.pill import HARDWARE_MODEL
from backend.research.evidence import _qualifying_all_lots, qualifying_lot_hits

if TYPE_CHECKING:  # pragma: no cover - the service module is another stream's
    from backend.graph.service import GraphContext

# How many of this device's scans to scan when looking for a record's
# next_steps donor. Generous: a real device rarely has more than a handful.
SCAN_LOOKUP_LIMIT = 200
MAX_LOTS_SHOWN = 25
MAX_BACKLINKS = 25
MAX_LINKED_SOURCES = 6
DEFAULT_NOTICE = "This detail is drawn from what was searched, not a guarantee about this medicine."
DEFAULT_RECORD_NEXT_STEP = "Shown for context. This record does not name the lot on your label."
CONTEXT_NOTICE = "This id is not part of your personal graph; shown for context only."
# `keys.cluster_key(parent, "reports")` — the crowd cluster an expansion mints.
# It never lives in the personal graph, so its note is authored, not derived.
REPORT_CLUSTER_SUFFIX = "|reports"

_PREFIX_TO_TYPE: dict[str, str] = {prefix: node_type for node_type, prefix in ID_PREFIX.items()}

# A human title never re-cases these: a lot string, an NDC or an imprint is
# meaningful verbatim ("D2402430"), and title-casing it would misrepresent it.
_VERBATIM_TITLE_TYPES = frozenset({"lot", "product", "imprint"})

# Plain-language captions for every kind a personal-graph link can carry.
# Tested to cover every value of `models.LinkKind`.
RELATION_LABELS: dict[str, str] = {
    "names": "Named on your label",
    "brand_of": "Brand name for",
    "labelled_ndc": "NDC on your label",
    "labelled_lot": "Lot on your label",
    "labelled_maker": "Manufacturer on your label",
    "observed_imprint": "Imprint on the pill",
    "scanned_in": "Scanned in",
    "contains": "Contains",
    "registered_to": "Registered to",
    "sibling_strength": "Other strength of this product",
    "makes": "Makes",
    "exact_lot": "Exact lot match",
    "lot_only_match": "Lot string only — not corroborated",
    "lot_listed": "Lot string appears in this record — product not checked",
    "all_lots_product": "Whole product line recalled",
    "all_lots_sibling": "Same product line — not this lot",
    "ndc_in_description": "Named in the recall text — not a lot match",
    "product_line_match": "Same product line — not this lot",
    "related": "Related record",
    "about": "About",
    "issued_by": "Issued by",
    "affects": "Affects",
    "names_maker": "Manufacturer named in this record",
    "stated_manufacturer": "Name printed on the label",
    "topic": "Reason given",
    "same_event": "Part of the same recall event",
    "fetched_for": "Fetched while researching this scan",
    "web_related": "Related web page",
    "lists_lot": "Lists this lot",
    "published_by": "Published by",
    "cited": "Cited in your scan report",
    "identifies_as": "Possible match from the imprint",
    "conflicts_with": "Label and pill reference disagree",
    "bought_from": "Where you said you bought it",
    "bought_in": "Where you said you bought it",
    "located_in": "Located in",
    "also_reported": "Other people's reports",
    "more": "More like this",
}

# Authored copy, gathered so the wording test can sweep every string at once.
SUBTITLES: dict[str, str] = {
    "lot_one": "Read from the label of one of your scans",
    "lot_many": "Read from the label of {n} of your scans",
    "product": "NDC product",
    "medicine": "Medicine named on {n} of your scans",
    "manufacturer": "Manufacturer",
    "manufacturer_stated": "Name printed on the label",
    "regulator": "Regulator",
    "country": "Country",
    "imprint": "Imprint read from the pill",
    "topic": "Reason given in recall records",
    "seller": "Named in your report as where you bought it",
    "place": "The place you named in your report",
    "report_cluster": "Counts from other people's reports",
}
BADGES: dict[str, str] = {
    "recall": "Named in a recall",
    "uncorroborated": "Lot string seen elsewhere — not corroborated",
    "listing_expired": "NDC listing expired",
}
BODY_TEXT: dict[str, str] = {
    "lot_alert": (
        "A lot number identifies a production run only together with its product. "
        "This one matches a recall for the same product."
    ),
    "lot_uncorroborated": (
        "This lot string also appears in records about other products. A lot number "
        "is unique only within one manufacturer, so these are shown as unconfirmed."
    ),
    "lot_neutral": (
        "A lot number identifies a production run only together with its product. "
        "No record in your graph names this lot."
    ),
    "manufacturer_stated": (
        "This is the name printed on a falsified product's label. The named company "
        "is usually the victim of the falsification."
    ),
    "manufacturer_default": "This is the manufacturer named on a product label or in a regulator's record.",
    "product": "An NDC identifies one product listing, not a single bottle or lot.",
    "product_listing_expired": "Its FDA listing has expired.",
    "medicine": "This is a medicine name read off one of your scans.",
    "regulator": "This is a regulator that issued a record in your graph.",
    "country": "This is a country named by a record or scan in your graph.",
    "web_page": "This is a web page referenced while researching one of your scans.",
    "imprint": (
        "An imprint is the marking pressed or printed on a pill. It can suggest "
        "candidate products but does not confirm one on its own."
    ),
    "topic": "This is the reason a recall or alert record in your graph gives for existing.",
    # A report is one person's account. None of this copy may read as a finding
    # about the seller, and none of it may read as an assurance either.
    "seller": (
        "This comes from a report you filed. Peel has not checked it, and it says "
        "nothing about what the seller did."
    ),
    "place": (
        "This is the city or country you gave in a report you filed. Peel has not "
        "checked it, and it says nothing about the medicines sold there."
    ),
    "report_cluster": (
        "Other people filed reports naming the same place of purchase. Peel shows how "
        "many, and nothing else about them: no dates, no locations, no scans. Peel has "
        "not checked any of these reports, and they say nothing about what anyone did."
    ),
}
PROPERTY_LABELS: dict[str, str] = {
    "lot": "Lot as read",
    "on_label": "On your label",
    "lot_records": "Records naming this lot",
    "ndc": "NDC",
    "dosage_form": "Dosage form",
    "listing_status": "Listing status",
    "named_as": "Named as",
    "graph_records": "Records in your graph",
    "domain": "Domain",
    "source_tier": "Source tier",
    "date": "Date",
    "shape": "Shape",
    "colors": "Colors",
    "topic_records": "Records giving this reason",
    "your_reports": "Reports you filed",
    "purchased_on": "You said you bought it",
    "purchased_between": "You said you bought it between",
    "place": "Place",
}

_LOT_UNCORROBORATED_KINDS = frozenset({"lot_only_match", "lot_listed"})


def _queries(ctx: GraphContext) -> GraphQueries:
    """The service may hand us one; otherwise wrap its client here."""
    existing = getattr(ctx, "queries", None)
    return existing if existing is not None else GraphQueries(ctx.es)


async def node_detail(ctx: GraphContext, node_id: str, *, device_id: str | None) -> NodeDetail:
    prefix, _, key = node_id.partition(":")
    if not key:
        raise KnowledgeError(f"malformed node id: {node_id!r}", status_code=404)
    node_type = _PREFIX_TO_TYPE.get(prefix)
    if node_type is None:
        raise KnowledgeError(f"unknown node id prefix: {node_id!r}", status_code=404)

    if node_type == "scan":
        return await _scan_detail(ctx, key, device_id=device_id)
    if node_type == "record":
        return await _record_detail(ctx, key, device_id=device_id)
    return await _graph_derived_detail(ctx, node_type, key, node_id, device_id=device_id)


# --------------------------------------------------------------------------- scan


async def _scan_detail(ctx: GraphContext, scan_id: str, *, device_id: str | None) -> NodeDetail:
    doc = await ctx.scans.get(scan_id) if scan_id else None
    if not doc or not device_id or doc.get(Scan.DEVICE_ID) != device_id:
        # Same answer whether the scan does not exist or belongs to someone
        # else: a 404 must never become an oracle for which scan ids exist.
        raise KnowledgeError(f"scan {scan_id} not found", status_code=404)
    return _build_scan_detail(doc)


def _build_scan_detail(doc: dict[str, Any]) -> NodeDetail:
    norm = doc.get(Scan.NORM) or {}
    research = doc.get(Scan.RESEARCH) or {}
    hardware = doc.get(Scan.HARDWARE) or {}
    demo = bool(doc.get(Scan.DEMO))

    drug = norm.get("generic_name") or norm.get("brand_name")
    strength = norm.get("strength")
    title = " ".join(part for part in (drug, strength) if part) or "Untitled scan"
    subtitle = VERDICT_LABELS.get(research.get("verdict"), research.get("verdict"))

    badges: list[str] = []
    if demo:
        badges.append("Demo scan")
    is_simulated = bool(hardware) and (hardware.get("model") == HARDWARE_MODEL or hardware.get("limitations"))
    if is_simulated:
        badges.append("Simulated hardware")
    if hardware.get("degraded"):
        badges.append("Degraded reading")
    if norm.get("expired"):
        badges.append("Expired")

    properties = _properties(
        ("drug", "Medicine", drug),
        ("strength", "Strength", strength),
        ("dosage_form", "Form", norm.get("dosage_form")),
        ("ndc", "NDC", norm.get("ndc_raw") or norm.get("ndc11") or norm.get("ndc9")),
        ("lot", "Lot", norm.get("lot")),
        ("manufacturer", "Manufacturer (as labelled)", norm.get("manufacturer")),
        ("country", "Country", doc.get(Scan.COUNTRY)),
        ("status", "Scan status", doc.get(Scan.STATUS)),
        ("verdict", "Verdict", research.get("verdict")),
        ("risk_level", "Risk level", research.get("risk_level")),
        # Expiry is its own property, never folded into a badge.
        ("expiration", "Expiration", norm.get("expiration")),
        ("hardware_status", "Hardware reading", hardware.get("status")),
        ("hardware_limitations", "Hardware note", hardware.get("limitations")),
    )

    findings = [
        DetailFinding(
            statement=str(finding.get("statement") or ""),
            severity=finding.get("severity"),
            evidence_type=finding.get("evidence_type"),
        )
        for finding in research.get("findings") or []
        if not (demo and finding.get("evidence_type") == "prior_scan_signal")
    ]
    mismatches = [
        str(mismatch.get("explanation"))
        for mismatch in research.get("mismatches") or []
        if mismatch.get("explanation")
    ]
    gaps = [str(gap) for gap in research.get("gaps") or []]
    next_steps = [str(step) for step in research.get("next_steps") or []]
    sources = [_source_attribution(source) for source in research.get("sources") or []]

    return NodeDetail(
        id=f"scan:{doc.get(Scan.SCAN_ID)}",
        type="scan",
        title=title,
        subtitle=subtitle,
        badges=badges,
        properties=properties,
        body=research.get("headline"),
        findings=findings,
        mismatches=mismatches,
        gaps=gaps,
        next_steps=next_steps,
        sources=sources,
        notice=DEFAULT_NOTICE,
        demo=demo,
    )


VERDICT_LABELS: dict[str, str] = {
    "no_adverse_findings": "No adverse findings in the sources checked",
    "mismatch_found": "The label and the pill reference do not match",
    "recall_match": "A recall or alert names this lot",
    "insufficient_evidence": "Not enough evidence to say",
}


def _source_attribution(source: dict[str, Any]) -> SourceAttribution:
    org = source.get("source_org")
    licensed = licensed_body(org, {})
    return SourceAttribution(
        id=str(source.get("id") or ""),
        title=str(source.get("title") or source.get("id") or "Source"),
        url=source.get("url"),
        source_org=org,
        published_at=source.get("published_at"),
        attribution=licensed.attribution,
        link_label=licensed.link_label,
    )


# --------------------------------------------------------------------------- record


async def _record_detail(ctx: GraphContext, record_id: str, *, device_id: str | None) -> NodeDetail:
    record = await _queries(ctx).record(record_id)
    if not record:
        raise KnowledgeError(f"record {record_id} not found", status_code=404)
    return await _build_record_detail(ctx, record_id, record, device_id=device_id)


async def _build_record_detail(
    ctx: GraphContext, record_id: str, record: dict[str, Any], *, device_id: str | None
) -> NodeDetail:
    source_org = record.get(Reg.SOURCE_ORG)
    lots = _as_list(record.get(Reg.LOT_NUMBERS))
    lot_count = len(lots)
    countries = _as_list(record.get(Reg.COUNTRIES))
    licensed = licensed_body(source_org, record)
    recency_date = record.get(Reg.RECENCY_DATE)

    properties = _properties(
        ("regulator", "Regulator", source_org),
        ("date", "Date", _date_only(recency_date)),
        ("age", "Age", _age_note(recency_date)),
        ("classification", "Classification", record.get(Reg.CLASSIFICATION_RAW)),
        ("status", "Status", record.get(Reg.STATUS)),
        ("lots", "Lots", ", ".join(lots[:MAX_LOTS_SHOWN]) or None),
        ("countries", "Countries", ", ".join(countries) or None),
    )

    next_steps = await _record_next_steps(ctx, record_id, device_id=device_id)

    title = str(record.get(Reg.TITLE) or record_id)
    severity = record.get(Reg.SEVERITY)

    return NodeDetail(
        id=f"rec:{record_id}",
        type="record",
        title=title,
        subtitle=source_org,
        badges=[str(severity)] if severity else [],
        properties=properties,
        body=licensed.body,
        next_steps=next_steps,
        sources=[
            SourceAttribution(
                id=record_id,
                title=title,
                url=record.get(Reg.URL),
                source_org=source_org,
                published_at=_date_only(recency_date),
                attribution=licensed.attribution,
                link_label=licensed.link_label,
            )
        ],
        counts={"lot_count": lot_count},
        notice=DEFAULT_NOTICE,
    )


def _alert_record_ids(evidence_pack: dict[str, Any]) -> set[str]:
    """Exactly the predicate the safety invariant uses for a red edge.

    Reusing `qualifying_lot_hits`/`_qualifying_all_lots` (research/evidence.py)
    rather than re-deriving "was this an alert" keeps this in lockstep with the
    verdict itself: a record's next_steps are only ever borrowed from a scan
    whose stored verdict this record actually earned.
    """
    ids: set[str] = set()
    for entry in (*qualifying_lot_hits(evidence_pack), *_qualifying_all_lots(evidence_pack)):
        record_id = entry.get("record_id")
        if record_id:
            ids.add(str(record_id))
    return ids


async def _record_next_steps(
    ctx: GraphContext, record_id: str, *, device_id: str | None
) -> list[str]:
    if not device_id:
        return [DEFAULT_RECORD_NEXT_STEP]
    try:
        docs = await ctx.scan_docs(device_id, SCAN_LOOKUP_LIMIT)
    except Exception:  # noqa: BLE001 - a lookup failure must not break the panel
        return [DEFAULT_RECORD_NEXT_STEP]
    for doc in docs or []:
        evidence = doc.get(Scan.EVIDENCE) or {}
        pack = evidence.get("evidence_pack") or {}
        if not pack or record_id not in _alert_record_ids(pack):
            continue
        steps = [str(step) for step in (doc.get(Scan.RESEARCH) or {}).get("next_steps") or []]
        if steps:
            return steps
    return [DEFAULT_RECORD_NEXT_STEP]


# --------------------------------------------------------------------------- graph-derived


@dataclass
class _Personal:
    """The slice of one device's personal graph that a note panel needs."""

    nodes: dict[str, GraphNode]
    links: list[GraphLink]
    docs_by_scan: dict[str, dict[str, Any]]


@dataclass
class _Draft:
    """What a per-type builder fills in; the rest is assembled generically."""

    subtitle: str | None = None
    badges: list[str] = field(default_factory=list)
    properties: list[DetailProperty] = field(default_factory=list)
    body: str | None = None
    next_steps: list[str] = field(default_factory=list)
    sources: list[SourceAttribution] = field(default_factory=list)


def _setting(ctx: GraphContext, name: str, default: int) -> int:
    settings = getattr(ctx, "settings", None)
    value = getattr(settings, name, None) if settings is not None else None
    return int(value) if value is not None else default


async def _own_reports(ctx: GraphContext, scan_ids: list[str]) -> list[dict[str, Any]]:
    """This device's own purchase reports, or none. Additive, never fatal."""
    loader = getattr(ctx, "report_docs", None)
    if loader is None or not scan_ids:
        return []
    try:
        return list(await loader(scan_ids))
    except Exception:  # noqa: BLE001 - a note panel without sellers is still a note panel
        return []


async def _load_personal(ctx: GraphContext, device_id: str) -> _Personal | None:
    scan_limit = _setting(ctx, "scan_limit", 50)
    max_nodes = _setting(ctx, "max_nodes", 600)
    max_links = _setting(ctx, "max_links", 1500)
    try:
        docs = await ctx.scan_docs(device_id, scan_limit)
    except Exception:  # noqa: BLE001 - an ES failure degrades to the context fallback
        return None
    nodes, links, _truncated = graph_from_scans(docs, max_nodes=max_nodes, max_links=max_links)
    docs_by_scan = {
        str(doc.get(Scan.SCAN_ID)): doc for doc in docs if isinstance(doc, dict) and doc.get(Scan.SCAN_ID)
    }
    scan_ids = list(docs_by_scan)
    nodes, links = attach_reports(
        nodes, links, await _own_reports(ctx, scan_ids), scan_ids
    )
    return _Personal(nodes={node.id: node for node in nodes}, links=links, docs_by_scan=docs_by_scan)


def _report_cluster_detail(full_id: str) -> NodeDetail:
    """The `also_reported` cluster: counts only, and copy that says so."""
    return NodeDetail(
        id=full_id,
        type="cluster",
        title="Other people's reports",
        subtitle=SUBTITLES["report_cluster"],
        body=BODY_TEXT["report_cluster"],
        notice=DEFAULT_NOTICE,
    )


async def _graph_derived_detail(
    ctx: GraphContext, node_type: str, key: str, full_id: str, *, device_id: str | None
) -> NodeDetail:
    if node_type == "cluster" and key.endswith(REPORT_CLUSTER_SUFFIX):
        return _report_cluster_detail(full_id)
    personal = await _load_personal(ctx, device_id) if device_id else None
    node = personal.nodes.get(full_id) if personal else None
    if node is None:
        return _context_detail(node_type, key, full_id)
    return _build_graph_detail(node, personal)  # type: ignore[arg-type]


def _human_title(node_type: str, key: str, full_id: str) -> str:
    """Strip the prefix; title-case prose types, keep codes verbatim."""
    if node_type in _VERBATIM_TITLE_TYPES:
        return key or full_id
    text = key.replace("-", " ").replace("_", " ").strip()
    return text.title() if text else full_id


def _context_detail(node_type: str, key: str, full_id: str) -> NodeDetail:
    return NodeDetail(
        id=full_id,
        type=node_type,  # type: ignore[arg-type]
        title=_human_title(node_type, key, full_id),
        properties=[DetailProperty(key="id", label="Id", value=full_id)],
        notice=CONTEXT_NOTICE,
    )


def _touching(node_id_: str, links: list[GraphLink]) -> list[tuple[GraphLink, str]]:
    out: list[tuple[GraphLink, str]] = []
    for link in links:
        if link.source == node_id_:
            out.append((link, link.target))
        elif link.target == node_id_:
            out.append((link, link.source))
    return out


def _incoming(node_id_: str, links: list[GraphLink]) -> list[GraphLink]:
    return [link for link in links if link.target == node_id_]


def _is_type(nodes: dict[str, GraphNode], other_id: str, node_type: str) -> bool:
    other = nodes.get(other_id)
    return other is not None and other.type == node_type


def _record_neighbors(
    touching: list[tuple[GraphLink, str]], nodes: dict[str, GraphNode]
) -> list[tuple[GraphLink, str]]:
    return [(link, other_id) for link, other_id in touching if _is_type(nodes, other_id, "record")]


def _backlinks(
    node_id_: str, touching: list[tuple[GraphLink, str]], nodes: dict[str, GraphNode]
) -> list[Backlink]:
    ranked: list[tuple[bool, bool, Backlink]] = []
    for link, other_id in touching:
        other = nodes.get(other_id)
        if other is None:
            continue
        relation = RELATION_LABELS.get(link.kind, link.kind)
        scan_id = other_id if other.type == "scan" else None
        ranked.append(
            (
                link.alert,
                link.strong,
                Backlink(node_id=other_id, type=other.type, label=other.label, relation=relation, scan_id=scan_id),
            )
        )
    ranked.sort(key=lambda item: (0 if item[0] else 1, 0 if item[1] else 1))
    return [item[2] for item in ranked[:MAX_BACKLINKS]]


def _link_counts(touching: list[tuple[GraphLink, str]]) -> dict[str, int]:
    counts = {"alert": 0, "strong": 0, "weak": 0}
    for link, _other_id in touching:
        if link.alert:
            counts["alert"] += 1
        elif link.strong:
            counts["strong"] += 1
        else:
            counts["weak"] += 1
    return counts


def _connected_demo(touching: list[tuple[GraphLink, str]], nodes: dict[str, GraphNode]) -> bool:
    return any(
        (other := nodes.get(other_id)) is not None and other.type == "scan" and other.demo
        for _link, other_id in touching
    )


def _source_from_record_node(node: GraphNode) -> SourceAttribution:
    return SourceAttribution(
        id=node.id,
        title=node.label,
        url=node.url,
        source_org=node.source_org,
        published_at=_date_only(node.date),
        attribution=attribution_for(node.source_org),
        link_label=link_label_for(node.source_org),
    )


def _record_sources(
    touching: list[tuple[GraphLink, str]], nodes: dict[str, GraphNode], *, limit: int = MAX_LINKED_SOURCES
) -> list[SourceAttribution]:
    seen: set[str] = set()
    ranked: list[tuple[bool, SourceAttribution]] = []
    for link, other_id in touching:
        other = nodes.get(other_id)
        if other is None or other.type != "record" or other_id in seen:
            continue
        seen.add(other_id)
        ranked.append((link.alert, _source_from_record_node(other)))
    ranked.sort(key=lambda item: 0 if item[0] else 1)
    return [source for _alert, source in ranked[:limit]]


def _alert_next_steps(
    touching: list[tuple[GraphLink, str]], docs_by_scan: dict[str, dict[str, Any]]
) -> list[str]:
    for link, _other_id in touching:
        if not link.alert:
            continue
        for scan_id in link.scan_ids:
            doc = docs_by_scan.get(scan_id)
            if not doc:
                continue
            steps = [str(step) for step in (doc.get(Scan.RESEARCH) or {}).get("next_steps") or []]
            if steps:
                return steps
    return []


def _label_lines(scan_ids: list[str], personal: _Personal) -> list[str]:
    lines: list[str] = []
    for raw_scan_id in scan_ids:
        scan_node = personal.nodes.get(_make_node_id("scan", raw_scan_id))
        doc = personal.docs_by_scan.get(raw_scan_id)
        label = scan_node.label if scan_node else raw_scan_id
        ndc = None
        if doc:
            norm = doc.get(Scan.NORM) or {}
            ndc = normalize.clean_text(norm.get("ndc_raw") or norm.get("ndc11") or norm.get("ndc9"))
        line = f"{label}, NDC {ndc}" if ndc else label
        if line not in lines:
            lines.append(line)
    return lines


def _pretty_date(value: Any) -> str | None:
    text = _date_only(value)
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return text
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


# ----------------------------------------------------------- per-type builders


def _lot_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    scan_count = len(node.scan_ids)
    subtitle = SUBTITLES["lot_one"] if scan_count <= 1 else SUBTITLES["lot_many"].format(n=scan_count)

    record_ids: set[str] = set()
    has_alert = False
    has_uncorroborated = False
    for link, other_id in _record_neighbors(touching, personal.nodes):
        record_ids.add(other_id)
        if link.alert:
            has_alert = True
        elif link.kind in _LOT_UNCORROBORATED_KINDS:
            has_uncorroborated = True

    badges: list[str] = []
    if has_alert:
        badges.append(BADGES["recall"])
    elif has_uncorroborated:
        badges.append(BADGES["uncorroborated"])

    properties = _properties(
        ("lot", PROPERTY_LABELS["lot"], node.attrs.get("lot") or node.id.partition(":")[2]),
        ("on_label", PROPERTY_LABELS["on_label"], "; ".join(_label_lines(node.scan_ids, personal)) or None),
        ("records", PROPERTY_LABELS["lot_records"], str(len(record_ids)) if record_ids else None),
    )

    if has_alert:
        body = BODY_TEXT["lot_alert"]
    elif has_uncorroborated:
        body = BODY_TEXT["lot_uncorroborated"]
    else:
        body = BODY_TEXT["lot_neutral"]

    next_steps = _alert_next_steps(touching, personal.docs_by_scan) if has_alert else []
    sources = _record_sources(touching, personal.nodes)
    return _Draft(
        subtitle=subtitle, badges=badges, properties=properties, body=body,
        next_steps=next_steps, sources=sources,
    )


def _product_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    listing_expired = node.attrs.get("listing_expired")
    badges = [BADGES["listing_expired"]] if listing_expired is True else []

    ndc = node.attrs.get("product_ndc") or node.attrs.get("ndc9") or node.id.partition(":")[2]
    listing_status = None
    if listing_expired is True:
        listing_status = "Expired"
    elif listing_expired is False:
        listing_status = "Active"
    properties = _properties(
        ("ndc", PROPERTY_LABELS["ndc"], ndc),
        ("dosage_form", PROPERTY_LABELS["dosage_form"], node.attrs.get("dosage_form")),
        ("listing_status", PROPERTY_LABELS["listing_status"], listing_status),
    )

    has_alert = any(link.alert for link, _other_id in _record_neighbors(touching, personal.nodes))
    body = BODY_TEXT["product"]
    if listing_expired is True:
        body = f"{body} {BODY_TEXT['product_listing_expired']}"

    next_steps = _alert_next_steps(touching, personal.docs_by_scan) if has_alert else []
    sources = _record_sources(touching, personal.nodes)
    return _Draft(
        subtitle=SUBTITLES["product"], badges=badges, properties=properties, body=body,
        next_steps=next_steps, sources=sources,
    )


def _medicine_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    subtitle = SUBTITLES["medicine"].format(n=len(node.scan_ids))
    aliases = [str(a) for a in (node.attrs.get("aliases") or []) if isinstance(a, str)]
    properties = _properties(("named_as", PROPERTY_LABELS["named_as"], "; ".join(aliases) or None))
    sources = _record_sources(touching, personal.nodes)
    return _Draft(subtitle=subtitle, properties=properties, body=BODY_TEXT["medicine"], sources=sources)


def _manufacturer_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    incoming = _incoming(node.id, personal.links)
    stated_only = bool(incoming) and all(link.kind == "stated_manufacturer" for link in incoming)
    subtitle = SUBTITLES["manufacturer_stated"] if stated_only else SUBTITLES["manufacturer"]

    variants = [str(v) for v in (node.attrs.get("variants") or []) if isinstance(v, str)]
    record_links = _record_neighbors(touching, personal.nodes)
    properties = _properties(
        ("named_as", PROPERTY_LABELS["named_as"], "; ".join(variants) or None),
        ("records", PROPERTY_LABELS["graph_records"], str(len(record_links)) if record_links else None),
    )
    body = BODY_TEXT["manufacturer_stated"] if stated_only else BODY_TEXT["manufacturer_default"]
    sources = _record_sources(touching, personal.nodes)
    return _Draft(subtitle=subtitle, properties=properties, body=body, sources=sources)


def _regulator_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    record_links = _record_neighbors(touching, personal.nodes)
    properties = _properties(
        ("records", PROPERTY_LABELS["graph_records"], str(len(record_links)) if record_links else None)
    )
    return _Draft(subtitle=SUBTITLES["regulator"], properties=properties, body=BODY_TEXT["regulator"])


def _country_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    record_links = _record_neighbors(touching, personal.nodes)
    properties = _properties(
        ("records", PROPERTY_LABELS["graph_records"], str(len(record_links)) if record_links else None)
    )
    return _Draft(subtitle=SUBTITLES["country"], properties=properties, body=BODY_TEXT["country"])


def _web_page_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    domain = node.attrs.get("domain") or node.sublabel
    properties = _properties(
        ("domain", PROPERTY_LABELS["domain"], domain),
        ("source_tier", PROPERTY_LABELS["source_tier"], node.attrs.get("source_tier")),
        ("date", PROPERTY_LABELS["date"], _pretty_date(node.date)),
    )
    return _Draft(subtitle=domain, properties=properties, body=BODY_TEXT["web_page"], sources=[_web_page_source(node)])


def _web_page_source(node: GraphNode) -> SourceAttribution:
    return SourceAttribution(
        id=node.id,
        title=node.label,
        url=node.url,
        source_org=node.source_org,
        published_at=_date_only(node.date),
        attribution=attribution_for(node.source_org),
        link_label=link_label_for(node.source_org),
    )


def _imprint_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    colors = [str(c) for c in (node.attrs.get("colors") or []) if isinstance(c, str)]
    properties = _properties(
        ("shape", PROPERTY_LABELS["shape"], node.attrs.get("shape")),
        ("colors", PROPERTY_LABELS["colors"], ", ".join(colors) or None),
    )
    return _Draft(subtitle=SUBTITLES["imprint"], properties=properties, body=BODY_TEXT["imprint"])


def _topic_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    record_links = _record_neighbors(touching, personal.nodes)
    properties = _properties(
        ("records", PROPERTY_LABELS["topic_records"], str(len(record_links)) if record_links else None)
    )
    return _Draft(subtitle=SUBTITLES["topic"], properties=properties, body=BODY_TEXT["topic"])


def _purchase_properties(node: GraphNode) -> list[DetailProperty]:
    """Dates and counts from this person's own reports; never the free text."""
    first = node.attrs.get("first_purchased_on")
    last = node.attrs.get("last_purchased_on")
    when = None
    span = None
    if first and last and first != last:
        span = f"{_pretty_date(first)} – {_pretty_date(last)}"
    elif first or last:
        when = _pretty_date(first or last)
    reports = node.attrs.get("reports") or node.count
    return _properties(
        ("reports", PROPERTY_LABELS["your_reports"], str(reports) if reports else None),
        ("purchased_on", PROPERTY_LABELS["purchased_on"], when),
        ("purchased_between", PROPERTY_LABELS["purchased_between"], span),
    )


def _seller_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    place = None
    for _link, other_id in touching:
        other = personal.nodes.get(other_id)
        if other is not None and other.type == "place":
            place = other.label
            break
    properties = [
        *_purchase_properties(node),
        *_properties(("place", PROPERTY_LABELS["place"], place or node.sublabel)),
    ]
    # A seller never gets a badge. A badge is a verdict, and there is none here.
    # Nor does the note state a crowd count: a note is rebuilt from this
    # device's own scans and its own reports every time it is opened, so there
    # is no other person's number in reach here. Other people's reports are a
    # `cluster:` node minted by `/graph/expand`, with a note of its own.
    return _Draft(
        subtitle=SUBTITLES["seller"], properties=properties, body=BODY_TEXT["seller"]
    )


def _place_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    properties = _purchase_properties(node)
    return _Draft(subtitle=SUBTITLES["place"], properties=properties, body=BODY_TEXT["place"])


def _default_draft(node: GraphNode, touching: list[tuple[GraphLink, str]], personal: _Personal) -> _Draft:
    return _Draft(subtitle=node.sublabel)


_TYPE_BUILDERS: dict[str, Any] = {
    "lot": _lot_draft,
    "product": _product_draft,
    "medicine": _medicine_draft,
    "manufacturer": _manufacturer_draft,
    "regulator": _regulator_draft,
    "country": _country_draft,
    "web_page": _web_page_draft,
    "imprint": _imprint_draft,
    "topic": _topic_draft,
    "seller": _seller_draft,
    "place": _place_draft,
}


def _build_graph_detail(node: GraphNode, personal: _Personal) -> NodeDetail:
    touching = _touching(node.id, personal.links)
    builder = _TYPE_BUILDERS.get(node.type, _default_draft)
    draft = builder(node, touching, personal)
    return NodeDetail(
        id=node.id,
        type=node.type,
        title=node.label,
        subtitle=draft.subtitle,
        badges=draft.badges,
        properties=draft.properties,
        body=draft.body,
        next_steps=draft.next_steps,
        sources=draft.sources,
        backlinks=_backlinks(node.id, touching, personal.nodes),
        counts=_link_counts(touching),
        notice=DEFAULT_NOTICE,
        demo=_connected_demo(touching, personal.nodes),
    )


# --------------------------------------------------------------------------- helpers


def _properties(*items: tuple[str, str, Any]) -> list[DetailProperty]:
    out: list[DetailProperty] = []
    for key, label, value in items:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        out.append(DetailProperty(key=key, label=label, value=text))
    return out


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item]


def _date_only(value: Any) -> str | None:
    text = normalize.clean_text(value)
    return text.split("T")[0] if text else None


def _age_note(recency_date: Any) -> str | None:
    age = normalize.age_days(recency_date)
    if age is None:
        return None
    if age >= 365:
        return f"About {age // 365} year(s) old"
    return f"{normalize.freshness_label(age).capitalize()} ({age} day(s) old)"


__all__ = ["node_detail"]
