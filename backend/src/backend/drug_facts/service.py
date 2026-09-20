from openai import APIError, AsyncOpenAI
from fastapi import Depends

from backend.config import Settings, get_settings
from backend.drug_facts.chunking import chunk_markdown
from backend.drug_facts.elastic import ElasticStore, SearchKind, get_elastic_store
from backend.drug_facts.firecrawl_client import (
    BOTTLE_DOMAINS,
    IMPRINT_DOMAINS,
    PILL_DOMAINS,
    FirecrawlClient,
    get_firecrawl_client,
)
from backend.drug_facts.models import (
    DrugFactHit,
    DrugFactsCard,
    DrugFactsError,
    DrugFactsResearch,
)
from backend.drug_facts.queries import (
    bottle_search_query,
    imprint_search_query,
    normalize_query,
    pill_search_query,
)
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import PillHardwareResult

FACTS_MODEL = "gpt-4o"
FACTS_INSTRUCTIONS = """\
Extract medication facts that are supported by the retrieved passages.
Read only the passages. Do not invent an NDC, imprint, name, strength, or warning.
This is not a real/fake verdict and not medical advice.
If sources disagree, prefer DailyMed.
"""


class ResearchService:
    def __init__(
        self,
        settings: Settings,
        elastic: ElasticStore,
        firecrawl: FirecrawlClient,
    ) -> None:
        self._elastic = elastic
        self._firecrawl = firecrawl
        self._openai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def research_imprint(self, result: ImprintPhotoResult) -> DrugFactsResearch:
        if not result.is_pill:
            raise DrugFactsError("Photo was not a pill.", status_code=400)
        query = imprint_search_query(result)
        if not query:
            raise DrugFactsError(
                "Need an imprint or physical features to research the imprint.",
                status_code=400,
            )
        return await self._research("imprint", query, IMPRINT_DOMAINS)

    async def research_bottle(self, result: BottlePhotoResult) -> DrugFactsResearch:
        if not result.is_medication_container:
            raise DrugFactsError("Photo was not a medication container.", status_code=400)
        query = bottle_search_query(result)
        if not query:
            raise DrugFactsError(
                "Need an NDC or drug name to research the bottle.",
                status_code=400,
            )
        return await self._research("bottle", query, BOTTLE_DOMAINS)

    async def research_pill(self, result: PillHardwareResult) -> DrugFactsResearch:
        # Fake contents have no trusted identity to look up. Unknown is also
        # not an identity: a low-confidence spectrum must not get DailyMed facts.
        # Substandard still has a matched type; look up that type's label facts.
        if result.status == "fake":
            raise DrugFactsError(
                "Hardware classified this pill as fake; contents facts are not looked up.",
                status_code=400,
            )
        if result.status == "unknown":
            raise DrugFactsError(
                "Hardware did not identify a pill type to research.",
                status_code=400,
            )
        query = pill_search_query(result)
        if not query:
            raise DrugFactsError(
                "Need a hardware pill_type to research contents facts.",
                status_code=400,
            )
        return await self._research("pill", query, PILL_DOMAINS)

    async def _research(
        self,
        kind: SearchKind,
        query: str,
        domains: tuple[str, ...],
    ) -> DrugFactsResearch:
        query_key = normalize_query(query)
        cached = await self._elastic.cached_hits(kind, query_key)
        sources_scraped: list[str] = []
        if not self._elastic.has_cache(cached):
            pages = await self._firecrawl.search_pages(query, domains)
            sources_scraped = [page.url for page in pages]
            chunks: list[tuple[str, str | None, str]] = []
            for page in pages:
                for text in chunk_markdown(page.markdown):
                    chunks.append((page.url, page.title, text))
            await self._elastic.upsert_chunks(kind, query, query_key, chunks)
        hits = await self._elastic.search(kind, query)
        if not hits:
            hits = cached
        if not hits:
            raise DrugFactsError("No drug facts found for this query")
        if not sources_scraped:
            sources_scraped = list(dict.fromkeys(hit.source_url for hit in hits))
        facts = await self._parse_facts(hits)
        return DrugFactsResearch(
            search_kind=kind,
            query=query,
            sources_scraped=sources_scraped,
            hits=hits,
            facts=facts,
        )

    async def _parse_facts(self, hits: list[DrugFactHit]) -> DrugFactsCard:
        passages = "\n\n".join(
            f"Source: {hit.source_url}\n{hit.passage}" for hit in hits[:6]
        )
        try:
            response = await self._openai.responses.parse(
                model=FACTS_MODEL,
                instructions=FACTS_INSTRUCTIONS,
                input=f"Extract structured drug facts from these passages:\n\n{passages}",
                text_format=DrugFactsCard,
            )
        except APIError as exc:
            raise DrugFactsError(
                exc.message or "OpenAI failed to parse drug facts"
            ) from exc
        parsed = response.output_parsed
        if parsed is None:
            raise DrugFactsError("OpenAI returned no structured drug facts")
        return parsed


def get_research_service(
    settings: Settings = Depends(get_settings),
    elastic: ElasticStore = Depends(get_elastic_store),
    firecrawl: FirecrawlClient = Depends(get_firecrawl_client),
) -> ResearchService:
    return ResearchService(settings, elastic, firecrawl)
