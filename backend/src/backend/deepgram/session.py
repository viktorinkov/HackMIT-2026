from __future__ import annotations

from typing import Any

from backend.config import Settings
from backend.deepgram.lead import lead_from_context
from backend.deepgram.models import ConcernReportCreate
from backend.deepgram.prompt import build_playground_prompt
from backend.research.contract import to_scan_context


def _named(name: str | None, strength: str | None) -> str | None:
    cleaned = " ".join(part for part in (name, strength) if part).strip()
    return cleaned or None


def _bottle_name(bottle: dict[str, Any] | None) -> str | None:
    if not bottle:
        return None
    return _named(bottle.get("generic_name") or bottle.get("brand_name"), bottle.get("strength"))


def _imprint_name(imprint: dict[str, Any] | None) -> str | None:
    if not imprint:
        return None
    candidates = imprint.get("candidates") or []
    if not candidates:
        return None
    first = candidates[0]
    return _named(first.get("generic_name"), first.get("strength"))


def _pill_name(hardware: dict[str, Any] | None) -> str | None:
    if not hardware:
        return None
    candidate = hardware.get("candidate")
    if not candidate:
        return None
    return _named(candidate.get("generic_name"), None)


def _source_lines(context: dict[str, Any]) -> list[str]:
    bottle = _bottle_name(context.get("bottle"))
    imprint = _imprint_name(context.get("imprint"))
    pill = _pill_name(context.get("hardware"))
    observed = (context.get("imprint") or {}).get("observed_text") if context.get("imprint") else None

    if bottle:
        bottle_line = f"Bottle: the label says {bottle}."
    else:
        bottle_line = "Bottle: no label result yet."

    if imprint:
        imprint_line = f"Imprint: the marking lookup returned {imprint}."
    elif observed:
        imprint_line = f"Imprint: the marking is {observed}, with no drug name yet."
    else:
        imprint_line = "Imprint: no marking lookup yet."

    if pill:
        pill_line = f"Pill: the hardware analysis reports the contents as {pill}."
    else:
        pill_line = "Pill: no hardware analysis yet."

    return [bottle_line, imprint_line, pill_line]


def greeting_from_scan(doc: dict[str, Any]) -> str:
    context = to_scan_context(doc)
    lines = ["Hi, I'm Peel."]
    if context.get("demo"):
        lines.append("These findings are a simulated demo.")
    return " ".join(lines)


def opening_messages_from_scan(doc: dict[str, Any]) -> list[str]:
    return _source_lines(to_scan_context(doc))


def _clean_report_field(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def concern_type_from_context(context: dict[str, Any]) -> str:
    hardware = context.get("hardware") or {}
    research = context.get("research") or {}
    if hardware.get("reported_status") == "fake":
        return "fake"
    if research.get("verdict") == "recall_match":
        return "recall"
    degradation = (hardware.get("degradation") or {}).get("status")
    if degradation in {"suspected", "detected"} or hardware.get("reported_status") == "substandard":
        return "quality"
    if research.get("verdict") == "mismatch_found":
        return "mismatch"
    if research.get("verdict") == "insufficient_evidence":
        return "uncertain"
    return "other"


def problem_from_scan(doc: dict[str, Any]) -> str:
    context = to_scan_context(doc)
    parts = list(_source_lines(context))
    lead = lead_from_context(context)
    if lead:
        parts.append(lead)
    return " ".join(parts)


def fill_concern_report(doc: dict[str, Any], body: ConcernReportCreate) -> ConcernReportCreate:
    context = to_scan_context(doc)
    return ConcernReportCreate(
        concern_type=_clean_report_field(body.concern_type) or concern_type_from_context(context),
        summary=_clean_report_field(body.summary) or lead_from_context(context) or "Scan concern",
        user_description=_clean_report_field(body.user_description) or problem_from_scan(doc),
        symptoms=_clean_report_field(body.symptoms),
    )


def keyterms_from_scan(doc: dict[str, Any]) -> list[str]:
    context = to_scan_context(doc)
    terms: list[str] = []

    def add(value: str | None) -> None:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in terms:
            terms.append(cleaned)

    bottle = context.get("bottle") or {}
    add(bottle.get("brand_name"))
    add(bottle.get("generic_name"))
    add(bottle.get("strength"))
    imprint = context.get("imprint") or {}
    add(imprint.get("observed_text"))
    for candidate in imprint.get("candidates") or []:
        add(candidate.get("generic_name"))
        add(candidate.get("strength"))
    hardware = context.get("hardware") or {}
    candidate = hardware.get("candidate") or {}
    add(candidate.get("generic_name"))
    return terms


def reports_url(settings: Settings, scan_id: str) -> str:
    return f"{settings.public_api_base_url.rstrip('/')}/deepgram/{scan_id}/reports"


def draft_concern_report_function(url: str) -> dict[str, Any]:
    return {
        "name": "draft_concern_report",
        "description": (
            "Save a concern report for the current scan after the user confirms "
            "they want to file. The problem is already filled from this scan. "
            "Do not ask the user to describe it. Call with no arguments unless "
            "the user volunteered symptoms."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "concern_type": {"type": "string"},
                "summary": {"type": "string"},
                "user_description": {"type": "string"},
                "symptoms": {"type": "string"},
            },
            "required": [],
        },
        "defer_until_eot": True,
        "endpoint": {
            "url": url,
            "method": "post",
        },
    }


def build_voice_agent_settings(doc: dict[str, Any], settings: Settings) -> dict[str, Any]:
    scan_id = str(doc.get("scan_id") or "")
    prompt = build_playground_prompt(doc).prompt
    return {
        "type": "Settings",
        "mip_opt_out": True,
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": 24000},
            "output": {"encoding": "linear16", "sample_rate": 24000, "container": "none"},
        },
        "agent": {
            "listen": {
                "provider": {
                    "type": "deepgram",
                    "model": "nova-3",
                    "smart_format": True,
                    "keyterms": keyterms_from_scan(doc),
                }
            },
            "think": {
                "provider": {
                    "type": "open_ai",
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                },
                "prompt": prompt,
                "functions": [draft_concern_report_function(reports_url(settings, scan_id))],
            },
            "speak": {
                "provider": {
                    "type": "deepgram",
                    "model": "aura-2-thalia-en",
                }
            },
            "greeting": greeting_from_scan(doc),
        },
    }
