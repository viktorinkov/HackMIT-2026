"""The evidence pack, the deterministic report, and the guardrails.

Three jobs, in the order the pipeline uses them:

1. `build_evidence` compacts every retrieval result into the small JSON object
   the agent and the coercion model read. It is size-capped, because an
   unbounded pack is how a 14 k-token prompt becomes a 90 k-token one.
2. `deterministic_report` answers the scan with no LLM at all. It is both the
   stage-2 "partial" report the app renders in ~3 s and the fallback when
   OpenAI is down, so the voice agent never sees a null report.
3. `enforce_guardrails` is applied to whatever the LLM returns. It is the last
   line before a user hears a verdict: an unsupported `recall_match`, an
   invented source id, or the word "genuine" never survives it
   (audit_redteam F2, F12, §5).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from backend.sensor_data import sensor_evidence, measurement_sentence
from urllib.parse import quote

from backend.knowledge import normalize
from backend.knowledge.fields import Ndc, Pill, Reg, Web
from backend.knowledge.search import Hit, PillMatch
from backend.pill import HARDWARE_MODEL
from backend.research.models import (
    SAFE_NO_FINDINGS_TEXT,
    DrugFact,
    Finding,
    Mismatch,
    ResearchReport,
    SourceRef,
)
from backend.research.rxnav import NdcStatus

MAX_EVIDENCE_CHARS = 14_000
MAX_SUMMARY_CHARS = 360
MAX_LOTS_SHOWN = 25
MAX_WEB_LOTS_SHOWN = 10
MAX_WEB_FINDINGS = 3
PRIOR_SCAN_MIN = 3

# scans.normalizer writes this onto every mock hardware reading; repeated here
# rather than imported so evidence.py does not depend on the scans package.
MOCK_LIMITATION = "Simulated result; no physical measurement was performed."
NO_IMPRINT_SKIP = "no imprint read"
DAILYMED_SEARCH_URL = "https://dailymed.nlm.nih.gov/dailymed/search.cfm"
_HARDWARE_ADVERSE = ("substandard", "fake")
_WEB_ADVERSE_FLAGS = {"recall", "falsified", "counterfeit", "substandard"}

_RISK_BY_SEVERITY = {"critical": "high", "high": "high", "moderate": "medium"}
# An all-lots recall is only about this bottle when the recall text itself names
# the NDC, or both the drug name and the manufacturer match (audit_redteam F2).
# A shared molecule name alone is another firm's product.
_PRECISE_NDC_KINDS = ("ndc_in_description", "all_lots_product")
# Only a corroborated record may carry the recall_match verdict. knowledge.search
# marks a lot hit whose product context disagrees as "lot_only_match" (a lot
# string that collides with an unrelated product) and an all-lots recall reached
# only through openFDA's sibling-strength NDC list as "all_lots_sibling". Both
# are cautions to compare by hand, never a match for this bottle.
_RECALL_LOT_KINDS = ("exact_lot",)
_RECALL_ALL_LOTS_KINDS = ("all_lots_product",)
LOT_ONLY_CAUTION = (
    "a recall names this lot number but for a different product — compare the product name "
    "carefully"
)
# Stated when the lot / all-lots lookup itself failed: the search never ran, so
# "nothing was found" would be a claim about a query that never happened.
RECALL_LOOKUP_FAILED_GAP = (
    "The recall lookup did not complete for this scan, so a matching recall could have been missed."
)
# "imprint_all_parts": every part read from one face is on the reference pill
# (Pillbox stores both faces, a phone photo shows one).
_EXACT_IMPRINT_KINDS = ("imprint_exact", "imprint_sorted", "imprint_all_parts")

_SAFE_NEXT_STEPS = (
    "Keep the medicine in its original packaging with the label and lot number intact.",
    "Ask a pharmacist to check the medicine together with its packaging.",
    "If anything about this medicine looks, smells or feels wrong to you, treat that as "
    "more reliable than this result.",
)
_RECALL_NEXT_STEPS = (
    "Set this medicine aside in its original packaging and keep the packaging.",
    "Take the bottle and this result to a pharmacist promptly and ask them to compare the "
    "lot number on the label with the recall notice.",
    "Ask the pharmacist what to do next before you change anything about how you take it.",
)

NEUTRAL_HEADLINES = {
    "recall_match": "A recall or safety alert matches this medicine.",
    "mismatch_found": "The label and the reference records do not agree.",
    "insufficient_evidence": "There was not enough readable detail to check this medicine.",
    "no_adverse_findings": "No matching recall or safety alert was found in the records searched.",
}

# Never assert the negative of these words either: "not fake" is still a claim.
_BANNED_RE = re.compile(r"\b(?:safe|genuine|authentic|authenticated|verified|counterfeit-free)\b", re.I)
_NEGATION_RE = re.compile(r"\b(?:not|never|cannot|can't|isn't|aren't|no|nor|neither)\b", re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# A negation only disarms a banned word inside its own clause: "no recall was
# found, so this medicine is genuine" is still a positive assurance.
_CLAUSE_RE = re.compile(r"[,;:—–]|\b(?:so|but|therefore|thus|hence|however|yet)\b", re.I)
_PII_RE = re.compile(
    r"\brx\s*(?:#|nos?\.?|numbers?)\s*[:#]?\s*\w{3,}|\bprescription\s+numbers?\b"
    r"|\bpatient\s+name\b|\bpharmacy\s*[:#]\s*\S+",
    re.I,
)

# The sentence a "nothing found" result must carry; it cites nothing by design.
DISCLAIMER_MARKER = "That is not a confirmation"
_UNSOURCED_OK = {"hardware_result", "bottle_label", "prior_scan_signal"}
# C0 controls except tab and newline. gpt-4o turns an en dash into U+0013 when it
# retypes a JSON escape, which is one reason source metadata is never trusted.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")



# --------------------------------------------------------------------------- pack


def build_evidence(
    scan_doc: dict[str, Any],
    *,
    index_date: str,
    exact_lot_hits: Sequence[Hit] = (),
    all_lots_hits: Sequence[Hit] = (),
    ndc_hits: Sequence[Hit] = (),
    ndc_directory: Sequence[Hit] = (),
    ndc_status: NdcStatus | None = None,
    pill: PillMatch | None = None,
    pill_skipped: str | None = None,
    regulatory_hits: Sequence[Hit] = (),
    web_hits: Sequence[Hit] = (),
    prior_scans: dict[str, Any] | None = None,
    recall_lookup_failed: bool = False,
) -> dict[str, Any]:
    """Stage-2 results -> the compact pack the agent and the LLM both read."""
    label = _label(scan_doc)
    # Belt and braces: whatever the caller passed, candidates without an imprint
    # are shape/colour coincidences, not an identification.
    if not label.get("imprint_norm"):
        pill, pill_skipped = None, pill_skipped or NO_IMPRINT_SKIP
    evidence: dict[str, Any] = {
        "index_date": index_date,
        "label": label,
        "hardware": _hardware(scan_doc),
        "exact_lot_hits": [_reg(hit) for hit in exact_lot_hits],
        "all_lots_hits": [_reg(hit) for hit in all_lots_hits],
        "ndc_hits": [_reg(hit) for hit in ndc_hits],
        "ndc_directory": [_ndc(hit) for hit in ndc_directory],
        "ndc_status": _ndc_status(ndc_status),
        "pill": _pill(pill, pill_skipped),
        "regulatory_hits": [_reg(hit) for hit in regulatory_hits],
        "web_hits": [_web(hit) for hit in web_hits],
        "prior_scans": dict(prior_scans or {"total": 0, "by_verdict": {}}),
        "recall_lookup_failed": bool(recall_lookup_failed),
    }
    # `_fit` trims each list from its tail, so the tail must be the cheapest
    # evidence: rank the web hits first, and keep the pages this scan fetched
    # (the ones that can name this very lot) ahead of generic hybrid matches.
    evidence["web_hits"] = sorted(
        rank_web_hits(evidence, label),
        key=lambda entry: 0 if entry.get("match_kind") == "fetched_for_this_scan" else 1,
    )
    return _fit(evidence)


def _label(scan_doc: dict[str, Any]) -> dict[str, Any]:
    norm = scan_doc.get("norm") or {}
    imprint = scan_doc.get("imprint") or {}
    hardware = scan_doc.get("hardware") or {}
    return {
        "lot": norm.get("lot"),
        "ndc9": norm.get("ndc9"),
        "ndc11": norm.get("ndc11"),
        "imprint_norm": norm.get("imprint_norm"),
        "observed_imprint": imprint.get("imprint"),
        "shape": norm.get("shape"),
        "colors": list(norm.get("colors") or []),
        "drug_names": list(norm.get("drug_names") or []),
        "generic_name": norm.get("generic_name"),
        "brand_name": norm.get("brand_name"),
        "strength": norm.get("strength"),
        "dosage_form": norm.get("dosage_form"),
        "manufacturer": norm.get("manufacturer"),
        "expiration": norm.get("expiration"),
        "expired": norm.get("expired"),
        "country": scan_doc.get("country"),
    }


def _hardware(scan_doc: dict[str, Any]) -> dict[str, Any] | None:
    """A block of its own, so a reader cannot miss that it may be simulated."""
    hardware = scan_doc.get("hardware") or {}
    if not hardware:
        return None
    model = hardware.get("model")
    simulated = model == HARDWARE_MODEL or bool(hardware.get("limitations"))
    return {
        "status": hardware.get("status"),
        "pill_type": hardware.get("pill_type"),
        "degraded": hardware.get("degraded"),
        "confidence": hardware.get("confidence"),
        "model": model,
        "simulated": simulated,
        **sensor_evidence(hardware),
        "limitations": hardware.get("limitations")
        or (MOCK_LIMITATION if simulated else None),
    }


def _reg(hit: Hit) -> dict[str, Any]:
    source = hit.source
    lots = _as_list(source.get(Reg.LOT_NUMBERS))
    return {
        "record_id": source.get(Reg.RECORD_ID) or hit.id,
        "url": source.get(Reg.URL),
        "source_org": source.get(Reg.SOURCE_ORG),
        "doc_type": source.get(Reg.DOC_TYPE),
        "title": source.get(Reg.TITLE),
        "summary": _short(source.get(Reg.SUMMARY) or hit.highlight or source.get(Reg.REASON)),
        "severity": source.get(Reg.SEVERITY),
        "status": source.get(Reg.STATUS),
        "drug_names": _as_list(source.get(Reg.DRUG_NAMES))
        or _as_list(source.get(Reg.DRUG_NAMES_EXTRACTED)),
        "manufacturer": source.get(Reg.MANUFACTURER) or source.get(Reg.RECALLING_FIRM),
        "countries": _as_list(source.get(Reg.COUNTRIES)),
        "recency_date": source.get(Reg.RECENCY_DATE),
        "age_days": hit.age_days,
        "freshness": hit.freshness,
        "match_kind": hit.match_kind,
        "lots_shown": lots[:MAX_LOTS_SHOWN],
        "lot_count": len(lots),
        "covers_all_lots": bool(source.get(Reg.COVERS_ALL_LOTS)),
    }


def _web(hit: Hit) -> dict[str, Any]:
    source = hit.source
    page_id = str(source.get(Web.PAGE_ID) or hit.id)
    return {
        "page_id": page_id,
        "source_id": web_source_id(page_id),
        "url": source.get(Web.URL),
        "domain": source.get(Web.DOMAIN),
        "source_tier": source.get(Web.SOURCE_TIER),
        "source_org": source.get(Web.SOURCE_ORG),
        "title": source.get(Web.TITLE),
        "summary": _short(hit.highlight or source.get(Web.DESCRIPTION)),
        "drug_names": _as_list(source.get(Web.DRUG_NAMES)),
        "lots_shown": _as_list(source.get(Web.LOT_NUMBERS))[:MAX_WEB_LOTS_SHOWN],
        "lot_count": len(_as_list(source.get(Web.LOT_NUMBERS))),
        "countries": _as_list(source.get(Web.COUNTRIES)),
        "flags": _as_list(source.get(Web.FLAGS)),
        "recency_date": source.get(Web.RECENCY_DATE),
        "date_precision": source.get(Web.DATE_PRECISION),
        "age_days": hit.age_days,
        "freshness": hit.freshness,
        "match_kind": hit.match_kind,
    }


def _ndc(hit: Hit) -> dict[str, Any]:
    source = hit.source
    return {
        "product_ndc": source.get(Ndc.PRODUCT_NDC) or hit.id,
        "ndc9": source.get(Ndc.NDC9),
        "brand_name": source.get(Ndc.BRAND_NAME),
        "generic_name": source.get(Ndc.GENERIC_NAME),
        "labeler_name": source.get(Ndc.LABELER_NAME),
        "active_ingredient_names": _as_list(source.get(Ndc.ACTIVE_INGREDIENT_NAMES)),
        "strengths": _as_list(source.get(Ndc.STRENGTHS)),
        "dosage_form": source.get(Ndc.DOSAGE_FORM),
        "marketing_category": source.get(Ndc.MARKETING_CATEGORY),
        "is_listing_expired": source.get(Ndc.IS_LISTING_EXPIRED),
        "match_kind": hit.match_kind,
    }


def _pill_candidate(hit: Hit) -> dict[str, Any]:
    source = hit.source
    generic = source.get(Pill.GENERIC_NAME) or source.get(Pill.MEDICINE_NAME)
    return {
        "pill_id": source.get(Pill.PILL_ID) or hit.id,
        "source_id": source.get(Pill.PILL_ID) or hit.id,
        "medication_id": normalize.normalize_drug_name(generic),
        "generic_name": generic,
        "medicine_name": source.get(Pill.MEDICINE_NAME),
        "strength": source.get(Pill.STRENGTH),
        "labeler": source.get(Pill.LABELER),
        "imprint": source.get(Pill.IMPRINT_RAW),
        "shape": source.get(Pill.SHAPE),
        "colors": _as_list(source.get(Pill.COLORS)),
        "product_ndc": source.get(Pill.PRODUCT_NDC),
        "setid": source.get(Pill.SETID),
        "match_kind": hit.match_kind,
    }


def _pill(pill: PillMatch | None, skipped: str | None = None) -> dict[str, Any]:
    if pill is None or skipped:
        return {
            "candidates": [],
            "rung": 0,
            "shape_relaxed": False,
            "filters_applied": {},
            "skipped": skipped or "not run",
        }
    return {
        "candidates": [_pill_candidate(hit) for hit in pill.hits],
        "rung": pill.rung,
        "shape_relaxed": pill.shape_relaxed,
        "filters_applied": dict(pill.filters_applied),
    }


def _ndc_status(status: NdcStatus | None) -> dict[str, Any] | None:
    if status is None:
        return None
    return {
        "ndc11": status.ndc11,
        "status": status.status,
        "active": status.active,
        "rxcui": status.rxcui,
        "concept_name": status.concept_name,
    }


def pill_candidates(evidence: dict[str, Any], dosage_form: str | None = None) -> list[dict[str, Any]]:
    """The `evidence.pill_candidates` shape `research/contract.py` reads."""
    out: list[dict[str, Any]] = []
    for candidate in (evidence.get("pill") or {}).get("candidates") or []:
        item = {
            "generic_name": candidate.get("generic_name"),
            "strength": candidate.get("strength"),
            "form": dosage_form,
            "source_id": candidate.get("source_id"),
        }
        if candidate.get("medication_id"):
            item["medication_id"] = candidate["medication_id"]
        out.append(item)
    return out


# Trimmed tail-first when the pack is too large: the cheapest evidence goes first.
# Name-level regulatory hits before web pages: a page this scan just fetched is
# fresher and more specific than a hybrid match on the drug name.
_TRIM_ORDER = (
    ("regulatory_hits",),
    ("web_hits",),
    ("ndc_hits",),
    ("pill", "candidates"),
    ("all_lots_hits",),
    ("ndc_directory",),
    ("exact_lot_hits",),
)


def _fit(evidence: dict[str, Any], cap: int = MAX_EVIDENCE_CHARS) -> dict[str, Any]:
    for path in _TRIM_ORDER:
        items = _at(evidence, path)
        while items and len(items) > 1 and evidence_size(evidence) > cap:
            items.pop()
    return evidence


def evidence_size(evidence: dict[str, Any]) -> int:
    return len(json.dumps(evidence, separators=(",", ":"), default=str))


def _at(evidence: dict[str, Any], path: tuple[str, ...]) -> list[Any] | None:
    node: Any = evidence
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, list) else None


# --------------------------------------------------------------------------- mismatches


def derive_mismatches(scan_doc: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Disagreements computed in code, so they exist with or without an LLM."""
    label = evidence.get("label") or _label(scan_doc)
    out: list[dict[str, Any]] = []
    label_tokens = _name_tokens(label.get("drug_names") or [])

    pill = evidence.get("pill") or {}
    exact = [
        candidate
        for candidate in pill.get("candidates") or []
        if candidate.get("match_kind") in _EXACT_IMPRINT_KINDS
    ]
    if exact and label_tokens:
        names = [c.get("generic_name") for c in exact if c.get("generic_name")]
        if names and not _name_tokens(names) & label_tokens:
            out.append(
                {
                    "field": "imprint",
                    "bottle_claim": _first(label.get("drug_names")),
                    "imprint_reference": ", ".join(str(n) for n in names[:3]),
                    "hardware_report": None,
                    "explanation": (
                        f"The imprint {label.get('imprint_norm') or ''} matches a US Pillbox "
                        "record for a different medicine than the label claims. Pillbox is an "
                        "archive frozen in January 2021, so this is a disagreement to check, "
                        "not proof of anything."
                    ).strip(),
                    "source_ids": [c["source_id"] for c in exact[:3] if c.get("source_id")],
                }
            )

    for entry in evidence.get("ndc_directory") or []:
        names = [entry.get("generic_name"), entry.get("brand_name")]
        names += entry.get("active_ingredient_names") or []
        directory_tokens = _name_tokens([n for n in names if n])
        if label_tokens and directory_tokens and not (directory_tokens & label_tokens):
            out.append(
                {
                    "field": "ndc_identity",
                    "bottle_claim": _first(label.get("drug_names")),
                    "imprint_reference": entry.get("generic_name") or entry.get("brand_name"),
                    "hardware_report": None,
                    "explanation": (
                        f"NDC {entry.get('product_ndc')} is registered in the FDA directory to "
                        f"{entry.get('generic_name') or entry.get('brand_name')}, not to the "
                        "medicine named on this label."
                    ),
                    "source_ids": [str(entry.get("product_ndc"))] if entry.get("product_ndc") else [],
                }
            )
            break
        maker = normalize.normalize_drug_name(label.get("manufacturer"))
        labeler = normalize.normalize_drug_name(entry.get("labeler_name"))
        if maker and labeler and not (_tokens(maker) & _tokens(labeler)):
            out.append(
                {
                    "field": "manufacturer",
                    "bottle_claim": label.get("manufacturer"),
                    "imprint_reference": entry.get("labeler_name"),
                    "hardware_report": None,
                    "explanation": (
                        f"The label names {label.get('manufacturer')}, but NDC "
                        f"{entry.get('product_ndc')} is registered to "
                        f"{entry.get('labeler_name')}. Repackagers legitimately differ from the "
                        "original maker, so this is worth checking rather than conclusive."
                    ),
                    "source_ids": [str(entry.get("product_ndc"))] if entry.get("product_ndc") else [],
                }
            )
            break

    if (evidence.get("pill") or {}).get("shape_relaxed"):
        out.append(
            {
                "field": "shape",
                "bottle_claim": label.get("shape"),
                "imprint_reference": _first(
                    [c.get("shape") for c in (pill.get("candidates") or []) if c.get("shape")]
                ),
                "hardware_report": None,
                "explanation": (
                    "No reference pill with this imprint matched the observed shape; the shape "
                    "filter had to be dropped to find candidates. A shape read from a photo is "
                    "often wrong, so treat this as a low-confidence disagreement."
                ),
                "source_ids": [],
            }
        )

    status = evidence.get("ndc_status") or {}
    if status and not status.get("active") and status.get("status") in ("OBSOLETE", "ALIEN", "UNKNOWN"):
        out.append(
            {
                "field": "ndc_identity",
                "bottle_claim": label.get("ndc11") or label.get("ndc9"),
                "imprint_reference": None,
                "hardware_report": None,
                "explanation": (
                    f"RxNav reports this NDC as {status.get('status')}, meaning the code is no "
                    "longer an active US listing. Old stock and non-US products can both look "
                    "like this."
                ),
                "source_ids": [],
            }
        )
    return out


