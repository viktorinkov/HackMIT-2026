"""Retrieval over the Peel knowledge base.

Two retrieval modes, kept deliberately separate:

* **Hybrid + decay** (`search_regulatory`, `search_web`) — a `linear` retriever whose
  top-level `filter` is pushed into every leg, so the vector leg searches a
  pre-filtered candidate set rather than filtering afterwards. Each leg is wrapped
  in `script_score` that multiplies by a gaussian recency decay with a floor.
* **Exact lookups** (`recalls_by_lot`, `recalls_by_ndc`, `ndc_directory`) — flat
  `constant_score` term queries, never decayed and never fused. `minmax`
  normalisation rescales each leg to [0, 1] per query, so the decay floor only
  survives as ordering *within* a leg; an old but exact lot match is therefore
  guaranteed by taking the UNION of these lookups with the hybrid hits, never by
  hoping it ranks.

The cluster has no ML nodes: vector search is only reachable through
`{"semantic": {...}}` on a `semantic_text` field. The `knn` retriever and
`query_vector_builder` are unavailable and must never appear here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from elasticsearch import ApiError, AsyncElasticsearch
from fastapi import Depends

from backend.config import Settings, get_settings
from backend.knowledge import normalize, vocab
from backend.knowledge.client import KnowledgeError, get_es
from backend.knowledge.fields import (
    NDC_INDEX,
    PILLS_INDEX,
    REGULATORY_DECAY,
    REGULATORY_INDEX,
    RERANK_INFERENCE_ID,
    SCANS_INDEX,
    WEB_DECAY,
    WEB_PAGES_INDEX,
    DecayProfile,
    Ndc,
    Pill,
    Reg,
    Scan,
    Web,
)
from backend.knowledge.normalize import ImprintForms, NdcForms

# doc.containsKey() is true for a mapped-but-empty field, so only .size() > 0
# protects doc[...].value from throwing and killing the shard.
DECAY_SCRIPT = (
    "double d = params.floor; "
    "if (doc[params.f].size() > 0) { "
    "d = params.floor + (1 - params.floor) * "
    "decayDateGauss(params.origin, params.scale, params.offset, 0.5, doc[params.f].value); "
    "} "
    "return _score * d;"
)

_BM25_WEIGHT = 1.0
_SEMANTIC_WEIGHT = 1.2
_REG_WINDOW = 100
_WEB_WINDOW = 50
_RERANK_WINDOW = 30
_EXACT_SIZE = 20
_NDC_PRECISE_BOOST = 10.0
_PILL_SIZE = 10
_SIZE_TOLERANCE_MM = 2.0

_INFERENCE_FIELDS = "_inference_fields"
_PILL_EXACT_KINDS = ("imprint_exact", "imprint_sorted")

_REG_TEXT_FIELDS = (
    f"{Reg.TITLE}^3",
    f"{Reg.DRUG_NAMES}.txt^2",
    f"{Reg.DRUG_NAMES_EXTRACTED}.txt^2",
    f"{Reg.MANUFACTURER}.txt^2",
    f"{Reg.REASON}^1.5",
    Reg.PRODUCT_DESCRIPTION,
    Reg.BODY,
)
_WEB_TEXT_FIELDS = (
    f"{Web.TITLE}^3",
    f"{Web.DRUG_NAMES}.txt^2",
    Web.DESCRIPTION,
    Web.CONTENT,
)


def utc_origin(now: datetime | None = None) -> str:
    """Decay anchor, passed per request so a query is reproducible and cacheable."""
    return (now or datetime.now(UTC)).date().isoformat()


@dataclass
class SearchFilters:
    """Trusted metadata pre-filters. Vision-derived attributes do not belong here."""

    drug_names: list[str] = field(default_factory=list)
    dosage_form: str | None = None
    doc_types: list[str] = field(default_factory=list)
    source_orgs: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    severities: list[str] = field(default_factory=list)
    max_age_days: int | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.drug_names,
                self.dosage_form,
                self.doc_types,
                self.source_orgs,
                self.countries,
                self.severities,
                self.max_age_days,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "drug_names": list(self.drug_names),
            "dosage_form": self.dosage_form,
            "doc_types": list(self.doc_types),
            "source_orgs": list(self.source_orgs),
            "countries": list(self.countries),
            "severities": list(self.severities),
            "max_age_days": self.max_age_days,
        }


@dataclass
class Hit:
    index: str
    id: str
    score: float
    source: dict[str, Any]
    match_kind: str | None = None
    age_days: int | None = None
    freshness: str = "unknown"
    highlight: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "id": self.id,
            "score": self.score,
            "source": self.source,
            "match_kind": self.match_kind,
            "age_days": self.age_days,
            "freshness": self.freshness,
            "highlight": self.highlight,
        }


@dataclass
class PillMatch:
    hits: list[Hit]
    rung: int
    shape_relaxed: bool
    filters_applied: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": [hit.to_dict() for hit in self.hits],
            "rung": self.rung,
            "shape_relaxed": self.shape_relaxed,
            "filters_applied": self.filters_applied,
        }


def _decay_leg(
    inner: dict[str, Any],
    *,
    weight: float,
    profile: DecayProfile,
    date_field: str,
    origin: str,
) -> dict[str, Any]:
    return {
        "weight": weight,
        "normalizer": "minmax",
        "retriever": {
            "standard": {
                "query": {
                    "script_score": {
                        "query": inner,
                        "script": {
                            "source": DECAY_SCRIPT,
                            "params": {
                                "f": date_field,
                                "floor": profile.floor,
                                "origin": origin,
                                "scale": f"{profile.scale_days}d",
                                "offset": f"{profile.offset_days}d",
                            },
                        },
                    }
                }
            }
        },
    }


def _regulatory_filters(filters: SearchFilters | None, origin: str) -> list[dict[str, Any]]:
    if filters is None:
        return []
    clauses: list[dict[str, Any]] = []
    if filters.drug_names:
        names = [name for name in (normalize.normalize_drug_name(n) for n in filters.drug_names) if name]
        if names:
            # Seeded names and names extracted from product_description are both valid.
            clauses.append(
                {
                    "bool": {
                        "should": [
                            {"terms": {Reg.DRUG_NAMES: names}},
                            {"terms": {Reg.DRUG_NAMES_EXTRACTED: names}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
    if filters.dosage_form:
        form = normalize.normalize_dosage_form(filters.dosage_form)
        if form:
            clauses.append({"term": {Reg.DOSAGE_FORM: form}})
    if filters.doc_types:
        clauses.append({"terms": {Reg.DOC_TYPE: list(filters.doc_types)}})
    if filters.source_orgs:
        clauses.append({"terms": {Reg.SOURCE_ORG: list(filters.source_orgs)}})
    if filters.countries:
        clauses.append({"terms": {Reg.COUNTRIES: list(filters.countries)}})
    if filters.severities:
        clauses.append({"terms": {Reg.SEVERITY: list(filters.severities)}})
    if filters.max_age_days:
        clauses.append(
            {"range": {Reg.RECENCY_DATE: {"gte": f"{origin}||-{filters.max_age_days}d"}}}
        )
    return clauses


def build_regulatory_query(
    query: str,
    filters: SearchFilters | None = None,
    *,
    origin: str,
    size: int = 10,
    rerank: bool = False,
) -> dict[str, Any]:
    linear = {
        "linear": {
            "rank_window_size": _REG_WINDOW,
            "filter": _regulatory_filters(filters, origin),
            "retrievers": [
                _decay_leg(
                    {
                        "multi_match": {
                            "query": query,
                            "type": "best_fields",
                            "fields": list(_REG_TEXT_FIELDS),
                        }
                    },
                    weight=_BM25_WEIGHT,
                    profile=REGULATORY_DECAY,
                    date_field=Reg.RECENCY_DATE,
                    origin=origin,
                ),
                _decay_leg(
                    {"semantic": {"field": Reg.BODY_SEMANTIC, "query": query}},
                    weight=_SEMANTIC_WEIGHT,
                    profile=REGULATORY_DECAY,
                    date_field=Reg.RECENCY_DATE,
                    origin=origin,
                ),
            ],
        }
    }
    retriever: dict[str, Any] = linear
    if rerank:
        # body, not body_semantic: the semantic field's chunks are not what the
        # cross-encoder should read, and rerank-on-copy_to is degenerate.
        retriever = {
            "text_similarity_reranker": {
                "retriever": linear,
                "field": Reg.BODY,
                "inference_id": RERANK_INFERENCE_ID,
                "inference_text": query,
                "rank_window_size": _RERANK_WINDOW,
            }
        }
    # No min_score: the linear retriever's output is a weighted sum of minmax'd
    # legs, so its scale is sum(weights) and its minimum is 0 by construction.
    return {
        "size": size,
        "_source": {"excludes": [Reg.RAW, Reg.BODY_SEMANTIC]},
        "retriever": retriever,
        "highlight": {
            "fields": {Reg.BODY: {"fragment_size": 180, "number_of_fragments": 1}},
        },
    }


def build_web_query(
    query: str,
    *,
    origin: str,
    size: int = 8,
    source_tiers: list[str] | None = None,
    scan_id: str | None = None,
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if source_tiers:
        clauses.append({"terms": {Web.SOURCE_TIER: list(source_tiers)}})
    if scan_id:
        clauses.append({"term": {Web.SCAN_IDS: scan_id}})
    return {
        "size": size,
        "_source": {"excludes": [Web.RAW, Web.PAGE_SEMANTIC]},
        "retriever": {
            "linear": {
                "rank_window_size": _WEB_WINDOW,
                "filter": clauses,
                "retrievers": [
                    _decay_leg(
                        {
                            "multi_match": {
                                "query": query,
                                "type": "best_fields",
                                "fields": list(_WEB_TEXT_FIELDS),
                            }
                        },
                        weight=_BM25_WEIGHT,
                        profile=WEB_DECAY,
                        date_field=Web.RECENCY_DATE,
                        origin=origin,
                    ),
                    _decay_leg(
                        {"semantic": {"field": Web.PAGE_SEMANTIC, "query": query}},
                        weight=_SEMANTIC_WEIGHT,
                        profile=WEB_DECAY,
                        date_field=Web.RECENCY_DATE,
                        origin=origin,
                    ),
                ],
            }
        },
        "highlight": {
            "fields": {Web.CONTENT: {"fragment_size": 180, "number_of_fragments": 1}},
        },
    }


def _shape_filter(shape: str | None, mode: str) -> dict[str, Any] | None:
    """Hard shape filter, or None when it would risk a fail-closed zero-result."""
    if not shape or mode == "boost":
        return None
    if mode == "strict":
        return {"term": {Pill.SHAPE: shape}}
    family = vocab.shape_family(shape)
    return {"term": {Pill.SHAPE_FAMILY: family}} if family else None


def _shape_boost(shape: str | None, mode: str) -> dict[str, Any] | None:
    if not shape:
        return None
    if mode == "strict":
        return {"term": {Pill.SHAPE: {"value": shape, "boost": 3.0}}}
    family = vocab.shape_family(shape)
    return {"term": {Pill.SHAPE_FAMILY: {"value": family, "boost": 3.0}}} if family else None


def build_pill_query(
    imprint: ImprintForms | None,
    *,
    shape: str | None = None,
    colors: list[str] | None = None,
    score: int | None = None,
    size_mm: float | None = None,
    rung: int = 1,
    mode: str = "family",
    size: int = _PILL_SIZE,
) -> dict[str, Any]:
    """One rung of the identification ladder.

    imprint_ngrams is in no mapping, so the fuzzy `imprint_text` match is the
    lowest tier rather than the n-gram tier the original design assumed.
    """
    colors = colors or []
    filters: list[dict[str, Any]] = []
    should: list[dict[str, Any]] = []

    if imprint:
        should.extend(
            [
                {"term": {Pill.IMPRINT_NORM: {"value": imprint.norm, "boost": 100}}},
                {"term": {Pill.IMPRINT_SORTED: {"value": imprint.sorted, "boost": 60}}},
                {"terms": {Pill.IMPRINT_PARTS: imprint.parts, "boost": 25}},
                {
                    "match": {
                        Pill.IMPRINT_TEXT: {
                            "query": imprint.text,
                            "fuzziness": "AUTO",
                            "boost": 5,
                        }
                    }
                },
            ]
        )

    if rung == 1:
        clause = _shape_filter(shape, mode)
        if clause:
            filters.append(clause)
        if colors:
            if imprint:
                should.append({"terms": {Pill.COLORS: colors, "boost": 1.5}})
            else:
                filters.append({"terms": {Pill.COLORS: colors}})
    elif rung == 2:
        clause = _shape_boost(shape, mode)
        if clause:
            should.append(clause)
        if colors:
            should.append({"terms": {Pill.COLORS: colors, "boost": 1.5}})

    if rung < 3:
        if score is not None:
            should.append({"term": {Pill.SCORE: {"value": score, "boost": 1.2}}})
        if size_mm is not None:
            should.append(
                {
                    "range": {
                        Pill.SIZE_MM: {
                            "gte": size_mm - _SIZE_TOLERANCE_MM,
                            "lte": size_mm + _SIZE_TOLERANCE_MM,
                            "boost": 1.2,
                        }
                    }
                }
            )

    bool_query: dict[str, Any] = {"minimum_should_match": 1 if imprint else 0}
    if filters:
        bool_query["filter"] = filters
    if should:
        bool_query["should"] = should
    if not should and not filters:
        bool_query["must"] = [{"match_all": {}}]
    return {
        "size": size,
        "_source": {"excludes": [Pill.RAW]},
        "query": {"bool": bool_query},
    }


def build_lot_query(lot: str) -> dict[str, Any]:
    """Exact lot match. Never decayed — an exact lot hit is the answer at any age."""
    return {
        "size": _EXACT_SIZE,
        "_source": {"excludes": [Reg.RAW, Reg.BODY_SEMANTIC]},
        "query": {"constant_score": {"filter": {"term": {Reg.LOT_NUMBERS: lot}}}},
        "sort": [{Reg.SEVERITY_RANK: "desc"}, {Reg.RECENCY_DATE: "desc"}],
    }


def ndc_values(ndc: NdcForms) -> list[str]:
    seen: list[str] = []
    for value in (ndc.ndc11, ndc.ndc9, ndc.product_ndc, ndc.raw):
        if value and value not in seen:
            seen.append(value)
    return seen


def build_ndc_query(ndc: NdcForms) -> dict[str, Any]:
    """Product-line lookup. A hit here is never a lot match — see `recalls_by_ndc`."""
    values = ndc_values(ndc)
    # The recall that names this NDC in its own text must outrank (and survive the
    # size cap over) the many sibling-strength recalls that merely list it.
    should: list[dict[str, Any]] = [
        _constant({"terms": {Reg.NDC_FROM_DESCRIPTION: values}}, _NDC_PRECISE_BOOST)
    ]
    if ndc.ndc11:
        should.append(_constant({"term": {Reg.NDC11: ndc.ndc11}}, 1.0))
    if ndc.ndc9:
        should.append(_constant({"term": {Reg.NDC9: ndc.ndc9}}, 1.0))
    return {
        "size": _EXACT_SIZE,
        "_source": {"excludes": [Reg.RAW, Reg.BODY_SEMANTIC]},
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
        "sort": ["_score", {Reg.SEVERITY_RANK: "desc"}, {Reg.RECENCY_DATE: "desc"}],
    }


def _constant(clause: dict[str, Any], boost: float) -> dict[str, Any]:
    return {"constant_score": {"filter": clause, "boost": boost}}


def _strip_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in source.items()
        if key not in (Reg.RAW, Reg.BODY_SEMANTIC, Web.PAGE_SEMANTIC, _INFERENCE_FIELDS)
    }


def _first_highlight(raw: dict[str, Any]) -> str | None:
    for fragments in (raw.get("highlight") or {}).values():
        if fragments:
            return str(fragments[0])
    return None


def _call_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    kwargs = dict(body)
    source = kwargs.pop("_source", None)
    if source is not None:
        kwargs["source"] = source
    return kwargs


class KnowledgeSearch:
    def __init__(
        self,
        es: AsyncElasticsearch,
        settings: Settings,
        *,
        indices: dict[str, str] | None = None,
    ) -> None:
        self._es = es
        self._settings = settings
        names = indices or {}
        self.regulatory = names.get("regulatory", REGULATORY_INDEX)
        self.pills = names.get("pills", PILLS_INDEX)
        self.ndc = names.get("ndc", NDC_INDEX)
        self.web = names.get("web", WEB_PAGES_INDEX)
        self.scans = names.get("scans", SCANS_INDEX)

    async def _run(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self._es.search(index=index, **_call_kwargs(body))
        except ApiError as exc:
            raise KnowledgeError(f"search on {index} failed: {exc.message}") from exc

    async def _hits(
        self,
        index: str,
        body: dict[str, Any],
        *,
        recency_field: str | None,
        match_kind: str | None = None,
    ) -> list[Hit]:
        response = await self._run(index, body)
        return [self._to_hit(raw, recency_field, match_kind) for raw in response["hits"]["hits"]]

    def _to_hit(
        self,
        raw: dict[str, Any],
        recency_field: str | None,
        match_kind: str | None,
    ) -> Hit:
        source = _strip_source(raw.get("_source") or {})
        age = normalize.age_days(source.get(recency_field)) if recency_field else None
        return Hit(
            index=raw["_index"],
            id=raw["_id"],
            score=float(raw.get("_score") or 0.0),
            source=source,
            match_kind=match_kind,
            age_days=age,
            freshness=normalize.freshness_label(age),
            highlight=_first_highlight(raw),
        )

    async def recalls_by_lot(self, lot: str) -> list[Hit]:
        normalized = normalize.normalize_lot(lot)
        if not normalized:
            return []
        return await self._hits(
            self.regulatory,
            build_lot_query(normalized),
            recency_field=Reg.RECENCY_DATE,
            match_kind="exact_lot",
        )

    async def recalls_covering_all_lots(
        self,
        *,
        ndc9: str | None = None,
        drug_names: list[str] | None = None,
    ) -> list[Hit]:
        """Recalls that name no lots at all, so every lot of the product is in scope."""
        names = [n for n in (normalize.normalize_drug_name(v) for v in drug_names or []) if n]
        should: list[dict[str, Any]] = []
        if ndc9:
            should.append({"term": {Reg.NDC_FROM_DESCRIPTION: ndc9}})
            should.append({"term": {Reg.NDC9: ndc9}})
        if names:
            should.append({"terms": {Reg.DRUG_NAMES: names}})
            should.append({"terms": {Reg.DRUG_NAMES_EXTRACTED: names}})
        if not should:
            return []
        body = {
            "size": _EXACT_SIZE,
            "_source": {"excludes": [Reg.RAW, Reg.BODY_SEMANTIC]},
            "query": {
                "constant_score": {
                    "filter": {
                        "bool": {
                            "filter": [{"term": {Reg.COVERS_ALL_LOTS: True}}],
                            "should": should,
                            "minimum_should_match": 1,
                        }
                    }
                }
            },
            "sort": [{Reg.SEVERITY_RANK: "desc"}, {Reg.RECENCY_DATE: "desc"}],
        }
        return await self._hits(
            self.regulatory,
            body,
            recency_field=Reg.RECENCY_DATE,
            match_kind="all_lots_product",
        )

    async def recalls_by_ndc(self, ndc: NdcForms) -> list[Hit]:
        """Product-line evidence only.

        openFDA's sibling NDC list puts all twelve strengths of a product on every
        recall, so an NDC hit says "a recall exists for this product line", never
        "your lot was recalled". Hits whose ndc_from_description carries the NDC are
        marked apart because that one was written in the recall's own text.
        """
        hits = await self._hits(self.regulatory, build_ndc_query(ndc), recency_field=Reg.RECENCY_DATE)
        wanted = set(ndc_values(ndc))
        for hit in hits:
            described = hit.source.get(Reg.NDC_FROM_DESCRIPTION) or []
            if isinstance(described, str):
                described = [described]
            hit.match_kind = (
                "ndc_in_description" if wanted & set(described) else "product_line_match"
            )
        # Sibling recalls share an event_id; deduping in Python rather than with
        # `collapse` keeps records that carry no event_id at all (WHO, NAFDAC).
        # Precise hits go first so the dedupe keeps them instead of a sibling.
        hits.sort(key=lambda hit: hit.match_kind != "ndc_in_description")
        return _dedupe_by_event(hits)

    async def search_regulatory(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        size: int = 10,
        rerank: bool | None = None,
    ) -> list[Hit]:
        use_rerank = self._settings.research_rerank if rerank is None else rerank
        body = build_regulatory_query(
            query, filters, origin=utc_origin(), size=size, rerank=use_rerank
        )
        return await self._hits(
            self.regulatory,
            body,
            recency_field=Reg.RECENCY_DATE,
            match_kind="hybrid",
        )

    async def search_web(
        self,
        query: str,
        *,
        size: int = 8,
        source_tiers: list[str] | None = None,
        scan_id: str | None = None,
    ) -> list[Hit]:
        body = build_web_query(
            query,
            origin=utc_origin(),
            size=size,
            source_tiers=source_tiers,
            scan_id=scan_id,
        )
        return await self._hits(
            self.web,
            body,
            recency_field=Web.RECENCY_DATE,
            match_kind="web_hybrid",
        )

    async def identify_pill(
        self,
        *,
        imprint: str | None,
        shape: str | None,
        colors: list[str] | None,
        score: int | None = None,
        size_mm: float | None = None,
    ) -> PillMatch:
        """Climb the ladder until an exact imprint form matches, or rungs run out."""
        forms = normalize.normalize_imprint(imprint)
        shape_norm = vocab.normalize_shape(shape)
        color_tokens: list[str] = []
        for raw in colors or []:
            for token in vocab.normalize_colors(raw):
                if token not in color_tokens:
                    color_tokens.append(token)
        color_tokens = color_tokens[: vocab.MAX_COLORS]
        score_norm = vocab.normalize_score(score)
        size_norm = vocab.parse_size_mm(size_mm)
        mode = self._settings.shape_filter_mode

        # Without an imprint there is nothing to be exact about, so only an empty
        # result justifies dropping the shape filter.
        rungs = (1, 2, 3) if forms else (1, 2)
        hits: list[Hit] = []
        used = rungs[0]
        for rung in rungs:
            used = rung
            body = build_pill_query(
                forms,
                shape=shape_norm,
                colors=color_tokens,
                score=score_norm,
                size_mm=size_norm,
                rung=rung,
                mode=mode,
            )
            hits = await self._hits(self.pills, body, recency_field=None)
            for hit in hits:
                hit.match_kind = _pill_match_kind(hit.source, forms)
            if not hits:
                continue
            if forms and not any(hit.match_kind in _PILL_EXACT_KINDS for hit in hits):
                continue
            break

        return PillMatch(
            hits=hits,
            rung=used,
            shape_relaxed=used > 1 and shape_norm is not None,
            filters_applied={
                "imprint_norm": forms.norm if forms else None,
                "shape": shape_norm,
                "shape_family": vocab.shape_family(shape_norm),
                "shape_filter_mode": mode,
                "colors": color_tokens,
                "score": score_norm,
                "size_mm": size_norm,
            },
        )

    async def ndc_directory(self, ndc: NdcForms) -> list[Hit]:
        should: list[dict[str, Any]] = []
        if ndc.ndc11:
            should.append({"term": {Ndc.NDC11: ndc.ndc11}})
        if ndc.ndc9:
            should.append({"term": {Ndc.NDC9: ndc.ndc9}})
        if ndc.product_ndc:
            should.append({"term": {Ndc.PRODUCT_NDC: ndc.product_ndc}})
            should.append({"term": {Ndc.PACKAGE_NDCS: ndc.product_ndc}})
        if not should:
            return []
        body = {
            "size": _PILL_SIZE,
            "_source": {"excludes": [Ndc.RAW]},
            "query": {
                "constant_score": {
                    "filter": {"bool": {"should": should, "minimum_should_match": 1}}
                }
            },
        }
        return await self._hits(
            self.ndc, body, recency_field=None, match_kind="ndc_directory"
        )

    async def prior_scans(
        self,
        *,
        lot: str | None,
        ndc9: str | None,
        exclude_scan_id: str | None = None,
    ) -> dict[str, Any]:
        """Crowd signal. The caller decides whether the total is large enough to mention."""
        should: list[dict[str, Any]] = []
        normalized_lot = normalize.normalize_lot(lot)
        if normalized_lot:
            should.append({"term": {Scan.NORM_LOT: normalized_lot}})
        if ndc9:
            should.append({"term": {Scan.NORM_NDC9: ndc9}})
        if not should:
            return {"total": 0, "by_verdict": {}}
        bool_query: dict[str, Any] = {"should": should, "minimum_should_match": 1}
        if exclude_scan_id:
            bool_query["must_not"] = [{"term": {Scan.SCAN_ID: exclude_scan_id}}]
        body = {
            "size": 0,
            "query": {"bool": bool_query},
            "aggs": {"by_verdict": {"terms": {"field": Scan.RESEARCH_VERDICT, "size": 10}}},
        }
        response = await self._run(self.scans, body)
        buckets = response.get("aggregations", {}).get("by_verdict", {}).get("buckets", [])
        return {
            "total": int(response["hits"]["total"]["value"]),
            "by_verdict": {b["key"]: int(b["doc_count"]) for b in buckets},
        }

    async def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name in (self.regulatory, self.pills, self.ndc, self.web, self.scans):
            try:
                response = await self._es.count(index=name)
            except ApiError:
                out[name] = -1  # index not created yet; -1 keeps the endpoint useful
            else:
                out[name] = int(response["count"])
        return out


def _pill_match_kind(source: dict[str, Any], forms: ImprintForms | None) -> str:
    if not forms:
        return "attribute_match"
    if source.get(Pill.IMPRINT_NORM) == forms.norm:
        return "imprint_exact"
    if source.get(Pill.IMPRINT_SORTED) == forms.sorted:
        return "imprint_sorted"
    return "imprint_partial"


def _dedupe_by_event(hits: list[Hit]) -> list[Hit]:
    seen: set[str] = set()
    out: list[Hit] = []
    for hit in hits:
        event = hit.source.get(Reg.EVENT_ID)
        if event:
            key = str(event)
            if key in seen:
                continue
            seen.add(key)
        out.append(hit)
    return out


def get_knowledge_search(
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> KnowledgeSearch:
    return KnowledgeSearch(es, settings)
