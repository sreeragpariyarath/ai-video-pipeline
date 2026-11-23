from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .evidence_schemas import NonNegativeInt, PositiveInt
from .research_schemas import NonEmptyStr, PositiveSeconds, ResearchPackage


VideoFormat = Literal["short", "mid_form", "long_form"]
SegmentType = Literal[
    "hook",
    "setup",
    "context",
    "explanation",
    "revelation",
    "transition",
    "payoff",
    "conclusion",
]

# Derived totals are compared to their parts with this tolerance. It absorbs
# float accumulation error without allowing a meaningfully wrong total.
DURATION_TOLERANCE_SECONDS = 0.01

# Generation bounds: enough room for layered long-form beats, but a bounded
# structured response the application can always validate.
MIN_SCRIPT_SEGMENTS = 3
MAX_SCRIPT_SEGMENTS = 32


class ScriptSegment(BaseModel):
    segment_id: NonEmptyStr
    order: PositiveInt
    segment_type: SegmentType
    narration: NonEmptyStr
    duration_seconds: PositiveSeconds
    claim_ids: list[NonEmptyStr] = Field(default_factory=list)
    purpose: NonEmptyStr

    @model_validator(mode="after")
    def _check_claim_ids(self) -> ScriptSegment:
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("claim_ids must not contain duplicates")
        return self


class VideoScript(BaseModel):
    script_id: NonEmptyStr
    research_id: NonEmptyStr
    format: VideoFormat
    target_seconds: PositiveSeconds
    planned_seconds: PositiveSeconds
    title: NonEmptyStr
    hook: NonEmptyStr
    narrative_arc: NonEmptyStr
    segments: list[ScriptSegment] = Field(min_length=1)
    word_count: NonNegativeInt
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _check_consistency(self) -> VideoScript:
        problems: list[str] = []
        segments = self.segments

        ids = [segment.segment_id for segment in segments]
        duplicates = sorted(
            {segment_id for segment_id in ids if ids.count(segment_id) > 1}
        )
        if duplicates:
            problems.append(f"duplicate segment IDs: {', '.join(duplicates)}")

        expected_order = list(range(1, len(segments) + 1))
        actual_order = [segment.order for segment in segments]
        if actual_order != expected_order:
            problems.append(
                f"segment order must be sequential from 1 (found {actual_order})"
            )

        if segments[0].segment_type != "hook":
            problems.append("the opening segment must have type 'hook'")
        if any(segment.segment_type == "hook" for segment in segments[1:]):
            problems.append("only the opening segment may have type 'hook'")

        hook = self.hook.strip()
        opening_narration = segments[0].narration.strip()
        if not opening_narration.startswith(hook):
            problems.append("the opening segment narration must start with the hook")

        total_words = sum(len(segment.narration.split()) for segment in segments)
        if self.word_count != total_words:
            problems.append(
                "word_count must match the narration word count "
                f"(declared {self.word_count}, found {total_words})"
            )

        total_seconds = sum(segment.duration_seconds for segment in segments)
        if abs(self.planned_seconds - total_seconds) > DURATION_TOLERANCE_SECONDS:
            problems.append(
                f"planned_seconds ({self.planned_seconds:g}) must equal the "
                f"segment duration sum ({total_seconds:g})"
            )

        if problems:
            raise ValueError("; ".join(problems))
        return self


def validate_claim_references(script: VideoScript, package: ResearchPackage) -> None:
    """Reject claim IDs absent from the package, or a wrong research package.

    Claim IDs are free-form on ScriptSegment, so existence can only be checked
    against the package the script was written from. The research ID check also
    catches a valid package being passed for the wrong script. This stays a
    pure, deterministic check; it does not re-verify the claims themselves.
    """
    if script.research_id != package.research_id:
        raise ValueError(
            f"script research_id ({script.research_id}) does not match "
            f"package research_id ({package.research_id})"
        )
    known = {claim.claim_id for claim in package.claims}
    cited = {claim_id for segment in script.segments for claim_id in segment.claim_ids}
    unknown = sorted(cited - known)
    if unknown:
        raise ValueError(f"script cites unknown claim IDs: {', '.join(unknown)}")


class ScriptSegmentContent(BaseModel):
    """AI-generated segment content only; application-owned fields live elsewhere."""

    segment_type: SegmentType
    narration: NonEmptyStr
    purpose: NonEmptyStr
    claim_ids: list[NonEmptyStr]
    duration_seconds: PositiveSeconds


class ScriptContent(BaseModel):
    """Content-only Gemini output schema: all fields required, no defaults."""

    title: NonEmptyStr
    hook: NonEmptyStr
    narrative_arc: NonEmptyStr
    segments: list[ScriptSegmentContent] = Field(
        min_length=MIN_SCRIPT_SEGMENTS, max_length=MAX_SCRIPT_SEGMENTS
    )
