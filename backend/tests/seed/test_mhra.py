from __future__ import annotations

from datetime import UTC, datetime

from backend.seed.sources.mhra import _table_lots, to_doc

_NOW = datetime(2026, 9, 19, tzinfo=UTC)

# A real MHRA body shape: headed sections + a column-only batch table (no
# "batch" keyword anywhere near the code itself -> extract_batches_from_prose
# alone cannot find it; this is exactly what the table-aware pass is for).
_TABLE_BODY = """
<h2 id="marketing-authorisation-holder">Marketing Authorisation Holder</h2>
<p>Zentiva Pharma UK Limited</p>
<h2 id="medicine-details">Medicine Details</h2>
<h3>Fingolimod Zentiva 0.5 mg Capsules</h3>
<p>PL: 17780/0858</p>
<p>Active Ingredient: Fingolimod</p>
<h2 id="affected-lot-batch-numbers">Affected Lot Batch Numbers</h2>
<table>
  <thead><tr><th>Batch No.</th><th>Expiry Date</th><th>Pack Size</th></tr></thead>
  <tbody>
    <tr><td>4L01372H</td><td>11/2027</td><td>28</td></tr>
    <tr><td>4L01373H</td><td>12/2027</td><td>28</td></tr>
  </tbody>
</table>
<h2 id="background">Background</h2>
<p>Zentiva UK Pharma Limited are recalling two batches of Fingolimod Zentiva 0.5 mg Capsules
as a precautionary measure due to a potential risk of contamination with metal particles.</p>
"""

_TABLE_ITEM = {
    "content_id": "47011eac-842f-4f80-a083-58f5bcb0808f",
    "title": "Class 2 Medicines Recall: Zentiva Pharma UK Limited, Fingolimod Zentiva 0.5 mg Capsules, EL(26)A/37",
    "link": "/drug-device-alerts/class-2-medicines-recall-zentiva",
    "public_timestamp": "2026-08-20T13:21:27Z",
    "description": (
        "Zentiva UK Pharma Limited are recalling batches of Fingolimod Zentiva 0.5 mg Capsules "
        "due to a potential risk of contamination with metal particles."
    ),
    "alert_type": ["medicines-recall-notification"],
}

_TABLE_CONTENT = {
    "content_id": "47011eac-842f-4f80-a083-58f5bcb0808f",
    "title": _TABLE_ITEM["title"],
    "description": _TABLE_ITEM["description"],
    "first_published_at": "2026-08-20T14:21:27+01:00",
    "public_updated_at": "2026-08-20T14:21:27+01:00",
    "base_path": "/drug-device-alerts/class-2-medicines-recall-zentiva",
    "withdrawn_notice": {},
    "details": {
        "body": _TABLE_BODY,
        "metadata": {
            "alert_type": "medicines-recall-notification",
            "issued_date": "2026-08-20",
            "medical_specialism": ["pharmacy"],
        },
    },
}

# A prose-only mention ("BN 4L99999X") with no table at all, to exercise the
# extract_batches_from_prose fallback and the "Class 4 -> moderate" severity.
_PROSE_CONTENT = {
    "content_id": "aaaa1111-2222-3333-4444-555566667777",
    "title": "Class 4 Medicines Defect Notification: Example Pharma Ltd, Widgetol 10mg Tablets, EL(26)A/99",
    "description": "Example Pharma Ltd has informed the MHRA of a labelling defect.",
    "first_published_at": "2026-07-01T09:00:00+01:00",
    "details": {
        "body": (
            "<h2>Background</h2><p>Example Pharma Ltd is recalling batch 4L99999X of "
            "Widgetol 10mg Tablets as a precaution.</p>"
        ),
        "metadata": {"issued_date": "2026-07-01"},
    },
}
_PROSE_ITEM = {
    "content_id": _PROSE_CONTENT["content_id"],
    "title": _PROSE_CONTENT["title"],
    "link": "/drug-device-alerts/class-4-widgetol",
    "public_timestamp": "2026-07-01T09:00:00Z",
    "description": _PROSE_CONTENT["description"],
}

_COMPANY_LED_ITEM = {
    "content_id": "bbbb1111-2222-3333-4444-555566667777",
    "title": "Company led medicines recall: Some Firm Ltd, Painex 20mg Tablets",
    "link": "/drug-device-alerts/company-led-painex",
    "public_timestamp": "2025-01-01T00:00:00Z",
    "description": "Some Firm Ltd is voluntarily recalling Painex 20mg Tablets.",
}
_COMPANY_LED_CONTENT = {
    "content_id": _COMPANY_LED_ITEM["content_id"],
    "title": _COMPANY_LED_ITEM["title"],
    "description": _COMPANY_LED_ITEM["description"],
    "first_published_at": "2025-01-01T00:00:00Z",
    "details": {"body": "<p>Some Firm Ltd is voluntarily recalling Painex 20mg Tablets.</p>", "metadata": {}},
}


