from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from .research_schemas import (
    EvidenceRelationship,
    NonEmptyStr,
    UnitInterval,
    VerificationStatus,
)


MAX_CLAIMS = 24
MAX_EVIDENCE = 60


class EvidenceEvaluation(BaseModel):
    """AI-generated content only; application-owned fields live elsewhere."""

    evidence_id: NonEmptyStr
    relationship: EvidenceRelationship
    note: str = Field(max_length=300)


class ClaimVerificationContent(BaseModel):
    """AI-generated content only; application-owned fields live elsewhere."""

    claim_id: NonEmptyStr
    status: VerificationStatus
    confidence: UnitInterval
    rationale: NonEmptyStr = Field(max_length=500)
    evaluations: list[EvidenceEvaluation] = Field(max_length=MAX_EVIDENCE)


class ClaimVerificationsContent(BaseModel):
    """Content-only Gemini output schema: all fields required, no defaults."""

    verifications: list[ClaimVerificationContent] = Field(max_length=MAX_CLAIMS)


class EvidenceJudgment(BaseModel):
    evidence_id: NonEmptyStr
    source_id: NonEmptyStr
    relationship: EvidenceRelationship


class ClaimVerification(BaseModel):
    claim_id: NonEmptyStr
    status: VerificationStatus
    confidence: UnitInterval
    rationale: NonEmptyStr = Field(max_length=500)
    evidence: list[EvidenceJudgment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_status_consistency(self) -> ClaimVerification:
        seen: set[str] = set()
        for item in self.evidence:
            if item.evidence_id in seen:
                raise ValueError(f"duplicate evidence ID: {item.evidence_id}")
            seen.add(item.evidence_id)
        relationships = {item.relationship for item in self.evidence}
        if self.status == "supported" and "supports" not in relationships:
            raise ValueError("supported claims require supporting evidence")
        if self.status == "contradicted" and "contradicts" not in relationships:
            raise ValueError("contradicted claims require contradicting evidence")
        if self.status == "disputed" and not {"supports", "contradicts"} <= relationships:
            raise ValueError(
                "disputed claims require both supporting and contradicting evidence"
            )
        return self


class VerificationResult(BaseModel):
    verifications: list[ClaimVerification] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def _check_unique_claims(self) -> VerificationResult:
        seen: set[str] = set()
        for item in self.verifications:
            if item.claim_id in seen:
                raise ValueError(f"duplicate claim ID: {item.claim_id}")
            seen.add(item.claim_id)
        return self