"""Structure assertions on the pure query builders, plus the classification that
turns raw hits into match kinds. Retrieval itself is exercised in the live tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.knowledge import normalize, vocab
from backend.knowledge.fields import (
    REGULATORY_DECAY,
    RERANK_INFERENCE_ID,
    WEB_DECAY,
    Pill,
    Reg,
    Scan,
    Web,
)
from backend.knowledge.router import router as knowledge_router
from backend.knowledge.search import (
    DECAY_SCRIPT,
    MAX_REGULATORY_SIZE,
    MAX_RERANK_SIZE,
    MAX_WEB_SIZE,
    Hit,
    KnowledgeSearch,
    SearchFilters,
    build_lot_query,
    build_ndc_query,
    build_pill_query,
    build_regulatory_query,
    build_web_query,
    corroborates_product,
    get_knowledge_search,
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


def _tiers(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Imprint tiers live in their own must-bool so attribute boosts cannot match alone."""
    must = body["query"]["bool"].get("must", [])
    return must[0]["bool"]["should"] if must and "bool" in must[0] else []


def _filters(body: dict[str, Any]) -> list[dict[str, Any]]:
    return body["query"]["bool"].get("filter", [])


def test_pill_rung1_hard_filters_the_shape_family(imprint) -> None:
    body = build_pill_query(imprint, shape="oblong", colors=["pink"], rung=1, mode="family")
    assert _filters(body) == [{"term": {Pill.SHAPE_FAMILY: vocab.shape_family("oblong")}}]
    tiers = _tiers(body)
    assert tiers[0]["term"][Pill.IMPRINT_NORM]["boost"] == 100
    assert tiers[1]["term"][Pill.IMPRINT_SORTED]["boost"] == 60
    # Colour is a boost, never a filter, once an imprint is available — and it sits
    # outside the imprint tiers so a colour-only match can never satisfy the query.
    assert {"terms": {Pill.COLORS: ["pink"], "boost": 1.5}} in _should(body)
    assert Pill.COLORS not in json.dumps(tiers)
    assert body["query"]["bool"]["must"][0]["bool"]["minimum_should_match"] == 1
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
    assert _should(body) == []
    assert len(_tiers(body)) == 5


def test_pill_rungs_differ(imprint) -> None:
    bodies = [
        json.dumps(build_pill_query(imprint, shape="oblong", colors=["pink"], rung=r), sort_keys=True)
        for r in (1, 2, 3)
    ]
    assert len(set(bodies)) == 3


def test_pill_tiers_are_ordered_exact_then_sorted_then_parts_then_fuzzy(imprint) -> None:
    tiers = _tiers(build_pill_query(imprint, rung=3))
    assert tiers[0]["term"][Pill.IMPRINT_NORM] == {"value": imprint.norm, "boost": 100}
    assert tiers[1]["term"][Pill.IMPRINT_SORTED] == {"value": imprint.sorted, "boost": 60}
    # One face of a two-sided imprint: every observed part present is a strong match.
    all_parts = tiers[2]["constant_score"]
    assert all_parts["filter"]["bool"]["filter"] == [
        {"term": {Pill.IMPRINT_PARTS: part}} for part in imprint.parts
    ]
    assert 10 < all_parts["boost"] < 60
    assert tiers[3]["terms"][Pill.IMPRINT_PARTS] == imprint.parts
    assert tiers[4]["match"][Pill.IMPRINT_TEXT]["fuzziness"] == "AUTO"


def test_a_single_short_fragment_gets_no_all_parts_tier() -> None:
    forms = normalize.normalize_imprint("B")
    if forms is None:  # too short to normalise at all: nothing to assert
        return
    assert "constant_score" not in json.dumps(_tiers(build_pill_query(forms, rung=3)))


