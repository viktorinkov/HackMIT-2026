from __future__ import annotations

from backend.deepgram.session import (
    build_voice_agent_settings,
    draft_report_function,
    greeting_from_scan,
    keyterms_from_scan,
    opening_messages_from_scan,
)
from tests.deepgram.conftest import complete_scan


def test_greeting_is_only_the_intro() -> None:
    assert greeting_from_scan(complete_scan()) == (
        "Hi, I'm Peel. These findings are a simulated demo."
    )
    assert greeting_from_scan(complete_scan(demo=False)) == "Hi, I'm Peel."


def test_opening_messages_are_exactly_the_three_sources() -> None:
    messages = opening_messages_from_scan(complete_scan())
    assert messages == [
        "Bottle: the label says acetaminophen 500 mg.",
        "Imprint: the marking lookup returned ibuprofen 200 mg.",
        "Pill: the hardware analysis reports the contents as ibuprofen.",
    ]


def test_opening_uses_observed_imprint_when_there_is_no_candidate() -> None:
    messages = opening_messages_from_scan(complete_scan(evidence={"pill_candidates": []}))
    assert messages[1] == "Imprint: the marking is L484, with no drug name yet."


def test_opening_does_not_include_the_headline_or_a_fake_line() -> None:
    # The prompt leads with fake/recall/headline; the opening is only the three sources.
    doc = complete_scan()
    doc["hardware"] = {**doc["hardware"], "status": "fake"}
    messages = opening_messages_from_scan(doc)
    assert len(messages) == 3
    assert not any("fake" in message.lower() for message in messages)
    assert "The label and the reference records do not agree." not in messages


def test_opening_does_not_include_a_recall_line() -> None:
    messages = opening_messages_from_scan(
        complete_scan(
            research={
                "verdict": "recall_match",
                "risk_level": "high",
                "headline": "The label and the reference records do not agree.",
            }
        )
    )
    assert len(messages) == 3
    assert not any("recall" in message.lower() for message in messages)


def test_keyterms_include_names_and_the_imprint_marking() -> None:
    terms = keyterms_from_scan(complete_scan())
    assert "Tylenol" in terms
    assert "acetaminophen" in terms
    assert "500 mg" in terms
    assert "L484" in terms
    assert "ibuprofen" in terms
    assert "200 mg" in terms


def test_draft_report_is_a_client_side_function() -> None:
    function = draft_report_function()
    assert function["name"] == "draft_report"
    # No endpoint: Deepgram sends FunctionCallRequest to the app instead of POSTing.
    assert "endpoint" not in function
    # Deferred so a speculative call cannot open the preview mid-sentence.
    assert function["defer_until_eot"] is True
    assert function["parameters"]["required"] == []
    assert set(function["parameters"]["properties"]) == {
        "purchased_on",
        "purchase_location",
        "seller",
    }
    assert "scan_id" not in function["parameters"]["properties"]
    assert "does not submit" in function["description"]


def test_voice_settings_include_the_greeting_the_prompt_and_the_draft_tool() -> None:
    payload = build_voice_agent_settings(complete_scan())
    assert payload["type"] == "Settings"
    assert payload["agent"]["greeting"] == "Hi, I'm Peel. These findings are a simulated demo."
    assert "acetaminophen" in payload["agent"]["think"]["prompt"]
    assert payload["agent"]["think"]["functions"] == [draft_report_function()]
