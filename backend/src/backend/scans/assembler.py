from typing import Any

from backend.drug_facts.models import DrugFactsResearch
from backend.pill import PillHardwareResult
from backend.scans.models import ScanReport


def _compact_research(research: DrugFactsResearch | None) -> dict[str, Any] | None:
    if research is None:
        return None
    return {
        "search_kind": research.search_kind,
        "query": research.query,
        "facts": research.facts.model_dump(),
        "sources": research.sources_scraped,
    }


def _compact_hardware(hardware: PillHardwareResult) -> dict[str, Any]:
    data = hardware.model_dump()
    data.pop("spectrum", None)
    return data


def compact_scan_context(report: ScanReport) -> dict[str, Any]:
    bottle = None
    if report.bottle is not None:
        bottle = {
            "observation": report.bottle.observation.model_dump(),
            "research": _compact_research(report.bottle.research),
        }
    imprint = None
    if report.imprint is not None:
        imprint = {
            "observation": report.imprint.observation.model_dump(),
            "research": _compact_research(report.imprint.research),
        }
    pill = None
    if report.pill is not None:
        pill = {
            "hardware": _compact_hardware(report.pill.hardware),
            "research": _compact_research(report.pill.research),
            "research_skipped_reason": report.pill.research_skipped_reason,
        }
    return {
        "scan_id": report.scan_id,
        "status": report.status,
        "demo": report.demo,
        "finding": report.finding,
        "bottle": bottle,
        "imprint": imprint,
        "pill": pill,
    }
