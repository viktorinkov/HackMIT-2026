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
from backend.knowledge.fields import REPORTS_INDEX, SCANS_INDEX, Scan
from backend.knowledge.fields import Report as ReportFields
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
    """Two matching documents per index, and a delete that really removes them.

    `delete_response` overrides what `delete_by_query` reports for one index,
    which is how a partial delete (`failures` / `version_conflicts` alongside a
    `deleted` count) is spelled.
    """

    def __init__(
        self,
        scan_ids: list[str] | None = None,
        *,
        delete_response: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.closed = False
        self.scan_ids = scan_ids if scan_ids is not None else []
        self.counted: list[tuple[str, dict[str, Any]]] = []
        self.deleted_queries: list[tuple[str, dict[str, Any]]] = []
        self.searched: list[tuple[str, dict[str, Any]]] = []
        self.remaining: dict[str, int] = {REPORTS_INDEX: 2, SCANS_INDEX: 2}
        self.delete_response = delete_response or {}

    async def close(self) -> None:
        self.closed = True

    async def search(self, *, index: str, **kwargs: Any) -> dict[str, Any]:
        self.searched.append((index, kwargs))
        hits = [{"_id": sid, "_source": {Scan.SCAN_ID: sid}} for sid in self.scan_ids]
        return {"hits": {"hits": hits}}

    async def count(self, *, index: str, query: dict[str, Any]) -> dict[str, Any]:
        self.counted.append((index, query))
        return {"count": self.remaining.get(index, 0)}

    async def delete_by_query(
        self, *, index: str, query: dict[str, Any], refresh: bool = True
    ) -> dict[str, Any]:
        self.deleted_queries.append((index, query))
        response = dict(self.delete_response.get(index) or {})
        deleted = int(response.setdefault("deleted", self.remaining.get(index, 0)))
        self.remaining[index] = max(0, self.remaining.get(index, 0) - deleted)
        return response


class _FakeReportStore:
    """Stands in for `reports.store.ElasticReportStore`; nothing leaves memory."""

    def __init__(self, existing: dict[str, list[Any]] | None = None) -> None:
        self.existing = existing or {}
        self.added: list[Any] = []

    async def list_for_scan(self, scan_id: str) -> list[Any]:
        return list(self.existing.get(scan_id, []))

    async def add(self, report: Any) -> Any:
        self.added.append(report)
        self.existing.setdefault(report.scan_id, []).append(report)
        return report


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


def _demo_scan_query() -> dict[str, Any]:
    return {
        "bool": {
            "filter": [
                {"term": {Scan.DEVICE_ID: seed_demo_scans.DEVICE_ID}},
                {"term": {Scan.DEMO: True}},
            ]
        }
    }


async def test_purge_only_ever_targets_the_demo_device_with_demo_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    es = _FakeEs()
    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", lambda settings: es)

    exit_code = await seed_demo_scans.run(["--purge", "--yes"])

    assert exit_code == 0
    assert es.counted == [(SCANS_INDEX, _demo_scan_query())]
    assert es.deleted_queries == [(SCANS_INDEX, _demo_scan_query())]
    assert es.closed is True


async def test_purge_deletes_the_demo_reports_before_the_scans_they_hang_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    es = _FakeEs(scan_ids=["scan-demo-1", "scan-demo-2"])
    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", lambda settings: es)

    exit_code = await seed_demo_scans.run(["--purge", "--yes"])

    assert exit_code == 0
    reports_query = {
        "bool": {"filter": [{"terms": {ReportFields.SCAN_ID: ["scan-demo-1", "scan-demo-2"]}}]}
    }
    # Reports first: after the scans are gone nothing selects the reports. The
    # second reports count is the check that they really went.
    assert es.counted == [
        (REPORTS_INDEX, reports_query),
        (REPORTS_INDEX, reports_query),
        (SCANS_INDEX, _demo_scan_query()),
    ]
    assert es.deleted_queries == [
        (REPORTS_INDEX, reports_query),
        (SCANS_INDEX, _demo_scan_query()),
    ]
    # And the read-only count is printed before either delete runs.
    out = capsys.readouterr().out
    assert "peel-reports: 2 document(s)" in out


async def test_the_purge_pages_through_every_demo_scan_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scan id this listing misses is a report that outlives its own scan."""

    class _PagingEs(_FakeEs):
        async def search(self, *, index: str, **kwargs: Any) -> dict[str, Any]:
            self.searched.append((index, kwargs))
            after = (kwargs.get("search_after") or [None])[0]
            remaining = [sid for sid in self.scan_ids if after is None or sid > after]
            page = remaining[: kwargs["size"]]
            return {
                "hits": {
                    "hits": [
                        {"_id": sid, "_source": {Scan.SCAN_ID: sid}, "sort": [sid]}
                        for sid in page
                    ]
                }
            }

    monkeypatch.setattr(seed_demo_scans, "MAX_DEMO_SCANS", 2)
    es = _PagingEs(scan_ids=["scan-a", "scan-b", "scan-c", "scan-d", "scan-e"])
    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", lambda settings: es)

    exit_code = await seed_demo_scans.run(["--purge", "--yes"])

    assert exit_code == 0
    assert len(es.searched) == 3  # 2 + 2 + 1
    reports_delete = next(q for index, q in es.deleted_queries if index == REPORTS_INDEX)
    assert reports_delete["bool"]["filter"][0]["terms"][ReportFields.SCAN_ID] == [
        "scan-a", "scan-b", "scan-c", "scan-d", "scan-e",
    ]


async def test_a_partial_report_delete_stops_the_purge_before_the_scans(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A demo report that outlives its demo scan stops looking like demo data.

    `delete_by_query` reports shard failures and version conflicts alongside a
    `deleted` count, so the count alone cannot tell a full delete from a partial
    one. The scans stay until the reports are really gone — they are the only
    handle left for selecting those reports.
    """
    es = _FakeEs(
        scan_ids=["scan-demo-1", "scan-demo-2"],
        delete_response={
            REPORTS_INDEX: {
                "deleted": 1,
                "version_conflicts": 1,
                "failures": [{"cause": {"type": "version_conflict_engine_exception"}}],
            }
        },
    )
    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", lambda settings: es)

    exit_code = await seed_demo_scans.run(["--purge", "--yes"])

    assert exit_code == 1
    assert [index for index, _query in es.deleted_queries] == [REPORTS_INDEX]
    out = capsys.readouterr().out
    assert "1 version conflict(s)" in out
    assert "1 report(s) still match" in out
    assert es.closed is True


async def test_the_reports_seeder_is_a_dry_run_without_yes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = seed_demo_scans._scenarios()[0]
    doc = {Scan.SCAN_ID: "scan-demo-1", Scan.NORM: seed_demo_scans._norm_for(scenario)}
    store = _FakeStore(existing_docs=[doc])
    reports = _FakeReportStore()
    _patch_es_layer(monkeypatch, _FakeEs(), store)
    monkeypatch.setattr(seed_demo_scans, "ElasticReportStore", lambda es: reports)

    exit_code = await seed_demo_scans.run(["--reports"])

    assert exit_code == 0
    assert reports.added == []
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Nothing was written" in out
    assert "would FILE against scan_id=scan-demo-1" in out
    # A scenario whose scan has not been seeded is named, never invented.
    assert "that demo scan does not exist yet" in out


async def test_the_reports_seeder_files_one_report_per_scan_and_skips_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenarios = {s.number: s for s in seed_demo_scans._scenarios()}
    docs = [
        {Scan.SCAN_ID: f"scan-demo-{number}",
         Scan.NORM: seed_demo_scans._norm_for(scenarios[number])}
        for number in (1, 2, 4)
    ]
    store = _FakeStore(existing_docs=docs)
    reports = _FakeReportStore()
    _patch_es_layer(monkeypatch, _FakeEs(), store)
    monkeypatch.setattr(seed_demo_scans, "ElasticReportStore", lambda es: reports)

    assert await seed_demo_scans.run(["--reports", "--yes"]) == 0

    assert [report.scan_id for report in reports.added] == [
        "scan-demo-1", "scan-demo-2", "scan-demo-4",
    ]
    # The two levothyroxine scans name the same shop, which is the point.
    assert reports.added[0].seller == reports.added[1].seller == "Riverside Demo Pharmacy"
    assert reports.added[2].purchase_location.city == "Douala"
    assert reports.added[2].purchase_location.country == "Cameroon"
    assert all(report.purchase_location is None or report.purchase_location.lat is None
               for report in reports.added)

    # A second run files nothing: skip-if-exists is (scan_id, seller).
    assert await seed_demo_scans.run(["--reports", "--yes"]) == 0
    assert len(reports.added) == 3


async def test_every_demo_seller_is_visibly_a_demo_and_no_report_carries_coordinates() -> None:
    specs = seed_demo_scans._demo_reports()
    assert 7 <= len(specs) <= 8
    for spec in specs:
        if spec.seller is not None:
            assert "demo" in spec.seller.casefold(), spec.seller
        location = spec.location
        if location is not None:
            assert location.lat is None and location.lon is None
            assert location.label is None
    # One report names a place but no seller, one a seller but no place.
    assert any(spec.seller is None and spec.location is not None for spec in specs)
    assert any(spec.seller is not None and spec.location is None for spec in specs)


async def test_purge_without_yes_never_touches_elasticsearch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("build_client must not be called without --yes")

    monkeypatch.setattr(seed_demo_scans, "get_settings", lambda: _settings())
    monkeypatch.setattr(seed_demo_scans, "build_client", _forbidden)

    exit_code = await seed_demo_scans.run(["--purge"])

    assert exit_code == 2
