from __future__ import annotations

from datetime import UTC, datetime

from backend.seed.sources.mhra import to_doc

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
