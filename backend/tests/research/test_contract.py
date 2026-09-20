"""`to_scan_context` against the real ElevenLabs fixtures.

The agent is configured against `docs/elevenlabs/demo-contexts.json`, so these
tests treat the fixtures as the contract: every key and status enum a fixture
uses must come out of a scan document that mirrors it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.research.contract import (
    BOTTLE_STATUSES,
    DEGRADATION_STATUSES,
    HARDWARE_STATUSES,
    IMPRINT_STATUSES,
    scan_context_json,
    to_scan_context,
)
from backend.research.models import SAFE_NO_FINDINGS_TEXT, ResearchReport, Verdict

DOCS = Path(__file__).resolve().parents[3] / "docs" / "elevenlabs"
FIXTURES = json.loads((DOCS / "demo-contexts.json").read_text())

BOTTLE_KEYS = {
    "status", "generic_name", "brand_name", "strength", "form",
    "expiration", "lot_number", "manufacturer", "ndc", "confidence",
}
IMPRINT_KEYS = {"status", "observed_text", "candidates"}
HARDWARE_KEYS = {"status", "reported_status", "candidate", "degradation", "limitations", "model"}
FORBIDDEN = ("rx_number", "pharmacy", "directions", "other_label_text")

DEMO_SOURCE = {
    "id": "demo-reference",
    "title": "Synthetic test fixture, not a real imprint reference",
    "url": None,
}
ACETAMINOPHEN_BOTTLE = {
    "is_medication_container": True,
    "generic_name": "acetaminophen",
    "strength": "500 mg",
    "form": "tablet",
    "confidence": 0.9,
    "rx_number_present": True,
    "pharmacy_present": True,
    "directions_present": True,
}


def _scan(**kwargs: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"scan_id": "scan-1", "revision": 1, "status": "complete", "demo": True}
    doc.update(kwargs)
    return doc


def pending_scan() -> dict[str, Any]:
    return _scan(scan_id="demo-pending", status="pending")


def mismatch_scan() -> dict[str, Any]:
    return _scan(
        scan_id="demo-mismatch",
        bottle=dict(ACETAMINOPHEN_BOTTLE),
        imprint={"is_pill": True, "imprint": "DEMO-B (synthetic test marking)"},
        hardware={
            "status": "real",
            "pill_type": "Ibuprofen",
            "degraded": False,
            "confidence": 0.92,
            "model": "mock-spectrometry",
            "limitations": "Simulated result; no physical measurement was performed.",
        },
        norm={"dosage_form": "tablet", "generic_name": "acetaminophen"},
        evidence={
            "pill_candidates": [
                {
                    "generic_name": "ibuprofen",
                    "strength": "200 mg",
                    "form": "tablet",
                    "source_id": "demo-reference",
                }
            ]
        },
        research={"verdict": "mismatch_found", "risk_level": "medium", "sources": [DEMO_SOURCE]},
    )


def degradation_scan() -> dict[str, Any]:
    scan = mismatch_scan()
    scan["scan_id"] = "demo-degradation"
    scan["imprint"] = {"is_pill": True, "imprint": "DEMO-A (synthetic test marking)"}
    scan["hardware"] = {
        "status": "substandard",
        "pill_type": "acetaminophen",
        "degraded": True,
        "confidence": 0.78,
        "model": "mock-spectrometry",
        "limitations": "Simulated result; no physical measurement was performed.",
    }
    scan["evidence"]["pill_candidates"] = [
        {
            "generic_name": "acetaminophen",
            "strength": "500 mg",
            "form": "tablet",
            "source_id": "demo-reference",
        }
    ]
    return scan


SCANS = {
    "pending": pending_scan,
    "mismatch": mismatch_scan,
    "suspected_degradation": degradation_scan,
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_top_level_shape_matches_the_fixture(name: str) -> None:
    fixture = FIXTURES[name]
    context = to_scan_context(SCANS[name]())
    assert set(fixture) <= set(context)
    assert context["scan_id"] == fixture["scan_id"]
    assert context["revision"] == fixture["revision"]
    assert context["status"] == fixture["status"]
    assert context["demo"] == fixture["demo"]


def test_a_pending_scan_produces_exactly_the_fixture_keys() -> None:
    context = to_scan_context(pending_scan())
    assert set(context) == set(FIXTURES["pending"])
    assert context == FIXTURES["pending"]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_blocks_match_the_fixture_statuses_and_keys(name: str) -> None:
    fixture = FIXTURES[name]
    context = to_scan_context(SCANS[name]())
    for block, allowed in (
        ("bottle", BOTTLE_KEYS),
        ("imprint", IMPRINT_KEYS),
        ("hardware", HARDWARE_KEYS),
    ):
        expected, actual = fixture[block], context[block]
        if expected is None:
            assert actual is None
            continue
        assert set(expected) <= set(actual) <= allowed
        assert actual["status"] == expected["status"]


def test_bottle_status_enum() -> None:
    read = to_scan_context(mismatch_scan())["bottle"]
    assert read["status"] == "read" and read["status"] in BOTTLE_STATUSES

    not_a_container = to_scan_context(
        _scan(bottle={"is_medication_container": False, "confidence": 0.9})
    )["bottle"]
    assert not_a_container["status"] == "not_a_container"

    blurred = to_scan_context(
        _scan(bottle={"is_medication_container": True, "generic_name": "x", "confidence": 0.05})
    )["bottle"]
    assert blurred["status"] == "unreadable"

    empty = to_scan_context(_scan(bottle={"is_medication_container": True, "confidence": 0.9}))
    assert empty["bottle"]["status"] == "unreadable"


def test_imprint_status_enum() -> None:
    found = to_scan_context(mismatch_scan())["imprint"]
    assert found["status"] == "candidate_found"
    assert found["observed_text"] == "DEMO-B (synthetic test marking)"
    assert found["candidates"][0]["generic_name"] == "ibuprofen"
    assert found["candidates"][0]["source_id"] == "demo-reference"

    no_candidate = to_scan_context(_scan(imprint={"is_pill": True, "imprint": "L484"}))["imprint"]
    assert no_candidate["status"] == "no_candidate"
    assert no_candidate["candidates"] == []

    not_a_pill = to_scan_context(_scan(imprint={"is_pill": False, "imprint": None}))["imprint"]
    assert not_a_pill["status"] == "not_a_pill"

    unreadable = to_scan_context(_scan(imprint={"is_pill": True, "imprint": None}))["imprint"]
    assert unreadable["status"] == "unreadable"
    assert {found["status"], no_candidate["status"], unreadable["status"]} <= set(IMPRINT_STATUSES)


def test_imprint_candidate_carries_a_medication_id_when_researched() -> None:
    scan = mismatch_scan()
    scan["evidence"]["pill_candidates"][0]["medication_id"] = "ibuprofen-tablet"
    candidate = to_scan_context(scan)["imprint"]["candidates"][0]
    assert candidate["medication_id"] == "ibuprofen-tablet"


def test_hardware_candidate_never_reports_a_strength() -> None:
    hardware = to_scan_context(mismatch_scan())["hardware"]
    assert hardware["status"] == "candidate_found"
    assert hardware["status"] in HARDWARE_STATUSES
    assert hardware["candidate"] == {
        "generic_name": "ibuprofen",
        "strength": None,
        "form": "tablet",
    }
    assert hardware["limitations"] == [
        "Simulated result; no physical measurement was performed."
    ]
    assert hardware["model"] == "mock-spectrometry"


def test_hardware_without_an_identity_is_inconclusive() -> None:
    hardware = to_scan_context(
        _scan(
            hardware={
                "status": "unknown",
                "pill_type": None,
                "degraded": False,
                "confidence": 0.2,
                "model": "mock-spectrometry",
            }
        )
    )["hardware"]
    assert hardware["status"] == "inconclusive"
    assert hardware["candidate"] is None
    assert hardware["degradation"] == {"status": "inconclusive"}


@pytest.mark.parametrize(
    ("status", "degraded", "expected"),
    [
        ("real", False, "not_assessed"),
        ("fake", False, "not_assessed"),
        ("substandard", True, "suspected"),
        ("substandard", False, "suspected"),
        ("real", True, "detected"),
        ("unknown", False, "inconclusive"),
    ],
)
def test_degradation_status_mapping(status: str, degraded: bool, expected: str) -> None:
    context = to_scan_context(
        _scan(
            hardware={
                "status": status,
                "pill_type": "acetaminophen",
                "degraded": degraded,
                "confidence": 0.5,
                "model": "mock-spectrometry",
            }
        )
    )
    degradation = context["hardware"]["degradation"]
    assert degradation["status"] == expected
    assert degradation["status"] in DEGRADATION_STATUSES
    if expected in ("suspected", "detected"):
        assert degradation["evidence"] and degradation["remaining_potency"] is None
    else:
        assert set(degradation) == {"status"}


def test_degradation_block_matches_the_fixtures() -> None:
    assert to_scan_context(mismatch_scan())["hardware"]["degradation"] == (
        FIXTURES["mismatch"]["hardware"]["degradation"]
    )
    produced = to_scan_context(degradation_scan())["hardware"]["degradation"]
    expected = FIXTURES["suspected_degradation"]["hardware"]["degradation"]
    assert set(produced) == set(expected)
    assert produced["status"] == expected["status"]
    assert produced["remaining_potency"] is None


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_sources_match_the_fixture_exactly(name: str) -> None:
    context = to_scan_context(SCANS[name]())
    assert context["sources"] == FIXTURES[name]["sources"]


def test_sources_add_dates_only_when_the_report_has_them() -> None:
    scan = _scan(
        research={
            "sources": [
                {
                    "id": "dailymed-nitroglycerin",
                    "title": "DailyMed",
                    "url": "https://example.test/x",
                    "label_date": "2024-10-15",
                    "source_org": "NLM",
                }
            ]
        }
    )
    source = to_scan_context(scan)["sources"][0]
    assert set(source) == {"id", "title", "url", "label_date"}
    assert source["label_date"] == "2024-10-15"


def test_drug_facts_pass_through_in_contract_shape() -> None:
    scan = _scan(
        research={
            "drug_facts": [
                {
                    "medication_id": "nitroglycerin-sublingual",
                    "topic": "storage_and_potency",
                    "text": "Keep tablets in the original glass container.",
                    "source_ids": ["dailymed-nitroglycerin"],
                    "internal_note": "dropped",
                }
            ]
        }
    )
    facts = to_scan_context(scan)["drug_facts"]
    assert facts == [
        {
            "medication_id": "nitroglycerin-sublingual",
            "topic": "storage_and_potency",
            "text": "Keep tablets in the original glass container.",
            "source_ids": ["dailymed-nitroglycerin"],
        }
    ]


def test_research_block_is_compact_and_omitted_when_absent() -> None:
    assert "research" not in to_scan_context(pending_scan())
    scan = _scan(
        research={
            "verdict": "recall_match",
            "risk_level": "high",
            "headline": "A recalled lot matches this label.",
            "findings": [
                {
                    "statement": "Lot AB1234 is under FDA recall.",
                    "evidence_type": "exact_lot_match",
                    "severity": "serious",
                    "source_ids": ["fda-enf-D-1"],
                    "country_scope": "United States",
                }
            ],
            "mismatches": [],
            "gaps": ["No WHO record for this country."],
            "next_steps": ["Set this pill aside."],
            "agent_used": True,
        }
    )
    block = to_scan_context(scan)["research"]
    assert set(block) == {
        "verdict", "risk_level", "headline", "findings", "mismatches", "gaps", "next_steps",
    }
    assert set(block["findings"][0]) == {
        "statement", "evidence_type", "severity", "source_ids",
    }


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_context_never_leaks_prescription_data(name: str) -> None:
    scan = SCANS[name]()
    if scan.get("bottle"):
        scan["bottle"].update(
            {
                "rx_number": "RX-8823410",
                "pharmacy": "Downtown Pharmacy",
                "directions": "Take one tablet twice daily",
                "other_label_text": "Jane Doe, 12 Main St",
            }
        )
    payload = scan_context_json(scan)
    for key in FORBIDDEN:
        assert key not in payload
    for value in ("RX-8823410", "Downtown Pharmacy", "Jane Doe"):
        assert value not in payload


def test_scan_context_json_is_compact_and_reparses() -> None:
    scan = mismatch_scan()
    payload = scan_context_json(scan)
    context = to_scan_context(scan)
    assert json.loads(payload) == context
    assert len(payload) < len(json.dumps(context, indent=2))
    assert '"scan_id":"demo-mismatch"' in payload


def test_to_scan_context_does_not_mutate_the_document() -> None:
    scan = mismatch_scan()
    before = json.dumps(scan, sort_keys=True)
    to_scan_context(scan)
    assert json.dumps(scan, sort_keys=True) == before


def test_verdict_has_no_positive_assurance_value() -> None:
    from typing import get_args

    values = set(get_args(Verdict))
    assert values == {
        "no_adverse_findings", "mismatch_found", "recall_match", "insufficient_evidence",
    }
    assert values.isdisjoint({"safe", "genuine", "verified", "authentic", "clean", "pass"})


def test_safe_no_findings_text_refuses_to_certify() -> None:
    text = SAFE_NO_FINDINGS_TEXT.format(index_date="19 September 2026")
    assert "19 September 2026" in text
    assert "not a confirmation that this medicine is genuine or safe" in text
    assert "ask a pharmacist" in text
    assert "{index_date}" not in text


def test_research_report_schema_is_strict_structured_output_safe() -> None:
    schema = ResearchReport.model_json_schema()
    objects = [schema, *schema.get("$defs", {}).values()]
    for definition in objects:
        if definition.get("type") != "object":
            continue
        properties = set(definition.get("properties", {}))
        assert properties == set(definition.get("required", []))
        assert definition.get("additionalProperties") is False
    # minimum/maximum/minItems are rejected by OpenAI strict schemas.
    flat = json.dumps(schema)
    for banned in ('"minimum"', '"maximum"', '"minItems"', '"exclusiveMinimum"'):
        assert banned not in flat
