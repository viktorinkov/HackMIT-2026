"""`GET /graph/expand`: the neighbours of one node, with hard caps.

Three rules decide everything here:

* **Expansion never mints an alert.** `recalls_by_lot` stamps every hit
  `exact_lot` when the caller passes no product context at all, so a bare
  `lot:` expansion would otherwise turn two unrelated recalls that merely share
  a lot string into solid, alerting evidence. Without a `scan_id` that belongs
  to `device_id`, every lot hit is rewritten to the neutral kind `lot_listed`,
  `strong=False`, `alert=False`.
* **Lists are capped.** Anything past the cap collapses into a single
  `cluster:` node carrying the real total from `hits.total`. Cluster paging was
  cut, so a cluster is not expandable.
* **One device never sees another's scans.** `scan:` expansion 404s for a
  foreign scan, and a foreign `scan_id` passed alongside a lot is treated as no
  context at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.graph.keys import (
    cluster_key,
    company_key,
    country_key,
    country_label,
    drug_key,
    lot_key,
    regulator_key,
)
from backend.graph.models import (
    MATCH_TIER_RANK,
    ExpandResponse,
    GraphLink,
    GraphMeta,
    GraphNode,
    clip_label,
    link_id,
)
from backend.graph.queries import GraphQueries
from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Ndc, Reg, Web

if TYPE_CHECKING:  # pragma: no cover - the service module is another stream's
    from backend.graph.service import GraphContext

DEFAULT_LIMIT = 12
MAX_COUNTRIES = 8
MAX_LOTS = 12
MAX_MEDICINES = 3
MAX_SIBLINGS = 12
MAX_LOT_RECORDS = 20

_SEVERITIES = frozenset({"critical", "high", "moderate", "unknown"})
_EXPANDABLE_TYPES = frozenset(
    {"lot", "product", "record", "medicine", "manufacturer", "regulator", "country"}
)
_FALSIFIED = "falsified_alert"
# The one sentence that keeps a falsified alert from libelling its victim.
STATED_MANUFACTURER_SUBLABEL = "name printed on the label"

# Every regulator seeded into `peel-regulatory`. The node id carries a slug, the
# term query needs the stored value back.
_KNOWN_ORGS = {
    "fda": "FDA",
    "who": "WHO",
    "nafdac": "NAFDAC",
    "mhra": "MHRA",
    "health-canada": "Health Canada",
    "ema": "EMA",
    "nlm": "NLM",
}

_WEIGHTS: dict[str, float] = {
    "exact_lot": 1.0,
    "lot_only_match": 0.2,
    "lot_listed": 0.2,
    "all_lots_product": 0.9,
    "all_lots_sibling": 0.25,
    "ndc_in_description": 0.5,
    "product_line_match": 0.25,
    "related": 0.15,
    "contains": 0.6,
    "registered_to": 0.6,
    "sibling_strength": 0.2,
    "makes": 0.2,
    "about": 0.5,
    "issued_by": 0.5,
    "affects": 0.3,
    "names_maker": 0.5,
    "stated_manufacturer": 0.5,
    "same_event": 0.2,
    "lists_lot": 0.5,
    "published_by": 0.4,
    "more": 0.1,
}


# --------------------------------------------------------------------------- accumulator


class Accumulator:
    """Nodes and links keyed by id, merged best-wins so order cannot decide."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.links: dict[str, GraphLink] = {}

    def add_node(self, node: GraphNode | None) -> GraphNode | None:
        if node is None:
            return None
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        if _severity_rank(node.severity) > _severity_rank(existing.severity):
            existing.severity = node.severity
        if MATCH_TIER_RANK.get(node.match_tier or "", 0) > MATCH_TIER_RANK.get(
            existing.match_tier or "", 0
        ):
            existing.match_tier = node.match_tier
        for scan_id in node.scan_ids:
            if scan_id not in existing.scan_ids:
                existing.scan_ids.append(scan_id)
        existing.expandable = existing.expandable or node.expandable
        existing.sublabel = existing.sublabel or node.sublabel
        existing.attrs = {**node.attrs, **existing.attrs}
        return existing

    def add_link(self, link: GraphLink | None) -> GraphLink | None:
        if link is None:
            return None
        existing = self.links.get(link.id)
        if existing is None:
            self.links[link.id] = link
            return link
        existing.strong = existing.strong or link.strong
        existing.alert = existing.alert or link.alert
        existing.weight = max(existing.weight, link.weight)
        existing.count += link.count
        for scan_id in link.scan_ids:
            if scan_id not in existing.scan_ids:
                existing.scan_ids.append(scan_id)
        return existing

    def response(self, anchor: str, *, device_id: str | None) -> ExpandResponse:
        nodes = list(self.nodes.values())
        links = list(self.links.values())
        return ExpandResponse(
            anchor=anchor,
            nodes=nodes,
            links=links,
            meta=GraphMeta(
                device_id=device_id,
                generated_at=normalize.to_iso(datetime.now(UTC)),
                source="live",
                counts={"nodes": len(nodes), "links": len(links)},
            ),
        )


