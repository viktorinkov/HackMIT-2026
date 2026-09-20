"""Seed ~12 demo scans for device_id "peel-graph-demo" into the live `peel-scans`
index, at zero paid cost.

    uv run python scripts/seed_demo_scans.py                 # dry run (default, writes nothing)
    uv run python scripts/seed_demo_scans.py --yes            # actually write
    uv run python scripts/seed_demo_scans.py --only 1,4,7     # a subset of scenarios
    uv run python scripts/seed_demo_scans.py --force --yes    # re-create over an existing match
    uv run python scripts/seed_demo_scans.py --reports        # dry run of the demo purchase reports
    uv run python scripts/seed_demo_scans.py --reports --yes  # file them against the demo scans
    uv run python scripts/seed_demo_scans.py --purge --yes    # delete every peel-graph-demo scan

The default is a **dry run**: it prints, per scenario, the `ScanCreate` payload
summary and the expected outcome, and — using read-only `KnowledgeSearch`
lookups against the live cluster — what the corpus actually returns right now,
flagging anything that disagrees with the expected outcome. Nothing is written
until `--yes` is given, and this script should only ever be run with `--yes`
or `--purge --yes` on the user's own go-ahead.

Every scan is created with `ScanStore.create` and researched with the real
`ResearchPipeline`, but `web`, `agent`, `openai_client` and `rxnav` are all
replaced through the pipeline's constructor seams (`ResearchPipeline.__init__`,
`research/pipeline.py:226-247`) with stand-ins that never touch Firecrawl,
Kibana, OpenAI or RxNav's HTTP API — every other attribute access on them
raises `AssertionError`, so a code path this script's author did not
anticipate fails loudly instead of spending a credit or a token. Elasticsearch
reads and writes (`peel-scans`, `peel-regulatory`, `peel-web-pages`, ...) are
the only network calls this script ever makes; `firecrawl_enabled` is left
exactly as `.env` set it, so `KnowledgeSearch.search_web` can still surface
pages a *previous, real* scan already cached, at zero additional cost.

`--reports` is a second, independent phase over the same demo device: it files
a handful of invented purchase reports (`peel-reports`) against demo scans that
already exist, so the Atlas graph has sellers and places to draw. Every seller
name contains the word "Demo" and every one of them is fictional; the cities and
countries are real ones that match each scenario's own country.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from elasticsearch import ApiError, AsyncElasticsearch

from backend.config import Settings, get_settings
from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError, build_client
from backend.knowledge.fields import REPORTS_INDEX, SCANS_INDEX, Reg, Scan
from backend.knowledge.fields import Report as ReportFields
from backend.knowledge.search import KnowledgeSearch
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import HARDWARE_MODEL, PillHardwareResult
from backend.reports.models import PurchaseLocation, Report
from backend.reports.store import ElasticReportStore
from backend.research import pipeline as pipeline_module
from backend.research.agent_builder import AgentBuilderUnavailable
from backend.research.pipeline import ResearchPipeline
from backend.research.web import WebOutcome
from backend.scans.models import ScanCreate
from backend.scans.normalizer import build_norm
from backend.scans.store import ScanStore

DEVICE_ID = "peel-graph-demo"
BACKDATE_DAYS = 21
MAX_DEMO_SCANS = 200


# --------------------------------------------------------------------------- stubs
#
# Every method below either returns the same *empty* value the real dependency
# would return on a cache miss / unavailable service, or raises the exception
# the pipeline already knows how to survive (`AgentBuilderUnavailable`). Any
# attribute this script's author did not anticipate falls through to
# `__getattr__`, which raises loudly rather than silently reaching a paid API.


class _NoNetwork:
    """Base for every stand-in: an unlisted attribute is a bug, not a network call."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"{type(self).__name__}.{name} was reached — the demo seeder must never "
            "call Firecrawl, Agent Builder / Kibana, OpenAI or RxNav"
        )


class _StubWeb(_NoNetwork):
    """Keeps `firecrawl_enabled` meaningful without ever calling Firecrawl.

    `_stage_web`/`_collect_web_hits` (research/pipeline.py) call exactly three
    methods on the injected `web`: `search_and_index`, `pages_for_scan` and
    `pages_by_id`. `search_web` itself is a `KnowledgeSearch` method (a plain
    Elasticsearch read over `peel-web-pages`), so cached pages from a *real*
    scan still surface through the ranked hits even though this stub never
    fetches a new one.
    """

    async def search_and_index(self, query: Any, **kwargs: Any) -> WebOutcome:
        return WebOutcome()

    async def pages_for_scan(self, scan_id: str, **kwargs: Any) -> list[Any]:
        return []

    async def pages_by_id(self, page_ids: list[str]) -> list[Any]:
        return []


