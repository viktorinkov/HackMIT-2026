from __future__ import annotations

import pytest

from backend.graph.keys import (
    cluster_key,
    company_key,
    country_key,
    country_label,
    drug_key,
    imprint_key,
    lot_key,
    product_key,
    regulator_key,
    slug,
    topic_of,
    web_key,
)

# Every string below was copied out of the seeded corpus.
ACCORD_VARIANTS = [
    "Accord Healthcare Inc.",
    "Accord Healthcare, Inc.,",
    "ACCORD HEALTHCARE, INC.",
    "Accord Healthcare Limited",
    "Accord Healthcare Ltd",
    "Accord Healthcare Limited - Losartan Potassium 50mg Film-coated Tablets",
]

NAFDAC_PROSE = (
    "Maxheal Pharmaceuticals (India), with batch numbers 023011 and H02605, "
    "found in Cameroon and H02605 in the Central African Republic (CAR)"
)


def test_company_key_merges_the_six_accord_variants() -> None:
    assert {company_key(value) for value in ACCORD_VARIANTS} == {"accord healthcare"}


def test_company_key_cuts_the_nafdac_prose_after_the_company_name() -> None:
    assert company_key(NAFDAC_PROSE) == "maxheal pharmaceuticals"
    assert company_key("MAXHEAL PHARMACEUTICALS (India) Limited") == "maxheal pharmaceuticals"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Zydus Pharmaceuticals (USA) Inc.", "zydus pharmaceuticals"),
        ("Zydus Pharmaceuticals (USA) Inc", "zydus pharmaceuticals"),
        ("Intas Pharmaceuticals Limited", "intas pharmaceuticals"),
        ("Qualitest Pharmaceuticals", "qualitest pharmaceuticals"),
        ("Sun Pharmaceutical Industries Ltd", "sun pharmaceutical industries"),
        # Nothing usable is better than a node labelled with a sentence.
        ("a", None),
        ("", None),
        (None, None),
    ],
)
def test_company_key_handles_real_manufacturer_strings(raw: str | None, expected: str | None) -> None:
    assert company_key(raw) == expected


def test_company_key_refuses_a_long_prose_fragment() -> None:
    assert company_key("recall of various products by three drug manufacturing firms") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("levothyroxine sodium", "levothyroxine"),
        ("Levothyroxine Sodium Tablets, USP, 200 mcg", "levothyroxine"),
        ("chlorpromazine hydrochloride", "chlorpromazine"),
        ("amlodipine besylate", "amlodipine"),
        ("and losartan potassium", "losartan"),
        ("batches of healmoxy", "healmoxy"),
        ("HEALMOXY", "healmoxy"),
        ("metformin hcl", "metformin"),
        # A salt is only stripped while a real name is left behind.
        ("sodium chloride", "sodium chloride"),
        ("potassium chloride", "potassium chloride"),
        ("sodium", "sodium"),
        ("various products", None),
        ("", None),
        (None, None),
    ],
)
def test_drug_key_strips_salts_and_fragments_but_keeps_sodium_chloride(
    raw: str | None, expected: str | None
) -> None:
    assert drug_key(raw) == expected


def test_drug_key_is_stable_across_the_rxnav_rewrite() -> None:
    assert drug_key("levothyroxine") == drug_key("Levothyroxine Sodium")


def test_lot_and_product_and_imprint_keys_reuse_the_shared_normalizers() -> None:
    assert lot_key("Lot D2402430") == "D2402430"
    assert lot_key("z400069") == "Z400069"
    assert product_key("16729-457-15") == "167290457"
    assert product_key("70710-1129-1") == "707101129"
    assert product_key("not an ndc") is None
    assert imprint_key("5892 V") == "5892V"
    assert imprint_key("I-2") == "I2"


def test_web_key_passes_a_page_id_through_and_hashes_a_url() -> None:
    page_id = "62a8176ee4a9b3b015e7d3df9fc32aec"
    assert web_key(page_id) == page_id
    hashed = web_key("https://www.who.int/news/item/some-alert")
    assert hashed is not None and len(hashed) == 32 and hashed != page_id


def test_country_key_canonicalises_before_slugging() -> None:
    assert country_key("USA") == "united-states"
    assert country_key("Central African Republic (CAR)") == "central-african-republic"
    assert country_label("U.K.") == "United Kingdom"
    assert country_key(None) is None


def test_regulator_key_is_a_stable_slug_per_source_org() -> None:
    assert regulator_key("FDA") == "fda"
    assert regulator_key("openFDA") == "fda"
    assert regulator_key("Health Canada") == "health-canada"
    assert regulator_key("NAFDAC") == "nafdac"
    assert regulator_key(None) is None


def test_topic_of_prefers_the_doc_type_then_falls_back_to_the_reason() -> None:
    assert topic_of("falsified_alert", "anything") == ("falsified", "Falsified product")
    assert topic_of("recall", "Subpotent Drug")[0] == "subpotent"
    assert topic_of("recall", "N-Nitroso-Desmethyl Chlorpromazine impurity")[0] == (
        "impurity-nitrosamine"
    )
    assert topic_of("recall", "no idea what this is") is None
    assert topic_of(None, None) is None


def test_slug_and_cluster_key_are_deterministic() -> None:
    assert slug("Health Canada") == "health-canada"
    assert slug("   ") is None
    assert cluster_key("reg:fda", "records") == "reg:fda|records"