def _severity_rank(severity: str | None) -> int:
    return {"critical": 4, "high": 3, "moderate": 2, "unknown": 1}.get(severity or "", 0)


# --------------------------------------------------------------------------- factories


def make_link(
    source: str,
    kind: str,
    target: str,
    *,
    strong: bool = False,
    alert: bool = False,
    match_kind: str | None = None,
    scan_ids: list[str] | None = None,
    weight: float | None = None,
    count: int = 1,
) -> GraphLink:
    return GraphLink(
        id=link_id(source, kind, target),
        source=source,
        target=target,
        kind=kind,  # type: ignore[arg-type]
        strong=strong,
        alert=alert,
        weight=_WEIGHTS.get(kind, 0.2) if weight is None else weight,
        count=count,
        match_kind=match_kind or kind,
        scan_ids=list(scan_ids or []),
    )


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def record_node(
    record_id: str,
    source: dict[str, Any],
    *,
    match_tier: str = "context",
    scan_ids: list[str] | None = None,
) -> GraphNode:
    severity = str(source.get(Reg.SEVERITY) or "").strip().lower()
    date = normalize.clean_text(source.get(Reg.RECENCY_DATE))
    age = normalize.age_days(date)
    lots = _as_list(source.get(Reg.LOT_NUMBERS))
    return GraphNode(
        id=f"rec:{record_id}",
        type="record",
        label=clip_label(source.get(Reg.TITLE), record_id),
        sublabel=normalize.clean_text(source.get(Reg.SOURCE_ORG)),
        val=1.4,
        personal=False,
        expandable=True,
        date=date,
        url=normalize.clean_text(source.get(Reg.URL)),
        severity=severity if severity in _SEVERITIES else "unknown",  # type: ignore[arg-type]
        match_tier=match_tier,  # type: ignore[arg-type]
        source_org=normalize.clean_text(source.get(Reg.SOURCE_ORG)),
        freshness=normalize.freshness_label(age),
        scan_ids=list(scan_ids or []),
        attrs={
            "record_id": record_id,
            "doc_type": normalize.clean_text(source.get(Reg.DOC_TYPE)),
            "lot_count": len(lots),
            "covers_all_lots": bool(source.get(Reg.COVERS_ALL_LOTS)),
            "age_days": age,
            "event_id": normalize.clean_text(source.get(Reg.EVENT_ID)),
        },
    )


def regulator_node(raw: str | None) -> GraphNode | None:
    org = normalize.clean_text(raw)
    key = regulator_key(org)
    if not org or not key:
        return None
    return GraphNode(
        id=f"reg:{key}",
        type="regulator",
        label=clip_label(org),
        val=2.0,
        expandable=True,
        source_org=org,
        attrs={"source_org": org},
    )


