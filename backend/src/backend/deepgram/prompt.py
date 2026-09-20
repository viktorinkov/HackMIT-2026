from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.deepgram.models import PlaygroundPrompt
from backend.research.contract import scan_context_json, to_scan_context

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system-prompt.txt"
PROMPT_LIMIT = 25_000


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_playground_prompt(doc: dict[str, Any]) -> PlaygroundPrompt:
    scan_json = scan_context_json(doc)
    prompt = load_system_prompt().replace("{{scan_context}}", scan_json)
    if len(prompt) > PROMPT_LIMIT:
        slim = to_scan_context(doc)
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
