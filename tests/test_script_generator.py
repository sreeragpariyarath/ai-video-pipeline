from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from orchestrator.gemini import GeminiError
from orchestrator.research_schemas import (
    ClaimEvidence,
    ResearchClaim,
    ResearchPackage,
    ResearchSource,
)
from orchestrator.script_generator import (
    INVALID_OUTPUT_MESSAGE,
    NO_SUPPORTED_CLAIMS_MESSAGE,
    REQUEST_FAILED_MESSAGE,
    TARGET_TOO_SHORT_MESSAGE,
    MockScriptGenerator,
    ScriptGenerationError,
    ScriptGenerator,
)
from orchestrator.script_schemas import MAX_SCRIPT_SEGMENTS, ScriptContent, VideoScript


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
TOPIC = "Why is Netflix cheaper than cable TV?"


def make_source(index: int = 1) -> ResearchSource:
    domain = f"source{index}.example.com"
    return ResearchSource(
        source_id=f"src-{index}",
        title=f"Source {index}",
        url=f"https://{domain}/article",
        domain=domain,
        source_type="secondary",
        retrieved_at=NOW,
    )


def make_claim(
    claim_id: str = "cl-1",
    status: str = "supported",
    *,
    with_evidence: bool = True,
    statement: str | None = None,
) -> ResearchClaim:
    return ResearchClaim(
        claim_id=claim_id,
        statement=statement or f"Supported fact number {claim_id} about pricing.",
        category="financial",
        importance=0.5,
        confidence=0.9 if status == "supported" else 0.0,
        verification_status=status,
        evidence=(
            [
                ClaimEvidence(
                    source_id="src-1",
                    excerpt=f"Evidence backing {claim_id} about pricing.",
                    relationship="supports",
                )
            ]
            if with_evidence
            else []
        ),
    )


def make_package(
    claims=None, *, research_id: str = "res-1", summary: str | None = None
) -> ResearchPackage:
    return ResearchPackage(
        research_id=research_id,
        topic=TOPIC,
        created_at=NOW,
        summary=summary or "Entry tiers advertise lower prices than cable bundles.",
        sources=[make_source(1)],
        claims=(
            [make_claim()]
            if claims is None
            else claims
        ),
    )


def segment_dict(
    segment_type: str,
    narration: str,
    purpose: str = "Move the story forward.",
    claim_ids=(),
    duration: float = 1.0,
) -> dict:
    return {
        "segment_type": segment_type,
        "narration": narration,
        "purpose": purpose,
        "claim_ids": list(claim_ids),
        "duration_seconds": duration,
    }


def content_dict(segments=None, **overrides) -> dict:
    data = {
        "title": "The streaming price trick",
        "hook": "Streaming looks cheaper. The bill says otherwise.",
        "narrative_arc": (
            "A cheap-looking price leads to a hidden-cost reveal and a takeaway."
        ),
        "segments": segments
        if segments is not None
        else [
            segment_dict(
                "hook",
                "Streaming looks cheaper. The bill says otherwise.",
                "Open the gap.",
                duration=4.0,
            ),
            segment_dict(
                "setup",
                "The headline price is only the entry point.",
                "Set up the comparison.",
                duration=6.0,
            ),
            segment_dict(
                "explanation",
                "Entry tiers advertise a low monthly rate.",
                "Ground the claim.",
                claim_ids=["cl-1"],
                duration=10.0,
            ),
            segment_dict(
                "payoff",
                "Add the extras and the cheap option stops being cheap.",
                "Resolve the gap.",
                duration=6.0,
            ),
            segment_dict(
                "conclusion",
                "The headline price was never the whole price.",
                "Close with the takeaway.",
                duration=4.0,
            ),
        ],
    }
    data.update(overrides)
    return data