def manufacturer_node(raw: str | None, *, sublabel: str | None = None) -> GraphNode | None:
    key = company_key(raw)
    if not key:
        return None
    return GraphNode(
        id=f"mfr:{key}",
        type="manufacturer",
        label=clip_label(raw),
        sublabel=sublabel,
        val=1.2,
        expandable=True,
        attrs={"key": key, "variants": [normalize.clean_text(raw)]},
    )


def medicine_node(raw: str | None) -> GraphNode | None:
    key = drug_key(raw)
    if not key:
        return None
    return GraphNode(
        id=f"med:{key}",
        type="medicine",
        label=clip_label(raw, key),
        val=1.2,
        expandable=True,
        attrs={"key": key, "aliases": [normalize.clean_text(raw)]},
    )


def country_node(raw: str | None) -> GraphNode | None:
    key = country_key(raw)
    name = country_label(raw)
    if not key or not name:
        return None
    return GraphNode(
        id=f"country:{key}",
        type="country",
        label=clip_label(name),
        val=0.8,
        expandable=True,
        attrs={"name": name},
    )


def lot_node(raw: str) -> GraphNode | None:
    lot = lot_key(raw) or normalize.clean_text(raw)
    if not lot:
        return None
    return GraphNode(
        id=f"lot:{lot}",
        type="lot",
        label=clip_label(f"Lot {lot}"),
        val=1.0,
        expandable=True,
        attrs={"lot": lot},
    )


def product_node(ndc9: str, source: dict[str, Any] | None = None) -> GraphNode:
    source = source or {}
    generic = normalize.clean_text(source.get(Ndc.GENERIC_NAME))
    labeler = normalize.clean_text(source.get(Ndc.LABELER_NAME))
    strengths = _as_list(source.get(Ndc.STRENGTHS))
    parts = [p for p in (generic, strengths[0] if strengths else None) if p]
    label = " ".join(parts) if parts else f"NDC {source.get(Ndc.PRODUCT_NDC) or ndc9}"
    return GraphNode(
        id=f"product:{ndc9}",
        type="product",
        label=clip_label(label),
        sublabel=labeler,
        val=1.1,
        expandable=True,
        attrs={
            "ndc9": ndc9,
            "product_ndc": normalize.clean_text(source.get(Ndc.PRODUCT_NDC)),
            "dosage_form": normalize.clean_text(source.get(Ndc.DOSAGE_FORM)),
            "listing_expired": bool(source.get(Ndc.IS_LISTING_EXPIRED)),
        },
    )


def web_node(page_id: str, source: dict[str, Any]) -> GraphNode:
    url = normalize.clean_text(source.get(Web.URL))
    domain = normalize.clean_text(source.get(Web.DOMAIN)) or (
        normalize.domain_of(url) if url else None
    )
    date = normalize.clean_text(source.get(Web.RECENCY_DATE))
    return GraphNode(
        id=f"web:{page_id}",
        type="web_page",
        label=clip_label(source.get(Web.TITLE), domain or page_id),
        sublabel=domain,
        val=0.9,
        expandable=False,
        date=date,
        url=url,
        source_org=normalize.clean_text(source.get(Web.SOURCE_ORG)),
        freshness=normalize.freshness_label(normalize.age_days(date)),
        attrs={
            "page_id": page_id,
            "domain": domain,
            "source_tier": normalize.clean_text(source.get(Web.SOURCE_TIER)),
        },
    )


def cluster_node(
    parent_id: str, relation: str, count: int, noun: str, *, label: str | None = None
) -> GraphNode | None:
    """One node standing in for everything past the cap. Paging was cut."""
    if count <= 0:
        return None
    return GraphNode(
        id=f"cluster:{cluster_key(parent_id, relation)}",
        type="cluster",
        label=clip_label(label or f"+{count:,} more {noun}"),
        val=1.0,
        expandable=False,
        count=count,
        attrs={"relation": relation, "parent": parent_id, "count": count},
    )


