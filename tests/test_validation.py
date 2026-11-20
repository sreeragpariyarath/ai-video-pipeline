import pytest

from orchestrator.validation import JobValidationError, validate_job


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