"""The structured report the research pipeline coerces every scan into.

These models are handed to OpenAI strict structured outputs, so every field is
required and nullable rather than defaulted, and no numeric constraints appear
anywhere: `minimum`/`maximum`/`minItems` are rejected by the strict schema.
Validate ranges in Python instead.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# "no_adverse_findings" is deliberately not "clean" or "verified": the product
# must never emit a positive assurance that a medicine is genuine or safe.
Verdict = Literal[
    "no_adverse_findings",
    "mismatch_found",
    "recall_match",
    "insufficient_evidence",
]
RiskLevel = Literal["low", "medium", "high", "unknown"]
EvidenceType = Literal[
    "exact_lot_match",
    "exact_ndc_match",
    "imprint_reference",
    "ndc_directory",
    "regulatory_record",
    "web_page",
    "prior_scan_signal",
    "hardware_result",
    "bottle_label",
]
Severity = Literal["info", "caution", "serious"]
MismatchField = Literal[
    "active_ingredient",
    "strength",
    "dosage_form",
    "release_type",
    "manufacturer",
    "imprint",
    "color",
    "shape",
    "ndc_identity",
]
FactTopic = Literal[
    "use",
    "storage_and_potency",
    "warnings",
    "recall",
    "counterfeit_reports",
    "identification",
]

# The one sentence a "nothing found" result is allowed to say. Callers format
# {index_date} with the freshness of the regulatory index they searched.
SAFE_NO_FINDINGS_TEXT = (
    "I did not find any recall or safety alert matching this medicine in the FDA, WHO "
    "and NAFDAC records I searched, which are current to {index_date}. That is not a "
    "confirmation that this medicine is genuine or safe — my pill reference is a US "
    "archive frozen in January 2021, my records do not cover every country, and I "
    "cannot measure what is actually inside the tablet. If anything about this "
    "medicine looks or feels wrong to you, treat that as more reliable than my result "
    "and ask a pharmacist."
)


class _Strict(BaseModel):
    # extra="forbid" is what emits additionalProperties:false, which strict mode requires.
    model_config = ConfigDict(extra="forbid")


class SourceRef(_Strict):
    id: str
    title: str
    url: str | None
    source_org: str | None
    published_at: str | None  # ISO date string, not datetime: strict schema has no format
    label_date: str | None


class Finding(_Strict):
    statement: str
    evidence_type: EvidenceType
    source_ids: list[str]
    severity: Severity
    country_scope: str | None


class Mismatch(_Strict):
    field: MismatchField
    bottle_claim: str | None
    imprint_reference: str | None
    hardware_report: str | None
    explanation: str
    source_ids: list[str]


class DrugFact(_Strict):
    medication_id: str
    topic: FactTopic
    text: str
    source_ids: list[str]


class ResearchReport(_Strict):
    verdict: Verdict
    risk_level: RiskLevel
    headline: str
    findings: list[Finding]
    mismatches: list[Mismatch]
    recall_hits: list[SourceRef]
    gaps: list[str]
    next_steps: list[str]
    drug_facts: list[DrugFact]
    sources: list[SourceRef]
    agent_used: bool
    demo: bool
