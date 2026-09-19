from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BACKEND_DIR / ".env",
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
    mongodb_uri: str = ""
    mongodb_server_selection_timeout_ms: int = 5000
    deepgram_api_key: str = ""
    deepgram_member_key: str = ""
    deepgram_websocket_url: str = "wss://agent.deepgram.com/v1/agent/converse"
    deepgram_grant_ttl_seconds: int = 120
    public_api_base_url: str = "https://m2cw0a06ep8e5g-8000.proxy.runpod.net"


@lru_cache
def get_settings() -> Settings:
    return Settings()
