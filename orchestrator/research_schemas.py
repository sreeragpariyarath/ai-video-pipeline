from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    model_validator,
)


RESEARCH_SCHEMA_VERSION = 1

SourceType = Literal["primary", "secondary", "informal", "unknown"]
ClaimCategory = Literal[
    "financial", "technical", "historical", "scientific", "business", "general"
]
VerificationStatus = Literal["unverified", "supported", "contradicted", "disputed"]
EvidenceRelationship = Literal["supports", "contradicts", "contextualizes"]

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _reject_bool(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    return value


UnitInterval = Annotated[float, Field(ge=0.0, le=1.0), BeforeValidator(_reject_bool)]


def _check_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("must be an http(s) URL")
    return value


HttpUrlStr = Annotated[NonEmptyStr, AfterValidator(_check_http_url)]


class ResearchSource(BaseModel):
    source_id: NonEmptyStr
    title: NonEmptyStr
    url: HttpUrlStr
    domain: NonEmptyStr
    source_type: SourceType
    published_date: date | None = None
    retrieved_at: datetime
    description: NonEmptyStr | None = None


class ClaimEvidence(BaseModel):
    source_id: NonEmptyStr
    excerpt: NonEmptyStr
    relationship: EvidenceRelationship
    notes: NonEmptyStr | None = None


class ResearchClaim(BaseModel):
    claim_id: NonEmptyStr
    statement: NonEmptyStr
    category: ClaimCategory
    importance: UnitInterval
    confidence: UnitInterval
    verification_status: VerificationStatus
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    caveats: list[NonEmptyStr] = Field(default_factory=list)


class StoryAngle(BaseModel):
    title: NonEmptyStr
    premise: NonEmptyStr
    why_interesting: NonEmptyStr
    supporting_claim_ids: list[NonEmptyStr] = Field(default_factory=list)


class ResearchPackage(BaseModel):
    schema_version: Literal[RESEARCH_SCHEMA_VERSION] = RESEARCH_SCHEMA_VERSION
    research_id: NonEmptyStr
    topic: NonEmptyStr
    created_at: datetime
    summary: NonEmptyStr
    research_questions: list[NonEmptyStr] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)
    story_angles: list[StoryAngle] = Field(default_factory=list)
    unresolved_questions: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_cross_references(self) -> ResearchPackage:
        problems: list[str] = []

        for label, ids in (
            ("source", [source.source_id for source in self.sources]),
            ("claim", [claim.claim_id for claim in self.claims]),
        ):
            seen: set[str] = set()
            for item_id in ids:
                if item_id in seen:
                    problems.append(f"duplicate {label} ID: {item_id}")
                seen.add(item_id)

        known_sources = {source.source_id for source in self.sources}
        for claim in self.claims:
            for index, evidence in enumerate(claim.evidence):
                if evidence.source_id not in known_sources:
                    problems.append(
                        f"claim '{claim.claim_id}' evidence[{index}] references "
                        f"unknown source ID: {evidence.source_id}"
                    )

        known_claims = {claim.claim_id for claim in self.claims}
        for index, angle in enumerate(self.story_angles):
            for claim_id in angle.supporting_claim_ids:
                if claim_id not in known_claims:
                    problems.append(
                        f"story_angles[{index}] ('{angle.title}') references "
                        f"unknown claim ID: {claim_id}"
                    )

        if problems:
            raise ValueError("; ".join(problems))
        return self


QuestionPriority = Literal["high", "medium", "low"]

PositiveSeconds = Annotated[
    float, Field(gt=0, allow_inf_nan=False), BeforeValidator(_reject_bool)
]


class ResearchQuestion(BaseModel):
    question_id: NonEmptyStr
    question: NonEmptyStr
    reason: NonEmptyStr
    priority: QuestionPriority
    expected_evidence: NonEmptyStr


class SearchQuery(BaseModel):
    query: NonEmptyStr
    question_ids: list[NonEmptyStr] = Field(min_length=1, max_length=12)
    purpose: NonEmptyStr


class SourcePreferences(BaseModel):
    preferred_categories: list[NonEmptyStr] = Field(min_length=1, max_length=8)
    avoid_or_caution: list[NonEmptyStr] = Field(max_length=8)
    prefer_primary_sources: bool


class StoryDirection(BaseModel):
    angle: NonEmptyStr
    description: NonEmptyStr
    questions_to_explore: list[NonEmptyStr] = Field(min_length=1, max_length=12)


class ResearchPlanContent(BaseModel):
    """AI-generated content only; application-owned fields live on ResearchPlan."""

    core_question: NonEmptyStr
    research_questions: list[ResearchQuestion] = Field(min_length=1, max_length=12)
    search_queries: list[SearchQuery] = Field(min_length=1, max_length=24)
    source_preferences: SourcePreferences
    story_directions: list[StoryDirection] = Field(min_length=1, max_length=6)
    target_audience: NonEmptyStr

    @model_validator(mode="after")
    def _check_question_references(self) -> ResearchPlanContent:
        problems: list[str] = []

        seen: set[str] = set()
        for question in self.research_questions:
            if question.question_id in seen:
                problems.append(f"duplicate question ID: {question.question_id}")
            seen.add(question.question_id)

        for index, query in enumerate(self.search_queries):
            if len(set(query.question_ids)) != len(query.question_ids):
                problems.append(f"search_queries[{index}] repeats question IDs")
            for question_id in query.question_ids:
                if question_id not in seen:
                    problems.append(
                        f"search_queries[{index}] references unknown question ID: {question_id}"
                    )

        for index, direction in enumerate(self.story_directions):
            if len(set(direction.questions_to_explore)) != len(direction.questions_to_explore):
                problems.append(f"story_directions[{index}] repeats question IDs")
            for question_id in direction.questions_to_explore:
                if question_id not in seen:
                    problems.append(
                        f"story_directions[{index}] ('{direction.angle}') references "
                        f"unknown question ID: {question_id}"
                    )

        if problems:
            raise ValueError("; ".join(problems))
        return self


class ResearchPlan(ResearchPlanContent):
    topic: NonEmptyStr
    target_seconds: PositiveSeconds
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))