"""Pipeline orchestration and the degradation matrix (design C §5.5).

Every dependency is injected, so no test touches Elasticsearch, Kibana,
Firecrawl, RxNav or OpenAI. The contract each row asserts: a failing stage is
recorded and survived, and a `complete` scan always carries a report.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from backend.config import Settings
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Pill, Reg, Scan, Web
from backend.knowledge.search import Hit, PillMatch
from backend.pill import HARDWARE_MODEL
from backend.research import pipeline as pipeline_module
from backend.research.agent_builder import AgentBuilderUnavailable, ConverseResult, ToolCall
from backend.research.models import ResearchReport
from backend.research.contract import to_scan_context
from backend.research.pipeline import ResearchPipeline, cancel_all, launch_research
from backend.research.rxnav import RxTerm
from backend.research.web import WebOutcome, reset_daily_credits

SCAN_ID = "scan-1"


@pytest.fixture(autouse=True)
def _clean_daily_counter() -> Any:
    # The pipeline now reserves credits up front, which touches the module-wide
    # daily counter; without this the suite exhausts it and tests interfere.
    reset_daily_credits()
    yield
    reset_daily_credits()


def settings(**kwargs: Any) -> Settings:
    base: dict[str, Any] = {
        "openai_api_key": "test",
        "firecrawl_api_key": "fc-test",
        "research_total_timeout_s": 30.0,
        "agent_builder_timeout_s": 5.0,
    }
    return Settings(**(base | kwargs))


def scan_doc(**kwargs: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        Scan.SCAN_ID: SCAN_ID,
        Scan.DEVICE_ID: "dev-1",
        Scan.COUNTRY: "Nigeria",
        Scan.STATUS: "pending",
        Scan.DEMO: False,
        Scan.BOTTLE: {
            "generic_name": "levothyroxine",
            "lot_number": "D2402430",
            "rx_number": "RX 8827341",
            "pharmacy": "Ikeja Pharmacy",
            "directions": "one tablet daily",
        },
        Scan.NORM: {
            "lot": "D2402430",
            "ndc9": "167290457",
            "ndc11": "16729045701",
            "ndc_raw": "16729-457-01",
            "imprint_norm": "ML8",
            "shape": "round",
            "colors": ["white"],
            "drug_names": ["levothyroxine"],
            "generic_name": "levothyroxine",
            "manufacturer": "Accord",
            "dosage_form": "tablet",
        },
    }
    doc.update(kwargs)
    return doc


def lot_hit() -> Hit:
    return Hit(
        index="peel-regulatory",
        id="fda-D-0785-2026",
        score=1.0,
        source={
            Reg.RECORD_ID: "fda-D-0785-2026",
            Reg.SOURCE_ORG: "FDA",
            Reg.TITLE: "Levothyroxine recall",
            Reg.SEVERITY: "high",
            Reg.LOT_NUMBERS: ["D2402430"],
            Reg.RECENCY_DATE: "2026-06-01T00:00:00Z",
            Reg.INDEXED_AT: "2026-09-18T00:00:00Z",
        },
        match_kind="exact_lot",
    )


class FakeStore:
    def __init__(self, doc: dict[str, Any] | None = None, *, get_error: Exception | None = None):
        self.doc = doc
        self.get_error = get_error
        self.applies: list[dict[str, Any]] = []

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        if self.get_error:
            raise self.get_error
        return self.doc

    async def apply(self, scan_id: str, **kwargs: Any) -> int:
        self.applies.append(kwargs)
        return len(self.applies)

    @property
    def statuses(self) -> list[str]:
        return [a["status"] for a in self.applies if a.get("status")]

    @property
    def stages(self) -> dict[str, dict[str, Any]]:
        return {a["stage"][0]: a["stage"][1] for a in self.applies if a.get("stage")}

    def last_patch(self) -> dict[str, Any]:
        return next(a["patch"] for a in reversed(self.applies) if a.get("patch"))


class FakeSearch:
    def __init__(self, **overrides: Any) -> None:
        self.overrides = overrides
        self.calls: list[str] = []

    def _value(self, name: str, default: Any) -> Any:
        self.calls.append(name)
        value = self.overrides.get(name, default)
        if isinstance(value, Exception):
            raise value
        return value

    async def recalls_by_lot(self, lot: str) -> list[Hit]:
        return self._value("recalls_by_lot", [])

    async def recalls_covering_all_lots(self, **kwargs: Any) -> list[Hit]:
        return self._value("recalls_covering_all_lots", [])

    async def recalls_by_ndc(self, ndc: Any) -> list[Hit]:
        return self._value("recalls_by_ndc", [])

    async def ndc_directory(self, ndc: Any) -> list[Hit]:
        return self._value("ndc_directory", [])

    async def identify_pill(self, **kwargs: Any) -> PillMatch:
        return self._value(
            "identify_pill", PillMatch(hits=[], rung=1, shape_relaxed=False, filters_applied={})
        )

    async def search_regulatory(self, query: str, filters: Any = None, **kwargs: Any) -> list[Hit]:
        return self._value("search_regulatory", [])

    async def search_web(self, query: str, **kwargs: Any) -> list[Hit]:
        return self._value("search_web", [])

    async def prior_scans(self, **kwargs: Any) -> dict[str, Any]:
        return self._value("prior_scans", {"total": 0, "by_verdict": {}})


class FakeWeb:
    def __init__(
        self,
        outcome: WebOutcome | None = None,
        error: Exception | None = None,
        *,
        pages: list[Hit] | None = None,
    ):
        self.outcome = outcome or WebOutcome(page_ids=["page-1"], credits=5)
        self.error = error
        self.pages = pages or []
        self.queries: list[str] = []
        self.requested_ids: list[str] = []
        self.harvested = 0

    async def search_and_index(self, query: Any, **kwargs: Any) -> WebOutcome:
        self.queries.append(query.text)
        if self.error:
            raise self.error
        return self.outcome

    async def pages_by_id(self, page_ids: list[str]) -> list[Hit]:
        self.requested_ids.extend(page_ids)
        return [hit for hit in self.pages if hit.id in set(page_ids)]

    async def harvest_agent_pages(self, tool_calls: Any, **kwargs: Any) -> list[str]:
        self.harvested += 1
        return []


class FakeAgent:
    def __init__(self, result: Any = None, error: Exception | None = None):
        self.result = result or ConverseResult(message="VERDICT: recall_match", conversation_id="c-1")
        self.error = error
        self.prompts: list[str] = []

    async def converse(self, prompt: str, **kwargs: Any) -> ConverseResult:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


class FakeOpenAI:
    def __init__(self, report: ResearchReport | None = None, error: Exception | None = None):
        self.report = report
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.responses = SimpleNamespace(parse=self._parse)

    async def _parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.report)


class FakeRxNav:
    def __init__(self, term: RxTerm | None = None, error: Exception | None = None):
        self.term = term
        self.error = error

    async def approximate_term(self, term: str | None) -> RxTerm | None:
        if self.error:
            raise self.error
        return self.term

    async def ndc_status(self, ndc11: str | None) -> None:
        return None


def build(
    *,
    doc: dict[str, Any] | None = None,
    store: FakeStore | None = None,
    search: FakeSearch | None = None,
    web: FakeWeb | None = None,
    agent: FakeAgent | None = None,
    openai_client: FakeOpenAI | None = None,
    rxnav: FakeRxNav | None = None,
    **setting_kwargs: Any,
) -> tuple[ResearchPipeline, FakeStore]:
    the_store = store or FakeStore(doc or scan_doc())
    return (
        ResearchPipeline(
            es=None,
            settings=settings(**setting_kwargs),
            search=search or FakeSearch(),
            store=the_store,
            web=web or FakeWeb(),
            agent=agent or FakeAgent(),
            openai_client=openai_client or FakeOpenAI(),
            rxnav=rxnav or FakeRxNav(),
        ),
        the_store,
    )


def llm_report(**kwargs: Any) -> ResearchReport:
    base: dict[str, Any] = {
        "verdict": "no_adverse_findings",
        "risk_level": "low",
        "headline": "Nothing adverse was found in the records searched.",
        "findings": [],
        "mismatches": [],
        "recall_hits": [],
        "gaps": [],
        "next_steps": ["Ask a pharmacist to check the medicine with its packaging."],
        "drug_facts": [],
        "sources": [],
        "agent_used": False,
        "demo": False,
    }
    return ResearchReport.model_validate(base | kwargs)


# --------------------------------------------------------------------------- happy path


async def test_a_full_run_writes_partial_then_complete() -> None:
    openai_client = FakeOpenAI(llm_report())
    search = FakeSearch(recalls_by_lot=[lot_hit()])
    pipeline, store = build(search=search, openai_client=openai_client)

    await pipeline.run(SCAN_ID)

    assert store.statuses == ["partial", "complete"]
    assert set(store.stages) == {"normalize", "deterministic", "web", "agent", "coerce"}
    assert all(stage["status"] == "ok" for stage in store.stages.values())
    report = store.last_patch()[Scan.RESEARCH]
    # The LLM said "nothing found" while an exact lot hit existed: F10 upgrade.
    assert report["verdict"] == "recall_match"
    assert report["agent_used"] is True


async def test_the_partial_report_lands_before_the_agent_runs() -> None:
    pipeline, store = build(search=FakeSearch(recalls_by_lot=[lot_hit()]))

    await pipeline.run(SCAN_ID)

    partial = next(a for a in store.applies if a.get("status") == "partial")
    assert partial["patch"][Scan.RESEARCH]["verdict"] == "recall_match"
    assert partial["patch"][Scan.EVIDENCE]["recall_record_ids"] == ["fda-D-0785-2026"]


async def test_prescription_details_never_reach_the_agent_prompt() -> None:
    agent = FakeAgent()
    pipeline, _ = build(agent=agent)

    await pipeline.run(SCAN_ID)

    prompt = agent.prompts[0]
    assert "8827341" not in prompt
    assert "Ikeja" not in prompt
    assert "one tablet daily" not in prompt
    assert "levothyroxine" in prompt


async def test_rxnav_patches_the_generic_name_and_keeps_the_original() -> None:
    rxnav = FakeRxNav(RxTerm(rxcui="10582", name="Levothyroxine Sodium", score=80.0))
    pipeline, store = build(rxnav=rxnav)

    await pipeline.run(SCAN_ID)

    norm = store.last_patch()[Scan.NORM]
    assert norm["generic_name"] == "levothyroxine sodium"
    assert norm["rxcui"] == "10582"
    assert "levothyroxine" in norm["drug_names"]


async def test_the_evidence_patch_carries_the_pill_candidates_the_contract_reads() -> None:
    hit = Hit(
        index="peel-pills",
        id="pill-1",
        score=1.0,
        source={Pill.PILL_ID: "pill-1", Pill.GENERIC_NAME: "levothyroxine", Pill.STRENGTH: "200 mcg"},
        match_kind="imprint_exact",
    )
    search = FakeSearch(identify_pill=PillMatch(hits=[hit], rung=1, shape_relaxed=False, filters_applied={}))
    pipeline, store = build(search=search)

    await pipeline.run(SCAN_ID)

    candidate = store.last_patch()[Scan.EVIDENCE]["pill_candidates"][0]
    assert candidate["source_id"] == "pill-1"
    assert candidate["form"] == "tablet"


async def test_the_finished_scan_converts_into_a_scan_context() -> None:
    hit = Hit(
        index="peel-pills",
        id="pill-1",
        score=1.0,
        source={Pill.PILL_ID: "pill-1", Pill.GENERIC_NAME: "levothyroxine"},
        match_kind="imprint_exact",
    )
    search = FakeSearch(
        recalls_by_lot=[lot_hit()],
        identify_pill=PillMatch(hits=[hit], rung=1, shape_relaxed=False, filters_applied={}),
    )
    pipeline, store = build(search=search)

    await pipeline.run(SCAN_ID)

    doc = scan_doc() | store.last_patch() | {Scan.STATUS: "complete", Scan.REVISION: 3}
    context = to_scan_context(doc)

    assert context["research"]["verdict"] == "recall_match"
    assert context["imprint"]["status"] == "candidate_found"
    assert context["sources"]
    assert context["drug_facts"]
    # sanitize_bottle keeps these out of the stored doc; the contract must not add them.
    assert "rx_number" not in (context["bottle"] or {})


async def test_a_mock_hardware_reading_marks_the_report_as_demo() -> None:
    doc = scan_doc(**{Scan.HARDWARE: {"status": "real", "model": HARDWARE_MODEL}})
    pipeline, store = build(doc=doc)

    await pipeline.run(SCAN_ID)

    assert store.last_patch()[Scan.RESEARCH]["demo"] is True


# --------------------------------------------------------------------------- degradation


async def test_an_unavailable_agent_is_recorded_and_survived() -> None:
    agent = FakeAgent(error=AgentBuilderUnavailable("Kibana returned 403"))
    pipeline, store = build(agent=agent)

    await pipeline.run(SCAN_ID)

    assert store.statuses[-1] == "complete"
    assert store.stages["agent"]["status"] == "unavailable"
    report = store.last_patch()[Scan.RESEARCH]
    assert report["agent_used"] is False
    assert any("Elastic research agent" in gap for gap in report["gaps"])


async def test_an_exhausted_firecrawl_budget_notes_a_gap_and_completes() -> None:
    web = FakeWeb()
    pipeline, store = build(web=web, firecrawl_daily_credit_cap=0)

    await pipeline.run(SCAN_ID)

    assert store.statuses[-1] == "complete"
    # The reservation fails before any search is launched, so nothing is spent.
    assert web.queries == []
    assert any("budget was spent" in gap for gap in store.last_patch()[Scan.RESEARCH]["gaps"])


async def test_searches_are_planned_against_the_budget_and_raise_no_gap() -> None:
    web = FakeWeb()
    pipeline, store = build(
        web=web,
        firecrawl_max_searches_per_scan=3,
        firecrawl_results_per_search=3,
        firecrawl_max_credits_per_scan=10,
    )

    await pipeline.run(SCAN_ID)

    # 10 // (2 + 3) == 2 affordable searches, so the third is never emitted.
    assert len(web.queries) == 2
    assert not any("budget was spent" in gap for gap in store.last_patch()[Scan.RESEARCH]["gaps"])


async def test_a_budget_too_small_for_one_search_does_note_a_gap() -> None:
    web = FakeWeb()
    pipeline, store = build(
        web=web, firecrawl_results_per_search=3, firecrawl_max_credits_per_scan=4
    )

    await pipeline.run(SCAN_ID)

    assert web.queries == []
    assert any("budget was spent" in gap for gap in store.last_patch()[Scan.RESEARCH]["gaps"])


async def test_the_daily_cap_blocks_the_second_of_two_planned_searches() -> None:
    web = FakeWeb()
    pipeline, store = build(web=web, firecrawl_daily_credit_cap=5)

    await pipeline.run(SCAN_ID)

    assert len(web.queries) == 1
    assert any("budget was spent" in gap for gap in store.last_patch()[Scan.RESEARCH]["gaps"])


async def test_pages_this_scan_fetched_are_unioned_into_the_evidence() -> None:
    ranked = Hit(
        index="peel-web-pages",
        id="page-ranked",
        score=1.0,
        source={Web.PAGE_ID: "page-ranked", Web.URL: "https://who.int/a", Web.DOMAIN: "who.int"},
        match_kind="web_hybrid",
    )
    fetched = Hit(
        index="peel-web-pages",
        id="page-1",
        score=0.0,
        source={
            Web.PAGE_ID: "page-1",
            Web.URL: "https://www.fda.gov/b",
            Web.DOMAIN: "fda.gov",
            Web.SOURCE_TIER: "regulator",
            Web.LOT_NUMBERS: ["D2402430"],
            Web.FLAGS: ["recall"],
        },
        match_kind="fetched_for_this_scan",
    )
    web = FakeWeb(pages=[fetched])
    pipeline, store = build(search=FakeSearch(search_web=[ranked]), web=web)

    await pipeline.run(SCAN_ID)

    # search_web ranked the freshly indexed page below the cut; it is added back.
    assert web.requested_ids == ["page-1"]
    pack = store.last_patch()[Scan.EVIDENCE]["evidence_pack"]
    assert {entry["page_id"] for entry in pack["web_hits"]} == {"page-ranked", "page-1"}


async def test_the_evidence_pack_carries_the_hardware_block() -> None:
    doc = scan_doc(**{Scan.HARDWARE: {"status": "substandard", "model": HARDWARE_MODEL}})
    pipeline, store = build(doc=doc)

    await pipeline.run(SCAN_ID)

    hardware = store.last_patch()[Scan.EVIDENCE]["evidence_pack"]["hardware"]
    assert hardware["status"] == "substandard"
    assert hardware["simulated"] is True


async def test_one_failing_search_is_recorded_without_losing_the_others() -> None:
    pipeline, store = build(web=FakeWeb(error=RuntimeError("firecrawl 502")))

    await pipeline.run(SCAN_ID)

    assert store.stages["web"]["status"] == "ok"
    assert store.statuses[-1] == "complete"
    errors = [q["error"] for q in store.last_patch()[Scan.EVIDENCE]["web_queries"]]
    assert all(error and "firecrawl 502" in error for error in errors)


async def test_web_research_is_skipped_without_a_firecrawl_key() -> None:
    web = FakeWeb()
    pipeline, store = build(web=web, firecrawl_api_key="")

    await pipeline.run(SCAN_ID)

    assert store.stages["web"]["status"] == "skipped"
    assert web.queries == []
    assert store.statuses[-1] == "complete"


async def test_openai_failing_keeps_the_deterministic_report() -> None:
    search = FakeSearch(recalls_by_lot=[lot_hit()])
    openai_client = FakeOpenAI(error=RuntimeError("openai is down"))
    pipeline, store = build(search=search, openai_client=openai_client)

    await pipeline.run(SCAN_ID)

    assert store.statuses[-1] == "complete"
    assert store.stages["coerce"]["status"] == "error"
    report = store.last_patch()[Scan.RESEARCH]
    assert report["verdict"] == "recall_match"
    assert report["risk_level"] == "high"


async def test_a_dead_elasticsearch_lookup_does_not_lose_the_others() -> None:
    search = FakeSearch(
        recalls_by_lot=RuntimeError("shard failure"), search_regulatory=[lot_hit()]
    )
    pipeline, store = build(search=search)

    await pipeline.run(SCAN_ID)

    assert store.stages["deterministic"]["status"] == "ok"
    assert store.statuses[-1] == "complete"


async def test_rxnav_failing_does_not_stop_the_run() -> None:
    pipeline, store = build(rxnav=FakeRxNav(error=TimeoutError("rxnav")))

    await pipeline.run(SCAN_ID)

    # asyncio.TimeoutError is TimeoutError, so a slow RxNav reads as a stage timeout.
    assert store.stages["normalize"]["status"] == "timeout"
    assert store.statuses[-1] == "complete"


async def test_elasticsearch_down_on_the_first_read_is_an_error() -> None:
    store = FakeStore(get_error=KnowledgeError("could not read the scan", status_code=502))
    pipeline, _ = build(store=store)

    await pipeline.run(SCAN_ID)

    assert store.statuses == ["error"]
    assert store.stages["load"]["status"] == "error"
    assert not any(a.get("patch") for a in store.applies)


async def test_a_missing_scan_writes_nothing() -> None:
    store = FakeStore(None)
    pipeline, _ = build(store=store)

    await pipeline.run(SCAN_ID)

    assert store.applies == []


async def test_the_total_timeout_still_produces_a_complete_report() -> None:
    class SlowAgent(FakeAgent):
        async def converse(self, prompt: str, **kwargs: Any) -> ConverseResult:
            await asyncio.sleep(5)
            raise AssertionError("should have been cancelled")

    pipeline, store = build(
        search=FakeSearch(recalls_by_lot=[lot_hit()]),
        agent=SlowAgent(),
        research_total_timeout_s=0.2,
        agent_builder_timeout_s=30.0,
    )

    await pipeline.run(SCAN_ID)

    assert store.statuses[-1] == "complete"
    report = store.last_patch()[Scan.RESEARCH]
    assert report["verdict"] == "recall_match"
    assert any("ran out of time" in gap for gap in report["gaps"])


async def test_tool_calls_are_compacted_into_the_evidence_patch() -> None:
    result = ConverseResult(
        message="narrative",
        conversation_id="conv-9",
        tool_calls=[
            ToolCall(
                tool_id="peel.recalls_by_lot",
                params={"lot": "D2402430"},
                results=[
                    {
                        "data": {
                            "columns": [{"name": "record_id"}],
                            "values": [["fda-D-0785-2026"], ["fda-2"], ["fda-3"], ["fda-4"]],
                        }
                    }
                ],
            )
        ],
    )
    pipeline, store = build(agent=FakeAgent(result))

    await pipeline.run(SCAN_ID)

    evidence = store.last_patch()[Scan.EVIDENCE]
    assert evidence["conversation_id"] == "conv-9"
    call = evidence["tool_calls"][0]
    assert call["tool_id"] == "peel.recalls_by_lot"
    assert call["row_count"] == 4
    assert len(call["rows"]) == pipeline_module.MAX_TOOL_ROWS


# --------------------------------------------------------------------------- launching


class StubPipeline:
    def __init__(self, delay: float = 0.05) -> None:
        self.runs = 0

    async def run(self, scan_id: str) -> None:
        self.runs += 1
        await asyncio.sleep(0.05)


def app_with(stub: StubPipeline) -> FastAPI:
    app = FastAPI()
    app.state.research_pipeline = stub
    return app


async def test_a_second_launch_is_refused_until_the_first_finishes() -> None:
    stub = StubPipeline()
    app = app_with(stub)

    assert launch_research(app, SCAN_ID) is True
    assert launch_research(app, SCAN_ID) is False

    await asyncio.sleep(0.1)
    assert stub.runs == 1
    assert launch_research(app, SCAN_ID) is True
    await cancel_all(app)


async def test_force_cancels_the_running_task() -> None:
    stub = StubPipeline()
    app = app_with(stub)

    launch_research(app, SCAN_ID)
    first = app.state.research_tasks[SCAN_ID]

    assert launch_research(app, SCAN_ID, force=True) is True
    assert first.cancelled() or first.cancelling()
    assert app.state.research_tasks[SCAN_ID] is not first
    await cancel_all(app)


async def test_a_finished_task_is_forgotten() -> None:
    app = app_with(StubPipeline())

    launch_research(app, SCAN_ID)
    await asyncio.sleep(0.1)

    assert SCAN_ID not in app.state.research_tasks


async def test_cancel_all_drains_the_registry() -> None:
    app = app_with(StubPipeline())
    launch_research(app, SCAN_ID)
    launch_research(app, "scan-2")

    await cancel_all(app)

    assert app.state.research_tasks == {}


def test_launch_returns_false_when_no_pipeline_can_be_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(app: Any) -> Any:
        raise KnowledgeError("Elasticsearch URL and API key are not set", status_code=503)

    monkeypatch.setattr(pipeline_module, "get_pipeline", boom)

    assert launch_research(FastAPI(), SCAN_ID) is False
