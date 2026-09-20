"""Live retrieval checks against throwaway indices on the real cluster.

Skipped unless PEEL_LIVE=1. Every index created here is named `peel-zz-test-*`
and is deleted in the fixture teardown, so a failed run cannot leave state behind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from backend.config import get_settings
from backend.knowledge import indices, normalize
from backend.knowledge.client import build_client
from backend.knowledge.fields import PILLS_INDEX, REGULATORY_INDEX, Pill, Reg
from backend.knowledge.search import KnowledgeSearch, SearchFilters

pytestmark = pytest.mark.live

# Semantic inference runs at index time and is the slow part of every call here.
_TIMEOUT_S = 180.0
_TWIN_BODY = (
    "Levothyroxine Sodium Tablets USP 100 mcg are being recalled because stability "
    "testing found subpotent content uniformity results below the specification limit."
)
_LOT_2016 = "ZZTESTLOT2016"


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()


def _reg(record_id: str, **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        Reg.RECORD_ID: record_id,
        Reg.SOURCE: "zz-test",
        Reg.SOURCE_ORG: "fda",
        Reg.DOC_TYPE: "recall",
        Reg.COUNTRY_OF_AUTHORITY: "United States",
        Reg.COUNTRIES: ["United States"],
        Reg.TITLE: "Levothyroxine Sodium Tablets recall",
        Reg.SUMMARY: _TWIN_BODY,
        Reg.BODY: _TWIN_BODY,
        Reg.BODY_SEMANTIC: _TWIN_BODY,
        Reg.REASON: "Subpotent drug",
        Reg.PRODUCT_DESCRIPTION: "Levothyroxine Sodium Tablets USP 100 mcg, 90-count bottle",
        Reg.DRUG_NAMES: ["levothyroxine sodium"],
        Reg.DRUG_NAMES_EXTRACTED: ["levothyroxine sodium"],
        Reg.MANUFACTURER: "ZZ Test Labs",
        Reg.DOSAGE_FORM: "tablet",
        Reg.SEVERITY: "high",
        Reg.SEVERITY_RANK: 3,
        Reg.STATUS: "ongoing",
        Reg.COVERS_ALL_LOTS: False,
        Reg.LOT_NUMBERS: [],
        Reg.HAS_SEMANTIC: True,
        Reg.DATE_PRECISION: "published",
        Reg.PUBLISHED_AT: _iso(5),
        Reg.RECENCY_DATE: _iso(5),
        Reg.URL: f"https://example.invalid/{record_id}",
    }
    doc.update(overrides)
    return doc


def _pill(pill_id: str, imprint_raw: str, shape: str, family: str, colors: list[str]) -> dict[str, Any]:
    forms = normalize.normalize_imprint(imprint_raw)
    assert forms is not None
    return {
        Pill.PILL_ID: pill_id,
        Pill.SOURCE: "zz-test",
        Pill.IMPRINT_RAW: forms.raw,
        Pill.IMPRINT_NORM: forms.norm,
        Pill.IMPRINT_SORTED: forms.sorted,
        Pill.IMPRINT_PARTS: forms.parts,
        Pill.IMPRINT_TEXT: forms.text,
        Pill.IMPRINT_LEN: len(forms.norm),
        Pill.SHAPE: shape,
        Pill.SHAPE_FAMILY: family,
        Pill.COLORS: colors,
        Pill.COLOR_COUNT: len(colors),
        Pill.SCORE: 1,
        Pill.SIZE_MM: 15.0,
        Pill.MEDICINE_NAME: f"ZZ Test {pill_id}",
        Pill.GENERIC_NAME: "zz testium",
        Pill.MARKETING_STATUS: "prescription",
        Pill.HAS_IMAGE: False,
    }


REG_DOCS = [
    _reg("zz-recent-twin"),
    _reg("zz-old-twin", **{Reg.RECENCY_DATE: "2018-03-01", Reg.PUBLISHED_AT: "2018-03-01"}),
    _reg(
        "zz-lot-2016",
        **{
            Reg.LOT_NUMBERS: [_LOT_2016],
            Reg.SEVERITY: "critical",
            Reg.SEVERITY_RANK: 4,
            Reg.RECENCY_DATE: "2016-05-10",
            Reg.PUBLISHED_AT: "2016-05-10",
        },
    ),
    _reg(
        "zz-fda-metformin",
        **{
            Reg.TITLE: "Metformin Hydrochloride Extended-Release Tablets recall",
            Reg.BODY: "Metformin hydrochloride extended-release tablets recalled for nitrosamine impurity above the acceptable intake limit.",
            Reg.BODY_SEMANTIC: "Metformin hydrochloride extended-release tablets recalled for nitrosamine impurity.",
            Reg.DRUG_NAMES: ["metformin hydrochloride"],
            Reg.DRUG_NAMES_EXTRACTED: ["metformin hydrochloride"],
        },
    ),
    _reg(
        "zz-fda-amoxicillin",
        **{
            Reg.TITLE: "Amoxicillin for Oral Suspension recall",
            Reg.BODY: "Amoxicillin for oral suspension recalled after dissolution testing failed at the twelve month station.",
            Reg.BODY_SEMANTIC: "Amoxicillin for oral suspension recalled after dissolution failure.",
            Reg.DRUG_NAMES: ["amoxicillin"],
            Reg.DRUG_NAMES_EXTRACTED: ["amoxicillin"],
            Reg.DOSAGE_FORM: "suspension",
        },
    ),
    _reg(
        "zz-all-lots-named",
        **{
            Reg.TITLE: "Valsartan tablets recall covering all lots",
            Reg.BODY: "Valsartan tablets 40 mg are recalled for a nitrosamine impurity; all lots are within scope.",
            Reg.BODY_SEMANTIC: "Valsartan tablets recalled for a nitrosamine impurity, all lots.",
            Reg.DRUG_NAMES: ["valsartan"],
            Reg.DRUG_NAMES_EXTRACTED: ["valsartan"],
            Reg.COVERS_ALL_LOTS: True,
            Reg.NDC9: ["435470367", "435470320", "435470160"],
            Reg.NDC_FROM_DESCRIPTION: ["435470367"],
            Reg.EVENT_ID: "zz-event-80525",
        },
    ),
    _reg(
        # Same recall event, a different strength: openFDA copies the whole
        # sibling NDC list onto it, so only ndc_from_description tells them apart.
        "zz-all-lots-sibling",
        **{
            Reg.TITLE: "Valsartan tablets 320 mg recall covering all lots",
            Reg.BODY: "Valsartan tablets 320 mg are recalled for a nitrosamine impurity; all lots are within scope.",
            Reg.BODY_SEMANTIC: "Valsartan tablets 320 mg recalled for a nitrosamine impurity, all lots.",
            Reg.DRUG_NAMES: ["valsartan"],
            Reg.DRUG_NAMES_EXTRACTED: ["valsartan"],
            Reg.COVERS_ALL_LOTS: True,
            Reg.NDC9: ["435470367", "435470320", "435470160"],
            Reg.NDC_FROM_DESCRIPTION: ["435470320"],
            Reg.EVENT_ID: "zz-event-80525",
        },
    ),
    _reg(
        "zz-who-falsified",
        **{
            Reg.SOURCE_ORG: "who",
            Reg.DOC_TYPE: "falsified_alert",
            Reg.COUNTRY_OF_AUTHORITY: "Switzerland",
            Reg.COUNTRIES: ["Nigeria"],
            Reg.TITLE: "Falsified levothyroxine tablets identified in West Africa",
            Reg.BODY: "Falsified levothyroxine sodium tablets with no active ingredient were identified in West Africa.",
            Reg.BODY_SEMANTIC: "Falsified levothyroxine sodium tablets identified in West Africa.",
        },
    ),
    _reg(
        "zz-who-substandard",
        **{
            Reg.SOURCE_ORG: "who",
            Reg.DOC_TYPE: "substandard_alert",
            Reg.COUNTRIES: ["Kenya"],
            Reg.TITLE: "Substandard levothyroxine tablets reported",
            Reg.BODY: "Substandard levothyroxine sodium tablets failing assay were reported to the surveillance system.",
            Reg.BODY_SEMANTIC: "Substandard levothyroxine sodium tablets failing assay.",
        },
    ),
    _reg(
        "zz-nafdac-alert",
        **{
            Reg.SOURCE_ORG: "nafdac",
            Reg.DOC_TYPE: "safety_alert",
            Reg.COUNTRY_OF_AUTHORITY: "Nigeria",
            Reg.COUNTRIES: ["Nigeria"],
            Reg.TITLE: "NAFDAC alert on levothyroxine tablets",
            Reg.BODY: "NAFDAC warns the public about levothyroxine sodium tablets circulating outside the regulated supply chain.",
            Reg.BODY_SEMANTIC: "NAFDAC alert about levothyroxine sodium tablets.",
        },
    ),
]

FDA_IDS = {"zz-recent-twin", "zz-old-twin", "zz-lot-2016", "zz-fda-metformin", "zz-fda-amoxicillin"}
NON_FDA_IDS = {"zz-who-falsified", "zz-who-substandard", "zz-nafdac-alert"}

PILL_DOCS = [
    _pill("zz-pill-target", "5892;V", "capsule", "elongated", ["pink"]),
    _pill("zz-pill-near", "5892", "capsule", "elongated", ["pink"]),
    _pill("zz-pill-sorted", "V;5892", "oval", "elongated", ["white"]),
    _pill("zz-pill-round-1", "TEVA;74", "round", "round", ["white"]),
    _pill("zz-pill-round-2", "M;321", "round", "round", ["yellow"]),
    _pill("zz-pill-diamond", "ZZ;9", "diamond", "diamond", ["blue"]),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def live():
    settings = get_settings()
    es = build_client(settings, request_timeout=_TIMEOUT_S)
    suffix = uuid4().hex[:8]
    reg_index = f"peel-zz-test-reg-{suffix}"
    pill_index = f"peel-zz-test-pills-{suffix}"
    try:
        await es.indices.create(index=reg_index, mappings=indices.mappings_for(REGULATORY_INDEX))
        await es.indices.create(index=pill_index, mappings=indices.mappings_for(PILLS_INDEX))
        await _bulk(es, reg_index, REG_DOCS, Reg.RECORD_ID)
        await _bulk(es, pill_index, PILL_DOCS, Pill.PILL_ID)
        yield KnowledgeSearch(
            es, settings, indices={"regulatory": reg_index, "pills": pill_index}
        )
    finally:
        await es.indices.delete(index=reg_index, ignore_unavailable=True)
        await es.indices.delete(index=pill_index, ignore_unavailable=True)
        await es.close()


async def _bulk(es, index: str, docs: list[dict[str, Any]], id_field: str) -> None:
    operations: list[dict[str, Any]] = []
    for doc in docs:
        operations.append({"index": {"_index": index, "_id": doc[id_field]}})
        operations.append(doc)
    response = await es.bulk(operations=operations, refresh="wait_for")
    assert not response["errors"], response


def _ids(hits) -> list[str]:
    return [hit.source[Reg.RECORD_ID] for hit in hits]


@pytest.mark.asyncio(loop_scope="module")
async def test_metadata_prefilter_excludes_without_losing_in_filter_docs(live) -> None:
    query = "levothyroxine sodium tablets quality defect recall"
    unfiltered = await live.search_regulatory(query, None, size=20)
    assert NON_FDA_IDS & set(_ids(unfiltered)), "the WHO/NAFDAC docs must be reachable at all"

    filtered = await live.search_regulatory(
        query, SearchFilters(source_orgs=["fda"]), size=20
    )
    returned = set(_ids(filtered))
    assert not returned & NON_FDA_IDS
    # Pre-filtering must narrow the candidate set, not silently drop in-filter docs.
    assert FDA_IDS <= returned


@pytest.mark.asyncio(loop_scope="module")
async def test_recent_doc_outranks_its_older_twin(live) -> None:
    hits = await live.search_regulatory(
        "levothyroxine sodium tablets subpotent content uniformity", None, size=20
    )
    order = _ids(hits)
    assert "zz-recent-twin" in order and "zz-old-twin" in order
    assert order.index("zz-recent-twin") < order.index("zz-old-twin")
    recent = next(h for h in hits if h.source[Reg.RECORD_ID] == "zz-recent-twin")
    old = next(h for h in hits if h.source[Reg.RECORD_ID] == "zz-old-twin")
    assert recent.age_days is not None and recent.freshness != "unknown"
    assert old.age_days is not None and old.age_days > recent.age_days
    assert Reg.RAW not in recent.source and Reg.BODY_SEMANTIC not in recent.source


@pytest.mark.asyncio(loop_scope="module")
async def test_exact_lot_lookup_finds_the_old_record(live) -> None:
    hits = await live.recalls_by_lot(_LOT_2016)
    assert [h.source[Reg.RECORD_ID] for h in hits] == ["zz-lot-2016"]
    # No product context was supplied, so nothing better than the lot is available.
    assert hits[0].match_kind == "exact_lot"
    assert hits[0].age_days is not None and hits[0].age_days > 3000


@pytest.mark.asyncio(loop_scope="module")
async def test_exact_lot_survives_a_differently_spelled_product(live) -> None:
    hits = await live.recalls_by_lot(_LOT_2016, drug_names=["Levothyroxine Sodium 100 mcg"])
    assert [h.match_kind for h in hits] == ["exact_lot"]


@pytest.mark.asyncio(loop_scope="module")
async def test_a_lot_that_collides_with_another_product_is_downgraded(live) -> None:
    # Same lot string, a different medicine: still returned, never the top tier.
    hits = await live.recalls_by_lot(_LOT_2016, drug_names=["amoxicillin"])
    assert [h.source[Reg.RECORD_ID] for h in hits] == ["zz-lot-2016"]
    assert hits[0].match_kind == "lot_only_match"


@pytest.mark.asyncio(loop_scope="module")
async def test_all_lots_prefers_the_recall_that_names_the_ndc_and_dedupes_the_event(live) -> None:
    hits = await live.recalls_covering_all_lots(ndc9="435470367", drug_names=[])
    # Both strengths carry the NDC in openFDA's sibling list and share an event.
    assert [h.source[Reg.RECORD_ID] for h in hits] == ["zz-all-lots-named"]
    assert hits[0].match_kind == "all_lots_product"


@pytest.mark.asyncio(loop_scope="module")
async def test_all_lots_classification_follows_the_text_not_the_sibling_list(live) -> None:
    hits = await live.recalls_covering_all_lots(ndc9="435470320", drug_names=[])
    # The other strength lists this NDC too, but only this record's text names it.
    assert {h.source[Reg.RECORD_ID]: h.match_kind for h in hits} == {
        "zz-all-lots-sibling": "all_lots_product"
    }


@pytest.mark.asyncio(loop_scope="module")
async def test_an_ndc_only_in_the_sibling_list_is_never_a_product_match(live) -> None:
    # 43547-0160 is a third strength: both records list it, neither names it.
    hits = await live.recalls_covering_all_lots(ndc9="435470160", drug_names=[])
    assert hits and all(h.match_kind == "all_lots_sibling" for h in hits)


@pytest.mark.asyncio(loop_scope="module")
async def test_pill_ladder_reports_no_relaxed_shape_when_it_found_nothing(live) -> None:
    match = await live.identify_pill(imprint="ZZQX99", shape="round", colors=["white"])
    assert match.hits == []
    assert match.rung == 3
    assert match.shape_relaxed is False


@pytest.mark.asyncio(loop_scope="module")
async def test_pill_lookup_without_any_usable_attribute_returns_nothing(live) -> None:
    match = await live.identify_pill(imprint=None, shape=None, colors=[])
    assert match.hits == []
    assert match.rung == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_pill_ladder_relaxes_a_wrong_shape(live) -> None:
    match = await live.identify_pill(
        imprint="5892;V", shape="round", colors=["pink"], score=None, size_mm=None
    )
    assert match.rung > 1
    assert match.shape_relaxed is True
    assert match.hits[0].source[Pill.PILL_ID] == "zz-pill-target"
    assert match.hits[0].match_kind == "imprint_exact"


@pytest.mark.asyncio(loop_scope="module")
async def test_pill_correct_shape_stays_on_rung_one(live) -> None:
    match = await live.identify_pill(
        imprint="5892;V", shape="capsule", colors=["pink"], score=None, size_mm=None
    )
    assert match.rung == 1
    assert match.shape_relaxed is False
    assert match.hits[0].source[Pill.PILL_ID] == "zz-pill-target"


@pytest.mark.asyncio(loop_scope="module")
async def test_pill_without_imprint_filters_on_shape_family(live) -> None:
    match = await live.identify_pill(imprint=None, shape="round", colors=None)
    families = {hit.source[Pill.SHAPE_FAMILY] for hit in match.hits}
    assert families == {"round"}
    assert match.rung == 1
