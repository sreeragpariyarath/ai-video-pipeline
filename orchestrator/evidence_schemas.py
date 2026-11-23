from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .research_schemas import (
    ClaimEvidence,
    EvidenceRelationship,
    HttpUrlStr,
    NonEmptyStr,
    PositiveSeconds,
    _reject_bool,
)


PositiveInt = Annotated[int, BeforeValidator(_reject_bool)]
NonNegativeInt = Annotated[int, BeforeValidator(_reject_bool)]
ExcerptStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=20, max_length=600)
]


class ExcerptItem(BaseModel):
    """AI-generated content only; application-owned fields live elsewhere."""

    excerpt: ExcerptStr
    relationship: EvidenceRelationship
    notes: str = Field(max_length=500)


class PageEvidenceContent(BaseModel):
    """Content-only Gemini output schema: all fields required, no defaults."""

    excerpts: list[ExcerptItem] = Field(max_length=12)


class ExtractionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_sources: PositiveInt = Field(default=8, ge=1, le=30)
    timeout_seconds: PositiveSeconds = 15.0
    max_retries: NonNegativeInt = Field(default=2, ge=0, le=5)
    max_response_bytes: PositiveInt = Field(default=2_000_000, ge=1)
    max_redirects: NonNegativeInt = Field(default=5, ge=0, le=10)
    max_chars_per_source: PositiveInt = Field(default=12_000, ge=1)
    max_excerpts_per_source: PositiveInt = Field(default=6, ge=1, le=12)
    max_fetch_seconds: PositiveSeconds = 30.0


class ExtractedContent(BaseModel):
    title: NonEmptyStr | None = None
    text: NonEmptyStr
    published_date: date | None = None
    extractor: NonEmptyStr


class FetchedPage(BaseModel):
    requested_url: HttpUrlStr
    final_url: HttpUrlStr
    status_code: Annotated[int, Field(ge=100, le=599), BeforeValidator(_reject_bool)]
    content_type: NonEmptyStr
    fetched_at: datetime
    html: str
    truncated: bool
    redirect_count: NonNegativeInt = Field(ge=0)


ExtractionStatus = Literal["ok", "failed", "skipped"]


class SourceExtraction(BaseModel):
    source_id: NonEmptyStr
    canonical_url: HttpUrlStr
    status: ExtractionStatus
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    error: NonEmptyStr | None = None
    chars_extracted: NonNegativeInt = Field(default=0, ge=0)
    rejected_excerpts: NonNegativeInt = Field(default=0, ge=0)
    text_truncated: bool = False

    @model_validator(mode="after")
    def _check_status_consistency(self) -> SourceExtraction:
        if self.status == "failed":
            if not self.error:
                raise ValueError("failed sources must include an error message")
            if self.evidence:
                raise ValueError("failed sources must not carry evidence")
        elif self.error:
            raise ValueError("only failed sources may include an error message")
        if self.status == "skipped" and (
            self.evidence
            or self.chars_extracted
            or self.rejected_excerpts
            or self.text_truncated
        ):
            raise ValueError("skipped sources must have empty evidence and counters")
        for index, item in enumerate(self.evidence):
            if item.source_id != self.source_id:
                raise ValueError(
                    f"evidence[{index}] references source ID {item.source_id}, "
                    f"expected {self.source_id}"
                )
        return self


class ExtractionResult(BaseModel):
    topic: NonEmptyStr
    sources: list[SourceExtraction] = Field(default_factory=list)
    sources_processed: NonNegativeInt = Field(ge=0)
    sources_succeeded: NonNegativeInt = Field(ge=0)
    sources_failed: NonNegativeInt = Field(ge=0)
    sources_skipped: NonNegativeInt = Field(ge=0)
    created_at: datetime

    @model_validator(mode="after")
    def _check_counters_and_ids(self) -> ExtractionResult:
        problems: list[str] = []
        counts = {"ok": 0, "failed": 0, "skipped": 0}
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()
        for source in self.sources:
            counts[source.status] += 1
            if source.source_id in seen_ids:
                problems.append(f"duplicate source ID: {source.source_id}")
            seen_ids.add(source.source_id)
            if source.canonical_url in seen_urls:
                problems.append(f"duplicate canonical URL: {source.canonical_url}")
            seen_urls.add(source.canonical_url)
        if self.sources_processed != len(self.sources):
            problems.append("sources_processed does not match the number of sources")
        if self.sources_succeeded != counts["ok"]:
            problems.append("sources_succeeded does not match ok sources")
        if self.sources_failed != counts["failed"]:
            problems.append("sources_failed does not match failed sources")
        if self.sources_skipped != counts["skipped"]:
            problems.append("sources_skipped does not match skipped sources")
        if problems:
            raise ValueError("; ".join(problems))
        return self