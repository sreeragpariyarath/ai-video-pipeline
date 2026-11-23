from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.scene_schemas import Scene, ScenePlan


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def scene_dict(**overrides):
    data = {
        "scene_id": "scene-1",
        "order": 1,
        "scene_type": "title",
        "duration_seconds": 3.0,
        "script_segment_ids": ["seg-1"],
        "narration_text": "A concise opening line.",
        "visual_description": "A bold title over a dark background.",
        "composition": {"layout": "centered"},
        "motion": {"entrance": "fade", "exit": "none", "emphasis": "none"},
        "on_screen_text": [{"text": "The key question", "role": "title"}],
        "transition": {"type": "cut", "duration_seconds": 0},
    }
    data.update(overrides)
    return data


def scene_list():
    return [
        scene_dict(),
        scene_dict(
            scene_id="scene-2",
            order=2,
            scene_type="statistic",
            duration_seconds=7.0,
            script_segment_ids=["seg-2"],
            narration_text="Here is the supporting number.",
            composition={"layout": "split", "hierarchy": "visual_first"},
        ),
    ]


def plan_dict(**overrides):
    data = {
        "scene_plan_id": "plan-1",
        "script_id": "script-1",
        "research_id": "research-1",
        "format": "short",
        "target_seconds": 10.0,
        "planned_seconds": 10.0,
        "scenes": scene_list(),
        "created_at": NOW,
    }
    data.update(overrides)
    return data


def make_scene(**overrides) -> Scene:
    return Scene.model_validate(scene_dict(**overrides))


def make_plan(**overrides) -> ScenePlan:
    return ScenePlan.model_validate(plan_dict(**overrides))


def test_valid_scene_and_plan_construct():
    scene = make_scene()
    plan = make_plan()
    assert scene.scene_type == "title"
    assert scene.composition.layout == "centered"
    assert plan.format == "short"
    assert [item.order for item in plan.scenes] == [1, 2]


def test_defaults_and_metadata():
    data = scene_dict()
    data.pop("motion")
    data.pop("on_screen_text")
    data.pop("transition")
    scene = Scene.model_validate(data)
    assert scene.motion.entrance == "fade"
    assert scene.on_screen_text == []
    assert scene.transition.type == "cut"
    data = plan_dict()
    data.pop("created_at")
    assert isinstance(ScenePlan.model_validate(data).created_at, datetime)


def test_created_at_default_is_utc():
    data = plan_dict()
    data.pop("created_at")
    plan = ScenePlan.model_validate(data)
    assert plan.created_at.tzinfo == timezone.utc


def test_round_trip_serialization():
    plan = make_plan()
    assert ScenePlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize("field", ["scene_id", "scene_type", "order", "duration_seconds", "script_segment_ids", "narration_text", "visual_description", "composition"])
def test_required_scene_fields(field):
    data = scene_dict()
    del data[field]
    with pytest.raises(ValidationError):
        Scene.model_validate(data)


@pytest.mark.parametrize("scene_type", ["opening", "hook", "chart"])
def test_invalid_scene_type_rejected(scene_type):
    with pytest.raises(ValidationError):
        make_scene(scene_type=scene_type)


@pytest.mark.parametrize("scene_type", ["title", "text_focus", "statistic", "comparison", "process", "diagram", "timeline", "illustration", "conclusion"])
def test_supported_scene_types(scene_type):
    assert make_scene(scene_type=scene_type).scene_type == scene_type


@pytest.mark.parametrize("value", [0, -1, True, False, float("nan"), float("inf"), -float("inf")])
def test_invalid_scene_duration_rejected(value):
    with pytest.raises(ValidationError):
        make_scene(duration_seconds=value)


@pytest.mark.parametrize("field", ["target_seconds", "planned_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, float("nan"), float("inf")])
def test_invalid_plan_durations_rejected(field, value):
    with pytest.raises(ValidationError):
        make_plan(**{field: value})


@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_invalid_order_rejected(value):
    with pytest.raises(ValidationError):
        make_scene(order=value)


def test_duplicate_scene_ids_rejected():
    scenes = scene_list()
    scenes[1]["scene_id"] = scenes[0]["scene_id"]
    with pytest.raises(ValidationError, match="scene IDs must be unique"):
        make_plan(scenes=scenes)


@pytest.mark.parametrize("orders", [[1, 3], [2, 1], [1, 1]])
def test_invalid_plan_order_rejected(orders):
    scenes = scene_list()
    for item, order in zip(scenes, orders):
        item["order"] = order
    with pytest.raises(ValidationError, match="sequential"):
        make_plan(scenes=scenes)


def test_planned_duration_must_match_sum():
    with pytest.raises(ValidationError, match="scene duration sum"):
        make_plan(planned_seconds=11)


def test_planned_duration_tolerance_boundary():
    plan = make_plan(planned_seconds=10.0 + 0.01)
    assert plan.planned_seconds == pytest.approx(10.01)
    with pytest.raises(ValidationError):
        make_plan(planned_seconds=10.0 + 0.011)


def test_empty_scene_list_rejected():
    with pytest.raises(ValidationError):
        make_plan(scenes=[])


@pytest.mark.parametrize("field", ["scene_plan_id", "script_id", "research_id"])
@pytest.mark.parametrize("value", ["", "   "])
def test_plan_ids_must_be_non_empty(field, value):
    with pytest.raises(ValidationError):
        make_plan(**{field: value})


@pytest.mark.parametrize("value", ["", "  "])
def test_script_segment_ids_must_be_non_empty(value):
    with pytest.raises(ValidationError):
        make_scene(script_segment_ids=[value])


def test_duplicate_segment_references_rejected():
    with pytest.raises(ValidationError, match="script_segment_ids"):
        make_scene(script_segment_ids=["seg-1", "seg-1"])


def test_invalid_composition_and_motion_options_rejected():
    with pytest.raises(ValidationError):
        make_scene(composition={"layout": "freeform"})
    with pytest.raises(ValidationError):
        make_scene(motion={"entrance": "bounce"})


def test_on_screen_text_timing_must_fit_scene():
    with pytest.raises(ValidationError, match="fit within the scene"):
        make_scene(on_screen_text=[{"text": "Late", "start_seconds": 2, "duration_seconds": 2}])
    with pytest.raises(ValidationError, match="fit within the scene"):
        make_scene(on_screen_text=[{"text": "Too long", "duration_seconds": 3.01}])


def test_text_timing_boundary_is_accepted():
    scene = make_scene(on_screen_text=[{"text": "Final beat", "start_seconds": 2, "duration_seconds": 1}])
    assert scene.on_screen_text[0].start_seconds == 2


def test_transition_rules_and_boundary():
    assert make_scene(transition={"type": "fade", "duration_seconds": 2.0}).transition.duration_seconds == 2.0
    with pytest.raises(ValidationError):
        make_scene(transition={"type": "cut", "duration_seconds": 0.2})
    with pytest.raises(ValidationError):
        make_scene(transition={"type": "slide", "duration_seconds": 2.01})


def test_planned_duration_may_differ_from_target():
    # The schema reconciles the scene sum; a later cross-artifact validator can
    # apply the selected target-duration tolerance policy.
    plan = make_plan(target_seconds=9.0)
    assert plan.planned_seconds == 10.0


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        make_scene(unbounded_visual_instruction="anything")