class _StubAgent(_NoNetwork):
    async def converse(self, prompt: str, **kwargs: Any) -> Any:
        raise AgentBuilderUnavailable("demo seeder: Agent Builder is stubbed out")


class _StubResponses(_NoNetwork):
    async def parse(self, **kwargs: Any) -> Any:
        return SimpleNamespace(output_parsed=None)


class _StubOpenAI(_NoNetwork):
    def __init__(self) -> None:
        self.responses = _StubResponses()


class _StubRxNav(_NoNetwork):
    async def approximate_term(self, term: str | None) -> None:
        return None

    async def ndc_status(self, ndc11: str | None) -> None:
        return None


# --------------------------------------------------------------------------- scenarios


@dataclass(frozen=True)
class Scenario:
    number: int
    title: str
    scan_create: ScanCreate
    expected: str
    # (record_id, match_kind) pairs the live corpus is expected to return right
    # now. Empty means "no expectation asserted" (still printed, never flagged).
    expect_lot: tuple[tuple[str, str], ...] = ()
    expect_ndc: tuple[tuple[str, str], ...] = ()


def _scenarios() -> list[Scenario]:
    return [
        Scenario(
            number=1,
            title="Levothyroxine Sodium 200 mcg — the recalled lot",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                country="United States",
                hardware_model=HARDWARE_MODEL,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Levothyroxine Sodium",
                    strength="200 mcg",
                    form="tablet",
                    ndc="16729-457-15",
                    manufacturer="Accord Healthcare",
                    lot_number="D2402430",
                    expiration="10/2026",
                    confidence=0.93,
                ),
                imprint=ImprintPhotoResult(
                    is_pill=True, color="pink", shape="round", confidence=0.7
                ),
                hardware=PillHardwareResult(
                    status="substandard",
                    spectrum=[0.1] * 16,
                    pill_type="levothyroxine",
                    degraded=False,
                    confidence=0.78,
                ),
            ),
            expected=(
                "recall_match -> fda-enf-D-0785-2026 (exact_lot); NDC 16729-457 "
                "corroborates as ndc_in_description, event 99584"
            ),
            expect_lot=(("fda-enf-D-0785-2026", "exact_lot"),),
            expect_ndc=(("fda-enf-D-0785-2026", "ndc_in_description"),),
        ),
        Scenario(
            number=2,
            title="Levothyroxine Sodium 200 mcg — near-miss lot, same product",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                country="United States",
                hardware_model=HARDWARE_MODEL,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Levothyroxine Sodium",
                    strength="200 mcg",
                    form="tablet",
                    ndc="16729-457-15",
                    manufacturer="Accord Healthcare",
                    lot_number="D2402999",
                    expiration="10/2026",
                    confidence=0.93,
                ),
                imprint=ImprintPhotoResult(
                    is_pill=True, color="pink", shape="round", confidence=0.7
                ),
                hardware=PillHardwareResult(
                    status="substandard",
                    spectrum=[0.1] * 16,
                    pill_type="levothyroxine",
                    degraded=False,
                    confidence=0.78,
                ),
            ),
            expected=(
                "no exact_lot hit (D2402999 is absent from the corpus); NDC 16729-457 "
                "still surfaces fda-enf-D-0785-2026 as an ndc_in_description caution, "
                "never recall_match; shares product/manufacturer/medicine nodes with #1"
            ),
            expect_lot=(),
            expect_ndc=(("fda-enf-D-0785-2026", "ndc_in_description"),),
        ),
        Scenario(
            number=3,
            title="Levothyroxine Sodium 112 mcg — sibling strength, its own recalled lot",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                country="United States",
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Levothyroxine Sodium",
                    strength="112 mcg",
                    form="tablet",
                    ndc="16729-452-17",
                    manufacturer="Accord Healthcare",
                    lot_number="D2402443",
                    expiration="10/2026",
                    confidence=0.9,
                ),
            ),
            expected=(
                "recall_match -> fda-enf-D-0780-2026 (exact_lot; same event 99584 as #1)"
            ),
            expect_lot=(("fda-enf-D-0780-2026", "exact_lot"),),
            expect_ndc=(("fda-enf-D-0780-2026", "ndc_in_description"),),
        ),
        Scenario(
            number=4,
            title="HEALMOXY Amoxicillin 500 mg — falsified, two regulators converge",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                country="Cameroon",
                hardware_model=HARDWARE_MODEL,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    brand_name="HEALMOXY",
                    generic_name="Amoxicillin",
                    strength="500 mg",
                    form="capsule",
                    manufacturer="MAXHEAL PHARMACEUTICALS",
                    lot_number="H02605",
                    confidence=0.85,
                ),
                imprint=ImprintPhotoResult(
                    is_pill=True, color="white", shape="capsule", confidence=0.6
                ),
                hardware=PillHardwareResult(
                    status="fake",
                    spectrum=[0.2] * 16,
                    pill_type="amoxicillin",
                    degraded=False,
                    confidence=0.6,
                ),
            ),
            expected=(
                "exact_lot x2 -> who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd and "
                "nafdac-18658 (falsified_alert; NAFDAC's manufacturer field is prose, "
                "so the record->manufacturer edge must be stated_manufacturer, not alert)"
            ),
            expect_lot=(
                ("who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd", "exact_lot"),
                ("nafdac-18658", "exact_lot"),
            ),
        ),
        Scenario(
            number=5,
            title="Ibuprofen 200 mg — clean, imprint closes a triangle",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                hardware_model=HARDWARE_MODEL,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Ibuprofen",
                    strength="200 mg",
                    form="tablet",
                    confidence=0.8,
                ),
                imprint=ImprintPhotoResult(
                    is_pill=True, imprint="I-2", color="brown", shape="round", confidence=0.75
                ),
                hardware=PillHardwareResult(
                    status="real",
                    spectrum=[0.05] * 16,
                    pill_type="ibuprofen",
                    degraded=False,
                    confidence=0.82,
                ),
            ),
            expected=(
                "no_adverse_findings; no lot or NDC on the label, so the exact-lot and "
                "NDC lookups have nothing to run against; imprint I-2 -> med:ibuprofen "
                "closes a triangle with the label"
            ),
        ),
        Scenario(
            number=6,
            title="Hydrochlorothiazide 12.5 mg — older Class I recall",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Hydrochlorothiazide",
                    strength="12.5 mg",
                    form="tablet",
                    ndc="16729-182-01",
                    manufacturer="Accord Healthcare",
                    lot_number="PW05264",
                    confidence=0.88,
                ),
            ),
            expected=(
                "recall_match -> fda-enf-D-1206-2018 (Class I, 2018, freshness "
                "'older'); shares mfr:accord healthcare with #1 and #3"
            ),
            expect_lot=(("fda-enf-D-1206-2018", "exact_lot"),),
            expect_ndc=(("fda-enf-D-1206-2018", "ndc_in_description"),),
        ),
        Scenario(
            number=7,
            title="Chlorpromazine HCl 10 mg — exact hit and a lot-string collision",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Chlorpromazine HCl",
                    strength="10 mg",
                    form="tablet",
                    ndc="70710-1129-1",
                    manufacturer="Zydus",
                    lot_number="Z400069",
                    confidence=0.85,
                ),
            ),
            expected=(
                "exact_lot -> fda-enf-D-0361-2025; lot_only_match -> nafdac-17970 "
                "('various products') on the same lot node — unconfirmed, product "
                "not named in the NAFDAC record, not a second independent collision"
            ),
            expect_lot=(
                ("fda-enf-D-0361-2025", "exact_lot"),
                ("nafdac-17970", "lot_only_match"),
            ),
            expect_ndc=(("fda-enf-D-0361-2025", "ndc_in_description"),),
        ),
        Scenario(
            number=8,
            title="Metformin HCl 500 mg — pure lot collisions, no NDC",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Metformin HCl",
                    strength="500 mg",
                    form="tablet",
                    lot_number="D24005",
                    confidence=0.82,
                ),
            ),
            expected=(
                "two lot_only_match collisions (fda-enf-D-0051-2025 bevacizumab, "
                "fda-enf-D-0719-2022 NAD+); the verdict is not a recall"
            ),
            expect_lot=(
                ("fda-enf-D-0051-2025", "lot_only_match"),
                ("fda-enf-D-0719-2022", "lot_only_match"),
            ),
        ),
        Scenario(
            number=9,
            title="Aspirin 325 mg — expired NDC listing",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Aspirin",
                    strength="325 mg",
                    form="tablet",
                    ndc="53209-2000-02",
                    manufacturer="Morning Stat OTC",
                    confidence=0.8,
                ),
            ),
            expected=(
                "no recall; the NDC directory row for ndc9 532092000 carries "
                "is_listing_expired=true (one of only 3 in the corpus); the "
                "deterministic report does not surface it on its own"
            ),
        ),
        Scenario(
            number=10,
            title="Ibuprofen 200 mg label — imprint mismatch to temazepam",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Ibuprofen",
                    strength="200 mg",
                    form="tablet",
                    confidence=0.8,
                ),
                imprint=ImprintPhotoResult(
                    is_pill=True, imprint="5892 V", color="pink", shape="capsule", confidence=0.8
                ),
            ),
            expected=(
                "mismatch_found: imprint 5892 V identifies as temazepam, not "
                "ibuprofen; produces a conflicts_with edge, never a recall"
            ),
        ),
        Scenario(
            number=11,
            title="Losartan Potassium 50 mg — Accord becomes a cross-regulator hub",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                country="United Kingdom",
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    generic_name="Losartan Potassium",
                    strength="50 mg",
                    form="tablet",
                    manufacturer="Accord Healthcare Limited",
                    lot_number="PT04882",
                    confidence=0.87,
                ),
            ),
            expected=(
                "exact_lot -> mhra-485cc3f1-e112-473f-92a7-9a9af2422485 (critical); "
                "Accord Healthcare spans FDA and MHRA in the same graph"
            ),
            expect_lot=(
                ("mhra-485cc3f1-e112-473f-92a7-9a9af2422485", "exact_lot"),
            ),
        ),
        Scenario(
            number=12,
            title="JAMP-Montelukast 10 mg — Health Canada substandard alert",
            scan_create=ScanCreate(
                device_id=DEVICE_ID,
                demo=True,
                country="Canada",
                bottle=BottlePhotoResult(
                    is_medication_container=True,
                    brand_name="JAMP-Montelukast",
                    generic_name="Montelukast",
                    strength="10 mg",
                    form="tablet",
                    lot_number="AT240486A",
                    confidence=0.83,
                ),
            ),
            expected="exact_lot -> hc-77328 (substandard_alert)",
            expect_lot=(("hc-77328", "exact_lot"),),
        ),
    ]


