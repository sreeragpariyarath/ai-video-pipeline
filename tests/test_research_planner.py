import copy
import math

import pytest
from pydantic import ValidationError

from orchestrator.gemini import GeminiClient
from orchestrator.prompts import RESEARCH_PLANNING_SYSTEM, research_planning_prompt
from orchestrator.research_planner import MockResearchPlanner, ResearchPlanner
from orchestrator.research_schemas import ResearchPlan

from conftest import make_response


QUESTION = {
    "question_id": "q1",
    "question": "What mechanism drives the price gap?",
    "reason": "The core explanation of the video.",
    "priority": "high",
    "expected_evidence": "Official pricing documentation.",
}
QUERY = {
    "query": "streaming vs cable pricing mechanism",
    "question_ids": ["q1"],
    "purpose": "Understand the pricing mechanism.",
}
PREFERENCES = {
    "preferred_categories": ["official statistics", "company filings"],
    "avoid_or_caution": ["forums"],
    "prefer_primary_sources": True,
}
DIRECTION = {
    "angle": "The hidden fee",
    "description": "Reveal what the sticker price hides.",
    "questions_to_explore": ["q1"],
}
PLAN = {
    "topic": "Why is streaming cheaper than cable?",
    "core_question": "What actually makes streaming cheaper?",
    "research_questions": [QUESTION],
    "search_queries": [QUERY],
    "source_preferences": PREFERENCES,
    "story_directions": [DIRECTION],
    "target_audience": "Curious general viewers",
    "target_seconds": 35.0,
}


def make_plan(**overrides) -> ResearchPlan:
    return ResearchPlan.model_validate({**PLAN, **overrides})


def test_valid_plan_constructs_and_round_trips():
    plan = make_plan()
    assert plan.created_at.tzinfo is not None
    restored = ResearchPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan


@pytest.mark.parametrize("priority", ["high", "medium", "low"])
def test_valid_priorities(priority):
    question = {**QUESTION, "priority": priority}
    assert make_plan(research_questions=[question]).research_questions[0].priority == priority


def test_invalid_priority_rejected():
    with pytest.raises(ValidationError):
        make_plan(research_questions=[{**QUESTION, "priority": "urgent"}])


def test_empty_questions_rejected():
    with pytest.raises(ValidationError):
        make_plan(research_questions=[])


@pytest.mark.parametrize("field", ["topic", "core_question", "target_audience"])
@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_required_strings_rejected(field, bad):
    with pytest.raises(ValidationError):
        make_plan(**{field: bad})


@pytest.mark.parametrize("field", ["question", "reason", "expected_evidence"])
def test_empty_question_fields_rejected(field):
    with pytest.raises(ValidationError):
        make_plan(research_questions=[{**QUESTION, field: "  "}])


def test_empty_search_queries_rejected():
    with pytest.raises(ValidationError):
        make_plan(search_queries=[])
    with pytest.raises(ValidationError):
        make_plan(search_queries=[{**QUERY, "query": "  "}])
    with pytest.raises(ValidationError):
        make_plan(search_queries=[{**QUERY, "question_ids": []}])


def test_duplicate_question_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate question ID: q1"):
        make_plan(research_questions=[QUESTION, {**QUESTION, "question": "Different?"}])


def test_query_unknown_question_reference_rejected():
    with pytest.raises(ValidationError, match="search_queries\\[0\\] references unknown question ID: q9"):
        make_plan(search_queries=[{**QUERY, "question_ids": ["q9"]}])


def test_direction_unknown_question_reference_rejected():
    with pytest.raises(ValidationError, match="story_directions\\[0\\].*unknown question ID: q9"):
        make_plan(story_directions=[{**DIRECTION, "questions_to_explore": ["q9"]}])


def test_empty_direction_references_rejected():
    with pytest.raises(ValidationError):
        make_plan(story_directions=[{**DIRECTION, "questions_to_explore": []}])


def test_empty_story_directions_rejected():
    with pytest.raises(ValidationError):
        make_plan(story_directions=[])


def test_empty_preferred_categories_rejected():
    with pytest.raises(ValidationError):
        make_plan(source_preferences={**PREFERENCES, "preferred_categories": []})


def test_question_limit_enforced():
    questions = [{**QUESTION, "question_id": f"q{i}"} for i in range(1, 14)]
    with pytest.raises(ValidationError):
        make_plan(research_questions=questions)


def test_query_limit_enforced():
    queries = [dict(QUERY) for _ in range(25)]
    with pytest.raises(ValidationError):
        make_plan(search_queries=queries)


