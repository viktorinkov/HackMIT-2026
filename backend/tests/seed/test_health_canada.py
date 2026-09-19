from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.knowledge.indices import mapped_fields
from backend.seed.sources.health_canada import (
    HealthCanadaSource,
    _extract_detail,
    _kept_newest_first,
    to_doc,
)

# Verbatim shape (field names, "&nbsp;" entities and all) from the live bulk
# JSON at recalls-rappels.canada.ca, NID 82628.
DRUG_RECORD: dict[str, Any] = {
    "NID": "82628",
    "Title": "Platinum Naturals Easymulti Stress (men): Affected lots incorrectly labelled for Vitamin B6 quantity",
    "URL": "https://recalls-rappels.canada.ca/en/alert-recall/platinum-naturals-easymulti-stress-men-affected-lots-incorrectly-labelled-vitamin-b6",
    "Organization": "Drugs and health products",
    "Product": "Easymulti Stress (Men) capsules",
    "Issue": "Labelling",
    "What you should do": "Report any health product&nbsp;related&nbsp;side effects&nbsp;to Health Canada.",
    "Category": "Natural health products",
    "Recall class": "Type III",
    "Last updated": "2026-09-16",
    "Archived": "0",
}

FOOD_RECORD: dict[str, Any] = {
    "NID": "78484",
    "Title": "Various brands of sandwiches recalled due to Listeria monocytogenes",
    "URL": "https://recalls-rappels.canada.ca/en/alert-recall/various-brands-sandwiches-recalled-due-listeria-monocytogenes",
    "Organization": "CFIA",
    "Product": "Sandwiches",
    "Issue": "Listeria",
    "What you should do": "Do not consume the recalled product.",
    "Category": "Multiple food items",
    "Recall class": "Class 1",
    "Last updated": "2026-09-17",
    "Archived": "0",
}

# The two real "Affected products" table vintages: DIN-style cells with no
# nested tags (pipe-joined by html_to_text) and NHP-style cells wrapping every
# value in a <p> (which collapses html_to_text's pipe joining entirely).
DIN_TABLE_HTML = """
<html><body><main>
<table class="table table-bordered gc-table provisional table">
<thead><tr class="bg-info"><th>Product</th><th>DIN</th><th>Lot</th><th>Expiry</th></tr></thead>
<tbody><tr>
<td data-label="Product">Novo-Gesic Forte 500 mg (acetaminophen)</td>
<td data-label="DIN">00482323</td>
<td data-label="Lot">100083040</td>
<td data-label="Expiry">January 31, 2029</td>
</tr></tbody>
</table>
</main></body></html>
"""

NHP_TABLE_HTML = """
<html><body><main>
<table id="tablefield-node-82628-field_affected_products-0" class="tablefield wb-tables">
<thead><tr>
<th class="row_0 col_0"><p>Brand</p></th>
<th class="row_0 col_1"><p>Product Name</p></th>
<th class="row_0 col_2"><p>Manufacturer</p></th>
<th class="row_0 col_3"><p>Lot Number</p></th>
</tr></thead>
<tbody><tr>
<td class="row_1 col_0"><p>Platinum Naturals Ltd.</p></td>
<td class="row_1 col_1"><p>Easymulti Stress (Men)</p></td>
<td class="row_1 col_2"><p>Platinum Naturals Inc.</p></td>
<td class="row_1 col_3"><p>737, 737A, 737B, 737C</p></td>
</tr></tbody>
</table>
</main></body></html>
"""

NO_TABLE_HTML = "<html><body><main><p>No affected products table on this vintage of page.</p></main></body></html>"


def test_kept_drug_record_is_recognised() -> None:
    now = datetime(2026, 9, 19, tzinfo=UTC)
    doc = to_doc(DRUG_RECORD, now=now)
    assert doc is not None
    assert doc["_id"] == "hc-82628"
    assert doc[Reg.RECORD_ID] == "hc-82628"
    assert doc[Reg.SOURCE] == "health_canada_recalls"
    assert doc[Reg.SOURCE_ORG] == "Health Canada"
    assert doc[Reg.COUNTRY_OF_AUTHORITY] == "Canada"
    assert doc[Reg.COUNTRIES] == ["Canada"]
    assert doc[Reg.TITLE].startswith("Platinum Naturals Easymulti Stress")
    assert doc[Reg.REASON] == "Labelling"
    assert doc[Reg.PRODUCT_DESCRIPTION] == "Easymulti Stress (Men) capsules"
    # "&nbsp;" must be unescaped to a plain space, never leak into the index.
    assert "&nbsp;" not in doc[Reg.BODY]
    assert (doc[Reg.SEVERITY], doc[Reg.SEVERITY_RANK]) == ("moderate", 2)
    assert doc[Reg.CLASSIFICATION_RAW] == "Type III"
    assert doc[Reg.PUBLISHED_AT] == "2026-09-16T00:00:00Z"
    assert doc[Reg.DATE_PRECISION] == "updated"
    assert doc[Reg.RECENCY_DATE] == doc[Reg.PUBLISHED_AT]
    assert doc[Reg.HAS_SEMANTIC] is True
    assert len(doc[Reg.BODY_SEMANTIC]) <= 900
    assert len(doc[Reg.SUMMARY]) <= 400
    assert doc[Reg.ATTRIBUTION] == "Health Canada — Recalls and Safety Alerts"
    assert doc[Reg.SOURCE_LICENSE] == "Open Government Licence – Canada"
    assert Reg.STATUS not in doc  # Archived == "0" -> not archived -> dropped, not False


