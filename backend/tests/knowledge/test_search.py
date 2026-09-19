"""Structure assertions on the pure query builders. No network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.knowledge import normalize, vocab
from backend.knowledge.fields import (
    REGULATORY_DECAY,
    RERANK_INFERENCE_ID,
    WEB_DECAY,
    Pill,
    Reg,
    Web,
)
from backend.knowledge.search import (
    DECAY_SCRIPT,
    SearchFilters,
    build_lot_query,
    build_ndc_query,
    build_pill_query,
    build_regulatory_query,
    build_web_query,
    utc_origin,
)

ORIGIN = "2026-09-19"


def _legs(body: dict[str, Any]) -> list[dict[str, Any]]:
    retriever = body["retriever"]
    if "text_similarity_reranker" in retriever:
        retriever = retriever["text_similarity_reranker"]["retriever"]
    return retriever["linear"]["retrievers"]


def _script_score(leg: dict[str, Any]) -> dict[str, Any]:
    return leg["retriever"]["standard"]["query"]["script_score"]


def test_regulatory_query_has_no_forbidden_top_level_keys() -> None:
    body = build_regulatory_query("levothyroxine subpotent", None, origin=ORIGIN)
    assert "retriever" in body
    for banned in ("query", "sort", "knn", "rescore", "search_after", "terminate_after"):
        assert banned not in body
    assert "knn" not in json.dumps(body)
    assert "query_vector_builder" not in json.dumps(body)


def test_regulatory_query_both_legs_are_script_scored_with_the_guard() -> None:
    body = build_regulatory_query("levothyroxine subpotent", None, origin=ORIGIN)
    legs = _legs(body)
    assert len(legs) == 2
    for leg in legs:
        assert leg["normalizer"] == "minmax"
        script = _script_score(leg)["script"]
        assert "doc[params.f].size() > 0" in script["source"]
        assert script["source"] == DECAY_SCRIPT
        assert script["params"] == {
            "f": Reg.RECENCY_DATE,
            "floor": REGULATORY_DECAY.floor,
            "origin": ORIGIN,
            "scale": "730d",
            "offset": "30d",
        }
    assert "multi_match" in _script_score(legs[0])["query"]
    assert _script_score(legs[1])["query"]["semantic"]["field"] == Reg.BODY_SEMANTIC


def test_regulatory_origin_is_the_passed_value_never_now() -> None:
    body = build_regulatory_query("x", None, origin="2020-01-02")
    for leg in _legs(body):
        assert _script_score(leg)["script"]["params"]["origin"] == "2020-01-02"
    assert "now" not in json.dumps(body)


def test_utc_origin_is_a_plain_iso_date() -> None:
    assert len(utc_origin()) == len("2026-09-19")


def test_regulatory_filter_is_a_top_level_array_shared_by_every_leg() -> None:
    filters = SearchFilters(
        drug_names=["Levothyroxine Sodium 100 mcg"],
        dosage_form="TABLET",
        doc_types=["recall"],
        source_orgs=["fda"],
        countries=["United States"],
        severities=["critical"],
        max_age_days=365,
    )
    body = build_regulatory_query("x", filters, origin=ORIGIN)
    clauses = body["retriever"]["linear"]["filter"]
    assert isinstance(clauses, list)
    # The filter lives once, at the top level, so it is pushed into the vector leg.
    for leg in _legs(body):
        assert "filter" not in _script_score(leg)["query"]

    drug_clause = clauses[0]["bool"]
    assert drug_clause["minimum_should_match"] == 1
    assert {Reg.DRUG_NAMES, Reg.DRUG_NAMES_EXTRACTED} == {
        next(iter(s["terms"])) for s in drug_clause["should"]
    }
    assert drug_clause["should"][0]["terms"][Reg.DRUG_NAMES] == ["levothyroxine sodium"]

    flat = {json.dumps(c, sort_keys=True) for c in clauses}
    assert json.dumps({"term": {Reg.DOSAGE_FORM: "tablet"}}, sort_keys=True) in flat
    assert json.dumps({"terms": {Reg.DOC_TYPE: ["recall"]}}, sort_keys=True) in flat
    assert json.dumps({"terms": {Reg.SOURCE_ORG: ["fda"]}}, sort_keys=True) in flat
    assert json.dumps({"terms": {Reg.COUNTRIES: ["United States"]}}, sort_keys=True) in flat
    assert json.dumps({"terms": {Reg.SEVERITY: ["critical"]}}, sort_keys=True) in flat
    assert clauses[-1]["range"][Reg.RECENCY_DATE]["gte"] == f"{ORIGIN}||-365d"


def test_empty_filters_produce_an_empty_filter_array() -> None:
    assert build_regulatory_query("x", None, origin=ORIGIN)["retriever"]["linear"]["filter"] == []
    assert SearchFilters().is_empty()


def test_rerank_wraps_linear_and_targets_the_real_text_field() -> None:
    body = build_regulatory_query("lot 15617VP03", None, origin=ORIGIN, rerank=True)
    wrapper = body["retriever"]["text_similarity_reranker"]
    assert wrapper["field"] == Reg.BODY
    assert wrapper["field"] != Reg.BODY_SEMANTIC
    assert wrapper["inference_id"] == RERANK_INFERENCE_ID
    assert wrapper["inference_text"] == "lot 15617VP03"
    assert "linear" in wrapper["retriever"]
    assert "query" not in body and "sort" not in body


def test_regulatory_source_excludes_raw_and_semantic() -> None:
    body = build_regulatory_query("x", None, origin=ORIGIN)
    assert set(body["_source"]["excludes"]) == {Reg.RAW, Reg.BODY_SEMANTIC}


def test_web_query_uses_the_web_decay_profile_and_fields() -> None:
    body = build_web_query("nafdac falsified", origin=ORIGIN, source_tiers=["regulator"])
    legs = _legs(body)
    for leg in legs:
        params = _script_score(leg)["script"]["params"]
        assert params["f"] == Web.RECENCY_DATE
        assert params["floor"] == WEB_DECAY.floor
        assert params["scale"] == f"{WEB_DECAY.scale_days}d"
        assert params["offset"] == f"{WEB_DECAY.offset_days}d"
    assert _script_score(legs[1])["query"]["semantic"]["field"] == Web.PAGE_SEMANTIC
    assert body["retriever"]["linear"]["filter"] == [{"terms": {Web.SOURCE_TIER: ["regulator"]}}]
    assert "query" not in body and "sort" not in body


def test_web_scan_id_filter() -> None:
    body = build_web_query("x", origin=ORIGIN, scan_id="scan-7")
    assert {"term": {Web.SCAN_IDS: "scan-7"}} in body["retriever"]["linear"]["filter"]


def test_lot_query_is_constant_score_term_and_never_decayed() -> None:
    body = build_lot_query("D2402430")
    assert body["query"]["constant_score"]["filter"] == {"term": {Reg.LOT_NUMBERS: "D2402430"}}
    assert body["sort"] == [{Reg.SEVERITY_RANK: "desc"}, {Reg.RECENCY_DATE: "desc"}]
    assert "retriever" not in body
    assert "script_score" not in json.dumps(body)


def test_ndc_query_is_constant_score_and_prefers_the_described_ndc() -> None:
    forms = normalize.normalize_ndc("16729-457-15")
    assert forms is not None
    body = build_ndc_query(forms)
    should = body["query"]["bool"]["should"]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    precise = should[0]["constant_score"]
    assert precise["filter"]["terms"][Reg.NDC_FROM_DESCRIPTION][0] == forms.ndc11
    # The recall naming this NDC in its own text must outrank sibling-strength recalls.
    assert precise["boost"] > 1
    assert {"constant_score": {"filter": {"term": {Reg.NDC9: forms.ndc9}}, "boost": 1.0}} in should
    assert body["sort"][0] == "_score"
    assert "script_score" not in json.dumps(body)
    assert "retriever" not in body


@pytest.fixture
def imprint():
    forms = normalize.normalize_imprint("5892;V")
    assert forms is not None
    return forms


def _should(body: dict[str, Any]) -> list[dict[str, Any]]:
    return body["query"]["bool"].get("should", [])


def _filters(body: dict[str, Any]) -> list[dict[str, Any]]:
    return body["query"]["bool"].get("filter", [])


def test_pill_rung1_hard_filters_the_shape_family(imprint) -> None:
    body = build_pill_query(imprint, shape="oblong", colors=["pink"], rung=1, mode="family")
    assert _filters(body) == [{"term": {Pill.SHAPE_FAMILY: vocab.shape_family("oblong")}}]
    should = _should(body)
    assert should[0]["term"][Pill.IMPRINT_NORM]["boost"] == 100
    assert should[1]["term"][Pill.IMPRINT_SORTED]["boost"] == 60
    # Colour is a boost, never a filter, once an imprint is available.
    assert {"terms": {Pill.COLORS: ["pink"], "boost": 1.5}} in should
    assert body["query"]["bool"]["minimum_should_match"] == 1
    assert "imprint_ngrams" not in json.dumps(body)


def test_pill_rung1_strict_mode_filters_the_exact_shape(imprint) -> None:
    body = build_pill_query(imprint, shape="capsule", rung=1, mode="strict")
    assert _filters(body) == [{"term": {Pill.SHAPE: "capsule"}}]


def test_pill_boost_mode_never_hard_filters_shape(imprint) -> None:
    body = build_pill_query(imprint, shape="round", rung=1, mode="boost")
    assert _filters(body) == []


def test_pill_rung2_demotes_shape_to_a_boost(imprint) -> None:
    body = build_pill_query(imprint, shape="oblong", colors=["pink"], rung=2, mode="family")
    assert _filters(body) == []
    family = vocab.shape_family("oblong")
    assert {"term": {Pill.SHAPE_FAMILY: {"value": family, "boost": 3.0}}} in _should(body)
    assert {"terms": {Pill.COLORS: ["pink"], "boost": 1.5}} in _should(body)


def test_pill_rung3_is_imprint_only(imprint) -> None:
    body = build_pill_query(
        imprint, shape="oblong", colors=["pink"], score=2, size_mm=15.0, rung=3, mode="family"
    )
    assert _filters(body) == []
    rendered = json.dumps(_should(body))
    assert Pill.SHAPE_FAMILY not in rendered
    assert Pill.COLORS not in rendered
    assert Pill.SCORE not in rendered
    assert Pill.SIZE_MM not in rendered
    assert len(_should(body)) == 4


def test_pill_rungs_differ(imprint) -> None:
    bodies = [
        json.dumps(build_pill_query(imprint, shape="oblong", colors=["pink"], rung=r), sort_keys=True)
        for r in (1, 2, 3)
    ]
    assert len(set(bodies)) == 3


def test_pill_tiers_are_ordered_exact_then_sorted_then_parts_then_fuzzy(imprint) -> None:
    should = _should(build_pill_query(imprint, rung=3))
    assert should[0]["term"][Pill.IMPRINT_NORM] == {"value": imprint.norm, "boost": 100}
    assert should[1]["term"][Pill.IMPRINT_SORTED] == {"value": imprint.sorted, "boost": 60}
    assert should[2]["terms"][Pill.IMPRINT_PARTS] == imprint.parts
    assert should[3]["match"][Pill.IMPRINT_TEXT]["fuzziness"] == "AUTO"


def test_pill_size_boost_is_a_two_millimetre_window(imprint) -> None:
    body = build_pill_query(imprint, size_mm=15.0, rung=1)
    window = next(c for c in _should(body) if "range" in c)["range"][Pill.SIZE_MM]
    assert (window["gte"], window["lte"]) == (13.0, 17.0)


def test_pill_without_imprint_filters_on_shape_and_colors() -> None:
    body = build_pill_query(None, shape="round", colors=["white"], rung=1, mode="family")
    assert {"term": {Pill.SHAPE_FAMILY: "round"}} in _filters(body)
    assert {"terms": {Pill.COLORS: ["white"]}} in _filters(body)
    assert body["query"]["bool"]["minimum_should_match"] == 0


def test_pill_with_no_signal_at_all_is_still_a_valid_query() -> None:
    body = build_pill_query(None, shape=None, colors=[], rung=1)
    assert body["query"]["bool"]["must"] == [{"match_all": {}}]
