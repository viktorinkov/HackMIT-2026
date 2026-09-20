from __future__ import annotations

from backend.config import Settings
from backend.deepgram.lead import FAKE_LEAD, RECALL_LEAD
from backend.deepgram.session import (
    build_voice_agent_settings,
    greeting_from_scan,
    keyterms_from_scan,
    reports_url,
)
from tests.deepgram.conftest import complete_scan


def test_greeting_states_the_three_sources_then_the_lead() -> None:
    greeting = greeting_from_scan(complete_scan())
    assert greeting.startswith("Hi, I'm Peel.")
    assert "These findings are a simulated demo." in greeting
    assert "Bottle: the label says acetaminophen 500 mg." in greeting
    assert "Imprint: the marking lookup returned ibuprofen 200 mg." in greeting
    assert "Pill: the hardware analysis reports the contents as ibuprofen." in greeting
    assert "The label and the reference records do not agree." in greeting
    assert "agreeing evidence" not in greeting
    assert "Those three results" not in greeting


def test_greeting_uses_observed_imprint_when_there_is_no_candidate() -> None:
    greeting = greeting_from_scan(complete_scan(evidence={"pill_candidates": []}))
    assert "Imprint: the marking is L484, with no drug name yet." in greeting


def test_greeting_leads_with_fake_instead_of_the_headline() -> None:
    doc = complete_scan()
    doc["hardware"] = {**doc["hardware"], "status": "fake"}
    greeting = greeting_from_scan(doc)
    assert FAKE_LEAD in greeting
    assert "The label and the reference records do not agree." not in greeting


def test_greeting_says_the_recall_when_the_headline_does_not() -> None:
    greeting = greeting_from_scan(
        complete_scan(
            research={
                "verdict": "recall_match",
                "risk_level": "high",
                "headline": "The label and the reference records do not agree.",
            }
        )
    )
    assert RECALL_LEAD in greeting
    assert greeting.endswith(RECALL_LEAD)


def test_keyterms_include_names_and_the_imprint_marking() -> None:
    terms = keyterms_from_scan(complete_scan())
    assert "Tylenol" in terms
    assert "acetaminophen" in terms
    assert "500 mg" in terms
    assert "L484" in terms
    assert "ibuprofen" in terms
    assert "200 mg" in terms


def test_reports_url_points_at_the_deepgram_route() -> None:
    settings = Settings(openai_api_key="test", public_api_base_url="https://api.example/")
    assert reports_url(settings, "scan-1") == "https://api.example/deepgram/scan-1/reports"


def test_voice_settings_include_the_greeting_and_the_prompt() -> None:
    settings = Settings(openai_api_key="test", public_api_base_url="https://api.example")
    payload = build_voice_agent_settings(complete_scan(), settings)
    assert payload["type"] == "Settings"
    greeting = payload["agent"]["greeting"]
    assert greeting.startswith("Hi, I'm Peel.")
    assert "acetaminophen" in payload["agent"]["think"]["prompt"]
    assert payload["agent"]["think"]["functions"][0]["endpoint"]["url"].endswith(
        "/deepgram/scan-1/reports"
    )
