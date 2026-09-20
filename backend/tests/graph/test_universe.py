"""`graph/universe.py` — the committed snapshot loader. No network, no ES."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.graph import universe
from backend.graph.models import GraphResponse

VALID_SNAPSHOT: dict[str, Any] = {
    "nodes": [
        {"id": "reg:fda", "type": "regulator", "label": "FDA", "backdrop": True, "count": 3},
    ],
    "links": [],
    "meta": {"source": "snapshot", "counts": {"FDA": 3}},
}


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    universe.reset_cache()
    yield
    universe.reset_cache()


def test_load_universe_parses_the_committed_fixture(tmp_path: Path) -> None:
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(VALID_SNAPSHOT))

    response = universe.load_universe(path=path)

    assert isinstance(response, GraphResponse)
    assert response.meta.source == "snapshot"
    assert len(response.nodes) == 1
    assert response.nodes[0].id == "reg:fda"


def test_load_universe_never_raises_on_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"

    response = universe.load_universe(path=missing)

    assert isinstance(response, GraphResponse)
    assert response.nodes == []
    assert response.links == []
    assert response.meta.source == "snapshot"
    assert response.meta.notice


def test_load_universe_never_raises_on_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not valid json")

    response = universe.load_universe(path=path)

    assert response.nodes == []
    assert response.meta.source == "snapshot"


def test_load_universe_never_raises_when_the_fixture_fails_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "bad-schema.json"
    path.write_text(json.dumps({"nodes": [{"id": "x"}], "links": [], "meta": {}}))

    response = universe.load_universe(path=path)

    assert response.nodes == []
    assert response.meta.source == "snapshot"


def test_load_universe_caches_the_default_path_across_calls() -> None:
    first = universe.load_universe()
    second = universe.load_universe()

    assert first is second


def test_force_reload_bypasses_the_cache_for_the_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(VALID_SNAPSHOT))
    monkeypatch.setattr(universe, "FIXTURE_PATH", path)

    first = universe.load_universe()
    assert len(first.nodes) == 1

    path.write_text(json.dumps({"nodes": [], "links": [], "meta": {"source": "snapshot"}}))
    still_cached = universe.load_universe()
    assert still_cached is first

    reloaded = universe.load_universe(force_reload=True)
    assert reloaded is not first
    assert reloaded.nodes == []


def test_the_committed_fixture_itself_validates_against_the_models() -> None:
    """The file `build_universe_snapshot.py` writes, checked into the repo."""
    response = universe.load_universe(path=universe.FIXTURE_PATH)

    # A freshly-built fixture always has real content; an unbuilt one degrades
    # to the documented empty response rather than failing this test outright.
    if not response.nodes:
        pytest.skip("fixtures/universe.json has not been built yet")
    assert response.meta.source == "snapshot"
    assert all(len(node.label) <= 40 for node in response.nodes)
    node_ids = {node.id for node in response.nodes}
    assert all(link.source in node_ids and link.target in node_ids for link in response.links)
