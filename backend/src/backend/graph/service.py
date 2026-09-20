"""The one dependency the graph router resolves, and everything behind it.

Two constraints shape this module:

- **`?demo=1` must work with no `.env` and Elasticsearch down.** `backend.config.Settings`
  raises without `OPENAI_API_KEY`, and the house dependency style
  (`Annotated[X, Depends(get_es)]`) resolves *before* the handler runs, so it
  cannot be skipped per request. `get_graph_service()` therefore takes no
  `Depends` at all and builds the Elasticsearch-backed half lazily inside a
  `try`. Tests override it through `app.dependency_overrides`.
- **A live session never silently becomes a demo.** The fixtures are served only
  when the caller asked for `demo=1`. Without it, a broken Elasticsearch is a
  502/503, never a fabricated graph.

The heavier read paths (`universe`, `expand`, `detail`, `search`) belong to other
streams. They are imported inside the methods so that a missing module is a clean
501 rather than an import error that takes the whole app down.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from elasticsearch import ApiError, AsyncElasticsearch, TransportError

from backend.graph.builder import graph_from_scans
from backend.graph.cache import TTLCache
from backend.graph.models import (
    ExpandResponse,
    GraphMeta,
    GraphResponse,
    NodeDetail,
    SearchGraphResponse,
)
from backend.graph.settings import GraphSettings, get_graph_settings
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import SCANS_INDEX, Scan

FIXTURES = Path(__file__).parent / "fixtures"

# The allow-list is the privacy boundary: `bottle`, `imprint`, `photos`, `raw`,
# `stages` and `hardware.spectrum` cannot reach a node because they are never
# fetched, whatever `SCANS_STORE_SENSITIVE` is set to.
SCAN_SOURCE_INCLUDES: tuple[str, ...] = (
    Scan.SCAN_ID,
    Scan.DEVICE_ID,
    Scan.COUNTRY,
    Scan.STATUS,
    Scan.DEMO,
    Scan.CREATED_AT,
    Scan.UPDATED_AT,
    Scan.NORM,
    Scan.RESEARCH,
    "hardware.status",
    "hardware.degraded",
    "hardware.model",
    "hardware.limitations",
    "hardware.confidence",
    "hardware.pill_type",
    "evidence.web_page_ids",
    "evidence.evidence_pack",
)

NOTICE = (
    "Peel checks published records only. It cannot tell you what is inside a tablet — "
    "if anything looks or feels wrong, ask a pharmacist."
)
OFFLINE_MESSAGE = "Elasticsearch is not configured; add ?demo=1 for the offline graph"


@lru_cache(maxsize=8)
def load_fixture(name: str) -> Any:
    path = FIXTURES / name
    if not path.is_file():
        raise KnowledgeError(f"demo fixture {name} is not installed", status_code=503)
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class GraphContext:
    """What the read paths are allowed to touch. Any field may be `None`."""

    es: AsyncElasticsearch | None = None
    search: Any | None = None  # KnowledgeSearch, typed loosely to keep imports lazy
    scans: Any | None = None  # ScanStore
    settings: GraphSettings = field(default_factory=get_graph_settings)

    @property
    def online(self) -> bool:
        return self.es is not None

    def require_es(self) -> AsyncElasticsearch:
        if self.es is None:
            raise KnowledgeError(OFFLINE_MESSAGE, status_code=503)
        return self.es

    def require_search(self) -> Any:
        """The read paths dereference `ctx.search` directly, so check it here."""
        if self.es is None or self.search is None:
            raise KnowledgeError(OFFLINE_MESSAGE, status_code=503)
        return self.search

    async def scan_docs(self, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """This device's scans, newest first, through the `_source` allow-list."""
        es = self.require_es()
        size = max(1, min(int(limit), 100))
        try:
            response = await es.search(
                index=SCANS_INDEX,
                query={"bool": {"filter": [{"term": {Scan.DEVICE_ID: device_id}}]}},
                sort=[{Scan.CREATED_AT: "desc"}, {Scan.SCAN_ID: "asc"}],
                size=size,
                source={"includes": list(SCAN_SOURCE_INCLUDES)},
                track_total_hits=False,
            )
        except ApiError as exc:
            raise KnowledgeError(f"could not read scans: {exc}", status_code=502) from exc
        except TransportError as exc:
            raise KnowledgeError(f"Elasticsearch is unreachable: {exc}", status_code=503) from exc
        return [dict(hit["_source"]) for hit in response["hits"]["hits"]]

    async def personal(self, device_id: str) -> GraphResponse:
        """This device's own graph, for the read paths that relate a result back to it
        (search highlights, node notes). One scans query; the service caches its own copy."""
        docs = await self.scan_docs(device_id, self.settings.scan_limit)
        nodes, links, truncated = graph_from_scans(
            docs, max_nodes=self.settings.max_nodes, max_links=self.settings.max_links
        )
        return GraphResponse(
            nodes=nodes,
            links=links,
            meta=GraphMeta(
                device_id=device_id,
                scans=len(docs),
                source="live",
                demo=any(node.demo for node in nodes),
                truncated=truncated,
            ),
        )


