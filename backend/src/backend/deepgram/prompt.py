from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.deepgram.models import PlaygroundPrompt
from backend.research.contract import to_scan_context

def voice_context(doc: dict[str, Any]) -> dict[str, Any]:
    """Keep Viktor's concise handoff: classification, not a raw telemetry dump."""
    context = to_scan_context(doc)
    hardware = context.get("hardware")
    if hardware:
        hardware.pop("measurements", None)
    research = context.get("research")
    if research:
        research["findings"] = [f for f in research.get("findings", [])
                                if f.get("evidence_type") != "hardware_result"]
    return context


SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system-prompt.txt"
PROMPT_LIMIT = 25_000


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_playground_prompt(doc: dict[str, Any]) -> PlaygroundPrompt:
    scan_json = json.dumps(voice_context(doc), separators=(",", ":"), ensure_ascii=False)
    prompt = load_system_prompt().replace("{{scan_context}}", scan_json)
    if len(prompt) > PROMPT_LIMIT:
        slim = voice_context(doc)
        slim["sources"] = []
        scan_json = json.dumps(slim, separators=(",", ":"), ensure_ascii=False)
        prompt = load_system_prompt().replace("{{scan_context}}", scan_json)
    if len(prompt) > PROMPT_LIMIT:
        raise ValueError(
            f"Playground prompt is {len(prompt)} characters; managed Deepgram prompts cap at {PROMPT_LIMIT}."
        )
    return PlaygroundPrompt(
        scan_id=str(doc.get("scan_id") or ""),
        prompt=prompt,
        character_count=len(prompt),
    )
