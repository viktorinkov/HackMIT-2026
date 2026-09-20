from __future__ import annotations

from typing import Any

import pytest
from elastic_transport import ApiResponseMeta, ConnectionTimeout
from elasticsearch import ApiError, NotFoundError

from backend.graph import queries
from backend.graph.queries import GraphQueries
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import REGULATORY_INDEX, Ndc, Reg, Report, Scan, Web


def _meta(status: int) -> ApiResponseMeta:
    return ApiResponseMeta(
        status=status, http_version="1.1", headers={}, duration=0.0, node=None
    )


class FakeEs:
    """Records every call; each method returns the queued response or raises."""

    def __init__(self, **responses: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses

    async def _run(self, name: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((name, kwargs))
        value = self.responses.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    async def search(self, **kwargs: Any) -> Any:
        return await self._run("search", kwargs)

    async def get(self, **kwargs: Any) -> Any:
        return await self._run("get", kwargs)

    def call(self, name: str) -> dict[str, Any]:
        return next(kwargs for called, kwargs in self.calls if called == name)


def response(*sources: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    hits = [{"_id": s.get(Reg.RECORD_ID, "x"), "_source": s, "_score": 1.0} for s in sources]
    return {"hits": {"hits": hits, "total": {"value": total if total is not None else len(hits)}}}


def test_med_query_ors_both_drug_name_fields_with_operator_and() -> None:
    body = queries.build_records_by_drug("levothyroxine")
    should = body["query"]["bool"]["should"]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    assert [next(iter(clause["match"])) for clause in should] == [
        f"{Reg.DRUG_NAMES}.txt",
        f"{Reg.DRUG_NAMES_EXTRACTED}.txt",
    ]
    assert all(
        next(iter(clause["match"].values()))["operator"] == "and" for clause in should
    )


def test_manufacturer_query_ors_manufacturer_and_recalling_firm() -> None:
    body = queries.build_records_by_manufacturer("accord healthcare")
    fields = [next(iter(clause["match"])) for clause in body["query"]["bool"]["should"]]
    assert fields == [f"{Reg.MANUFACTURER}.txt", f"{Reg.RECALLING_FIRM}.txt"]


def test_every_record_body_excludes_the_regulators_body_text() -> None:
    bodies = [
        queries.build_records_by_drug("ibuprofen"),
        queries.build_records_by_manufacturer("zydus"),
        queries.build_records_by_source_org("FDA"),
        queries.build_records_by_country("Cameroon"),
        queries.build_records_by_event("99584"),
    ]
    for body in bodies:
        assert body["_source"] == {
            "excludes": [Reg.RAW, Reg.BODY_SEMANTIC, Reg.BODY]
        }
        assert body["track_total_hits"] is True


def test_record_bodies_sort_by_severity_then_recency_then_id() -> None:
    body = queries.build_records_by_drug("ibuprofen")
    assert body["sort"] == [
        {Reg.SEVERITY_RANK: "desc"},
        {Reg.RECENCY_DATE: "desc"},
        {Reg.RECORD_ID: "asc"},
    ]


def test_no_request_body_ever_carries_an_aggregation() -> None:
    bodies = [
        queries.build_records_by_drug("ibuprofen"),
        queries.build_records_by_manufacturer("zydus"),
        queries.build_records_by_source_org("FDA"),
        queries.build_records_by_country("Cameroon"),
        queries.build_records_by_event("99584", exclude_record_id="fda-enf-1"),
        queries.build_web_pages_by_lot("D24005"),
        queries.build_ndc_siblings("Accord Healthcare", "levothyroxine sodium"),
    ]
    assert not any("aggs" in body or "aggregations" in body for body in bodies)


def test_limit_is_clamped_to_one_through_twenty_five() -> None:
    assert queries.build_records_by_drug("x", limit=0)["size"] == 1
    assert queries.build_records_by_drug("x", limit=900)["size"] == 25
    assert queries.clamp(None) == queries.DEFAULT_LIMIT


def test_event_siblings_exclude_the_record_being_expanded() -> None:
    body = queries.build_records_by_event("99584", exclude_record_id="fda-enf-D-0785-2026")
    assert body["query"]["bool"]["filter"] == [{"term": {Reg.EVENT_ID: "99584"}}]
    assert body["query"]["bool"]["must_not"] == [
        {"term": {Reg.RECORD_ID: "fda-enf-D-0785-2026"}}
    ]


def test_web_pages_by_lot_terms_the_lot_field_and_drops_the_page_body() -> None:
    body = queries.build_web_pages_by_lot("D24005")
    assert body["query"] == {"term": {Web.LOT_NUMBERS: "D24005"}}
    assert body["_source"] == {"excludes": [Web.RAW, Web.PAGE_SEMANTIC, Web.CONTENT]}


def test_ndc_siblings_filter_on_labeler_and_generic_name() -> None:
    body = queries.build_ndc_siblings("Accord Healthcare Inc.", "levothyroxine sodium")
    assert body["query"]["bool"]["filter"] == [
        {"term": {Ndc.LABELER_NAME: "Accord Healthcare Inc."}},
        {"term": {Ndc.GENERIC_NAME: "levothyroxine sodium"}},
    ]


async def test_the_source_key_is_sent_as_the_clients_source_keyword() -> None:
    es = FakeEs(search=response({Reg.RECORD_ID: "fda-enf-1"}))
    await GraphQueries(es).records_by_drug("levothyroxine")
    call = es.call("search")
    assert call["index"] == REGULATORY_INDEX
    assert "_source" not in call and call["source"] == queries.REC_SRC


async def test_totals_come_from_hits_total_not_from_the_page_length() -> None:
    es = FakeEs(search=response({Reg.RECORD_ID: "fda-enf-1"}, total=17963))
    hits, total = await GraphQueries(es).records_by_source_org("FDA")
    assert len(hits) == 1 and total == 17963


async def test_transport_errors_become_503() -> None:
    es = FakeEs(search=ConnectionTimeout("timed out"))
    with pytest.raises(KnowledgeError) as excinfo:
        await GraphQueries(es).records_by_drug("levothyroxine")
    assert excinfo.value.status_code == 503
    assert "unreachable" in excinfo.value.message


async def test_api_errors_become_502() -> None:
    es = FakeEs(search=ApiError("boom", meta=_meta(400), body={}))
    with pytest.raises(KnowledgeError) as excinfo:
        await GraphQueries(es).records_by_drug("levothyroxine")
    assert excinfo.value.status_code == 502


async def test_a_missing_record_becomes_404() -> None:
    es = FakeEs(get=NotFoundError("missing", meta=_meta(404), body={}))
    with pytest.raises(KnowledgeError) as excinfo:
        await GraphQueries(es).record("fda-enf-nope")
    assert excinfo.value.status_code == 404


async def test_a_record_fetch_excludes_the_body_fields() -> None:
    es = FakeEs(get={"_source": {Reg.RECORD_ID: "fda-enf-1", Reg.TITLE: "Recall"}})
    source = await GraphQueries(es).record("fda-enf-1")
    assert source[Reg.TITLE] == "Recall"
    assert es.call("get")["source_excludes"] == [Reg.RAW, Reg.BODY_SEMANTIC, Reg.BODY]


# --------------------------------------------------------------------------- reports


def test_a_seller_lookup_matches_the_keyword_and_excludes_this_devices_scans() -> None:
    body = queries.build_reports_by_seller(
        ["Riverside Demo Pharmacy", "Riverside Demo Pharmacy", ""],
        exclude_scan_ids=["scan-1", "scan-1"],
    )
    bool_query = body["query"]["bool"]
    # The `.kw` sub-field, never the analysed one: an analysed match would join
    # "Riverside Pharmacy" to every other pharmacy in the index.
    assert bool_query["filter"] == [
        {"terms": {"seller.kw": ["Riverside Demo Pharmacy"]}}
    ]
    assert bool_query["must_not"] == [{"terms": {Report.SCAN_ID: ["scan-1"]}}]
    # Only the join key is ever read back.
    assert body["_source"] == {"includes": [Report.SCAN_ID]}


def test_a_place_lookup_only_ever_filters_on_the_structured_fields() -> None:
    body = queries.build_reports_by_place(city="Douala", country="Cameroon")
    assert body["query"]["bool"]["filter"] == [
        {"term": {"purchase_location.city": "Douala"}},
        {"term": {"purchase_location.country": "Cameroon"}},
    ]
    assert body["query"]["bool"]["must_not"] == []
    rendered = str(body)
    assert "label" not in rendered and "coordinates" not in rendered


def test_the_crowd_scan_join_reads_three_fields_and_nothing_else() -> None:
    body = queries.build_crowd_scans(["other-1", "other-2", "other-1"])
    assert body["query"] == {"terms": {Scan.SCAN_ID: ["other-1", "other-2"]}}
    # `device_id` groups rows into people inside `graph.expand` and never
    # leaves it; the medicine name is not read at all, because a breakdown of
    # other people's medicines is not a count of reports.
    assert body["_source"] == {"includes": ["device_id", "research.verdict", "demo"]}
    assert "norm" not in str(body["_source"])
    assert body["size"] == 2
