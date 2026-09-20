"""`GET /graph/search`: hybrid retrieval plus the exact-lookup union.

Zero LLM calls. The semantic leg is Elastic's own inference on a
`semantic_text` field, and nothing here writes prose.

The union rule is the README's: a hybrid search alone can rank an exact lot or
NDC match off the end of the page, because `minmax` rescales each leg per query
and an old-but-exact record loses to a fresh fuzzy one. So a code-shaped query
also runs the exact lot lookup and an NDC-shaped query also runs the product
lookup, and the results are unioned rather than hoped for.

Lot hits from this endpoint carry **no product context at all**, so — exactly as
in `expand` — they are marked `lot_listed`: the page lists the lot, which is not
the same as "your lot was recalled". Path-finding was cut; `highlight` carries
the personal nodes worth lighting instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.graph.expand import (
    STATED_MANUFACTURER_SUBLABEL,
    Accumulator,
    country_node,
    make_link,
    manufacturer_node,
    product_node,
    record_node,
    regulator_node,
)
from backend.graph.models import (
    GraphMeta,
    GraphNode,
    SearchGraphResponse,
    SearchHit,
    clip_label,
)
from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Reg

if TYPE_CHECKING:  # pragma: no cover - the service module is another stream's
    from backend.graph.service import GraphContext

MAX_SIZE = 12
MAX_COUNTRIES = 3
MIN_HIGHLIGHT_TOKEN = 4
_FALSIFIED = "falsified_alert"


def query_tokens(q: str) -> list[str]:
    """Tokens long enough to mean something in a label."""
    out: list[str] = []
    for raw in str(q or "").casefold().split():
        token = raw.strip(".,;:()[]\"'")
        if len(token) >= MIN_HIGHLIGHT_TOKEN and token not in out:
            out.append(token)
    return out


def _normalised(scores: list[float]) -> list[float]:
    """Each leg is rescaled on its own: a constant_score 10.0 and a linear
    retriever's 2.2 are not comparable, and the page only needs a glow ramp."""
    top = max(scores) if scores else 0.0
    if top <= 0:
        return [1.0 for _ in scores]
    return [max(0.0, min(1.0, score / top)) for score in scores]


def _structure(acc: Accumulator, node: GraphNode, source: dict[str, Any]) -> None:
    """Regulator, maker and countries straight off the hit — no extra queries."""
    reg = regulator_node(source.get(Reg.SOURCE_ORG))
    if reg:
        acc.add_node(reg)
        acc.add_link(make_link(node.id, "issued_by", reg.id, strong=True))

    maker_raw = source.get(Reg.MANUFACTURER) or source.get(Reg.RECALLING_FIRM)
    falsified = normalize.clean_text(source.get(Reg.DOC_TYPE)) == _FALSIFIED
    mfr = manufacturer_node(
        maker_raw, sublabel=STATED_MANUFACTURER_SUBLABEL if falsified else None
    )
    if mfr:
        acc.add_node(mfr)
        acc.add_link(
            make_link(
                node.id,
                "stated_manufacturer" if falsified else "names_maker",
                mfr.id,
                strong=not falsified,
            )
        )

    countries = source.get(Reg.COUNTRIES)
    if isinstance(countries, str):
        countries = [countries]
    for country in list(countries or [])[:MAX_COUNTRIES]:
        node_c = country_node(country)
        if node_c:
            acc.add_node(node_c)
            acc.add_link(make_link(node.id, "affects", node_c.id, strong=True))


def _add_record(acc: Accumulator, hit: Any, score: float, kind: str) -> GraphNode:
    node = record_node(hit.id, hit.source, match_tier="context")
    merged = acc.add_node(node) or node
    merged.attrs["match_kind"] = kind
    merged.attrs["score"] = max(float(merged.attrs.get("score") or 0.0), score)
    _structure(acc, merged, hit.source)
    return merged


