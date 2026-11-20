import math

import pytest

from orchestrator.validation import JobValidationError, validate_job

from conftest import make_job


def expect_rejected(job, fragment=None):
    with pytest.raises(JobValidationError) as excinfo:
        validate_job(job)
    if fragment is not None:
        assert any(fragment in problem for problem in excinfo.value.problems), (
            excinfo.value.problems
        )
    return excinfo.value.problems


def test_valid_job_passes(valid_job):
    summary = validate_job(valid_job)
    assert summary == {
        "sceneCount": 5,
        "durationSeconds": 35.0,
        "sourceCount": 3,
        "factCount": 3,
    }


def test_invalid_schema_version_rejected(valid_job):
    valid_job["schemaVersion"] = 1
    expect_rejected(valid_job, "schemaVersion must be 2")


def test_missing_schema_version_rejected(valid_job):
    del valid_job["schemaVersion"]
    expect_rejected(valid_job, "schemaVersion")


def test_total_duration_outside_tolerance_rejected(valid_job):
    valid_job["format"]["targetDurationSeconds"] = 60.0
    expect_rejected(valid_job, "Scene durations total")


def test_total_duration_within_tolerance_passes(valid_job):
    valid_job["format"]["targetDurationSeconds"] = 36.5
    validate_job(valid_job)


def test_hook_duration_too_long_rejected(valid_job):
    valid_job["scenes"][0]["durationSeconds"] = 5.0
    expect_rejected(valid_job, "for the hook")


def test_hook_duration_too_short_rejected(valid_job):
    valid_job["scenes"][0]["durationSeconds"] = 0.5
    expect_rejected(valid_job, "for the hook")


def test_body_scene_duration_over_cap_rejected(valid_job):
    valid_job["scenes"][1]["durationSeconds"] = 13.0
    expect_rejected(valid_job, "durationSeconds must be 2-12s")


def test_body_scene_duration_under_floor_rejected(valid_job):
    valid_job["scenes"][1]["durationSeconds"] = 1.0
    expect_rejected(valid_job, "durationSeconds must be 2-12s")


def test_fact_citation_outside_sources_rejected(valid_job):
    valid_job["research"]["facts"][0]["source"] = "https://evil.example.com/not-a-source"
    expect_rejected(valid_job, "must come from research.sources")


def test_scene_citation_outside_sources_rejected(valid_job):
    valid_job["scenes"][1]["sources"] = ["https://evil.example.com/not-a-source"]
    expect_rejected(valid_job, "must come from research.sources")


def test_non_http_source_url_rejected(valid_job):
    valid_job["research"]["sources"][0]["url"] = "ftp://example.com/file"
    expect_rejected(valid_job, "must be an http(s) URL")


def test_too_few_facts_rejected(valid_job):
    valid_job["research"]["facts"] = valid_job["research"]["facts"][:2]
    expect_rejected(valid_job, "at least 3 facts")


def test_no_facts_rejected(valid_job):
    valid_job["research"]["facts"] = []
    expect_rejected(valid_job, "at least 3 facts")


def test_no_sources_rejected(valid_job):
    valid_job["research"]["sources"] = []
    problems = expect_rejected(valid_job, "at least one source URL")
    assert any("must come from research.sources" in problem for problem in problems)


def test_duplicate_source_urls_rejected(valid_job):
    sources = valid_job["research"]["sources"]
    sources.append(dict(sources[0]))
    expect_rejected(valid_job, "must be unique")


def test_missing_research_rejected(valid_job):
    del valid_job["research"]
    expect_rejected(valid_job, "research must be an object")


def test_too_few_scenes_rejected(valid_job):
    valid_job["scenes"] = valid_job["scenes"][:2]
    expect_rejected(valid_job, "scenes must contain 3-10 scenes")


def test_too_many_scenes_rejected(valid_job):
    scene = valid_job["scenes"][1]
    valid_job["scenes"] = [valid_job["scenes"][0]] + [dict(scene) for _ in range(10)]
    for index, item in enumerate(valid_job["scenes"]):
        item["id"] = f"scene-{index + 1:02d}"
    expect_rejected(valid_job, "scenes must contain 3-10 scenes")


def test_first_scene_must_be_hook(valid_job):
    valid_job["scenes"][0]["type"] = "explainer"
    expect_rejected(valid_job, "first scene must be type hook")


def test_duplicate_scene_id_rejected(valid_job):
    valid_job["scenes"][1]["id"] = valid_job["scenes"][0]["id"]
    expect_rejected(valid_job, "duplicates")


def test_unknown_visual_component_rejected(valid_job):
    valid_job["scenes"][0]["visual"]["component"] = "FancyChart"
    expect_rejected(valid_job, "visual.component must be one of")


def test_empty_headline_rejected(valid_job):
    valid_job["scenes"][0]["visual"]["headline"] = "   "
    expect_rejected(valid_job, "visual.headline")


def test_missing_hook_alternatives_rejected(valid_job):
    valid_job["hook"]["alternatives"] = ["only one"]
    expect_rejected(valid_job, "at least 2 hooks")


