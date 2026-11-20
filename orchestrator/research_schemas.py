from __future__ import annotations

from datetime import date, datetime
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

SourceType = Literal["primary", "secondary", "informal"]
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