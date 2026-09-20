"""Contract every seed source implements.

A source downloads raw artifacts into backend/data/raw/<name>/ (plain HTTP, no
Firecrawl, no LLM) and parses them into documents for one Peel index. Documents
carry "_id" plus only fields mapped for that index (mappings are strict).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import httpx

DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# Fast, vector-free sources first so pill lookup works while embeddings ingest.
DEFAULT_ORDER = (
    "pillbox",
    "openfda_enforcement",
    "who_alerts",
    "nafdac",
    "mhra",
    "health_canada",
    "openfda_ndc",
)


@dataclass
class SeedContext:
    http: httpx.AsyncClient
    now: datetime
    limit: int | None = None
    refresh_cache: bool = False
    concurrency: int = 8
    options: dict[str, Any] = field(default_factory=dict)

    def raw_dir(self, source: str) -> Path:
        path = DATA_DIR / "raw" / source
        path.mkdir(parents=True, exist_ok=True)
        return path

    def normalized_path(self, source: str) -> Path:
        path = DATA_DIR / "normalized"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{source}.jsonl"


class Source(ABC):
    name: ClassVar[str]
    index: ClassVar[str]
    description: ClassVar[str] = ""
    # True when documents carry a semantic_text field (smaller, slower bulk chunks).
    semantic: ClassVar[bool] = False

    @abstractmethod
    async def download(self, ctx: SeedContext) -> None:
        """Fetch raw artifacts into ctx.raw_dir(self.name). Reuse cached files
        unless ctx.refresh_cache. Honour ctx.limit where it avoids needless fetches."""

    @abstractmethod
    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        """Yield index-ready documents from the raw cache, newest first where the
        source has dates. Must not touch the network. Stop after ctx.limit docs."""
