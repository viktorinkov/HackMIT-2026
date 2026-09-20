from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.deepgram.models import PlaygroundPrompt
from backend.research.contract import to_scan_context

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system-prompt.txt"
PROMPT_LIMIT = 25_000


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_playground_prompt(doc: dict[str, Any]) -> PlaygroundPrompt:
    context = to_scan_context(doc)
    template = load_system_prompt()

    def render() -> str:
        scan_json = json.dumps(context, separators=(",", ":"), ensure_ascii=False)
        return template.replace("{{scan_context}}", scan_json)

    prompt = render()
    if len(prompt) > PROMPT_LIMIT:
        # Keep citations for every spoken fact, finding, mismatch, and recall.
        report = context.get("research") or {}
        cited = {
            source_id
            for item in [
                *context["drug_facts"],
                *report.get("findings", []),
                *report.get("mismatches", []),
            ]
            for source_id in item["source_ids"]
        }
        cited.update(item["id"] for item in report.get("recall_hits", []))
        cited.update(
            item.get("source_id")
            for item in (context.get("imprint") or {}).get("candidates", [])
        )
        context["sources"] = [item for item in context["sources"] if item["id"] in cited]
        prompt = render()
    if len(prompt) > PROMPT_LIMIT:
        measurements = (context.get("hardware") or {}).get("measurements")
        if measurements:
            for key, limit in (("sensor_readings", 8), ("absorbance_trace", 16)):
                values = measurements.get(key) or []
                if len(values) > limit:
                    measurements[key] = [values[round(i * (len(values) - 1) / (limit - 1))] for i in range(limit)]
            measurements["voice_samples_reduced"] = True
            prompt = render()
    if len(prompt) > PROMPT_LIMIT:
        raise ValueError(
            f"Playground prompt is {len(prompt)} characters; managed Deepgram prompts cap at {PROMPT_LIMIT}."
        )
    return PlaygroundPrompt(
        scan_id=str(doc.get("scan_id") or ""),
        prompt=prompt,
        character_count=len(prompt),
    )
