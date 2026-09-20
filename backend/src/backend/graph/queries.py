"""Elasticsearch request bodies for Atlas expansion and search.

Two halves, deliberately separate:

* pure `build_*` functions that return a request body and touch no client, so a
  test can assert on the body without a fake cluster;
* `GraphQueries`, a thin wrapper that runs those bodies and maps the
  Elasticsearch exception families onto `KnowledgeError` the way
  `KnowledgeSearch._run` already does (`ApiError` → 502, `TransportError` →
  503, `NotFoundError` → 404).

Two rules hold everywhere in this module:

* field names come from `knowledge.fields`, never from a string literal, so a
  rename still happens in one place;
* there are no aggregations. Live aggregations were cut, so every total on
  screen comes from `hits.total` with `track_total_hits: True`.
"""

from __future__ import annotations

from typing import Any

from elasticsearch import ApiError, AsyncElasticsearch, NotFoundError, TransportError

from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import (
    NDC_INDEX,
    REGULATORY_INDEX,
    WEB_PAGES_INDEX,
    Ndc,
    Reg,
    Web,
)

# The regulator's own body text is the one field a graph never needs and the one
# field licensing forbids re-publishing, so it is excluded everywhere.
REC_SRC: dict[str, Any] = {"excludes": [Reg.RAW, Reg.BODY_SEMANTIC, Reg.BODY]}
WEB_SRC: dict[str, Any] = {"excludes": [Web.RAW, Web.PAGE_SEMANTIC, Web.CONTENT]}
NDC_SRC: dict[str, Any] = {"excludes": [Ndc.RAW]}

# Severity first, then recency, then the id: a total order, so two identical
# requests return the same page and a cluster count means the same thing twice.
SORT: list[Any] = [
    {Reg.SEVERITY_RANK: "desc"},
    {Reg.RECENCY_DATE: "desc"},
    {Reg.RECORD_ID: "asc"},
]
RECENT_SORT: list[Any] = [{Reg.RECENCY_DATE: "desc"}, {Reg.RECORD_ID: "asc"}]

MIN_LIMIT = 1
MAX_LIMIT = 25
DEFAULT_LIMIT = 12

# Fixed sub-caps that are not the caller's `limit`.
EVENT_SIBLINGS = 12
NDC_SIBLINGS = 12
WEB_PAGES_PER_LOT = 10
LATEST_PER_REGULATOR = 6

# `KW_TXT` fields are keywords with a `.txt` analysed sub-field. A salt-stripped
# key never equals the stored keyword ("levothyroxine" vs "levothyroxine
# sodium"), so every key match runs on `.txt` with operator `and`.
TXT = "txt"


def txt(field: str) -> str:
    return f"{field}.{TXT}"