def test_pill_size_boost_is_a_two_millimetre_window(imprint) -> None:
    body = build_pill_query(imprint, size_mm=15.0, rung=1)
    window = next(c for c in _should(body) if "range" in c)["range"][Pill.SIZE_MM]
    assert (window["gte"], window["lte"]) == (13.0, 17.0)


def test_pill_without_imprint_filters_on_shape_and_colors() -> None:
    body = build_pill_query(None, shape="round", colors=["white"], rung=1, mode="family")
    assert {"term": {Pill.SHAPE_FAMILY: "round"}} in _filters(body)
    assert {"terms": {Pill.COLORS: ["white"]}} in _filters(body)
    assert "must" not in body["query"]["bool"]


def test_pill_with_no_signal_at_all_matches_nothing() -> None:
    # match_all (and a bare `{"bool": {}}`) would return ten arbitrary pills
    # labelled as candidates, so the fallback has to be explicit.
    body = build_pill_query(None, shape=None, colors=[], rung=1)
    assert body["query"]["bool"]["must"] == [{"match_none": {}}]
    assert "match_all" not in json.dumps(body)


# ----------------------------------------------------------------- size bounds


def test_rank_windows_follow_an_oversized_size() -> None:
    # A retriever rejects the whole request when size > rank_window_size.
    body = build_regulatory_query("x", None, origin=ORIGIN, size=MAX_REGULATORY_SIZE + 150)
    assert body["retriever"]["linear"]["rank_window_size"] == MAX_REGULATORY_SIZE + 150
    reranked = build_regulatory_query("x", None, origin=ORIGIN, size=80, rerank=True)
    wrapper = reranked["retriever"]["text_similarity_reranker"]
    assert wrapper["rank_window_size"] == 80
    assert wrapper["retriever"]["linear"]["rank_window_size"] == MAX_REGULATORY_SIZE
    web = build_web_query("x", origin=ORIGIN, size=MAX_WEB_SIZE + 10)
    assert web["retriever"]["linear"]["rank_window_size"] == MAX_WEB_SIZE + 10


def test_default_sizes_leave_the_windows_at_their_constants() -> None:
    body = build_regulatory_query("x", None, origin=ORIGIN)
    assert body["retriever"]["linear"]["rank_window_size"] == MAX_REGULATORY_SIZE
    assert build_web_query("x", origin=ORIGIN)["retriever"]["linear"]["rank_window_size"] == (
        MAX_WEB_SIZE
    )


# ------------------------------------------------------- product corroboration


def _reg_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        Reg.RECORD_ID: "zz-1",
        Reg.DRUG_NAMES: ["levothyroxine sodium"],
        Reg.DRUG_NAMES_EXTRACTED: [],
        Reg.NDC9: ["167290457"],
        Reg.NDC_FROM_DESCRIPTION: ["167290457"],
        Reg.SEVERITY_RANK: 3,
        Reg.RECENCY_DATE: "2026-01-05",
    }
    source.update(overrides)
    return source


@pytest.mark.parametrize(
    ("source", "ndc9", "drug_names", "expected"),
    [
        # The NDC leg: either field identifies the product for a lot lookup.
        (_reg_source(), "167290457", None, True),
        (_reg_source(**{Reg.NDC_FROM_DESCRIPTION: []}), "167290457", None, True),
        (_reg_source(**{Reg.NDC9: []}), "167290457", None, True),
        (_reg_source(), "999999999", None, False),
        # A keyword field reads back as a bare string when it holds one value.
        (_reg_source(**{Reg.NDC9: "167290457"}), "167290457", None, True),
        # Token overlap, not term equality: "Lidocaine HCl" never equals the
        # stored "lidocaine hydrochloride".
        (
            _reg_source(**{Reg.DRUG_NAMES: ["lidocaine hydrochloride"]}),
            None,
            ["Lidocaine HCl"],
            True,
        ),
        # ...but the salt word alone is shared by thousands of products.
        (
            _reg_source(**{Reg.DRUG_NAMES: ["cefazolin sodium"]}),
            None,
            ["Amoxicillin Sodium"],
            False,
        ),
        # A token under four characters cannot corroborate on its own either.
        (_reg_source(**{Reg.DRUG_NAMES: ["lidocaine hydrochloride"]}), None, ["HCl"], False),
        # Names extracted from product_description count.
        (
            _reg_source(
                **{Reg.DRUG_NAMES: [], Reg.DRUG_NAMES_EXTRACTED: ["amoxicillin trihydrate"]}
            ),
            None,
            ["Amoxicillin 500 mg capsules"],
            True,
        ),
        (_reg_source(), None, ["amoxicillin"], False),
        # Nothing to corroborate with.
        (_reg_source(), None, None, False),
        (_reg_source(), None, [], False),
    ],
)
def test_corroborates_product_table(
    source: dict[str, Any], ndc9: str | None, drug_names: list[str] | None, expected: bool
) -> None:
    assert corroborates_product(source, ndc9, drug_names) is expected


