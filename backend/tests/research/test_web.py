"""Firecrawl budget, SDK coercion and `peel-web-pages` write semantics.

Nothing here touches the network: the Firecrawl client is a stub and
Elasticsearch is a recording fake. Credits spent by this file: zero, on purpose.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from elastic_transport import ApiResponseMeta
from elasticsearch import AsyncElasticsearch, ConflictError, NotFoundError

from backend.config import Settings
from backend.knowledge import normalize
from backend.knowledge.fields import SOURCE_TIERS, WEB_PAGES_INDEX, Web
from backend.knowledge.indices import mapped_fields
from backend.research import web as web_module
from backend.research.queries import WebQuery
from backend.research.web import (
    BudgetExhausted,
    CreditBudget,
    FetchedPage,
    WebResearcher,
    coerce_page,
    coerce_pages,
    estimate_credits,
    is_blocked,
    reset_daily_credits,
    source_tier,
)

QUERY = WebQuery(text="levothyroxine recall", key="levothyroxine recall", tbs=None, purpose="t")


def _not_found() -> NotFoundError:
    meta = ApiResponseMeta(status=404, http_version="1.1", headers={}, duration=0.0, node=None)
    return NotFoundError("missing", meta=meta, body={})


class FakeEs:
    def __init__(self, *, existing: dict[str, Any] | None = None, hits: list[dict[str, Any]] | None = None):
        self.existing = existing
        self.hits = hits or []
        self.indexed: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.searches: list[dict[str, Any]] = []

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        if self.existing is None:
            raise _not_found()
        return {"_source": self.existing}

    async def index(self, **kwargs: Any) -> dict[str, Any]:
        self.indexed.append(kwargs)
        return {"result": "created"}

    async def update(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return {"result": "updated"}

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.searches.append(kwargs)
        return {"hits": {"hits": self.hits}}


class FakeFirecrawl:
    def __init__(self, data: Any = None, error: Exception | None = None):
        self.data = data
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, query: str, **kwargs: Any) -> Any:
        self.calls.append((query, kwargs))
        if self.error:
            raise self.error
        return self.data


def settings(**kwargs: Any) -> Settings:
    return Settings(openai_api_key="test", firecrawl_api_key="fc-test", **kwargs)


def page(url: str = "https://www.fda.gov/recall/abc", markdown: str = "content") -> FetchedPage:
    return FetchedPage(
        url=url,
        title="Recall notice",
        description="a recall",
        markdown=markdown,
        published_at=None,
        language="en",
        status_code=200,
    )


@pytest.fixture(autouse=True)
def _clean_daily_counter() -> Any:
    reset_daily_credits()
    yield
    reset_daily_credits()


# --------------------------------------------------------------------------- tiers


@pytest.mark.parametrize(
    ("domain", "tier"),
    [
        ("fda.gov", "regulator"),
        ("www.accessdata.fda.gov", "regulator"),
        ("medicines-recalls.sub.gov.uk", "regulator"),
        ("who.int", "regulator"),
        ("drugs.com", "reference"),
        ("www.reuters.com", "news"),
        ("bbc.co.uk", "news"),
        ("some-blog.example", "other"),
        ("", "other"),
    ],
)
def test_source_tier_matches_the_registrable_suffix(domain: str, tier: str) -> None:
    assert source_tier(domain) == tier


def test_every_declared_tier_is_a_known_tier() -> None:
    assert set(web_module.SOURCE_TIER.values()) <= set(SOURCE_TIERS)


# --------------------------------------------------------------------------- budget


def test_estimated_cost_is_the_search_base_plus_one_per_page() -> None:
    assert estimate_credits(3) == 5
    assert estimate_credits(0) == 2


def test_scan_budget_stops_before_it_overspends() -> None:
    budget = CreditBudget(10, daily_cap=1000)

    assert budget.take(5) == 5
    assert budget.take(5) == 5
    assert budget.used == 10
    with pytest.raises(BudgetExhausted, match="scan credit budget"):
        budget.take(1)


def test_daily_cap_applies_across_scans() -> None:
    CreditBudget(10, daily_cap=8).take(5)
    second = CreditBudget(10, daily_cap=8)

    with pytest.raises(BudgetExhausted, match="daily credit cap"):
        second.take(5)
    assert second.used == 0


def test_daily_counter_resets_when_the_utc_date_rolls_over(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_module, "_utc_today", lambda: date(2026, 9, 19))
    CreditBudget(10, daily_cap=6).take(6)

    monkeypatch.setattr(web_module, "_utc_today", lambda: date(2026, 9, 20))
    assert CreditBudget(10, daily_cap=6).take(6) == 6


# --------------------------------------------------------------------------- coercion


def test_object_shaped_sdk_result_is_coerced() -> None:
    item = SimpleNamespace(
        markdown="# Recall\nLot ABC123 was recalled.",
        metadata=SimpleNamespace(
            url="https://www.fda.gov/x",
            title="FDA recall",
            description="d",
            published_time="2026-09-01T00:00:00Z",
            language="en",
            status_code=200,
        ),
    )
    fetched = coerce_page(item)

    assert fetched is not None
    assert fetched.url == "https://www.fda.gov/x"
    assert fetched.title == "FDA recall"
    assert fetched.status_code == 200
    assert fetched.published_at == datetime(2026, 9, 1, tzinfo=UTC)


def test_dict_shaped_result_with_camel_case_metadata_is_coerced() -> None:
    fetched = coerce_page(
        {
            "markdown": "body",
            "metadata": {
                "sourceURL": "https://who.int/alert",
                "og_title": "WHO alert",
                "publishedTime": "2026-08-15",
                "statusCode": 200,
            },
        }
    )

    assert fetched is not None
    assert fetched.url == "https://who.int/alert"
    assert fetched.title == "WHO alert"
    assert fetched.published_at == datetime(2026, 8, 15, tzinfo=UTC)


def test_a_result_with_only_a_description_is_kept() -> None:
    fetched = coerce_page({"url": "https://example.com/a", "description": "short blurb"})

    assert fetched is not None
    assert fetched.markdown == "short blurb"


def test_results_without_a_url_or_content_are_dropped() -> None:
    assert coerce_page({"markdown": "body"}) is None
    assert coerce_page({"url": "https://example.com"}) is None


def test_web_and_news_results_are_merged_and_deduped() -> None:
    data = SimpleNamespace(
        web=[{"url": "https://a.example/1", "markdown": "a"}],
        news=[
            {"url": "https://a.example/1", "markdown": "a"},
            {"url": "https://b.example/2", "markdown": "b"},
        ],
    )

    assert [p.url for p in coerce_pages(data)] == ["https://a.example/1", "https://b.example/2"]


# --------------------------------------------------------------------------- index_page


async def test_new_page_is_written_with_revision_one_and_only_mapped_fields() -> None:
    es = FakeEs()
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    page_id = await researcher.index_page(
        page(markdown="Batch numbers: AB12345 and CD67890. NDC 16729-457-01. Recalled in Nigeria."),
        scan_id="scan-1",
        query=QUERY,
        credits=1,
        known_drug_names=["levothyroxine", "ibuprofen"],
    )

    doc = es.indexed[0]["document"]
    assert es.indexed[0]["id"] == page_id == normalize.url_hash("https://www.fda.gov/recall/abc")
    assert es.indexed[0]["refresh"] == "wait_for"
    assert set(doc) <= mapped_fields(WEB_PAGES_INDEX)
    assert doc[Web.REVISION] == 1
    assert doc[Web.FIRST_SEEN_AT] == doc[Web.LAST_CHANGED_AT] == doc[Web.FETCHED_AT]
    assert doc[Web.RECENCY_DATE] == doc[Web.LAST_CHANGED_AT]
    assert doc[Web.DATE_PRECISION] == "fetched"
    assert doc[Web.SOURCE_TIER] == "regulator"
    assert doc[Web.SOURCE_ORG] == "FDA"
    assert doc[Web.LOT_NUMBERS] == ["AB12345", "CD67890"]
    assert doc[Web.NDC9] == ["167290457"]
    assert doc[Web.COUNTRIES] == ["Nigeria"]
    assert doc[Web.IS_RECALL] is True
    assert doc[Web.QUERIES] == [QUERY.key]
    assert doc[Web.SCAN_IDS] == ["scan-1"]
    assert doc[Web.DRUG_NAMES] == []
    assert doc[Web.VIA] == "backend"


async def test_a_published_date_wins_over_the_fetch_time() -> None:
    es = FakeEs()
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())
    published = datetime(2024, 3, 2, tzinfo=UTC)

    await researcher.index_page(
        FetchedPage("https://who.int/a", "t", None, "body", published, None, 200),
        scan_id=None,
    )

    doc = es.indexed[0]["document"]
    assert doc[Web.DATE_PRECISION] == "published"
    assert doc[Web.RECENCY_DATE] == normalize.to_iso(published)


async def test_unchanged_content_only_moves_fetched_at() -> None:
    content = "identical body"
    existing = {
        Web.CONTENT_HASH: normalize.content_hash(content),
        Web.FIRST_SEEN_AT: "2026-01-01T00:00:00Z",
        Web.LAST_CHANGED_AT: "2026-02-01T00:00:00Z",
        Web.REVISION: 4,
        Web.QUERIES: ["older query"],
        Web.SCAN_IDS: ["scan-old"],
    }
    es = FakeEs(existing=existing)
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.index_page(page(markdown=content), scan_id="scan-2", query=QUERY)

    doc = es.indexed[0]["document"]
    assert doc[Web.REVISION] == 4
    assert doc[Web.FIRST_SEEN_AT] == "2026-01-01T00:00:00Z"
    assert doc[Web.LAST_CHANGED_AT] == "2026-02-01T00:00:00Z"
    assert doc[Web.FETCHED_AT] > doc[Web.LAST_CHANGED_AT]
    assert doc[Web.RECENCY_DATE] == "2026-02-01T00:00:00Z"
    assert doc[Web.QUERIES] == ["older query", QUERY.key]
    assert doc[Web.SCAN_IDS] == ["scan-old", "scan-2"]


async def test_changed_content_bumps_the_revision_and_keeps_first_seen() -> None:
    existing = {
        Web.CONTENT_HASH: normalize.content_hash("old body"),
        Web.FIRST_SEEN_AT: "2026-01-01T00:00:00Z",
        Web.LAST_CHANGED_AT: "2026-02-01T00:00:00Z",
        Web.REVISION: 4,
    }
    es = FakeEs(existing=existing)
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.index_page(page(markdown="a new body"), scan_id=None)

    doc = es.indexed[0]["document"]
    assert doc[Web.REVISION] == 5
    assert doc[Web.FIRST_SEEN_AT] == "2026-01-01T00:00:00Z"
    assert doc[Web.LAST_CHANGED_AT] == doc[Web.FETCHED_AT]


async def test_content_is_capped() -> None:
    es = FakeEs()
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.index_page(page(markdown="x" * 200_000), scan_id=None)

    assert len(es.indexed[0]["document"][Web.CONTENT]) == web_module.MAX_CONTENT_CHARS


# --------------------------------------------------------------------------- search_and_index


def _cache_hit(count: int = 2, hours_old: float = 1.0) -> list[dict[str, Any]]:
    fetched = normalize.to_iso(datetime.now(UTC) - timedelta(hours=hours_old))
    return [
        {
            "_id": f"page-{i}",
            "_source": {
                Web.PAGE_ID: f"page-{i}",
                Web.SOURCE_TIER: "regulator",
                Web.FETCHED_AT: fetched,
            },
        }
        for i in range(count)
    ]


async def test_a_cache_hit_spends_no_credits_and_never_calls_firecrawl() -> None:
    es = FakeEs(hits=_cache_hit())
    firecrawl = FakeFirecrawl()
    researcher = WebResearcher(es, settings(), firecrawl=firecrawl)
    budget = CreditBudget(10, daily_cap=100)

    outcome = await researcher.search_and_index(QUERY, scan_id="scan-1", budget=budget)

    assert outcome.cache_hit is True
    assert outcome.credits == 0 and budget.used == 0
    assert outcome.page_ids == ["page-0", "page-1"]
    assert firecrawl.calls == []
    # The cached pages learn about this scan.
    assert [u["id"] for u in es.updates] == ["page-0", "page-1"]


async def test_the_cache_lookup_uses_kwargs_the_real_client_accepts() -> None:
    es = FakeEs(hits=_cache_hit())
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.cached_page_ids("levothyroxine recall")

    accepted = set(inspect.signature(AsyncElasticsearch.search).parameters)
    assert set(es.searches[0]) <= accepted
    assert "_source" not in es.searches[0]


async def test_stale_cached_pages_do_not_count_as_a_hit() -> None:
    es = FakeEs(hits=_cache_hit(hours_old=200))
    firecrawl = FakeFirecrawl(SimpleNamespace(web=[], news=None))
    researcher = WebResearcher(es, settings(), firecrawl=firecrawl)

    outcome = await researcher.search_and_index(
        QUERY, scan_id="scan-1", budget=CreditBudget(10, daily_cap=100)
    )

    assert outcome.cache_hit is False
    assert len(firecrawl.calls) == 1


async def test_a_live_search_takes_credits_before_it_runs_and_indexes_every_page() -> None:
    data = SimpleNamespace(
        web=[
            {"url": "https://www.fda.gov/1", "markdown": "recall one"},
            {"url": "https://reuters.com/2", "markdown": "recall two"},
        ],
        news=None,
    )
    es = FakeEs()
    firecrawl = FakeFirecrawl(data)
    researcher = WebResearcher(es, settings(firecrawl_results_per_search=3), firecrawl=firecrawl)
    budget = CreditBudget(10, daily_cap=100)

    outcome = await researcher.search_and_index(
        WebQuery("q", "q", "qdr:y", "t"), scan_id="scan-1", budget=budget
    )

    assert outcome.credits == 5 and budget.used == 5
    assert len(outcome.page_ids) == 2
    assert len(es.indexed) == 2
    _, kwargs = firecrawl.calls[0]
    assert kwargs["limit"] == 3
    assert kwargs["scrape_options"] == {"formats": ["markdown"], "only_main_content": True}
    assert kwargs["tbs"] == "qdr:y"


async def test_an_exhausted_budget_returns_an_error_instead_of_searching() -> None:
    firecrawl = FakeFirecrawl()
    researcher = WebResearcher(FakeEs(), settings(), firecrawl=firecrawl)
    budget = CreditBudget(2, daily_cap=100)

    outcome = await researcher.search_and_index(QUERY, scan_id="scan-1", budget=budget)

    assert outcome.page_ids == []
    assert outcome.error is not None and "budget" in outcome.error
    assert firecrawl.calls == []


async def test_a_firecrawl_failure_still_costs_the_reserved_credits() -> None:
    researcher = WebResearcher(
        FakeEs(), settings(), firecrawl=FakeFirecrawl(error=RuntimeError("402"))
    )
    budget = CreditBudget(10, daily_cap=100)

    outcome = await researcher.search_and_index(QUERY, scan_id="scan-1", budget=budget)

    assert outcome.page_ids == []
    assert outcome.credits == budget.used
    assert "firecrawl search failed" in (outcome.error or "")


# --------------------------------------------------------------------------- blocklist


@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("https://www.facebook.com/groups/123/posts/456", True),
        ("https://m.facebook.com/x", True),
        ("https://youtube.com/watch?v=a", True),
        ("https://reddit.com/r/pharmacy", True),
        ("https://www.fda.gov/recall", False),
        ("https://facebook.com.example.org/x", False),
    ],
)
def test_social_domains_are_blocked_by_registrable_suffix(url: str, blocked: bool) -> None:
    assert is_blocked(url) is blocked


async def test_blocked_pages_are_never_indexed_or_counted() -> None:
    data = SimpleNamespace(
        web=[
            {"url": "https://www.facebook.com/groups/1/posts/2", "markdown": "my pills look fake"},
            {"url": "https://www.fda.gov/recall/abc", "markdown": "official recall"},
        ],
        news=None,
    )
    es = FakeEs()
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl(data))

    outcome = await researcher.search_and_index(
        QUERY, scan_id="scan-1", budget=CreditBudget(10, daily_cap=100)
    )

    assert len(outcome.page_ids) == 1
    assert outcome.skipped == ["https://www.facebook.com/groups/1/posts/2"]
    assert [call["document"][Web.DOMAIN] for call in es.indexed] == ["fda.gov"]


# --------------------------------------------------------------------------- pages_by_id


async def test_pages_by_id_returns_hits_for_this_scans_own_pages() -> None:
    es = FakeEs(
        hits=[
            {
                "_index": WEB_PAGES_INDEX,
                "_id": "page-1",
                "_source": {
                    Web.PAGE_ID: "page-1",
                    Web.URL: "https://www.fda.gov/x",
                    Web.RECENCY_DATE: normalize.to_iso(datetime.now(UTC)),
                },
            }
        ]
    )
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    hits = await researcher.pages_by_id(["page-1"])

    assert [hit.id for hit in hits] == ["page-1"]
    assert hits[0].match_kind == "fetched_for_this_scan"
    assert hits[0].freshness == "today"
    assert es.searches[0]["query"] == {"ids": {"values": ["page-1"]}}
    assert set(es.searches[0]) <= set(inspect.signature(AsyncElasticsearch.search).parameters)


async def test_pages_by_id_short_circuits_on_an_empty_list() -> None:
    es = FakeEs()
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    assert await researcher.pages_by_id([]) == []
    assert es.searches == []


# --------------------------------------------------------------------------- agent harvest


async def test_agent_pages_are_only_harvested_when_the_connector_is_configured() -> None:
    es = FakeEs()
    call = SimpleNamespace(
        tool_id=".firecrawl-search",
        results=[{"data": {"web": [{"url": "https://who.int/z", "markdown": "alert"}]}}],
    )

    off = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())
    assert await off.harvest_agent_pages([call], scan_id="scan-1") == []
    assert es.indexed == []

    on = WebResearcher(
        es,
        settings(agent_builder_firecrawl_connector_id="conn-1"),
        firecrawl=FakeFirecrawl(),
    )
    page_ids = await on.harvest_agent_pages([call], scan_id="scan-1")

    assert len(page_ids) == 1
    assert es.indexed[0]["document"][Web.VIA] == "agent_connector"


async def test_blocked_domains_are_skipped_on_the_agent_path_too() -> None:
    es = FakeEs()
    researcher = WebResearcher(
        es, settings(agent_builder_firecrawl_connector_id="conn-1"), firecrawl=FakeFirecrawl()
    )
    call = SimpleNamespace(
        tool_id=".firecrawl-search",
        results=[{"data": {"web": [{"url": "https://x.com/post/1", "markdown": "rumour"}]}}],
    )

    assert await researcher.harvest_agent_pages([call], scan_id="scan-1") == []
    assert es.indexed == []


async def test_non_firecrawl_tool_calls_are_ignored() -> None:
    es = FakeEs()
    researcher = WebResearcher(
        es, settings(agent_builder_firecrawl_connector_id="conn-1"), firecrawl=FakeFirecrawl()
    )
    call = SimpleNamespace(tool_id="peel.recalls_by_lot", results=[{"data": {"columns": []}}])

    assert await researcher.harvest_agent_pages([call], scan_id="scan-1") == []


# --------------------------------------------------------------------------- refunds


def test_a_refund_gives_the_reservation_back_to_both_counters() -> None:
    budget = CreditBudget(10, daily_cap=10)
    budget.take(5)

    budget.refund(5)

    assert budget.used == 0
    assert web_module.daily_credits_used() == 0
    # The whole plan is affordable again, which is the point of the refund.
    assert budget.take(10) == 10


def test_a_refund_never_drives_a_counter_negative() -> None:
    budget = CreditBudget(10, daily_cap=10)
    budget.take(2)

    budget.refund(50)

    assert budget.used == 0
    assert web_module.daily_credits_used() == 0


# --------------------------------------------------------------------------- write concurrency


def _conflict() -> ConflictError:
    meta = ApiResponseMeta(status=409, http_version="1.1", headers={}, duration=0.0, node=None)
    return ConflictError("version conflict", meta=meta, body={})


class VersionedEs(FakeEs):
    """An index that hands out version stamps and can lose a race on purpose."""

    def __init__(
        self,
        *,
        existing: dict[str, Any] | None = None,
        seq_no: int = 7,
        primary_term: int = 3,
        conflicts: int = 0,
        winner: dict[str, Any] | None = None,
    ):
        super().__init__(existing=existing)
        self.seq_no = seq_no
        self.primary_term = primary_term
        self.conflicts = conflicts
        self.winner = winner or {}
        self.attempts = 0

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        if self.existing is None:
            raise _not_found()
        return {
            "_source": self.existing,
            "_seq_no": self.seq_no,
            "_primary_term": self.primary_term,
        }

    async def index(self, **kwargs: Any) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self.conflicts:
            # Someone else wrote between our read and our write.
            self.existing = dict(self.existing or {}) | self.winner
            self.seq_no += 1
            raise _conflict()
        return await super().index(**kwargs)


async def test_a_new_page_is_written_with_create_semantics() -> None:
    es = VersionedEs()
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.index_page(page(), scan_id="scan-1", query=QUERY)

    assert es.indexed[0]["op_type"] == "create"
    assert "if_seq_no" not in es.indexed[0]


async def test_an_update_is_guarded_by_the_version_it_read() -> None:
    es = VersionedEs(existing={Web.CONTENT_HASH: "other", Web.REVISION: 2})
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.index_page(page(), scan_id="scan-1", query=QUERY)

    assert es.indexed[0]["if_seq_no"] == 7
    assert es.indexed[0]["if_primary_term"] == 3
    assert "op_type" not in es.indexed[0]


async def test_a_lost_race_is_retried_and_the_other_writer_is_merged_in() -> None:
    other = WebQuery(text="levothyroxine counterfeit", key="levothyroxine counterfeit", tbs=None, purpose="t")
    es = VersionedEs(
        existing={Web.CONTENT_HASH: normalize.content_hash("content"), Web.QUERIES: [], Web.SCAN_IDS: []},
        conflicts=1,
        winner={Web.QUERIES: [other.key], Web.SCAN_IDS: ["scan-other"]},
    )
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    page_id = await researcher.index_page(page(), scan_id="scan-1", query=QUERY)

    assert es.attempts == 2
    assert page_id == normalize.url_hash("https://www.fda.gov/recall/abc")
    doc = es.indexed[0]["document"]
    # Neither writer's query key is lost, so the next scan still hits the cache.
    assert doc[Web.QUERIES] == [other.key, QUERY.key]
    assert doc[Web.SCAN_IDS] == ["scan-other", "scan-1"]
    assert es.indexed[0]["if_seq_no"] == 8


async def test_the_retry_is_bounded_to_one_attempt() -> None:
    es = VersionedEs(existing={Web.CONTENT_HASH: "other"}, conflicts=5)
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    with pytest.raises(ConflictError):
        await researcher.index_page(page(), scan_id="scan-1", query=QUERY)

    assert es.attempts == 2
    assert es.indexed == []


async def test_an_unreadable_document_is_still_written_on_the_retry() -> None:
    class BlindEs(VersionedEs):
        async def get(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("get timed out")

    es = BlindEs(conflicts=1)
    researcher = WebResearcher(es, settings(), firecrawl=FakeFirecrawl())

    await researcher.index_page(page(), scan_id="scan-1", query=QUERY)

    # The first write took create semantics and lost; the retry cannot read the
    # winner, so it writes rather than dropping a page we already paid for.
    assert es.attempts == 2
    assert "op_type" not in es.indexed[0]
