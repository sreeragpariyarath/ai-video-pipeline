from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.research_schemas import ResearchClaim, ResearchPackage
from orchestrator.script_schemas import (
    DURATION_TOLERANCE_SECONDS,
    ScriptSegment,
    VideoScript,
    validate_claim_references,
)


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def segment_dict(**overrides) -> dict:
    data = {
        "segment_id": "seg-1",
        "order": 1,
        "segment_type": "hook",
        "narration": "Streaming is cheap. Then the bill arrives.",
        "duration_seconds": 3.0,
        "claim_ids": [],
        "purpose": "Open the curiosity gap.",
    }
    data.update(overrides)
    return data


def segment_list() -> list[dict]:
    return [
        segment_dict(),
        segment_dict(
            segment_id="seg-2",
            order=2,
            segment_type="explanation",
            narration="The advertised price is only the entry tier.",
            duration_seconds=7.0,
            claim_ids=["cl-1"],
            purpose="Explain the pricing ladder.",
        ),
    ]


def script_dict(**overrides) -> dict:
    data = {
        "script_id": "script-1",
        "research_id": "res-1",
        "format": "short",
        "target_seconds": 40.0,
        "planned_seconds": 10.0,
        "title": "The streaming price trick",
        "hook": "Streaming is cheap.",
        "narrative_arc": "Curiosity gap, pricing reveal, takeaway",
        "segments": segment_list(),
        "word_count": 15,
        "created_at": NOW,
    }
    data.update(overrides)
    return data


def make_script(**overrides) -> VideoScript:
    return VideoScript.model_validate(script_dict(**overrides))


def make_segment(**overrides) -> ScriptSegment:
    return ScriptSegment.model_validate(segment_dict(**overrides))


def make_package(claim_ids=("cl-1",), research_id="res-1") -> ResearchPackage:
    return ResearchPackage(
        research_id=research_id,
        topic="Why is Netflix cheaper than cable TV?",
        created_at=NOW,
        summary="Research summary.",
        claims=[
            ResearchClaim(
                claim_id=claim_id,
                statement=f"Verified statement for {claim_id}.",
                category="financial",
                importance=0.5,
                confidence=0.9,
                verification_status="supported",
            )
            for claim_id in claim_ids
        ],
    )


def test_valid_script_constructs():
    script = make_script()
    assert script.format == "short"
    assert script.planned_seconds == 10.0
    assert script.word_count == 15
    assert [s.order for s in script.segments] == [1, 2]
    assert script.segments[1].claim_ids == ["cl-1"]


def test_defaults_and_metadata():
    script = make_script()
    assert isinstance(script.created_at, datetime)
    assert script.segments[0].claim_ids == []


def test_round_trips_through_model_dump():
    script = make_script()
    assert VideoScript.model_validate(script.model_dump()) == script


def test_all_formats_accepted():
    for video_format in ("short", "mid_form", "long_form"):
        assert make_script(format=video_format).format == video_format


def test_format_duration_guidance_is_not_enforced():
    # A short can be trimmed or expanded during development; 10s must not fail.
    script = make_script(format="short", target_seconds=10.0)
    assert script.planned_seconds == 10.0


def test_invalid_format_rejected():
    with pytest.raises(ValidationError):
        make_script(format="reel")


def test_valid_segment_types_accepted():
    for segment_type in (
        "setup",
        "context",
        "explanation",
        "revelation",
        "transition",
        "payoff",
        "conclusion",
    ):
        assert make_segment(segment_type=segment_type).segment_type == segment_type


def test_invalid_segment_type_rejected():
    with pytest.raises(ValidationError):
        make_segment(segment_type="montage")


def test_duplicate_segment_ids_rejected():
    segments = segment_list()
    segments[1]["segment_id"] = segments[0]["segment_id"]
    with pytest.raises(ValidationError, match="duplicate segment IDs"):
        make_script(segments=segments)


@pytest.mark.parametrize("orders", [[1, 3], [2, 1], [1, 1], [0, 1]])
def test_non_sequential_order_rejected(orders):
    segments = segment_list()
    for segment, order in zip(segments, orders):
        segment["order"] = order
    with pytest.raises(ValidationError):
        make_script(segments=segments)


def test_order_must_be_integer():
    with pytest.raises(ValidationError):
        make_segment(order=1.5)


@pytest.mark.parametrize("order", [0, -1, True])
def test_invalid_order_values_rejected(order):
    with pytest.raises(ValidationError):
        make_segment(order=order)


def test_empty_segments_rejected():
    with pytest.raises(ValidationError):
        make_script(segments=[])


def test_opening_segment_must_be_hook():
    segments = segment_list()
    segments[0]["segment_type"] = "setup"
    with pytest.raises(ValidationError, match="opening segment must have type 'hook'"):
        make_script(segments=segments)


