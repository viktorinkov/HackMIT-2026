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


@lru_cache
def get_settings() -> Settings:
    return Settings()
