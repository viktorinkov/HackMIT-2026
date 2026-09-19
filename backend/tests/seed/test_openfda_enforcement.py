from __future__ import annotations

from typing import Any

from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.knowledge.indices import mapped_fields
from backend.seed.sources.openfda_enforcement import OpenFdaEnforcementSource, to_doc

# The demo anchor, verbatim from openFDA (recall_number D-0785-2026). openfda.*
# lists every sibling strength of the Accord levothyroxine line, which is exactly
# the over-matching the ndc_from_description split has to survive.
ANCHOR: dict[str, Any] = {
    "status": "Ongoing",
    "city": "Raleigh",
    "state": "NC",
    "country": "United States",
    "classification": "Class II",
    "openfda": {
        "brand_name": ["LEVOTHYROXINE SODIUM"],
        "generic_name": ["LEVOTHYROXINE SODIUM"],
        "manufacturer_name": ["Accord Healthcare Inc."],
        "product_ndc": [
            "16729-447", "16729-458", "16729-448", "16729-449", "16729-451", "16729-450",
            "16729-452", "16729-453", "16729-454", "16729-455", "16729-456", "16729-457",
        ],
        "substance_name": ["LEVOTHYROXINE SODIUM"],
        "rxcui": ["892246", "892251"],
        "package_ndc": ["16729-447-15", "16729-447-17", "16729-457-15", "16729-457-17"],
    },
    "product_type": "Drugs",
    "event_id": "99584",
    "recalling_firm": "ACCORD HEALTHCARE, INC.",
    "distribution_pattern": "Nationwide within the United States",
    "recall_number": "D-0785-2026",
    "product_description": (
        "Levothyroxine Sodium Tablets, USP, 200 mcg (0.2 mg), packaged in a) 90-count bottles "
        "(NDC  16729-457-15) and b) 1000-count bottles (NDC 16729-457-17), Rx Only, "
        "Manufactured for: Accord Healthcare, Inc., Raleigh, NC 27617, Manufactured by: "
        "Intas Pharmaceuticals Limited, Camp Road, Selaqui, Dehradun-248 197, India."
    ),
    "reason_for_recall": "Subpotent Drug",
    "recall_initiation_date": "20260806",
    "center_classification_date": "20260821",
    "report_date": "20260902",
    "code_info": (
        "a) Lot # D2402430, D2402431, Exp Date: 10/31/2026. b) Lot #: D2402432, "
        "Exp. Date 10/31/2026; D2500180, Exp. Date 12/31/2026."
    ),
}

ALL_LOTS: dict[str, Any] = {
    "status": "Terminated",
    "country": "United States",
    "classification": "Class I",
    "openfda": {"generic_name": ["VALSARTAN"], "manufacturer_name": ["Torrent Pharmaceuticals"]},
    "event_id": "81234",
    "recalling_firm": "Torrent Pharmaceuticals Limited",
    "distribution_pattern": "Nationwide and Puerto Rico; also distributed to Canada and India.",
    "recall_number": "D-1300-2019",
    "product_description": "Valsartan Tablets USP, 320 mg, 90-count bottle, NDC 13668-116-90",
    "reason_for_recall": "Presence of an impurity, N-nitrosodiethylamine (NDEA).",
    "recall_initiation_date": "20190102",
    "report_date": "20190116",
    "code_info": "All lots within expiry.",
}

NO_OPENFDA: dict[str, Any] = {
    "status": "Completed",
    "classification": "Class III",
    "openfda": {},
    "recalling_firm": "Sample Compounding Pharmacy",
    "recall_number": "D-0042-2024",
    "product_description": "Nystatin Oral Suspension, USP 500,000 units/5mL Cup, 5 mL unit dose",
    "reason_for_recall": "Lack of Assurance of Sterility",
    "recall_initiation_date": "20231201",
    "report_date": "20240110",
    "code_info": "Lot #: 072915, Exp 10/29/2015",
}


def test_anchor_resolves_the_demo_lot() -> None:
    doc = to_doc(ANCHOR, indexed_at="2026-09-19T00:00:00Z")
    assert doc is not None
    assert doc["_id"] == "fda-enf-D-0785-2026"
    assert doc[Reg.RECORD_ID] == "fda-enf-D-0785-2026"
    assert doc[Reg.LOT_NUMBERS] == ["D2402430", "D2402431", "D2402432", "D2500180"]
    assert doc[Reg.COVERS_ALL_LOTS] is False
    assert doc[Reg.LOT_TEXT].startswith("a) Lot # D2402430")


def test_anchor_keeps_sibling_ndcs_out_of_ndc_from_description() -> None:
    doc = to_doc(ANCHOR)
    assert doc is not None
    assert doc[Reg.NDC_FROM_DESCRIPTION] == ["167290457"]
    # Sibling strengths are searchable but must never be mistaken for this lot's NDC.
    assert "167290447" in doc[Reg.NDC9]
    assert "167290447" not in doc[Reg.NDC_FROM_DESCRIPTION]
    assert "16729045715" in doc[Reg.NDC11]
    assert "16729-457-15" in doc[Reg.NDC_RAW]