def test_later_hook_rejected():
    segments = segment_list()
    segments[1]["segment_type"] = "hook"
    with pytest.raises(ValidationError, match="only the opening segment"):
        make_script(segments=segments)


@pytest.mark.parametrize(
    "field",
    [
        "script_id",
        "research_id",
        "title",
        "hook",
        "narrative_arc",
    ],
)
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_required_text_rejected(field, value):
    with pytest.raises(ValidationError):
        make_script(**{field: value})


@pytest.mark.parametrize(
    "field",
    ["segment_id", "narration", "purpose"],
)
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_segment_text_rejected(field, value):
    with pytest.raises(ValidationError):
        make_segment(**{field: value})


@pytest.mark.parametrize("value", [0, -1, True, False, float("nan"), float("inf")])
def test_invalid_segment_duration_rejected(value):
    with pytest.raises(ValidationError):
        make_segment(duration_seconds=value)


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_planned_seconds_rejected(value):
    with pytest.raises(ValidationError):
        make_script(planned_seconds=value)


@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_target_seconds_rejected(value):
    with pytest.raises(ValidationError):
        make_script(target_seconds=value)


def test_word_count_must_match_narration():
    with pytest.raises(ValidationError, match="word_count must match"):
        make_script(word_count=99)


def test_word_count_rejects_bool_and_negative():
    for value in (True, -1):
        with pytest.raises(ValidationError):
            make_script(word_count=value)


def test_planned_seconds_must_match_segments():
    with pytest.raises(ValidationError, match="planned_seconds"):
        make_script(planned_seconds=12.0)


def test_planned_seconds_tolerance_accepts_float_noise():
    script = make_script(planned_seconds=10.0 + DURATION_TOLERANCE_SECONDS)
    assert abs(script.planned_seconds - 10.0) <= DURATION_TOLERANCE_SECONDS


def test_planned_seconds_beyond_tolerance_rejected():
    with pytest.raises(ValidationError, match="planned_seconds"):
        make_script(planned_seconds=10.0 + DURATION_TOLERANCE_SECONDS * 2)


def test_hook_must_match_opening_narration():
    with pytest.raises(ValidationError, match="start with the hook"):
        make_script(hook="This is a different hook.")


def test_opening_narration_may_continue_after_hook():
    script = make_script(hook="Streaming is cheap.")
    assert script.segments[0].narration.startswith(script.hook)


def test_exact_hook_narration_accepted():
    segments = segment_list()
    segments[0]["narration"] = "Streaming is cheap."
    script = make_script(
        hook="Streaming is cheap.", segments=segments, word_count=11
    )
    assert script.segments[0].narration == script.hook


def test_duplicate_claim_ids_within_segment_rejected():
    with pytest.raises(ValidationError, match="claim_ids must not contain duplicates"):
        make_segment(claim_ids=["cl-1", "cl-1"])


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_claim_id_rejected(value):
    with pytest.raises(ValidationError):
        make_segment(claim_ids=[value])


def test_same_claim_can_be_referenced_by_multiple_segments():
    segments = segment_list()
    segments[0]["claim_ids"] = ["cl-1"]
    script = make_script(segments=segments)
    assert script.segments[0].claim_ids == ["cl-1"]
    assert script.segments[1].claim_ids == ["cl-1"]


def test_known_claim_references_accepted():
    script = make_script()
    validate_claim_references(script, make_package(["cl-1"]))


def test_matching_research_ids_accepted():
    script = make_script()
    validate_claim_references(script, make_package(["cl-1"], research_id="res-1"))


def test_mismatched_research_id_rejected():
    # The cited claim exists in both packages; only the research IDs differ.
    script = make_script()
    package = make_package(["cl-1"], research_id="res-other")
    with pytest.raises(ValueError, match="does not match") as excinfo:
        validate_claim_references(script, package)
    assert "res-1" in str(excinfo.value)
    assert "res-other" in str(excinfo.value)


def test_script_without_claim_references_accepted():
    segments = segment_list()
    segments[1]["claim_ids"] = []
    validate_claim_references(make_script(segments=segments), make_package([]))


def test_unknown_claim_reference_rejected():
    segments = segment_list()
    segments[1]["claim_ids"] = ["cl-9"]
    with pytest.raises(ValueError, match="unknown claim IDs: cl-9"):
        validate_claim_references(make_script(segments=segments), make_package(["cl-1"]))


def test_multiple_errors_reported_together():
    segments = segment_list()
    segments[0]["segment_type"] = "setup"
    segments[1]["order"] = 5
    with pytest.raises(ValidationError) as excinfo:
        make_script(segments=segments, word_count=1)
    message = str(excinfo.value)
    assert "segment order" in message
    assert "opening segment" in message
    assert "word_count" in message