async def search_graph(
    ctx: GraphContext,
    q: str,
    *,
    device_id: str | None,
    size: int = 10,
) -> SearchGraphResponse:
    query = str(q or "").strip()
    size = max(1, min(int(size or 10), MAX_SIZE))
    acc = Accumulator()
    scores: dict[str, float] = {}
    snippets: dict[str, str | None] = {}

    hybrid = await ctx.search.search_regulatory(query, None, size=size, rerank=False)
    for hit, score in zip(hybrid, _normalised([h.score for h in hybrid]), strict=False):
        node = _add_record(acc, hit, score, hit.match_kind or "hybrid")
        scores[node.id] = max(scores.get(node.id, 0.0), score)
        snippets.setdefault(node.id, hit.highlight)

    # --- union leg 1: the query is one code-shaped token ---------------------
    code = normalize.code_token(query) if len(query.split()) == 1 else None
    if code:
        lot_hits = await ctx.search.recalls_by_lot(code)
        if lot_hits:
            lot = GraphNode(
                id=f"lot:{code}",
                type="lot",
                label=clip_label(f"Lot {code}"),
                expandable=True,
                attrs={"lot": code},
            )
            acc.add_node(lot)
        for hit, score in zip(
            lot_hits, _normalised([h.score for h in lot_hits]), strict=False
        ):
            node = _add_record(acc, hit, score, "lot_listed")
            # No product context was supplied, so this is only "the record lists
            # that lot string", never an exact-lot match.
            acc.add_link(
                make_link(f"lot:{code}", "lot_listed", node.id, match_kind="lot_listed")
            )
            scores[node.id] = max(scores.get(node.id, 0.0), score)
            snippets.setdefault(node.id, hit.highlight)

    # --- union leg 2: the query parses as an NDC -----------------------------
    forms = normalize.normalize_ndc(query)
    if forms is not None and (forms.ndc9 or forms.ndc11):
        ndc_hits = await ctx.search.recalls_by_ndc(forms)
        product_id = f"product:{forms.ndc9}" if forms.ndc9 else None
        if ndc_hits and product_id:
            acc.add_node(product_node(forms.ndc9 or "", {}))
        for hit, score in zip(
            ndc_hits, _normalised([h.score for h in ndc_hits]), strict=False
        ):
            kind = (
                hit.match_kind
                if hit.match_kind in ("ndc_in_description", "product_line_match")
                else "product_line_match"
            )
            node = _add_record(acc, hit, score, kind)
            if product_id:
                # A product-line hit never alerts: openFDA copies every sibling
                # strength's NDC onto every recall.
                acc.add_link(make_link(product_id, kind, node.id, strong=False))
            scores[node.id] = max(scores.get(node.id, 0.0), score)
            snippets.setdefault(node.id, hit.highlight)

    hits = [
        SearchHit(node_id=node_id, score=round(score, 4), highlight=snippets.get(node_id))
        for node_id, score in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    highlight = await _highlight(ctx, device_id, set(scores), query_tokens(query))
    nodes = list(acc.nodes.values())
    links = list(acc.links.values())
    return SearchGraphResponse(
        query=query,
        nodes=nodes,
        links=links,
        hits=hits,
        highlight=highlight,
        meta=GraphMeta(
            device_id=device_id,
            generated_at=normalize.to_iso(datetime.now(UTC)),
            source="live",
            counts={"nodes": len(nodes), "links": len(links), "hits": len(hits)},
        ),
    )


async def _highlight(
    ctx: GraphContext,
    device_id: str | None,
    hit_ids: set[str],
    tokens: list[str],
) -> list[str]:
    """Which of this device's own nodes the query is about.

    Only this device's personal graph is ever consulted, so another device's
    scan ids cannot appear in a search response.
    """
    if not device_id:
        return []
    try:
        personal = await ctx.personal(device_id)
    except KnowledgeError:
        # Search still works when the personal graph is unavailable.
        return []
    out: list[str] = []
    for node in personal.nodes:
        label = (node.label or "").casefold()
        if node.id in hit_ids or any(token in label for token in tokens):
            out.append(node.id)
    return out
