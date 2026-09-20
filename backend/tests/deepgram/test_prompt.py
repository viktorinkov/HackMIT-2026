from __future__ import annotations

from backend.deepgram.prompt import PROMPT_LIMIT, build_playground_prompt
from tests.deepgram.conftest import complete_scan


def test_prompt_embeds_the_scan_context() -> None:
    prompt = build_playground_prompt(complete_scan())
    assert prompt.scan_id == "scan-1"
    assert '"scan_id":"scan-1"' in prompt.prompt
    assert "acetaminophen" in prompt.prompt
    # The greeting carries the three sources now; the prompt must say so and
    # must tell Peel how to behave when the user interrupts.
    assert "Your greeting already introduced you" in prompt.prompt
    assert "offered the user report" in prompt.prompt
    assert "Answer questions from the scan context in one or two sentences" in prompt.prompt
    assert "Report button is in the app" in prompt.prompt
    assert "Do not add an opening line" in prompt.prompt
    assert "The user can interrupt you at any time" in prompt.prompt
    assert "Do not restart or finish the summary" in prompt.prompt
    assert "One moment, I'll open the report" in prompt.prompt
    assert "call draft_report once" in prompt.prompt
    assert "Never say it was submitted" in prompt.prompt
    assert "March twelfth, twenty twenty-six" in prompt.prompt
    assert "When did you buy this?" in prompt.prompt
    assert "Do not mention slashes, hyphens, month-day-year, or any required form" in prompt.prompt
    assert "Do not mention a format" in prompt.prompt
    assert "Silently convert the purchase day on that call" in prompt.prompt
    assert "YYYY-MM-DD" not in prompt.prompt
    assert "yy/mm/dd" not in prompt.prompt
    assert "seller or shop" in prompt.prompt
    assert "concern report" not in prompt.prompt
    assert "fills the problem" not in prompt.prompt
    assert "draft_concern_report" not in prompt.prompt
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
