"""The evidence pack, the deterministic verdict table and the guardrails.

These are the safety tests: a product-line NDC hit must never become
`recall_match` (audit_redteam F2), an invented source id must never survive,
and a "nothing found" answer must carry the exact required disclaimer.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.knowledge.fields import Ndc, Pill, Reg, Web
from backend.knowledge.search import Hit, PillMatch
from backend.pill import HARDWARE_MODEL
from backend.research.evidence import (
    MAX_EVIDENCE_CHARS,
    MAX_WEB_FINDINGS,
    NEUTRAL_HEADLINES,
    allowed_source_ids,
    build_evidence,
    derive_mismatches,
    deterministic_report,
    enforce_guardrails,
    evidence_size,
    pill_candidates,
)
from backend.research.models import SAFE_NO_FINDINGS_TEXT, Finding, ResearchReport, SourceRef
from backend.research.rxnav import NdcStatus

INDEX_DATE = "2026-09-19"
DISCLAIMER_MARKER = "That is not a confirmation"


def scan(**norm: Any) -> dict[str, Any]:
    base = {
        "lot": None,
        "ndc9": None,
        "ndc11": None,
        "imprint_norm": None,
        "shape": None,
        "colors": [],
        "drug_names": [],
        "generic_name": None,
        "brand_name": None,
        "strength": None,
        "manufacturer": None,
        "dosage_form": "tablet",
        "expiration": None,
        "expired": None,
    }
    return {"scan_id": "scan-1", "demo": False, "country": "Nigeria", "norm": base | norm}


def with_hardware(doc: dict[str, Any], **hardware: Any) -> dict[str, Any]:
    # What scans.normalizer.hardware_doc actually stores for the mock device.
    base = {
        "status": "substandard",
        "pill_type": "levothyroxine",
        "degraded": True,
        "model": HARDWARE_MODEL,
    }
    return doc | {"hardware": base | hardware}


def reg_hit(
    record_id: str = "fda-D-0785-2026",
    *,
    lots: list[str] | None = None,
    covers_all: bool = False,
    severity: str = "high",
    match_kind: str = "exact_lot",
    drug: str = "levothyroxine",
) -> Hit:
    return Hit(
        index="peel-regulatory",
        id=record_id,
        score=1.0,
        source={
            Reg.RECORD_ID: record_id,
            Reg.SOURCE_ORG: "FDA",
            Reg.DOC_TYPE: "recall",
            Reg.TITLE: "Levothyroxine tablets recall",
            Reg.SUMMARY: "Subpotent tablets.",
            Reg.SEVERITY: severity,
            Reg.STATUS: "ongoing",
            Reg.DRUG_NAMES: [drug],
            Reg.MANUFACTURER: "Accord Healthcare",
            Reg.COUNTRIES: ["United States"],
            Reg.LOT_NUMBERS: lots or [],
            Reg.COVERS_ALL_LOTS: covers_all,
            Reg.RECENCY_DATE: "2026-06-01T00:00:00Z",
            Reg.URL: "https://www.fda.gov/x",
        },
        match_kind=match_kind,
        age_days=110,
        freshness="this_year",
    )


def pill_match(generic: str = "levothyroxine sodium", kind: str = "imprint_exact", relaxed: bool = False) -> PillMatch:
    hit = Hit(
        index="peel-pills",
        id="pill-1",
        score=1.0,
        source={
            Pill.PILL_ID: "pill-1",
            Pill.IMPRINT_RAW: "M L 8",
            Pill.SHAPE: "round",
            Pill.COLORS: ["white"],
            Pill.GENERIC_NAME: generic,
            Pill.MEDICINE_NAME: generic,
            Pill.STRENGTH: "200 mcg",
            Pill.LABELER: "Mylan",
            Pill.PRODUCT_NDC: "00378-1810",
        },
        match_kind=kind,
    )
    return PillMatch(hits=[hit], rung=2 if relaxed else 1, shape_relaxed=relaxed, filters_applied={})


def ndc_hit(generic: str = "levothyroxine sodium", labeler: str = "Accord Healthcare") -> Hit:
    return Hit(
        index="peel-ndc",
        id="16729-457",
        score=1.0,
        source={
            Ndc.PRODUCT_NDC: "16729-457",
            Ndc.NDC9: "167290457",
            Ndc.GENERIC_NAME: generic,
            Ndc.BRAND_NAME: generic,
            Ndc.LABELER_NAME: labeler,
            Ndc.ACTIVE_INGREDIENT_NAMES: [generic],
            Ndc.STRENGTHS: ["200 mcg"],
            Ndc.DOSAGE_FORM: "tablet",
        },
        match_kind="ndc_directory",
    )


def web_hit(
    page_id: str = "abcdef0123456789",
    flags: list[str] | None = None,
    *,
    lots: list[str] | None = None,
    tier: str = "regulator",
    domain: str = "who.int",
    drug_names: list[str] | None = None,
    age_days: int = 9,
) -> Hit:
    return Hit(
        index="peel-web-pages",
        id=page_id,
        score=1.0,
        source={
            Web.PAGE_ID: page_id,
            Web.URL: f"https://{domain}/alert",
            Web.DOMAIN: domain,
            Web.SOURCE_TIER: tier,
            Web.TITLE: "WHO medical product alert for levothyroxine",
            Web.DESCRIPTION: "Falsified product reported.",
            Web.FLAGS: flags or ["falsified"],
            Web.LOT_NUMBERS: lots if lots is not None else ["H02605"],
            Web.DRUG_NAMES: drug_names if drug_names is not None else ["levothyroxine"],
            Web.RECENCY_DATE: "2026-09-10T00:00:00Z",
            Web.DATE_PRECISION: "published",
        },
        match_kind="web_hybrid",
        age_days=age_days,
        freshness="this_month",
    )


def pack(doc: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return build_evidence(doc, index_date=INDEX_DATE, **kwargs)


# --------------------------------------------------------------------------- pack shape


def test_the_pack_compacts_hits_and_stays_small() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine", imprint_norm="ML8")
    evidence = pack(
        doc,
        exact_lot_hits=[reg_hit(lots=["D2402430"])],
        pill=pill_match(),
        web_hits=[web_hit()],
        prior_scans={"total": 4, "by_verdict": {"recall_match": 4}},
    )

    entry = evidence["exact_lot_hits"][0]
    assert entry["record_id"] == "fda-D-0785-2026"
    assert entry["lots_shown"] == ["D2402430"] and entry["lot_count"] == 1
    assert entry["age_days"] == 110 and entry["freshness"] == "this_year"
    assert evidence["web_hits"][0]["source_id"] == "web-abcdef012345"
    assert evidence["label"]["lot"] == "D2402430"
    assert evidence_size(evidence) <= MAX_EVIDENCE_CHARS


def test_an_oversized_pack_is_trimmed_to_the_cap() -> None:
    doc = scan(generic_name="levothyroxine")
    big = reg_hit()
    big.source[Reg.SUMMARY] = "x" * 4000
    evidence = pack(doc, regulatory_hits=[big] * 40, web_hits=[web_hit()] * 40)

    assert evidence_size(evidence) <= MAX_EVIDENCE_CHARS
    assert evidence["regulatory_hits"]


def test_pill_candidates_match_the_scan_context_contract() -> None:
    evidence = pack(scan(imprint_norm="ML8"), pill=pill_match())

    candidate = pill_candidates(evidence, "tablet")[0]
    assert set(candidate) == {"generic_name", "strength", "form", "source_id", "medication_id"}
    assert candidate["source_id"] == "pill-1"
    assert candidate["form"] == "tablet"


# --------------------------------------------------------------------------- verdict table


def test_an_exact_lot_hit_is_a_recall_match_at_high_risk() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])])

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    assert report.verdict == "recall_match"
    assert report.risk_level == "high"
    assert report.recall_hits[0].id == "fda-D-0785-2026"
    assert any(f.evidence_type == "exact_lot_match" for f in report.findings)
    assert "D2402430" in report.headline


def test_a_moderate_severity_lot_hit_is_medium_risk() -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["AB1234"], severity="moderate")])

    assert deterministic_report(doc, evidence, index_date=INDEX_DATE).risk_level == "medium"


def test_a_product_line_ndc_hit_is_never_a_recall_match() -> None:
    doc = scan(lot="Z9999", ndc9="167290457", generic_name="levothyroxine")
    sibling = reg_hit(lots=["D2402430", "D2402431"], match_kind="product_line_match")
    evidence = pack(doc, ndc_hits=[sibling])

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    assert report.verdict != "recall_match"
    caution = [f for f in report.findings if f.evidence_type == "exact_ndc_match"]
    assert caution and caution[0].severity == "caution"
    assert "D2402430" in caution[0].statement
    assert "Z9999 is not on that list" in caution[0].statement


def test_an_all_lots_recall_naming_the_ndc_is_a_recall_match() -> None:
    doc = scan(ndc9="167290457", generic_name="levothyroxine")
    hit = reg_hit(covers_all=True, match_kind="ndc_in_description")
    evidence = pack(doc, ndc_hits=[hit])

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    assert report.verdict == "recall_match"
    assert "every lot" in report.headline


def test_a_mismatch_without_a_recall_is_mismatch_found() -> None:
    doc = scan(imprint_norm="ML8", drug_names=["metformin"], generic_name="metformin")
    evidence = pack(doc, pill=pill_match(generic="levothyroxine sodium"))

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    assert report.verdict == "mismatch_found"
    assert report.risk_level == "medium"
    assert report.mismatches[0].field == "imprint"


def test_an_unreadable_label_is_insufficient_evidence() -> None:
    doc = scan()
    report = deterministic_report(doc, pack(doc), index_date=INDEX_DATE)

    assert report.verdict == "insufficient_evidence"
    assert report.risk_level == "unknown"


def test_nothing_adverse_carries_the_required_disclaimer() -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine", drug_names=["levothyroxine"])
    report = deterministic_report(doc, pack(doc), index_date=INDEX_DATE)

    assert report.verdict == "no_adverse_findings"
    assert report.risk_level == "low"
    blob = " ".join([f.statement for f in report.findings] + report.next_steps)
    assert SAFE_NO_FINDINGS_TEXT.format(index_date=INDEX_DATE) in blob
    assert report.gaps


def test_next_steps_are_never_medical_advice() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])])

    steps = " ".join(deterministic_report(doc, evidence, index_date=INDEX_DATE).next_steps).lower()

    assert "stop taking" not in steps
    assert "pharmacist" in steps


def test_drug_facts_are_keyed_off_the_normalised_generic_name() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine", imprint_norm="ML8")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])], pill=pill_match())

    facts = deterministic_report(doc, evidence, index_date=INDEX_DATE).drug_facts

    assert {f.topic for f in facts} >= {"recall", "identification"}
    assert facts[0].medication_id == "levothyroxine"
    assert facts[0].source_ids == ["fda-D-0785-2026"]


def test_an_expired_label_is_a_finding_not_a_mismatch() -> None:
    doc = scan(
        generic_name="levothyroxine",
        drug_names=["levothyroxine"],
        expired=True,
        expiration="2024-01-31T00:00:00Z",
    )
    report = deterministic_report(doc, pack(doc), index_date=INDEX_DATE)

    assert not any(m.field == "strength" for m in report.mismatches)
    assert any("expiry" in f.statement for f in report.findings)


# --------------------------------------------------------------------------- mismatches


def test_ndc_registered_to_another_drug_is_an_identity_mismatch() -> None:
    doc = scan(ndc9="167290457", generic_name="metformin", drug_names=["metformin"])
    evidence = pack(doc, ndc_directory=[ndc_hit()])

    fields = [m["field"] for m in derive_mismatches(doc, evidence)]

    assert "ndc_identity" in fields


def test_a_relaxed_shape_filter_is_reported_as_a_shape_mismatch() -> None:
    doc = scan(imprint_norm="ML8", shape="oval", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(doc, pill=pill_match(relaxed=True))

    assert [m["field"] for m in derive_mismatches(doc, evidence)] == ["shape"]


def test_an_obsolete_ndc_is_an_identity_mismatch() -> None:
    doc = scan(ndc11="16729045701", generic_name="levothyroxine", drug_names=["levothyroxine"])
    status = NdcStatus(ndc11="16729045701", status="OBSOLETE", active=False, rxcui=None, concept_name=None)
    evidence = pack(doc, ndc_status=status)

    mismatch = derive_mismatches(doc, evidence)[0]
    assert mismatch["field"] == "ndc_identity"
    assert "OBSOLETE" in mismatch["explanation"]


def test_a_matching_imprint_reference_is_not_a_mismatch() -> None:
    doc = scan(imprint_norm="ML8", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(doc, pill=pill_match(generic="levothyroxine sodium"))

    assert derive_mismatches(doc, evidence) == []


# --------------------------------------------------------------------------- guardrails


def llm_report(**kwargs: Any) -> ResearchReport:
    base: dict[str, Any] = {
        "verdict": "no_adverse_findings",
        "risk_level": "low",
        "headline": "Nothing adverse was found.",
        "findings": [],
        "mismatches": [],
        "recall_hits": [],
        "gaps": [],
        "next_steps": ["Ask a pharmacist to check the medicine with its packaging."],
        "drug_facts": [],
        "sources": [],
        "agent_used": True,
        "demo": False,
    }
    return ResearchReport.model_validate(base | kwargs)


def test_an_unsupported_recall_match_is_downgraded() -> None:
    doc = scan(ndc9="167290457", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(doc, ndc_hits=[reg_hit(lots=["D2402430"], match_kind="product_line_match")])
    report = llm_report(
        verdict="recall_match",
        risk_level="high",
        recall_hits=[
            SourceRef(
                id="fda-D-0785-2026", title="t", url=None, source_org="FDA",
                published_at=None, label_date=None,
            )
        ],
    )

    guarded = enforce_guardrails(report, evidence)

    assert guarded.verdict == "no_adverse_findings"
    assert guarded.recall_hits == []
    assert guarded.headline != report.headline


def test_a_supported_recall_match_survives() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])])
    report = llm_report(verdict="recall_match", risk_level="high", headline="Lot D2402430 is recalled.")

    guarded = enforce_guardrails(report, evidence)

    assert guarded.verdict == "recall_match"
    assert guarded.headline == "Lot D2402430 is recalled."


def test_a_missed_lot_recall_is_upgraded() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])])

    guarded = enforce_guardrails(llm_report(), evidence)

    assert guarded.verdict == "recall_match"
    assert guarded.risk_level == "high"


def test_invented_source_ids_are_stripped_and_unsupported_findings_dropped() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine")
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])])
    report = llm_report(
        verdict="recall_match",
        findings=[
            Finding(
                statement="Real citation.",
                evidence_type="exact_lot_match",
                source_ids=["fda-D-0785-2026", "fda-INVENTED-1"],
                severity="serious",
                country_scope=None,
            ),
            Finding(
                statement="Invented citation only.",
                evidence_type="web_page",
                source_ids=["web-deadbeefdead"],
                severity="info",
                country_scope=None,
            ),
        ],
        sources=[
            SourceRef(id="fda-D-0785-2026", title="t", url=None, source_org="FDA", published_at=None, label_date=None),
            SourceRef(id="fda-INVENTED-1", title="t", url=None, source_org="FDA", published_at=None, label_date=None),
        ],
    )

    guarded = enforce_guardrails(report, evidence)

    assert [f.statement for f in guarded.findings] == ["Real citation."]
    assert guarded.findings[0].source_ids == ["fda-D-0785-2026"]
    assert [s.id for s in guarded.sources] == ["fda-D-0785-2026"]


@pytest.mark.parametrize(
    "headline",
    [
        "This medicine is genuine.",
        "The tablet appears authentic and safe.",
        "Verified against the FDA directory.",
    ],
)
def test_assurance_headlines_are_replaced_with_a_neutral_template(headline: str) -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine")
    evidence = pack(doc)

    guarded = enforce_guardrails(llm_report(headline=headline), evidence)

    assert guarded.headline != headline
    assert guarded.headline in NEUTRAL_HEADLINES.values()


def test_the_required_disclaimer_is_never_scrubbed_as_an_assurance() -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine")
    evidence = pack(doc)
    report = llm_report(
        findings=[
            Finding(
                statement=SAFE_NO_FINDINGS_TEXT.format(index_date=INDEX_DATE),
                evidence_type="regulatory_record",
                source_ids=[],
                severity="info",
                country_scope=None,
            )
        ]
    )

    guarded = enforce_guardrails(report, evidence)

    assert len(guarded.findings) == 1
    assert DISCLAIMER_MARKER in guarded.findings[0].statement


def test_a_missing_disclaimer_is_added_back() -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine")

    guarded = enforce_guardrails(llm_report(), pack(doc))

    blob = " ".join(f.statement for f in guarded.findings)
    assert DISCLAIMER_MARKER in blob


def test_assurance_and_stop_advice_are_dropped_from_findings_and_steps() -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine")
    report = llm_report(
        findings=[
            Finding(
                statement="This tablet is genuine.",
                evidence_type="imprint_reference",
                source_ids=[],
                severity="info",
                country_scope=None,
            )
        ],
        next_steps=["Stop taking this medicine immediately.", "Ask a pharmacist to check it."],
    )

    guarded = enforce_guardrails(report, pack(doc))

    assert "This tablet is genuine." not in [f.statement for f in guarded.findings]
    assert all("Stop taking" not in step for step in guarded.next_steps)
    assert guarded.next_steps == ["Ask a pharmacist to check it."]


def test_prescription_details_are_dropped_from_the_report() -> None:
    doc = scan(lot="AB1234", generic_name="levothyroxine")
    report = llm_report(
        headline="Rx # 8827341 was dispensed at the pharmacy.",
        findings=[
            Finding(
                statement="The prescription number on the label matches the pharmacy record.",
                evidence_type="bottle_label",
                source_ids=[],
                severity="info",
                country_scope=None,
            )
        ],
    )

    guarded = enforce_guardrails(report, pack(doc))

    assert "8827341" not in guarded.headline
    assert all("prescription number" not in f.statement.lower() for f in guarded.findings)


def test_allowed_ids_cover_every_kind_of_evidence() -> None:
    doc = scan(lot="D2402430", ndc9="167290457", imprint_norm="ML8", generic_name="levothyroxine")
    evidence = pack(
        doc,
        exact_lot_hits=[reg_hit(lots=["D2402430"])],
        ndc_directory=[ndc_hit()],
        pill=pill_match(),
        web_hits=[web_hit()],
    )

    allowed = allowed_source_ids(evidence)

    assert {"fda-D-0785-2026", "16729-457", "pill-1", "web-abcdef012345"} <= allowed
    assert "fda-INVENTED-1" not in allowed


# --------------------------------------------------------------------------- report richness


def test_a_web_page_listing_the_label_lot_is_a_caution_finding_with_a_source() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(
        doc,
        exact_lot_hits=[reg_hit(lots=["D2402430"])],
        web_hits=[web_hit(page_id="aaaaaaaaaaaa1111", lots=["D2402430", "D2402431"])],
    )

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    web_findings = [f for f in report.findings if f.evidence_type == "web_page"]
    assert len(web_findings) == 1
    assert web_findings[0].severity == "caution"
    assert "independently lists lot D2402430" in web_findings[0].statement
    assert web_findings[0].source_ids == ["web-aaaaaaaaaaaa"]

    source = next(s for s in report.sources if s.id == "web-aaaaaaaaaaaa")
    assert source.url == "https://who.int/alert"
    assert source.published_at == "2026-09-10"


def test_lot_listing_pages_outrank_other_web_hits_and_cap_at_three() -> None:
    doc = scan(lot="D2402430", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(
        doc,
        web_hits=[
            web_hit(page_id="cccccccccccc3333", lots=[], tier="other", domain="blog.example"),
            web_hit(page_id="dddddddddddd4444", lots=[], tier="other", domain="news.example"),
            web_hit(page_id="eeeeeeeeeeee5555", lots=[], tier="other", domain="other.example"),
            web_hit(page_id="aaaaaaaaaaaa1111", lots=["D2402430"], domain="fda.gov"),
        ],
    )

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    web_findings = [f for f in report.findings if f.evidence_type == "web_page"]
    assert len(web_findings) == MAX_WEB_FINDINGS
    assert web_findings[0].source_ids == ["web-aaaaaaaaaaaa"]


def test_a_regulator_page_about_this_drug_is_reported_as_such() -> None:
    doc = scan(generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(doc, web_hits=[web_hit(page_id="bbbbbbbbbbbb2222", lots=[], domain="fda.gov")])

    finding = next(
        f for f in deterministic_report(doc, evidence, index_date=INDEX_DATE).findings
        if f.evidence_type == "web_page"
    )

    assert "regulator page mentioning falsified" in finding.statement
    assert finding.severity == "info"


def test_a_page_with_no_publication_date_says_so() -> None:
    doc = scan(generic_name="levothyroxine", drug_names=["levothyroxine"])
    hit = web_hit(page_id="bbbbbbbbbbbb2222", lots=[], tier="other", domain="blog.example")
    hit.source[Web.DATE_PRECISION] = "fetched"
    evidence = pack(doc, web_hits=[hit])

    finding = next(
        f for f in deterministic_report(doc, evidence, index_date=INDEX_DATE).findings
        if f.evidence_type == "web_page"
    )

    assert "no publication date" in finding.statement


def test_a_simulated_hardware_reading_is_never_stated_as_a_measurement() -> None:
    doc = with_hardware(scan(generic_name="levothyroxine", drug_names=["levothyroxine"]))
    evidence = pack(doc)

    assert evidence["hardware"]["simulated"] is True
    finding = next(
        f for f in deterministic_report(doc, evidence, index_date=INDEX_DATE).findings
        if f.evidence_type == "hardware_result"
    )

    assert 'status "substandard"' in finding.statement
    assert "Simulated result" in finding.statement
    assert "no potency figure" in finding.statement


def test_real_hardware_carries_no_simulation_caveat() -> None:
    doc = with_hardware(scan(generic_name="levothyroxine"), model="peel-nir-v1", status="real")
    evidence = pack(doc)

    assert evidence["hardware"]["simulated"] is False
    finding = next(
        f for f in deterministic_report(doc, evidence, index_date=INDEX_DATE).findings
        if f.evidence_type == "hardware_result"
    )

    assert "Simulated result" not in finding.statement
    assert finding.severity == "info"


def test_agreeing_hardware_and_recall_signals_are_noted_without_calling_it_proof() -> None:
    doc = with_hardware(scan(lot="D2402430", generic_name="levothyroxine"))
    evidence = pack(doc, exact_lot_hits=[reg_hit(lots=["D2402430"])])

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)
    note = next(f for f in report.findings if "two separate signals" in f.statement)

    assert note.severity == "serious"
    assert "not proof" in note.statement
    assert note.source_ids == ["fda-D-0785-2026"]


def test_no_corroboration_note_without_a_recall() -> None:
    doc = with_hardware(scan(generic_name="levothyroxine", drug_names=["levothyroxine"]))

    report = deterministic_report(doc, pack(doc), index_date=INDEX_DATE)

    assert not any("two separate signals" in f.statement for f in report.findings)


def test_a_rich_scan_produces_several_findings() -> None:
    doc = with_hardware(
        scan(
            lot="D2402430",
            ndc9="167290457",
            imprint_norm="ML8",
            generic_name="levothyroxine",
            drug_names=["levothyroxine"],
        )
    )
    evidence = pack(
        doc,
        exact_lot_hits=[reg_hit(lots=["D2402430"])],
        ndc_hits=[reg_hit("fda-2", lots=["X1"], match_kind="product_line_match")],
        ndc_directory=[ndc_hit()],
        pill=pill_match(),
        web_hits=[web_hit(page_id="aaaaaaaaaaaa1111", lots=["D2402430"])],
    )

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)

    assert 4 <= len(report.findings) <= 10
    kinds = {f.evidence_type for f in report.findings}
    assert {"exact_lot_match", "exact_ndc_match", "ndc_directory", "imprint_reference",
            "web_page", "hardware_result"} <= kinds


# --------------------------------------------------------------------------- ndc source


def test_ndc_directory_sources_are_citable() -> None:
    doc = scan(ndc9="167290457", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(doc, ndc_directory=[ndc_hit()])

    report = deterministic_report(doc, evidence, index_date=INDEX_DATE)
    source = next(s for s in report.sources if s.id.startswith("ndc-"))

    assert source.id == "ndc-16729-457"
    assert source.url == (
        "https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query=16729-457"
    )
    assert "ndc-16729-457" in allowed_source_ids(evidence)


def test_guardrails_accept_web_and_ndc_ids_and_indexed_page_ids() -> None:
    doc = scan(ndc9="167290457", generic_name="levothyroxine", drug_names=["levothyroxine"])
    evidence = pack(doc, ndc_directory=[ndc_hit()], web_hits=[web_hit(page_id="aaaaaaaaaaaa1111")])
    report = llm_report(
        findings=[
            Finding(
                statement="A regulator page discusses this product.",
                evidence_type="web_page",
                source_ids=["web-aaaaaaaaaaaa"],
                severity="info",
                country_scope=None,
            ),
            Finding(
                statement="The NDC directory row agrees with the label.",
                evidence_type="ndc_directory",
                source_ids=["ndc-16729-457"],
                severity="info",
                country_scope=None,
            ),
            Finding(
                statement="A page this scan fetched mentions the drug.",
                evidence_type="web_page",
                source_ids=["web-ffffffffffff"],
                severity="info",
                country_scope=None,
            ),
        ]
    )

    guarded = enforce_guardrails(report, evidence, page_ids=["ffffffffffff9999"])

    assert len(guarded.findings) == 4  # three kept plus the required disclaimer
    assert guarded.findings[2].source_ids == ["web-ffffffffffff"]
