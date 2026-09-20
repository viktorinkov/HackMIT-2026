"""The ElevenLabs `scan_context` handoff.

A stored scan holds raw `BottlePhotoResult` / `ImprintPhotoResult` /
`PillHardwareResult` shapes; the voice agent expects the status enums in
`docs/elevenlabs/demo-contexts.json`. That translation is the single most likely
silent contract break with the agent, so it lives in one pure function that is
unit-tested against the fixtures. Every field is whitelisted on the way out,
which is also what keeps prescription data off the wire.
"""

from __future__ import annotations

import json
from typing import Any

from backend.knowledge import normalize

BOTTLE_STATUSES = ("read", "unreadable", "not_a_container")
IMPRINT_STATUSES = ("candidate_found", "no_candidate", "unreadable", "not_a_pill")
HARDWARE_STATUSES = ("candidate_found", "inconclusive")
DEGRADATION_STATUSES = ("not_assessed", "inconclusive", "suspected", "detected")

# Below this, the label was photographed but not actually read.
MIN_READABLE_CONFIDENCE = 0.3
_IDENTIFIED_STATUSES = ("real", "substandard", "fake")
_DEGRADATION_EVIDENCE = {
    "suspected": "The hardware analysis reported a substandard quality reading.",
    "detected": "The hardware analysis reported degradation.",
}


def to_scan_context(scan_doc: dict[str, Any]) -> dict[str, Any]:
    """Build the handoff object. Pure: no clock, no settings, no I/O."""
    research = scan_doc.get("research") or {}
    evidence = scan_doc.get("evidence") or {}
    norm = scan_doc.get("norm") or {}
    context: dict[str, Any] = {
        "scan_id": scan_doc.get("scan_id"),
        "revision": int(scan_doc.get("revision") or 1),
        "demo": bool(scan_doc.get("demo") or research.get("demo")),
        "status": scan_doc.get("status") or "pending",
        "bottle": _bottle(scan_doc.get("bottle")),
        "imprint": _imprint(scan_doc.get("imprint"), evidence),
        "hardware": _hardware(scan_doc.get("hardware"), norm),
        "drug_facts": _drug_facts(research),
        "sources": _sources(research.get("sources") or []),
    }
    if research:
        context["research"] = _research(research)
    return context


def scan_context_json(scan_doc: dict[str, Any]) -> str:
    """ElevenLabs dynamic variables must be strings, so the report ships serialized."""
    return json.dumps(
        to_scan_context(scan_doc), separators=(",", ":"), ensure_ascii=False
    )


