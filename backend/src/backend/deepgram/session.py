from typing import Any

from backend.config import Settings
from backend.scans.compare import pair_mismatches
from backend.scans.models import ScanReport
from backend.deepgram.prompt import build_playground_prompt


def _named(name: str | None, strength: str | None) -> str | None:
    cleaned = " ".join(part for part in (name, strength) if part).strip()
    return cleaned or None


def _bottle_name(report: ScanReport) -> str | None:
    if report.bottle is None:
        return None
    return _named(
        report.bottle.observation.generic_name or report.bottle.observation.brand_name,
        report.bottle.observation.strength,
    )


def _imprint_name(report: ScanReport) -> str | None:
    if report.imprint is None or report.imprint.research is None:
        return None
    return _named(
        report.imprint.research.facts.generic_name or report.imprint.research.facts.name,
        report.imprint.research.facts.strength,
    )


def _pill_name(report: ScanReport) -> str | None:
    if report.pill is None:
        return None
    pill_name = report.pill.hardware.pill_type
    strength = None
    if report.pill.research is not None:
        pill_name = (
            report.pill.research.facts.generic_name
            or report.pill.research.facts.name
            or pill_name
        )
        strength = report.pill.research.facts.strength
    return _named(pill_name, strength)


def _conflict_line(report: ScanReport) -> str:
    bottle_imprint, bottle_pill, imprint_pill = pair_mismatches(
        report.bottle, report.imprint, report.pill
    )
    aside = (
        "so set this pill aside and ask a pharmacist to check it with the bottle."
    )
    if bottle_imprint and bottle_pill and imprint_pill:
        return (
            "The bottle label, imprint lookup, and hardware analysis all name "
            f"different medications, {aside}"
        )
    if bottle_imprint and bottle_pill:
        return (
            "The bottle label disagrees with the imprint lookup and the hardware "
            f"analysis, {aside}"
        )
    if bottle_pill and imprint_pill:
        return (
            "The hardware analysis disagrees with the bottle label and the imprint "
            f"lookup, {aside}"
        )
    if bottle_imprint and imprint_pill:
        return (
            "The imprint lookup disagrees with the bottle label and the hardware "
            f"analysis, {aside}"
        )
    return f"Those three results do not match, {aside}"


def greeting_from_scan(report: ScanReport) -> str:
    lines = ["Hi, I'm Peel."]
    if report.demo:
        lines.append("These findings are a simulated demo.")

    bottle = _bottle_name(report)
    imprint = _imprint_name(report)
    pill = _pill_name(report)

    if bottle:
        lines.append(f"Bottle: the label says {bottle}.")
    else:
        lines.append("Bottle: no label result yet.")

    if imprint:
        lines.append(f"Imprint: the marking lookup returned {imprint}.")
    elif report.imprint is not None and report.imprint.observation.imprint:
        lines.append(
            f"Imprint: the marking is {report.imprint.observation.imprint}, with no drug name yet."
        )
    else:
        lines.append("Imprint: no marking lookup yet.")

    if pill:
        lines.append(f"Pill: the hardware analysis reports the contents as {pill}.")
    else:
        lines.append("Pill: no hardware analysis yet.")

    if report.finding == "conflict":
        lines.append(_conflict_line(report))
    elif report.finding == "quality_concern":
        lines.append(
            "The names agree, but the hardware analysis flagged the contents as off. Set this pill aside and ask a pharmacist to check it."
        )
    elif report.finding == "agree":
        lines.append("Those three results name the same medication. That is not a safety guarantee.")
    elif report.finding == "inconclusive":
        lines.append("There is not enough agreeing evidence yet to call this a match or a mismatch.")
    else:
        lines.append("I can walk you through this pill check once the scan is ready.")
    return " ".join(lines)


def keyterms_from_scan(report: ScanReport) -> list[str]:
    terms: list[str] = []

    def add(value: str | None) -> None:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in terms:
            terms.append(cleaned)

    if report.bottle is not None:
        add(report.bottle.observation.brand_name)
        add(report.bottle.observation.generic_name)
        add(report.bottle.observation.strength)
        add(report.bottle.observation.imprint_on_label)
        if report.bottle.research is not None:
            add(report.bottle.research.facts.name)
            add(report.bottle.research.facts.generic_name)
            add(report.bottle.research.facts.expected_imprint)
    if report.imprint is not None:
        add(report.imprint.observation.imprint)
        if report.imprint.research is not None:
            add(report.imprint.research.facts.name)
            add(report.imprint.research.facts.generic_name)
            add(report.imprint.research.facts.expected_imprint)
    if report.pill is not None:
        add(report.pill.hardware.pill_type)
        if report.pill.research is not None:
            add(report.pill.research.facts.name)
            add(report.pill.research.facts.generic_name)
    return terms


def reports_url(settings: Settings, scan_id: str) -> str:
    return f"{settings.public_api_base_url.rstrip('/')}/scans/{scan_id}/reports"


def draft_concern_report_function(url: str) -> dict[str, Any]:
    return {
        "name": "draft_concern_report",
        "description": (
            "Call this to save a concern report for the current scan after the "
            "user confirms they want to report."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "concern_type": {"type": "string"},
                "summary": {"type": "string"},
                "user_description": {"type": "string"},
                "symptoms": {"type": "string"},
            },
            "required": ["concern_type", "summary", "user_description"],
        },
        "defer_until_eot": True,
        "endpoint": {
            "url": url,
            "method": "post",
        },
    }


def build_voice_agent_settings(report: ScanReport, settings: Settings) -> dict[str, Any]:
    prompt = build_playground_prompt(report).prompt
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
                    "keyterms": keyterms_from_scan(report),
                }
            },
            "think": {
                "provider": {
                    "type": "open_ai",
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                },
                "prompt": prompt,
                "functions": [draft_concern_report_function(reports_url(settings, report.scan_id))],
            },
            "speak": {
                "provider": {
                    "type": "deepgram",
                    "model": "aura-2-thalia-en",
                }
            },
            "greeting": greeting_from_scan(report),
        },
    }
