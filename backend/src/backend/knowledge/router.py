"""Debug and demo surface over the knowledge base.

These endpoints exist so the retrieval layer can be driven and shown without the
scan pipeline: `?debug=true` returns the exact query body that was sent, which is
what makes the pre-filter and the decay script visible on stage.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError
from backend.knowledge.search import (
    MAX_REGULATORY_SIZE,
    MAX_RERANK_SIZE,
    MAX_WEB_SIZE,
    KnowledgeSearch,
    SearchFilters,
    build_lot_query,
    build_ndc_query,
    build_pill_query,
    build_regulatory_query,
    build_web_query,
    get_knowledge_search,
    utc_origin,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

Search = Annotated[KnowledgeSearch, Depends(get_knowledge_search)]


def _fail(exc: KnowledgeError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/search")
async def search_knowledge(
    ks: Search,
    q: str,
    index: Literal["regulatory", "web"] = "regulatory",
    drug: Annotated[list[str] | None, Query()] = None,
    dosage_form: str | None = None,
    doc_type: Annotated[list[str] | None, Query()] = None,
    source_org: Annotated[list[str] | None, Query()] = None,
    country: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
    max_age_days: int | None = None,
    source_tier: Annotated[list[str] | None, Query()] = None,
    scan_id: str | None = None,
    size: Annotated[int, Query(ge=1, le=MAX_REGULATORY_SIZE)] = 10,
    rerank: bool | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    filters = SearchFilters(
        drug_names=drug or [],
        dosage_form=dosage_form,
        doc_types=doc_type or [],
        source_orgs=source_org or [],
        countries=country or [],
        severities=severity or [],
        max_age_days=max_age_days,
    )
    use_rerank = ks.rerank_enabled(rerank)
    origin = utc_origin()
    applied: dict[str, Any]
    if index == "web":
        # The web index carries none of these, and silently ignoring them would
        # return an unfiltered result set under a body claiming otherwise.
        if not filters.is_empty() or rerank is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "drug/dosage_form/doc_type/source_org/country/severity/max_age_days"
                    " and rerank are regulatory-only; use source_tier and scan_id with index=web"
                ),
            )
        if size > MAX_WEB_SIZE:
            raise HTTPException(
                status_code=422, detail=f"size must be <= {MAX_WEB_SIZE} for index=web"
            )
        applied = {"source_tiers": list(source_tier or []), "scan_id": scan_id}
    else:
        if source_tier or scan_id:
            raise HTTPException(
                status_code=422, detail="source_tier and scan_id apply to index=web only"
            )
        if use_rerank and size > MAX_RERANK_SIZE:
            raise HTTPException(
                status_code=422, detail=f"size must be <= {MAX_RERANK_SIZE} when rerank is on"
            )
        applied = filters.to_dict()
    try:
        if index == "web":
            hits = await ks.search_web(
                q, size=size, source_tiers=source_tier or None, scan_id=scan_id
            )
            body = build_web_query(
                q,
                origin=origin,
                size=size,
                source_tiers=source_tier or None,
                scan_id=scan_id,
            )
        else:
            hits = await ks.search_regulatory(q, filters, size=size, rerank=use_rerank)
            body = build_regulatory_query(
                q, filters, origin=origin, size=size, rerank=use_rerank
            )
    except KnowledgeError as exc:
        raise _fail(exc) from exc
    out: dict[str, Any] = {
        "query": q,
        "index": index,
        "origin": origin,
        # Only the filters that were actually applied to this search.
        "filters": applied,
        "count": len(hits),
        "hits": [hit.to_dict() for hit in hits],
    }
    if debug:
        out["body"] = body
    return out


@router.get("/lot/{lot}")
async def lot_lookup(ks: Search, lot: str, debug: bool = False) -> dict[str, Any]:
    normalized = normalize.normalize_lot(lot)
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{lot!r} is not a usable lot number")
    try:
        exact = await ks.recalls_by_lot(normalized)
    except KnowledgeError as exc:
        raise _fail(exc) from exc
    out: dict[str, Any] = {
        "lot": normalized,
        "count": len(exact),
        "hits": [hit.to_dict() for hit in exact],
    }
    if debug:
        out["body"] = build_lot_query(normalized)
    return out


@router.get("/ndc/{ndc}")
async def ndc_lookup(ks: Search, ndc: str, debug: bool = False) -> dict[str, Any]:
    forms = normalize.normalize_ndc(ndc)
    if forms is None:
        raise HTTPException(status_code=422, detail=f"{ndc!r} is not a usable NDC")
    try:
        recalls = await ks.recalls_by_ndc(forms)
        directory = await ks.ndc_directory(forms)
    except KnowledgeError as exc:
        raise _fail(exc) from exc
    out: dict[str, Any] = {
        "ndc": {
            "raw": forms.raw,
            "product_ndc": forms.product_ndc,
            "ndc9": forms.ndc9,
            "ndc11": forms.ndc11,
        },
        # Never a lot match: these recalls name the product line, not this bottle.
        "recalls": [hit.to_dict() for hit in recalls],
        "directory": [hit.to_dict() for hit in directory],
    }
    if debug:
        out["body"] = build_ndc_query(forms)
    return out


@router.get("/pill")
async def pill_lookup(
    ks: Search,
    imprint: str | None = None,
    shape: str | None = None,
    color: Annotated[list[str] | None, Query()] = None,
    score: int | None = None,
    size_mm: float | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    try:
        match = await ks.identify_pill(
            imprint=imprint,
            shape=shape,
            colors=color or [],
            score=score,
            size_mm=size_mm,
        )
    except KnowledgeError as exc:
        raise _fail(exc) from exc
    out = match.to_dict()
    out["count"] = len(match.hits)
    if debug:
        applied = match.filters_applied
        out["body"] = build_pill_query(
            normalize.normalize_imprint(imprint),
            shape=applied["shape"],
            colors=applied["colors"],
            score=applied["score"],
            size_mm=applied["size_mm"],
            rung=match.rung,
            mode=applied["shape_filter_mode"],
        )
    return out


@router.get("/stats")
async def index_stats(ks: Search) -> dict[str, Any]:
    try:
        counts = await ks.counts()
    except KnowledgeError as exc:
        raise _fail(exc) from exc
    return {"counts": counts}
