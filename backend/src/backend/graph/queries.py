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

from collections.abc import Sequence
from typing import Any

from elasticsearch import ApiError, AsyncElasticsearch, NotFoundError, TransportError

from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import (
    NDC_INDEX,
    REGULATORY_INDEX,
    REPORTS_INDEX,
    SCANS_INDEX,
    WEB_PAGES_INDEX,
    Ndc,
    Reg,
    Report,
    Scan,
    Web,
)

# The regulator's own body text is the one field a graph never needs and the one
# field licensing forbids re-publishing, so it is excluded everywhere.
REC_SRC: dict[str, Any] = {"excludes": [Reg.RAW, Reg.BODY_SEMANTIC, Reg.BODY]}
WEB_SRC: dict[str, Any] = {"excludes": [Web.RAW, Web.PAGE_SEMANTIC, Web.CONTENT]}
NDC_SRC: dict[str, Any] = {"excludes": [Ndc.RAW]}

# Another person's report is only ever counted, so only the join key is read:
# no report_id, no purchase date, no free-text label, no coordinates. This is an
# includes list rather than an excludes list precisely so a new field on the
# report mapping cannot become readable here by being added.
REPORT_SRC: dict[str, Any] = {"includes": [Report.SCAN_ID]}
# The same rule one hop on: the scan behind another person's report is read for
# the three things a crowd count needs and nothing else. `device_id` is here
# because a count of report rows is not a count of people — two taps of Submit,
# or two scans by one person, are one reporter — and because it is the only way
# to keep a heavy user's own older scans out of their own crowd count. It is
# grouped on inside `graph.expand` and never reaches a node, a label or a
# response; what leaves the backend is the size of the group, never its key.
CROWD_SCAN_SRC: dict[str, Any] = {
    "includes": [Scan.DEVICE_ID, Scan.RESEARCH_VERDICT, Scan.DEMO]
}

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
REPORTS_PER_ANCHOR = 200
CROWD_SCANS = 200

# The keyword sub-field `indices.TEXT_KW` puts on a free-text field.
KW = "kw"

# `purchase_location` is a plain object; these three leaves are keywords, and
# they are the only ones a graph query is ever allowed to name.
LOCATION_CITY = f"{Report.PURCHASE_LOCATION}.city"
LOCATION_REGION = f"{Report.PURCHASE_LOCATION}.region"
LOCATION_COUNTRY = f"{Report.PURCHASE_LOCATION}.country"

# `KW_TXT` fields are keywords with a `.txt` analysed sub-field. A salt-stripped
# key never equals the stored keyword ("levothyroxine" vs "levothyroxine
# sodium"), so every key match runs on `.txt` with operator `and`.
TXT = "txt"


def txt(field: str) -> str:
    return f"{field}.{TXT}"


def kw(field: str) -> str:
    return f"{field}.{KW}"


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


# --------------------------------------------------------------------------- reports


def _excluding_scans(scan_ids: Sequence[str]) -> list[dict[str, Any]]:
    """This device's own scans, kept out of every crowd count."""
    ids = [scan_id for scan_id in dict.fromkeys(scan_ids or ()) if scan_id]
    return [{"terms": {Report.SCAN_ID: ids}}] if ids else []


def build_reports_by_seller(
    variants: Sequence[str],
    *,
    exclude_scan_ids: Sequence[str] = (),
    size: int = REPORTS_PER_ANCHOR,
) -> dict[str, Any]:
    """Other people's reports naming this exact seller text.

    `seller` is analysed text with a `.kw` keyword sub-field, and only the
    keyword is matched: an analysed match would join "Riverside Pharmacy" to
    every other pharmacy in the index.
    """
    names = [name for name in dict.fromkeys(variants or ()) if name]
    query: dict[str, Any] = {
        "bool": {
            "filter": [{"terms": {kw(Report.SELLER): names}}],
            "must_not": _excluding_scans(exclude_scan_ids),
        }
    }
    return {
        "size": max(1, size),
        "track_total_hits": True,
        "_source": REPORT_SRC,
        "query": query,
    }


def build_reports_by_place(
    *,
    city: str | None = None,
    region: str | None = None,
    country: str | None = None,
    exclude_scan_ids: Sequence[str] = (),
    size: int = REPORTS_PER_ANCHOR,
) -> dict[str, Any]:
    """Other people's reports naming the same city/region/country. `label` is
    never a filter: it is free text one person typed, not a place."""
    filters = [
        {"term": {field: value}}
        for field, value in (
            (LOCATION_CITY, city),
            (LOCATION_REGION, region),
            (LOCATION_COUNTRY, country),
        )
        if value
    ]
    query: dict[str, Any] = {
        "bool": {"filter": filters, "must_not": _excluding_scans(exclude_scan_ids)}
    }
    return {
        "size": max(1, size),
        "track_total_hits": True,
        "_source": REPORT_SRC,
        "query": query,
    }


def build_crowd_scans(scan_ids: Sequence[str], *, size: int = CROWD_SCANS) -> dict[str, Any]:
    """One lookup for the scans another person's reports point at."""
    ids = [scan_id for scan_id in dict.fromkeys(scan_ids or ()) if scan_id]
    return {
        "size": max(1, min(len(ids) or 1, size)),
        "track_total_hits": False,
        "_source": CROWD_SCAN_SRC,
        "query": {"terms": {Scan.SCAN_ID: ids}},
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

    async def reports_by_seller(
        self, variants: Sequence[str], *, exclude_scan_ids: Sequence[str] = ()
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(
            REPORTS_INDEX,
            build_reports_by_seller(variants, exclude_scan_ids=exclude_scan_ids),
        )

    async def reports_by_place(
        self,
        *,
        city: str | None = None,
        region: str | None = None,
        country: str | None = None,
        exclude_scan_ids: Sequence[str] = (),
    ) -> tuple[list[dict[str, Any]], int]:
        return await self.search(
            REPORTS_INDEX,
            build_reports_by_place(
                city=city, region=region, country=country, exclude_scan_ids=exclude_scan_ids
            ),
        )

    async def crowd_scans(self, scan_ids: Sequence[str]) -> tuple[list[dict[str, Any]], int]:
        return await self.search(SCANS_INDEX, build_crowd_scans(scan_ids))
