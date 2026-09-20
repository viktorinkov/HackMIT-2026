from __future__ import annotations

from dataclasses import dataclass

from firecrawl import AsyncFirecrawl
from fastapi import Depends

from backend.config import Settings, get_settings
from backend.drug_facts.models import DrugFactsError

IMPRINT_DOMAINS = ("drugs.com", "dailymed.nlm.nih.gov")
BOTTLE_DOMAINS = ("dailymed.nlm.nih.gov", "drugs.com", "www.accessdata.fda.gov")
# Hardware identity is a drug name, not an imprint code: same label sources as the bottle.
PILL_DOMAINS = BOTTLE_DOMAINS

_SEARCH_LIMIT = 3
_SEARCH_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class ScrapedPage:
    url: str
    title: str | None
    markdown: str


class FirecrawlClient:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.firecrawl_api_key
        self._client = AsyncFirecrawl(api_key=settings.firecrawl_api_key or None)

    async def search_pages(self, query: str, domains: tuple[str, ...]) -> list[ScrapedPage]:
        if not self._api_key:
            raise DrugFactsError("FIRECRAWL_API_KEY is not set")
        pages = await self._search(query, domains)
        if not pages:
            pages = await self._search(query, ())
        return pages

    async def _search(self, query: str, domains: tuple[str, ...]) -> list[ScrapedPage]:
        kwargs: dict[str, object] = {
            "limit": _SEARCH_LIMIT,
            "timeout": _SEARCH_TIMEOUT_MS,
            "scrape_options": {
                "formats": ["markdown"],
                "only_main_content": True,
            },
        }
        if domains:
            kwargs["include_domains"] = list(domains)
        try:
            results = await self._client.search(query, **kwargs)
        except Exception as exc:
            raise DrugFactsError(f"Firecrawl search failed: {exc}") from exc

        pages: list[ScrapedPage] = []
        seen: set[str] = set()
        for item in results.web or []:
            page = _as_page(item)
            if page is None or page.url in seen:
                continue
            seen.add(page.url)
            pages.append(page)
        return pages


def get_firecrawl_client(
    settings: Settings = Depends(get_settings),
) -> FirecrawlClient:
    return FirecrawlClient(settings)


def _as_page(item: object) -> ScrapedPage | None:
    markdown = getattr(item, "markdown", None)
    metadata = getattr(item, "metadata", None)
    url = _meta_url(metadata) or getattr(item, "url", None)
    title = _meta_title(metadata) or getattr(item, "title", None)
    if not markdown:
        markdown = getattr(item, "description", None)
    if not url or not markdown:
        return None
    return ScrapedPage(url=str(url), title=str(title) if title else None, markdown=str(markdown))


def _meta_url(metadata: object) -> str | None:
    if metadata is None:
        return None
    url = getattr(metadata, "url", None)
    return str(url) if url else None


def _meta_title(metadata: object) -> str | None:
    if metadata is None:
        return None
    title = getattr(metadata, "title", None)
    return str(title) if title else None
