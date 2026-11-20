import pytest

from orchestrator.engine import MockEngine
from orchestrator.validation import validate_job

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


# Duration scaling: the mock now adapts its scene count and durations to the
# target (10-60s) instead of failing validation outside a narrow band.


@pytest.mark.parametrize("target", [10.0, 25.0, 35.0, 60.0])
def test_mock_supported_targets_pass_validation(target):
    summary = validate_job(make_job(target))
    tolerance = max(2.0, target * 0.08)
    assert abs(summary["durationSeconds"] - target) <= tolerance


@pytest.mark.parametrize("target", [10.0, 25.0, 35.0, 60.0])
def test_mock_scene_bounds_hold_for_supported_targets(target):
    job = make_job(target)
    scenes = job["scenes"]
    assert 3 <= len(scenes) <= 10
    assert 1.0 <= scenes[0]["durationSeconds"] <= 3.0
    assert scenes[0]["type"] == "hook"
    for scene in scenes[1:]:
        assert 2.0 <= scene["durationSeconds"] <= 12.0
    total = sum(scene["durationSeconds"] for scene in scenes)
    assert total == job["durationSeconds"]
    assert abs(total - target) <= max(2.0, target * 0.08)


@pytest.mark.parametrize(
    ("target", "expected_scenes"),
    [(10.0, 5), (25.0, 5), (35.0, 5), (60.0, 6)],
)
def test_mock_scene_count_adapts_to_target(target, expected_scenes):
    assert len(make_job(target)["scenes"]) == expected_scenes


@pytest.mark.parametrize("target", [10.0, 25.0, 35.0, 60.0])
def test_mock_output_is_deterministic(target):
    first = make_job(target)
    second = make_job(target)
    for key in ("jobId", "createdAt"):
        first.pop(key)
        second.pop(key)
    assert first == second


@pytest.mark.parametrize("target", [5.0, 9.0, 61.0, 120.0])
def test_mock_unsupported_targets_raise_clear_error(target):
    with pytest.raises(ValueError, match="MockEngine supports target durations from 10 to 60"):
        make_job(target)


def test_mock_error_message_names_the_offending_target():
    with pytest.raises(ValueError, match=r"got 90\)\. Choose a --target-seconds value"):
        make_job(90.0)


def test_mock_payoff_stays_last_at_every_supported_target():
    for target in (10.0, 25.0, 35.0, 60.0):
        scenes = make_job(target)["scenes"]
        assert scenes[-1]["type"] == "payoff"
        assert scenes[-1]["sources"] == []