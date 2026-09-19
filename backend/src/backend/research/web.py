"""Live web research: Firecrawl search -> `peel-web-pages`.

Everything this module fetches lands in Elasticsearch, so the next scan of the
same product finds it without spending a credit. Two rules shape the code:

* **Credits are the scarce resource.** A `CreditBudget` is taken *before* the
  call, never reconciled after, and a module-wide daily counter backs up the
  per-scan cap so a retry loop in dev cannot drain the plan.
* **The SDK is not trusted.** firecrawl-py returns pydantic objects whose
  attribute names drift between versions, and metadata keys arrive in both
  snake_case and camelCase, so every field is read through `_attr`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError

from backend.config import Settings
from backend.knowledge import normalize
from backend.knowledge.fields import WEB_PAGES_INDEX, Web
from backend.knowledge.search import Hit
from backend.research.queries import EXCLUDED_DOMAINS, WebQuery

MAX_CONTENT_CHARS = 100_000
MAX_SEMANTIC_CHARS = 6_000
MAX_CODES = 50
MAX_COUNTRIES = 20
MAX_ACCUMULATED = 50
# Two fresh pages is enough to answer from cache; one is usually a stub.
CACHE_MIN_PAGES = 2
CACHE_CANDIDATES = 25
SEARCH_TIMEOUT_MS = 45_000
# Firecrawl v2 /search: one base credit-pair for the search, one per scraped page.
SEARCH_BASE_CREDITS = 2

_REGULATOR = (
    "fda.gov",
    "accessdata.fda.gov",
    "who.int",
    "nafdac.gov.ng",
    "gov.uk",
    "mhra.gov.uk",
    "recalls-rappels.canada.ca",
    "canada.ca",
    "healthycanadians.gc.ca",
    "ema.europa.eu",
    "cdsco.gov.in",
    "tga.gov.au",
    "dailymed.nlm.nih.gov",
    "nih.gov",
    "nlm.nih.gov",
    "cdc.gov",
    "europa.eu",
    "sahpra.org.za",
    "pmda.go.jp",
)
_REFERENCE = (
    "drugs.com",
    "rxlist.com",
    "medlineplus.gov",
    "fda.report",
    "webmd.com",
    "pillintrip.com",
    "medscape.com",
    "mims.com",
    "healthline.com",
)
_NEWS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "fiercepharma.com",
    "raps.org",
    "pharmaceutical-technology.com",
    "statnews.com",
    "npr.org",
    "theguardian.com",
    "cnn.com",
    "nytimes.com",
    "punchng.com",
    "premiumtimesng.com",
)

SOURCE_TIER: dict[str, str] = {
    **{domain: "regulator" for domain in _REGULATOR},
    **{domain: "reference" for domain in _REFERENCE},
    **{domain: "news" for domain in _NEWS},
}

SOURCE_ORG: dict[str, str] = {
    "fda.gov": "FDA",
    "accessdata.fda.gov": "FDA",
    "who.int": "WHO",
    "nafdac.gov.ng": "NAFDAC",
    "gov.uk": "MHRA",
    "mhra.gov.uk": "MHRA",
    "recalls-rappels.canada.ca": "Health Canada",
    "canada.ca": "Health Canada",
    "ema.europa.eu": "EMA",
    "dailymed.nlm.nih.gov": "NLM",
}

# Substring rules over the page text. Deliberately blunt: these drive filters
# and a "flags" facet, never a verdict on their own.
_FLAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recall", ("recall", "recalled", "withdrawal of batch", "market withdrawal")),
    ("counterfeit", ("counterfeit", "fake medicine", "spurious")),
    ("falsified", ("falsified",)),
    ("substandard", ("substandard", "out of specification", "not of standard quality")),
    ("contamination", ("contaminat", "adulterat", "impurit")),
    ("warning_letter", ("warning letter", "import alert")),
    ("shortage", ("drug shortage", "supply shortage")),
)
_ALERT_FLAGS = {"counterfeit", "falsified", "substandard", "contamination", "warning_letter"}

_daily_used = 0
_daily_date: date | None = None


class BudgetExhausted(Exception):
    """The per-scan or the process-wide daily Firecrawl credit cap is spent."""


def _utc_today() -> date:
    return datetime.now(UTC).date()


def reset_daily_credits() -> None:
    """Test hook; production resets itself when the UTC date changes."""
    global _daily_used, _daily_date
    _daily_used, _daily_date = 0, None


def daily_credits_used() -> int:
    _roll_over()
    return _daily_used


def _roll_over() -> None:
    global _daily_used, _daily_date
    today = _utc_today()
    if _daily_date != today:
        _daily_date, _daily_used = today, 0


def estimate_credits(results: int) -> int:
    """Cost of one Firecrawl search that scrapes `results` pages."""
    return SEARCH_BASE_CREDITS + max(0, int(results))


class CreditBudget:
    def __init__(self, per_scan: int, *, daily_cap: int) -> None:
        self._per_scan = max(0, int(per_scan))
        self._daily_cap = max(0, int(daily_cap))
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self._per_scan - self._used)

    def take(self, amount: int) -> int:
        """Reserve credits before the call, so a failed call still costs us."""
        global _daily_used
        _roll_over()
        cost = max(0, int(amount))
        if self._used + cost > self._per_scan:
            raise BudgetExhausted(
                f"scan credit budget exhausted: {self._used}+{cost} > {self._per_scan}"
            )
        if _daily_used + cost > self._daily_cap:
            raise BudgetExhausted(
                f"daily credit cap reached: {_daily_used}+{cost} > {self._daily_cap}"
            )
        self._used += cost
        _daily_used += cost
        return cost


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str | None
    description: str | None
    markdown: str
    published_at: datetime | None
    language: str | None
    status_code: int | None


@dataclass
class WebOutcome:
    page_ids: list[str] = field(default_factory=list)
    cache_hit: bool = False
    credits: int = 0
    error: str | None = None
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_ids": list(self.page_ids),
            "cache_hit": self.cache_hit,
            "credits": self.credits,
            "error": self.error,
            "skipped": list(self.skipped),
        }


def source_tier(domain: str) -> str:
    """Tier by registrable suffix: `www.sub.x.gov.uk` resolves to `gov.uk`."""
    host = (domain or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    for start in range(len(labels) - 1):
        tier = SOURCE_TIER.get(".".join(labels[start:]))
        if tier:
            return tier
    return "other"


def source_org(domain: str) -> str | None:
    host = (domain or "").lower().strip(".")
    labels = host.split(".")
    for start in range(len(labels) - 1):
        org = SOURCE_ORG.get(".".join(labels[start:]))
        if org:
            return org
    return None


def is_blocked(url_or_domain: str) -> bool:
    """The `-site:` operators are advisory; a search engine still returns these."""
    host = normalize.domain_of(url_or_domain) or (url_or_domain or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    for start in range(len(labels) - 1):
        if ".".join(labels[start:]) in EXCLUDED_DOMAINS:
            return True
    return False


def _attr(obj: object, *names: str) -> Any:
    """First truthy value of `names`, from either a mapping or an object."""
    if obj is None:
        return None
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value not in (None, "", [], {}):
            return value
    return None


def coerce_page(item: object) -> FetchedPage | None:
    """One SDK search result -> FetchedPage, or None when it carries no content."""
    metadata = _attr(item, "metadata")
    url = _attr(metadata, "url", "source_url", "sourceURL", "og_url", "ogUrl") or _attr(
        item, "url", "source_url", "sourceURL"
    )
    title = _attr(metadata, "title", "og_title", "ogTitle") or _attr(item, "title")
    description = _attr(metadata, "description", "og_description", "ogDescription") or _attr(
        item, "description", "snippet", "summary"
    )
    markdown = _attr(item, "markdown", "content", "text")
    published = _attr(
        metadata,
        "published_time",
        "publishedTime",
        "article:published_time",
        "article_published_time",
        "og_published_time",
        "modified_time",
        "modifiedTime",
        "dc_date",
    ) or _attr(item, "date", "published_time")
    if not url:
        return None
    body = str(markdown) if markdown else (str(description) if description else "")
    if not body.strip():
        return None
    return FetchedPage(
        url=str(url),
        title=str(title) if title else None,
        description=str(description) if description else None,
        markdown=body,
        published_at=normalize.parse_date(published),
        language=str(_attr(metadata, "language", "lang") or "") or None,
        status_code=_int(_attr(metadata, "status_code", "statusCode")),
    )


def coerce_pages(data: object) -> list[FetchedPage]:
    """SearchData (object or dict) -> pages, web results first, then news."""
    pages: list[FetchedPage] = []
    seen: set[str] = set()
    for key in ("web", "news"):
        for item in _attr(data, key) or []:
            page = coerce_page(item)
            if page is None:
                continue
            page_id = normalize.url_hash(page.url)
            if page_id in seen:
                continue
            seen.add(page_id)
            pages.append(page)
    return pages


@lru_cache(maxsize=1)
def supports_tbs() -> bool:
    """firecrawl-py forwards **kwargs into SearchRequest, so check its fields."""
    try:
        from firecrawl.v2.types import SearchRequest
    except Exception:  # noqa: BLE001 - an SDK layout change must not break research
        return False
    return "tbs" in getattr(SearchRequest, "model_fields", {})


_APPEND_SCAN_SCRIPT = (
    "if (ctx._source.scan_ids == null) { ctx._source.scan_ids = []; }"
    " if (!ctx._source.scan_ids.contains(params.scan_id)"
    " && ctx._source.scan_ids.size() < params.cap) {"
    " ctx._source.scan_ids.add(params.scan_id); }"
)


class WebResearcher:
    def __init__(
        self,
        es: AsyncElasticsearch,
        settings: Settings,
        *,
        firecrawl: Any = None,
        index: str = WEB_PAGES_INDEX,
    ) -> None:
        self._es = es
        self._settings = settings
        self._firecrawl = firecrawl
        self._index = index

    def _client(self) -> Any:
        if self._firecrawl is None:
            from firecrawl import AsyncFirecrawl

            self._firecrawl = AsyncFirecrawl(api_key=self._settings.firecrawl_api_key or None)
        return self._firecrawl

    def _ttl_hours(self, tier: str) -> int:
        settings = self._settings
        return {
            "regulator": settings.web_cache_ttl_hours_regulator,
            "news": settings.web_cache_ttl_hours_news,
            "reference": settings.web_cache_ttl_hours_reference,
        }.get(tier, settings.web_cache_ttl_hours_other)

    async def cached_page_ids(self, query_key: str) -> list[str]:
        """Page ids already fetched for this query and still inside their tier's TTL."""
        key = normalize.query_key(query_key or "")
        if not key:
            return []
        response = await self._es.search(
            index=self._index,
            size=CACHE_CANDIDATES,
            # `source`, not `_source`: the client rewrites it into the request body.
            source=[Web.PAGE_ID, Web.SOURCE_TIER, Web.FETCHED_AT],
            query={
                "bool": {
                    "should": [
                        {"term": {Web.QUERY_KEY: key}},
                        {"term": {Web.QUERIES: key}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        )
        now = datetime.now(UTC)
        fresh: list[str] = []
        for raw in response["hits"]["hits"]:
            source = raw.get("_source") or {}
            page_id = source.get(Web.PAGE_ID) or raw.get("_id")
            fetched = normalize.parse_date(source.get(Web.FETCHED_AT))
            if not page_id or fetched is None:
                continue
            ttl = self._ttl_hours(str(source.get(Web.SOURCE_TIER) or "other"))
            if (now - fetched).total_seconds() <= ttl * 3600:
                fresh.append(str(page_id))
        return fresh

    async def search_and_index(
        self,
        query: WebQuery,
        *,
        scan_id: str,
        budget: CreditBudget,
        known_drug_names: list[str] | None = None,
        prepaid: bool = False,
    ) -> WebOutcome:
        try:
            cached = await self.cached_page_ids(query.key)
        except Exception:  # noqa: BLE001 - a cache miss is cheaper than a failed scan
            cached = []
        if len(cached) >= CACHE_MIN_PAGES:
            await self._append_scan_id(cached, scan_id)
            return WebOutcome(page_ids=cached, cache_hit=True, credits=0)

        limit = max(1, int(self._settings.firecrawl_results_per_search))
        cost = estimate_credits(limit)
        # `prepaid` means the caller reserved the whole plan before launching the
        # searches concurrently; taking again here would double-charge the cap.
        if not prepaid:
            try:
                budget.take(cost)
            except BudgetExhausted as exc:
                return WebOutcome(error=str(exc))

        try:
            data = await self._search(query, limit)
        except Exception as exc:  # noqa: BLE001 - SDK raises bare Exception subclasses
            return WebOutcome(credits=cost, error=f"firecrawl search failed: {exc!r}")

        page_ids: list[str] = []
        skipped: list[str] = []
        for page in coerce_pages(data):
            if is_blocked(page.url):
                # Already paid for, but a social post is not evidence: keep it out
                # of the index so it can never be cited.
                skipped.append(page.url)
                continue
            try:
                page_ids.append(
                    await self.index_page(
                        page,
                        scan_id=scan_id,
                        query=query,
                        # One credit per scraped page; the search base sits on the outcome.
                        credits=1,
                        known_drug_names=known_drug_names,
                    )
                )
            except Exception:  # noqa: BLE001 - one bad page must not lose the others
                continue
        return WebOutcome(page_ids=page_ids, credits=cost, skipped=skipped)

    async def _search(self, query: WebQuery, limit: int) -> Any:
        kwargs: dict[str, Any] = {
            "limit": limit,
            "timeout": SEARCH_TIMEOUT_MS,
            "scrape_options": {"formats": ["markdown"], "only_main_content": True},
        }
        if query.tbs and supports_tbs():
            kwargs["tbs"] = query.tbs
        return await self._client().search(query.text, **kwargs)

    async def index_page(
        self,
        page: FetchedPage,
        *,
        scan_id: str | None,
        query: WebQuery | None = None,
        via: str = "backend",
        credits: int = 0,
        known_drug_names: list[str] | None = None,
    ) -> str:
        page_id = normalize.url_hash(page.url)
        existing = await self._existing(page_id)
        now = datetime.now(UTC)
        now_iso = normalize.to_iso(now)
        content = page.markdown[:MAX_CONTENT_CHARS]
        content_hash = normalize.content_hash(content)

        if existing is None:
            first_seen, last_changed, revision = now_iso, now_iso, 1
        elif existing.get(Web.CONTENT_HASH) == content_hash:
            # Unchanged: only fetched_at moves, so recency_date does not drift.
            first_seen = existing.get(Web.FIRST_SEEN_AT) or now_iso
            last_changed = existing.get(Web.LAST_CHANGED_AT) or now_iso
            revision = int(existing.get(Web.REVISION) or 1)
        else:
            first_seen = existing.get(Web.FIRST_SEEN_AT) or now_iso
            last_changed = now_iso
            revision = int(existing.get(Web.REVISION) or 1) + 1

        published_iso = normalize.to_iso(page.published_at)
        domain = normalize.domain_of(page.url)
        title = page.title or ""
        haystack = f"{title}\n{content}"
        ndc9, ndc11 = _ndc_forms(content)
        doc: dict[str, Any] = {
            Web.PAGE_ID: page_id,
            Web.URL: normalize.canonical_url(page.url),
            Web.DOMAIN: domain,
            Web.SOURCE_TIER: source_tier(domain),
            Web.SOURCE_ORG: source_org(domain),
            Web.TITLE: page.title,
            Web.DESCRIPTION: page.description,
            Web.CONTENT: content,
            Web.PAGE_SEMANTIC: normalize.truncate_on_sentence(
                f"{title}\n\n{content}".strip(), MAX_SEMANTIC_CHARS
            ),
            Web.DRUG_NAMES: _mentioned(known_drug_names, haystack),
            Web.LOT_NUMBERS: normalize.extract_batches_from_prose(content)[:MAX_CODES],
            Web.NDC9: ndc9,
            Web.NDC11: ndc11,
            Web.COUNTRIES: normalize.extract_countries(content)[:MAX_COUNTRIES],
            Web.FLAGS: _flags(haystack),
            Web.LANGUAGE: page.language,
            Web.STATUS_CODE: page.status_code,
            Web.PUBLISHED_AT: published_iso,
            Web.FETCHED_AT: now_iso,
            Web.FIRST_SEEN_AT: first_seen,
            Web.LAST_CHANGED_AT: last_changed,
            # Never fetched_at: re-fetching an old page must not make it look fresh.
            Web.RECENCY_DATE: published_iso or last_changed,
            Web.DATE_PRECISION: "published" if published_iso else "fetched",
            Web.CONTENT_HASH: content_hash,
            Web.REVISION: revision,
            Web.STALE: False,
            Web.QUERY_KEY: query.key if query else (existing or {}).get(Web.QUERY_KEY),
            Web.QUERIES: _accumulate(existing, Web.QUERIES, query.key if query else None),
            Web.SCAN_IDS: _accumulate(existing, Web.SCAN_IDS, scan_id),
            Web.FIRECRAWL_CREDITS: int(credits),
            Web.VIA: via,
        }
        doc[Web.IS_RECALL] = "recall" in doc[Web.FLAGS]
        doc[Web.IS_ALERT] = bool(_ALERT_FLAGS.intersection(doc[Web.FLAGS]))
        # refresh="wait_for": the very next search_web must see this page.
        await self._es.index(
            index=self._index, id=page_id, document=doc, refresh="wait_for"
        )
        return page_id

    async def pages_by_id(self, page_ids: list[str]) -> list[Hit]:
        """Exact fetch by id, so a page this scan just indexed is in the evidence
        pack even when the hybrid web search ranks it below the cut."""
        ids = [str(value) for value in page_ids if value]
        if not ids:
            return []
        response = await self._es.search(
            index=self._index,
            size=len(ids),
            source={"excludes": [Web.RAW, Web.PAGE_SEMANTIC]},
            query={"ids": {"values": ids}},
        )
        return [self._to_hit(raw) for raw in response["hits"]["hits"]]

    def _to_hit(self, raw: dict[str, Any]) -> Hit:
        source = dict(raw.get("_source") or {})
        age = normalize.age_days(source.get(Web.RECENCY_DATE))
        return Hit(
            index=raw.get("_index", self._index),
            id=raw["_id"],
            score=0.0,
            source=source,
            match_kind="fetched_for_this_scan",
            age_days=age,
            freshness=normalize.freshness_label(age),
        )

    async def pages_for_scan(self, scan_id: str, *, limit: int = 25) -> list[Hit]:
        """Every page indexed under this scan id.

        The timeout path relies on this: a search cancelled mid-flight may have
        indexed pages the caller never got a `WebOutcome` for.
        """
        if not scan_id:
            return []
        response = await self._es.search(
            index=self._index,
            size=limit,
            source={"excludes": [Web.RAW, Web.PAGE_SEMANTIC]},
            query={"term": {Web.SCAN_IDS: scan_id}},
        )
        return [self._to_hit(raw) for raw in response["hits"]["hits"]]

    async def harvest_agent_pages(self, tool_calls: list[Any], *, scan_id: str) -> list[str]:
        """Index pages the Agent Builder Firecrawl connector fetched on its own."""
        if not self._settings.agent_builder_firecrawl_connector_id:
            return []
        page_ids: list[str] = []
        for call in tool_calls or []:
            if "firecrawl" not in str(_attr(call, "tool_id") or "").lower():
                continue
            for item in _walk_documents(_attr(call, "results")):
                page = coerce_page(item)
                if page is None or is_blocked(page.url):
                    continue
                try:
                    page_ids.append(
                        await self.index_page(page, scan_id=scan_id, via="agent_connector")
                    )
                except Exception:  # noqa: BLE001 - best effort harvesting
                    continue
        return page_ids

    async def _existing(self, page_id: str) -> dict[str, Any] | None:
        try:
            response = await self._es.get(index=self._index, id=page_id, realtime=True)
        except NotFoundError:
            return None
        except Exception:  # noqa: BLE001 - treat an unreadable doc as a new one
            return None
        return dict(response.get("_source") or {})

    async def _append_scan_id(self, page_ids: list[str], scan_id: str) -> None:
        for page_id in page_ids:
            try:
                await self._es.update(
                    index=self._index,
                    id=page_id,
                    script={
                        "source": _APPEND_SCAN_SCRIPT,
                        "params": {"scan_id": scan_id, "cap": MAX_ACCUMULATED},
                    },
                )
            except Exception:  # noqa: BLE001 - provenance is nice to have, not required
                continue


def _accumulate(existing: dict[str, Any] | None, field_name: str, value: str | None) -> list[str]:
    out: list[str] = []
    for item in (existing or {}).get(field_name) or []:
        text = str(item)
        if text and text not in out:
            out.append(text)
    if value and value not in out:
        out.append(value)
    return out[:MAX_ACCUMULATED]


def _mentioned(names: list[str] | None, haystack: str) -> list[str]:
    """Only drug names that literally appear on the page, so the facet stays honest."""
    body = haystack.casefold()
    out: list[str] = []
    for raw in names or []:
        name = normalize.normalize_drug_name(raw)
        if name and name in body and name not in out:
            out.append(name)
    return out[:MAX_CODES]


def _flags(haystack: str) -> list[str]:
    body = haystack.casefold()
    return [flag for flag, needles in _FLAG_RULES if any(n in body for n in needles)]


def _ndc_forms(content: str) -> tuple[list[str], list[str]]:
    ndc9: list[str] = []
    ndc11: list[str] = []
    for raw in normalize.extract_ndcs(content):
        forms = normalize.normalize_ndc(raw)
        if forms is None:
            continue
        if forms.ndc9 and forms.ndc9 not in ndc9:
            ndc9.append(forms.ndc9)
        if forms.ndc11 and forms.ndc11 not in ndc11:
            ndc11.append(forms.ndc11)
    return ndc9[:MAX_CODES], ndc11[:MAX_CODES]


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


_DOC_KEYS = ("markdown", "metadata", "url", "description", "content")


def _walk_documents(payload: object, depth: int = 0) -> list[Any]:
    """Find page-shaped dicts anywhere in a connector's tool result."""
    if depth > 4 or payload is None:
        return []
    if isinstance(payload, list):
        out: list[Any] = []
        for item in payload:
            out.extend(_walk_documents(item, depth + 1))
        return out
    if isinstance(payload, dict):
        if any(key in payload for key in _DOC_KEYS):
            return [payload]
        out = []
        for value in payload.values():
            out.extend(_walk_documents(value, depth + 1))
        return out
    if any(hasattr(payload, key) for key in _DOC_KEYS):
        return [payload]
    return []