# ------------------------------------------------ classification of exact hits


class _FakeEs:
    """Replays canned pages and records the bodies KnowledgeSearch sent."""

    def __init__(self, *pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages) or [[]]
        self.bodies: list[dict[str, Any]] = []

    async def search(self, *, index: str, **body: Any) -> dict[str, Any]:
        page = self.pages[min(len(self.bodies), len(self.pages) - 1)]
        self.bodies.append(body)
        return {
            "hits": {
                "hits": [
                    {
                        "_index": index,
                        "_id": source.get(Reg.RECORD_ID) or str(position),
                        "_score": 1.0,
                        "_source": source,
                    }
                    for position, source in enumerate(page)
                ]
            }
        }


def _search(es: _FakeEs, **settings: Any) -> KnowledgeSearch:
    return KnowledgeSearch(es, Settings(openai_api_key="test", **settings))


def _kinds(hits: list[Hit]) -> list[str | None]:
    return [hit.match_kind for hit in hits]


async def test_recalls_by_lot_keeps_exact_lot_when_the_record_names_the_product() -> None:
    es = _FakeEs([_reg_source()])
    hits = await _search(es).recalls_by_lot(
        "D2402430", ndc9="167290457", drug_names=["levothyroxine sodium"]
    )
    assert _kinds(hits) == ["exact_lot"]
    # The lot term is still the only retrieval clause; corroboration is applied
    # to the hits, so a genuine match is never filtered away before it is seen.
    assert es.bodies[0]["query"]["constant_score"]["filter"] == {
        "term": {Reg.LOT_NUMBERS: "D2402430"}
    }


async def test_recalls_by_lot_downgrades_a_collision_to_lot_only_match() -> None:
    es = _FakeEs([_reg_source()])
    hits = await _search(es).recalls_by_lot("MG30", drug_names=["amoxicillin"])
    assert _kinds(hits) == ["lot_only_match"]


async def test_recalls_by_lot_downgrades_when_only_the_ndc_context_misses() -> None:
    es = _FakeEs([_reg_source()])
    hits = await _search(es).recalls_by_lot("MG30", ndc9="999999999")
    assert _kinds(hits) == ["lot_only_match"]


async def test_recalls_by_lot_without_product_context_stays_exact_lot() -> None:
    # Nothing better than the lot is available, so the lot keeps its tier.
    es = _FakeEs([_reg_source()])
    assert _kinds(await _search(es).recalls_by_lot("MG30")) == ["exact_lot"]
    es = _FakeEs([_reg_source()])
    assert _kinds(await _search(es).recalls_by_lot("MG30", drug_names=["   "])) == ["exact_lot"]


