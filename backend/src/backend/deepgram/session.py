from __future__ import annotations

from typing import Any

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


def draft_report_function() -> dict[str, Any]:
    """Client-side function: no `endpoint`, so Deepgram sends FunctionCallRequest to
    the app instead of POSTing. The app opens the preview; Submit is a button there."""
    return {
        "name": "draft_report",
        "description": (
            "Open the report in the app, prefilled with what the user told you. "
            "The app already shows this scan, so never ask them to describe the "
            "problem and never send a scan id. Call once after the optional "
            "questions about when, where, and from whom they bought this "
            "medicine; omit any field they do not know. An empty call is valid. "
            "The user reviews and submits in the app; this call does not submit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "purchased_on": {
                    "type": "string",
                    "description": (
                        "Calendar date they bought this medicine, as YYYY-MM-DD. "
                        "An approximate day is fine. Omit if unknown."
                    ),
                },
                "purchase_location": {
                    "type": "object",
                    "description": (
                        "Where they bought it. Fill label with the place as they "
                        "said it, plus city, region, and country when they named "
                        "them. Omit if unknown."
                    ),
                    "properties": {
                        "label": {"type": "string"},
                        "city": {"type": "string"},
                        "region": {
                            "type": "string",
                            "description": "State, province, or region",
                        },
                        "country": {"type": "string"},
                    },
                },
                "seller": {
                    "type": "string",
                    "description": (
                        "Name of the person or shop they bought it from. "
                        "Omit if unknown."
                    ),
                },
            },
            "required": [],
        },
        # Wait for the confirmed end of turn: a speculative call would open the
        # preview while the user is still mid-sentence.
        "defer_until_eot": True,
    }


def build_voice_agent_settings(doc: dict[str, Any]) -> dict[str, Any]:
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
                "functions": [draft_report_function()],
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
