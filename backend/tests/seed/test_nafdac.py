from __future__ import annotations

from datetime import UTC, datetime

from backend.seed.sources.nafdac import to_doc

_NOW = datetime(2026, 9, 19, tzinfo=UTC)

# Trimmed but structurally real content.rendered: elementor wrapper divs, a
# "Product Details" table whose cells are wrapped in <p> (as NAFDAC's CMS
# actually emits them), the fixed sign-off, and the feedback-widget tail that
# must be stripped.
_FALSIFIED_HTML = """
<div data-elementor-type="wp-post" class="elementor">
<div class="e-con-inner">
<div class="elementor-widget-text-editor"><div class="elementor-widget-container">
<p>The National Agency for Food and Drug Administration and Control (NAFDAC) is notifying
the public of the seizure of a suspected Substandard and Falsified (SF) antimalarial medicine,
<strong>Artemether/Lumefantrine 80mg/480mg</strong>, purportedly manufactured by
<strong>Bandaram Pharma Packleh Ltd (BPPL), India</strong>.</p>
<p><strong>Product Details</strong></p>
<table><tbody>
<tr><td><p><strong>Product Name</strong></p></td><td><p>Artemether/Lumefantrine 80mg/480mg</p></td></tr>
<tr><td><p>Batch Number</p></td><td><p>BP5203</p></td></tr>
<tr><td><p>Expiry Date</p></td><td><p>09/2027</p></td></tr>
</tbody></table>
<p><strong>Reporting of Adverse Events</strong></p>
<p>Healthcare professionals and consumers are advised to report any suspicion of the sale of
substandard and falsified medicines to the nearest NAFDAC office.</p>
<p><strong>NAFDAC</strong>………. Customer-focused, Agency-minded!!!</p>
</div></div>
</div></div>
<div id="daexthefu-container" class="daexthefu-container">
<h3 class="daexthefu-title">Was this helpful?</h3>
<style>.thumb-up-cls-1{fill:#c9c9c9;}</style>
<div class="daexthefu-button-text">Yes</div>
<div class="daexthefu-button-text">No</div>
</div>
"""

_FALSIFIED_POST = {
    "id": 22021,
    "date": "2026-08-19T08:17:03",
    "date_gmt": "2026-08-19T08:17:03",
    "modified": "2026-08-20T08:39:42",
    "modified_gmt": "2026-08-20T08:39:42",
    "link": "https://nafdac.gov.ng/public-alert-no-042-2026-alert-on-the-seizure-of-suspected-substandard-and-falsified-bppl-artemether-lumefantrine-80mg-480mg/",
    "title": {"rendered": "Public Alert No. 042/2026-Alert on the Seizure of Suspected Substandard and Falsified BPPL Artemether/Lumefantrine 80mg/480mg"},
    "content": {"rendered": _FALSIFIED_HTML},
    "excerpt": {"rendered": "<p>Seizure alert&#8230;</p>"},
}

_WATCHLIST_POST = {
    "id": 22027,
    "date": "2026-08-19T08:42:18",
    "date_gmt": "2026-08-19T08:42:18",
    "modified": "2026-08-20T08:55:45",
    "modified_gmt": "2026-08-20T08:55:45",
    "link": "https://nafdac.gov.ng/public-alert-no-043-2026-nafdac-places-products-marketed-by-mofus-nigeria-ltd-on-watchlist-pending-regulatory-investigation/",
    "title": {"rendered": "Public Alert No. 043/2026-NAFDAC Places Products Marketed by Mofus Nigeria Ltd on Watchlist Pending Regulatory Investigation"},
    "content": {
        "rendered": (
            "<p>NAFDAC wishes to inform the public that products marketed by Mofus Nigeria Ltd "
            "have been placed on the NAFDAC Watchlist pending investigation.</p>"
            "<p><strong>Reporting of Adverse Events</strong></p>"
            "<p>Healthcare professionals and patients are encouraged to report the sale of "
            "substandard and falsified medicines to the nearest NAFDAC office.</p>"
            "<p><strong>NAFDAC</strong>………. Customer-focused, Agency-minded!!!</p>"
        )
    },
    "excerpt": {"rendered": "<p>Watchlist&#8230;</p>"},
}


def test_falsified_alert_extracts_lot_and_manufacturer() -> None:
    doc = to_doc(_FALSIFIED_POST, now=_NOW)
    assert doc is not None
    assert doc["_id"] == "nafdac-22021"
    assert doc["record_id"] == "nafdac-22021"
    assert doc["source"] == "nafdac_alerts"
    assert doc["source_org"] == "NAFDAC"
    assert doc["country_of_authority"] == "Nigeria"
    assert doc["doc_type"] == "falsified_alert"
    assert doc["severity"] == "critical"
    assert doc["severity_rank"] == 4
    assert doc["alert_number"] == "042/2026"
    assert doc["lot_numbers"] == ["BP5203"]
    assert "BP5203" in doc["lot_text"]
    assert doc["manufacturer"] == "Bandaram Pharma Packleh Ltd (BPPL), India"
    assert doc["published_at"] == "2026-08-19T08:17:03Z"
    assert doc["recency_date"] == "2026-08-19T08:17:03Z"
    assert doc["date_precision"] == "published"
    assert doc["url"] == _FALSIFIED_POST["link"]
    assert doc["has_semantic"] is True
    assert len(doc["body_semantic"]) <= 2000
    # the fixed sign-off and feedback-widget junk must not leak into body
    assert "Customer-focused" not in doc["body"]
    assert "Was this helpful" not in doc["body"]
    assert "thumb-up-cls" not in doc["body"]
    # the boilerplate reporting paragraph must not poison classification
    assert "Nigeria" in doc["countries"]


def test_watchlist_title_does_not_misclassify_as_falsified() -> None:
    doc = to_doc(_WATCHLIST_POST, now=_NOW)
    assert doc is not None
    # The generic "report substandard and falsified medicines" footer appears
    # in this post too; only the *title* should drive doc_type.
    assert doc["doc_type"] == "safety_alert"
    assert doc["severity"] == "moderate"
    assert doc["alert_number"] == "043/2026"
    assert "drug_names_extracted" not in doc  # no trigger word in title -> dropped, not guessed


def test_missing_id_returns_none() -> None:
    post = dict(_FALSIFIED_POST)
    post.pop("id")
    assert to_doc(post, now=_NOW) is None


def test_missing_date_returns_none() -> None:
    post = {**_FALSIFIED_POST, "date": None, "date_gmt": None, "modified": None, "modified_gmt": None}
    assert to_doc(post, now=_NOW) is None


def test_empty_fields_are_dropped_not_null() -> None:
    post = {
        **_WATCHLIST_POST,
        "content": {"rendered": "<p>Nothing specific is named in this notice at all.</p>"},
    }
    doc = to_doc(post, now=_NOW)
    assert doc is not None
    assert "manufacturer" not in doc
    assert "lot_numbers" not in doc
    assert "lot_text" not in doc


def test_unmapped_fields_are_a_subset_of_the_strict_mapping() -> None:
    from backend.knowledge.indices import mapped_fields
    from backend.knowledge.fields import REGULATORY_INDEX

    allowed = mapped_fields(REGULATORY_INDEX) | {"_id"}
    for post in (_FALSIFIED_POST, _WATCHLIST_POST):
        doc = to_doc(post, now=_NOW)
        assert doc is not None
        assert set(doc) <= allowed