async def test_recalls_by_lot_sorts_corroborated_first_then_dedupes_by_event() -> None:
    sibling = _reg_source(
        **{Reg.RECORD_ID: "sibling", Reg.EVENT_ID: "80525", Reg.DRUG_NAMES: ["valsartan"]}
    )
    named = _reg_source(
        **{
            Reg.RECORD_ID: "named",
            Reg.EVENT_ID: "80525",
            Reg.DRUG_NAMES: ["valsartan"],
            Reg.NDC9: ["435470367"],
        }
    )
    es = _FakeEs([sibling, named])
    hits = await _search(es).recalls_by_lot("ABC123", ndc9="435470367")
    # The dedupe runs after the sort, so the record that names the NDC survives.
    assert [hit.source[Reg.RECORD_ID] for hit in hits] == ["named"]
    assert _kinds(hits) == ["exact_lot"]


async def test_recalls_by_lot_returns_nothing_for_an_unusable_lot() -> None:
    es = _FakeEs([_reg_source()])
    assert await _search(es).recalls_by_lot("--") == []
    assert es.bodies == []


async def test_all_lots_sibling_when_only_the_openfda_ndc_list_carries_the_ndc() -> None:
    source = _reg_source(
        **{
            Reg.NDC9: ["713510026"],
            Reg.NDC_FROM_DESCRIPTION: ["713510023"],
            Reg.DRUG_NAMES: ["lidocaine hydrochloride"],
        }
    )
    es = _FakeEs([source])
    hits = await _search(es).recalls_covering_all_lots(ndc9="713510026", drug_names=[])
    assert _kinds(hits) == ["all_lots_sibling"]
    # The sibling leg still retrieves — the hit is classified, not dropped.
    should = es.bodies[0]["query"]["constant_score"]["filter"]["bool"]["should"]
    assert {"term": {Reg.NDC9: "713510026"}} in should
    assert {"term": {Reg.NDC_FROM_DESCRIPTION: "713510026"}} in should


async def test_an_ndc_written_in_the_recalls_own_text_still_names_the_product_without_any_manufacturer() -> None:
    es = _FakeEs([_reg_source(**{Reg.NDC_FROM_DESCRIPTION: ["713510026"], Reg.NDC9: []})])
    hits = await _search(es).recalls_covering_all_lots(ndc9="713510026", drug_names=[])
    assert _kinds(hits) == ["all_lots_product"]


async def test_an_all_lots_recall_names_the_product_when_the_manufacturers_share_a_distinctive_token() -> None:
    es = _FakeEs(
        [
            _reg_source(
                **{
                    Reg.NDC9: [],
                    Reg.NDC_FROM_DESCRIPTION: [],
                    Reg.MANUFACTURER: "Accord Healthcare, Inc.",
                }
            )
        ]
    )
    hits = await _search(es).recalls_covering_all_lots(
        ndc9=None,
        drug_names=["Levothyroxine Sodium 100 mcg"],
        manufacturer="Accord Healthcare Inc.",
    )
    assert _kinds(hits) == ["all_lots_product"]


async def test_an_all_lots_recall_of_another_firms_bulk_ingredient_is_only_a_sibling_for_an_accord_tablet() -> None:
    # fda-enf-D-761-2015: a Toronto repackager's levothyroxine API in bags and
    # drums. It shares the molecule's name with every levothyroxine tablet ever
    # made, and nothing else — an Accord bottle is not in its scope.
    attix = _reg_source(
        **{
            Reg.RECORD_ID: "fda-enf-D-761-2015",
            Reg.NDC9: [],
            Reg.NDC_FROM_DESCRIPTION: [],
            Reg.DRUG_NAMES: [],
            Reg.DRUG_NAMES_EXTRACTED: ["levothyroxine sodium"],
            Reg.MANUFACTURER: "Attix Pharmaceuticals",
            Reg.RECALLING_FIRM: "Attix Pharmaceuticals",
        }
    )
    hits = await _search(_FakeEs([attix])).recalls_covering_all_lots(
        ndc9="167290457",
        drug_names=["Levothyroxine Sodium 200 mcg"],
        manufacturer="Accord Healthcare",
    )
    assert _kinds(hits) == ["all_lots_sibling"]