def add_cluster(
    acc: Accumulator,
    parent_id: str,
    relation: str,
    count: int,
    noun: str,
    *,
    label: str | None = None,
) -> None:
    node = cluster_node(parent_id, relation, count, noun, label=label)
    if node is None:
        return
    acc.add_node(node)
    acc.add_link(make_link(parent_id, "more", node.id, count=count))


_ANCHOR_TYPES: dict[str, str] = {
    "scan": "scan",
    "med": "medicine",
    "product": "product",
    "lot": "lot",
    "mfr": "manufacturer",
    "rec": "record",
    "reg": "regulator",
    "country": "country",
    "web": "web_page",
    "imprint": "imprint",
    "pillref": "pill_ref",
    "topic": "topic",
    "cluster": "cluster",
}


def anchor_node(node_id: str) -> GraphNode:
    """A stand-in for the node being expanded, so no link dangles on merge.

    Only used when the handler did not already mint a richer version of it.
    """
    prefix, _, key = node_id.partition(":")
    if prefix == "lot" and key:
        return lot_node(key) or GraphNode(
            id=node_id, type="lot", label=clip_label(f"Lot {key}"), expandable=True
        )
    if prefix == "product" and key:
        return product_node(key)
    node_type = _ANCHOR_TYPES.get(prefix, "topic")
    if prefix == "reg":
        label = _KNOWN_ORGS.get(key, key)
    elif prefix == "country":
        label = country_label(key.replace("-", " ")) or key
    else:
        label = key
    return GraphNode(
        id=node_id,
        type=node_type,  # type: ignore[arg-type]
        label=clip_label(label or node_id),
        expandable=node_type in _EXPANDABLE_TYPES,
        attrs={"key": key},
    )


def _queries(ctx: GraphContext) -> GraphQueries:
    """The service may hand us one; otherwise wrap its client here."""
    existing = getattr(ctx, "queries", None)
    return existing if existing is not None else GraphQueries(ctx.es)


# --------------------------------------------------------------------------- entry point


async def expand_node(
    ctx: GraphContext,
    node_id: str,
    *,
    device_id: str | None,
    scan_id: str | None,
    limit: int = DEFAULT_LIMIT,
) -> ExpandResponse:
    limit = max(1, min(int(limit or DEFAULT_LIMIT), 25))
    prefix, _, key = node_id.partition(":")
    acc = Accumulator()

    if prefix == "scan":
        return await _expand_scan(ctx, node_id, key, device_id=device_id)

    if not key:
        return acc.response(node_id, device_id=device_id)

    handlers = {
        "lot": _expand_lot,
        "product": _expand_product,
        "rec": _expand_record,
        "med": _expand_medicine,
        "mfr": _expand_manufacturer,
        "reg": _expand_regulator,
        "country": _expand_country,
    }
    handler = handlers.get(prefix)
    if handler is None:
        # imprint, pill_ref, topic, web and cluster expansions were cut.
        return acc.response(node_id, device_id=device_id)

    await handler(ctx, acc, node_id, key, device_id=device_id, scan_id=scan_id, limit=limit)
    # The handler usually mints a richer version of the anchor itself; this only
    # covers the rest, because a link to a missing node crashes the layout.
    if node_id not in acc.nodes:
        acc.add_node(anchor_node(node_id))
    return acc.response(node_id, device_id=device_id)


# --------------------------------------------------------------------------- lot


def product_names(norm: dict[str, Any]) -> list[str]:
    """Every name the label gave, exactly as `research.pipeline._product_names`."""
    out: list[str] = []
    values = list(norm.get("drug_names") or []) + [
        norm.get("generic_name"),
        norm.get("brand_name"),
    ]
    for value in values:
        text = str(value).strip() if value else ""
        if text and text not in out:
            out.append(text)
    return out


async def _verified_scan(
    ctx: GraphContext, scan_id: str | None, device_id: str | None
) -> dict[str, Any] | None:
    """The scan doc only when it really is this device's. Otherwise no context."""
    if not scan_id or not device_id:
        return None
    doc = await ctx.scans.get(scan_id)
    if not doc or doc.get("device_id") != device_id:
        return None
    return doc


