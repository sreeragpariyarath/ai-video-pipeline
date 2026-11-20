from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .research_schemas import HttpUrlStr, NonEmptyStr, UnitInterval


SourceTier = Literal["primary", "secondary", "informal", "unknown"]


class DiscoveryCandidate(BaseModel):
    source_id: NonEmptyStr
    title: NonEmptyStr
    original_url: HttpUrlStr
    canonical_url: HttpUrlStr
    domain: NonEmptyStr
    snippet: NonEmptyStr | None = None
    published_date: date | None = None
    relevance_score: UnitInterval | None = None
    source_tier: SourceTier
    tier_reason: NonEmptyStr
    question_ids: list[NonEmptyStr] = Field(min_length=1)
    discovered_by_queries: list[NonEmptyStr] = Field(min_length=1)
    discovered_at: datetime
    rank_score: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check_unique_lists(self) -> DiscoveryCandidate:
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("question_ids must not contain duplicates")
        if len(set(self.discovered_by_queries)) != len(self.discovered_by_queries):
            raise ValueError("discovered_by_queries must not contain duplicates")
        return self


class QueryReport(BaseModel):
    query: NonEmptyStr
    question_ids: list[NonEmptyStr] = Field(min_length=1)
    status: Literal["ok", "failed", "skipped"]
    results_returned: int = Field(ge=0)
    error: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _check_status_consistency(self) -> QueryReport:
        if self.status == "failed" and not self.error:
            raise ValueError("failed query reports must include an error message")
        if self.status != "failed" and self.error:
            raise ValueError("only failed query reports may include an error message")
        if self.status == "skipped" and self.results_returned != 0:
            raise ValueError("skipped queries must report zero results")
        return self


class DiscoveryResult(BaseModel):
    topic: NonEmptyStr
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    queries: list[QueryReport] = Field(default_factory=list)
    queries_executed: int = Field(ge=0)
    results_examined: int = Field(ge=0)
    duplicates_removed: int = Field(ge=0)
    created_at: datetime

    @model_validator(mode="after")
    def _check_unique_candidates(self) -> DiscoveryResult:
        problems: list[str] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        for candidate in self.candidates:
            if candidate.source_id in seen_ids:
                problems.append(f"duplicate source ID: {candidate.source_id}")
            seen_ids.add(candidate.source_id)
            if candidate.canonical_url in seen_urls:
                problems.append(f"duplicate canonical URL: {candidate.canonical_url}")
            seen_urls.add(candidate.canonical_url)
        if problems:
            raise ValueError("; ".join(problems))
        return self