async def test_an_all_lots_recall_matched_by_name_alone_is_never_the_product_when_the_label_names_no_manufacturer() -> None:
    # fda-enf-D-1016-2015: a compounding pharmacy's ibuprofen 10% cream. A plain
    # ibuprofen tablet with no NDC and no firm on the label has nothing to
    # corroborate with, so the name overlap alone cannot promote it.
    cream = _reg_source(
        **{
            Reg.RECORD_ID: "fda-enf-D-1016-2015",
            Reg.NDC9: [],
            Reg.NDC_FROM_DESCRIPTION: [],
            Reg.DRUG_NAMES: ["ibuprofen"],
            Reg.MANUFACTURER: "Health Innovations Pharmacy",
        }
    )
    hits = await _search(_FakeEs([cream])).recalls_covering_all_lots(
        ndc9=None, drug_names=["Ibuprofen 200 mg"], manufacturer=None
    )
    assert _kinds(hits) == ["all_lots_sibling"]
    # A blank firm on the label is no different from none at all.
    hits = await _search(_FakeEs([cream])).recalls_covering_all_lots(
        ndc9=None, drug_names=["Ibuprofen 200 mg"], manufacturer="   "
    )
    assert _kinds(hits) == ["all_lots_sibling"]


async def test_legal_and_generic_company_words_never_corroborate_a_manufacturer() -> None:
    zydus = _reg_source(
        **{
            Reg.NDC9: [],
            Reg.NDC_FROM_DESCRIPTION: [],
            Reg.DRUG_NAMES: ["levothyroxine sodium"],
            Reg.MANUFACTURER: "Zydus Pharmaceuticals (USA) Inc.",
        }
    )
    hits = await _search(_FakeEs([zydus])).recalls_covering_all_lots(
        ndc9=None,
        drug_names=["Levothyroxine Sodium 100 mcg"],
        manufacturer="Sun Pharmaceutical Industries Ltd",
    )
    assert _kinds(hits) == ["all_lots_sibling"]


async def test_the_recalling_firm_corroborates_when_the_manufacturer_field_is_empty() -> None:
    source = _reg_source(
        **{
            Reg.NDC9: [],
            Reg.NDC_FROM_DESCRIPTION: [],
            Reg.DRUG_NAMES: ["levothyroxine sodium"],
            Reg.RECALLING_FIRM: "Accord Healthcare Inc",
        }
    )
    hits = await _search(_FakeEs([source])).recalls_covering_all_lots(
        ndc9=None, drug_names=["Levothyroxine Sodium"], manufacturer="Accord Healthcare"
    )
    assert _kinds(hits) == ["all_lots_product"]


async def test_the_lot_lookup_still_corroborates_on_the_drug_name_alone() -> None:
    # The all-lots firm requirement must not leak into `recalls_by_lot`: an exact
    # lot string plus a name overlap is a much stronger signal on its own.
    es = _FakeEs([_reg_source(**{Reg.NDC9: [], Reg.NDC_FROM_DESCRIPTION: []})])
    hits = await _search(es).recalls_by_lot("D2402430", drug_names=["Levothyroxine Sodium"])
    assert _kinds(hits) == ["exact_lot"]


async def test_all_lots_dedupes_by_event_keeping_the_product_record() -> None:
    sibling = _reg_source(
        **{
            Reg.RECORD_ID: "sibling-320",
            Reg.EVENT_ID: "80525",
            Reg.DRUG_NAMES: ["valsartan"],
            Reg.NDC9: ["435470367"],
            Reg.NDC_FROM_DESCRIPTION: ["435470320"],
        }
    )
    named = _reg_source(
        **{
            Reg.RECORD_ID: "named-40",
            Reg.EVENT_ID: "80525",
            Reg.DRUG_NAMES: ["valsartan"],
            Reg.NDC9: ["435470367"],
            Reg.NDC_FROM_DESCRIPTION: ["435470367"],
        }
    )
    hits = await _search(_FakeEs([sibling, named])).recalls_covering_all_lots(
        ndc9="435470367", drug_names=[]
    )
    assert [hit.source[Reg.RECORD_ID] for hit in hits] == ["named-40"]
    assert _kinds(hits) == ["all_lots_product"]