# --------------------------------------------------------------------------- reports


@dataclass(frozen=True)
class DemoReport:
    """One invented purchase report, joined to a scenario by its number.

    Nothing here is a real shop. Every `seller` carries the word "Demo" so that
    no one can mistake a rehearsal pharmacy for an accusation about a real one;
    the city, region and country are real and match the scenario's own country.
    """

    scenario: int
    purchased_on: date
    seller: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None

    @property
    def location(self) -> PurchaseLocation | None:
        if not any((self.city, self.region, self.country)):
            return None
        return PurchaseLocation(city=self.city, region=self.region, country=self.country)

    def describe(self) -> str:
        place = ", ".join(part for part in (self.city, self.region, self.country) if part)
        return (
            f"seller={self.seller!r} place={place or None!r} "
            f"purchased_on={self.purchased_on.isoformat()!r}"
        )


def _demo_reports() -> list[DemoReport]:
    return [
        # The same shop on both levothyroxine bottles and on the older
        # hydrochlorothiazide one: one seller node joining three scans.
        DemoReport(1, date(2026, 8, 20), "Riverside Demo Pharmacy", "Columbus", "Ohio",
                   "United States"),
        DemoReport(2, date(2026, 9, 2), "Riverside Demo Pharmacy", "Columbus", "Ohio",
                   "United States"),
        DemoReport(6, date(2026, 6, 15), "Riverside Demo Pharmacy", "Columbus", "Ohio",
                   "United States"),
        # A seller with no place at all: the node exists, the place does not.
        DemoReport(3, date(2026, 7, 9), "Demo Mail Order Depot"),
        DemoReport(4, date(2026, 8, 30), "Pharmacie du Marché Demo", "Douala", "Littoral",
                   "Cameroon"),
        DemoReport(7, date(2026, 8, 5), "Demo Clinic Dispensary", "Columbus", "Ohio",
                   "United States"),
        DemoReport(11, date(2026, 8, 12), "High Street Demo Chemist", "Leeds", "England",
                   "United Kingdom"),
        # A place with no seller: the scan reaches the town directly.
        DemoReport(12, date(2026, 7, 28), None, "Toronto", "Ontario", "Canada"),
    ]


