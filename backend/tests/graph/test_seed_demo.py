"""backend/scripts/seed_demo_scans.py — house fakes only, zero network.

The seeder is not a package (it lives under `scripts/`, not `src/backend/`), so
it is loaded by file path rather than imported normally. Every test replaces
`build_client`/`KnowledgeSearch`/`ScanStore` on the loaded module with fakes;
none of them ever construct a real Elasticsearch client, and the pipeline's
`web`/`agent`/`openai_client`/`rxnav` seams are exercised through the script's
own network-guarded stand-ins.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.config import Settings
from backend.knowledge.fields import SCANS_INDEX, Scan
from backend.knowledge.search import PillMatch
from backend.research.agent_builder import AgentBuilderUnavailable
from backend.scans.normalizer import build_norm

pytestmark = pytest.mark.asyncio


def _load_seed_demo_scans() -> Any:
    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_scans.py"
    spec = importlib.util.spec_from_file_location("seed_demo_scans", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' KW_ONLY/type introspection looks the module up by name in
    # sys.modules, so it must be registered before exec_module runs.
    sys.modules["seed_demo_scans"] = module
    spec.loader.exec_module(module)
    return module


seed_demo_scans = _load_seed_demo_scans()


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "openai_api_key": "test",
        "firecrawl_api_key": "fc-test",
        "elasticsearch_url": "https://example.invalid",
        "elasticsearch_api_key": "key",
    }
    return Settings(**(base | overrides))


class _FakeSearch:
    """Every KnowledgeSearch method the pipeline can reach, all empty."""

    async def recalls_by_lot(self, lot: str, *, ndc9: Any = None, drug_names: Any = None) -> list[Any]:
        return []

    async def recalls_covering_all_lots(self, **kwargs: Any) -> list[Any]:
        return []

    async def recalls_by_ndc(self, ndc: Any) -> list[Any]:
        return []

    async def ndc_directory(self, ndc: Any) -> list[Any]:
        return []

    async def identify_pill(self, **kwargs: Any) -> PillMatch:
        return PillMatch(hits=[], rung=1, shape_relaxed=False, filters_applied={})

    async def search_regulatory(self, query: str, filters: Any = None, **kwargs: Any) -> list[Any]:
        return []

    async def search_web(self, query: str, **kwargs: Any) -> list[Any]:
        return []

    async def prior_scans(self, **kwargs: Any) -> dict[str, Any]:
        return {"total": 0, "by_verdict": {}}


class _FakeStore:
    def __init__(self, existing_docs: list[dict[str, Any]] | None = None) -> None:
        self.existing_docs = existing_docs or []
        self.created: list[Any] = []
        self.applies: list[dict[str, Any]] = []
        self._docs: dict[str, dict[str, Any]] = {}

    async def list(self, *, device_id: str | None = None, limit: int = 20, **kwargs: Any):
        return list(self.existing_docs), None

    async def create(self, payload: Any) -> dict[str, Any]:
        scan_id = f"scan-fake-{len(self.created)}"
        norm = build_norm(
            payload.bottle, payload.imprint, imprint_size_mm=payload.imprint_size_mm,
            now=datetime.now(UTC),
        )
        doc: dict[str, Any] = {
            Scan.SCAN_ID: scan_id,
            Scan.DEVICE_ID: payload.device_id,
            Scan.COUNTRY: payload.country,
            Scan.STATUS: "pending",
            Scan.DEMO: payload.demo,
            Scan.NORM: norm,
            Scan.STAGES: {},
        }
        self.created.append(payload)
        self._docs[scan_id] = doc
        return doc

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        return self._docs.get(scan_id)

    async def apply(self, scan_id: str, **kwargs: Any) -> int:
        self.applies.append({"scan_id": scan_id, **kwargs})
        doc = self._docs.setdefault(scan_id, {})
        if kwargs.get("status"):
            doc[Scan.STATUS] = kwargs["status"]
        if kwargs.get("patch"):
            doc.update(kwargs["patch"])
        if kwargs.get("stage"):
            name, stage = kwargs["stage"]
            doc.setdefault(Scan.STAGES, {})[name] = stage
        return len(self.applies)


class _FakeEs:
    def __init__(self) -> None:
        self.closed = False
        self.counted: list[tuple[str, dict[str, Any]]] = []
        self.deleted_queries: list[tuple[str, dict[str, Any]]] = []

    async def close(self) -> None:
        self.closed = True

    async def count(self, *, index: str, query: dict[str, Any]) -> dict[str, Any]:
        self.counted.append((index, query))
        return {"count": 2}

    async def delete_by_query(
        self, *, index: str, query: dict[str, Any], refresh: bool = True
    ) -> dict[str, Any]:
        self.deleted_queries.append((index, query))
        return {"deleted": 2}


def _patch_es_layer(monkeypatch: pytest.MonkeyPatch, es: Any, store: _FakeStore) -> None:
    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", lambda settings: es)
    monkeypatch.setattr(seed_demo_scans, "KnowledgeSearch", lambda es, settings: _FakeSearch())
    monkeypatch.setattr(seed_demo_scans, "ScanStore", lambda es, settings: store)


# --------------------------------------------------------------------------- tests


async def test_the_seeder_is_a_dry_run_without_yes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _FakeStore()
    _patch_es_layer(monkeypatch, _FakeEs(), store)

    exit_code = await seed_demo_scans.run(["--only", "1,4"])

    assert exit_code == 0
    assert store.created == []
    assert store.applies == []
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Nothing was written" in out
    # The live-corpus section still prints even though nothing is written.
    assert "Scenario 1" in out and "Scenario 4" in out


async def test_the_seeder_never_calls_firecrawl_the_agent_openai_or_rxnav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Any attribute the seeder's author did not explicitly stub must raise,
    # rather than silently falling through to a real network call.
    with pytest.raises(AssertionError):
        seed_demo_scans._StubWeb()._client
    with pytest.raises(AssertionError):
        seed_demo_scans._StubAgent().bootstrap
    with pytest.raises(AssertionError):
        seed_demo_scans._StubOpenAI().images
    with pytest.raises(AssertionError):
        seed_demo_scans._StubRxNav().some_other_method

    # The explicitly-allowed methods behave exactly as the design calls for.
    outcome = await seed_demo_scans._StubWeb().search_and_index(None)
    assert outcome.page_ids == [] and outcome.credits == 0
    assert await seed_demo_scans._StubWeb().pages_for_scan("scan-1") == []
    assert await seed_demo_scans._StubWeb().pages_by_id(["p1"]) == []
    with pytest.raises(AgentBuilderUnavailable):
        await seed_demo_scans._StubAgent().converse("prompt")
    response = await seed_demo_scans._StubOpenAI().responses.parse()
    assert response.output_parsed is None
    assert await seed_demo_scans._StubRxNav().approximate_term("aspirin") is None
    assert await seed_demo_scans._StubRxNav().ndc_status("12345678901") is None

    # And a full --yes run through the real pipeline never trips the guard.
    store = _FakeStore()
    _patch_es_layer(monkeypatch, _FakeEs(), store)
    exit_code = await seed_demo_scans.run(["--only", "5", "--yes"])
    assert exit_code == 0
    assert len(store.created) == 1
    (scan_id,) = store._docs.keys()
    assert store._docs[scan_id][Scan.STATUS] == "complete"


async def test_the_seeder_skips_a_scenario_that_already_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = seed_demo_scans._scenarios()[0]
    norm = seed_demo_scans._norm_for(scenario)
    store = _FakeStore(existing_docs=[{Scan.NORM: norm}])
    _patch_es_layer(monkeypatch, _FakeEs(), store)

    exit_code = await seed_demo_scans.run(["--only", "1", "--yes"])

    assert exit_code == 0
    assert store.created == []
    out = capsys.readouterr().out
    assert "SKIP" in out

    # --force overrides the skip.
    exit_code = await seed_demo_scans.run(["--only", "1", "--yes", "--force"])
    assert exit_code == 0
    assert len(store.created) == 1


async def test_purge_only_ever_targets_the_demo_device_with_demo_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    es = _FakeEs()
    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", lambda settings: es)

    exit_code = await seed_demo_scans.run(["--purge", "--yes"])

    assert exit_code == 0
    expected_query = {
        "bool": {
            "filter": [
                {"term": {Scan.DEVICE_ID: seed_demo_scans.DEVICE_ID}},
                {"term": {Scan.DEMO: True}},
            ]
        }
    }
    assert es.counted == [(SCANS_INDEX, expected_query)]
    assert es.deleted_queries == [(SCANS_INDEX, expected_query)]
    assert es.closed is True


async def test_purge_without_yes_never_touches_elasticsearch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("build_client must not be called without --yes")

    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", _forbidden)

    exit_code = await seed_demo_scans.run(["--purge"])

    assert exit_code == 2