async def test_all_lots_without_any_signal_never_searches() -> None:
    es = _FakeEs([_reg_source()])
    assert await _search(es).recalls_covering_all_lots(ndc9=None, drug_names=[]) == []
    assert es.bodies == []


# ------------------------------------------------------------- the pill ladder


def _pill_source(pill_id: str, imprint_norm: str) -> dict[str, Any]:
    return {Pill.PILL_ID: pill_id, Pill.IMPRINT_NORM: imprint_norm, Pill.SHAPE: "round"}


async def test_identify_pill_with_no_usable_attribute_short_circuits() -> None:
    es = _FakeEs([_pill_source("zz", "5892V")])
    match = await _search(es).identify_pill(imprint=None, shape=None, colors=[])
    assert match.hits == []
    assert match.rung == 0
    assert match.shape_relaxed is False
    assert es.bodies == [], "nothing survived normalisation, so nothing should be searched"


async def test_identify_pill_zero_hits_never_reports_a_relaxed_shape() -> None:
    # An imprint absent from Pillbox climbs every rung and finds nothing: that is
    # no evidence that the observed shape disagrees with a reference pill.
    es = _FakeEs([])
    match = await _search(es, shape_filter_mode="family").identify_pill(
        imprint="ZZQX99", shape="round", colors=["white"]
    )
    assert match.hits == []
    assert match.rung == 3
    assert match.shape_relaxed is False


async def test_identify_pill_boost_mode_never_reports_a_relaxed_shape() -> None:
    # No shape clause is ever installed in boost mode, so none can be dropped.
    es = _FakeEs([], [_pill_source("zz", "5892V")])
    match = await _search(es, shape_filter_mode="boost").identify_pill(
        imprint="5892;V", shape="round", colors=["white"]
    )
    assert match.rung == 2 and match.hits
    assert match.shape_relaxed is False


async def test_identify_pill_reports_a_relaxed_shape_only_with_candidates() -> None:
    es = _FakeEs([], [_pill_source("zz-pill-target", "5892V")])
    match = await _search(es, shape_filter_mode="family").identify_pill(
        imprint="5892;V", shape="round", colors=["pink"]
    )
    assert match.rung == 2
    assert match.hits[0].match_kind == "imprint_exact"
    assert match.shape_relaxed is True


# ---------------------------------------------------- the /knowledge/search API


def _client(es: _FakeEs, **settings: Any) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_router)
    app.dependency_overrides[get_knowledge_search] = lambda: _search(es, **settings)
    return TestClient(app)


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x", "size": 0},
        {"q": "x", "size": MAX_REGULATORY_SIZE + 1},
        {"q": "x", "index": "web", "size": MAX_WEB_SIZE + 1},
        {"q": "x", "rerank": "true", "size": MAX_RERANK_SIZE + 1},
    ],
)
def test_search_rejects_a_size_the_retriever_cannot_serve(params: dict[str, Any]) -> None:
    # Elasticsearch answers these with a validation error that the client layer
    # turns into a 502; a bad client input must not look like a gateway failure.
    es = _FakeEs()
    with _client(es) as client:
        assert client.get("/knowledge/search", params=params).status_code == 422
    assert es.bodies == []