def test_non_numeric_duration_rejected(valid_job):
    valid_job["scenes"][1]["durationSeconds"] = "eight"
    expect_rejected(valid_job, "must be a positive number")


def test_boolean_duration_rejected(valid_job):
    valid_job["scenes"][1]["durationSeconds"] = True
    expect_rejected(valid_job, "must be a positive number")


# --- Hardening rules (Task 5) ---


def test_declared_total_mismatch_rejected(valid_job):
    valid_job["durationSeconds"] = 99.0
    expect_rejected(valid_job, "must equal the scene duration sum")


def test_declared_total_missing_rejected(valid_job):
    del valid_job["durationSeconds"]
    expect_rejected(valid_job, "durationSeconds must be a positive number")


@pytest.mark.parametrize("value", [0, -5, math.nan, math.inf, True, "35"])
def test_declared_total_invalid_values_rejected(valid_job, value):
    valid_job["durationSeconds"] = value
    expect_rejected(valid_job, "durationSeconds must be a positive number")


def test_declared_total_within_rounding_passes(valid_job):
    valid_job["durationSeconds"] = 35.005
    validate_job(valid_job)


def test_declared_total_beyond_rounding_rejected(valid_job):
    valid_job["durationSeconds"] = 35.02
    expect_rejected(valid_job, "must equal the scene duration sum")


def test_hook_narration_mismatch_rejected(valid_job):
    valid_job["scenes"][0]["narration"] = "A completely different opening line."
    expect_rejected(valid_job, "must match hook.text")


def test_hook_narration_whitespace_difference_tolerated(valid_job):
    valid_job["hook"]["text"] = valid_job["hook"]["text"] + "   "
    validate_job(valid_job)


def test_word_count_mismatch_rejected(valid_job):
    valid_job["script"]["wordCount"] += 5
    expect_rejected(valid_job, "must match the narration word count")


def test_word_count_missing_rejected(valid_job):
    del valid_job["script"]["wordCount"]
    expect_rejected(valid_job, "script.wordCount must be a non-negative integer")


@pytest.mark.parametrize("value", ["84", True, -1, 8.5])
def test_word_count_invalid_values_rejected(valid_job, value):
    valid_job["script"]["wordCount"] = value
    expect_rejected(valid_job, "script.wordCount must be a non-negative integer")


def test_simple_diagram_requires_items(valid_job):
    del valid_job["scenes"][1]["visual"]["items"]
    expect_rejected(valid_job, "SimpleDiagram must include items")


def test_animated_text_rejects_items(valid_job):
    valid_job["scenes"][0]["visual"]["items"] = ["not allowed here"]
    expect_rejected(valid_job, "AnimatedText must not include items")


def test_duplicate_scene_citation_rejected(valid_job):
    url = valid_job["research"]["sources"][0]["url"]
    valid_job["scenes"][1]["sources"] = [url, url]
    expect_rejected(valid_job, "must not repeat URLs")


def test_non_string_scene_sources_rejected_without_crashing(valid_job):
    valid_job["scenes"][1]["sources"] = [{"url": "https://example.com/x"}]
    expect_rejected(valid_job, "must be an http(s) URL")


@pytest.mark.parametrize("status", ["draft", "rendered", None])
def test_invalid_status_rejected(valid_job, status):
    valid_job["status"] = status
    expect_rejected(valid_job, 'status must be "scripted"')


def test_missing_status_rejected(valid_job):
    del valid_job["status"]
    expect_rejected(valid_job, 'status must be "scripted"')


@pytest.mark.parametrize("hook_seconds", [1.0, 3.0])
def test_hook_duration_boundary_values_pass(valid_job, hook_seconds):
    delta = hook_seconds - valid_job["scenes"][0]["durationSeconds"]
    valid_job["scenes"][0]["durationSeconds"] = hook_seconds
    valid_job["scenes"][1]["durationSeconds"] -= delta
    validate_job(valid_job)


@pytest.mark.parametrize(
    ("first", "rest"),
    [(2.0, [10.4, 10.3, 10.3]), (12.0, [7.0, 7.0, 7.0])],
)
def test_body_duration_boundary_values_pass(valid_job, first, rest):
    valid_job["scenes"][1]["durationSeconds"] = first
    for scene, duration in zip(valid_job["scenes"][2:], rest):
        scene["durationSeconds"] = duration
    validate_job(valid_job)


@pytest.mark.parametrize("value", [math.nan, math.inf, -1.0, 0.0])
def test_scene_duration_invalid_numbers_rejected(valid_job, value):
    valid_job["scenes"][1]["durationSeconds"] = value
    expect_rejected(valid_job, "must be a positive number")


@pytest.mark.parametrize("target", [10.0, 25.0, 35.0, 60.0])
def test_valid_mock_jobs_pass_at_supported_durations(target):
    summary = validate_job(make_job(target))
    assert summary["sceneCount"] >= 3
    assert abs(summary["durationSeconds"] - target) <= max(2.0, target * 0.08)