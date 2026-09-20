"""Offline tests for backend.knowledge.normalize. No network, no cluster."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.knowledge.fields import SEVERITY_RANKS
from backend.knowledge.normalize import (
    MAX_LOTS,
    age_days,
    canonical_url,
    classify_doc_type,
    clean_text,
    code_token,
    code_tokens,
    content_hash,
    domain_of,
    extract_batches_from_prose,
    extract_countries,
    extract_drug_names,
    extract_lots,
    extract_ndcs,
    freshness_label,
    html_to_text,
    lot_code,
    mentions_all_lots,
    normalize_dosage_form,
    normalize_drug_name,
    normalize_imprint,
    normalize_lot,
    normalize_ndc,
    parse_date,
    parse_expiration,
    query_key,
    severity_for,
    to_iso,
    truncate_on_sentence,
    url_hash,
)

# --------------------------------------------------------------------------- lots

# The 20 verbatim openFDA `code_info` strings from design B §1.1b plus the demo
# string. Expected values are the design's outputs after normalize_lot (which
# strips [^A-Z0-9]), so `t12-07-2016@97` is locked in as `T1207201697`.
CODE_INFO_CASES: list[tuple[str, list[str], bool]] = [
    ("Lot #: 072915, Exp 10/29/2015", ["072915"], False),
    ("1931102AL", ["1931102AL"], False),
    (
        "Lot #s: 7800929, 7800931, Exp 02/15; 7800962, Exp 03/15",
        ["7800929", "7800931", "7800962"],
        False,
    ),
    (
        "Lot #: a) 619800, Exp. 12/31/2020; 626200, Exp. 01/31/2021; "
        "b) 619800X, Exp. 12/31/2020; 626200X, Exp. 01/31/2021",
        ["619800", "626200", "619800X", "626200X"],
        False,
    ),
    (
        "Lot # t12-07-2016@97, Exp 5/22/2017; t12-12-2016@88, Exp 5/22/2017",
        ["T1207201697", "T1212201688"],
        False,
    ),
    ("Lot: 2005441, 01/2017, Code: 0378-3978-93", ["2005441"], False),
    (
        "Product Code: 1020; NDC: 63323-010-20; Lot Number: 6107992; Expiration Date: 09/2015",
        ["6107992"],
        False,
    ),
    (
        "Batch 81801504002 to 81801701003, exp 4/12/2017 through 1/19/2019",
        ["81801504002", "81801701003"],
        False,
    ),
    (
        "All unexpired lots, manufactured and distributed between 07/01/2013 and "
        "10/19/2013; including Lot #: 08292013@10",
        ["0829201310"],
        True,
    ),
    (
        "lot code No Expiration Date on product: a) 224010, b) 321260, 322260, 320280",
        ["224010", "321260", "322260", "320280"],
        False,
    ),
    ("Lot #: 23MAY016, Exp. Date 5/8/24; 23JUL016, Exp. Date 7/10/24", ["23MAY016", "23JUL016"], False),
    (
        "Lot number CABCAIBA:36, Exp date: 4/6/2013; Lot number CABDDAAB:10, Exp date: 4/6/2013",
        ["CABCAIBA36", "CABDDAAB10"],
        False,
    ),
    (
        "Lot: 04262018:09 Discard by: 10/22/2018; 07022018:48 Discard by: 12/29/2018",
        ["0426201809", "0702201848"],
        False,
    ),
    (
        "bulk lot N0019, Expiration Date: 11 2014 Warennummer: 10131968 "
        "Chargennummer:NXXXX 2000609D Lot N0019B01-N0019B12",
        ["N0019", "2000609D", "N0019B01N0019B12"],
        False,
    ),
    ("Lots: ALL", [], True),
    ("All lots within expiry.", [], True),
    ("UPC 859613252258", [], False),
    ("Rx #: 0403172", [], False),
    (
        "Lot # NC185424, Exp Date: 2/12/2027; Lot # NC185479, Exp Date: 2/13/2027",
        ["NC185424", "NC185479"],
        False,
    ),
]


@pytest.mark.parametrize(("code_info", "lots", "covers_all"), CODE_INFO_CASES)
def test_extract_lots_table(code_info: str, lots: list[str], covers_all: bool) -> None:
    codes = extract_lots(code_info)
    assert codes.lot_numbers == lots
    assert codes.covers_all_lots is covers_all


def test_extract_lots_demo_case() -> None:
    codes = extract_lots("Lot # NC185424, Exp Date: 2/12/2027; Lot # NC185479, Exp Date: 2/13/2027")
    assert codes.lot_numbers == ["NC185424", "NC185479"]


def test_extract_lots_captures_ndcs_but_never_returns_them() -> None:
    codes = extract_lots("Lot: 2005441, 01/2017, Code: 0378-3978-93")
    assert codes.ndc_raw == ["0378-3978-93"]
    assert "03783978" not in "".join(codes.lot_numbers)

    codes = extract_lots(
        "Product Code: 1020; NDC: 63323-010-20; Lot Number: 6107992; Expiration Date: 09/2015"
    )
    assert codes.ndc_raw == ["63323-010-20"]
    assert codes.lot_numbers == ["6107992"]


@pytest.mark.parametrize(
    "text",
    [
        "Lot #: 072915, Exp 10/29/2015",
        "Lot #s: 7800929, Exp 02/15; 7800962, Exp 03/15",
        "Lot: 123456, Expiration Date: 20190731",
        "Lot: 123456, Exp July 31, 2025",
        "Lot: 123456, Exp November 2014",
        "Lot: 123456, Exp 28-Sep-15",
    ],
)
def test_extract_lots_never_returns_dates(text: str) -> None:
    for lot in extract_lots(text).lot_numbers:
        assert not any(token in lot for token in ("2015", "2017", "2019", "2025", "2014"))


def test_extract_lots_no_expiration_guard() -> None:
    # The (?<!no ) guard: "No Expiration Date" must not swallow the lot list.
    codes = extract_lots("lot code No Expiration Date on product: a) 224010, b) 321260")
    assert codes.lot_numbers == ["224010", "321260"]


@pytest.mark.parametrize(
    "text",
    ["All lots", "all batches", "ALL CODES", "All unexpired lots.", "Lots: ALL", "every lot"],
)
def test_extract_lots_covers_all(text: str) -> None:
    assert extract_lots(text).covers_all_lots is True


@pytest.mark.parametrize("text", [None, "", "   ", "N/A"])
def test_extract_lots_empty(text: str | None) -> None:
    codes = extract_lots(text)
    assert codes.lot_numbers == []
    assert codes.covers_all_lots is False
    assert codes.ndc_raw == []


def test_extract_lots_rejects_quantities_and_years() -> None:
    assert extract_lots("Lot: 90 count bottles packed in 2014").lot_numbers == []


def test_extract_lots_caps_and_dedupes() -> None:
    many = "Lot #: " + ", ".join(f"AB{n:05d}" for n in range(MAX_LOTS + 40))
    assert len(extract_lots(many).lot_numbers) == MAX_LOTS
    assert extract_lots("Lot: 123456, 123456, 123-456").lot_numbers == ["123456"]


def test_extract_lots_labelled_date_shaped_lot() -> None:
    # openFDA D-0462-2026: the lot really is a yyyymmdd-looking number.
    codes = extract_lots("Lot# 20240524, Exp Date: 05/24/2026.")
    assert codes.lot_numbers == ["20240524"]


def test_extract_lots_labelled_date_shaped_list() -> None:
    assert extract_lots("Lot # 20240524, 20240601, Exp 05/2026").lot_numbers == [
        "20240524",
        "20240601",
    ]


def test_extract_lots_unlabelled_date_shape_still_rejected() -> None:
    assert extract_lots("20240524").lot_numbers == []


@pytest.mark.parametrize(
    "label",
    ["Lot#", "Lot #:", "Lot No.", "Lots:", "Batch", "Batch No", "B/N", "Control #"],
)
def test_extract_lots_explicit_labels_admit_digits(label: str) -> None:
    assert extract_lots(f"{label} 20240524").lot_numbers == ["20240524"]


@pytest.mark.parametrize(
    "label",
    ["Exp", "Expiry", "Expires", "Exp Date:", "Use by", "BUD", "Best before", "Mfg",
     "Manufactured date:"],
)
def test_extract_lots_expiry_labels_never_yield_lots(label: str) -> None:
    # Even with a lot already collected, an expiry label must not leak its date.
    assert extract_lots(f"Lot: A1234, {label} 20260524").lot_numbers == ["A1234"]


def test_extract_lots_pack_descriptors_and_parentheticals() -> None:
    codes = extract_lots(
        "Lots: D2402430, D2402431 (90-count bottles, NDC 16729-457-15); "
        "D2402432, D2500180 (1000-count), Exp 08/2026"
    )
    assert codes.lot_numbers == ["D2402430", "D2402431", "D2402432", "D2500180"]
    assert codes.ndc_raw == ["16729-457-15"]


@pytest.mark.parametrize(
    "descriptor",
    ["90-count", "90ct", "1000 tablets", "60 capsules", "30mL", "500mg", "200 mcg",
     "100 units", "12 bottles", "x 30"],
)
def test_extract_lots_never_emits_pack_descriptors(descriptor: str) -> None:
    assert extract_lots(f"Lot: {descriptor}").lot_numbers == []


@pytest.mark.parametrize(
    ("code_info", "expected"),
    [
        # Real openFDA lots that end in a unit-like suffix: the pack-size filter
        # must key on the short digit run, not on the suffix alone.
        ("Lot #: 070717ML, Exp. 1/7/18", ["070717ML"]),
        ("Lot: 010518G", ["010518G"]),
        # "L/N" is a lot label; without it the MFG aside swallows the lot.
        ("Lot: MFG: 2020/05/10 L/N: 20200510-3", ["202005103"]),
        # "Sep. 25th, 2025" must not leak "25TH" as a lot.
        (
            "Batch # CP-030-20250911, Mfg Date: Sep. 25th, 2025, Retest Date: Sep. 24th, 2027.",
            ["CP03020250911"],
        ),
    ],
)
def test_extract_lots_live_corpus_regressions(code_info: str, expected: list[str]) -> None:
    assert extract_lots(code_info).lot_numbers == expected


def test_extract_batches_from_prose_rejects_bare_gram_strength() -> None:
    assert extract_batches_from_prose("Batch: 500G") == []
    # ...but a long date-coded batch ending in G survives.
    assert extract_batches_from_prose("Batch: 010518G") == ["010518G"]


def test_extract_lots_semicolon_and_paren_do_not_end_collection() -> None:
    assert extract_lots("Lots: A1234; B5678").lot_numbers == ["A1234", "B5678"]
    assert extract_lots("Lots: A1234 (NDC 16729-457-15) B5678").lot_numbers == ["A1234", "B5678"]


def test_extract_lots_comma_separated_lot_expiry_pairs() -> None:
    """fda-enf-D-0823-2026, verbatim: pairs separated by commas, not `;`.

    The expiry label opened an aside that nothing ever closed, so every lot after
    the first was dropped — 4,710 lots across 750 cached FDA records.
    """
    codes = extract_lots(
        "Lots: H22V01 Exp. 8/29/2026, H22V02 Exp. 8/30/2026, "
        "K22V02A Exp. 10/29/2026, M10V01 Exp. 01/21/2027"
    )
    assert codes.lot_numbers == ["H22V01", "H22V02", "K22V02A", "M10V01"]


def test_extract_lots_compound_label_header_keeps_the_first_lot() -> None:
    """fda-enf-D-0672-2026: `Lot, expiry:` names two columns, so the value right
    after it is a lot — treating the `expiry` half as an aside ate RPTH0125A."""
    codes = extract_lots(
        "Lot, expiry:            RPTH0125A Jan 31, 2028;   RPTH0225A Jan 31, 2028;   "
        "RPTH0325A Jan 31, 2028;   RPTH0725A Apr 30, 2028;"
    )
    assert codes.lot_numbers == ["RPTH0125A", "RPTH0225A", "RPTH0325A", "RPTH0725A"]


def test_extract_lots_separate_expiry_label_still_opens_an_aside() -> None:
    # Only a label that *directly* follows a lot label is a compound header.
    assert extract_lots("Lot: A1234, Exp 20260524").lot_numbers == ["A1234"]


# ------------------------------------------------------------------ code tokens


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        # The Lipitor recall's batch cells: a code plus a livery name.
        ("T43157 (Almus)", ["T43157"]),
        ("T43166 (Lipitor)", ["T43166"]),
        # A range cell yields its endpoints; the caller expands the interior.
        ("From 5000879 to 5000964", ["5000879", "5000964"]),
        # A leading "#" is punctuation, not part of the code.
        ("# 56688403", ["56688403"]),
        # gov.uk prints some real batches with an underscore.
        ("B231264_01", ["B23126401"]),
        # A product name in the wrong column must yield nothing at all.
        ("KOGENATE BAYER 500 IU", []),
        ("12/06/2018", []),
        ("Expiry date", []),
        ("", []),
        (None, []),
    ],
)
def test_code_tokens(cell: str | None, expected: list[str]) -> None:
    assert code_tokens(cell) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("ITA2N65", "ITA2N65"),
        ("56688403", "56688403"),
        ("12/06/2018", None),
        ("28FEB16", None),
        ("500mg", None),
        ("2018", None),  # a bare year is never a batch
        ("20180601", None),  # nor a packed date
        ("IU", None),
        ("BATCH", None),
    ],
)
def test_code_token(token: str, expected: str | None) -> None:
    assert code_token(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("FA2B6004A", "FA2B6004A"),
        ("737A", "737A"),
        # Health Canada cells split on whitespace: neighbouring words and short
        # digit runs are not lot numbers, and they are exact-matchable if kept.
        ("EXPIRY", None),
        ("CANADIAN", None),
        ("ALL", None),
        ("2029", None),
        ("737", None),
    ],
)
def test_lot_code_is_the_public_gate(token: str, expected: str | None) -> None:
    assert lot_code(token) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("All lots", True),
        ("All lots (since July 2023)", True),
        ("Lots: ALL", True),
        ("737, 737A, 737B", False),
        ("", False),
        (None, False),
    ],
)
def test_mentions_all_lots(text: str | None, expected: bool) -> None:
    assert mentions_all_lots(text) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" d2402430 ", "D2402430"),
        ("15617VP-02", "15617VP02"),
        ("LOT# A1234", "A1234"),
        ("Lot No. 6107992", "6107992"),
        ("B/N 123456", "123456"),
        ("BATCH 023011", "023011"),
        ("ab", None),
        ("", None),
        (None, None),
        ("X" * 40, None),
    ],
)
def test_normalize_lot(value: str | None, expected: str | None) -> None:
    assert normalize_lot(value) == expected


# --------------------------------------------------------------------------- prose batches

OZEMPIC_ALERT = (
    "WHO has been informed that batch number LP6F832 is not recognized by the genuine "
    "manufacturer. In addition, the combination of batch number NAR0074 with serial "
    "number 430834149057 was found on a falsified product. Finally, batch number MP5E511 "
    "is genuine, but the product is falsified."
)


def test_extract_batches_from_prose_ozempic() -> None:
    assert extract_batches_from_prose(OZEMPIC_ALERT) == [
        "LP6F832",
        "NAR0074",
        "430834149057",
        "MP5E511",
    ]


def test_extract_batches_from_prose_who_annex() -> None:
    batches = extract_batches_from_prose(
        "Batch 023011 / H02605 were detected in Cameroon. "
        "The product carries batch number H026051 in the Central African Republic."
    )
    assert {"023011", "H02605", "H026051"} <= set(batches)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("batch number LP6F832", ["LP6F832"]),
        ("Lot: BP5203", ["BP5203"]),
        ("Batch No. 023011 and H02605", ["023011", "H02605"]),
        ("batch numbers listed below", []),
        ("Batch Number and Serial numbers", []),
        (None, []),
        ("", []),
        # Whitespace-separated runs (WHO annex tables lose their delimiters).
        ("Batch numbers: AVT50 FNR06 SGL04", ["AVT50", "FNR06", "SGL04"]),
        ("Batch 023011 023011 H02605", ["023011", "H02605"]),
    ],
)
def test_extract_batches_from_prose_cases(text: str | None, expected: list[str]) -> None:
    assert extract_batches_from_prose(text) == expected


@pytest.mark.parametrize(
    "noise",
    ["28FEB16", "28-FEB-2016", "FEB2027", "300MG", "500 MG", "10ML", "2027", "5 IU", "listed"],
)
def test_extract_batches_from_prose_rejects_dates_and_strengths(noise: str) -> None:
    assert extract_batches_from_prose(f"Batch: {noise}") == []


def test_extract_batches_from_prose_run_stops_at_non_batch_token() -> None:
    assert extract_batches_from_prose("Batch H02605, 500MG, 10ML, 2027") == ["H02605"]
    assert extract_batches_from_prose(
        "Batch number: 023011, strength 500MG, expiry 28FEB16"
    ) == ["023011"]


# --------------------------------------------------------------------------- NDC


@pytest.mark.parametrize(
    ("value", "product_ndc", "ndc9", "ndc11"),
    [
        ("16729-457-15", "16729-457", "167290457", "16729045715"),
        ("0093-0058-01", "0093-0058", "000930058", "00093005801"),
        ("76420-833-01", "76420-833", "764200833", "76420083301"),
        ("76420-8331-1", "76420-8331", "764208331", "76420833101"),
        ("50580-451", "50580-451", "505800451", None),
        ("0603-5892", "0603-5892", "006035892", None),
        ("NDC 0093-0058-01", "0093-0058", "000930058", "00093005801"),
        ("NDC 0603-5892-21", "0603-5892", "006035892", "00603589221"),
        ("00093005801", "00093-0058", "000930058", "00093005801"),
        ("0603589221", None, None, None),
    ],
)
def test_normalize_ndc(
    value: str, product_ndc: str | None, ndc9: str | None, ndc11: str | None
) -> None:
    forms = normalize_ndc(value)
    assert forms is not None
    assert forms.raw == value
    assert forms.product_ndc == product_ndc
    assert forms.ndc9 == ndc9
    assert forms.ndc11 == ndc11


@pytest.mark.parametrize("value", [None, "", "   ", "hello", "123", "12-34-56", "N/A"])
def test_normalize_ndc_garbage(value: str | None) -> None:
    assert normalize_ndc(value) is None


def test_extract_ndcs() -> None:
    text = "Mfd for Acme, NDC 66689-037-50, product 0603-5892, package 63323-010-20, 66689-037-50"
    assert extract_ndcs(text) == ["66689-037-50", "0603-5892", "63323-010-20"]
    assert extract_ndcs(None) == []


# --------------------------------------------------------------------------- imprint


@pytest.mark.parametrize(
    ("value", "norm", "sorted_", "parts", "text"),
    [
        ("5892;V", "5892V", "5892V", ["5892", "V"], "5892 V"),
        ("L484", "L484", "L484", ["L484"], "L484"),
        ("TEVA 3109", "TEVA3109", "3109TEVA", ["TEVA", "3109"], "TEVA 3109"),
        ("M | 30", "M30", "30M", ["M", "30"], "M 30"),
        ("apo,tev", "APOTEV", "APOTEV", ["APO", "TEV"], "APO TEV"),
    ],
)
def test_normalize_imprint(
    value: str, norm: str, sorted_: str, parts: list[str], text: str
) -> None:
    forms = normalize_imprint(value)
    assert forms is not None
    assert forms.raw == value
    assert forms.norm == norm
    assert forms.sorted == sorted_
    assert forms.parts == parts
    assert forms.text == text


@pytest.mark.parametrize("value", [None, "", "   ", "none", "No imprint", "BLANK", "n/a", "..."])
def test_normalize_imprint_blank(value: str | None) -> None:
    assert normalize_imprint(value) is None


# --------------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("value", "iso"),
    [
        ("20180829", "2018-08-29T00:00:00Z"),
        ("2026-09-02", "2026-09-02T00:00:00Z"),
        ("2026-09-02T00:00:00Z", "2026-09-02T00:00:00Z"),
        ("2026-09-02T12:30:00+02:00", "2026-09-02T10:30:00Z"),
        ("2/12/2027", "2027-02-12T00:00:00Z"),
        ("02/2027", "2027-02-01T00:00:00Z"),
        ("September 2, 2026", "2026-09-02T00:00:00Z"),
        ("2 September 2026", "2026-09-02T00:00:00Z"),
        ("2026-09", "2026-09-01T00:00:00Z"),
        (datetime(2020, 1, 1), "2020-01-01T00:00:00Z"),
        (datetime(2020, 1, 1, tzinfo=UTC), "2020-01-01T00:00:00Z"),
        (date(2020, 1, 1), "2020-01-01T00:00:00Z"),
    ],
)
def test_parse_date(value: object, iso: str) -> None:
    parsed = parse_date(value)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert to_iso(parsed) == iso


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "garbage",
        "N/A",
        1700000000,  # epoch millis/seconds are explicitly not accepted
        "1700000000",
        "1535500800000",
        "2026",
        "1899-01-01",
        "2200-01-01",
        True,
    ],
)
def test_parse_date_rejects(value: object) -> None:
    assert parse_date(value) is None


def test_to_iso_none() -> None:
    assert to_iso(None) is None


@pytest.mark.parametrize(
    ("value", "iso"),
    [
        ("EXP 02/2027", "2027-02-28T00:00:00Z"),
        ("Exp. Date: 02/2027", "2027-02-28T00:00:00Z"),
        ("2027-02", "2027-02-28T00:00:00Z"),
        ("02/27", "2027-02-28T00:00:00Z"),
        ("FEB 2027", "2027-02-28T00:00:00Z"),
        ("February 2027", "2027-02-28T00:00:00Z"),
        ("12/31/2026", "2026-12-31T00:00:00Z"),
        ("2024-02", "2024-02-29T00:00:00Z"),
        ("USE BY 06/2030", "2030-06-30T00:00:00Z"),
    ],
)
def test_parse_expiration(value: str, iso: str) -> None:
    assert to_iso(parse_expiration(value)) == iso


@pytest.mark.parametrize("value", [None, "", "EXP", "garbage"])
def test_parse_expiration_rejects(value: str | None) -> None:
    assert parse_expiration(value) is None


# --------------------------------------------------------------------------- names


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Losartan Potassium Tablets USP 100 mg", "losartan potassium"),
        ("Nystatin Oral Suspension, USP 500,000 units/5mL", "nystatin"),
        ("Amoxicillin 500mg", "amoxicillin"),
        ("Levothyroxine Sodium 200 mcg", "levothyroxine sodium"),
        ("Fentanyl 5 mg/5 mL Injection", "fentanyl"),
        ("  OZEMPIC  ", "ozempic"),
        ("Tablets, USP", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_drug_name(value: str | None, expected: str | None) -> None:
    assert normalize_drug_name(value) == expected


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "Losartan Potassium Tablets USP 100 mg 90 film coated tablets "
            "Manufactured by: Vivimed Labs",
            ["losartan potassium"],
        ),
        ("Nystatin Oral Suspension, USP 500,000 units/5mL Cup", ["nystatin"]),
        ("SKY Aspirin Chewable Tablets, 81 mg, 36 count, Rx only", ["sky aspirin"]),
        (
            "PGE1/Papaverine HCl/Phentolamine Injection, 10 mL vial",
            ["pge1", "papaverine hcl", "phentolamine"],
        ),
        ("Metformin HCl ER 500 mg, NDC 12345-678-90", ["metformin hcl er"]),
        ("", []),
        (None, []),
    ],
)
def test_extract_drug_names(description: str | None, expected: list[str]) -> None:
    assert extract_drug_names(description) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("tablet", "tablet"),
        ("TABLETS", "tablet"),
        ("caplet", "tablet"),
        ("film-coated tablet", "tablet"),
        ("TABLET, FILM COATED", "tablet"),
        ("capsule", "capsule"),
        ("softgel", "capsule"),
        ("vial", "injection"),
        ("ampoule", "injection"),
        ("prefilled syringe", "injection"),
        ("oral solution", "solution"),
        ("oral suspension", "suspension"),
        ("syrup", "syrup"),
        ("transdermal patch", "patch"),
        ("nasal spray", "spray"),
        ("eye drops", "drops"),
        ("metered dose inhaler", "inhaler"),
        ("suppository", "suppository"),
        ("lozenge", "other"),
        ("banana", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_dosage_form(value: str | None, expected: str | None) -> None:
    assert normalize_dosage_form(value) == expected


# --------------------------------------------------------------------------- severity


@pytest.mark.parametrize(
    ("org", "classification", "doc_type", "severity"),
    [
        ("FDA", "Class I", None, "critical"),
        ("FDA", "Class II", None, "high"),
        ("FDA", "Class III", None, "moderate"),
        ("FDA", "", None, "unknown"),
        ("FDA", None, None, "unknown"),
        ("Health Canada", "Type I", None, "critical"),
        ("Health Canada", "Type II", None, "high"),
        ("Health Canada", "Type III", None, "moderate"),
        ("Health Canada", "Class 1", None, "critical"),
        ("Health Canada", "Type I - Type II", None, "critical"),
        ("Health Canada", "--", None, "unknown"),
        ("Health Canada", "", None, "unknown"),
        ("MHRA", "Class 1", None, "critical"),
        ("MHRA", "Class 2", None, "critical"),
        ("MHRA", "Class 3", None, "high"),
        ("MHRA", "Class 4", None, "moderate"),
        ("MHRA", "company-led", None, "moderate"),
        ("MHRA", None, None, "unknown"),
        ("WHO", None, "falsified_alert", "critical"),
        ("WHO", None, "substandard_alert", "high"),
        ("WHO", None, "safety_alert", "unknown"),
        ("NAFDAC", None, "falsified_alert", "critical"),
        ("NAFDAC", None, "substandard_alert", "high"),
        ("NAFDAC", None, "recall", "high"),
        ("NAFDAC", "watchlist", None, "moderate"),
        ("NAFDAC", None, None, "unknown"),
        ("Mystery Agency", "Class I", None, "unknown"),
    ],
)
def test_severity_for(org: str, classification: str | None, doc_type: str | None, severity: str) -> None:
    assert severity_for(org, classification, doc_type) == (severity, SEVERITY_RANKS[severity])


def test_severity_rank_polarity() -> None:
    # audit finding 5: higher rank == worse, so SORT severity_rank DESC is correct.
    ranks = [severity_for("FDA", f"Class {c}")[1] for c in ("I", "II", "III")]
    assert ranks == sorted(ranks, reverse=True)
    assert severity_for("FDA", "")[1] < min(ranks)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Falsified DARZALEX detected", "falsified_alert"),
        ("Counterfeit product seized", "falsified_alert"),
        ("fake registration number", "falsified_alert"),
        ("spurious medicine", "falsified_alert"),
        ("Substandard amoxicillin", "substandard_alert"),
        ("Product found to be contaminated", "substandard_alert"),
        ("Result is out of specification", "substandard_alert"),
        ("Not of standard quality", "substandard_alert"),
        ("Voluntary nationwide recall", "recall"),
        ("Company withdraws product", "recall"),
        ("General safety information", "safety_alert"),
        (None, "safety_alert"),
        ("", "safety_alert"),
    ],
)
def test_classify_doc_type(text: str | None, expected: str) -> None:
    assert classify_doc_type(text) == expected


def test_classify_doc_type_default_override() -> None:
    assert classify_doc_type("nothing relevant", default="recall") == "recall"


# --------------------------------------------------------------------------- countries


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("detected in Maldives and Mexico", ["Maldives", "Mexico"]),
        ("Georgia", []),
        ("The Republic of Georgia reported cases", ["Georgia"]),
        ("Jersey", []),
        ("Papua New Guinea", ["Papua New Guinea"]),
        ("Guinea-Bissau", ["Guinea-Bissau"]),
        ("Equatorial Guinea", ["Equatorial Guinea"]),
        ("Guinea", ["Guinea"]),
        ("Nigeria", ["Nigeria"]),
        ("Niger", ["Niger"]),
        ("Dominican Republic", ["Dominican Republic"]),
        ("Dominica", ["Dominica"]),
        ("Indiana", []),
        ("India", ["India"]),
        ("USA", ["United States"]),
        ("United States of America", ["United States"]),
        ("UK", ["United Kingdom"]),
        ("DRC", ["Democratic Republic of the Congo"]),
        ("Cote d'Ivoire", ["Cote d'Ivoire"]),
        ("Côte d’Ivoire", ["Cote d'Ivoire"]),
        ("CAR", []),
        ("Central African Republic", ["Central African Republic"]),
        ("Cameroon and Cameroon", ["Cameroon"]),
        (None, []),
        ("", []),
    ],
)
def test_extract_countries(text: str | None, expected: list[str]) -> None:
    assert extract_countries(text) == expected


def test_extract_countries_order_of_appearance() -> None:
    assert extract_countries("Shipped from India to Kenya, then Brazil.") == [
        "India",
        "Kenya",
        "Brazil",
    ]


# --------------------------------------------------------------------------- urls


def test_canonical_url() -> None:
    url = "HTTPS://WWW.Example.com/a/b/?utm_source=x&b=2&a=1&fbclid=z&gclid=q&ref=r#frag"
    assert canonical_url(url) == "https://www.example.com/a/b?a=1&b=2"
    assert canonical_url("https://example.com") == "https://example.com/"
    assert canonical_url("https://example.com/") == "https://example.com/"
    assert canonical_url("https://example.com:443/x/") == "https://example.com/x"
    assert canonical_url("example.com/x") == "https://example.com/x"
    assert canonical_url("") == ""


def test_canonical_url_is_stable_and_hashable() -> None:
    a = "https://who.int/news/item/alert?utm_campaign=x#top"
    b = "HTTPS://who.int/news/item/alert/"
    assert canonical_url(a) == canonical_url(b)
    assert url_hash(a) == url_hash(b)
    assert len(url_hash(a)) == 32


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.fda.gov/a/b", "fda.gov"),
        ("http://NAFDAC.gov.ng/", "nafdac.gov.ng"),
        ("who.int/news", "who.int"),
        ("", ""),
    ],
)
def test_domain_of(url: str, domain: str) -> None:
    assert domain_of(url) == domain


def test_content_hash_and_query_key() -> None:
    assert content_hash("  Hello   World\n") == content_hash("hello world")
    assert content_hash("a") != content_hash("b")
    assert len(content_hash("a")) == 64
    assert query_key("  Ozempic   RECALL ") == "ozempic recall"


# --------------------------------------------------------------------------- recency

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-19", 0),
        ("2026-09-18", 1),
        ("2026-09-01", 18),
        ("2025-09-19", 365),
        ("2027-01-01", 0),  # never negative
        (None, None),
        ("garbage", None),
    ],
)
def test_age_days(value: str | None, expected: int | None) -> None:
    assert age_days(value, NOW) == expected


def test_age_days_defaults_to_now() -> None:
    assert age_days(datetime.now(UTC)) == 0


@pytest.mark.parametrize(
    ("age", "label"),
    [
        (None, "unknown"),
        (0, "today"),
        (1, "today"),
        (2, "this_week"),
        (7, "this_week"),
        (8, "this_month"),
        (31, "this_month"),
        (32, "this_year"),
        (365, "this_year"),
        (366, "older"),
    ],
)
def test_freshness_label(age: int | None, label: str) -> None:
    assert freshness_label(age) == label


# --------------------------------------------------------------------------- text


def test_truncate_on_sentence_keeps_short_text() -> None:
    assert truncate_on_sentence("Short text.", 100) == "Short text."


def test_truncate_on_sentence_cuts_at_sentence() -> None:
    text = "Alpha beta gamma delta epsilon. Zeta eta theta iota kappa lambda mu nu."
    out = truncate_on_sentence(text, 40)
    assert out == "Alpha beta gamma delta epsilon."
    assert len(out) <= 40


def test_truncate_on_sentence_falls_back_to_word_boundary() -> None:
    text = "A. " + "word " * 40
    out = truncate_on_sentence(text, 30)
    assert len(out) <= 30
    assert not out.endswith(" ")
    assert out.split()[-1] == "word"


def test_truncate_on_sentence_zero_cap() -> None:
    assert truncate_on_sentence("anything", 0) == ""


HTML_SNIPPET = """
<html><head><style>p { color: red }</style></head>
<body>
  <nav>Skip me</nav>
  <header>Also skip</header>
  <article>
    <h1>Alert N&deg;3/2026 &amp; annex</h1>
    <p>Batch   LP6F832 is
       falsified.</p>
    <table>
      <tr><th>Lot</th><th>Expiry</th></tr>
      <tr><td>023011</td><td>18/07/2025</td></tr>
    </table>
  </article>
  <footer>Footer junk</footer>
  <script>var x = 1;</script>
  <noscript>enable js</noscript>
</body></html>
"""


def test_html_to_text() -> None:
    text = html_to_text(HTML_SNIPPET)
    assert "Skip me" not in text
    assert "Also skip" not in text
    assert "Footer junk" not in text
    assert "var x" not in text
    assert "enable js" not in text
    assert "color: red" not in text
    assert "Alert N°3/2026 & annex" in text
    assert "Batch LP6F832 is falsified." in text
    assert "Lot | Expiry" in text
    assert "023011 | 18/07/2025" in text
    assert "\n\n\n" not in text


def test_html_to_text_handles_garbage() -> None:
    assert html_to_text("") == ""
    assert "hello" in html_to_text("<p>hello<p")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  a   b ", "a b"),
        ("a\n\tb", "a b"),
        (42, "42"),
        ("N/A", None),
        ("None", None),
        ("--", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_text(value: object, expected: str | None) -> None:
    assert clean_text(value) == expected
