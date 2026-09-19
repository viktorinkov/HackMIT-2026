from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.knowledge.fields import NDC_INDEX, Ndc
from backend.knowledge.indices import mapped_fields
from backend.seed.sources.openfda_ndc import OpenFdaNdcSource, to_doc

NOW = datetime(2026, 9, 19, tzinfo=UTC)

# Verbatim shape from the live openFDA NDC directory export.
RECORD: dict[str, Any] = {
    "product_ndc": "70771-1050",
    "generic_name": "Ibuprofen",
    "labeler_name": "Example Pharma LLC",
    "brand_name": "Ibuprofen",
    "active_ingredients": [{"name": "IBUPROFEN", "strength": "200 mg/1"}],
    "finished": True,
    "packaging": [
        {
            "package_ndc": "70771-1050-1",
            "description": "100 TABLET, FILM COATED in 1 BOTTLE (70771-1050-1)",
            "marketing_start_date": "20181101",
            "sample": False,
        },
        {
            "package_ndc": "70771-1050-3",
            "description": "30 TABLET, FILM COATED in 1 BOTTLE (70771-1050-3)",
            "marketing_start_date": "20181101",
            "sample": False,
        },
    ],
    "listing_expiration_date": "20271231",
    "openfda": {
        "manufacturer_name": ["Example Pharma LLC"],
        "rxcui": ["123456"],
        "spl_set_id": ["b5f78b2a-56d1-4400-9d2f-b033cc13d26e"],
        "unii": ["ABC123XYZ"],
    },
    "marketing_category": "ANDA",
    "dosage_form": "TABLET, FILM COATED",
    "spl_id": "3d2f2743-d245-4a85-b6cb-e4e7cc417394",
    "product_type": "HUMAN OTC DRUG",
    "route": ["ORAL"],
    "marketing_start_date": "20181101",
    "pharm_class": ["Cyclooxygenase Inhibitors [MoA]"],
}

EXPIRED_RECORD: dict[str, Any] = {
    "product_ndc": "0009-0056",
    "generic_name": "Example Drug",
    "labeler_name": "Old Labeler Inc.",
    "brand_name": "OldBrand",
    "active_ingredients": [{"name": "EXAMPLE", "strength": "10 mg/1"}],
    "finished": True,
    "packaging": [{"package_ndc": "0009-0056-01", "description": "1 BOTTLE", "sample": False}],
    "listing_expiration_date": "20200101",
    "openfda": {},
    "marketing_category": "NDA",
    "dosage_form": "CAPSULE",
    "spl_id": "aaaa-bbbb",
    "product_type": "HUMAN PRESCRIPTION DRUG",
    "route": ["ORAL"],
    "marketing_start_date": "19990101",
}

NO_EXPIRATION_RECORD: dict[str, Any] = {
    "product_ndc": "12345-999",
    "generic_name": "Bulk Ingredient",
    "labeler_name": "Bulk Supplier",
    "active_ingredients": [],
    "finished": False,
    "packaging": [],
    "openfda": {},
    "marketing_category": "BULK INGREDIENT",
    "spl_id": "cccc-dddd",
    "product_type": "BULK INGREDIENT",
    "marketing_start_date": "20100101",
}


def test_packaging_resolves_to_ndc9_and_ndc11() -> None:
    doc = to_doc(RECORD, now=NOW)
    assert doc is not None
    assert doc["_id"] == "70771-1050"
    assert doc[Ndc.PRODUCT_NDC] == "70771-1050"
    assert doc[Ndc.NDC9] == "707711050"
    assert doc[Ndc.PACKAGE_NDCS] == ["70771-1050-1", "70771-1050-3"]
    assert doc[Ndc.NDC11] == ["70771105001", "70771105003"]
    assert doc[Ndc.ACTIVE_INGREDIENT_NAMES] == ["ibuprofen"]
    assert doc[Ndc.STRENGTHS] == ["200 mg/1"]
    assert doc[Ndc.DOSAGE_FORM] == "tablet, film coated"
    assert doc[Ndc.ROUTE] == ["oral"]
    assert doc[Ndc.RXCUI] == ["123456"]
    assert doc[Ndc.UNII] == ["ABC123XYZ"]
    assert doc[Ndc.SPL_SET_ID] == "b5f78b2a-56d1-4400-9d2f-b033cc13d26e"
    assert doc[Ndc.PHARM_CLASS] == ["Cyclooxygenase Inhibitors [MoA]"]
    assert doc[Ndc.MARKETING_START_DATE] == "2018-11-01T00:00:00Z"


def test_future_listing_is_not_expired() -> None:
    doc = to_doc(RECORD, now=NOW)
    assert doc is not None
    assert doc[Ndc.IS_LISTING_EXPIRED] is False


def test_past_listing_is_flagged_expired() -> None:
    doc = to_doc(EXPIRED_RECORD, now=NOW)
    assert doc is not None
    assert doc[Ndc.IS_LISTING_EXPIRED] is True


def test_missing_listing_expiration_omits_the_flag() -> None:
    doc = to_doc(NO_EXPIRATION_RECORD, now=NOW)
    assert doc is not None
    assert Ndc.IS_LISTING_EXPIRED not in doc
    assert Ndc.PACKAGE_NDCS not in doc  # empty list -> dropped, not indexed


def test_duplicate_product_ndc_gets_an_spl_id_suffix() -> None:
    dup = {"70771-1050"}
    doc = to_doc(RECORD, now=NOW, dup_product_ndcs=dup)
    assert doc is not None
    assert doc["_id"] == "70771-1050-3d2f2743-d245-4a85-b6cb-e4e7cc417394"
    # A record whose product_ndc is not in the duplicate set keeps the plain id.
    doc_unique = to_doc(RECORD, now=NOW, dup_product_ndcs=set())
    assert doc_unique is not None
    assert doc_unique["_id"] == "70771-1050"


def test_record_without_product_ndc_is_skipped() -> None:
    assert to_doc({**RECORD, "product_ndc": ""}, now=NOW) is None
    assert to_doc({}, now=NOW) is None


def test_every_emitted_field_is_mapped() -> None:
    allowed = mapped_fields(NDC_INDEX) | {"_id"}
    for record in (RECORD, EXPIRED_RECORD, NO_EXPIRATION_RECORD):
        doc = to_doc(record, now=NOW)
        assert doc is not None
        assert set(doc) <= allowed
        assert not any(value in (None, "", [], {}) for value in doc.values())
        assert "raw" not in doc  # kept out entirely to keep the index small


def test_source_declares_the_ndc_index_with_no_semantic_text() -> None:
    source = OpenFdaNdcSource()
    assert source.name == "openfda_ndc"
    assert source.index == NDC_INDEX
    assert source.semantic is False