def test_search_accepts_a_size_at_each_limit() -> None:
    with _client(_FakeEs()) as client:
        assert client.get(
            "/knowledge/search", params={"q": "x", "size": MAX_REGULATORY_SIZE}
        ).status_code == 200
        assert client.get(
            "/knowledge/search", params={"q": "x", "index": "web", "size": MAX_WEB_SIZE}
        ).status_code == 200
        assert client.get(
            "/knowledge/search",
            params={"q": "x", "rerank": "true", "size": MAX_RERANK_SIZE},
        ).status_code == 200


def test_web_search_rejects_regulatory_only_parameters() -> None:
    es = _FakeEs()
    with _client(es) as client:
        for params in (
            {"q": "recall", "index": "web", "drug": "levothyroxine"},
            {"q": "recall", "index": "web", "country": "Nigeria"},
            {"q": "recall", "index": "web", "max_age_days": 7},
            {"q": "recall", "index": "web", "rerank": "true"},
        ):
            response = client.get("/knowledge/search", params=params)
            assert response.status_code == 422, params
    assert es.bodies == []


def test_web_search_echoes_only_the_filters_it_applied() -> None:
    es = _FakeEs()
    with _client(es) as client:
        response = client.get(
            "/knowledge/search",
            params={"q": "recall", "index": "web", "source_tier": "regulator", "scan_id": "s-7"},
        )
    assert response.status_code == 200
    assert response.json()["filters"] == {"source_tiers": ["regulator"], "scan_id": "s-7"}
    clauses = es.bodies[0]["retriever"]["linear"]["filter"]
    assert {"terms": {Web.SOURCE_TIER: ["regulator"]}} in clauses
    assert {"term": {Web.SCAN_IDS: "s-7"}} in clauses


def test_regulatory_search_rejects_the_web_only_parameters() -> None:
    with _client(_FakeEs()) as client:
        response = client.get(
            "/knowledge/search", params={"q": "x", "source_tier": "regulator"}
        )
    assert response.status_code == 422


def test_debug_body_reflects_the_rerank_that_actually_ran() -> None:
    es = _FakeEs()
    with _client(es, research_rerank=True) as client:
        response = client.get("/knowledge/search", params={"q": "x", "debug": "true"})
    assert response.status_code == 200
    # No explicit ?rerank, so the setting decides — and the echoed body has to be
    # the one that was sent, not one rebuilt from the missing parameter.
    assert "text_similarity_reranker" in response.json()["body"]["retriever"]
    assert "text_similarity_reranker" in es.bodies[0]["retriever"]


# ------------------------------------------------ prior_scans demo exclusion


async def test_prior_scans_excludes_demo_scans_from_the_crowd_signal() -> None:
    class _PriorScansEs:
        def __init__(self) -> None:
            self.bodies: list[dict[str, Any]] = []

        async def search(self, *, index: str, **body: Any) -> dict[str, Any]:
            self.bodies.append(body)
            return {
                "hits": {"total": {"value": 0}},
                "aggregations": {"by_verdict": {"buckets": []}},
            }

    es = _PriorScansEs()
    await _search(es).prior_scans(lot="D2402430", ndc9="167290457")
    must_not = es.bodies[0]["query"]["bool"]["must_not"]
    assert {"term": {Scan.DEMO: True}} in must_not


async def test_prior_scans_still_excludes_the_scan_itself_alongside_demo() -> None:
    class _PriorScansEs:
        def __init__(self) -> None:
            self.bodies: list[dict[str, Any]] = []

        async def search(self, *, index: str, **body: Any) -> dict[str, Any]:
            self.bodies.append(body)
            return {
                "hits": {"total": {"value": 0}},
                "aggregations": {"by_verdict": {"buckets": []}},
            }

    es = _PriorScansEs()
    await _search(es).prior_scans(lot="D2402430", ndc9=None, exclude_scan_id="scan-7")
    must_not = es.bodies[0]["query"]["bool"]["must_not"]
    assert {"term": {Scan.DEMO: True}} in must_not
    assert {"term": {Scan.SCAN_ID: "scan-7"}} in must_not
