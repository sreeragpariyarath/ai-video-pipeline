import json

import pytest

from orchestrator.production_pipeline import (
    build_production_pipeline,
    save_artifacts,
)
from orchestrator.scene_validation import validate_scene_coverage


TOPIC = "Why is Netflix cheaper than cable TV?"


def test_modular_mock_pipeline_builds_valid_artifacts():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )

    assert artifacts.mode == "mock"
    assert artifacts.quality.status == "ready"
    assert artifacts.script.research_id == artifacts.research.research_id
    validate_scene_coverage(artifacts.scene_plan, artifacts.script, artifacts.research)
    assert [
        segment_id
        for scene in artifacts.scene_plan.scenes
        for segment_id in scene.script_segment_ids
    ] == [segment.segment_id for segment in artifacts.script.segments]


def test_scene_coverage_rejects_missing_script_segments():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    plan = artifacts.scene_plan.model_copy(
        update={"scenes": artifacts.scene_plan.scenes[:-1]}
    )

    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_scene_coverage(plan, artifacts.script, artifacts.research)


def test_scene_coverage_rejects_changed_narration():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    first = artifacts.scene_plan.scenes[0].model_copy(
        update={"narration_text": "Narration that is not in the script."}
    )
    plan = artifacts.scene_plan.model_copy(
        update={"scenes": [first, *artifacts.scene_plan.scenes[1:]]}
    )

    with pytest.raises(ValueError, match="narration does not match"):
        validate_scene_coverage(plan, artifacts.script, artifacts.research)


def test_scene_coverage_rejects_overlay_not_in_narration():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    first = artifacts.scene_plan.scenes[0].model_copy(
        update={
            "on_screen_text": [
                artifacts.scene_plan.scenes[0].on_screen_text[0].model_copy(
                    update={"text": "Invented metric: 93%"}
                )
            ]
        }
    )
    plan = artifacts.scene_plan.model_copy(
        update={"scenes": [first, *artifacts.scene_plan.scenes[1:]]}
    )

    with pytest.raises(ValueError, match="overlay text must come from its narration"):
        validate_scene_coverage(plan, artifacts.script, artifacts.research)


def test_artifacts_are_saved_as_separate_json_files(tmp_path):
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )

    job_dir = save_artifacts(artifacts, tmp_path)

    for filename in (
        "research.json",
        "run_metadata.json",
        "quality.json",
        "usage.json",
        "script.json",
        "scene_plan.json",
        "render_props.json",
    ):
        assert (job_dir / filename).is_file()
    props = json.loads((job_dir / "render_props.json").read_text(encoding="utf-8"))
    metadata = json.loads((job_dir / "run_metadata.json").read_text(encoding="utf-8"))
    assert props["plan"]["scene_plan_id"] == artifacts.scene_plan.scene_plan_id
    assert metadata["mode"] == "mock"
