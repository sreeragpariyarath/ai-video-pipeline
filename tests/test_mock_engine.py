import pytest

from orchestrator.engine import MockEngine
from orchestrator.validation import JobValidationError, validate_job

from conftest import TOPIC, make_job


@pytest.fixture
def engine():
    return MockEngine()


def test_mock_research_is_deterministic(engine):
    first = engine.research(TOPIC)
    second = MockEngine().research(TOPIC)
    assert first == second
    assert len(first.facts) == 3
    assert len(first.sources) == 3
    assert all(source.url.startswith("https://example.com/") for source in first.sources)
    assert {fact.source for fact in first.facts} == {source.url for source in first.sources}


def test_mock_hook_text_and_alternatives(engine):
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    assert hook.text == "Why is Netflix cheaper than cable TV. Here is what actually matters."
    assert len(hook.alternatives) == 2
    assert all(hook.alternatives)


def test_mock_script_matches_scene_narration(engine):
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    script = engine.write_script(TOPIC, research, hook, 35.0)
    plan = engine.breakdown(TOPIC, research, hook, script, 35.0)
    assert script.narration == " ".join(scene.narration for scene in plan.scenes)
    assert len(script.beats) == 5


def test_mock_scene_plan_shape(engine):
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    script = engine.write_script(TOPIC, research, hook, 35.0)
    plan = engine.breakdown(TOPIC, research, hook, script, 35.0)
    assert len(plan.scenes) == 5
    assert [scene.type for scene in plan.scenes] == [
        "hook", "explainer", "explainer", "example", "payoff",
    ]
    assert plan.scenes[0].durationSeconds == 2.0
    assert plan.scenes[0].narration == hook.text


def test_mock_35_second_job_passes_validation():
    job = make_job(35.0)
    summary = validate_job(job)
    assert summary["durationSeconds"] == 35.0
    assert summary["sceneCount"] == 5


def test_mock_25_second_job_passes_validation():
    job = make_job(25.0)
    summary = validate_job(job)
    assert summary["sceneCount"] == 5
    assert abs(summary["durationSeconds"] - 25.0) <= 2.0


def test_mock_body_durations_scale_with_target(engine):
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    script = engine.write_script(TOPIC, research, hook, 25.0)
    plan = engine.breakdown(TOPIC, research, hook, script, 25.0)
    body_total = sum(scene.durationSeconds for scene in plan.scenes[1:])
    assert body_total == pytest.approx(23.0, abs=0.2)


# Known limitation (audit finding, intentionally NOT fixed here): the mock hook
# is fixed at 2.0s and body scenes scale linearly, so targets far from 35s
# violate the 2-12s per-scene bounds and fail validation. These tests pin the
# current behavior so a future fix is a deliberate, visible change.


def test_mock_60_second_target_currently_fails_validation():
    with pytest.raises(JobValidationError) as excinfo:
        validate_job(make_job(60.0))
    assert any("durationSeconds must be 2-12s" in p for p in excinfo.value.problems)


def test_mock_10_second_target_currently_fails_validation():
    with pytest.raises(JobValidationError) as excinfo:
        validate_job(make_job(10.0))
    assert any("durationSeconds must be 2-12s" in p for p in excinfo.value.problems)