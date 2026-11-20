import copy
import math
from datetime import timedelta

import pytest
from pydantic import ValidationError

from orchestrator.gemini import GeminiClient
from orchestrator.prompts import RESEARCH_PLANNING_SYSTEM, research_planning_prompt
from orchestrator.research_planner import MockResearchPlanner, ResearchPlanner
from orchestrator.research_schemas import ResearchPlan, ResearchPlanContent

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


CONTENT = {
    key: PLAN[key]
    for key in (
        "core_question",
        "research_questions",
        "search_queries",
        "source_preferences",
        "story_directions",
        "target_audience",
    )
}


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


def test_planning_prompt_separates_id_order_from_priority():
    prompt = research_planning_prompt("A topic", 35.0)
    assert "sequentially in the recommended investigation order" in prompt
    assert "priority independently" in prompt
    assert "do not imply equal" in prompt


# --- Content-only schema (Gemini boundary) ---


def test_content_schema_has_no_app_owned_or_unsupported_features():
    schema = ResearchPlanContent.model_json_schema()
    assert set(schema["properties"]) == set(CONTENT)
    assert set(schema["required"]) == set(CONTENT)
    for owned in ("topic", "target_seconds", "created_at"):
        assert owned not in schema["properties"]

    unsupported = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"anyOf", "oneOf", "default", "format"}:
                    unsupported.append(key)
                if key == "$ref":
                    assert value.split("/")[-1] in schema.get("$defs", {})
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert unsupported == []


def test_content_model_enforces_references_without_app_fields():
    content = ResearchPlanContent.model_validate(CONTENT)
    assert content.core_question == PLAN["core_question"]
    bad = {**CONTENT, "search_queries": [{**QUERY, "question_ids": ["q9"]}]}
    with pytest.raises(ValidationError, match="unknown question ID: q9"):
        ResearchPlanContent.model_validate(bad)


def test_duplicate_query_references_rejected():
    questions = [QUESTION, {**QUESTION, "question_id": "q2", "question": "Another?"}]
    with pytest.raises(ValidationError, match=r"search_queries\[0\] repeats question IDs"):
        make_plan(
            research_questions=questions,
            search_queries=[{**QUERY, "question_ids": ["q1", "q1"]}],
        )


def test_duplicate_direction_references_rejected():
    questions = [QUESTION, {**QUESTION, "question_id": "q2", "question": "Another?"}]
    with pytest.raises(ValidationError, match=r"story_directions\[0\] repeats question IDs"):
        make_plan(
            research_questions=questions,
            story_directions=[{**DIRECTION, "questions_to_explore": ["q1", "q1"]}],
        )


def test_unique_multi_references_are_valid():
    questions = [QUESTION, {**QUESTION, "question_id": "q2", "question": "Another?"}]
    plan = make_plan(
        research_questions=questions,
        search_queries=[{**QUERY, "question_ids": ["q1", "q2"]}],
        story_directions=[{**DIRECTION, "questions_to_explore": ["q2", "q1"]}],
    )
    assert plan.search_queries[0].question_ids == ["q1", "q2"]
    assert plan.story_directions[0].questions_to_explore == ["q2", "q1"]


# --- Gemini planner (fake SDK, no network) ---


@pytest.fixture
def planner(fake_sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-not-real")
    return ResearchPlanner(GeminiClient()), fake_sdk


def test_planner_requests_content_only_and_owns_identity_fields(planner):
    client_planner, fake_sdk = planner
    content = ResearchPlanContent.model_validate(CONTENT)
    fake_sdk.responses.append(make_response(parsed=content))
    result = client_planner.plan("Why is streaming cheaper?", target_seconds=35.0)
    assert isinstance(result, ResearchPlan)
    assert result.topic == "Why is streaming cheaper?"
    assert result.target_seconds == 35.0
    assert result.created_at.utcoffset() == timedelta(0)
    call = fake_sdk.calls[0]
    assert call.config.response_schema is ResearchPlanContent
    assert "Why is streaming cheaper?" in call.contents
    assert "35 seconds" in call.contents


def test_planner_passes_context_into_request(planner):
    client_planner, fake_sdk = planner
    fake_sdk.responses.append(
        make_response(parsed=ResearchPlanContent.model_validate(CONTENT))
    )
    client_planner.plan("A topic", context="vertical short for beginners")
    assert "Video context: vertical short for beginners" in fake_sdk.calls[0].contents


@pytest.mark.parametrize("target", [35, 35.0, 10, 60.5])
def test_planner_accepts_int_and_float_targets(planner, target):
    client_planner, fake_sdk = planner
    fake_sdk.responses.append(
        make_response(parsed=ResearchPlanContent.model_validate(CONTENT))
    )
    result = client_planner.plan("A topic", target_seconds=target)
    assert result.target_seconds == float(target)


@pytest.mark.parametrize(
    "target", [True, False, 0, 0.0, -5, math.nan, math.inf, -math.inf, "35", None]
)
def test_planner_rejects_invalid_durations_before_any_call(planner, target):
    client_planner, fake_sdk = planner
    with pytest.raises(ValueError, match="Target duration"):
        client_planner.plan("A topic", target_seconds=target)
    assert fake_sdk.calls == []


@pytest.mark.parametrize("topic", [None, 123, "", "   "])
def test_planner_rejects_invalid_topics_before_any_call(planner, topic):
    client_planner, fake_sdk = planner
    with pytest.raises(ValueError, match="Topic"):
        client_planner.plan(topic)
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


@pytest.mark.parametrize(
    "target", [True, False, 0, -5, math.nan, math.inf, "35", None]
)
def test_mock_planner_rejects_invalid_durations_consistently(target):
    with pytest.raises(ValueError, match="Target duration"):
        MockResearchPlanner().plan("A topic", target_seconds=target)


@pytest.mark.parametrize("topic", [None, 123, "", "  "])
def test_mock_planner_rejects_invalid_topics(topic):
    with pytest.raises(ValueError, match="Topic"):
        MockResearchPlanner().plan(topic)


def test_mock_planner_accepts_int_target():
    plan = MockResearchPlanner().plan("A topic", target_seconds=35)
    assert plan.target_seconds == 35.0