def test_anchor_severity_dates_and_metadata() -> None:
    doc = to_doc(ANCHOR, indexed_at="2026-09-19T00:00:00Z", export_date="2026-09-16T00:00:00Z")
    assert doc is not None
    assert (doc[Reg.SEVERITY], doc[Reg.SEVERITY_RANK]) == ("high", 3)
    assert doc[Reg.CLASSIFICATION_RAW] == "Class II"
    assert doc[Reg.STATUS] == "ongoing"
    assert doc[Reg.PUBLISHED_AT] == "2026-09-02T00:00:00Z"
    assert doc[Reg.EVENT_DATE] == "2026-08-06T00:00:00Z"
    assert doc[Reg.RECENCY_DATE] == doc[Reg.PUBLISHED_AT]
    assert doc[Reg.DATE_PRECISION] == "published"
    assert doc[Reg.SOURCE_EXPORT_DATE] == "2026-09-16T00:00:00Z"
    assert doc[Reg.DOC_TYPE] == "recall"
    assert doc[Reg.COUNTRY_OF_AUTHORITY] == "United States"
    assert doc[Reg.COUNTRIES] == ["United States"]
    assert doc[Reg.DOSAGE_FORM] == "tablet"
    assert doc[Reg.MANUFACTURER] == "Accord Healthcare Inc."
    assert doc[Reg.EVENT_ID] == "99584"
    assert doc[Reg.RXCUI] == ["892246", "892251"]
    assert doc[Reg.URL].endswith("recall_number:%22D-0785-2026%22")


def test_anchor_text_fields_keep_lots_out_of_the_vector_space() -> None:
    doc = to_doc(ANCHOR)
    assert doc is not None
    assert doc[Reg.TITLE].startswith("Class II recall: Levothyroxine Sodium Tablets")
    assert len(doc[Reg.SUMMARY]) <= 400
    assert doc[Reg.HAS_SEMANTIC] is True
    semantic = doc[Reg.BODY_SEMANTIC]
    assert len(semantic) <= 900
    assert not any(lot in semantic for lot in doc[Reg.LOT_NUMBERS])
    assert "Exp Date" not in semantic
    # body is the BM25 + display field, so it must carry the code table.
    assert "D2402430" in doc[Reg.BODY]
    assert "Subpotent Drug" in doc[Reg.BODY]
    assert doc[Reg.DRUG_NAMES] == ["levothyroxine sodium"]
    assert doc[Reg.DRUG_NAMES_EXTRACTED] == ["levothyroxine sodium"]


def test_all_lots_record() -> None:
    doc = to_doc(ALL_LOTS)
    assert doc is not None
    assert doc[Reg.COVERS_ALL_LOTS] is True
    assert Reg.LOT_NUMBERS not in doc  # empty lists are dropped, not indexed
    assert (doc[Reg.SEVERITY], doc[Reg.SEVERITY_RANK]) == ("critical", 4)
    assert doc[Reg.NDC_FROM_DESCRIPTION] == ["136680116"]
    assert sorted(doc[Reg.COUNTRIES]) == ["Canada", "India", "United States"]
    assert doc[Reg.STATUS] == "terminated"


def test_empty_openfda_falls_back_to_the_record_text() -> None:
    doc = to_doc(NO_OPENFDA)
    assert doc is not None
    assert Reg.DRUG_NAMES not in doc
    # "Oral" is a dosage-form word, so the head stops before it.
    assert doc[Reg.DRUG_NAMES_EXTRACTED] == ["nystatin"]
    assert doc[Reg.MANUFACTURER] == "Sample Compounding Pharmacy"
    assert doc[Reg.LOT_NUMBERS] == ["072915"]
    assert (doc[Reg.SEVERITY], doc[Reg.SEVERITY_RANK]) == ("moderate", 2)
    assert Reg.NDC9 not in doc
    assert Reg.EVENT_ID not in doc


def test_records_without_a_recency_date_or_id_are_skipped() -> None:
    assert to_doc({**ANCHOR, "report_date": None, "recall_initiation_date": None}) is None
    assert to_doc({**ANCHOR, "recall_number": ""}) is None


def test_every_emitted_field_is_mapped() -> None:
    allowed = mapped_fields(REGULATORY_INDEX) | {"_id"}
    for record in (ANCHOR, ALL_LOTS, NO_OPENFDA):
        doc = to_doc(record, indexed_at="2026-09-19T00:00:00Z", disclaimer="Do not rely…")
        assert doc is not None
        assert set(doc) <= allowed
        assert not any(value in (None, "", [], {}) for value in doc.values())


def test_source_declares_the_regulatory_index_with_semantic_text() -> None:
    source = OpenFdaEnforcementSource()
    assert source.name == "openfda_enforcement"
    assert source.index == REGULATORY_INDEX
    assert source.semantic is True