def test_table_only_batches_are_extracted() -> None:
    doc = to_doc(_TABLE_ITEM, _TABLE_CONTENT, now=_NOW)
    assert doc is not None
    assert doc["_id"] == "mhra-47011eac-842f-4f80-a083-58f5bcb0808f"
    assert doc["record_id"] == "mhra-47011eac-842f-4f80-a083-58f5bcb0808f"
    assert doc["source"] == "mhra_alerts"
    assert doc["source_org"] == "MHRA"
    assert doc["doc_type"] == "recall"
    assert doc["country_of_authority"] == "United Kingdom"
    assert sorted(doc["lot_numbers"]) == ["4L01372H", "4L01373H"]
    assert doc["classification_raw"] == "Class 2 Medicines Recall"
    assert doc["alert_number"] == "EL(26)A/37"
    assert doc["severity"] == "critical"  # Class 2 -> critical
    assert doc["severity_rank"] == 4
    assert doc["manufacturer"] == "Zentiva Pharma UK Limited"
    assert "fingolimod" in " ".join(doc["drug_names_extracted"]).lower()
    assert doc["dosage_form"] == "capsule"
    assert doc["published_at"] == "2026-08-20T00:00:00Z"  # issued_date wins over public_timestamp
    assert doc["date_precision"] == "published"
    assert doc["url"] == "https://www.gov.uk/drug-device-alerts/class-2-medicines-recall-zentiva"
    assert doc["has_semantic"] is True
    assert len(doc["body_semantic"]) <= 1500


def test_prose_batch_mention_is_still_caught() -> None:
    doc = to_doc(_PROSE_ITEM, _PROSE_CONTENT, now=_NOW)
    assert doc is not None
    assert "4L99999X" in doc["lot_numbers"]
    assert doc["classification_raw"] == "Class 4 Medicines Defect Notification"
    assert doc["severity"] == "moderate"  # Class 4 -> moderate
    assert doc["alert_number"] == "EL(26)A/99"


def test_company_led_recall_has_no_class_but_is_moderate() -> None:
    doc = to_doc(_COMPANY_LED_ITEM, _COMPANY_LED_CONTENT, now=_NOW)
    assert doc is not None
    assert doc["classification_raw"] == "Company led medicines recall"
    assert doc["severity"] == "moderate"
    assert doc["manufacturer"] == "Some Firm Ltd"


def test_missing_content_id_returns_none() -> None:
    item = {k: v for k, v in _TABLE_ITEM.items() if k != "content_id"}
    content = {k: v for k, v in _TABLE_CONTENT.items() if k != "content_id"}
    assert to_doc(item, content) is None


def test_missing_date_returns_none() -> None:
    content = {**_TABLE_CONTENT, "first_published_at": None, "public_updated_at": None}
    content["details"] = {**content["details"], "metadata": {}}
    item = {k: v for k, v in _TABLE_ITEM.items() if k != "public_timestamp"}
    assert to_doc(item, content) is None


# --------------------------------------------------------------- table parsing

# Verbatim from the cached gov.uk body of the Lipitor/Almus Class 2 recall: the
# batch cell carries the livery name alongside the code.
LIPITOR_TABLE = """
<table>
<thead><tr><th>Batch Number</th><th>Expiry Date</th><th>Pack Size</th></tr></thead>
<tbody>
<tr><td>T43157 (Almus)</td><td>31 Jan 2020</td><td>1 x 28</td></tr>
<tr><td>T43166 (Lipitor)</td><td>31 Jan 2020</td><td>1 x 28</td></tr>
<tr><td>T43170 (Lipitor)</td><td>31 Jan 2020</td><td>1 x 28</td></tr>
</tbody></table>
"""

# The Adrenaline/Amiodarone alert: one cell stands for a whole inclusive range.
RANGE_TABLE = """
<table>
<thead><tr><th>Product name</th><th>Batch number range from and to inclusive</th>
<th>Expiry date range From and to inclusive</th></tr></thead>
<tbody>
<tr><td>Adrenaline 1mg/10ml</td><td>From 5000879 to 5000964</td><td>From 05/2014 to 07/2014</td></tr>
<tr><td>Ephedrine Hydrochloride 3mg/ml</td><td>From 5000377 to 5000846</td>
<td>From 06/2013 to 10/2014</td></tr>
</tbody></table>
"""

# Kogenate Bayer, CLDA(16)A/05: gov.uk swapped its own first two columns, so the
# header says "Batch no" over a column of product names.
KOGENATE_TABLE = """
<table>
<thead><tr><th>Batch no</th><th>Product</th><th>Expiry date</th></tr></thead>
<tbody>
<tr><td>KOGENATE BAYER 500 IU</td><td>ITA2N65</td><td>12/06/2018</td></tr>
<tr><td>KOGENATE BAYER 500 IU</td><td>ITA2CNV</td><td>19/03/2017</td></tr>
<tr><td>KOGENATE BAYER 2000 IU</td><td>ITA2P68</td><td>12/06/2018</td></tr>
</tbody></table>
"""


