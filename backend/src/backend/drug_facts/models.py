from typing import Literal

from pydantic import BaseModel, Field


class DrugFactsError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DrugFactHit(BaseModel):
    source_url: str
    source_title: str | None = None
    passage: str
    score: float


class DrugFactsCard(BaseModel):
    name: str | None = None
    generic_name: str | None = None
    strength: str | None = None
    ndc: str | None = None
    expected_imprint: str | None = None
    expected_color: str | None = None
    expected_shape: str | None = None
    manufacturer: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DrugFactsResearch(BaseModel):
    search_kind: Literal["imprint", "bottle", "pill"]
    query: str
    sources_scraped: list[str]
    hits: list[DrugFactHit]
    facts: DrugFactsCard