def _bottle(bottle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bottle:
        return None
    return {
        "status": _bottle_status(bottle),
        "generic_name": bottle.get("generic_name"),
        "brand_name": bottle.get("brand_name"),
        "strength": bottle.get("strength"),
        "form": bottle.get("form"),
        "expiration": bottle.get("expiration"),
        "lot_number": bottle.get("lot_number"),
        "manufacturer": bottle.get("manufacturer"),
        "ndc": bottle.get("ndc"),
        "confidence": bottle.get("confidence"),
    }


def _bottle_status(bottle: dict[str, Any]) -> str:
    if not bottle.get("is_medication_container"):
        return "not_a_container"
    identified = any(
        bottle.get(key)
        for key in ("generic_name", "brand_name", "strength", "ndc", "lot_number")
    )
    confidence = bottle.get("confidence")
    unreadable = confidence is not None and float(confidence) < MIN_READABLE_CONFIDENCE
    return "unreadable" if unreadable or not identified else "read"


def _imprint(
    imprint: dict[str, Any] | None, evidence: dict[str, Any]
) -> dict[str, Any] | None:
    candidates = [
        _candidate(item)
        for item in (evidence.get("pill_candidates") or [])
        if isinstance(item, dict)
    ]
    if not imprint and not candidates:
        return None
    observed = (imprint or {}).get("imprint")
    if candidates:
        status = "candidate_found"
    elif imprint and not imprint.get("is_pill"):
        status = "not_a_pill"
    elif observed:
        status = "no_candidate"
    else:
        status = "unreadable"
    return {"status": status, "observed_text": observed, "candidates": candidates}


def _candidate(item: dict[str, Any]) -> dict[str, Any]:
    candidate = {
        "generic_name": item.get("generic_name"),
        "strength": item.get("strength"),
        "form": item.get("form"),
        "source_id": item.get("source_id"),
    }
    if item.get("medication_id"):
        candidate["medication_id"] = item["medication_id"]
    return candidate


def _hardware(
    hardware: dict[str, Any] | None, norm: dict[str, Any]
) -> dict[str, Any] | None:
    if not hardware:
        return None
    pill_type = hardware.get("pill_type")
    identified = hardware.get("status") in _IDENTIFIED_STATUSES and bool(pill_type)
    candidate = None
    if identified:
        candidate = {
            "generic_name": normalize.normalize_drug_name(pill_type) or pill_type,
            # The device measures identity, never dose: strength stays null.
            "strength": None,
            "form": norm.get("dosage_form"),
        }
    return {
        "status": "candidate_found" if identified else "inconclusive",
        # The device's own classification (real | substandard | fake | unknown). Without
        # it a "fake" reading with no identified pill type would read as merely inconclusive.
        "reported_status": hardware.get("status"),
        "candidate": candidate,
        "degradation": _degradation(hardware),
        "limitations": _as_list(hardware.get("limitations")),
        "model": hardware.get("model"),
    }


def _degradation(hardware: dict[str, Any]) -> dict[str, Any]:
    status = hardware.get("status")
    if status == "substandard":
        # Checked before `degraded` on purpose: the mock raises that flag for every
        # substandard reading, and a quality suspicion is not a measured degradation.
        state = "suspected"
    elif hardware.get("degraded"):
        state = "detected"
    elif status == "unknown":
        state = "inconclusive"
    else:
        state = "not_assessed"
    degradation: dict[str, Any] = {"status": state}
    if state in _DEGRADATION_EVIDENCE:
        degradation["evidence"] = [_DEGRADATION_EVIDENCE[state]]
        # Never invented; the device reports no potency number.
        degradation["remaining_potency"] = None
    return degradation


def _drug_facts(research: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "medication_id": fact.get("medication_id"),
            "topic": fact.get("topic"),
            "text": fact.get("text"),
            "source_ids": list(fact.get("source_ids") or []),
        }
        for fact in (research.get("drug_facts") or [])
        if isinstance(fact, dict)
    ]


def _sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = {
            "id": item.get("id"),
            "title": item.get("title"),
            "url": item.get("url"),
        }
        for key in ("source_org", "label_date", "published_at"):
            if item.get(key):
                source[key] = item[key]
        sources.append(source)
    return sources


def _research(research: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": research.get("verdict"),
        "risk_level": research.get("risk_level"),
        "headline": research.get("headline"),
        "findings": [
            {
                "statement": finding.get("statement"),
                "evidence_type": finding.get("evidence_type"),
                "severity": finding.get("severity"),
                "country_scope": finding.get("country_scope"),
                "source_ids": list(finding.get("source_ids") or []),
            }
            for finding in (research.get("findings") or [])
            if isinstance(finding, dict)
        ],
        "mismatches": [
            {
                "field": mismatch.get("field"),
                "bottle_claim": mismatch.get("bottle_claim"),
                "imprint_reference": mismatch.get("imprint_reference"),
                "hardware_report": mismatch.get("hardware_report"),
                "explanation": mismatch.get("explanation"),
                "source_ids": list(mismatch.get("source_ids") or []),
            }
            for mismatch in (research.get("mismatches") or [])
            if isinstance(mismatch, dict)
        ],
        "recall_hits": _sources(research.get("recall_hits") or []),
        "gaps": [str(gap) for gap in (research.get("gaps") or [])],
        "next_steps": [str(step) for step in (research.get("next_steps") or [])],
        "agent_used": bool(research.get("agent_used")),
        "demo": bool(research.get("demo")),
    }


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return [str(value)]
