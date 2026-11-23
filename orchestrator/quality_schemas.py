from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence_schemas import NonNegativeInt, PositiveInt
from .research_schemas import NonEmptyStr, PositiveSeconds, UnitInterval


QualityStatus = Literal["ready", "needs_review", "insufficient"]


class QualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_sources: PositiveInt = Field(default=3, ge=1)
    min_claims: PositiveInt = Field(default=1, ge=1)
    min_distinct_domains: PositiveInt = Field(default=2, ge=1)
    min_evidence_coverage: UnitInterval = 0.8
    contradiction_ratio: UnitInterval = 0.3
    # Token-set overlap (Jaccard) at or above this marks two claims as
    # highly similar. 0.9 flags near-verbatim restatements, not shared topics.
    similar_claim_threshold: UnitInterval = 0.9


class QualityWarning(BaseModel):
    code: NonEmptyStr
    message: NonEmptyStr


class SourceMetrics(BaseModel):
    total: NonNegativeInt
    distinct_domains: NonNegativeInt
    primary: NonNegativeInt
    secondary: NonNegativeInt
    informal: NonNegativeInt
    unknown: NonNegativeInt


class ClaimMetrics(BaseModel):
    total: NonNegativeInt
    supported: NonNegativeInt
    contradicted: NonNegativeInt
    disputed: NonNegativeInt
    unverified: NonNegativeInt
    duplicate_statements: NonNegativeInt
    # Counts pairs of non-identical statements whose token overlap is high.
    similar_statements: NonNegativeInt = 0

    @model_validator(mode="after")
    def _check_counts(self) -> ClaimMetrics:
        if (
            self.supported + self.contradicted + self.disputed + self.unverified
            != self.total
        ):
            raise ValueError("claim status counts must sum to total")
        return self


class EvidenceMetrics(BaseModel):
    total_items: NonNegativeInt
    claims_with_evidence: NonNegativeInt
    coverage: UnitInterval


class Completeness(BaseModel):
    has_summary: bool
    has_research_questions: bool
    has_story_angles: bool


class QualityReport(BaseModel):
    status: QualityStatus
    warnings: list[QualityWarning] = Field(default_factory=list)
    sources: SourceMetrics
    claims: ClaimMetrics
    evidence: EvidenceMetrics
    completeness: Completeness

    @model_validator(mode="after")
    def _check_status_consistency(self) -> QualityReport:
        if self.status == "ready" and self.warnings:
            raise ValueError("ready reports must not carry warnings")
        if self.status in {"needs_review", "insufficient"} and not self.warnings:
            raise ValueError(f"{self.status} reports must explain their warnings")
        codes = [warning.code for warning in self.warnings]
        if len(set(codes)) != len(codes):
            raise ValueError("duplicate warning codes")
        if self.evidence.claims_with_evidence > self.claims.total:
            raise ValueError("claims_with_evidence cannot exceed total claims")
        return self


class ResourceLimits(BaseModel):
    max_research_questions: PositiveInt
    max_search_queries: PositiveInt
    max_candidates: PositiveInt
    max_sources_fetched: PositiveInt
    max_fetch_requests_per_source: PositiveInt
    max_fetch_seconds_per_source: PositiveSeconds
    max_evidence_items: PositiveInt
    max_claims: PositiveInt
    max_gemini_calls: PositiveInt


class ResourceUsage(BaseModel):
    queries_executed: NonNegativeInt
    queries_failed: NonNegativeInt
    candidates_discovered: NonNegativeInt
    sources_processed: NonNegativeInt
    sources_failed: NonNegativeInt
    evidence_items: NonNegativeInt
    claims_verified: NonNegativeInt
    limits: ResourceLimits

    @model_validator(mode="after")
    def _check_bounds(self) -> ResourceUsage:
        problems: list[str] = []
        if self.queries_failed > self.queries_executed:
            problems.append("queries_failed cannot exceed queries_executed")
        if self.sources_failed > self.sources_processed:
            problems.append("sources_failed cannot exceed sources_processed")
        if self.queries_executed > self.limits.max_search_queries:
            problems.append("queries_executed exceeds max_search_queries")
        if self.candidates_discovered > self.limits.max_candidates:
            problems.append("candidates_discovered exceeds max_candidates")
        if self.sources_processed > self.candidates_discovered:
            problems.append("sources_processed cannot exceed candidates_discovered")
        if self.sources_failed > self.limits.max_sources_fetched:
            problems.append("sources_failed exceeds max_sources_fetched")
        if self.evidence_items > self.limits.max_evidence_items:
            problems.append("evidence_items exceeds max_evidence_items")
        if self.claims_verified > self.limits.max_claims:
            problems.append("claims_verified exceeds max_claims")
        if problems:
            raise ValueError("; ".join(problems))
        return self