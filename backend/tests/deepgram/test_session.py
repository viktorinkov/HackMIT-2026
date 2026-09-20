from __future__ import annotations

from backend.config import Settings
from backend.deepgram.lead import FAKE_LEAD, RECALL_LEAD
from backend.deepgram.models import ConcernReportCreate
from backend.deepgram.session import (
    build_voice_agent_settings,
    fill_concern_report,
    greeting_from_scan,
    keyterms_from_scan,
    opening_messages_from_scan,
    reports_url,
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


def test_opening_does_not_include_the_headline_or_fake_lead() -> None:
    doc = complete_scan()
    doc["hardware"] = {**doc["hardware"], "status": "fake"}
    messages = opening_messages_from_scan(doc)
    assert len(messages) == 3
    assert FAKE_LEAD not in messages
    assert "The label and the reference records do not agree." not in messages
    filled = fill_concern_report(doc, ConcernReportCreate())
    assert filled.summary == FAKE_LEAD


def test_opening_does_not_include_the_recall_lead() -> None:
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
    assert RECALL_LEAD not in messages
    filled = fill_concern_report(
        complete_scan(
            research={
                "verdict": "recall_match",
                "risk_level": "high",
                "headline": "The label and the reference records do not agree.",
            }
        ),
        ConcernReportCreate(),
    )
    assert filled.summary == RECALL_LEAD


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
    assert payload["agent"]["greeting"] == "Hi, I'm Peel. These findings are a simulated demo."
    assert "acetaminophen" in payload["agent"]["think"]["prompt"]
    assert payload["agent"]["think"]["functions"][0]["endpoint"]["url"].endswith(
        "/deepgram/scan-1/reports"
    )
    assert payload["agent"]["think"]["functions"][0]["parameters"]["required"] == []


def test_fill_concern_report_uses_the_scan_problem() -> None:
    filled = fill_concern_report(complete_scan(), ConcernReportCreate())
    assert filled.concern_type == "mismatch"
    assert filled.summary == "The label and the reference records do not agree."
    assert filled.user_description == (
        "Bottle: the label says acetaminophen 500 mg. "
        "Imprint: the marking lookup returned ibuprofen 200 mg. "
        "Pill: the hardware analysis reports the contents as ibuprofen. "
        "The label and the reference records do not agree."
    )
    assert filled.symptoms is None


def test_fill_concern_report_keeps_symptoms_the_user_gave() -> None:
    filled = fill_concern_report(
        complete_scan(),
        ConcernReportCreate(symptoms="Dizzy after one tablet."),
    )
    assert filled.concern_type == "mismatch"
    assert filled.symptoms == "Dizzy after one tablet."