# --------------------------------------------------------------------------- report


def deterministic_report(
    scan_doc: dict[str, Any],
    evidence: dict[str, Any],
    *,
    index_date: str,
    agent_used: bool = False,
) -> ResearchReport:
    """The no-LLM report: stage-2's `partial`, and stage-5's fallback."""
    label = evidence.get("label") or _label(scan_doc)
    mismatch_dicts = derive_mismatches(scan_doc, evidence)
    verdict, risk = verdict_from_evidence(evidence, has_mismatch=bool(mismatch_dicts))

    findings: list[Finding] = []
    sources: dict[str, SourceRef] = {}
    recall_hits: list[SourceRef] = []
    gaps: list[str] = []

    for entry in evidence.get("exact_lot_hits") or []:
        ref = _reg_source(entry)
        sources[ref.id] = ref
        if entry.get("match_kind") in _RECALL_LOT_KINDS:
            recall_hits.append(ref)
            findings.append(
                Finding(
                    statement=(
                        f"{entry.get('source_org') or 'A regulator'} record "
                        f"\"{entry.get('title')}\" names lot {label.get('lot')}, the lot read "
                        "from this label."
                    ),
                    evidence_type="exact_lot_match",
                    source_ids=[ref.id],
                    severity="serious",
                    country_scope=_first(entry.get("countries")),
                )
            )
            continue
        # lot_only_match: the lot string matches, the product does not.
        findings.append(
            Finding(
                statement=(
                    f"{entry.get('source_org') or 'A regulator'} record \"{entry.get('title')}\" "
                    f"lists lot {label.get('lot')}: {LOT_ONLY_CAUTION}."
                ),
                evidence_type="regulatory_record",
                source_ids=[ref.id],
                severity="caution",
                country_scope=_first(entry.get("countries")),
            )
        )

    for entry in evidence.get("all_lots_hits") or []:
        ref = _reg_source(entry)
        sources[ref.id] = ref
        if entry.get("match_kind") in _RECALL_ALL_LOTS_KINDS:
            recall_hits.append(ref)
            findings.append(
                Finding(
                    statement=(
                        f"{entry.get('source_org') or 'A regulator'} record "
                        f"\"{entry.get('title')}\" covers every lot of this product, so no lot "
                        "number is needed to be in scope."
                    ),
                    evidence_type="regulatory_record",
                    source_ids=[ref.id],
                    severity="serious",
                    country_scope=_first(entry.get("countries")),
                )
            )
            continue
        # all_lots_sibling: reached through openFDA's sibling-strength NDC list,
        # so it is product-line evidence exactly like an NDC hit.
        findings.append(
            Finding(
                statement=_product_line_statement(entry, label.get("lot")),
                evidence_type="exact_ndc_match",
                source_ids=[ref.id],
                severity="caution",
                country_scope=_first(entry.get("countries")),
            )
        )

    for entry in (evidence.get("ndc_hits") or [])[:3]:
        ref = _reg_source(entry)
        sources[ref.id] = ref
        findings.append(
            Finding(
                statement=_product_line_statement(entry, label.get("lot")),
                evidence_type="exact_ndc_match",
                source_ids=[ref.id],
                severity="caution",
                country_scope=_first(entry.get("countries")),
            )
        )

    for entry in (evidence.get("ndc_directory") or [])[:2]:
        ref = _ndc_source(entry)
        sources[ref.id] = ref
        findings.append(
            Finding(
                statement=(
                    f"NDC {entry.get('product_ndc')} is registered in the FDA directory to "
                    f"{entry.get('generic_name') or entry.get('brand_name')} "
                    f"({entry.get('labeler_name')})."
                ),
                evidence_type="ndc_directory",
                source_ids=[ref.id],
                severity="info",
                country_scope="United States",
            )
        )

    for candidate in ((evidence.get("pill") or {}).get("candidates") or [])[:3]:
        ref = _pill_source(candidate)
        sources[ref.id] = ref
        findings.append(
            Finding(
                statement=(
                    f"The US Pillbox archive lists imprint {candidate.get('imprint')} as "
                    f"{candidate.get('generic_name')} {candidate.get('strength') or ''}".strip()
                    + ". Pillbox was frozen in January 2021, so a newer product may be missing."
                ),
                evidence_type="imprint_reference",
                source_ids=[ref.id],
                severity="info",
                country_scope="United States",
            )
        )

    for entry in (evidence.get("regulatory_hits") or [])[:2]:
        ref = _reg_source(entry)
        if ref.id in sources:
            continue
        sources[ref.id] = ref
        findings.append(
            Finding(
                statement=(
                    f"Related {entry.get('source_org') or 'regulatory'} record: "
                    f"\"{entry.get('title')}\"{_age_note(entry)}."
                ),
                evidence_type="regulatory_record",
                source_ids=[ref.id],
                severity="info",
                country_scope=_first(entry.get("countries")),
            )
        )

    for entry in rank_web_hits(evidence, label)[:MAX_WEB_FINDINGS]:
        ref = _web_source(entry)
        sources[ref.id] = ref
        findings.append(
            Finding(
                statement=_web_statement(entry, label.get("lot")),
                evidence_type="web_page",
                source_ids=[ref.id],
                severity="caution" if _lists_lot(entry, label.get("lot")) else "info",
                country_scope=_first(entry.get("countries")),
            )
        )

    prior = evidence.get("prior_scans") or {}
    if int(prior.get("total") or 0) >= PRIOR_SCAN_MIN:
        findings.append(
            Finding(
                statement=(
                    f"{prior['total']} earlier Peel scans matched this lot or product NDC. This "
                    "is crowd signal from app users, not a regulator's conclusion."
                ),
                evidence_type="prior_scan_signal",
                source_ids=[],
                severity="info",
                country_scope=None,
            )
        )

    if label.get("expired"):
        findings.append(
            Finding(
                statement=(
                    f"The expiry date read from the label ({label.get('expiration')}) has passed. "
                    "A medicine past its expiry date may have lost potency whatever its origin."
                ),
                evidence_type="bottle_label",
                source_ids=[],
                severity="caution",
                country_scope=None,
            )
        )

    hardware = evidence.get("hardware") or {}
    hardware_finding = _hardware_finding(hardware)
    if hardware_finding is not None:
        findings.append(hardware_finding)
    corroboration = _corroboration_finding(hardware, evidence)
    if corroboration is not None:
        findings.append(corroboration)

    gaps.extend(_gaps(label, evidence))

    if verdict == "no_adverse_findings":
        findings.append(
            Finding(
                statement=SAFE_NO_FINDINGS_TEXT.format(index_date=index_date),
                evidence_type="regulatory_record",
                source_ids=[],
                severity="info",
                country_scope=None,
            )
        )

    next_steps = list(_RECALL_NEXT_STEPS if verdict == "recall_match" else _SAFE_NEXT_STEPS)
    if verdict == "no_adverse_findings":
        next_steps.append(SAFE_NO_FINDINGS_TEXT.format(index_date=index_date))

    return _scrubbed(ResearchReport(
        verdict=verdict,
        risk_level=risk,
        headline=_headline(verdict, label, evidence, len(mismatch_dicts)),
        findings=findings,
        mismatches=[Mismatch(**item) for item in mismatch_dicts],
        recall_hits=recall_hits,
        gaps=gaps,
        next_steps=next_steps,
        drug_facts=_drug_facts(label, evidence, sources),
        sources=list(sources.values()),
        agent_used=agent_used,
        demo=bool(scan_doc.get("demo", False)),
    ))