def make_content(segments=None, **overrides) -> ScriptContent:
    return ScriptContent.model_validate(content_dict(segments=segments, **overrides))


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_json(self, *, system, prompt, schema, temperature=0.4):
        self.calls.append(
            {
                "system": system,
                "prompt": prompt,
                "schema": schema,
                "temperature": temperature,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def make_generator(response=None, error=None):
    client = FakeClient(response or make_content(), error)
    return ScriptGenerator(client), client


def test_valid_generation_produces_script():
    generator, client = make_generator()
    script = generator.generate(make_package(), format="short", target_seconds=30.0)

    assert isinstance(script, VideoScript)
    assert script.research_id == "res-1"
    assert script.format == "short"
    assert script.target_seconds == 30.0
    assert script.planned_seconds == pytest.approx(30.0)
    assert sum(s.duration_seconds for s in script.segments) == pytest.approx(
        script.planned_seconds
    )
    assert all(s.duration_seconds > 0 for s in script.segments)
    assert script.script_id.startswith("script-")
    assert [s.segment_id for s in script.segments] == [
        "seg-01",
        "seg-02",
        "seg-03",
        "seg-04",
        "seg-05",
    ]
    assert [s.order for s in script.segments] == [1, 2, 3, 4, 5]
    assert script.word_count == sum(
        len(s.narration.split()) for s in script.segments
    )
    assert script.segments[0].narration == script.hook
    assert script.segments[2].claim_ids == ["cl-1"]
    assert client.calls[0]["schema"] is ScriptContent
    assert client.calls[0]["temperature"] == 0.7


def test_app_owned_fields_are_not_taken_from_model():
    data = content_dict()
    data.update(
        {
            "script_id": "evil-id",
            "research_id": "evil-research",
            "word_count": 1,
            "planned_seconds": 1.0,
            "format": "long_form",
        }
    )
    generator, _ = make_generator(ScriptContent.model_validate(data))
    script = generator.generate(make_package(), format="short", target_seconds=30.0)

    assert script.script_id != "evil-id"
    assert script.research_id == "res-1"
    assert script.format == "short"
    assert script.word_count == sum(
        len(s.narration.split()) for s in script.segments
    )
    assert script.planned_seconds == pytest.approx(30.0)


def test_prompt_includes_supported_and_excluded_claims():
    package = make_package(
        [make_claim("cl-1"), make_claim("cl-2", "unverified")]
    )
    generator, client = make_generator()
    generator.generate(package, format="short", target_seconds=30.0)

    prompt = client.calls[0]["prompt"]
    assert TOPIC in prompt
    assert "SUPPORTED CLAIMS" in prompt
    assert "cl-1" in prompt
    assert "NOT USABLE AS FACTS" in prompt
    assert "cl-2" in prompt
    assert "unverified" in prompt
    assert "Evidence (source1.example.com)" in prompt


def test_short_target_uses_short_segment_hint():
    generator, client = make_generator()
    generator.generate(make_package(), format="short", target_seconds=30.0)
    assert "Use 4-8 segments" in client.calls[0]["prompt"]

    generator, client = make_generator()
    generator.generate(make_package(), format="mid_form", target_seconds=240.0)
    assert "Use 6-12 segments" in client.calls[0]["prompt"]


@pytest.mark.parametrize("status", ["unverified", "contradicted", "disputed"])
def test_ineligible_claim_citation_rejected(status):
    package = make_package([make_claim("cl-1"), make_claim("cl-2", status)])
    segments = content_dict()["segments"]
    segments[2]["claim_ids"] = ["cl-2"]
    generator, _ = make_generator(make_content(segments=segments))

    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(package, format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_unknown_claim_id_rejected():
    segments = content_dict()["segments"]
    segments[2]["claim_ids"] = ["cl-99"]
    generator, _ = make_generator(make_content(segments=segments))

    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_script_without_citations_rejected():
    segments = content_dict()["segments"]
    for segment in segments:
        segment["claim_ids"] = []
    generator, _ = make_generator(make_content(segments=segments))

    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_supported_claim_without_evidence_is_ineligible():
    package = make_package(
        [make_claim("cl-1", with_evidence=False), make_claim("cl-2")]
    )
    segments = content_dict()["segments"]
    segments[2]["claim_ids"] = ["cl-1"]
    generator, _ = make_generator(make_content(segments=segments))

    with pytest.raises(ScriptGenerationError, match="invalid script content"):
        generator.generate(package, format="short", target_seconds=30.0)


def test_no_usable_claims_fails_before_gemini():
    package = make_package([make_claim("cl-1", "unverified")])
    generator, client = make_generator()

    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(package, format="short", target_seconds=30.0)
    assert str(excinfo.value) == NO_SUPPORTED_CLAIMS_MESSAGE
    assert client.calls == []


@pytest.mark.parametrize("video_format", ["reel", "", "SHORT", None, 1])
def test_invalid_format_rejected(video_format):
    generator, client = make_generator()
    with pytest.raises(ValueError, match="format must be"):
        generator.generate(
            make_package(), format=video_format, target_seconds=30.0
        )
    assert client.calls == []


@pytest.mark.parametrize(
    "target", [0, -1, True, False, float("nan"), float("inf"), "30", None]
)
def test_invalid_target_duration_rejected(target):
    generator, client = make_generator()
    with pytest.raises(ValueError, match="finite number greater than 0"):
        generator.generate(make_package(), format="short", target_seconds=target)
    assert client.calls == []


def test_invalid_package_rejected():
    generator, _ = make_generator()
    with pytest.raises(ValueError, match="ResearchPackage"):
        generator.generate({"topic": TOPIC}, format="short", target_seconds=30.0)


def test_integer_target_accepted():
    generator, _ = make_generator()
    script = generator.generate(make_package(), format="short", target_seconds=30)
    assert script.target_seconds == 30.0


def test_hook_must_match_opening_narration():
    generator, _ = make_generator(make_content(hook="A different opening line."))
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_opening_segment_must_be_hook():
    segments = content_dict()["segments"]
    segments[0]["segment_type"] = "setup"
    generator, _ = make_generator(make_content(segments=segments))
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_post_validation_empty_segment_list_rejected():
    content = ScriptContent.model_construct(
        title="Title",
        hook="Hook line.",
        narrative_arc="Arc.",
        segments=[],
    )
    generator, _ = make_generator(content)
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_gemini_schema_error_is_sanitized():
    secret = "SECRET-MODEL-OUTPUT"
    generator, _ = make_generator(
        error=GeminiError(
            f"Gemini returned JSON that does not match ScriptContent: {secret}"
        )
    )
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE
    assert secret not in str(excinfo.value)


def test_gemini_request_error_is_sanitized():
    secret = "AIza-SECRET-KEY"
    generator, _ = make_generator(
        error=GeminiError(f"Gemini request failed: 401 for key {secret}")
    )
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == REQUEST_FAILED_MESSAGE
    assert secret not in str(excinfo.value)


def test_gemini_failure_does_not_fall_back_to_mock():
    generator, _ = make_generator(error=GeminiError("Gemini request failed: 500"))
    with pytest.raises(ScriptGenerationError):
        generator.generate(make_package(), format="short", target_seconds=30.0)


def test_segment_durations_scale_to_target():
    segments = content_dict()["segments"]
    for segment in segments:
        segment["duration_seconds"] = 1.0
    generator, _ = make_generator(make_content(segments=segments))
    script = generator.generate(make_package(), format="short", target_seconds=10.0)

    assert script.planned_seconds == pytest.approx(10.0)
    assert sum(s.duration_seconds for s in script.segments) == pytest.approx(10.0)
    assert all(s.duration_seconds > 0 for s in script.segments)


@pytest.mark.parametrize("target", [17.3, 0.07, 359.99])
def test_fractional_targets_sum_correctly(target):
    generator, _ = make_generator()
    script = generator.generate(make_package(), format="short", target_seconds=target)
    assert sum(s.duration_seconds for s in script.segments) == pytest.approx(
        script.planned_seconds
    )
    assert script.planned_seconds == pytest.approx(target, abs=0.01)


def test_target_too_short_for_segments_rejected():
    generator, _ = make_generator()
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=0.02)
    assert str(excinfo.value) == TARGET_TOO_SHORT_MESSAGE


def test_content_schema_rejects_too_few_segments():
    with pytest.raises(ValidationError):
        make_content(segments=content_dict()["segments"][:2])


def test_content_schema_rejects_too_many_segments():
    segments = [
        segment_dict("explanation", f"Line {index}.") for index in range(33)
    ]
    with pytest.raises(ValidationError):
        make_content(segments=segments)


def test_content_schema_rejects_invalid_durations():
    for value in (0, -1, True, float("nan"), float("inf")):
        segments = content_dict()["segments"]
        segments[2]["duration_seconds"] = value
        with pytest.raises(ValidationError):
            make_content(segments=segments)


def test_content_schema_requires_claim_ids():
    data = content_dict()
    del data["segments"][2]["claim_ids"]
    with pytest.raises(ValidationError):
        ScriptContent.model_validate(data)


def test_mock_generation_produces_valid_script():
    package = make_package(
        [make_claim("cl-1"), make_claim("cl-2"), make_claim("cl-3", "unverified")]
    )
    script = MockScriptGenerator().generate(
        package, format="short", target_seconds=35.0
    )

    assert isinstance(script, VideoScript)
    assert script.format == "short"
    assert script.target_seconds == 35.0
    assert script.planned_seconds == pytest.approx(35.0)
    assert sum(s.duration_seconds for s in script.segments) == pytest.approx(35.0)
    assert script.word_count == sum(
        len(s.narration.split()) for s in script.segments
    )
    assert script.segments[0].narration.startswith(script.hook)
    cited = {cid for s in script.segments for cid in s.claim_ids}
    assert cited <= {"cl-1", "cl-2"}
    assert cited


@pytest.mark.parametrize(
    "video_format,target",
    [("short", 45.0), ("mid_form", 240.0), ("long_form", 480.0)],
)
def test_mock_respects_format_and_duration(video_format, target):
    package = make_package([make_claim(f"cl-{i}") for i in range(1, 6)])
    script = MockScriptGenerator().generate(
        package, format=video_format, target_seconds=target
    )
    assert script.format == video_format
    assert script.target_seconds == target
    assert script.planned_seconds == pytest.approx(target, abs=0.01)


def test_mock_output_is_deterministic():
    package = make_package([make_claim("cl-1"), make_claim("cl-2")])
    first = MockScriptGenerator().generate(
        package, format="short", target_seconds=40.0
    )
    second = MockScriptGenerator().generate(
        package, format="short", target_seconds=40.0
    )
    excluded = {"script_id", "created_at"}
    assert first.model_dump(exclude=excluded) == second.model_dump(exclude=excluded)


def test_mock_requires_supported_claims():
    package = make_package([make_claim("cl-1", "contradicted")])
    with pytest.raises(ScriptGenerationError) as excinfo:
        MockScriptGenerator().generate(
            package, format="short", target_seconds=30.0
        )
    assert str(excinfo.value) == NO_SUPPORTED_CLAIMS_MESSAGE


def test_mock_validates_inputs():
    with pytest.raises(ValueError, match="format must be"):
        MockScriptGenerator().generate(
            make_package(), format="reel", target_seconds=30.0
        )
    with pytest.raises(ValueError, match="finite number greater than 0"):
        MockScriptGenerator().generate(
            make_package(), format="short", target_seconds=0
        )


def test_mock_never_cites_ineligible_claims():
    package = make_package(
        [
            make_claim("cl-1"),
            make_claim("cl-2", "unverified"),
            make_claim("cl-3", "disputed"),
        ]
    )
    script = MockScriptGenerator().generate(
        package, format="short", target_seconds=60.0
    )
    cited = {cid for s in script.segments for cid in s.claim_ids}
    assert cited == {"cl-1"}


def test_mock_fails_when_target_too_short_for_segments():
    package = make_package([make_claim("cl-1"), make_claim("cl-2")])
    with pytest.raises(ScriptGenerationError) as excinfo:
        MockScriptGenerator().generate(
            package, format="short", target_seconds=0.04
        )
    assert str(excinfo.value) == TARGET_TOO_SHORT_MESSAGE


def test_prompt_contains_security_note():
    generator, client = make_generator()
    generator.generate(make_package(), format="short", target_seconds=30.0)
    assert "SECURITY" in client.calls[0]["prompt"]


def test_duration_allocation_preserves_relative_weights():
    segments = content_dict()["segments"]
    for segment, duration in zip(segments, [1.0, 1.0, 2.0, 2.0, 4.0]):
        segment["duration_seconds"] = duration
    generator, _ = make_generator(make_content(segments=segments))
    script = generator.generate(make_package(), format="short", target_seconds=40.0)

    durations = [s.duration_seconds for s in script.segments]
    assert durations[0] == pytest.approx(durations[1])
    assert durations[2] == pytest.approx(durations[0] * 2, abs=0.01)
    assert durations[4] == pytest.approx(durations[0] * 4, abs=0.02)


def test_mock_hook_uses_topic_question():
    script = MockScriptGenerator().generate(
        make_package(), format="short", target_seconds=30.0
    )
    assert script.hook == TOPIC
    assert script.segments[0].narration.startswith(script.hook)


def test_mock_long_form_stays_within_segment_bounds():
    package = make_package([make_claim(f"cl-{i}") for i in range(1, 41)])
    script = MockScriptGenerator().generate(
        package, format="long_form", target_seconds=600.0
    )
    assert len(script.segments) <= MAX_SCRIPT_SEGMENTS
    assert script.segments[-1].segment_type == "conclusion"
    assert all(s.duration_seconds > 0 for s in script.segments)


def test_prompt_includes_format_guidance():
    generator, client = make_generator()
    generator.generate(make_package(), format="short", target_seconds=30.0)
    assert "One idea, one payoff" in client.calls[0]["prompt"]

    generator, client = make_generator()
    generator.generate(make_package(), format="long_form", target_seconds=480.0)
    assert "Several layered reveals" in client.calls[0]["prompt"]


@pytest.mark.parametrize("leak", ["cl-1", "src-2", "ev-3", "CL-1"])
def test_claim_id_leak_in_narration_rejected(leak):
    segments = content_dict()["segments"]
    segments[1]["narration"] = f"The part tagged {leak} explains it."
    generator, _ = make_generator(make_content(segments=segments))
    with pytest.raises(ScriptGenerationError) as excinfo:
        generator.generate(make_package(), format="short", target_seconds=30.0)
    assert str(excinfo.value) == INVALID_OUTPUT_MESSAGE


def test_ordinary_numbers_in_narration_accepted():
    segments = content_dict()["segments"]
    segments[1]["narration"] = "The price fell to 3 dollars in 2019."
    generator, _ = make_generator(make_content(segments=segments))
    script = generator.generate(make_package(), format="short", target_seconds=30.0)
    assert "3 dollars in 2019" in script.segments[1].narration
