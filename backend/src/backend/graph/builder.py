"""`graph_from_scans`: stored scan documents -> the personal graph. Pure, no I/O.

Three rules carry the whole safety story and each has a test:

1. **An alert edge is the verdict's own evidence.** The alert set is not a list of
   `match_kind` strings maintained here; it is whatever
   `research.evidence.qualifying_lot_hits` and `_qualifying_all_lots` return for
   that scan's pack. A red edge therefore exists exactly when the stored evidence
   supports `recall_match`, including the third branch nobody remembers (an
   `ndc_hits` entry that covers all lots).
2. **Best tier wins on merge.** One record reaches a scan through several lists
   under different kinds. A last-writer merge would quietly demote the recalled
   record to `context`, so nodes take the max tier and the max severity.
3. **A falsified alert names a victim, not a maker.** `doc_type ==
   "falsified_alert"` makes the record -> manufacturer edge
   `stated_manufacturer`: neutral, never an alert, sublabelled with what it
   really means.

The builder reads `scan_id, device_id, country, status, demo, created_at, norm,
hardware, research, evidence.web_page_ids, evidence.evidence_pack` and nothing
else. It never opens `bottle` or `imprint`, so a prescription number or a
pharmacy name cannot reach a node even when `SCANS_STORE_SENSITIVE` is on.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from backend.graph import keys
from backend.graph.models import (
    ALERT_CAPABLE_KINDS,
    MATCH_TIER_RANK,
    GraphLink,
    GraphNode,
    clip_label,
    link_id,
    node_id,
)
from backend.knowledge import normalize
from backend.knowledge.fields import SEVERITY_RANKS
from backend.research.evidence import _qualifying_all_lots, qualifying_lot_hits

__all__ = ["graph_from_scans", "VERDICT_LABELS", "MATCH_KIND_LINK_KINDS"]

# Wording. Nothing here asserts anything about a medicine, and `no_adverse_findings`
# is a statement about a search, not about a bottle.
VERDICT_LABELS: dict[str, str] = {
    "recall_match": "A recall or alert names this lot",
    "mismatch_found": "The label and the reference do not agree",
    "insufficient_evidence": "Not enough readable detail to check",
    "no_adverse_findings": "Nothing found in the records searched",
}

# A `match_kind` becomes the link kind of the same name when the contract has one.
# Anything else (hybrid, web_hybrid, ndc_directory, the imprint kinds, and any
# kind added after this file was written) is weak, non-alert `related`.
MATCH_KIND_LINK_KINDS: frozenset[str] = frozenset(
    {
        "exact_lot",
        "lot_only_match",
        "lot_listed",
        "all_lots_product",
        "all_lots_sibling",
        "ndc_in_description",
        "product_line_match",
    }
)
# Corroboration is missing by construction for these, whatever else is true.
NEVER_STRONG: frozenset[str] = frozenset(
    {"lot_only_match", "all_lots_sibling", "product_line_match", "lot_listed", "related"}
)
# A recall that merely mentions this NDC in its free text is a fact about the
# product line. It only becomes a strong claim about the bottle when it is also
# the entry the verdict counted.
WEAK_UNLESS_ALERT: frozenset[str] = frozenset({"ndc_in_description"})
_KIND_WEIGHTS: dict[str, float] = {
    "exact_lot": 1.0,
    "all_lots_product": 0.9,
    "ndc_in_description": 0.5,
    "product_line_match": 0.25,
    "all_lots_sibling": 0.25,
    "lot_only_match": 0.2,
    "lot_listed": 0.2,
    "related": 0.15,
}

# Per-scan caps. `exact_lot_hits` is uncapped on purpose: it is the list the
# verdict is built from.
CAP_ALL_LOTS = 5
CAP_NDC = 5
CAP_REGULATORY = 4
CAP_WEB = 5
CAP_PILL_MEDICINES = 3
CAP_COUNTRIES = 4
CAP_DIRECTORY = 4

_LABEL_ONLY_STATUSES = frozenset({"pending", "error"})


# --------------------------------------------------------------------------- accumulator


class _Node:
    __slots__ = (
        "id", "type", "label", "sublabel", "val", "personal", "backdrop", "expandable",
        "count", "date", "url", "severity", "verdict", "risk_level", "status", "match_tier",
        "source_org", "freshness", "demo", "scan_ids", "attrs", "order", "oldest",
    )

    def __init__(self, node: str, node_type: str, label: str, order: int) -> None:
        self.id = node
        self.type = node_type
        self.label = label
        self.sublabel: str | None = None
        self.val = 1.0
        self.personal = True
        self.backdrop = False
        self.expandable = False
        self.count: int | None = None
        self.date: str | None = None
        self.url: str | None = None
        self.severity: str | None = None
        self.verdict: str | None = None
        self.risk_level: str | None = None
        self.status: str | None = None
        self.match_tier: str | None = None
        self.source_org: str | None = None
        self.freshness: str | None = None
        self.demo = False
        self.scan_ids: list[str] = []
        self.attrs: dict[str, Any] = {}
        self.order = order
        # The created_at of the oldest scan that touched this node; the global cap
        # sheds the oldest scans' context first.
        self.oldest: str = "9999"

    def to_model(self) -> GraphNode:
        return GraphNode(
            id=self.id,
            type=self.type,  # type: ignore[arg-type]
            label=clip_label(self.label),
            sublabel=self.sublabel,
            val=self.val,
            personal=self.personal,
            backdrop=self.backdrop,
            expandable=self.expandable,
            count=self.count,
            date=self.date,
            url=self.url,
            severity=self.severity,  # type: ignore[arg-type]
            verdict=self.verdict,  # type: ignore[arg-type]
            risk_level=self.risk_level,  # type: ignore[arg-type]
            status=self.status,  # type: ignore[arg-type]
            match_tier=self.match_tier,  # type: ignore[arg-type]
            source_org=self.source_org,
            freshness=self.freshness,
            demo=self.demo,
            scan_ids=list(self.scan_ids),
            attrs=dict(self.attrs),
        )


class _Link:
    __slots__ = (
        "id", "source", "target", "kind", "strong", "alert", "weight", "count",
        "match_kind", "scan_ids", "alert_scan_ids", "order",
    )

    def __init__(self, source: str, kind: str, target: str, order: int) -> None:
        self.id = link_id(source, kind, target)
        self.source = source
        self.target = target
        self.kind = kind
        self.strong = False
        self.alert = False
        self.weight = 0.2
        self.count = 0
        self.match_kind: str | None = None
        self.scan_ids: list[str] = []
        # Only the scans whose own pack qualified this edge. A shared lot node must
        # never put someone else's red edge one hover away from your bottle.
        self.alert_scan_ids: list[str] = []
        self.order = order

    def to_model(self) -> GraphLink:
        return GraphLink(
            id=self.id,
            source=self.source,
            target=self.target,
            kind=self.kind,  # type: ignore[arg-type]
            strong=self.strong,
            alert=self.alert,
            weight=self.weight,
            count=max(1, self.count),
            match_kind=self.match_kind,
            scan_ids=list(self.alert_scan_ids if self.alert else self.scan_ids),
        )


def _extend(target: list[str], values: Iterable[str]) -> None:
    seen = set(target)
    for value in values:
        if value and value not in seen:
            seen.add(value)
            target.append(value)


class _Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, _Node] = {}
        self.links: dict[str, _Link] = {}
        self._order = 0

    def node(
        self,
        node_type: str,
        key: str,
        label: str,
        *,
        scan_id: str | None = None,
        created_at: str | None = None,
        **fields: Any,
    ) -> str:
        nid = node_id(node_type, key)
        item = self.nodes.get(nid)
        if item is None:
            self._order += 1
            item = _Node(nid, node_type, label, self._order)
            self.nodes[nid] = item
        elif not item.label and label:
            item.label = label
        if scan_id:
            _extend(item.scan_ids, [scan_id])
        if created_at and created_at < item.oldest:
            item.oldest = created_at
        _merge_fields(item, fields)
        return nid

    def link(
        self,
        source: str,
        kind: str,
        target: str,
        *,
        weight: float,
        strong: bool = False,
        alert: bool = False,
        match_kind: str | None = None,
        scan_id: str | None = None,
    ) -> str:
        lid = link_id(source, kind, target)
        item = self.links.get(lid)
        if item is None:
            self._order += 1
            item = _Link(source, kind, target, self._order)
            self.links[lid] = item
        item.weight = max(item.weight, weight)
        item.count += 1
        item.strong = (item.strong or strong) and kind not in NEVER_STRONG
        if alert and kind in ALERT_CAPABLE_KINDS:
            item.alert = True
            if scan_id:
                _extend(item.alert_scan_ids, [scan_id])
        if match_kind and item.match_kind is None:
            item.match_kind = match_kind
        if scan_id:
            _extend(item.scan_ids, [scan_id])
        return lid


def _merge_fields(item: _Node, fields: dict[str, Any]) -> None:
    for name, value in fields.items():
        if value is None:
            continue
        if name == "attrs":
            _merge_attrs(item.attrs, value)
        elif name == "severity":
            if SEVERITY_RANKS.get(str(value), 0) > SEVERITY_RANKS.get(str(item.severity), 0):
                item.severity = value
        elif name == "match_tier":
            if MATCH_TIER_RANK.get(str(value), 0) > MATCH_TIER_RANK.get(str(item.match_tier), 0):
                item.match_tier = value
        elif name in ("val", "count"):
            current = getattr(item, name) or 0
            setattr(item, name, max(current, value))
        elif name in ("personal", "expandable", "backdrop", "demo"):
            setattr(item, name, bool(getattr(item, name)) or bool(value))
        elif getattr(item, name, None) in (None, ""):
            setattr(item, name, value)


def _merge_attrs(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for name, value in incoming.items():
        if value is None:
            continue
        current = target.get(name)
        if isinstance(current, list) and isinstance(value, list):
            _extend(current, [v for v in value if isinstance(v, str)])
            if not all(isinstance(v, str) for v in value):
                current.extend(v for v in value if not isinstance(v, str))
        elif name not in target or target[name] in (None, "", [], {}):
            target[name] = value


# --------------------------------------------------------------------------- per scan


def _first_str(*values: Any) -> str | None:
    for value in values:
        text = normalize.clean_text(value)
        if text:
            return text
    return None


def _title(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


def _entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (str(entry.get("record_id") or ""), str(entry.get("match_kind") or ""))


def _alert_keys(pack: dict[str, Any]) -> set[tuple[str, str]]:
    """The verdict's own predicates decide which entries may carry an alert."""
    qualifying = list(qualifying_lot_hits(pack)) + list(_qualifying_all_lots(pack))
    return {_entry_key(entry) for entry in qualifying}


