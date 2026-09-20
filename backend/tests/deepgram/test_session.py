from __future__ import annotations

from backend.deepgram.prompt import PROMPT_LIMIT
from backend.deepgram.session import (
    EAGER_EOT_THRESHOLD,
    EOT_THRESHOLD,
    EOT_TIMEOUT_MS,
    INPUT_SAMPLE_RATE,
    OFFER_DISAGREE,
    OFFER_LIGHT,
    OUTPUT_SAMPLE_RATE,
    build_voice_agent_settings,
    draft_report_function,
    greeting_from_scan,
    intro_from_scan,
    keyterms_from_scan,
    opening_messages_from_scan,
    scan_has_concern,
)
from tests.deepgram.conftest import complete_scan

THREE_SOURCES = [
    "Bottle: the label says acetaminophen 500 mg.",
    "Imprint: the marking lookup returned ibuprofen 200 mg.",
    "Pill: the hardware analysis reports the contents as ibuprofen.",
]


def test_intro_is_only_the_intro() -> None:
    assert intro_from_scan(complete_scan()) == (
        "Hi, I'm Peel. These findings are a simulated demo."
    )
    assert intro_from_scan(complete_scan(demo=False)) == "Hi, I'm Peel."


def test_greeting_is_the_intro_plus_the_three_sources_and_the_offer() -> None:
    # One greeting the user can interrupt, instead of three injected messages.
    assert greeting_from_scan(complete_scan()) == " ".join(
        [
            "Hi, I'm Peel. These findings are a simulated demo.",
            *THREE_SOURCES,
            OFFER_DISAGREE,
        ]
    )


def test_greeting_offers_the_user_report_when_the_results_disagree() -> None:
    assert scan_has_concern(complete_scan()) is True
    greeting = greeting_from_scan(complete_scan())
    assert greeting.endswith(OFFER_DISAGREE)
    assert OFFER_LIGHT not in greeting


def test_greeting_uses_the_light_offer_when_there_is_no_concern() -> None:
    doc = complete_scan(
        hardware={
            "status": "unknown",
            "pill_type": None,
            "degraded": False,
            "confidence": 0.2,
            "model": "mock-spectrometry",
        },
        research={
            "verdict": "no_adverse_findings",
            "risk_level": "low",
            "headline": "No adverse findings in the records we searched.",
            "findings": [],
            "mismatches": [],
            "gaps": [],
            "next_steps": [],
            "sources": [],
        },
    )
    assert scan_has_concern(doc) is False
    greeting = greeting_from_scan(doc)
    assert "Pill: the hardware result is unknown." in greeting
    assert greeting.endswith(OFFER_LIGHT)
    assert OFFER_DISAGREE not in greeting


def test_unknown_hardware_is_not_a_concern() -> None:
    doc = complete_scan(
        hardware={"status": "unknown", "degraded": False, "confidence": 0.2},
        research={
            "verdict": "insufficient_evidence",
            "risk_level": "low",
            "headline": "Not enough was read to compare this medicine.",
            "findings": [],
            "mismatches": [],
            "gaps": [],
            "next_steps": [],
            "sources": [],
        },
    )
    assert scan_has_concern(doc) is False


def test_fake_or_substandard_hardware_is_a_concern() -> None:
    for status in ("fake", "substandard"):
        doc = complete_scan(
            hardware={**complete_scan()["hardware"], "status": status},
            research={
                "verdict": "no_adverse_findings",
                "risk_level": "low",
                "headline": "No adverse findings in the records we searched.",
                "findings": [],
                "mismatches": [],
                "gaps": [],
                "next_steps": [],
                "sources": [],
            },
        )
        assert scan_has_concern(doc) is True


def test_opening_messages_are_exactly_the_three_sources() -> None:
    assert opening_messages_from_scan(complete_scan()) == THREE_SOURCES


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
    purchased = function["parameters"]["properties"]["purchased_on"]["description"]
    assert "YYYY-MM-DD" in purchased
    assert "JSON argument only, never spoken" in purchased
    assert "Never ask the user for this form" in purchased


def test_voice_settings_use_flux_stt_with_turn_thresholds() -> None:
    listen = build_voice_agent_settings(complete_scan())["agent"]["listen"]["provider"]
    assert listen["type"] == "deepgram"
    assert listen["version"] == "v2"
    assert listen["model"] == "flux-general-en"
    assert listen["eot_threshold"] == EOT_THRESHOLD
    assert listen["eager_eot_threshold"] == EAGER_EOT_THRESHOLD
    assert listen["eot_timeout_ms"] == EOT_TIMEOUT_MS
    assert "acetaminophen" in listen["keyterms"]
    # Flux rejects smart_format with INVALID_SETTINGS.
    assert "smart_format" not in listen


def test_voice_settings_speak_with_flux_tts_and_fall_back_to_aura() -> None:
    speak = build_voice_agent_settings(complete_scan())["agent"]["speak"]
    assert [entry["provider"]["version"] for entry in speak] == ["v2", "v1"]
    assert speak[0]["provider"]["model"].startswith("flux-")
    assert speak[1]["provider"]["model"].startswith("aura-2-")


def test_voice_settings_think_chain_shares_the_prompt_and_the_draft_tool() -> None:
    payload = build_voice_agent_settings(complete_scan())
    think = payload["agent"]["think"]
    assert len(think) == 2
    for entry in think:
        assert "acetaminophen" in entry["prompt"]
        assert entry["functions"] == [draft_report_function()]
        assert len(entry["prompt"]) <= PROMPT_LIMIT
    assert think[0]["provider"]["model"] == "gpt-4o-mini"
    assert think[1]["provider"]["type"] == "google"


def test_voice_settings_audio_greeting_and_tags() -> None:
    payload = build_voice_agent_settings(complete_scan())
    assert payload["type"] == "Settings"
    assert payload["mip_opt_out"] is True
    assert payload["audio"]["input"] == {"encoding": "linear16", "sample_rate": INPUT_SAMPLE_RATE}
    assert payload["audio"]["output"] == {
        "encoding": "linear16",
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "container": "none",
    }
    assert payload["agent"]["greeting"] == greeting_from_scan(complete_scan())
    assert payload["tags"] == ["peel", "hackmit-2026", "mismatch_found"]
