from __future__ import annotations

from datetime import date

from backend.reports.models import PurchaseLocation, ReportCreate


def test_empty_body_leaves_provenance_blank() -> None:
    body = ReportCreate.model_validate({})
    assert body.purchased_on is None
    assert body.purchase_location is None
    assert body.seller is None


def test_full_body_round_trips() -> None:
    body = ReportCreate.model_validate(
        {
            "purchased_on": "2026-03-12",
            "purchase_location": {
                "label": "CVS on Mass Ave",
                "city": "Cambridge",
                "region": "MA",
                "country": "US",
            },
            "seller": "CVS Pharmacy",
        }
    )
    assert body.purchased_on == date(2026, 3, 12)
    assert body.purchase_location is not None
    assert body.purchase_location.label == "CVS on Mass Ave"
    assert body.purchase_location.city == "Cambridge"
    assert body.seller == "CVS Pharmacy"


def test_location_string_becomes_a_label() -> None:
    # The app may pass Peel's raw arguments straight through.
    body = ReportCreate.model_validate({"purchase_location": "the CVS in Cambridge"})
    assert body.purchase_location is not None
    assert body.purchase_location.label == "the CVS in Cambridge"
    assert body.purchase_location.city is None


def test_month_only_date_becomes_the_first() -> None:
    body = ReportCreate.model_validate({"purchased_on": "2026-03"})
    assert body.purchased_on == date(2026, 3, 1)


def test_unknown_date_is_omitted() -> None:
    body = ReportCreate.model_validate({"purchased_on": "not sure"})
    assert body.purchased_on is None


def test_blank_fields_are_omitted() -> None:
    body = ReportCreate.model_validate(
        {"seller": "  ", "purchase_location": {}, "purchased_on": ""}
    )
    assert body.seller is None
    assert body.purchase_location is None
    assert body.purchased_on is None


def test_body_ignores_scan_fields() -> None:
    body = ReportCreate.model_validate({"scan_id": "scan-other", "summary": "x", "seller": "a friend"})
    assert body.seller == "a friend"
    assert not hasattr(body, "summary")


def test_purchase_location_empty_helper() -> None:
    assert PurchaseLocation().is_empty()
    assert not PurchaseLocation(city="Boston").is_empty()