def _link_kind(match_kind: str | None, default: str) -> str:
    """A named kind keeps its name; an unrecognised one is weak, non-alert `related`."""
    kind = str(match_kind or "").strip()
    if not kind:
        return default
    if kind in MATCH_KIND_LINK_KINDS:
        return kind
    return "related"


class _ScanContext:
    """The node ids one scan minted, so records can be attached to them."""

    def __init__(self, scan_id: str, created_at: str | None) -> None:
        self.scan_id = scan_id
        self.created_at = created_at or ""
        self.medicines: dict[str, str] = {}  # drug_key -> node id
        self.label_medicine: str | None = None
        self.product: str | None = None
        self.ndc9: str | None = None
        self.lot: str | None = None
        self.manufacturer: str | None = None
        self.imprint: str | None = None
        self.aliases: dict[str, str] = {}  # evidence source_id -> node id


def _add_scan_node(graph: _Graph, doc: dict[str, Any], norm: dict[str, Any]) -> str:
    scan_id = str(doc.get("scan_id") or "")
    research = doc.get("research") or {}
    hardware = doc.get("hardware") or {}
    verdict = research.get("verdict")
    name = _first_str(norm.get("generic_name"), norm.get("brand_name")) or "Unreadable label"
    strength = _first_str(norm.get("strength"))
    label = f"{_title(name)} {strength}" if strength else _title(name)
    created = normalize.clean_text(doc.get("created_at"))
    model = hardware.get("model")
    attrs: dict[str, Any] = {
        "headline": _first_str(research.get("headline")),
        "verdict_label": VERDICT_LABELS.get(str(verdict or "")),
        # Expiry and a degraded instrument are different facts and stay apart.
        "expired": norm.get("expired"),
        "gaps_n": len(research.get("gaps") or []),
        "lot": norm.get("lot"),
        "ndc9": norm.get("ndc9"),
        "imprint": norm.get("imprint_norm"),
    }
    if hardware:
        attrs["hardware"] = {
            "status": hardware.get("status"),
            "degraded": hardware.get("degraded"),
            "simulated": bool(hardware.get("limitations")) or model == "mock-spectrometry",
            "model": model,
            "confidence": hardware.get("confidence"),
            "pill_type": hardware.get("pill_type"),
        }
    thumb = _thumb_url(doc)
    if thumb:
        attrs["thumb_url"] = thumb
    return graph.node(
        "scan",
        scan_id,
        label,
        scan_id=scan_id,
        created_at=created,
        sublabel=_scan_sublabel(created, doc.get("country")),
        val=3.2,
        personal=True,
        expandable=True,
        date=created,
        verdict=verdict,
        risk_level=research.get("risk_level"),
        status=doc.get("status"),
        demo=bool(doc.get("demo")),
        attrs={k: v for k, v in attrs.items() if v is not None},
    )


