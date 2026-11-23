from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import get_args

from pydantic import ValidationError

from .gemini import GeminiClient, GeminiError
from .prompts import SCRIPT_GENERATION_SYSTEM, script_generation_prompt
from .research_schemas import ResearchClaim, ResearchPackage
from .script_schemas import (
    MAX_SCRIPT_SEGMENTS,
    ScriptContent,
    ScriptSegment,
    ScriptSegmentContent,
    VideoFormat,
    VideoScript,
)


VIDEO_FORMATS = frozenset(get_args(VideoFormat))

INVALID_OUTPUT_MESSAGE = "Gemini returned invalid script content."
REQUEST_FAILED_MESSAGE = "Gemini request failed."
NO_SUPPORTED_CLAIMS_MESSAGE = (
    "Research package has no supported claims with evidence to build a script from."
)
TARGET_TOO_SHORT_MESSAGE = (
    "Target duration is too short for the generated segment count."
)

# Pipeline IDs look like cl-1, src-2, ev-3. They must never reach narration,
# where a viewer would hear them.
_ID_IN_NARRATION = re.compile(r"\b(?:cl|src|ev)-\d+\b", re.IGNORECASE)


class ScriptGenerationError(RuntimeError):
    """Script generation failed; the message is application-defined and sanitized."""


def _validate_inputs(
    package: ResearchPackage, video_format: str, target_seconds: float
) -> None:
    if not isinstance(package, ResearchPackage):
        raise ValueError("package must be a ResearchPackage instance.")
    if not isinstance(video_format, str) or video_format not in VIDEO_FORMATS:
        raise ValueError(f"format must be one of {sorted(VIDEO_FORMATS)}.")
    if (
        isinstance(target_seconds, bool)
        or not isinstance(target_seconds, (int, float))
        or not math.isfinite(target_seconds)
        or target_seconds <= 0
    ):
        raise ValueError("Target duration must be a finite number greater than 0.")


def _eligible_claims(package: ResearchPackage) -> list[ResearchClaim]:
    """Claims safe to use as facts: verified as supported and backed by evidence."""
    return [
        claim
        for claim in package.claims
        if claim.verification_status == "supported" and claim.evidence
    ]


def _sanitized(exc: GeminiError) -> ScriptGenerationError:
    # GeminiError text can embed model output quoting page content; only
    # application-defined classifications are surfaced.
    message = str(exc)
    if "does not match" in message or "empty JSON" in message:
        return ScriptGenerationError(INVALID_OUTPUT_MESSAGE)
    return ScriptGenerationError(REQUEST_FAILED_MESSAGE)


def _allocate_durations(
    weights: list[float], target_seconds: float
) -> list[float]:
    """Scale relative estimates so the segment durations sum to the target.

    Allocation works in hundredths of a second with the largest-remainder
    method, so the total is exact and every segment stays positive.
    """
    if not weights:
        raise ScriptGenerationError(INVALID_OUTPUT_MESSAGE)
    total_weight = sum(weights)
    if total_weight <= 0:
        raise ScriptGenerationError(INVALID_OUTPUT_MESSAGE)
    units = round(target_seconds * 100)
    if units < len(weights):
        raise ScriptGenerationError(TARGET_TOO_SHORT_MESSAGE)

    raw = [weight / total_weight * units for weight in weights]
    allocated = [math.floor(value) for value in raw]
    remainder = units - sum(allocated)
    order = sorted(
        range(len(raw)),
        key=lambda index: (-(raw[index] - allocated[index]), index),
    )
    for index in order[:remainder]:
        allocated[index] += 1
    if any(value < 1 for value in allocated):
        # Degenerate weights (a near-zero estimate) can floor to zero. Fall
        # back to an equal split rather than emit an invalid zero duration.
        base, extra = divmod(units, len(weights))
        allocated = [
            base + (1 if index < extra else 0) for index in range(len(weights))
        ]
    return [value / 100 for value in allocated]


def _assemble(
    content: ScriptContent,
    package: ResearchPackage,
    video_format: VideoFormat,
    target_seconds: float,
    eligible_ids: set[str],
) -> VideoScript:
    cited = {
        claim_id for segment in content.segments for claim_id in segment.claim_ids
    }
    if not cited or cited - eligible_ids:
        raise ScriptGenerationError(INVALID_OUTPUT_MESSAGE)

    try:
        durations = _allocate_durations(
            [segment.duration_seconds for segment in content.segments],
            target_seconds,
        )
        segments = [
            ScriptSegment(
                segment_id=f"seg-{index:02d}",
                order=index,
                segment_type=segment.segment_type,
                narration=segment.narration,
                duration_seconds=durations[index - 1],
                claim_ids=segment.claim_ids,
                purpose=segment.purpose,
            )
            for index, segment in enumerate(content.segments, start=1)
        ]
        return VideoScript(
            script_id=f"script-{uuid.uuid4().hex}",
            research_id=package.research_id,
            format=video_format,
            target_seconds=target_seconds,
            planned_seconds=round(sum(durations), 2),
            title=content.title,
            hook=content.hook,
            narrative_arc=content.narrative_arc,
            segments=segments,
            word_count=sum(
                len(segment.narration.split()) for segment in segments
            ),
            created_at=datetime.now(timezone.utc),
        )
    except ScriptGenerationError:
        raise
    except (ValidationError, ValueError):
        raise ScriptGenerationError(INVALID_OUTPUT_MESSAGE) from None