def verdict_from_evidence(
    evidence: dict[str, Any], *, has_mismatch: bool
) -> tuple[str, str]:
    """The verdict the evidence supports on its own, LLM or no LLM."""
    lot_hits = qualifying_lot_hits(evidence)
    if lot_hits:
        return "recall_match", _risk(lot_hits)
    all_lots = _qualifying_all_lots(evidence)
    if all_lots:
        return "recall_match", _risk(all_lots)
    if has_mismatch:
        return "mismatch_found", "medium"
    if not _label_usable(evidence.get("label") or {}):
        return "insufficient_evidence", "unknown"
    if evidence.get("recall_lookup_failed"):
        # The anchor lookup never ran, so "nothing was found" would describe a
        # search that did not happen.
        return "insufficient_evidence", "unknown"
    return "no_adverse_findings", "low"


def qualifying_lot_hits(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Lot hits whose product is corroborated, not a lot-string collision."""
    return [
        entry
        for entry in evidence.get("exact_lot_hits") or []
        if entry.get("match_kind") in _RECALL_LOT_KINDS
    ]


def _qualifying_all_lots(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """All-lots recalls that are actually about this product, not a sibling NDC."""
    out = [
        entry
        for entry in evidence.get("all_lots_hits") or []
        if entry.get("match_kind") in _RECALL_ALL_LOTS_KINDS
    ]
    for entry in evidence.get("ndc_hits") or []:
        if entry.get("covers_all_lots") and entry.get("match_kind") in _PRECISE_NDC_KINDS:
            out.append(entry)
    return out


def _label_usable(label: dict[str, Any]) -> bool:
    return bool(
        label.get("lot")
        or label.get("ndc9")
        or label.get("ndc11")
        or label.get("imprint_norm")
        or label.get("drug_names")
    )


def _risk(entries: Sequence[dict[str, Any]]) -> str:
    for entry in entries:
        risk = _RISK_BY_SEVERITY.get(str(entry.get("severity") or "").lower())
        if risk == "high":
            return "high"
    for entry in entries:
        if _RISK_BY_SEVERITY.get(str(entry.get("severity") or "").lower()) == "medium":
            return "medium"
    # A named lot with no published classification is still a named lot.
    return "high"


def _product_line_statement(entry: dict[str, Any], lot: str | None) -> str:
    lots = entry.get("lots_shown") or []
    listed = ", ".join(str(item) for item in lots[:8]) if lots else "no specific lots"
    head = (
        f"A recall exists for this product line: \"{entry.get('title')}\" "
        f"({entry.get('source_org') or 'regulator'}). It names {listed}"
    )
    if entry.get("lot_count", 0) > 8:
        head += f" and {entry['lot_count'] - 8} more"
    head += "."
    if not lot:
        return head + " No lot number was read from this label, so it cannot be compared."
    if lot in {str(item) for item in lots}:
        return head + f" The label's lot {lot} is on that list."
    if entry.get("covers_all_lots"):
        return head + f" It covers all lots, so the label's lot {lot} is in scope."
    if entry.get("lot_count", 0) > len(lots):
        return (
            head
            + f" The label's lot {lot} is not among the lots shown here, but the full list is "
            "longer than what is stored; compare it with the notice itself."
        )
    return head + f" The label's lot {lot} is not on that list."


def _lists_lot(entry: dict[str, Any], lot: str | None) -> bool:
    """Exact normalised equality only.

    F12: `H02605` and `H026051MFG` differ by an extraction artefact, and a near
    match must never be presented as evidence that this lot was recalled.
    """
    wanted = normalize.normalize_lot(lot)
    if not wanted:
        return False
    return wanted in {
        normalize.normalize_lot(item) for item in entry.get("lots_shown") or []
    }


def _is_regulator_alert(entry: dict[str, Any], label: dict[str, Any]) -> bool:
    if entry.get("source_tier") != "regulator":
        return False
    if not _WEB_ADVERSE_FLAGS & set(entry.get("flags") or []):
        return False
    label_tokens = _name_tokens(label.get("drug_names") or [])
    if not label_tokens:
        return False
    page_tokens = _name_tokens(entry.get("drug_names") or []) | _tokens(
        normalize.normalize_drug_name(entry.get("title"))
    )
    return bool(label_tokens & page_tokens)


def rank_web_hits(evidence: dict[str, Any], label: dict[str, Any]) -> list[dict[str, Any]]:
    """Pages naming this lot first, then regulator alerts about this drug."""
    entries = list(evidence.get("web_hits") or [])
    lot = label.get("lot")

    def rank(entry: dict[str, Any]) -> tuple[int, int]:
        if _lists_lot(entry, lot):
            tier = 0
        elif _is_regulator_alert(entry, label):
            tier = 1
        elif entry.get("source_tier") == "regulator":
            tier = 2
        else:
            tier = 3
        return tier, entry.get("age_days") if entry.get("age_days") is not None else 10_000

    return sorted(entries, key=rank)


def _web_statement(entry: dict[str, Any], lot: str | None) -> str:
    head = f"{entry.get('domain')} page \"{entry.get('title')}\"{_age_note(entry)}"
    if entry.get("date_precision") == "fetched":
        head += " (no publication date; age is since this page was first seen)"
    if _lists_lot(entry, lot):
        return (
            f"{head} independently lists lot {lot}, the lot read from this label, among the "
            "affected batches."
        )
    if entry.get("source_tier") == "regulator":
        flags = ", ".join(sorted(_WEB_ADVERSE_FLAGS & set(entry.get("flags") or [])))
        if flags:
            return f"{head} is a regulator page mentioning {flags} for this medicine."
    return f"{head}. {entry.get('summary') or ''}".strip()


def _hardware_finding(hardware: dict[str, Any]) -> Finding | None:
    status = hardware.get("status")
    measurements = hardware.get("measurements")
    if measurements:
        return Finding(statement=measurement_sentence(measurements), evidence_type="hardware_result",
                       source_ids=[], severity="info", country_scope=None)
    if not status or status == "unknown":
        return None
    kind = hardware.get("pill_type")
    statement = f'The hardware step reported status "{status}"'
    statement += f" for {kind}." if kind else "."
    if hardware.get("simulated"):
        # Never let this read as a measurement of what is in the tablet.
        statement += f" {hardware.get('limitations') or MOCK_LIMITATION}"
    statement += " It reports no potency figure and does not identify a contaminant."
    return Finding(
        statement=statement,
        evidence_type="hardware_result",
        source_ids=[],
        severity="caution" if status in _HARDWARE_ADVERSE else "info",
        country_scope=None,
    )


def _corroboration_finding(
    hardware: dict[str, Any], evidence: dict[str, Any]
) -> Finding | None:
    """Two weak-but-independent signals agreeing is worth saying, and only that."""
    if hardware.get("status") not in _HARDWARE_ADVERSE:
        return None
    recalls = qualifying_lot_hits(evidence) or _qualifying_all_lots(evidence)
    if not recalls:
        return None
    simulated = (
        " The hardware reading is simulated, so it adds no measurement here."
        if hardware.get("simulated")
        else ""
    )
    return Finding(
        statement=(
            f'The hardware step reported "{hardware.get("status")}" and a recall record names '
            "this product independently, so two separate signals point the same way. That is not "
            f"proof that this particular tablet is falsified or substandard.{simulated}"
        ),
        evidence_type="hardware_result",
        source_ids=[str(entry.get("record_id")) for entry in recalls[:2] if entry.get("record_id")],
        severity="serious",
        country_scope=None,
    )


def _gaps(label: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not label.get("lot"):
        gaps.append("No lot or batch number was read from the label, so lot-level recalls could not be checked.")
    if not (label.get("ndc9") or label.get("ndc11")):
        gaps.append("No NDC was read from the label, so the product could not be matched to the FDA directory.")
    if not label.get("imprint_norm"):
        gaps.append("No pill imprint was read, so the tablet could not be compared with the imprint reference.")
    elif not (evidence.get("pill") or {}).get("candidates"):
        gaps.append(
            "The imprint matched nothing in the US Pillbox archive, which was frozen in January "
            "2021 and never covered non-US products."
        )
    if not evidence.get("web_hits"):
        gaps.append("No live web pages were available for this medicine during this scan.")
    if evidence.get("recall_lookup_failed"):
        gaps.append(RECALL_LOOKUP_FAILED_GAP)
    gaps.append("What is actually inside the tablet was not measured.")
    return gaps


def _headline(
    verdict: str, label: dict[str, Any], evidence: dict[str, Any], mismatches: int
) -> str:
    if verdict == "recall_match":
        if qualifying_lot_hits(evidence):
            return f"A recall or safety alert names lot {label.get('lot')} from this label."
        return "A recall covering every lot of this product matches this label."
    if verdict == "mismatch_found":
        noun = "point" if mismatches == 1 else "points"
        return f"The label and the reference records disagree on {mismatches} {noun}."
    if verdict == "insufficient_evidence":
        if (evidence.get("hardware") or {}).get("measurements"):
            return "Sensor readings recorded; the medicine's identity is not established."
        return "There was not enough readable detail on the label or the pill to check this."
    return "No matching recall or safety alert was found in the records searched."


def _drug_facts(
    label: dict[str, Any], evidence: dict[str, Any], sources: dict[str, SourceRef]
) -> list[DrugFact]:
    """Content for the ElevenLabs contract, keyed off the normalised generic name."""
    medication_id = (
        label.get("generic_name") or label.get("brand_name") or _first(label.get("drug_names")) or "unknown"
    )
    facts: list[DrugFact] = []

    recall_entry = _first(qualifying_lot_hits(evidence)) or _first(
        _qualifying_all_lots(evidence)
    ) or _first(evidence.get("ndc_hits"))
    if recall_entry:
        ref_id = str(recall_entry.get("record_id"))
        facts.append(
            DrugFact(
                medication_id=str(medication_id),
                topic="recall",
                text=_short(
                    f"{recall_entry.get('source_org') or 'A regulator'} published "
                    f"\"{recall_entry.get('title')}\"{_age_note(recall_entry)}. "
                    f"{recall_entry.get('summary') or ''}"
                )
                or "",
                source_ids=[ref_id] if ref_id in sources else [],
            )
        )

    counterfeit = _first(
        [
            entry
            for entry in (evidence.get("web_hits") or [])
            if {"counterfeit", "falsified", "substandard"} & set(entry.get("flags") or [])
        ]
    ) or _first(
        [
            entry
            for entry in (evidence.get("regulatory_hits") or [])
            if entry.get("doc_type") in ("falsified_alert", "substandard_alert")
        ]
    )
    if counterfeit:
        ref_id = str(counterfeit.get("source_id") or counterfeit.get("record_id"))
        facts.append(
            DrugFact(
                medication_id=str(medication_id),
                topic="counterfeit_reports",
                text=_short(
                    f"Reported falsified or substandard product: \"{counterfeit.get('title')}\""
                    f"{_age_note(counterfeit)}. {counterfeit.get('summary') or ''}"
                )
                or "",
                source_ids=[ref_id] if ref_id in sources else [],
            )
        )

    candidate = _first((evidence.get("pill") or {}).get("candidates"))
    if candidate:
        ref_id = str(candidate.get("source_id"))
        facts.append(
            DrugFact(
                medication_id=str(candidate.get("medication_id") or medication_id),
                topic="identification",
                text=_short(
                    f"The US Pillbox archive lists imprint {candidate.get('imprint')} as "
                    f"{candidate.get('generic_name')} {candidate.get('strength') or ''}, "
                    f"{candidate.get('shape') or 'unknown shape'}, made by "
                    f"{candidate.get('labeler') or 'an unlisted labeler'}. Pillbox was frozen in "
                    "January 2021."
                )
                or "",
                source_ids=[ref_id] if ref_id in sources else [],
            )
        )
    return facts


# --------------------------------------------------------------------------- guardrails


def web_source_id(page_id: str) -> str:
    return f"web-{str(page_id)[:12]}"


def allowed_source_ids(
    evidence: dict[str, Any],
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    page_ids: Sequence[str] | None = None,
) -> set[str]:
    """Every string that resolves to a citable source: canonical ids and aliases."""
    refs, aliases = source_index(evidence, tool_calls=tool_calls, page_ids=page_ids)
    return set(refs) | set(aliases)


def source_index(
    evidence: dict[str, Any],
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    page_ids: Sequence[str] | None = None,
) -> tuple[dict[str, SourceRef], dict[str, str]]:
    """Canonical id -> SourceRef, plus an alias table of ids a model might write.

    The model chooses *which* sources to cite; it never supplies their metadata.
    A title it retyped comes back with mangled escapes, and an id it retyped is
    often the raw page id, so both are rebuilt from the evidence here.
    """
    refs: dict[str, SourceRef] = {}
    aliases: dict[str, str] = {}

    def add(ref: SourceRef, *extra: object) -> None:
        refs.setdefault(ref.id, ref)
        for value in (ref.id, ref.url, *extra):
            text = str(value).strip() if value else ""
            if text:
                aliases.setdefault(text, ref.id)
                aliases.setdefault(text.casefold(), ref.id)

    for key in ("exact_lot_hits", "all_lots_hits", "ndc_hits", "regulatory_hits"):
        for entry in evidence.get(key) or []:
            add(_reg_source(entry))
    for entry in evidence.get("web_hits") or []:
        page_id = str(entry.get("page_id") or "")
        add(_web_source(entry), page_id, f"web-{page_id}")
    for entry in evidence.get("ndc_directory") or []:
        add(_ndc_source(entry), entry.get("product_ndc"))
    for candidate in (evidence.get("pill") or {}).get("candidates") or []:
        add(_pill_source(candidate))
    for row in _tool_rows(tool_calls):
        ref = _row_source(row)
        if ref is not None:
            add(ref, row.get("page_id"), row.get("record_id"))
    for page_id in page_ids or []:
        text = str(page_id)
        add(
            SourceRef(
                id=web_source_id(text),
                title="Web page fetched during this scan",
                url=None,
                source_org=None,
                published_at=None,
                label_date=None,
            ),
            text,
            f"web-{text}",
        )
    return refs, aliases


def _tool_rows(tool_calls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call in tool_calls or []:
        for row in (call or {}).get("rows") or []:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _row_source(row: dict[str, Any]) -> SourceRef | None:
    if row.get("record_id"):
        return SourceRef(
            id=str(row["record_id"]),
            title=str(row.get("title") or row["record_id"]),
            url=row.get("url"),
            source_org=row.get("source_org"),
            published_at=_date_only(row.get("recency_date")),
            label_date=_date_only(row.get("recency_date")),
        )
    if row.get("page_id"):
        return SourceRef(
            id=web_source_id(str(row["page_id"])),
            title=str(row.get("title") or row.get("domain") or "Web page"),
            url=row.get("url"),
            source_org=row.get("domain"),
            published_at=_date_only(row.get("published_at")),
            label_date=_date_only(row.get("published_at")),
        )
    return None


def resolve_source_id(
    value: object, refs: dict[str, SourceRef], aliases: dict[str, str]
) -> str | None:
    """One id as the model wrote it -> the canonical id, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.casefold()):
        if candidate in aliases:
            return aliases[candidate]
    # A raw page id, or `web-` plus the full hash instead of the first twelve.
    bare = text[4:] if text.lower().startswith("web-") else text
    for candidate in (web_source_id(bare), ndc_source_id(bare)):
        if candidate in refs:
            return candidate
    return None