def _thumb_url(doc: dict[str, Any]) -> str | None:
    """No scan carries one today; the contract keeps the slot so one can."""
    direct = normalize.clean_text(doc.get("thumb_url"))
    if direct:
        return direct
    for photo in doc.get("photos") or []:
        if isinstance(photo, dict):
            found = normalize.clean_text(photo.get("thumb_url"))
            if found:
                return found
    return None


def _scan_sublabel(created: str | None, country: Any) -> str | None:
    place = keys.country_label(country)
    day = (created or "")[:10]
    if day and place:
        return f"Scanned {day} · {place}"
    if day:
        return f"Scanned {day}"
    return f"Scanned in {place}" if place else None


def _add_label_nodes(graph: _Graph, ctx: _ScanContext, doc: dict[str, Any],
                     norm: dict[str, Any], scan_node: str) -> None:
    created = ctx.created_at
    generic = keys.drug_key(norm.get("generic_name"))
    brand = keys.drug_key(norm.get("brand_name"))
    for key, raw, is_brand in (
        (generic, norm.get("generic_name"), False),
        (brand, norm.get("brand_name"), True),
    ):
        if not key:
            continue
        nid = graph.node(
            "medicine", key, _title(key), scan_id=ctx.scan_id, created_at=created,
            val=2.2, expandable=True, count=1,
            attrs={"aliases": [normalize.clean_text(raw) or key], "brand": is_brand},
        )
        ctx.medicines[key] = nid
        if not is_brand:
            ctx.label_medicine = nid
        graph.link(scan_node, "names", nid, weight=0.8, strong=True, scan_id=ctx.scan_id)
    if generic and brand and generic != brand:
        graph.link(
            ctx.medicines[brand], "brand_of", ctx.medicines[generic],
            weight=0.6, strong=True, scan_id=ctx.scan_id,
        )
    if ctx.label_medicine is None and brand:
        ctx.label_medicine = ctx.medicines[brand]

    ndc9 = normalize.clean_text(norm.get("ndc9"))
    if ndc9:
        ctx.ndc9 = ndc9
        ctx.product = graph.node(
            "product", ndc9, f"NDC {normalize.clean_text(norm.get('ndc_raw')) or ndc9}",
            scan_id=ctx.scan_id, created_at=created, val=2.2, expandable=True, count=1,
            attrs={"ndc9": ndc9, "product_ndc": f"{ndc9[:5]}-{ndc9[5:]}"},
        )
        graph.link(scan_node, "labelled_ndc", ctx.product, weight=0.8, strong=True,
                   scan_id=ctx.scan_id)

    lot = keys.lot_key(norm.get("lot"))
    if lot:
        ctx.lot = graph.node(
            "lot", lot, f"Lot {lot}", scan_id=ctx.scan_id, created_at=created,
            val=2.2, expandable=True, attrs={"lot": lot},
        )
        graph.link(scan_node, "labelled_lot", ctx.lot, weight=0.8, strong=True,
                   scan_id=ctx.scan_id)

    maker = keys.company_key(norm.get("manufacturer"))
    if maker:
        ctx.manufacturer = graph.node(
            "manufacturer", maker, maker.title(), scan_id=ctx.scan_id, created_at=created,
            val=2.4, expandable=True, count=1,
            attrs={"variants": [normalize.clean_text(norm.get("manufacturer")) or maker]},
        )
        graph.link(scan_node, "labelled_maker", ctx.manufacturer, weight=0.6, strong=True,
                   scan_id=ctx.scan_id)

    imprint = keys.imprint_key(norm.get("imprint_norm"))
    if imprint:
        ctx.imprint = graph.node(
            "imprint", imprint, f"Imprint {imprint}", scan_id=ctx.scan_id, created_at=created,
            val=1.8, expandable=True,
            attrs={"shape": norm.get("shape"), "colors": list(norm.get("colors") or [])},
        )
        graph.link(scan_node, "observed_imprint", ctx.imprint, weight=0.6, strong=True,
                   scan_id=ctx.scan_id)

    country = keys.country_key(doc.get("country"))
    if country:
        nid = graph.node(
            "country", country, keys.country_label(doc.get("country")) or country,
            scan_id=ctx.scan_id, created_at=created, val=1.8, expandable=True,
        )
        graph.link(scan_node, "scanned_in", nid, weight=0.1, scan_id=ctx.scan_id)

    if ctx.product and ctx.label_medicine:
        graph.link(ctx.product, "contains", ctx.label_medicine, weight=0.6, strong=True,
                   scan_id=ctx.scan_id)
    if ctx.product and ctx.manufacturer:
        graph.link(ctx.product, "registered_to", ctx.manufacturer, weight=0.6, strong=True,
                   scan_id=ctx.scan_id)


