from __future__ import annotations

from backend.deepgram.prompt import PROMPT_LIMIT, build_playground_prompt
from tests.deepgram.conftest import complete_scan


def test_prompt_embeds_the_scan_context() -> None:
    prompt = build_playground_prompt(complete_scan())
    assert prompt.scan_id == "scan-1"
    assert '"scan_id":"scan-1"' in prompt.prompt
    assert "acetaminophen" in prompt.prompt
    assert "three separate messages" in prompt.prompt
    assert "Do not add a fourth opening line" in prompt.prompt
    assert "backend already fills the problem" in prompt.prompt
    assert prompt.character_count == len(prompt.prompt)
    assert prompt.character_count < PROMPT_LIMIT


def test_prompt_drops_sources_when_it_exceeds_the_cap() -> None:
    doc = complete_scan(
        research={
            "verdict": "mismatch_found",
            "risk_level": "medium",
            "headline": "The label and the reference records do not agree.",
            "sources": [
                {
                    "id": f"src-{index}",
                    "title": "x" * 800,
                    "url": f"https://example.test/{index}",
                }
                for index in range(40)
            ],
        }
    )
    prompt = build_playground_prompt(doc)
    assert prompt.character_count < PROMPT_LIMIT
    assert '"sources":[]' in prompt.prompt
    assert "example.test" not in prompt.prompt
