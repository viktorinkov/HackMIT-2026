from __future__ import annotations

from typing import Any

from backend.deepgram.prompt import build_playground_prompt, voice_context
from backend.reference_match import match_sentence


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


OFFER_DISAGREE = (
    "These results do not agree, so I can help you report this medicine. "
    "Do you want to?"
)
OFFER_LIGHT = "If anything about this medicine seems wrong, I can help you report it."


def scan_has_concern(doc: dict[str, Any]) -> bool:
    """True when the results disagree. Hardware `unknown` is not a concern."""
    research = doc.get("research") or {}
    if research.get("verdict") in {"mismatch_found", "recall_match"}:
        return True
    if research.get("mismatches"):
        return True
    hardware = doc.get("hardware") or {}
    return hardware.get("status") in {"fake", "substandard"}


def _source_lines(context: dict[str, Any]) -> list[str]:
    bottle = _bottle_name(context.get("bottle"))
    imprint = _imprint_name(context.get("imprint"))
    hardware = context.get("hardware")
    pill = _pill_name(hardware)
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

    match = (hardware or {}).get("reference_match") or {}
    if match.get("closest_match"):
        pill_line = match_sentence(match)
    elif pill:
        pill_line = f"Pill: the hardware analysis reports the contents as {pill}."
    elif hardware:
        if hardware.get("reported_status") == "unknown":
            pill_line = "Pill: the hardware result is unknown."
        else:
            pill_line = "Pill: the hardware analysis did not identify the contents."
    else:
        pill_line = "Pill: no hardware analysis yet."

    return [bottle_line, imprint_line, pill_line]


def intro_from_scan(doc: dict[str, Any]) -> str:
    context = voice_context(doc)
    lines = ["Hi, I'm Peel."]
    if context.get("demo"):
        lines.append("These findings are a simulated demo.")
    return " ".join(lines)


def greeting_from_scan(doc: dict[str, Any]) -> str:
    """The intro, three source lines, and the report offer, as one utterance.

    One greeting instead of three injected messages: the user can interrupt it
    at any point, and there is no InjectionRefused race while it plays.
    """
    offer = OFFER_DISAGREE if scan_has_concern(doc) else OFFER_LIGHT
    return " ".join([intro_from_scan(doc), *opening_messages_from_scan(doc), offer])


def opening_messages_from_scan(doc: dict[str, Any]) -> list[str]:
    return _source_lines(voice_context(doc))


def keyterms_from_scan(doc: dict[str, Any]) -> list[str]:
    context = voice_context(doc)
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
                        "JSON argument only, never spoken. Convert whatever "
                        "they said into YYYY-MM-DD. 'September fifteenth "
                        "twenty twenty six' becomes 2026-09-15. A month "
                        "alone becomes the first of that month. Omit if "
                        "unknown. Never ask the user for this form."
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


# Deepgram's stated accuracy sweet spot for Nova and Flux; anything higher only
# costs upload bandwidth. Output stays at Flux TTS's default 24 kHz.
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000

# Flux STT (v2): end-of-turn detection lives inside the model, which is what makes
# barge-in reliable. The thresholds are Deepgram's documented knobs; 0.75 leans
# slightly toward not cutting off a hesitant speaker, eager 0.5 buys ~150-250 ms
# of latency, and 4 s is the silence backstop so a long pause never stalls a turn.
LISTEN_MODEL = "flux-general-en"
EOT_THRESHOLD = 0.75
EAGER_EOT_THRESHOLD = 0.5
EOT_TIMEOUT_MS = 4000

# Flux TTS (v2) first for its turn lifecycle and cross-turn voice consistency;
# Brooke is one of Deepgram's healthcare-tagged voices. Aura-2 is the automatic
# fallback: Deepgram moves to the next provider on SPEAK_REQUEST_FAILED.
SPEAK_MODEL = "flux-brooke-en"
SPEAK_FALLBACK_MODEL = "aura-2-thalia-en"

# Both in Deepgram's Standard price tier. A THINK_REQUEST_FAILED warning falls
# through to the second provider instead of producing a dead turn.
THINK_MODEL = "gpt-4o-mini"
THINK_FALLBACK = ("google", "gemini-2.5-flash")
THINK_TEMPERATURE = 0.3


def build_voice_agent_settings(doc: dict[str, Any]) -> dict[str, Any]:
    prompt = build_playground_prompt(doc).prompt
    functions = [draft_report_function()]
    verdict = ((doc.get("research") or {}).get("verdict")) or "unknown"
    return {
        "type": "Settings",
        "tags": ["peel", "hackmit-2026", str(verdict)],
        "mip_opt_out": True,
        "audio": {
            "input": {"encoding": "linear16", "sample_rate": INPUT_SAMPLE_RATE},
            "output": {
                "encoding": "linear16",
                "sample_rate": OUTPUT_SAMPLE_RATE,
                "container": "none",
            },
        },
        "agent": {
            "listen": {
                "provider": {
                    "type": "deepgram",
                    "version": "v2",
                    "model": LISTEN_MODEL,
                    "keyterms": keyterms_from_scan(doc),
                    "eot_threshold": EOT_THRESHOLD,
                    "eager_eot_threshold": EAGER_EOT_THRESHOLD,
                    "eot_timeout_ms": EOT_TIMEOUT_MS,
                }
            },
            "think": [
                {
                    "provider": {
                        "type": "open_ai",
                        "model": THINK_MODEL,
                        "temperature": THINK_TEMPERATURE,
                    },
                    "prompt": prompt,
                    "functions": functions,
                },
                {
                    "provider": {
                        "type": THINK_FALLBACK[0],
                        "model": THINK_FALLBACK[1],
                        "temperature": THINK_TEMPERATURE,
                    },
                    "prompt": prompt,
                    "functions": functions,
                },
            ],
            "speak": [
                {
                    "provider": {
                        "type": "deepgram",
                        "version": "v2",
                        "model": SPEAK_MODEL,
                        "expressivity": 0,
                    }
                },
                {
                    "provider": {
                        "type": "deepgram",
                        "version": "v1",
                        "model": SPEAK_FALLBACK_MODEL,
                    }
                },
            ],
            "greeting": greeting_from_scan(doc),
        },
    }