def _record_node(graph: _Graph, ctx: _ScanContext, entry: dict[str, Any], tier: str) -> str | None:
    record_id = normalize.clean_text(entry.get("record_id"))
    if not record_id:
        return None
    org = normalize.clean_text(entry.get("source_org"))
    date = normalize.clean_text(entry.get("recency_date"))
    reason = _first_str(entry.get("summary"), entry.get("title"))
    nid = graph.node(
        "record",
        record_id,
        normalize.clean_text(entry.get("title")) or record_id,
        scan_id=ctx.scan_id,
        created_at=ctx.created_at,
        sublabel=_record_sublabel(org, date),
        val=2.8,
        expandable=True,
        date=date,
        url=normalize.clean_text(entry.get("url")),
        severity=normalize.clean_text(entry.get("severity")),
        source_org=org,
        freshness=normalize.clean_text(entry.get("freshness")),
        match_tier=tier,
        attrs={
            "doc_type": entry.get("doc_type"),
            "lot_count": entry.get("lot_count"),
            "covers_all_lots": bool(entry.get("covers_all_lots")),
            "age_days": entry.get("age_days"),
            "status": entry.get("status"),
        },
    )
    ctx.aliases[record_id] = nid
    _record_context(graph, ctx, entry, nid, reason)
    return nid


