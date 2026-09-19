from typing import Any

from backend.config import Settings
from backend.scans.models import ScanReport
from backend.scans.prompt import build_playground_prompt

GREETING = "Hi, I'm Peel. I can walk you through this pill check."


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
            "greeting": GREETING,
        },
    }
