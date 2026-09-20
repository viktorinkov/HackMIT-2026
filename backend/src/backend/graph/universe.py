"""`GET /graph/universe`'s data source: the committed corpus-backdrop snapshot.

`scripts/build_universe_snapshot.py` builds `fixtures/universe.json` offline
from the local seed cache, with no Elasticsearch involved
(design-data-api.md §4, tier T4 — "build T4 first, it doubles as the demo
backdrop"). This module only ever reads that committed file. Two rules:

* **Read once, cache in memory.** The snapshot only changes when someone
  re-runs the build script and redeploys, so re-parsing ~100 nodes on every
  request would be pure waste.
* **A missing or unreadable fixture is never fatal.** The universe backdrop
  (and `?demo=1`, which can render alongside it) must keep working even on a
  checkout where the fixture was never built; `load_universe()` returns an
  empty, schema-valid `GraphResponse` instead of raising.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.graph.models import GraphMeta, GraphResponse

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "universe.json"

_cached: GraphResponse | None = None


def _empty(reason: str | None = None) -> GraphResponse:
    return GraphResponse(
        nodes=[],
        links=[],
        meta=GraphMeta(
            scans=0,
            source="snapshot",
            demo=False,
            truncated=False,
            notice=reason or "The universe snapshot has not been built yet.",
        ),
    )


def load_universe(*, path: Path | None = None, force_reload: bool = False) -> GraphResponse:
    """The committed snapshot, parsed once and cached for the process lifetime.

    `path` and `force_reload` exist for tests; production code always calls
    this with no arguments, and — after the first successful load — gets the
    same cached object back on every call. A `path` override bypasses the
    module-level cache entirely, so a test can load a fixture without
    disturbing the real one.
    """
    global _cached
    if path is None and _cached is not None and not force_reload:
        return _cached

    target = path or FIXTURE_PATH
    try:
        raw = target.read_text(encoding="utf-8")
        response = GraphResponse.model_validate(json.loads(raw))
    except FileNotFoundError:
        response = _empty(f"No universe snapshot at {target}.")
    except (OSError, ValueError) as exc:
        # ValueError also catches json.JSONDecodeError and pydantic's
        # ValidationError, both of which subclass it.
        response = _empty(f"The universe snapshot at {target} could not be read: {exc}")

    if path is None:
        _cached = response
    return response


def reset_cache() -> None:
    """Test hook: forget the cached snapshot so the next call re-reads it."""
    global _cached
    _cached = None