def _record_sublabel(org: str | None, date: str | None) -> str | None:
    day = (date or "")[:10]
    if org and day:
        return f"{org} · {day}"
    return org or (day or None)


def _record_context(graph: _Graph, ctx: _ScanContext, entry: dict[str, Any], record: str,
                    reason: str | None) -> None:
    org = normalize.clean_text(entry.get("source_org"))
    org_key = keys.regulator_key(org)
    if org_key:
        nid = graph.node("regulator", org_key, org or org_key.upper(), created_at=ctx.created_at,
                         val=3.6, expandable=True, source_org=org)
        graph.link(record, "issued_by", nid, weight=0.5, strong=True)

    # A record joins a medicine only when a scan already minted that node: regulator
    # titles produce fragments like "batches of healmoxy" and "various products".
    for name in (entry.get("drug_names") or [])[:3]:
        key = keys.drug_key(name)
        if key and key in ctx.medicines:
            graph.link(record, "about", ctx.medicines[key], weight=0.5, strong=True)

    maker = keys.company_key(entry.get("manufacturer"))
    if maker:
        falsified = str(entry.get("doc_type") or "") == "falsified_alert"
        nid = graph.node(
            "manufacturer", maker, maker.title(), created_at=ctx.created_at, val=2.4,
            expandable=True,
            sublabel="name printed on the label" if falsified else None,
            attrs={
                "variants": [normalize.clean_text(entry.get("manufacturer")) or maker],
                "stated_only": True if falsified else None,
            },
        )
        if falsified:
            # The firm on a falsified pack is usually the firm that was copied.
            graph.link(record, "stated_manufacturer", nid, weight=0.5, strong=False)
        else:
            graph.link(record, "names_maker", nid, weight=0.5, strong=True)

    countries = list(entry.get("countries") or [])
    for country in countries[:CAP_COUNTRIES]:
        key = keys.country_key(country)
        if not key:
            continue
        nid = graph.node("country", key, keys.country_label(country) or key,
                         created_at=ctx.created_at, val=1.8, expandable=True)
        graph.link(record, "affects", nid, weight=0.3, strong=True)
    if len(countries) > CAP_COUNTRIES:
        graph.nodes[record].attrs.setdefault("more_countries", len(countries) - CAP_COUNTRIES)

    topic = keys.topic_of(entry.get("doc_type"), reason)
    if topic:
        key, label = topic
        nid = graph.node("topic", key, label, created_at=ctx.created_at, val=1.8,
                         expandable=True)
        graph.link(record, "topic", nid, weight=0.2)


def _walk_pack(graph: _Graph, ctx: _ScanContext, pack: dict[str, Any], scan_node: str) -> None:
    alerts = _alert_keys(pack)
    anchor_lot = ctx.lot
    anchor_product = ctx.product or ctx.label_medicine

    def qualifies(kind: str, entry: dict[str, Any]) -> bool:
        return kind in ALERT_CAPABLE_KINDS and _entry_key(entry) in alerts

    for entry in pack.get("exact_lot_hits") or []:
        kind = _link_kind(entry.get("match_kind"), "lot_only_match")
        tier = "match" if qualifies(kind, entry) else "context"
        record = _record_node(graph, ctx, entry, tier)
        if record and anchor_lot:
            _emit(graph, ctx, anchor_lot, kind, record, entry, alerts)

    for entry in (pack.get("all_lots_hits") or [])[:CAP_ALL_LOTS]:
        kind = _link_kind(entry.get("match_kind"), "all_lots_sibling")
        tier = "match" if qualifies(kind, entry) else "product"
        record = _record_node(graph, ctx, entry, tier)
        if record and anchor_product:
            _emit(graph, ctx, anchor_product, kind, record, entry, alerts)

    ndc_hits = list(pack.get("ndc_hits") or [])
    for entry in ndc_hits[:CAP_NDC]:
        kind = _link_kind(entry.get("match_kind"), "product_line_match")
        if qualifies(kind, entry):
            tier = "match"
        else:
            tier = "product" if kind == "ndc_in_description" else "context"
        record = _record_node(graph, ctx, entry, tier)
        if record and anchor_product:
            _emit(graph, ctx, anchor_product, kind, record, entry, alerts)
    if len(ndc_hits) > CAP_NDC and anchor_product:
        _cluster(graph, anchor_product, "product_line", len(ndc_hits) - CAP_NDC, "more records")

    for entry in (pack.get("regulatory_hits") or [])[:CAP_REGULATORY]:
        record = _record_node(graph, ctx, entry, "context")
        if record and ctx.label_medicine:
            graph.link(ctx.label_medicine, "related", record, weight=0.15,
                       match_kind=entry.get("match_kind"), scan_id=ctx.scan_id)

    for entry in (pack.get("ndc_directory") or [])[:CAP_DIRECTORY]:
        _directory_entry(graph, ctx, entry)

    for entry in (pack.get("web_hits") or [])[:CAP_WEB]:
        _web_entry(graph, ctx, entry, scan_node)

    _pill_candidates(graph, ctx, pack)


