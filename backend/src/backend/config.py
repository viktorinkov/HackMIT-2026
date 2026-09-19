from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win: backend/.env overrides the repo-root .env.
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    openai_api_key: str
    firecrawl_api_key: str = ""
    elasticsearch_url: str = Field(
        default="",
        validation_alias=AliasChoices("ELASTICSEARCH_URL", "ELASTICSEARCH_HOST"),
    )
    elasticsearch_api_key: str = ""

    # Kibana hosts Agent Builder. Blank derives it from the Elasticsearch URL.
    kibana_url: str = ""
    agent_builder_enabled: bool = True
    agent_builder_agent_id: str = "peel-research-agent"
    agent_builder_connector_id: str = ".anthropic-claude-5-sonnet-chat_completion"
    agent_builder_timeout_s: float = 120.0
    agent_builder_firecrawl_connector_id: str = ""
    semantic_score_threshold: float = 0.70

    firecrawl_enabled: bool = True
    firecrawl_max_searches_per_scan: int = 2
    firecrawl_results_per_search: int = 3
    firecrawl_max_credits_per_scan: int = 10
    firecrawl_daily_credit_cap: int = 150
    web_cache_ttl_hours_regulator: int = 24
    web_cache_ttl_hours_news: int = 6
    web_cache_ttl_hours_reference: int = 168
    web_cache_ttl_hours_other: int = 48

    research_model: str = "gpt-4o"
    research_total_timeout_s: float = 240.0
    research_rerank: bool = False
    rxnav_enabled: bool = True
    rxnav_timeout_s: float = 2.0

    scans_store_sensitive: bool = False
    shape_filter_mode: str = "family"  # family | strict | boost

    @property
    def resolved_kibana_url(self) -> str:
        if self.kibana_url:
            return self.kibana_url.rstrip("/")
        return self.elasticsearch_url.rstrip("/").replace(".es.", ".kb.", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
