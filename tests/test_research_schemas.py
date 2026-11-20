import copy
import math
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from orchestrator.research_schemas import (
    ClaimEvidence,
    ResearchClaim,
    ResearchPackage,
    ResearchSource,
    StoryAngle,
)


SOURCE = {
    "source_id": "src-1",
    "title": "Example industry report",
    "url": "https://example.com/report",
    "domain": "example.com",
    "source_type": "primary",
    "retrieved_at": "2026-11-20T09:00:00+00:00",
}
EVIDENCE = {
    "source_id": "src-1",
    "excerpt": "Average prices fell 20% between 2020 and 2025.",
    "relationship": "supports",
}
CLAIM = {
    "claim_id": "clm-1",
    "statement": "Average prices fell 20% between 2020 and 2025.",
    "category": "financial",
    "importance": 0.8,
    "confidence": 0.9,
    "verification_status": "supported",
    "evidence": [EVIDENCE],
}
ANGLE = {
    "title": "The price drop nobody noticed",
    "premise": "Open on the falling price, then reveal the cause.",
    "why_interesting": "Contradicts the common belief that prices always rise.",
    "supporting_claim_ids": ["clm-1"],
}
PACKAGE = {
    "research_id": "res-1",
    "topic": "Why did prices fall?",
    "created_at": "2026-11-20T09:30:00+00:00",
    "summary": "Prices fell because supply outpaced demand.",
    "research_questions": ["What drove the price drop?"],
    "sources": [SOURCE],
    "claims": [CLAIM],
    "story_angles": [ANGLE],
    "unresolved_questions": ["Will the trend continue?"],
}


def make_package(**overrides) -> ResearchPackage:
    return ResearchPackage.model_validate({**PACKAGE, **overrides})


def set_path(payload: dict, path: str, value) -> dict:
    payload = copy.deepcopy(payload)
    keys = path.split(".")
    target = payload
    for key in keys[:-1]:
        target = target[int(key)] if key.isdigit() else target[key]
    last = keys[-1]
    if last.isdigit():
        target[int(last)] = value
    else:
        target[last] = value
    return payload


def test_valid_package_constructs_and_round_trips():
    package = make_package()
    assert package.schema_version == 1
    assert package.sources[0].published_date is None
    assert isinstance(package.created_at, datetime)
    assert isinstance(package.sources[0].retrieved_at, datetime)
    restored = ResearchPackage.model_validate_json(package.model_dump_json())
    assert restored == package


def test_minimal_package_with_empty_collections_is_valid():
    package = ResearchPackage.model_validate(
        {
            "research_id": "res-min",
            "topic": "A topic",
            "created_at": "2026-11-20T09:30:00+00:00",
            "summary": "Nothing found yet.",
        }
    )
    assert package.sources == []
    assert package.claims == []
    assert package.story_angles == []
    assert package.research_questions == []
    assert package.unresolved_questions == []


@pytest.mark.parametrize(
    "path",
    [
        "research_id",
        "topic",
        "summary",
        "sources.0.source_id",
        "sources.0.title",
        "sources.0.domain",
        "claims.0.claim_id",
        "claims.0.statement",
        "claims.0.evidence.0.source_id",
        "claims.0.evidence.0.excerpt",
        "story_angles.0.title",
        "story_angles.0.premise",
        "story_angles.0.why_interesting",
        "research_questions.0",
        "unresolved_questions.0",
    ],
)
@pytest.mark.parametrize("bad", ["", "   "])
def test_required_strings_reject_empty_and_whitespace(path, bad):
    with pytest.raises(ValidationError):
        ResearchPackage.model_validate(set_path(PACKAGE, path, bad))


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/x", "javascript:alert(1)", "not a url", "http://", "https://"],
)
def test_invalid_urls_rejected(url):
    with pytest.raises(ValidationError):
        ResearchSource.model_validate({**SOURCE, "url": url})


@pytest.mark.parametrize("url", ["http://example.com/x", "https://example.com/x?q=1#frag"])
def test_http_and_https_urls_accepted(url):
    assert ResearchSource.model_validate({**SOURCE, "url": url}).url == url


@pytest.mark.parametrize("value", ["primary", "secondary", "informal"])
def test_valid_source_types(value):
    assert ResearchSource.model_validate({**SOURCE, "source_type": value}).source_type == value


@pytest.mark.parametrize(
    "value",
    ["financial", "technical", "historical", "scientific", "business", "general"],
)
def test_valid_claim_categories(value):
    claim = ResearchClaim.model_validate({**CLAIM, "category": value, "evidence": []})
    assert claim.category == value


@pytest.mark.parametrize("value", ["supports", "contradicts", "contextualizes"])
def test_valid_evidence_relationships(value):
    evidence = ClaimEvidence.model_validate({**EVIDENCE, "relationship": value})
    assert evidence.relationship == value


@pytest.mark.parametrize("value", ["unverified", "supported", "contradicted", "disputed"])
def test_valid_verification_statuses(value):
    claim = ResearchClaim.model_validate(
        {**CLAIM, "verification_status": value, "evidence": []}
    )
    assert claim.verification_status == value


@pytest.mark.parametrize(
    ("model", "payload", "field", "bad"),
    [
        (ResearchSource, SOURCE, "source_type", "blog"),
        (ResearchClaim, CLAIM, "category", "gossip"),
        (ResearchClaim, CLAIM, "verification_status", "probably-true"),
        (ClaimEvidence, EVIDENCE, "relationship", "refutes"),
    ],
)
def test_invalid_enum_values_rejected(model, payload, field, bad):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: bad})