class GraphService:
    def __init__(self, context: GraphContext) -> None:
        self.context = context
        self.settings = context.settings
        self.personal_cache = TTLCache()
        self.expand_cache = TTLCache()
        self.universe_cache = TTLCache()

    # ----------------------------------------------------------------- personal

    async def personal(
        self,
        device_id: str | None,
        *,
        universe: bool = False,
        max_nodes: int | None = None,
        fresh: bool = False,
        demo: bool = False,
    ) -> GraphResponse:
        if demo:
            return self.demo_personal(universe=universe)
        if not device_id:
            raise KnowledgeError("device_id is required", status_code=422)
        cap = int(max_nodes or self.settings.max_nodes)
        key = f"personal:{device_id}:{cap}:{int(universe)}"

        async def build() -> GraphResponse:
            docs = await self.context.scan_docs(device_id, self.settings.scan_limit)
            nodes, links, truncated = graph_from_scans(
                docs, max_nodes=cap, max_links=self.settings.max_links
            )
            counts: dict[str, int] = {}
            for node in nodes:
                counts[node.type] = counts.get(node.type, 0) + 1
            return GraphResponse(
                nodes=nodes,
                links=links,
                meta=GraphMeta(
                    device_id=device_id,
                    scans=len(docs),
                    generated_at=_now(),
                    source="live",
                    demo=any(node.demo for node in nodes),
                    truncated=truncated,
                    notice=NOTICE,
                    counts=counts,
                ),
            )

        graph = await self.personal_cache.get_or_set(
            key, self.settings.personal_ttl_s, build, fresh=fresh
        )
        if universe:
            # The backdrop is decoration. A missing snapshot must not take the
            # person's own graph down with it.
            try:
                graph = _merge_backdrop(graph, await self.universe())
            except KnowledgeError:
                pass
        return graph

    def demo_personal(self, *, universe: bool = False) -> GraphResponse:
        graph = GraphResponse.model_validate(load_fixture("demo_graph.json"))
        if universe:
            try:
                graph = _merge_backdrop(graph, _load_universe_module()())
            except KnowledgeError:
                pass
        return graph

    # ----------------------------------------------------------------- universe

    async def universe(self, *, demo: bool = False) -> GraphResponse:
        try:
            loader = _load_universe_module()
        except KnowledgeError:
            if not demo:
                raise
            # The Universe toggle degrades to "nothing to show" during a demo
            # rather than taking the page down.
            return GraphResponse(
                nodes=[],
                links=[],
                meta=GraphMeta(
                    generated_at=_now(), source="snapshot", demo=True, notice=NOTICE
                ),
            )

        async def build() -> GraphResponse:
            return loader()

        return await self.universe_cache.get_or_set(
            "universe", self.settings.universe_ttl_s, build
        )

    # ----------------------------------------------------------------- expand

    async def expand(
        self,
        node_id: str,
        *,
        device_id: str | None = None,
        scan_id: str | None = None,
        limit: int = 12,
        demo: bool = False,
    ) -> ExpandResponse:
        if demo:
            return self.demo_expand(node_id)
        self.context.require_search()
        expand_node = _lazy("backend.graph.expand", "expand_node")

        async def build() -> ExpandResponse:
            return await expand_node(
                self.context, node_id, device_id=device_id, scan_id=scan_id, limit=limit
            )

        key = f"expand:{node_id}:{device_id or '-'}:{scan_id or '-'}:{limit}"
        return await self.expand_cache.get_or_set(key, self.settings.expand_ttl_s, build)

    def demo_expand(self, node_id: str) -> ExpandResponse:
        canned = load_fixture("demo_expansions.json").get(node_id)
        if canned is None:
            # An un-canned node is an empty neighbourhood, not an error: the page
            # must stay usable when the venue network is gone.
            return ExpandResponse(
                anchor=node_id,
                nodes=[],
                links=[],
                meta=GraphMeta(
                    device_id=self.settings.demo_device_id,
                    generated_at=_now(),
                    source="demo",
                    demo=True,
                    notice=NOTICE,
                ),
            )
        return ExpandResponse.model_validate(canned)

    # ----------------------------------------------------------------- detail

    async def node(
        self, node_id: str, *, device_id: str | None = None, demo: bool = False
    ) -> NodeDetail:
        if demo:
            return self.demo_node(node_id)
        self.context.require_search()
        node_detail = _lazy("backend.graph.detail", "node_detail")
        return await node_detail(self.context, node_id, device_id=device_id)

    def demo_node(self, node_id: str) -> NodeDetail:
        canned = load_fixture("demo_nodes.json").get(node_id)
        if canned is None:
            raise KnowledgeError(f"no demo detail for {node_id}", status_code=404)
        return NodeDetail.model_validate(canned)

    # ----------------------------------------------------------------- search

    async def search(
        self,
        query: str,
        *,
        device_id: str | None = None,
        size: int = 10,
        demo: bool = False,
    ) -> SearchGraphResponse:
        if demo:
            return self.demo_search(query)
        self.context.require_search()
        search_graph = _lazy("backend.graph.search", "search_graph")
        return await search_graph(self.context, query, device_id=device_id, size=size)

    def demo_search(self, query: str) -> SearchGraphResponse:
        canned = SearchGraphResponse.model_validate(load_fixture("demo_search.json"))
        return canned.model_copy(update={"query": query})

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, Any]:
        modules = {}
        for name, attr in (
            ("universe", "load_universe"),
            ("expand", "expand_node"),
            ("detail", "node_detail"),
            ("search", "search_graph"),
        ):
            try:
                _lazy(f"backend.graph.{name}", attr)
            except KnowledgeError:
                modules[name] = False
            else:
                modules[name] = True
        return {
            "online": self.context.online,
            "demo_device_id": self.settings.demo_device_id,
            "fixtures": sorted(p.name for p in FIXTURES.glob("*.json")),
            "modules": modules,
            "max_nodes": self.settings.max_nodes,
        }


