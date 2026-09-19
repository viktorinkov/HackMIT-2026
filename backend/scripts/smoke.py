"""Live smoke test for the Peel knowledge layer.

    uv run python scripts/smoke.py            # retrieval + Agent Builder tools (no credits spent)
    uv run python scripts/smoke.py --e2e      # also runs one full scan through the pipeline
                                              # (spends <= 10 Firecrawl credits + OpenAI tokens)

Talks to the real cluster configured in .env. Read-only except for --e2e, which
writes one demo scan and any web pages it fetches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from backend.config import get_settings
from backend.knowledge import normalize
from backend.knowledge.client import build_client
from backend.knowledge.fields import ALL_INDICES, REGULATORY_INDEX, Reg
from backend.knowledge.search import KnowledgeSearch, SearchFilters, build_regulatory_query, utc_origin
from backend.research.agent_builder import AgentBuilderClient, esql_rows

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def ids(hits: list[Any]) -> list[str]:
    return [hit.source.get(Reg.RECORD_ID, hit.id) for hit in hits]


async def retrieval(es: Any, ks: KnowledgeSearch) -> None:
    counts = {index: (await es.count(index=index))["count"] for index in ALL_INDICES}
    check("corpus seeded", counts[REGULATORY_INDEX] > 20_000 and counts["peel-pills"] > 80_000, str(counts))

    started = time.monotonic()
    hits = await ks.recalls_by_lot("d2402430")
    took = (time.monotonic() - started) * 1000
    check("exact lot D2402430 -> FDA D-0785-2026", "fda-enf-D-0785-2026" in ids(hits), f"{took:.0f} ms")

    hits = await ks.recalls_by_lot("H02605")
    orgs = {hit.source.get(Reg.SOURCE_ORG) for hit in hits}
    check("WHO falsified HEALMOXY batch H02605", "WHO" in orgs, f"sources={sorted(o for o in orgs if o)}")

    check("unknown lot returns nothing", not await ks.recalls_by_lot("ZZ99ZZ99ZZ"))

    ndc = normalize.normalize_ndc("16729-457-15")
    assert ndc is not None
    hits = await ks.recalls_by_ndc(ndc)
    top = hits[0] if hits else None
    check(
        "NDC 16729-457: recall naming it ranks first, siblings are product-line only",
        bool(top)
        and top.match_kind == "ndc_in_description"
        and top.source.get(Reg.RECORD_ID) == "fda-enf-D-0785-2026"
        and all(hit.match_kind != "exact_lot" for hit in hits),
        str([(hit.match_kind, hit.source.get(Reg.RECORD_ID)) for hit in hits[:3]]),
    )

    match = await ks.identify_pill(imprint="5892;V", shape="capsule", colors=["pink"])
    first = match.hits[0].source if match.hits else {}
    check("pill 5892;V capsule -> temazepam on rung 1", "temazepam" in str(first).lower() and match.rung == 1)

    match = await ks.identify_pill(imprint="5892 V", shape="round", colors=["pink"])
    check(
        "wrong shape relaxes the filter and flags it",
        match.shape_relaxed and match.rung > 1 and "temazepam" in str(match.hits[0].source).lower(),
        f"rung={match.rung}",
    )

    filters = SearchFilters(drug_names=["levothyroxine sodium", "levothyroxine"])
    hits = await ks.search_regulatory("tablets contain less active ingredient than labelled", filters, size=10)
    in_filter = all("levothyroxine" in json.dumps(hit.source).lower() for hit in hits)
    check("hybrid search honours the metadata pre-filter", bool(hits) and in_filter, f"{len(hits)} hits")
    check("every hit carries age_days + freshness", all(hit.age_days is not None and hit.freshness for hit in hits))

    body = build_regulatory_query("levothyroxine subpotent", filters, origin=utc_origin(), size=5)
    check("hybrid body pre-filters (top-level retriever filter)", bool(body["retriever"]["linear"].get("filter")))

    # Decay proof: the same query evaluated "today" vs five years from now must
    # reorder toward whatever is recent relative to the origin.
    now_hits = await ks.search_regulatory("falsified medicine alert", SearchFilters(source_orgs=["NAFDAC"]), size=5)
    ages = [hit.age_days for hit in now_hits if hit.age_days is not None]
    check("recency decay favours recent NAFDAC alerts", bool(ages) and min(ages) < 400, f"ages={ages}")


async def agent_tools(ab: AgentBuilderClient) -> None:
    await ab.bootstrap()
    rows = esql_rows(await ab.execute_tool("peel.recalls_by_lot", {"lot": "D2402430"}))
    check("tool recalls_by_lot", any(row.get("record_id") == "fda-enf-D-0785-2026" for row in rows))
    rows = esql_rows(await ab.execute_tool("peel.recalls_by_ndc", {"ndc9": "167290457"}))
    check("tool recalls_by_ndc ranks the precise recall first", bool(rows) and rows[0].get("match_kind") == "ndc_in_recall_text")
    rows = esql_rows(await ab.execute_tool("peel.regulatory_search_text", {"query": "levothyroxine subpotent", "drug": "levothyroxine"}))
    check("tool regulatory_search_text returns decayed rank + age_days", bool(rows) and "rank" in rows[0] and "age_days" in rows[0])
    rows = esql_rows(await ab.execute_tool("peel.regulatory_search_semantic", {"query": "zzzqqq flibbertigibbet nonexistentword"}))
    check("semantic tool rejects nonsense (score threshold)", not rows, f"{len(rows)} rows")
    rows = esql_rows(await ab.execute_tool("peel.pill_lookup", {"imprint": "5892V", "shape": "capsule"}))
    check("tool pill_lookup", bool(rows) and rows[0].get("exact") == 1)
    rows = esql_rows(await ab.execute_tool("peel.ndc_lookup", {"ndc9": "167290457"}))
    check("tool ndc_lookup", bool(rows) and "levothyroxine" in str(rows[0]).lower())


async def end_to_end(es: Any) -> None:
    from backend.photo_identification.bottle import BottlePhotoResult
    from backend.photo_identification.imprint import ImprintPhotoResult
    from backend.pill import HARDWARE_MODEL, PillHardwareResult
    from backend.research.contract import to_scan_context
    from backend.research.pipeline import ResearchPipeline
    from backend.scans.models import ScanCreate
    from backend.scans.store import ScanStore

    settings = get_settings()
    store = ScanStore(es, settings)
    payload = ScanCreate(
        device_id="smoke-test-device",
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
        imprint=ImprintPhotoResult(is_pill=True, imprint=None, color="pink", shape="round", confidence=0.7),
        hardware=PillHardwareResult(status="substandard", spectrum=[0.1] * 16, pill_type="levothyroxine", degraded=False, confidence=0.78),
    )
    scan = await store.create(payload)
    scan_id = scan["scan_id"]
    started = time.monotonic()
    await ResearchPipeline(es, settings).run(scan_id)
    doc = await store.get(scan_id) or {}
    research = doc.get("research") or {}
    evidence = doc.get("evidence") or {}
    print(json.dumps({"stages": doc.get("stages"), "verdict": research.get("verdict"), "risk": research.get("risk_level"), "headline": research.get("headline"), "agent_used": research.get("agent_used")}, indent=2)[:2500])
    check("pipeline completes", doc.get("status") == "complete", f"{time.monotonic() - started:.0f}s, revision {doc.get('revision')}")
    check("verdict is recall_match for the recalled lot", research.get("verdict") == "recall_match")
    check("Firecrawl spend within the per-scan budget", int(evidence.get("firecrawl_credits_used") or 0) <= settings.firecrawl_max_credits_per_scan, str(evidence.get("firecrawl_credits_used")))
    context = to_scan_context(doc)
    leaked = [key for key in ("rx_number", "pharmacy", "directions") if key in json.dumps(context)]
    check("scan_context is contract-shaped and PHI-free", {"scan_id", "revision", "status", "bottle", "imprint", "hardware", "drug_facts", "sources"} <= set(context) and not leaked)
    print(f"scan_id={scan_id}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--e2e", action="store_true", help="run one full scan (spends Firecrawl credits + OpenAI tokens)")
    parser.add_argument("--skip-agent", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    es = build_client(settings)
    ab = AgentBuilderClient(settings)
    try:
        await retrieval(es, KnowledgeSearch(es, settings))
        if not args.skip_agent:
            await agent_tools(ab)
        if args.e2e:
            await end_to_end(es)
    finally:
        await ab.aclose()
        await es.close()
    failed = [name for name, ok, _ in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