class ScriptGenerator:
    def __init__(self, client: GeminiClient):
        self._client = client

    def generate(
        self,
        package: ResearchPackage,
        *,
        format: VideoFormat,
        target_seconds: float,
    ) -> VideoScript:
        _validate_inputs(package, format, target_seconds)
        eligible = _eligible_claims(package)
        if not eligible:
            raise ScriptGenerationError(NO_SUPPORTED_CLAIMS_MESSAGE)
        eligible_ids = {claim.claim_id for claim in eligible}
        excluded = [
            claim
            for claim in package.claims
            if claim.claim_id not in eligible_ids
        ]
        try:
            content = self._client.generate_json(
                system=SCRIPT_GENERATION_SYSTEM,
                prompt=script_generation_prompt(
                    topic=package.topic,
                    summary=package.summary,
                    supported_claims=eligible,
                    excluded_claims=excluded,
                    sources={source.source_id: source for source in package.sources},
                    video_format=format,
                    target_seconds=target_seconds,
                ),
                schema=ScriptContent,
                temperature=0.7,
            )
        except GeminiError as exc:
            raise _sanitized(exc) from None
        # The model must cite claims through claim_ids, never in spoken text.
        if any(
            _ID_IN_NARRATION.search(segment.narration)
            for segment in content.segments
        ):
            raise ScriptGenerationError(INVALID_OUTPUT_MESSAGE)
        return _assemble(content, package, format, target_seconds, eligible_ids)


class MockScriptGenerator:
    """Deterministic offline script generation from supported research claims."""

    def generate(
        self,
        package: ResearchPackage,
        *,
        format: VideoFormat,
        target_seconds: float,
    ) -> VideoScript:
        _validate_inputs(package, format, target_seconds)
        eligible = _eligible_claims(package)
        if not eligible:
            raise ScriptGenerationError(NO_SUPPORTED_CLAIMS_MESSAGE)

        subject = package.topic.strip().rstrip(".!")
        if package.topic.strip().endswith("?"):
            hook = package.topic.strip()
        else:
            hook = f"{subject}: what the simple version leaves out."

        # Leave room for the fixed opening and closing beats so a long request
        # still produces a script inside the generated-content segment bounds.
        claim_limit = max(
            1, min(math.ceil(target_seconds / 12), MAX_SCRIPT_SEGMENTS - 4)
        )
        claims = eligible[:claim_limit]
        segments = [
            ScriptSegmentContent(
                segment_type="hook",
                narration=hook,
                purpose="Open a curiosity gap.",
                claim_ids=[],
                duration_seconds=max(1.0, len(hook.split())),
            ),
            ScriptSegmentContent(
                segment_type="setup",
                narration="Here is the part that changes how it looks.",
                purpose="Frame the question.",
                claim_ids=[],
                duration_seconds=7.0,
            ),
        ]
        for index, claim in enumerate(claims):
            segments.append(
                ScriptSegmentContent(
                    segment_type=(
                        "revelation"
                        if len(claims) > 1 and index == len(claims) - 1
                        else "explanation"
                    ),
                    narration=claim.statement,
                    purpose=f"Ground the story in a {claim.category} claim.",
                    claim_ids=[claim.claim_id],
                    duration_seconds=max(1.0, len(claim.statement.split())),
                )
            )
        segments.extend(
            [
                ScriptSegmentContent(
                    segment_type="payoff",
                    narration=(
                        "Put those pieces together and the simple version "
                        "stops holding up."
                    ),
                    purpose="Resolve the question.",
                    claim_ids=[],
                    duration_seconds=12.0,
                ),
                ScriptSegmentContent(
                    segment_type="conclusion",
                    narration=(
                        "The takeaway: look for the system behind the headline."
                    ),
                    purpose="Close with a memorable perspective.",
                    claim_ids=[],
                    duration_seconds=9.0,
                ),
            ]
        )
        content = ScriptContent(
            title=subject,
            hook=hook,
            narrative_arc=(
                "A curiosity hook, a fast setup, a claim-by-claim reveal, "
                "a payoff, and a takeaway."
            ),
            segments=segments,
        )
        return _assemble(
            content,
            package,
            format,
            target_seconds,
            {claim.claim_id for claim in eligible},
        )