def enforce_guardrails(
    report: ResearchReport,
    evidence: dict[str, Any],
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    page_ids: Sequence[str] | None = None,
) -> ResearchReport:
    """Everything the model wrote, checked against what the evidence supports."""
    refs, aliases = source_index(evidence, tool_calls=tool_calls, page_ids=page_ids)
    # Before any text check: a stray control byte could split a banned word.
    data = _scrub_strings(report.model_dump())

    verdict, risk = verdict_from_evidence(evidence, has_mismatch=bool(data.get("mismatches")))
    upgraded = False
    if data.get("verdict") == "recall_match" and verdict != "recall_match":
        # F2/F12: a product-line or fuzzy match is never a recall for this bottle.
        data["verdict"], data["risk_level"] = verdict, risk
        data["headline"] = NEUTRAL_HEADLINES[verdict]
        data["recall_hits"] = []
    elif verdict == "recall_match" and data.get("verdict") != "recall_match":
        # F10: reporting a named-lot recall as "nothing found" is the worst failure
        # here. The whole recall side of the report is rebuilt below, because the
        # model wrote its findings, sources and next steps for the wrong verdict.
        upgraded = True
        data["verdict"], data["risk_level"] = verdict, risk
    elif data.get("verdict") == "no_adverse_findings" and evidence.get("recall_lookup_failed"):
        # A lookup that never ran cannot support "I found nothing".
        data["verdict"], data["risk_level"] = "insufficient_evidence", "unknown"
        data["headline"] = NEUTRAL_HEADLINES["insufficient_evidence"]

    data["findings"] = _clean_findings(data.get("findings") or [], refs, aliases)
    data["mismatches"] = [
        item
        | {
            "source_ids": _keep_ids(item.get("source_ids"), refs, aliases),
            # The field and the two claims are real evidence even when the
            # explanation is not sayable, so neutralise the text, not the row.
            "explanation": _safe_explanation(item.get("explanation")),
        }
        for item in data.get("mismatches") or []
    ]
    data["drug_facts"] = [
        item | {"source_ids": _keep_ids(item.get("source_ids"), refs, aliases)}
        for item in data.get("drug_facts") or []
        if not _unsafe(str(item.get("text") or ""))
    ]
    data["sources"] = _rebuild_sources(data, refs, aliases)
    data["recall_hits"] = [
        refs[canonical].model_dump()
        for canonical in _resolved_ids(
            [item.get("id") for item in data.get("recall_hits") or []], refs, aliases
        )
    ]
    data["next_steps"] = [
        step for step in data.get("next_steps") or [] if not _unsafe(str(step))
    ]
    data["gaps"] = [gap for gap in data.get("gaps") or [] if not _unsafe(str(gap))]

    if upgraded:
        # deterministic_report reads the label straight out of the pack, so it is
        # the one source of truth for what a recall_match report must say.
        fallback = deterministic_report(
            {}, evidence, index_date=str(evidence.get("index_date") or "")
        )
        data["headline"] = fallback.headline
        data["findings"] = [item.model_dump() for item in fallback.findings]
        data["recall_hits"] = [item.model_dump() for item in fallback.recall_hits]
        data["sources"] = [item.model_dump() for item in fallback.sources]
        data["next_steps"] = list(_RECALL_NEXT_STEPS)

    headline = str(data.get("headline") or "")
    if _unsafe(headline):
        data["headline"] = NEUTRAL_HEADLINES[data["verdict"]]

    index_date = str(evidence.get("index_date") or "the latest records indexed")
    if data["verdict"] == "no_adverse_findings":
        _ensure_safe_wording(data, index_date)
    if not data["next_steps"]:
        data["next_steps"] = list(
            _RECALL_NEXT_STEPS if data["verdict"] == "recall_match" else _SAFE_NEXT_STEPS
        )
    measured = (evidence.get("hardware") or {}).get("measurements")
    if measured:
        fact = _hardware_finding(evidence["hardware"])
        if fact and not any(item.get("statement") == fact.statement for item in data["findings"]):
            data["findings"].append(fact.model_dump())
        if data["verdict"] == "insufficient_evidence":
            data["headline"] = "Sensor readings recorded; the medicine's identity is not established."
    return ResearchReport.model_validate(data)


