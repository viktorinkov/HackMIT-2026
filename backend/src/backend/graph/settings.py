"""Graph-only settings. Zero edits to `backend.config`.

`extra="ignore"` is load-bearing rather than tidy. pydantic-settings' dotenv
source injects every key it finds in the file into the model's data regardless of
`env_prefix`, and `BaseSettings` defaults to `extra="forbid"` — so a class
pointed at the shared `.env` (which holds `OPENAI_API_KEY`, `ELASTICSEARCH_URL`
and friends) raises `ValidationError` on construction. That would break `?demo=1`
in precisely the environment that has a `.env`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.config import Settings

_ENV_FILES = Settings.model_config["env_file"]


class GraphSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRAPH_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The personal graph is cheap and changes while someone watches it scan.
    personal_ttl_s: int = 20
    expand_ttl_s: int = 600
    # The corpus changes only on a re-seed.
    universe_ttl_s: int = 21600

    demo_device_id: str = "peel-graph-demo"
    max_nodes: int = 600
    max_links: int = 1500
    scan_limit: int = 50


@lru_cache
def get_graph_settings() -> GraphSettings:
    return GraphSettings()