def test_table_cell_yields_each_code_not_the_glued_cell() -> None:
    # Was ['T43157ALMUS', 'T43166LIPITOR', 'T43170LIPITOR'] — no exact lot hit
    # for a patient scanning T43157 on a Class 2 (patient-level) recall.
    assert _table_lots(LIPITOR_TABLE) == ["T43157", "T43166", "T43170"]


def test_table_range_cell_expands_only_when_it_is_small_and_numeric() -> None:
    lots = _table_lots(RANGE_TABLE)
    # 5000879..5000964 inclusive is 86 batches, all of them recalled.
    assert lots[:3] == ["5000879", "5000880", "5000881"]
    assert "5000964" in lots
    assert len([lot for lot in lots if lot.startswith("50008") or lot.startswith("50009")]) >= 86
    # 5000377..5000846 is 470 wide: endpoints only, never 470 index entries.
    assert "5000377" in lots and "5000846" in lots
    assert "5000378" not in lots
    assert "FROM5000879TO5000964" not in lots


def test_swapped_columns_are_validated_against_the_data_rows() -> None:
    lots = _table_lots(KOGENATE_TABLE)
    assert lots == ["ITA2N65", "ITA2CNV", "ITA2P68"]
    assert not any(lot.startswith("KOGENATE") for lot in lots)


def test_a_table_where_no_column_holds_a_code_yields_nothing() -> None:
    table = """
    <table><thead><tr><th>Batch no</th><th>Product</th></tr></thead>
    <tbody><tr><td>see annex</td><td>Widgetol tablets</td></tr>
    <tr><td>see annex</td><td>Widgetol capsules</td></tr></tbody></table>
    """
    assert _table_lots(table) == []


def test_a_batch_code_printed_with_a_space_survives() -> None:
    table = """
    <table><thead><tr><th>Batch no</th><th>Expiry date</th></tr></thead>
    <tbody><tr><td>ER 4824</td><td>May 2017</td></tr></tbody></table>
    """
    assert _table_lots(table) == ["ER4824"]


# ------------------------------------------------------------- title splitting


def _titled(title: str) -> dict:
    doc = to_doc(
        {"content_id": "t-1", "title": title, "link": "/x", "public_timestamp": "2020-01-01T00:00:00Z"},
        {
            "content_id": "t-1",
            "title": title,
            "description": "d",
            "first_published_at": "2020-01-01T00:00:00Z",
            "details": {"body": "<p>body</p>", "metadata": {}},
        },
        now=_NOW,
    )
    assert doc is not None
    return doc


def test_comma_separated_class_title_is_split_and_classified() -> None:
    doc = _titled(
        "Class 2 Medicines Recall, medac GmbH (T/A medac Pharma LLP) Sodiofolin 50mg/ml "
        "Solution for Injection 100mg/2ml, PL 11587/0005, EL (20) A/61"
    )
    assert doc["classification_raw"] == "Class 2 Medicines Recall"
    assert doc["severity"] == "critical"
    assert doc["severity_rank"] == 4
    assert not doc["manufacturer"].lower().startswith("class")


def test_qualifier_word_and_bare_notification_titles_still_split() -> None:
    fmd = _titled("Class 3 FMD Medicines Recall, Beconase Aqueous Nasal Spray, EL (20)A/07")
    assert fmd["classification_raw"] == "Class 3 FMD Medicines Recall"
    assert fmd["severity"] == "high"
    notif = _titled("Class 4 Medicines Notification: Zentiva Pharma UK Limited, Irbesartan 150mg")
    assert notif["classification_raw"] == "Class 4 Medicines Notification"
    assert notif["severity"] == "moderate"
    assert "irbesartan" in " ".join(notif["drug_names_extracted"])


def test_an_unsplittable_class_title_never_falls_to_unknown() -> None:
    # "FMD Alert: Class 2 (EL (19)A/19)" has no splittable prefix at all, but a
    # Class 2 recall must not rank below a correctly-parsed Class 4 notice.
    doc = _titled("FMD Alert: Class 2 (EL (19)A/19)")
    assert doc["severity"] == "critical"
    assert doc["severity_rank"] == 4
    # …and the fallback feeds severity only, so the honest fields stay honest.
    assert "classification_raw" not in doc


def test_unmapped_fields_are_a_subset_of_the_strict_mapping() -> None:
    from backend.knowledge.indices import mapped_fields
    from backend.knowledge.fields import REGULATORY_INDEX

    allowed = mapped_fields(REGULATORY_INDEX) | {"_id"}
    for item, content in (
        (_TABLE_ITEM, _TABLE_CONTENT),
        (_PROSE_ITEM, _PROSE_CONTENT),
        (_COMPANY_LED_ITEM, _COMPANY_LED_CONTENT),
    ):
        doc = to_doc(item, content, now=_NOW)
        assert doc is not None
        assert set(doc) <= allowed