def _emit(graph: _Graph, ctx: _ScanContext, source: str, kind: str, record: str,
          entry: dict[str, Any], alerts: set[tuple[str, str]]) -> None:
    alert = kind in ALERT_CAPABLE_KINDS and _entry_key(entry) in alerts
    graph.link(
        source,
        kind,
        record,
        weight=_KIND_WEIGHTS.get(kind, 0.2),
        strong=kind not in NEVER_STRONG and (alert or kind not in WEAK_UNLESS_ALERT),
        alert=alert,
        match_kind=normalize.clean_text(entry.get("match_kind")),
        scan_id=ctx.scan_id,
    )


def _directory_entry(graph: _Graph, ctx: _ScanContext, entry: dict[str, Any]) -> None:
    ndc9 = normalize.clean_text(entry.get("ndc9")) or keys.product_key(entry.get("product_ndc"))
    if not ndc9:
        return
    generic = normalize.clean_text(entry.get("generic_name"))
    strengths = [s for s in (entry.get("strengths") or []) if s]
    labeler = normalize.clean_text(entry.get("labeler_name"))
    parts = [p for p in (_title(generic or ""), strengths[0] if strengths else None) if p]
    label = " ".join(parts)
    if labeler:
        label = f"{label} · {labeler}" if label else labeler
    nid = graph.node(
        "product", ndc9, label or f"NDC {entry.get('product_ndc')}", scan_id=ctx.scan_id,
        created_at=ctx.created_at, val=2.2, expandable=True,
        attrs={
            "product_ndc": entry.get("product_ndc"),
            "dosage_form": entry.get("dosage_form"),
            "listing_expired": bool(entry.get("is_listing_expired")),
            "brand_name": entry.get("brand_name"),
        },
    )
    ctx.aliases[f"ndc-{entry.get('product_ndc')}"] = nid
    key = keys.drug_key(generic)
    if key and key in ctx.medicines:
        graph.link(nid, "contains", ctx.medicines[key], weight=0.6, strong=True,
                   scan_id=ctx.scan_id)
    maker = keys.company_key(labeler)
    if maker:
        mid = graph.node("manufacturer", maker, maker.title(), created_at=ctx.created_at,
                         val=2.4, expandable=True, attrs={"variants": [labeler or maker]})
        graph.link(nid, "registered_to", mid, weight=0.6, strong=True, scan_id=ctx.scan_id)


def _web_entry(graph: _Graph, ctx: _ScanContext, entry: dict[str, Any], scan_node: str) -> None:
    key = keys.web_key(entry.get("page_id") or entry.get("url"))
    if not key:
        return
    domain = normalize.clean_text(entry.get("domain"))
    nid = graph.node(
        "web_page", key, normalize.clean_text(entry.get("title")) or domain or "Web page",
        scan_id=ctx.scan_id, created_at=ctx.created_at, sublabel=domain, val=1.6,
        expandable=True, url=normalize.clean_text(entry.get("url")),
        date=normalize.clean_text(entry.get("recency_date")),
        source_org=normalize.clean_text(entry.get("source_org")),
        freshness=normalize.clean_text(entry.get("freshness")),
        attrs={
            "domain": domain,
            "source_tier": entry.get("source_tier"),
            "flags": list(entry.get("flags") or []),
            "date_precision": entry.get("date_precision"),
        },
    )
    ctx.aliases[str(entry.get("source_id") or key)] = nid
    if str(entry.get("match_kind") or "") == "fetched_for_this_scan":
        graph.link(scan_node, "fetched_for", nid, weight=0.3, scan_id=ctx.scan_id)
    elif ctx.label_medicine:
        graph.link(ctx.label_medicine, "web_related", nid, weight=0.15, scan_id=ctx.scan_id)
    else:
        graph.link(scan_node, "fetched_for", nid, weight=0.3, scan_id=ctx.scan_id)
    if ctx.lot and normalize.normalize_lot(ctx.lot.split(":", 1)[-1]) in [
        normalize.normalize_lot(value) for value in (entry.get("lots_shown") or [])
    ]:
        graph.link(nid, "lists_lot", ctx.lot, weight=0.5, strong=True, scan_id=ctx.scan_id)
    org_key = keys.regulator_key(entry.get("source_org"))
    if org_key and str(entry.get("source_tier") or "") == "regulator":
        rid = graph.node("regulator", org_key,
                         normalize.clean_text(entry.get("source_org")) or org_key.upper(),
                         created_at=ctx.created_at, val=3.6, expandable=True)
        graph.link(nid, "published_by", rid, weight=0.4, strong=True)