def _clean_findings(
    findings: list[dict[str, Any]],
    refs: dict[str, SourceRef],
    aliases: dict[str, str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in findings:
        statement = str(item.get("statement") or "")
        if _unsafe(statement):
            continue
        kept = _keep_ids(item.get("source_ids"), refs, aliases)
        # A claim with no citation left is a claim with no evidence. The
        # exemptions are the claims that legitimately have no external source:
        # the device reading, the label itself, crowd signal, and the required
        # "nothing found" disclaimer.
        if not kept and item.get("evidence_type") not in _UNSOURCED_OK:
            if DISCLAIMER_MARKER not in statement:
                continue
        out.append(item | {"source_ids": kept})
    return out


def _keep_ids(ids: Any, refs: dict[str, SourceRef], aliases: dict[str, str]) -> list[str]:
    return _resolved_ids(list(ids or []), refs, aliases)


def _resolved_ids(
    ids: Sequence[Any], refs: dict[str, SourceRef], aliases: dict[str, str]
) -> list[str]:
    out: list[str] = []
    for value in ids:
        canonical = resolve_source_id(value, refs, aliases)
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def _rebuild_sources(
    data: dict[str, Any], refs: dict[str, SourceRef], aliases: dict[str, str]
) -> list[dict[str, Any]]:
    """Canonical metadata only, and one entry for every id still cited."""
    ids = _resolved_ids([item.get("id") for item in data.get("sources") or []], refs, aliases)
    for group in ("findings", "mismatches", "drug_facts"):
        for item in data.get(group) or []:
            for value in item.get("source_ids") or []:
                if value in refs and value not in ids:
                    ids.append(value)
    return [refs[value].model_dump() for value in ids]


def _unsafe(text: str) -> bool:
    return bool(_positive_assurance(text) or _PII_RE.search(text) or _stop_advice(text))


_STOP_RE = re.compile(r"\bstop\s+(?:taking|using)\b|\bdiscontinue\s+(?:taking|the)\b", re.I)


def _stop_advice(text: str) -> bool:
    return bool(_STOP_RE.search(text))


def _positive_assurance(text: str) -> bool:
    """A banned word is a claim unless its own clause negates it first.

    Clause scope, not sentence scope: "No recall was found, so this medicine is
    genuine" negates the recall, not the assurance that follows it. The one
    sentence that must survive intact is the mandated disclaimer, which is
    allowlisted by its marker rather than by the "not" inside it.
    """
    if DISCLAIMER_MARKER in text:
        return False
    for sentence in _SENTENCE_RE.split(text):
        for clause in _CLAUSE_RE.split(sentence):
            for match in _BANNED_RE.finditer(clause):
                if _NEGATION_RE.search(clause[: match.start()]) is None:
                    return True
    return False


_NEUTRAL_MISMATCH_EXPLANATION = (
    "The label and the reference records disagree on this field; ask a pharmacist to compare them."
)


def _safe_explanation(value: object) -> str:
    text = str(value or "")
    return text if not _unsafe(text) else _NEUTRAL_MISMATCH_EXPLANATION


def scrub_controls(text: str) -> str:
    return _CONTROL_RE.sub("", text)


def _scrub_strings(node: Any) -> Any:
    if isinstance(node, str):
        return scrub_controls(node)
    if isinstance(node, dict):
        return {key: _scrub_strings(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub_strings(value) for value in node]
    return node


def _scrubbed(report: ResearchReport) -> ResearchReport:
    return ResearchReport.model_validate(_scrub_strings(report.model_dump()))


def _ensure_safe_wording(data: dict[str, Any], index_date: str) -> None:
    text = SAFE_NO_FINDINGS_TEXT.format(index_date=index_date)
    marker = DISCLAIMER_MARKER
    blob = " ".join(
        [str(f.get("statement") or "") for f in data["findings"]] + [str(s) for s in data["next_steps"]]
    )
    if marker in blob:
        return
    data["findings"].append(
        {
            "statement": text,
            "evidence_type": "regulatory_record",
            "source_ids": [],
            "severity": "info",
            "country_scope": None,
        }
    )


# --------------------------------------------------------------------------- helpers


def _reg_source(entry: dict[str, Any]) -> SourceRef:
    return SourceRef(
        id=str(entry.get("record_id")),
        title=str(entry.get("title") or entry.get("record_id") or "Regulatory record"),
        url=entry.get("url"),
        source_org=entry.get("source_org"),
        published_at=_date_only(entry.get("recency_date")),
        label_date=_date_only(entry.get("recency_date")),
    )


def _web_source(entry: dict[str, Any]) -> SourceRef:
    return SourceRef(
        id=str(entry.get("source_id") or web_source_id(str(entry.get("page_id")))),
        title=str(entry.get("title") or entry.get("domain") or "Web page"),
        url=entry.get("url"),
        source_org=entry.get("source_org") or entry.get("domain"),
        published_at=_date_only(entry.get("recency_date")),
        label_date=_date_only(entry.get("recency_date")),
    )


def _pill_source(candidate: dict[str, Any]) -> SourceRef:
    return SourceRef(
        id=str(candidate.get("source_id")),
        title=f"US Pillbox reference: imprint {candidate.get('imprint')}",
        # Pillbox itself is retired; the label it was built from lives on DailyMed.
        url=(
            f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={candidate['setid']}"
            if candidate.get("setid")
            else None
        ),
        source_org="NLM Pillbox (archived January 2021)",
        published_at=None,
        label_date="2021-01",
    )


def ndc_source_id(product_ndc: str) -> str:
    return f"ndc-{product_ndc}"


def _ndc_source(entry: dict[str, Any]) -> SourceRef:
    product_ndc = str(entry.get("product_ndc"))
    return SourceRef(
        id=ndc_source_id(product_ndc),
        title=f"FDA NDC directory: {product_ndc}",
        # A citable page a person can actually open, not a bare code.
        url=f"{DAILYMED_SEARCH_URL}?labeltype=all&query={quote(product_ndc)}",
        source_org="FDA",
        published_at=None,
        label_date=None,
    )


def _age_note(entry: dict[str, Any]) -> str:
    age = entry.get("age_days")
    if age is None:
        return ""
    if age >= 365:
        return f", published about {age // 365} year(s) ago"
    return f", {entry.get('freshness') or 'age unknown'}"


def _date_only(value: object) -> str | None:
    text = normalize.clean_text(value)
    return text.split("T")[0] if text else None


def _short(value: object) -> str | None:
    text = normalize.clean_text(value)
    return normalize.truncate_on_sentence(text, MAX_SUMMARY_CHARS) if text else None


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _first(values: object) -> Any:
    items = _as_list(values)
    return items[0] if items else None


def _tokens(name: str | None) -> set[str]:
    return {token for token in (name or "").split() if len(token) >= 4}


def _name_tokens(names: Sequence[Any]) -> set[str]:
    out: set[str] = set()
    for raw in names:
        out |= _tokens(normalize.normalize_drug_name(raw))
    return out
