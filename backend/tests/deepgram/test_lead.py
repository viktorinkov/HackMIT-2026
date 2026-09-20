from __future__ import annotations

import re
from typing import Any

import pytest

from backend.deepgram.lead import FAKE_LEAD, RECALL_LEAD, lead_from_context


def _context(
    *,
    reported_status: str | None = None,
    verdict: str | None = None,
    headline: str | None = None,
    degradation: str | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {"scan_id": "scan-1", "status": "complete", "demo": False}
    if reported_status is not None or degradation is not None:
        hardware: dict[str, Any] = {
            "status": "candidate_found" if reported_status in ("real", "substandard", "fake") else "inconclusive",
            "reported_status": reported_status,
            "candidate": {"generic_name": "acetaminophen", "strength": None, "form": "tablet"},
            "degradation": {"status": degradation or "not_assessed"},
        }
        context["hardware"] = hardware
    if verdict is not None or headline is not None:
        context["research"] = {"verdict": verdict, "headline": headline}
    return context


def test_no_research_and_no_fake_has_no_lead() -> None:
    assert lead_from_context({"scan_id": "scan-1", "status": "pending"}) is None


def test_headline_is_the_lead_when_nothing_overrides_it() -> None:
    context = _context(
        verdict="mismatch_found",
        headline="The label and the reference records do not agree.",
    )
    assert lead_from_context(context) == "The label and the reference records do not agree."


def test_recall_verdict_without_a_recall_headline_uses_the_recall_sentence() -> None:
    context = _context(
        verdict="recall_match",
        headline="The label and the reference records do not agree.",
    )
    assert lead_from_context(context) == RECALL_LEAD


def test_recall_verdict_keeps_an_affirmative_recall_headline() -> None:
    headline = "A recall or safety alert names lot AB1234 from this label."
    context = _context(verdict="recall_match", headline=headline)
    assert lead_from_context(context) == headline


def test_no_findings_headline_is_not_treated_as_a_recall() -> None:
    headline = "No matching recall or safety alert was found in the records searched."
    context = _context(verdict="no_adverse_findings", headline=headline)
    assert lead_from_context(context) == headline


def test_fake_leads_even_when_the_headline_says_no_recall() -> None:
    context = _context(
        reported_status="fake",
        verdict="no_adverse_findings",
        headline="No matching recall or safety alert was found in the records searched.",
    )
    assert lead_from_context(context) == FAKE_LEAD


def test_fake_then_recall_are_two_sentences() -> None:
    headline = "A recall covering every lot of this product matches this label."
    context = _context(
        reported_status="fake",
        verdict="recall_match",
        headline=headline,
    )
    assert lead_from_context(context) == f"{FAKE_LEAD} {headline}"


def test_fake_and_a_mute_recall_headline_still_says_the_recall() -> None:
    context = _context(
        reported_status="fake",
        verdict="recall_match",
        headline="Nothing adverse was found.",
    )
    assert lead_from_context(context) == f"{FAKE_LEAD} {RECALL_LEAD}"


@pytest.mark.parametrize("status", ["real", "substandard", "unknown"])
def test_non_fake_hardware_does_not_override_the_headline(status: str) -> None:
    headline = "The label and the reference records do not agree."
    context = _context(
        reported_status=status,
        verdict="mismatch_found",
        headline=headline,
        degradation="detected" if status == "substandard" else "not_assessed",
    )
    assert lead_from_context(context) == headline


def test_degradation_without_fake_is_not_a_lead() -> None:
    headline = "The label and the reference records do not agree."
    context = _context(
        reported_status="substandard",
        verdict="mismatch_found",
        headline=headline,
        degradation="suspected",
    )
    assert "fake" not in (lead_from_context(context) or "").lower()
    assert lead_from_context(context) == headline


def test_lead_does_not_claim_proof_when_fake_and_recall_agree() -> None:
    text = lead_from_context(
        _context(
            reported_status="fake",
            verdict="recall_match",
            headline="A recall or safety alert names lot AB1234 from this label.",
        )
    )
    assert text is not None
    lowered = text.lower()
    assert "proof" not in lowered
    assert "falsified" not in lowered
    assert "genuine" not in lowered
    assert re.search(r"\bsafe\b", lowered) is None