@pytest.mark.parametrize("field", ["importance", "confidence"])
@pytest.mark.parametrize("value", [0, 1, 0.5, 0.0, 1.0])
def test_numeric_bounds_accept_valid_values(field, value):
    claim = ResearchClaim.model_validate({**CLAIM, field: value, "evidence": []})
    assert getattr(claim, field) == float(value)


@pytest.mark.parametrize("field", ["importance", "confidence"])
@pytest.mark.parametrize(
    "value", [True, False, -0.1, 1.5, math.nan, math.inf, -math.inf, "high"]
)
def test_numeric_bounds_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        ResearchClaim.model_validate({**CLAIM, field: value, "evidence": []})


def test_confidence_and_verification_status_are_independent():
    claim = ResearchClaim.model_validate(
        {
            **CLAIM,
            "confidence": 0.95,
            "verification_status": "unverified",
            "evidence": [],
        }
    )
    assert claim.confidence == 0.95
    assert claim.verification_status == "unverified"
    assert claim.evidence == []


def test_timestamps_parse_and_reject_garbage():
    package = make_package()
    assert package.created_at.year == 2026
    with pytest.raises(ValidationError):
        make_package(created_at="yesterday")
    with pytest.raises(ValidationError):
        ResearchSource.model_validate({**SOURCE, "retrieved_at": "last week"})
    with pytest.raises(ValidationError):
        ResearchSource.model_validate({k: v for k, v in SOURCE.items() if k != "retrieved_at"})


def test_published_date_is_optional_and_typed():
    assert ResearchSource.model_validate(SOURCE).published_date is None
    source = ResearchSource.model_validate({**SOURCE, "published_date": "2025-06-01"})
    assert source.published_date == date(2025, 6, 1)
    with pytest.raises(ValidationError):
        ResearchSource.model_validate({**SOURCE, "published_date": "someday"})


@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (ResearchSource, SOURCE, "description"),
        (ClaimEvidence, EVIDENCE, "notes"),
    ],
)
def test_optional_text_fields(model, payload, field):
    assert model.model_validate(payload).model_dump()[field] is None
    with pytest.raises(ValidationError):
        model.model_validate({**payload, field: "   "})
    assert model.model_validate({**payload, field: " useful note "}).model_dump()[field] == "useful note"


def test_caveats_reject_whitespace_entries():
    with pytest.raises(ValidationError):
        ResearchClaim.model_validate({**CLAIM, "caveats": ["ok", "   "]})


def test_wrong_schema_version_rejected():
    with pytest.raises(ValidationError):
        make_package(schema_version=2)


def test_evidence_must_reference_known_source():
    payload = set_path(PACKAGE, "claims.0.evidence.0.source_id", "src-missing")
    with pytest.raises(ValidationError, match="unknown source ID: src-missing"):
        ResearchPackage.model_validate(payload)


def test_story_angle_must_reference_known_claims():
    payload = set_path(PACKAGE, "story_angles.0.supporting_claim_ids", ["clm-missing"])
    with pytest.raises(ValidationError, match="unknown claim ID: clm-missing"):
        ResearchPackage.model_validate(payload)


def test_duplicate_source_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate source ID: src-1"):
        make_package(sources=[SOURCE, {**SOURCE, "title": "Different title"}])


def test_duplicate_claim_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate claim ID: clm-1"):
        make_package(claims=[CLAIM, {**CLAIM, "statement": "Different statement"}])


def test_all_cross_reference_problems_are_collected():
    payload = set_path(PACKAGE, "claims.0.evidence.0.source_id", "src-missing")
    payload = set_path(payload, "story_angles.0.supporting_claim_ids", ["clm-missing"])
    payload["sources"] = [SOURCE, dict(SOURCE)]
    with pytest.raises(ValidationError) as excinfo:
        ResearchPackage.model_validate(payload)
    message = str(excinfo.value)
    assert "unknown source ID: src-missing" in message
    assert "unknown claim ID: clm-missing" in message
    assert "duplicate source ID: src-1" in message


def test_valid_cross_references_pass():
    second_source = {**SOURCE, "source_id": "src-2", "url": "https://other.example.com/a"}
    second_claim = {
        **CLAIM,
        "claim_id": "clm-2",
        "statement": "A second claim.",
        "evidence": [
            {**EVIDENCE, "source_id": "src-2", "relationship": "contradicts"},
            {**EVIDENCE, "source_id": "src-1", "relationship": "contextualizes"},
        ],
    }
    package = make_package(
        sources=[SOURCE, second_source],
        claims=[CLAIM, second_claim],
        story_angles=[
            ANGLE,
            {**ANGLE, "title": "Both sides", "supporting_claim_ids": ["clm-1", "clm-2"]},
        ],
    )
    assert len(package.claims[1].evidence) == 2


def test_angle_without_supporting_claims_is_allowed():
    angle = StoryAngle.model_validate(
        {k: v for k, v in ANGLE.items() if k != "supporting_claim_ids"}
    )
    assert angle.supporting_claim_ids == []
    make_package(story_angles=[angle.model_dump()])


def test_evidence_source_id_is_checked_against_package_not_just_shape():
    evidence = ClaimEvidence.model_validate(EVIDENCE)
    claim = ResearchClaim.model_validate({**CLAIM, "evidence": [evidence.model_dump()]})
    with pytest.raises(ValidationError, match="unknown source ID"):
        ResearchPackage.model_validate(
            {
                "research_id": "res-x",
                "topic": "A topic",
                "created_at": "2026-11-20T09:30:00+00:00",
                "summary": "Summary.",
                "sources": [],
                "claims": [claim.model_dump()],
            }
        )