def clamp(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(MIN_LIMIT, min(int(limit), MAX_LIMIT))


def _match_any(fields: tuple[str, ...], value: str) -> dict[str, Any]:
    """OR over analysed sub-fields, each requiring every token of the key.

    `drug_names` is sparse (3,277 of 17,963 FDA records) and Health Canada, MHRA
    and NAFDAC only ever fill `drug_names_extracted`, so a single-field match
    silently loses three regulators.
    """
    return {
        "bool": {
            "should": [
                {"match": {txt(field): {"query": value, "operator": "and"}}}
                for field in fields
            ],
            "minimum_should_match": 1,
        }
    }


def build_records_by_drug(key: str, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    return {
        "size": clamp(limit),
        "track_total_hits": True,
        "_source": REC_SRC,
        "query": _match_any((Reg.DRUG_NAMES, Reg.DRUG_NAMES_EXTRACTED), key),
        "sort": SORT,
    }


def build_records_by_manufacturer(key: str, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    return {
        "size": clamp(limit),
        "track_total_hits": True,
        "_source": REC_SRC,
        "query": _match_any((Reg.MANUFACTURER, Reg.RECALLING_FIRM), key),
        "sort": SORT,
    }


def build_records_by_source_org(org: str, *, limit: int = LATEST_PER_REGULATOR) -> dict[str, Any]:
    """A regulator's shelf: the newest few, plus the total for the cluster."""
    return {
        "size": clamp(limit),
        "track_total_hits": True,
        "_source": REC_SRC,
        "query": {"term": {Reg.SOURCE_ORG: org}},
        "sort": RECENT_SORT,
    }


def build_records_by_country(country: str, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    return {
        "size": clamp(limit),
        "track_total_hits": True,
        "_source": REC_SRC,
        "query": {"term": {Reg.COUNTRIES: country}},
        "sort": SORT,
    }


def build_records_by_event(
    event_id: str, *, exclude_record_id: str | None = None, limit: int = EVENT_SIBLINGS
) -> dict[str, Any]:
    """The other strengths of one recall event, which openFDA indexes separately."""
    bool_query: dict[str, Any] = {"filter": [{"term": {Reg.EVENT_ID: event_id}}]}
    if exclude_record_id:
        bool_query["must_not"] = [{"term": {Reg.RECORD_ID: exclude_record_id}}]
    return {
        "size": clamp(limit),
        "track_total_hits": True,
        "_source": REC_SRC,
        "query": {"bool": bool_query},
        "sort": SORT,
    }


def build_web_pages_by_lot(lot: str, *, size: int = WEB_PAGES_PER_LOT) -> dict[str, Any]:
    """Pages that print this lot. A fact about the page, never about the product."""
    return {
        "size": max(1, size),
        "track_total_hits": True,
        "_source": WEB_SRC,
        "query": {"term": {Web.LOT_NUMBERS: lot}},
    }


def build_ndc_siblings(
    labeler_name: str, generic_name: str, *, size: int = NDC_SIBLINGS
) -> dict[str, Any]:
    """The other strengths one labeler lists under the same generic name."""
    return {
        "size": max(1, size),
        "track_total_hits": True,
        "_source": NDC_SRC,
        "query": {
            "bool": {
                "filter": [
                    {"term": {Ndc.LABELER_NAME: labeler_name}},
                    {"term": {Ndc.GENERIC_NAME: generic_name}},
                ]
            }
        },
    }


def _call_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    """`_source` is a body key but a `source` keyword on the client."""
    kwargs = dict(body)
    source = kwargs.pop("_source", None)
    if source is not None:
        kwargs["source"] = source
    return kwargs


def hits_of(response: dict[str, Any]) -> list[dict[str, Any]]:
    return list((response.get("hits") or {}).get("hits") or [])


def total_of(response: dict[str, Any]) -> int:
    total = (response.get("hits") or {}).get("total")
    if isinstance(total, dict):
        return int(total.get("value") or 0)
    if isinstance(total, (int, float)):
        return int(total)
    return len(hits_of(response))


class GraphQueries:
    """Runs the bodies above and keeps the API's status codes honest."""

    def __init__(self, es: AsyncElasticsearch) -> None:
        self._es = es

    async def search(self, index: str, body: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        try:
            response = await self._es.search(index=index, **_call_kwargs(body))
        except NotFoundError as exc:
            raise KnowledgeError(f"{index} not found", status_code=404) from exc
        except ApiError as exc:
            raise KnowledgeError(f"search on {index} failed: {exc.message}") from exc
        except TransportError as exc:
            raise KnowledgeError(
                f"search on {index} failed: Elasticsearch is unreachable "
                f"({type(exc).__name__})",
                status_code=503,
            ) from exc
        return hits_of(response), total_of(response)

    async def get(
        self, index: str, doc_id: str, *, source_excludes: list[str] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._es.get(
                index=index, id=doc_id, source_excludes=source_excludes
            )
        except NotFoundError as exc:
            raise KnowledgeError(f"{doc_id} not found", status_code=404) from exc
        except ApiError as exc:
            raise KnowledgeError(f"get on {index} failed: {exc.message}") from exc
        except TransportError as exc:
            raise KnowledgeError(
                f"get on {index} failed: Elasticsearch is unreachable "
                f"({type(exc).__name__})",
                status_code=503,
            ) from exc
        return dict(response.get("_source") or {})

    # -- named calls, so expansion never names an index itself ---------------

    async def record(self, record_id: str) -> dict[str, Any]:
        return await self.get(
            REGULATORY_INDEX, record_id, source_excludes=list(REC_SRC["excludes"])
        )

    async def records_by_drug(
        self, key: str, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(REGULATORY_INDEX, build_records_by_drug(key, limit=limit))

    async def records_by_manufacturer(
        self, key: str, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(
            REGULATORY_INDEX, build_records_by_manufacturer(key, limit=limit)
        )

    async def records_by_source_org(
        self, org: str, *, limit: int = LATEST_PER_REGULATOR
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(
            REGULATORY_INDEX, build_records_by_source_org(org, limit=limit)
        )

    async def records_by_country(
        self, country: str, *, limit: int = DEFAULT_LIMIT
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(
            REGULATORY_INDEX, build_records_by_country(country, limit=limit)
        )

    async def records_by_event(
        self, event_id: str, *, exclude_record_id: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(
            REGULATORY_INDEX,
            build_records_by_event(event_id, exclude_record_id=exclude_record_id),
        )

    async def web_pages_by_lot(self, lot: str) -> tuple[list[dict[str, Any]], int]:
        return await self.search(WEB_PAGES_INDEX, build_web_pages_by_lot(lot))

    async def ndc_siblings(
        self, labeler_name: str, generic_name: str
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(NDC_INDEX, build_ndc_siblings(labeler_name, generic_name))
