"""Web query generation: priority, dedupe, and the PII boundary."""

from __future__ import annotations

from typing import Any

from backend.research.queries import EXCLUDED_DOMAINS, EXCLUSIONS, build_web_queries


def base(text: str) -> str:
    """The query without the trailing -site: operators."""
    return text.replace(EXCLUSIONS, "").strip()

SENSITIVE = {
    "rx_number": "RX 8827341",
    "pharmacy": "Ikeja Community Pharmacy",
    "directions": "take one tablet twice daily with food",
    "other_label_text": "Patient: Ada Obi, refill before 2026-10-01",
}


def scan(**norm: Any) -> dict[str, Any]:
    base = {
        "lot": None,
        "generic_name": None,
        "brand_name": None,
        "manufacturer": None,
        "strength": None,
    }
    return {"norm": base | norm, "bottle": dict(SENSITIVE), "country": "Nigeria"}


def test_lot_query_comes_first_and_quotes_the_lot() -> None:
    queries = build_web_queries(scan(lot="D2402430", generic_name="levothyroxine"), max_queries=3)

    assert queries[0].purpose == "lot_recall"
    assert '"D2402430"' in queries[0].text
    assert queries[0].tbs is None
    assert [q.purpose for q in queries] == ["lot_recall", "counterfeit_reports", "product_recall"]


def test_without_a_lot_only_the_drug_queries_are_built() -> None:
    queries = build_web_queries(scan(generic_name="artemether"), max_queries=3)

    assert [q.purpose for q in queries] == ["counterfeit_reports", "product_recall"]
    assert [q.tbs for q in queries] == ["qdr:y", "qdr:m"]


def test_no_drug_and_no_lot_produces_nothing() -> None:
    assert build_web_queries(scan(manufacturer="Some Pharma"), max_queries=3) == []


def test_lot_alone_is_still_specific_enough() -> None:
    queries = build_web_queries(scan(lot="H02605"), max_queries=3)

    assert len(queries) == 1
    assert base(queries[0].text) == '"H02605" recall OR batch'


def test_queries_are_capped_and_keyed() -> None:
    doc = scan(lot="AB1234", generic_name="amoxicillin", manufacturer="Acme")
    queries = build_web_queries(doc, max_queries=2)

    assert len(queries) == 2
    # The key is the question, not the fetch-time filter, so cached pages survive
    # a change to the exclusion list.
    assert all(q.key == " ".join(base(q.text).casefold().split()) for q in queries)
    assert all(EXCLUSIONS not in q.key for q in queries)
    assert build_web_queries(doc, max_queries=0) == []


def test_every_query_excludes_social_and_video_domains() -> None:
    queries = build_web_queries(scan(lot="AB1234", generic_name="amoxicillin"), max_queries=3)

    assert queries
    for query in queries:
        for domain in EXCLUDED_DOMAINS:
            assert f"-site:{domain}" in query.text


def test_duplicate_queries_collapse_on_their_key() -> None:
    # brand == generic makes queries 2 and 3 identical once strength is absent.
    doc = scan(generic_name="paracetamol", brand_name="paracetamol")
    doc["country"] = None
    queries = build_web_queries(doc, max_queries=3)

    assert len({q.key for q in queries}) == len(queries)


def test_prescription_details_never_reach_a_query() -> None:
    doc = scan(lot="AB1234", generic_name="metformin", manufacturer="Acme")
    blob = " ".join(q.text for q in build_web_queries(doc, max_queries=3)).casefold()

    for value in SENSITIVE.values():
        assert value.casefold() not in blob
    assert "8827341" not in blob
    assert "ikeja" not in blob


def test_bottle_fields_are_the_fallback_when_norm_is_empty() -> None:
    doc = {
        "norm": {},
        "bottle": dict(SENSITIVE) | {"generic_name": "ibuprofen", "lot_number": "lot # nc185424"},
        "country": None,
    }
    queries = build_web_queries(doc, max_queries=3)

    assert '"NC185424"' in queries[0].text
    assert "ibuprofen" in queries[0].text


def test_quotes_in_ocr_output_cannot_rewrite_the_query() -> None:
    doc = scan(generic_name='amox" OR site:evil.example')
    text = build_web_queries(doc, max_queries=1)[0].text

    assert '"' not in text