def test_direction_limit_enforced():
    directions = [dict(DIRECTION) for _ in range(7)]
    with pytest.raises(ValidationError):
        make_plan(story_directions=directions)


@pytest.mark.parametrize("value", [0, -5, True, math.nan, math.inf])
def test_invalid_target_seconds_rejected(value):
    with pytest.raises(ValidationError):
        make_plan(target_seconds=value)


@pytest.mark.parametrize("value", [10.0, 60.0])
def test_valid_target_seconds_accepted(value):
    assert make_plan(target_seconds=value).target_seconds == value


def test_all_reference_problems_collected():
    payload = copy.deepcopy(PLAN)
    payload["research_questions"] = [QUESTION, dict(QUESTION)]
    payload["search_queries"] = [{**QUERY, "question_ids": ["q9"]}]
    payload["story_directions"] = [{**DIRECTION, "questions_to_explore": ["q8"]}]
    with pytest.raises(ValidationError) as excinfo:
        ResearchPlan.model_validate(payload)
    message = str(excinfo.value)
    assert "duplicate question ID: q1" in message
    assert "unknown question ID: q9" in message
    assert "unknown question ID: q8" in message


# --- Prompt behavior ---


def test_planning_prompt_contains_topic_duration_and_guardrails():
    prompt = research_planning_prompt("Why is streaming cheaper?", 35.0)
    assert "Why is streaming cheaper?" in prompt
    assert "35 seconds" in prompt
    assert "Do not answer any question" in prompt
    assert "do not write a script" in prompt
    assert "never answer the research questions" in RESEARCH_PLANNING_SYSTEM


@pytest.mark.parametrize(
    ("target", "depth"),
    [(15.0, "3-4 research questions"), (35.0, "4-6 research questions"), (60.0, "6-8 research questions")],
)
def test_planning_prompt_depth_adapts_to_duration(target, depth):
    assert depth in research_planning_prompt("A topic", target)


def test_planning_prompt_includes_optional_context():
    assert "Video context: vertical short for beginners" in research_planning_prompt(
        "A topic", 35.0, "vertical short for beginners"
    )
    assert "Video context" not in research_planning_prompt("A topic", 35.0)


# --- Gemini planner (fake SDK, no network) ---


@pytest.fixture
def planner(fake_sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-not-real")
    return ResearchPlanner(GeminiClient()), fake_sdk


def test_planner_returns_validated_plan_and_owns_identity_fields(planner):
    client_planner, fake_sdk = planner
    drifted = ResearchPlan.model_validate({**PLAN, "topic": "DRIFTED", "target_seconds": 99.0})
    fake_sdk.responses.append(make_response(parsed=drifted))
    result = client_planner.plan("Why is streaming cheaper?", target_seconds=35.0)
    assert isinstance(result, ResearchPlan)
    assert result.topic == "Why is streaming cheaper?"
    assert result.target_seconds == 35.0
    assert result.created_at.tzinfo is not None
    call = fake_sdk.calls[0]
    assert call.config.response_schema is ResearchPlan
    assert "Why is streaming cheaper?" in call.contents
    assert "35 seconds" in call.contents


def test_planner_rejects_bad_inputs_before_any_call(planner):
    client_planner, fake_sdk = planner
    with pytest.raises(ValueError, match="Topic must not be empty"):
        client_planner.plan("   ")
    with pytest.raises(ValueError, match="greater than 0"):
        client_planner.plan("A topic", target_seconds=0)
    with pytest.raises(ValueError, match="greater than 0"):
        client_planner.plan("A topic", target_seconds=math.nan)
    assert fake_sdk.calls == []


# --- Mock planner ---


@pytest.mark.parametrize("target", [10.0, 35.0, 60.0])
def test_mock_planner_produces_valid_plan(target):
    plan = MockResearchPlanner().plan("Why is streaming cheaper?", target_seconds=target)
    assert isinstance(plan, ResearchPlan)
    assert plan.target_seconds == target
    assert plan.topic == "Why is streaming cheaper?"
    assert len(plan.research_questions) == 4
    assert len(plan.search_queries) == 5
    assert len(plan.story_directions) == 2


def test_mock_planner_is_deterministic():
    first = MockResearchPlanner().plan("A topic").model_dump()
    second = MockResearchPlanner().plan("A topic").model_dump()
    first.pop("created_at")
    second.pop("created_at")
    assert first == second


def test_mock_planner_rejects_bad_inputs():
    with pytest.raises(ValueError, match="Topic must not be empty"):
        MockResearchPlanner().plan("  ")
    with pytest.raises(ValueError, match="greater than 0"):
        MockResearchPlanner().plan("A topic", target_seconds=-1)