async def _expand_lot(
    ctx: GraphContext,
    acc: Accumulator,
    node_id: str,
    key: str,
    *,
    device_id: str | None,
    scan_id: str | None,
    limit: int,
    **_: Any,
) -> None:
    scan = await _verified_scan(ctx, scan_id, device_id)
    norm = (scan or {}).get("norm") or {}
    ndc9 = normalize.clean_text(norm.get("ndc9")) if scan else None
    names = product_names(norm) if scan else []
    verified = scan is not None
    owner = [scan_id] if verified and scan_id else []

    hits = await ctx.search.recalls_by_lot(key, ndc9=ndc9, drug_names=names or None)
    shown = hits[:MAX_LOT_RECORDS]
    for hit in shown:
        if not verified:
            # `recalls_by_lot` stamps `exact_lot` on everything when it is given
            # no product context, so a bare lot expansion must not repeat it.
            kind, strong, alert, tier = "lot_listed", False, False, "context"
        elif hit.match_kind == "exact_lot":
            kind, strong, alert, tier = "exact_lot", True, True, "match"
        else:
            kind, strong, alert, tier = "lot_only_match", False, False, "context"
        node = record_node(hit.id, hit.source, match_tier=tier, scan_ids=owner)
        acc.add_node(node)
        acc.add_link(
            make_link(
                node_id,
                kind,
                node.id,
                strong=strong,
                alert=alert,
                match_kind=kind,
                scan_ids=owner,
            )
        )
    add_cluster(acc, node_id, "records", len(hits) - len(shown), "records")

    pages, total = await _queries(ctx).web_pages_by_lot(key)
    for raw in pages:
        source = dict(raw.get("_source") or {})
        page_id = normalize.clean_text(source.get(Web.PAGE_ID)) or str(raw.get("_id"))
        node = web_node(page_id, source)
        acc.add_node(node)
        acc.add_link(make_link(node.id, "lists_lot", node_id, strong=True))
    add_cluster(acc, node_id, "pages", total - len(pages), "pages")


# --------------------------------------------------------------------------- product


async def _expand_product(
    ctx: GraphContext,
    acc: Accumulator,
    node_id: str,
    key: str,
    *,
    limit: int,
    **_: Any,
) -> None:
    forms = normalize.normalize_ndc(key)
    if forms is None:
        return

    labeler = generic = None
    for hit in await ctx.search.ndc_directory(forms):
        source = hit.source
        acc.add_node(product_node(key, source))
        labeler = labeler or normalize.clean_text(source.get(Ndc.LABELER_NAME))
        generic = generic or normalize.clean_text(source.get(Ndc.GENERIC_NAME))
        med = medicine_node(source.get(Ndc.GENERIC_NAME))
        if med:
            acc.add_node(med)
            acc.add_link(make_link(node_id, "contains", med.id, strong=True))
        mfr = manufacturer_node(source.get(Ndc.LABELER_NAME))
        if mfr:
            acc.add_node(mfr)
            acc.add_link(make_link(node_id, "registered_to", mfr.id, strong=True))

    # A product-line hit says "a recall exists for this product line", never
    # "your lot was recalled", so neither kind is strong and neither alerts.
    hits = await ctx.search.recalls_by_ndc(forms)
    shown = hits[:limit]
    for hit in shown:
        kind = hit.match_kind if hit.match_kind in (
            "ndc_in_description",
            "product_line_match",
        ) else "product_line_match"
        node = record_node(hit.id, hit.source, match_tier="context")
        acc.add_node(node)
        acc.add_link(make_link(node_id, kind, node.id, strong=False, alert=False))
    add_cluster(acc, node_id, "records", len(hits) - len(shown), "records")

    if labeler and generic:
        siblings, total = await _queries(ctx).ndc_siblings(labeler, generic)
        seen = 0
        for raw in siblings[:MAX_SIBLINGS]:
            source = dict(raw.get("_source") or {})
            sibling = normalize.clean_text(source.get(Ndc.NDC9))
            if not sibling or sibling == key:
                continue
            node = product_node(sibling, source)
            acc.add_node(node)
            acc.add_link(make_link(node_id, "sibling_strength", node.id))
            seen += 1
        add_cluster(acc, node_id, "siblings", total - seen - 1, "strengths")


