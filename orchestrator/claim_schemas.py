from __future__ import annotations

from pydantic import BaseModel, Field

from .research_schemas import ClaimCategory, NonEmptyStr
from .verification_schemas import MAX_CLAIMS, MAX_EVIDENCE


class SynthesizedClaim(BaseModel):
    """AI-generated content only; application-owned fields live elsewhere."""

    statement: NonEmptyStr = Field(max_length=300)
    category: ClaimCategory
    evidence_ids: list[NonEmptyStr] = Field(min_length=1, max_length=MAX_EVIDENCE)
    caveats: list[NonEmptyStr] = Field(max_length=6)


class ClaimSynthesisContent(BaseModel):
    """Content-only Gemini output schema: all fields required, no defaults."""

    claims: list[SynthesizedClaim] = Field(min_length=1, max_length=MAX_CLAIMS)