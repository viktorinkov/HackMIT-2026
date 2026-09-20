"""The graph contract: what `/graph` returns and what the Atlas page renders.

`static/js/config.js` mirrors the vocabularies here. Change one, change both.

Two rules every producer must keep:

- `GraphLink.alert` is evidence, not decoration. It is true only for the entries the
  verdict itself counts (`research.evidence.qualifying_lot_hits` and
  `_qualifying_all_lots`), so a red edge exists exactly when the stored evidence
  supports `recall_match`. A sibling NDC or a bare lot-string collision is never one.
- Nothing here is an assurance. There is no "ok" tier and no positive colour group;
  a scan with nothing found is neutral, never good.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.research.models import RiskLevel, Verdict

NodeType = Literal[
    "scan",
    "medicine",
    "product",
    "lot",
    "manufacturer",
    "record",
    "regulator",
    "country",
    "web_page",
    "imprint",
    "pill_ref",
    "topic",
    "cluster",
    # Crowd reports (peel-reports): where someone says they bought the medicine.
    "seller",
    "place",
]

# The id of every node is "<prefix>:<key>"; the key comes from `graph.keys`.
ID_PREFIX: dict[str, str] = {
    "scan": "scan",
    "medicine": "med",
    "product": "product",
    "lot": "lot",
    "manufacturer": "mfr",
    "record": "rec",
    "regulator": "reg",
    "country": "country",
    "web_page": "web",
    "imprint": "imprint",
    "pill_ref": "pillref",
    "topic": "topic",
    "cluster": "cluster",
    "seller": "seller",
    "place": "place",
}

LinkKind = Literal[
    # scan -> what its label says
    "names",
    "brand_of",
    "labelled_ndc",
    "labelled_lot",
    "labelled_maker",
    "observed_imprint",
    "scanned_in",
    # registry identity
    "contains",
    "registered_to",
    "sibling_strength",
    "makes",
    # lot / product -> record, one per match_kind the lookups emit
    "exact_lot",
    "lot_only_match",
    "lot_listed",
    "all_lots_product",
    "all_lots_sibling",
    "ndc_in_description",
    "product_line_match",
    "related",
    # record -> context
    "about",
    "issued_by",
    "affects",
    "names_maker",
    "stated_manufacturer",
    "topic",
    "same_event",
    # web pages
    "fetched_for",
    "web_related",
    "lists_lot",
    "published_by",
    "cited",
    # pill identification and disagreements
    "identifies_as",
    "conflicts_with",
    # crowd reports: a person's own statement about a purchase, never evidence
    "bought_from",
    "bought_in",
    "located_in",
    "also_reported",
    # structure
    "more",
]

# The only kinds that may ever carry alert=True. `ndc_in_description` qualifies
# only when the record also covers all lots; the builder decides that per entry.
ALERT_CAPABLE_KINDS: frozenset[str] = frozenset(
    {"exact_lot", "all_lots_product", "ndc_in_description"}
)

# A report is one person's unverified account of where they bought something. These
# kinds are never strong and never an alert, whatever the scan's verdict: the graph
# may show that reports cluster around a seller, not that the seller did anything.
REPORT_KINDS: frozenset[str] = frozenset(
    {"bought_from", "bought_in", "located_in", "also_reported"}
)

# How directly a record reached the user's scans. Best tier wins on merge.
MatchTier = Literal["match", "product", "context"]
MATCH_TIER_RANK: dict[str, int] = {"match": 3, "product": 2, "context": 1}

RecordSeverity = Literal["critical", "high", "moderate", "unknown"]
ScanStatus = Literal["pending", "partial", "complete", "error"]
GraphSource = Literal["live", "cache", "demo", "snapshot"]

MAX_LABEL_CHARS = 40


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphNode(_Model):
    id: str
    type: NodeType
    label: str = Field(max_length=MAX_LABEL_CHARS)
    sublabel: str | None = None
    # Relative size hint; the page applies its own size law on top.
    val: float = 1.0
    # Minted from one of this device's scans, as opposed to backdrop or expansion.
    personal: bool = False
    backdrop: bool = False
    expandable: bool = False
    count: int | None = None
    date: str | None = None
    url: str | None = None
    severity: RecordSeverity | None = None
    verdict: Verdict | None = None
    risk_level: RiskLevel | None = None
    status: ScanStatus | None = None
    match_tier: MatchTier | None = None
    source_org: str | None = None
    freshness: str | None = None
    # Seeded or rehearsal data. The page shows a persistent chip while any is on screen.
    demo: bool = False
    scan_ids: list[str] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)


class GraphLink(_Model):
    # "<source>><kind>><target>": deterministic, so merging is idempotent.
    id: str
    source: str
    target: str
    kind: LinkKind
    strong: bool = False
    alert: bool = False
    weight: float = 0.2
    count: int = 1
    match_kind: str | None = None
    # An alert on a shared lot node is an alert only for these scans.
    scan_ids: list[str] = Field(default_factory=list)


class TimelineBucket(_Model):
    year: int
    total: int
    by_org: dict[str, int] = Field(default_factory=dict)


class GraphMeta(_Model):
    device_id: str | None = None
    scans: int = 0
    generated_at: str | None = None
    source: GraphSource = "live"
    demo: bool = False
    truncated: bool = False
    index_date: str | None = None
    # The no-assurance sentence the page prints under the legend.
    notice: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    timeline: list[TimelineBucket] = Field(default_factory=list)


class GraphResponse(_Model):
    nodes: list[GraphNode]
    links: list[GraphLink]
    meta: GraphMeta


class ExpandResponse(_Model):
    anchor: str
    nodes: list[GraphNode]
    links: list[GraphLink]
    meta: GraphMeta


class DetailProperty(_Model):
    key: str
    label: str
    value: str


class DetailFinding(_Model):
    statement: str
    severity: str | None = None
    evidence_type: str | None = None


class SourceAttribution(_Model):
    id: str
    title: str
    url: str | None = None
    source_org: str | None = None
    published_at: str | None = None
    # Licence line shown under the source, e.g. "WHO, CC BY-NC-SA 3.0 IGO".
    attribution: str | None = None
    # FDA records link to an API query, so the page labels them as JSON.
    link_label: str | None = None


class Backlink(_Model):
    node_id: str
    type: NodeType
    label: str
    relation: str
    scan_id: str | None = None


class NodeDetail(_Model):
    id: str
    type: NodeType
    title: str
    subtitle: str | None = None
    badges: list[str] = Field(default_factory=list)
    properties: list[DetailProperty] = Field(default_factory=list)
    # A short summary only. Never a regulator's full body text.
    body: str | None = None
    findings: list[DetailFinding] = Field(default_factory=list)
    mismatches: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    sources: list[SourceAttribution] = Field(default_factory=list)
    backlinks: list[Backlink] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    notice: str | None = None
    demo: bool = False


class SearchHit(_Model):
    node_id: str
    score: float
    highlight: str | None = None


class SearchGraphResponse(_Model):
    query: str
    nodes: list[GraphNode]
    links: list[GraphLink]
    hits: list[SearchHit]
    # Personal-graph node ids worth lighting for this query.
    highlight: list[str] = Field(default_factory=list)
    meta: GraphMeta


def node_id(node_type: str, key: str) -> str:
    return f"{ID_PREFIX[node_type]}:{key}"


def link_id(source: str, kind: str, target: str) -> str:
    return f"{source}>{kind}>{target}"


def clip_label(text: str | None, fallback: str = "") -> str:
    """Labels come from regulator prose and OCR; keep them one short line."""
    value = " ".join((text or fallback or "").split())
    if len(value) <= MAX_LABEL_CHARS:
        return value
    return value[: MAX_LABEL_CHARS - 1].rstrip() + "…"