# --------------------------------------------------------------------------- record


async def _expand_record(
    ctx: GraphContext,
    acc: Accumulator,
    node_id: str,
    key: str,
    *,
    limit: int,
    **_: Any,
) -> None:
    source = await _queries(ctx).record(key)
    if not source:
        raise KnowledgeError(f"record {key} not found", status_code=404)

    record = record_node(key, source, match_tier="context")
    acc.add_node(record)

    reg = regulator_node(source.get(Reg.SOURCE_ORG))
    if reg:
        acc.add_node(reg)
        acc.add_link(make_link(node_id, "issued_by", reg.id, strong=True))

    doc_type = normalize.clean_text(source.get(Reg.DOC_TYPE))
    maker_raw = source.get(Reg.MANUFACTURER) or source.get(Reg.RECALLING_FIRM)
    if doc_type == _FALSIFIED:
        # The firm named on a falsified alert is usually the victim, not the
        # maker. Neutral kind, neutral colour, and the sublabel says so.
        mfr = manufacturer_node(maker_raw, sublabel=STATED_MANUFACTURER_SUBLABEL)
        kind, strong = "stated_manufacturer", False
    else:
        mfr = manufacturer_node(maker_raw)
        kind, strong = "names_maker", True
    if mfr:
        acc.add_node(mfr)
        acc.add_link(make_link(node_id, kind, mfr.id, strong=strong))

    countries = _as_list(source.get(Reg.COUNTRIES))
    for country in countries[:MAX_COUNTRIES]:
        node = country_node(country)
        if node:
            acc.add_node(node)
            acc.add_link(make_link(node_id, "affects", node.id, strong=True))

    names = _as_list(source.get(Reg.DRUG_NAMES)) or _as_list(
        source.get(Reg.DRUG_NAMES_EXTRACTED)
    )
    minted = 0
    for name in names:
        if minted >= MAX_MEDICINES:
            break
        med = medicine_node(name)
        if med is None or med.id in acc.nodes:
            continue
        acc.add_node(med)
        acc.add_link(make_link(node_id, "about", med.id, strong=True))
        minted += 1

    lots = _as_list(source.get(Reg.LOT_NUMBERS))
    for lot in lots[:MAX_LOTS]:
        node = lot_node(lot)
        if node is None:
            continue
        acc.add_node(node)
        acc.add_link(make_link(node.id, "lot_listed", node_id))
    if len(lots) > MAX_LOTS:
        # A record can name up to 500 lots. The cluster carries the full count,
        # not the overflow, because "142 lots" is the fact worth reading.
        add_cluster(
            acc,
            node_id,
            "lots",
            len(lots),
            "lots",
            label=f"{len(lots):,} lots in this record",
        )

    event_id = normalize.clean_text(source.get(Reg.EVENT_ID))
    if event_id:
        siblings, total = await _queries(ctx).records_by_event(
            event_id, exclude_record_id=key
        )
        for raw in siblings:
            sibling_id = str(raw.get("_id"))
            node = record_node(
                sibling_id, dict(raw.get("_source") or {}), match_tier="context"
            )
            acc.add_node(node)
            acc.add_link(make_link(node_id, "same_event", node.id))
        add_cluster(acc, node_id, "same_event", total - len(siblings), "in this event")


# --------------------------------------------------------------------------- key nodes


def _records_branch(
    acc: Accumulator,
    node_id: str,
    hits: list[dict[str, Any]],
    total: int,
    *,
    kind: str,
    noun: str,
) -> None:
    for raw in hits:
        record_id = str(raw.get("_id"))
        node = record_node(record_id, dict(raw.get("_source") or {}), match_tier="context")
        acc.add_node(node)
        acc.add_link(make_link(node_id, kind, node.id))
        reg = regulator_node(node.source_org)
        if reg:
            acc.add_node(reg)
            acc.add_link(make_link(node.id, "issued_by", reg.id, strong=True))
    add_cluster(acc, node_id, "records", total - len(hits), noun)