async def _scans_by_signature(store: ScanStore) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    docs, _ = await store.list(device_id=DEVICE_ID, limit=MAX_DEMO_SCANS)
    out: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for doc in docs:
        out.setdefault(_signature(doc.get(Scan.NORM) or {}), doc)
    return out


async def _already_filed(reports: ElasticReportStore, scan_id: str, seller: str | None) -> bool:
    """Skip-if-exists by (scan_id, seller), so a re-run files nothing twice."""
    try:
        existing = await reports.list_for_scan(scan_id)
    except KnowledgeError as exc:
        print(f"  [WARN] could not list existing reports: {exc.message}")
        return False
    return any((report.seller or None) == seller for report in existing)


async def _seed_reports(es: AsyncElasticsearch, settings: Settings, *, write: bool) -> int:
    store = ScanStore(es, settings)
    reports = ElasticReportStore(es)
    scenarios = {scenario.number: scenario for scenario in _scenarios()}

    try:
        by_signature = await _scans_by_signature(store)
    except Exception as exc:  # noqa: BLE001 - report and stop, never guess
        print(f"Could not list the demo scans: {type(exc).__name__}: {exc}")
        return 1

    specs = _demo_reports()
    print("=" * 78)
    print(f"Peel Atlas demo reports — device_id={DEVICE_ID!r}, {len(specs)} report(s)")
    print(f"mode: {'WRITE (--yes)' if write else 'DRY RUN (no writes; pass --yes to write)'}")
    print("=" * 78)

    filed = 0
    for spec in specs:
        scenario = scenarios.get(spec.scenario)
        print(f"\n--- Report for scenario {spec.scenario}"
              f"{': ' + scenario.title if scenario else ''} ---")
        print(spec.describe())
        if scenario is None:
            print("status: SKIP — no such scenario")
            continue
        doc = by_signature.get(_signature(_norm_for(scenario)))
        if doc is None:
            print("status: SKIP — that demo scan does not exist yet "
                  "(seed the scans first, with --yes)")
            continue
        scan_id = str(doc.get(Scan.SCAN_ID) or "")
        if await _already_filed(reports, scan_id, spec.seller):
            print(f"status: SKIP — already filed against scan_id={scan_id}")
            continue
        if not write:
            print(f"status: would FILE against scan_id={scan_id}")
            continue
        stored = await reports.add(
            Report(
                scan_id=scan_id,
                purchased_on=spec.purchased_on,
                purchase_location=spec.location,
                seller=spec.seller,
                created_at=datetime.now(UTC),
            )
        )
        filed += 1
        print(f"  -> report_id={stored.report_id} scan_id={scan_id}")

    print()
    if not write:
        print("Dry run complete. Nothing was written. Re-run with --yes once approved.")
    else:
        print(f"Write complete: {filed} report(s) filed.")
    return 0