def test_archived_flag_maps_to_status() -> None:
    doc = to_doc({**DRUG_RECORD, "Archived": "1"})
    assert doc is not None
    assert doc[Reg.STATUS] == "archived"


def test_record_without_nid_or_date_is_skipped() -> None:
    assert to_doc({**DRUG_RECORD, "NID": ""}) is None
    assert to_doc({**DRUG_RECORD, "Last updated": ""}) is None
    assert to_doc({**DRUG_RECORD, "Last updated": "not a date"}) is None


def test_food_record_is_filtered_out_by_category() -> None:
    kept = _kept_newest_first([DRUG_RECORD, FOOD_RECORD])
    assert [r["NID"] for r in kept] == ["82628"]


def test_kept_records_sort_newest_first() -> None:
    older = {**DRUG_RECORD, "NID": "1", "Last updated": "2020-01-01"}
    newer = {**DRUG_RECORD, "NID": "2", "Last updated": "2026-01-01"}
    kept = _kept_newest_first([older, newer])
    assert [r["NID"] for r in kept] == ["2", "1"]


def test_detail_table_din_style_no_nested_tags() -> None:
    detail = _extract_detail(DIN_TABLE_HTML)
    assert detail.lot_numbers == ["100083040"]
    assert "100083040" in detail.lot_text


def test_detail_table_nhp_style_p_wrapped_cells() -> None:
    detail = _extract_detail(NHP_TABLE_HTML)
    # A bare 3-digit run is rejected by the shared code test (the FDA path's
    # rule): it matches far too much in an exact-match keyword field.
    assert detail.lot_numbers == ["737A", "737B", "737C"]
    assert detail.manufacturers == ["Platinum Naturals Inc."]


def _lot_table(cell: str) -> str:
    return f"""
<html><body><main><table id="tablefield-affected_products">
<thead><tr><th><p>Product Name</p></th><th><p>Lot Number</p></th></tr></thead>
<tbody><tr><td><p>Ifosfamide for Injection</p></td><td><p>{cell}</p></td></tr></tbody>
</table></main></body></html>
"""


def test_detail_table_tokens_are_gated_through_the_shared_code_test() -> None:
    # hc-82226, verbatim: the whole cell used to be split and normalized, so
    # 'EXPIRY' and '2029' landed in the exact-match lot field.
    detail = _extract_detail(_lot_table("Lot #: FA2B6004A Expiry: 2029/04/19"))
    assert detail.lot_numbers == ["FA2B6004A"]

    # hc-82156: the label word must go, the real lots must stay.
    detail = _extract_detail(_lot_table("Canadian lots: 3213779, 3213780"))
    assert detail.lot_numbers == ["3213779", "3213780"]
    assert "CANADIAN" not in detail.lot_numbers


def test_an_all_lots_cell_sets_the_flag_instead_of_the_lot_ALL() -> None:
    # 54 cached records indexed the literal lot 'ALL' and never set the flag, so
    # recalls_covering_all_lots could not return a Health Canada all-lots recall.
    detail = _extract_detail(_lot_table("All lots (since July 2023)"))
    assert detail.covers_all_lots is True
    assert detail.lot_numbers == []

    doc = to_doc(DRUG_RECORD, detail_html=_lot_table("All lots"))
    assert doc is not None
    assert doc[Reg.COVERS_ALL_LOTS] is True
    assert Reg.LOT_NUMBERS not in doc

    # A record with real lots must not carry the flag at all.
    doc = to_doc(DRUG_RECORD, detail_html=NHP_TABLE_HTML)
    assert doc is not None
    assert Reg.COVERS_ALL_LOTS not in doc


def test_detail_table_missing_degrades_to_no_lots() -> None:
    detail = _extract_detail(NO_TABLE_HTML)
    assert detail.lot_numbers == []
    assert detail.lot_text == ""
    assert _extract_detail(None).lot_numbers == []
    assert _extract_detail("<not even html").lot_numbers == []


def test_to_doc_merges_detail_page_lots_into_the_record() -> None:
    doc = to_doc(DRUG_RECORD, detail_html=NHP_TABLE_HTML)
    assert doc is not None
    assert doc[Reg.LOT_NUMBERS] == ["737A", "737B", "737C"]
    assert doc[Reg.MANUFACTURER] == ["Platinum Naturals Inc."]
    assert "737" in doc[Reg.BODY]  # lot table text is in body (BM25 + display)…
    assert "737" not in doc[Reg.BODY_SEMANTIC]  # …never in the embedded excerpt


def test_every_emitted_field_is_mapped() -> None:
    allowed = mapped_fields(REGULATORY_INDEX) | {"_id"}
    for record, html in ((DRUG_RECORD, NHP_TABLE_HTML), (DRUG_RECORD, None), (FOOD_RECORD, DIN_TABLE_HTML)):
        doc = to_doc(record, detail_html=html)
        assert doc is not None
        assert set(doc) <= allowed
        assert not any(value in (None, "", [], {}) for value in doc.values())


def test_source_declares_the_regulatory_index_with_semantic_text() -> None:
    source = HealthCanadaSource()
    assert source.name == "health_canada"
    assert source.index == REGULATORY_INDEX
    assert source.semantic is True