async def _expand_medicine(
    ctx: GraphContext, acc: Accumulator, node_id: str, key: str, *, limit: int, **_: Any
) -> None:
    hits, total = await _queries(ctx).records_by_drug(key, limit=limit)
    _records_branch(acc, node_id, hits, total, kind="related", noun="records")


async def _expand_manufacturer(
    ctx: GraphContext, acc: Accumulator, node_id: str, key: str, *, limit: int, **_: Any
) -> None:
    hits, total = await _queries(ctx).records_by_manufacturer(key, limit=limit)
    for raw in hits:
        record_id = str(raw.get("_id"))
        source = dict(raw.get("_source") or {})
        node = record_node(record_id, source, match_tier="context")
        acc.add_node(node)
        kind = (
            "stated_manufacturer"
            if normalize.clean_text(source.get(Reg.DOC_TYPE)) == _FALSIFIED
            else "names_maker"
        )
        acc.add_link(make_link(node.id, kind, node_id, strong=kind == "names_maker"))
        reg = regulator_node(node.source_org)
        if reg:
            acc.add_node(reg)
            acc.add_link(make_link(node.id, "issued_by", reg.id, strong=True))
    add_cluster(acc, node_id, "records", total - len(hits), "records")


async def _expand_regulator(
    ctx: GraphContext, acc: Accumulator, node_id: str, key: str, **_: Any
) -> None:
    org = _KNOWN_ORGS.get(key) or key.replace("-", " ").title()
    hits, total = await _queries(ctx).records_by_source_org(org)
    for raw in hits:
        node = record_node(
            str(raw.get("_id")), dict(raw.get("_source") or {}), match_tier="context"
        )
        acc.add_node(node)
        acc.add_link(make_link(node.id, "issued_by", node_id, strong=True))
    add_cluster(acc, node_id, "records", total - len(hits), f"{org} records")


async def _expand_country(
    ctx: GraphContext, acc: Accumulator, node_id: str, key: str, *, limit: int, **_: Any
) -> None:
    # The id carries the slug; `countries` is a keyword field of canonical names.
    name = country_label(key.replace("-", " ")) or key
    hits, total = await _queries(ctx).records_by_country(name, limit=limit)
    for raw in hits:
        node = record_node(
            str(raw.get("_id")), dict(raw.get("_source") or {}), match_tier="context"
        )
        acc.add_node(node)
        acc.add_link(make_link(node.id, "affects", node_id, strong=True))
        reg = regulator_node(node.source_org)
        if reg:
            acc.add_node(reg)
            acc.add_link(make_link(node.id, "issued_by", reg.id, strong=True))
    add_cluster(acc, node_id, "records", total - len(hits), "records")


# --------------------------------------------------------------------------- scan


async def _expand_scan(
    ctx: GraphContext, node_id: str, key: str, *, device_id: str | None
) -> ExpandResponse:
    doc = await ctx.scans.get(key) if key else None
    if not doc or not device_id or doc.get("device_id") != device_id:
        # Same answer for "no such scan" and "someone else's scan": a 404 must
        # not become an oracle for which scan ids exist.
        raise KnowledgeError(f"scan {key} not found", status_code=404)

    from backend.graph.builder import graph_from_scans  # lazy: another stream owns it

    nodes, links, truncated = graph_from_scans([doc])
    return ExpandResponse(
        anchor=node_id,
        nodes=nodes,
        links=links,
        meta=GraphMeta(
            device_id=device_id,
            scans=1,
            generated_at=normalize.to_iso(datetime.now(UTC)),
            source="live",
            truncated=truncated,
            counts={"nodes": len(nodes), "links": len(links)},
        ),
    )
