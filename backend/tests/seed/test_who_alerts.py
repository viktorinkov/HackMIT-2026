"""Offline tests for the WHO Medical Product Alerts adapter.

Fixtures reproduce the real text shapes observed while building the adapter: the
HEALMOXY annex table (the LMIC demo), the Ozempic prose sentence, and the
multi-column IBRANCE annex whose expiry column must not leak into lot_numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.seed.sources.who_alerts import (
    WhoAlertsSource,
    _annex_urls,
    _strip_boilerplate,
    extract_batches_from_tables,
    to_doc,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

HEALMOXY_ITEM = {
    "Id": "f2d738e5-8445-45ab-9dc4-10bcb4f0afcd",
    "Title": "Medical Product Alert N°2/2025: Falsified HEALMOXY (Amoxicillin) Capsules 500mg",
    "ItemDefaultUrl": "/23-04-2025-medical-product-alert-n-2-2025--falsified-healmoxy",
    "PublicationDateAndTime": "2025-04-23T08:46:11Z",
    "NewsType": "Medical product alert",
}

HEALMOXY_PAGE = """Alert Summary

This WHO Medical Product Alert refers to four batches of falsified HEALMOXY Capsules 500mg. \
The falsified products have been detected in Cameroon and the Central African Republic and \
were reported to the WHO in March 2025.

How to identify these falsified products

Analysis of samples of the falsified HEALMOXY found the capsules did not contain the stated \
active ingredient, specifically amoxicillin.

Please refer to the Annex of this alert for full details of the falsified products."""

# pypdf flattens each annex table row onto one line; the batch row carries every
# code for that country, and the expiry row sits directly beneath it.
HEALMOXY_ANNEX = """                                April 2025

WHO Global Surveillance and Monitoring System for Substandard and Falsified Medical Products
Please visit: https://www.who.int/health-topics/substandard-and-falsified-medical-products
 Ref. RPQ/REG/ISF/Alert N°2/2025 | |   2

Annex: Products subject of WHO Medical Product Alert No. 2/2025
Product Name HEALMOXY Capsules 500mg
Stated
manufacturer MAXHEAL PHARMACEUTICALS (India) Limited
Identified in Cameroon
Batch  023011 023011 H02605
Expiry date 18/07/2025 10/01/2027 02/27
Available
Photographs

 Ref. RPQ/REG/ISF/Alert N°2/2025 | |   3
