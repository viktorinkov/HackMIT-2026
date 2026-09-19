import json
from pathlib import Path
from typing import Any

from backend.drug_facts.models import DrugFactsCard, DrugFactsResearch
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareResult, PillStatus
from backend.scans.compare import compare_channels
from backend.scans.models import BottleChannel, ImprintChannel, PillChannel, ScanReport

_DATA = Path(__file__).resolve().parent / "data"
_DEMO_CONTEXTS = _DATA / "demo-contexts.json"
_NITRO = _DATA / "demo-degradation-with-sources.json"

FIXTURE_NAMES = ("pending", "mismatch", "suspected_degradation", "nitroglycerin")


def _demo_research(
    kind: str,
    query: str,
    generic_name: str | None,
    strength: str | None,
    form: str | None,
    sources: list[str],
    warnings: list[str] | None = None,
) -> DrugFactsResearch:
    return DrugFactsResearch(
        search_kind=kind,
        query=query,
        sources_scraped=sources,
        hits=[],
        facts=DrugFactsCard(
            name=generic_name,
            generic_name=generic_name,
            strength=strength,
            warnings=warnings or [],
        ),
    )


def _bottle_from_demo(block: dict[str, Any], sources: list[str]) -> BottleChannel:
    generic = block.get("generic_name")
    strength = block.get("strength")
    form = block.get("form")
    return BottleChannel(
        observation=BottlePhotoResult(
            is_medication_container=True,
            generic_name=generic,
            strength=strength,
            form=form,
            confidence=0.9,
        ),
        research=_demo_research("bottle", generic or "", generic, strength, form, sources),
    )


def _imprint_from_demo(block: dict[str, Any], sources: list[str]) -> ImprintChannel:
    observed = block.get("observed_text")
    candidate = (block.get("candidates") or [{}])[0]
    generic = candidate.get("generic_name")
    strength = candidate.get("strength")
    form = candidate.get("form")
    return ImprintChannel(
        observation=ImprintPhotoResult(
            is_pill=True,
            imprint=observed,
            form=form,
            confidence=0.85,
        ),
        research=_demo_research("imprint", observed or "", generic, strength, form, sources),
    )


def _pill_from_demo(block: dict[str, Any], sources: list[str]) -> PillChannel:
    candidate = block.get("candidate") or {}
    generic = candidate.get("generic_name")
    form = candidate.get("form")
    degradation = (block.get("degradation") or {}).get("status")
    if degradation == "detected":
        status: PillStatus = "substandard"
    elif degradation == "suspected":
        status = "substandard"
    else:
        status = "real"
    hardware = PillHardwareResult(
        status=status,
        spectrum=[],
        pill_type=generic,
        degraded=status == "substandard",
        confidence=0.8 if status == "substandard" else 0.92,
    )
    research = None
    skipped = None
    if status in {"real", "substandard"} and generic:
        warnings = []
        if degradation in {"suspected", "detected"}:
            warnings = [f"Fixture degradation status: {degradation}"]
        research = _demo_research("pill", generic, generic, candidate.get("strength"), form, sources, warnings)
    else:
        skipped = "Hardware did not identify a pill type to research."
    return PillChannel(hardware=hardware, research=research, research_skipped_reason=skipped)


def _sources_from_demo(raw: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for source in raw.get("sources") or []:
        url = source.get("url")
        title = source.get("title")
        if url:
            urls.append(url)
        elif title:
            urls.append(title)
    return urls


def _report_from_demo(raw: dict[str, Any], scan_id: str) -> ScanReport:
    sources = _sources_from_demo(raw)
    bottle = _bottle_from_demo(raw["bottle"], sources) if raw.get("bottle") else None
    imprint = _imprint_from_demo(raw["imprint"], sources) if raw.get("imprint") else None
    pill_block = raw.get("pill") or raw.get("hardware")
    pill = _pill_from_demo(pill_block, sources) if pill_block else None
    extra_warnings: list[str] = []
    for fact in raw.get("drug_facts") or []:
        text = fact.get("text")
        if text:
            extra_warnings.append(text)
    if extra_warnings and bottle and bottle.research:
        bottle.research.facts.warnings.extend(extra_warnings)
    return ScanReport(
        scan_id=scan_id,
        status=raw.get("status") or "pending",
        demo=True,
        finding=compare_channels(bottle, imprint, pill),
        bottle=bottle,
        imprint=imprint,
        pill=pill,
    )


def load_fixture(name: str, scan_id: str) -> ScanReport:
    if name == "nitroglycerin":
        raw = json.loads(_NITRO.read_text(encoding="utf-8"))
        return _report_from_demo(raw, scan_id)
    contexts = json.loads(_DEMO_CONTEXTS.read_text(encoding="utf-8"))
    if name not in contexts:
        raise KeyError(name)
    return _report_from_demo(contexts[name], scan_id)
