import json
from pathlib import Path

from backend.scans.assembler import compact_scan_context
from backend.scans.models import PlaygroundPrompt, ScanReport

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "data" / "system-prompt.txt"
PROMPT_LIMIT = 25_000


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_playground_prompt(report: ScanReport) -> PlaygroundPrompt:
    context = compact_scan_context(report)
    scan_json = json.dumps(context, separators=(",", ":"), default=str)
    prompt = load_system_prompt().replace("{{scan_context}}", scan_json)
    if "revision" in prompt:
        prompt = prompt.replace(
            "Use the latest app-provided context for the active scan_id and revision.",
            "Use the latest app-provided context for the active scan_id.",
        )
    if len(prompt) > PROMPT_LIMIT:
        raise ValueError(
            f"Playground prompt is {len(prompt)} characters; managed Deepgram prompts cap at {PROMPT_LIMIT}."
        )
    return PlaygroundPrompt(
        scan_id=report.scan_id,
        prompt=prompt,
        character_count=len(prompt),
    )
