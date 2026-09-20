"""`/graph` — the five reads the Atlas page makes, plus a health probe.

Error mapping follows `knowledge/router.py`: a `KnowledgeError` keeps its own
status code, so a missing sibling module is 501, an unreachable cluster is 503,
and a rejected query is 502. There is deliberately no `/graph/{id}` catch-all:
it would shadow `/graph/universe` and every other fixed path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.graph.models import (
    ExpandResponse,
    GraphResponse,
    NodeDetail,
    SearchGraphResponse,
)
from backend.graph.service import GraphService, get_graph_service
from backend.knowledge.client import KnowledgeError

router = APIRouter(prefix="/graph", tags=["graph"])

Service = Annotated[GraphService, Depends(get_graph_service)]

# `type:key`; the key half may hold anything a regulator id contains.
NODE_ID_PATTERN = r"^[a-z_]+:.+"


def _fail(exc: KnowledgeError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=GraphResponse)
async def personal_graph(
    service: Service,
    device_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    universe: bool = False,
    max_nodes: Annotated[int, Query(ge=50, le=1500)] = 600,
    fresh: bool = False,
    demo: bool = False,
) -> GraphResponse:
    if not demo and not device_id:
        raise HTTPException(
            status_code=422, detail="device_id is required unless demo=1 is set"
        )
    try:
        return await service.personal(
            device_id, universe=universe, max_nodes=max_nodes, fresh=fresh, demo=demo
        )
    except KnowledgeError as exc:
        raise _fail(exc) from exc


@router.get("/universe", response_model=GraphResponse)
async def universe_graph(service: Service, demo: bool = False) -> GraphResponse:
    try:
        return await service.universe(demo=demo)
    except KnowledgeError as exc:
        raise _fail(exc) from exc


@router.get("/expand", response_model=ExpandResponse)
async def expand_graph(
    service: Service,
    id: Annotated[str, Query(min_length=3, max_length=300, pattern=NODE_ID_PATTERN)],
    device_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    scan_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 12,
    demo: bool = False,
) -> ExpandResponse:
    try:
        return await service.expand(
            id, device_id=device_id, scan_id=scan_id, limit=limit, demo=demo
        )
    except KnowledgeError as exc:
        raise _fail(exc) from exc


@router.get("/node", response_model=NodeDetail)
async def node_panel(
    service: Service,
    id: Annotated[str, Query(min_length=3, max_length=300, pattern=NODE_ID_PATTERN)],
    device_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    demo: bool = False,
) -> NodeDetail:
    try:
        return await service.node(id, device_id=device_id, demo=demo)
    except KnowledgeError as exc:
        raise _fail(exc) from exc


@router.get("/search", response_model=SearchGraphResponse)
async def search_graph_endpoint(
    service: Service,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    device_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    size: Annotated[int, Query(ge=1, le=25)] = 10,
    demo: bool = False,
) -> SearchGraphResponse:
    try:
        return await service.search(q, device_id=device_id, size=size, demo=demo)
    except KnowledgeError as exc:
        raise _fail(exc) from exc


@router.get("/health")
async def graph_health(service: Service) -> dict:
    return service.health()