Product Name HEALMOXY Capsules 500mg
Stated manufacturer MAXHEAL PHARMACEUTICALS (India) Limited
Identified in Central African Republic
Batch  H026051
Expiry date 01/26
Available Photographs"""


def _healmoxy() -> dict:
    doc = to_doc(
        HEALMOXY_ITEM,
        page_text=HEALMOXY_PAGE,
        annex_text=HEALMOXY_ANNEX,
        attachment_urls=["https://cdn.who.int/media/docs/n2_2025_healmoxy_en.pdf"],
        indexed_at=NOW,
    )
    assert doc is not None
    return doc


class TestHealmoxyDemo:
    def test_annex_batches_reach_lot_numbers(self) -> None:
        lots = _healmoxy()[Reg.LOT_NUMBERS]
        assert set(lots) >= {"023011", "H02605", "H026051"}

    def test_expiry_dates_are_not_lots(self) -> None:
        lots = _healmoxy()[Reg.LOT_NUMBERS]
        assert not {"18072025", "10012027", "0227", "0126"} & set(lots)

    def test_classification(self) -> None:
        doc = _healmoxy()
        assert doc[Reg.DOC_TYPE] == "falsified_alert"
        assert (doc[Reg.SEVERITY], doc[Reg.SEVERITY_RANK]) == ("critical", 4)

    def test_countries(self) -> None:
        assert {"Cameroon", "Central African Republic"} <= set(_healmoxy()[Reg.COUNTRIES])

    def test_identity_and_provenance(self) -> None:
        doc = _healmoxy()
        assert doc["_id"] == doc[Reg.RECORD_ID] == f"who-mpa-{HEALMOXY_ITEM['Id']}"
        assert doc[Reg.SOURCE_ORG] == "WHO"
        assert doc[Reg.SOURCE] == "who_medical_product_alert"
        assert doc[Reg.ALERT_NUMBER] == "2/2025"
        assert doc[Reg.URL].startswith("https://www.who.int/news/item/23-04-2025-")
        assert doc[Reg.PUBLISHED_AT] == doc[Reg.RECENCY_DATE] == "2025-04-23T08:46:11Z"
        assert doc[Reg.DATE_PRECISION] == "published"
        assert doc[Reg.INDEXED_AT] == "2026-09-19T12:00:00Z"
        assert doc[Reg.SOURCE_LICENSE] == "CC BY-NC-SA 3.0 IGO"
        assert doc[Reg.RAW] == HEALMOXY_ITEM

    def test_names_and_form(self) -> None:
        doc = _healmoxy()
        assert set(doc[Reg.DRUG_NAMES]) == {"healmoxy", "amoxicillin"}
        assert doc[Reg.MANUFACTURER] == "MAXHEAL PHARMACEUTICALS (India) Limited"
        assert doc[Reg.DOSAGE_FORM] == "capsule"

    def test_semantic_field_excludes_the_annex(self) -> None:
        doc = _healmoxy()
        assert doc[Reg.HAS_SEMANTIC] is True
        assert len(doc[Reg.BODY_SEMANTIC]) <= 1800
        assert "023011" not in doc[Reg.BODY_SEMANTIC]
        assert doc[Reg.BODY_SEMANTIC].startswith(HEALMOXY_ITEM["Title"])

    def test_body_keeps_the_annex_and_summary_drops_the_heading(self) -> None:
        doc = _healmoxy()
        assert "H026051" in doc[Reg.BODY] and "ANNEX" in doc[Reg.BODY]
        assert len(doc[Reg.SUMMARY]) <= 400
        assert doc[Reg.SUMMARY].startswith("This WHO Medical Product Alert refers to four")

    def test_letterhead_never_reaches_the_document(self) -> None:
        doc = _healmoxy()
        assert "Switzerland" not in doc[Reg.COUNTRIES]
        assert "WHO Global Surveillance" not in doc[Reg.BODY]

    def test_lot_text_carries_the_source_rows(self) -> None:
        lot_text = _healmoxy()[Reg.LOT_TEXT]
        assert "Batch  023011 023011 H02605" in lot_text
        assert len(lot_text) <= 4000


class TestProseAlerts:
    OZEMPIC_PAGE = (
        "Alert Summary\n\n"
        "This WHO Medical Product Alert refers to falsified OZEMPIC (semaglutide) identified in "
        "Brazil, the United Kingdom and the United States.\n\n"
        "The genuine manufacturer, NOVO NORDISK, has confirmed that batch number LP6F832 is not "
        "recognized. The combination of batch number NAR0074 with serial number 430834149057 is "
        "not valid. Batch number MP5E511 is genuine, but the product is falsified."
    )
    ITEM = {
        "Id": "ozempic-0001",
        "Title": "Medical Product Alert N°2/2024: Falsified OZEMPIC (semaglutide)",
        "ItemDefaultUrl": "/19-06-2024-medical-product-alert-n-2-2024--falsified-ozempic",
        "PublicationDateAndTime": "2024-06-19T10:00:00Z",
    }

    def _doc(self) -> dict:
        doc = to_doc(self.ITEM, page_text=self.OZEMPIC_PAGE, indexed_at=NOW)
        assert doc is not None
        return doc

    def test_inline_batches_are_extracted(self) -> None:
        assert {"LP6F832", "NAR0074", "MP5E511"} <= set(self._doc()[Reg.LOT_NUMBERS])

    def test_prose_alert_without_annex(self) -> None:
        doc = self._doc()
        assert Reg.ATTACHMENT_URLS not in doc
        assert doc[Reg.COUNTRIES] == ["Brazil", "United Kingdom", "United States"]
        assert doc[Reg.MANUFACTURER] == "NOVO NORDISK"
        assert set(doc[Reg.DRUG_NAMES]) == {"ozempic", "semaglutide"}

    def test_alert_with_no_lots_anywhere(self) -> None:
        doc = to_doc(
            {
                "Id": "no-lots-1",
                "Title": "Medical Product Alert N°1/2026: Substandard ACCUPAQUE (Iohexol)",
                "ItemDefaultUrl": "07-05-2026-medical-product-alert-n-1-2026",
                "PublicationDateAndTime": "2026-05-07T11:09:04Z",
            },
            page_text="This alert refers to multiple affected presentations. Refer to the Annex.",
            indexed_at=NOW,
        )
        assert doc is not None
        # Empty containers are dropped so the strict mapping never sees a null.
        assert Reg.LOT_NUMBERS not in doc and Reg.LOT_TEXT not in doc
        assert doc[Reg.DOC_TYPE] == "substandard_alert"
        assert (doc[Reg.SEVERITY], doc[Reg.SEVERITY_RANK]) == ("high", 3)
        # ItemDefaultUrl is not always absolute.
        assert doc[Reg.URL] == "https://www.who.int/news/item/07-05-2026-medical-product-alert-n-1-2026"

    def test_substandard_title_beats_the_letterhead(self) -> None:
        doc = to_doc(
            {
                "Id": "substandard-1",
                "Title": "Medical Product Alert N°4/2025: Substandard FENTANILO HLB",
                "ItemDefaultUrl": "/fentanilo",
                "PublicationDateAndTime": "2025-08-29T08:00:00Z",
            },
            page_text="A contaminated batch was found.",
            annex_text="WHO Global Surveillance and Monitoring System for substandard and "
            "falsified medical products\nLot 31200 31202",
            indexed_at=NOW,
        )
        assert doc is not None
        assert doc[Reg.DOC_TYPE] == "substandard_alert"
        assert set(doc[Reg.LOT_NUMBERS]) == {"31200", "31202"}

    def test_record_without_a_date_is_skipped(self) -> None:
        assert to_doc({"Id": "x", "Title": "t"}, page_text="body") is None
        assert to_doc({"Title": "t", "PublicationDateAndTime": "2025-01-01"}, page_text="b") is None


class TestAnnexTables:
    def test_multi_column_header_yields_only_the_batch_cell(self) -> None:
        # The IBRANCE annex: `Lot number | Expiry Date | Identified In`.
        codes = [
            code
            for code, _ in extract_batches_from_tables(
                "Lot number Expiry Date Identified In\n"
                "FS5173   271126 Cote d'Ivoire, Lebanon, Libya\n"
                "GK2981 250630 Lebanon\n"
            )
        ]
        assert codes == ["FS5173", "GK2981"]

    def test_expiry_on_the_batch_row_is_cut(self) -> None:
        codes = [
            code
            for code, _ in extract_batches_from_tables("Batch Number: UH301AA; Expiry Date: 28FEB16")
        ]
        assert codes == ["UH301AA"]

    def test_split_code_fragment_is_dropped(self) -> None:
        doc = to_doc(
            {
                "Id": "frag-1",
                "Title": "Medical Product Alert N°3/2015: Falsified Meningitis Vaccines",
                "ItemDefaultUrl": "/men",
                "PublicationDateAndTime": "2015-05-27T00:00:00Z",
            },
            page_text="Falsified vaccines.",
            annex_text="Batch Number: UH 301AA\nBatch Number: UH301AA",
            indexed_at=NOW,
        )
        assert doc is not None
        assert doc[Reg.LOT_NUMBERS] == ["UH301AA"]

    def test_strengths_and_bullets_are_not_batches(self) -> None:
        codes = [
            code
            for code, _ in extract_batches_from_tables(
                "Batch number:\n Product name:   Quinine Sulphate 300mg USP\n"
            )
        ]
        assert codes == []

    def test_prose_is_not_mined_for_bare_numbers(self) -> None:
        text = "Some 40000 doses were distributed in 2021 across 12345 pharmacies."
        assert extract_batches_from_tables(text) == []

    def test_column_beneath_a_bare_header(self) -> None:
        codes = [code for code, _ in extract_batches_from_tables("Batch\nAB1234\nCD5678\n")]
        assert codes == ["AB1234", "CD5678"]

    def test_batch_column_before_a_trailing_expiry(self) -> None:
        # The N1/2026 contrast-media annex: `Product Batch Expiry`, where the
        # product column has a variable number of words and a leading SKU.
        codes = [
            code
            for code, _ in extract_batches_from_tables(
                "Product Batch Expiry\n"
                "26170256 OMNIPAQUE350 10x100PP 17253643 30-Jul-28\n"
                "ACCUPAQUE 300 mg USB 1x100 ml 17333581 07-Nov-28\n"
                "                                7 May 2026\n"
                "ACCUPAQUE 350 mg USB 10x100 ml 17089899 20-Jan-28\n"
            )
        ]
        assert codes == ["17253643", "17333581"]

    def test_trailing_date_rows_need_a_header(self) -> None:
        assert extract_batches_from_tables("ACCUPAQUE 300 mg 17333581 07-Nov-28") == []

    def test_boilerplate_stripping(self) -> None:
        cleaned = _strip_boilerplate(
            "20, AVENUE APPIA - CH-1211 GENEVA 27 - SWITZERLAND - WWW.WHO.INT\n"
            "Page 2 of 3\n"
            "Batch  023011\n"
        )
        assert cleaned == "Batch  023011"


class TestAnnexLinks:
    ARTICLE = (
        "<article><p>Advice.</p>"
        '<p><a target="_blank" href="https://cdn.who.int/media/docs/n3_2026_darzalex_en.pdf?sfvrsn=e7">'
        "Annex<strong>: Products subject to Alert N3/2026</strong></a></p>"
        '<p><a target="_blank" href="https://cdn.who.int/media/docs/n2_2026_jakavi_en.pdf?sfvrsn=73">'
        "<strong></strong></a></p>"
        '<p><a href="https://www.who.int/publications/other.pdf">Other</a></p>'
        "</article>"
    )

    def test_empty_anchor_to_another_alert_is_ignored(self) -> None:
        # WHO left a text-less link to the *previous* alert's annex on N3/2026;
        # following it would import another drug's batch numbers.
        assert _annex_urls(self.ARTICLE) == ["https://cdn.who.int/media/docs/n3_2026_darzalex_en.pdf"]

    def test_links_outside_an_article_are_ignored(self) -> None:
        assert _annex_urls('<div><a href="https://cdn.who.int/a.pdf">Annex</a></div>') == []


class TestSourceContract:
    def test_registration(self) -> None:
        source = WhoAlertsSource()
        assert source.name == "who_alerts"
        assert source.index == REGULATORY_INDEX
        assert source.semantic is True

    def test_documents_only_use_mapped_fields(self) -> None:
        from backend.knowledge.indices import mapped_fields

        assert set(_healmoxy()) - {"_id"} <= mapped_fields(REGULATORY_INDEX)

    def test_no_empty_values_survive(self) -> None:
        assert all(value not in (None, "", [], {}) for value in _healmoxy().values())

    def test_discovered_by_the_cli(self) -> None:
        from backend.seed.sources import discover

        assert discover()["who_alerts"] is WhoAlertsSource