_EXACT_IMPRINT = frozenset({"imprint_exact", "imprint_sorted", "imprint_all_parts"})


def _pill_candidates(graph: _Graph, ctx: _ScanContext, pack: dict[str, Any]) -> None:
    if not ctx.imprint:
        return
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in (pack.get("pill") or {}).get("candidates") or []:
        key = keys.drug_key(candidate.get("generic_name"))
        if not key:
            continue
        bucket = grouped.setdefault(key, {"count": 0, "kind": None, "raw": None})
        bucket["count"] += 1
        bucket["raw"] = bucket["raw"] or normalize.clean_text(candidate.get("generic_name"))
        kind = str(candidate.get("match_kind") or "")
        if bucket["kind"] is None or (kind in _EXACT_IMPRINT and bucket["kind"] not in _EXACT_IMPRINT):
            bucket["kind"] = kind
    for key, bucket in list(grouped.items())[:CAP_PILL_MEDICINES]:
        nid = graph.node(
            "medicine", key, _title(key), scan_id=ctx.scan_id, created_at=ctx.created_at,
            val=2.0, expandable=True, sublabel="from the imprint, not the label",
            attrs={"aliases": [bucket["raw"] or key]},
        )
        ctx.medicines.setdefault(key, nid)
        exact = bucket["kind"] in _EXACT_IMPRINT
        graph.link(ctx.imprint, "identifies_as", nid, weight=0.6 if exact else 0.25,
                   strong=exact, match_kind=bucket["kind"], scan_id=ctx.scan_id)


_CONFLICT_MEDICINE_FIELDS = frozenset({"imprint", "ndc_identity", "active_ingredient"})


def _mismatch_links(graph: _Graph, ctx: _ScanContext, research: dict[str, Any]) -> None:
    for mismatch in research.get("mismatches") or []:
        if not isinstance(mismatch, dict):
            continue
        field = str(mismatch.get("field") or "")
        if field in _CONFLICT_MEDICINE_FIELDS:
            key = keys.drug_key(mismatch.get("imprint_reference"))
            other = ctx.medicines.get(key or "") if key else None
            if other is None and key and len(key.split()) <= 3:
                other = graph.node("medicine", key, _title(key), scan_id=ctx.scan_id,
                                   created_at=ctx.created_at, val=2.0, expandable=True,
                                   sublabel="from the imprint, not the label")
                ctx.medicines[key] = other
            target = ctx.label_medicine
        elif field == "manufacturer":
            key = keys.company_key(mismatch.get("imprint_reference"))
            candidate = node_id("manufacturer", key) if key else None
            other = candidate if candidate in graph.nodes else None
            target = ctx.manufacturer
        else:
            continue
        if other and target and other != target:
            graph.link(other, "conflicts_with", target, weight=0.7, strong=True,
                       match_kind=field, scan_id=ctx.scan_id)


def _attach_findings(graph: _Graph, ctx: _ScanContext, research: dict[str, Any],
                     scan_node: str) -> None:
    for finding in research.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        item = {
            "statement": normalize.clean_text(finding.get("statement")),
            "severity": finding.get("severity"),
            "evidence_type": finding.get("evidence_type"),
        }
        if not item["statement"]:
            continue
        targets = {ctx.aliases[sid] for sid in finding.get("source_ids") or []
                   if sid in ctx.aliases}
        for target in targets or {scan_node}:
            node = graph.nodes.get(target)
            if node is not None:
                node.attrs.setdefault("findings", []).append(item)