# --------------------------------------------------------------------------- helpers


def _norm_for(scenario: Scenario) -> dict[str, Any]:
    payload = scenario.scan_create
    return build_norm(
        payload.bottle,
        payload.imprint,
        imprint_size_mm=payload.imprint_size_mm,
        now=datetime.now(UTC),
    )


def _signature(norm: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (norm.get("lot"), norm.get("generic_name"), norm.get("imprint_norm"))


def _payload_summary(scenario: Scenario) -> str:
    payload = scenario.scan_create
    bottle = payload.bottle
    imprint = payload.imprint
    hardware = payload.hardware
    drug = (bottle.generic_name or bottle.brand_name) if bottle else None
    imprint_desc = (
        f"{imprint.imprint or '(none printed)'} {imprint.color or ''} {imprint.shape or ''}".strip()
        if imprint
        else "none"
    )
    return (
        f"drug={drug!r} strength={(bottle.strength if bottle else None)!r} "
        f"ndc={(bottle.ndc if bottle else None)!r} lot={(bottle.lot_number if bottle else None)!r} "
        f"manufacturer={(bottle.manufacturer if bottle else None)!r} "
        f"country={payload.country!r} imprint={imprint_desc!r} "
        f"hardware={(hardware.status if hardware else None)!r}"
    )


def _diff(expected: tuple[tuple[str, str], ...], actual: list[tuple[str, str]]) -> list[str]:
    problems: list[str] = []
    for record_id, kind in expected:
        found_kind = next((k for rid, k in actual if rid == record_id), None)
        if found_kind is None:
            problems.append(f"expected {record_id} ({kind}) — NOT FOUND in the live corpus")
        elif found_kind != kind:
            problems.append(f"expected {record_id} as {kind}, live corpus says {found_kind}")
    return problems


async def _live_check(search: KnowledgeSearch, norm: dict[str, Any]) -> dict[str, list[tuple[str, str]]]:
    """The same read-only lookups `ResearchPipeline._deterministic` runs.

    `ndc9` and `drug_names` are built exactly the way `pipeline._product_names`
    builds them, per the plan — reusing that private helper directly rather
    than re-implementing it, so this can never silently drift from stage 2.
    """
    out: dict[str, list[tuple[str, str]]] = {"lot": [], "ndc": [], "all_lots": []}
    product_names = pipeline_module._product_names(norm)
    if norm.get("lot"):
        hits = await search.recalls_by_lot(
            norm["lot"], ndc9=norm.get("ndc9"), drug_names=product_names
        )
        out["lot"] = [(str(hit.source.get(Reg.RECORD_ID, hit.id)), hit.match_kind or "") for hit in hits]
    ndc_forms = normalize.normalize_ndc(
        norm.get("ndc_raw") or norm.get("ndc11") or norm.get("ndc9")
    )
    if ndc_forms is not None:
        hits = await search.recalls_by_ndc(ndc_forms)
        out["ndc"] = [(str(hit.source.get(Reg.RECORD_ID, hit.id)), hit.match_kind or "") for hit in hits]
    hits = await search.recalls_covering_all_lots(
        ndc9=norm.get("ndc9"),
        drug_names=product_names,
        manufacturer=norm.get("manufacturer"),
    )
    out["all_lots"] = [(str(hit.source.get(Reg.RECORD_ID, hit.id)), hit.match_kind or "") for hit in hits]
    return out


def _backdated_iso(index: int, total: int) -> str:
    """Spreads scenarios across the last `BACKDATE_DAYS` days, oldest first."""
    span = max(1, total - 1)
    days_ago = BACKDATE_DAYS - round(BACKDATE_DAYS * index / span) if total > 1 else BACKDATE_DAYS
    when = datetime.now(UTC) - timedelta(days=days_ago, hours=(index * 7) % 24, minutes=(index * 13) % 60)
    return normalize.to_iso(when) or when.isoformat()


async def _existing_signatures(store: ScanStore) -> set[tuple[Any, Any, Any]]:
    docs, _ = await store.list(device_id=DEVICE_ID, limit=100)
    out: set[tuple[Any, Any, Any]] = set()
    for doc in docs:
        norm = doc.get(Scan.NORM) or {}
        out.add(_signature(norm))
    return out


def _demo_scan_query() -> dict[str, Any]:
    return {
        "bool": {"filter": [{"term": {Scan.DEVICE_ID: DEVICE_ID}}, {"term": {Scan.DEMO: True}}]}
    }


async def _demo_scan_ids(es: AsyncElasticsearch) -> list[str] | None:
    """Every demo scan id, read-only. `None` means "could not tell".

    Paged rather than capped: the purge deletes the scans by query but the
    reports only by the ids listed here, so an id this misses is a demo report
    that outlives its scan and stops being recognisable as rehearsal data.
    """
    out: list[str] = []
    after: list[Any] | None = None
    while True:
        try:
            response = await es.search(
                index=SCANS_INDEX,
                query=_demo_scan_query(),
                size=MAX_DEMO_SCANS,
                source={"includes": [Scan.SCAN_ID]},
                sort=[{Scan.SCAN_ID: "asc"}],
                track_total_hits=False,
                **({"search_after": after} if after else {}),
            )
        except Exception as exc:  # noqa: BLE001 - report and stop, never guess
            print(f"Could not list matching scans: {type(exc).__name__}: {exc}")
            return None
        hits = list(response["hits"]["hits"])
        for hit in hits:
            scan_id = str((hit.get("_source") or {}).get(Scan.SCAN_ID) or hit.get("_id") or "")
            if scan_id:
                out.append(scan_id)
        if len(hits) < MAX_DEMO_SCANS:
            return out
        sort_values = hits[-1].get("sort")
        if not sort_values:
            # No cursor to page on: stop rather than loop on the same page.
            print(f"Listed {len(out)} scan(s); the cluster returned no paging cursor.")
            return out
        after = list(sort_values)


async def _report_count(es: AsyncElasticsearch, query: dict[str, Any]) -> int | None:
    """How many reports match, or `None` when the cluster would not say."""
    try:
        response = await es.count(index=REPORTS_INDEX, query=query)
    except Exception as exc:  # noqa: BLE001 - report and stop, never guess
        print(f"Could not count matching reports: {type(exc).__name__}: {exc}")
        return None
    return int(response.get("count", 0))


async def _purge_reports(es: AsyncElasticsearch, scan_ids: list[str]) -> int:
    """Reports are joined to a scan by `scan_id` alone, so they go first: once
    the scans are gone there is nothing left to select them by.

    A report that outlives its scan is worse than one that is never deleted: it
    is a demo report with no demo scan behind it, which no longer looks like
    rehearsal data to anything that reads it. So a partial delete is a failure
    here, and the caller must not go on to delete the scans — `delete_by_query`
    reports `failures` and `version_conflicts` while still returning a `deleted`
    count, so the count alone cannot tell the two apart.
    """
    query: dict[str, Any] = {"bool": {"filter": [{"terms": {ReportFields.SCAN_ID: scan_ids}}]}}
    count = await _report_count(es, query)
    if count is None:
        return 1
    print(f"peel-reports: {count} document(s) filed against those scans.")
    if count == 0:
        print("No reports to delete.")
        return 0
    try:
        response = await es.delete_by_query(index=REPORTS_INDEX, query=query, refresh=True)
    except ApiError as exc:
        if exc.status_code in (401, 403):
            print(
                f"PERMISSION ERROR: the configured Elasticsearch API key cannot delete "
                f"from {REPORTS_INDEX} ({exc.status_code}): {exc.message}"
            )
            return 1
        print(f"Delete failed: {exc.message}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Delete failed: {type(exc).__name__}: {exc}")
        return 1
    print(f"Deleted {int(response.get('deleted', 0))} report(s).")

    failures = list(response.get("failures") or [])
    conflicts = int(response.get("version_conflicts", 0) or 0)
    if failures:
        print(f"{len(failures)} shard failure(s) during the report delete: {failures[0]}")
    if conflicts:
        print(f"{conflicts} version conflict(s) during the report delete.")

    remaining = await _report_count(es, query)
    if remaining is None:
        return 1
    if remaining:
        print(
            f"{remaining} report(s) still match. Re-run --purge --yes; the scans are "
            "left in place so those reports can still be selected by scan_id."
        )
        return 1
    if failures or conflicts:
        print("Every matching report is gone despite the failures above.")
    return 0


async def _purge(es: AsyncElasticsearch) -> int:
    scan_ids = await _demo_scan_ids(es)
    if scan_ids is None:
        return 1
    if scan_ids:
        failed = await _purge_reports(es, scan_ids)
        if failed:
            return failed
    else:
        print("peel-reports: no demo scans, so no demo reports to delete.")

    query = _demo_scan_query()
    try:
        count_response = await es.count(index=SCANS_INDEX, query=query)
    except Exception as exc:  # noqa: BLE001 - report and stop, never guess
        print(f"Could not count matching scans: {type(exc).__name__}: {exc}")
        return 1
    count = int(count_response.get("count", 0))
    print(f"peel-scans: {count} document(s) match device_id={DEVICE_ID!r} AND demo=true.")
    if count == 0:
        print("Nothing to delete.")
        return 0
    try:
        response = await es.delete_by_query(index=SCANS_INDEX, query=query, refresh=True)
    except ApiError as exc:
        if exc.status_code in (401, 403):
            print(
                f"PERMISSION ERROR: the configured Elasticsearch API key cannot delete "
                f"from {SCANS_INDEX} ({exc.status_code}): {exc.message}"
            )
            return 1
        print(f"Delete failed: {exc.message}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Delete failed: {type(exc).__name__}: {exc}")
        return 1
    deleted = int(response.get("deleted", 0))
    print(f"Deleted {deleted} document(s) for device_id={DEVICE_ID!r}.")
    return 0


def _parse_only(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    out: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk:
            out.add(int(chunk))
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="actually write the scans (default: dry run)")
    parser.add_argument("--only", default=None, help="comma-separated scenario numbers, e.g. 1,4,7")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="delete every peel-graph-demo scan (device_id AND demo:true); requires --yes",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-create a scenario even if one already exists"
    )
    parser.add_argument(
        "--reports",
        action="store_true",
        help="file the demo purchase reports against the demo scans instead of seeding scans",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- main


async def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.purge and not args.yes:
        print("ERROR: --purge requires --yes (it deletes live peel-scans documents).")
        return 2

    settings = get_settings()
    numbers = _parse_only(args.only)
    scenarios = [s for s in _scenarios() if numbers is None or s.number in numbers]

    es: AsyncElasticsearch | None = None
    es_error: str | None = None
    try:
        es = build_client(settings)
    except KnowledgeError as exc:
        es_error = exc.message

    if args.purge:
        if es is None:
            print(f"Cannot purge: Elasticsearch is not reachable/configured ({es_error}).")
            return 1
        try:
            return await _purge(es)
        finally:
            await es.close()

    if args.reports:
        if es is None:
            print(f"Cannot file reports: Elasticsearch is not reachable/configured ({es_error}).")
            return 1
        try:
            return await _seed_reports(es, settings, write=args.yes)
        finally:
            await es.close()

    search = KnowledgeSearch(es, settings) if es is not None else None
    store = ScanStore(es, settings) if es is not None else None

    existing: set[tuple[Any, Any, Any]] = set()
    if store is not None and es_error is None:
        try:
            existing = await _existing_signatures(store)
        except Exception as exc:  # noqa: BLE001 - dry run must still print payloads
            es_error = f"{type(exc).__name__}: {exc}"

    print("=" * 78)
    print(f"Peel Atlas demo seeder — device_id={DEVICE_ID!r}, {len(scenarios)} scenario(s)")
    print(f"mode: {'WRITE (--yes)' if args.yes else 'DRY RUN (no writes; pass --yes to write)'}")
    print("=" * 78)
    if es_error:
        print(f"[WARN] Elasticsearch unreachable/not configured: {es_error}")
        print("       Payload summaries and expected outcomes still print below; live")
        print("       corpus checks and skip-if-exists detection are unavailable.\n")

    try:
        for index, scenario in enumerate(scenarios):
            norm = _norm_for(scenario)
            signature = _signature(norm)
            exists = signature in existing

            print(f"\n--- Scenario {scenario.number}: {scenario.title} ---")
            print(_payload_summary(scenario))
            print(f"expected: {scenario.expected}")

            if exists and not args.force:
                print("status: SKIP — a scan with this (lot, generic_name, imprint_norm) "
                      "signature already exists for peel-graph-demo (pass --force to re-create)")
            elif not args.yes:
                suffix = " (would force a re-create over an existing match)" if exists else ""
                print(f"status: would CREATE{suffix}")
            else:
                suffix = " (forced re-create over an existing match)" if exists else ""
                print(f"status: WRITING{suffix}")

            if search is not None and es_error is None:
                try:
                    actual = await _live_check(search, norm)
                except Exception as exc:  # noqa: BLE001 - keep going with what we can print
                    es_error = f"{type(exc).__name__}: {exc}"
                    print(f"[WARN] Elasticsearch became unreachable during lookups: {es_error}")
                    actual = None
                if actual is not None:
                    print("actual (live cluster, right now):")
                    for key in ("lot", "ndc", "all_lots"):
                        hits = actual[key]
                        rendered = ", ".join(f"{rid} [{kind}]" for rid, kind in hits) or "(none)"
                        print(f"  recalls_by_{key}: {rendered}")
                    problems = _diff(scenario.expect_lot, actual["lot"]) + _diff(
                        scenario.expect_ndc, actual["ndc"]
                    )
                    if problems:
                        print("  MISMATCH vs expected:")
                        for problem in problems:
                            print(f"    - {problem}")

            if not args.yes:
                continue
            if exists and not args.force:
                continue
            assert store is not None and es is not None  # es_error would have short-circuited above

            scan_doc = await store.create(scenario.scan_create)
            scan_id = scan_doc[Scan.SCAN_ID]
            pipeline = ResearchPipeline(
                es,
                settings,
                search=search,
                store=store,
                web=_StubWeb(),
                agent=_StubAgent(),
                rxnav=_StubRxNav(),
                openai_client=_StubOpenAI(),
            )
            await pipeline.run(scan_id)
            backdated = _backdated_iso(index, len(scenarios))
            await store.apply(
                scan_id, patch={Scan.CREATED_AT: backdated, Scan.RECENCY_DATE: backdated}
            )
            doc = await store.get(scan_id) or {}
            research = doc.get(Scan.RESEARCH) or {}
            print(
                f"  -> scan_id={scan_id} status={doc.get(Scan.STATUS)!r} "
                f"verdict={research.get('verdict')!r}"
            )
    finally:
        if es is not None:
            await es.close()

    print()
    if not args.yes:
        print("Dry run complete. Nothing was written. Re-run with --yes once approved.")
    else:
        print("Write complete.")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