def _lazy(module: str, attribute: str) -> Any:
    """Import a sibling read path on use; a missing one is 501, not a crash."""
    try:
        loaded = __import__(module, fromlist=[attribute])
        return getattr(loaded, attribute)
    except (ImportError, AttributeError) as exc:
        raise KnowledgeError(
            f"{module}.{attribute} is not available in this build", status_code=501
        ) from exc


def _load_universe_module() -> Any:
    return _lazy("backend.graph.universe", "load_universe")


def _merge_backdrop(graph: GraphResponse, backdrop: GraphResponse) -> GraphResponse:
    """The corpus behind the personal graph; personal nodes always win a collision."""
    if not backdrop.nodes:
        return graph
    known = {node.id for node in graph.nodes}
    nodes = list(graph.nodes)
    for node in backdrop.nodes:
        if node.id not in known:
            known.add(node.id)
            nodes.append(node.model_copy(update={"backdrop": True, "personal": False}))
    seen = {link.id for link in graph.links}
    links = list(graph.links)
    for link in backdrop.links:
        if link.id not in seen and link.source in known and link.target in known:
            seen.add(link.id)
            links.append(link)
    meta = graph.meta.model_copy(update={"counts": dict(graph.meta.counts)})
    return GraphResponse(nodes=nodes, links=links, meta=meta)


def _build_context() -> GraphContext:
    """Best effort. Anything that raises leaves the demo half fully usable."""
    settings = get_graph_settings()
    try:
        from backend.config import get_settings
        from backend.knowledge.client import get_es
        from backend.knowledge.search import KnowledgeSearch
        from backend.scans.store import ScanStore

        app_settings = get_settings()
        es = get_es(app_settings)
        return GraphContext(
            es=es,
            search=KnowledgeSearch(es, app_settings),
            scans=ScanStore(es, app_settings),
            settings=settings,
        )
    except Exception:  # noqa: BLE001 - no .env, no cluster: demo must still serve
        return GraphContext(settings=settings)


_service: GraphService | None = None


def get_graph_service() -> GraphService:
    """The only FastAPI dependency in this package. Takes no `Depends`."""
    global _service
    if _service is None:
        _service = GraphService(_build_context())
    return _service


def reset_graph_service() -> None:
    """Test and lifespan hook; the module-level singleton is not a cache of data."""
    global _service
    _service = None
    load_fixture.cache_clear()