def _sources_fallback(graph: _Graph, ctx: _ScanContext, research: dict[str, Any],
                      scan_node: str) -> None:
    """No pack (an older or errored scan), but the report cited something."""
    for entry in research.get("sources") or []:
        if not isinstance(entry, dict):
            continue
        sid = normalize.clean_text(entry.get("id"))
        title = normalize.clean_text(entry.get("title")) or sid
        url = normalize.clean_text(entry.get("url"))
        if not sid:
            continue
        if sid.startswith("web-") or (url and not sid.startswith(("fda-", "who-", "nafdac-",
                                                                  "mhra-", "hc-"))):
            key = keys.web_key(url or sid)
            if not key:
                continue
            nid = graph.node("web_page", key, title or "Web page", scan_id=ctx.scan_id,
                             created_at=ctx.created_at, val=1.6, url=url,
                             source_org=normalize.clean_text(entry.get("source_org")),
                             date=normalize.clean_text(entry.get("published_at")))
        else:
            nid = graph.node("record", sid, title or sid, scan_id=ctx.scan_id,
                             created_at=ctx.created_at, val=2.4, url=url, match_tier="context",
                             source_org=normalize.clean_text(entry.get("source_org")),
                             date=normalize.clean_text(entry.get("published_at")))
        graph.link(scan_node, "cited", nid, weight=0.2, scan_id=ctx.scan_id)


def _cluster(graph: _Graph, parent: str, relation: str, count: int, noun: str) -> str:
    key = keys.cluster_key(parent, relation)
    nid = graph.node(
        "cluster", key, f"+{count:,} {noun}", val=1.2, personal=False, expandable=True,
        count=count, attrs={"relation": relation, "parent": parent},
    )
    graph.link(parent, "more", nid, weight=0.1)
    return nid


# --------------------------------------------------------------------------- caps


def _apply_caps(graph: _Graph, max_nodes: int, max_links: int) -> bool:
    truncated = False
    if len(graph.nodes) > max_nodes:
        truncated = True
        _shed_nodes(graph, max_nodes)
    if len(graph.links) > max_links:
        truncated = True
        ranked = sorted(
            graph.links.values(),
            key=lambda item: (item.alert, item.strong, item.weight, -item.order),
        )
        for item in ranked[: len(graph.links) - max_links]:
            graph.links.pop(item.id, None)
    return truncated


def _shed_nodes(graph: _Graph, max_nodes: int) -> None:
    degree: dict[str, int] = {}
    for item in graph.links.values():
        degree[item.source] = degree.get(item.source, 0) + 1
        degree[item.target] = degree.get(item.target, 0) + 1

    def droppable(item: _Node) -> bool:
        return item.type != "scan"

    # Oldest scans' context first, then topic and country leaves.
    context = sorted(
        (n for n in graph.nodes.values() if droppable(n) and n.match_tier == "context"),
        key=lambda n: (n.oldest, -n.order),
    )
    leaves = sorted(
        (n for n in graph.nodes.values()
         if droppable(n) and n.type in ("topic", "country") and n.match_tier != "context"),
        key=lambda n: (degree.get(n.id, 0), n.oldest, -n.order),
    )
    rest = sorted(
        (n for n in graph.nodes.values()
         if droppable(n) and n.match_tier != "context" and n.type not in ("topic", "country")),
        key=lambda n: (n.type != "cluster", degree.get(n.id, 0), n.oldest, -n.order),
    )
    for item in [*context, *leaves, *rest]:
        if len(graph.nodes) <= max_nodes:
            break
        graph.nodes.pop(item.id, None)
    for lid, item in list(graph.links.items()):
        if item.source not in graph.nodes or item.target not in graph.nodes:
            graph.links.pop(lid, None)


# --------------------------------------------------------------------------- entry point


def graph_from_scans(
    scan_docs: Sequence[dict[str, Any]],
    *,
    max_nodes: int = 600,
    max_links: int = 1500,
) -> tuple[list[GraphNode], list[GraphLink], bool]:
    """Stored scan docs -> `(nodes, links, truncated)`. Pure; safe to call anywhere."""
    graph = _Graph()
    for doc in scan_docs:
        if not isinstance(doc, dict):
            continue
        scan_id = normalize.clean_text(doc.get("scan_id"))
        if not scan_id:
            continue
        norm = doc.get("norm") or {}
        ctx = _ScanContext(scan_id, normalize.clean_text(doc.get("created_at")))
        scan_node = _add_scan_node(graph, doc, norm)
        _add_label_nodes(graph, ctx, doc, norm, scan_node)

        status = str(doc.get("status") or "")
        evidence = doc.get("evidence") or {}
        pack = evidence.get("evidence_pack") or {}
        research = doc.get("research") or {}
        if status in _LABEL_ONLY_STATUSES or not pack:
            # No pack: either the scan never got that far, or it errored. Either way
            # the honest graph is the label and whatever the report cited.
            if research.get("sources"):
                _sources_fallback(graph, ctx, research, scan_node)
            continue

        _walk_pack(graph, ctx, pack, scan_node)
        _mismatch_links(graph, ctx, research)
        _attach_findings(graph, ctx, research, scan_node)

    truncated = _apply_caps(graph, max_nodes, max_links)
    nodes = [item.to_model() for item in sorted(graph.nodes.values(), key=lambda n: n.order)]
    links = [item.to_model() for item in sorted(graph.links.values(), key=lambda n: n.order)]
    return nodes, links, truncated
