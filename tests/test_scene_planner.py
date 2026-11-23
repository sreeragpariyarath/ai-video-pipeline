import pytest

from orchestrator.production_pipeline import build_production_pipeline
from orchestrator.scene_planner import (
    SceneDesign,
    MockScenePlanner,
    ScenePlanner,
    ScenePlanContent,
    ScenePlanningError,
)
from orchestrator.scene_schemas import (
    SceneComposition,
    SceneMotion,
    SceneTransition,
)
from orchestrator.scene_validation import validate_scene_coverage


TOPIC = "Why is Netflix cheaper than cable TV?"


def design_for(segment_ids):
    return SceneDesign(
        scene_type="text_focus",
        script_segment_ids=segment_ids,
        visual_description="One focused typographic scene.",
        composition=SceneComposition(layout="centered"),
        motion=SceneMotion(entrance="fade"),
        on_screen_text=[],
        transition=SceneTransition(type="cut"),
    )


class StubClient:
    def __init__(self, content):
        self.content = content
        self.schema = None

    def generate_json(self, *, schema, **kwargs):
        self.schema = schema
        return self.content


def test_ai_scene_planner_assigns_application_owned_scene_data():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    content = ScenePlanContent(
        scenes=[
            design_for([segment.segment_id for segment in artifacts.script.segments])
        ]
    )
    client = StubClient(content)
    plan = ScenePlanner(client).plan(artifacts.script)

    validate_scene_coverage(plan, artifacts.script, artifacts.research)
    assert client.schema is ScenePlanContent
    assert plan.scenes[0].order == 1
    assert plan.scenes[0].narration_text == " ".join(
        segment.narration for segment in artifacts.script.segments
    )
    assert plan.scenes[0].duration_seconds == artifacts.script.planned_seconds


def test_mock_scene_planner_ids_are_stable_for_the_same_script():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    first = MockScenePlanner().plan(artifacts.script)
    second = MockScenePlanner().plan(artifacts.script)
    assert [scene.scene_id for scene in first.scenes] == [
        scene.scene_id for scene in second.scenes
    ]
    assert first.scene_plan_id == second.scene_plan_id


def test_ai_scene_planner_rejects_unknown_segment_reference():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    client = StubClient(ScenePlanContent(scenes=[design_for(["seg-unknown"])]))

    with pytest.raises(ScenePlanningError, match="invalid scene planning output"):
        ScenePlanner(client).plan(artifacts.script)


def test_ai_scene_planner_rejects_missing_segment_coverage():
    artifacts = build_production_pipeline(mock=True).generate(
        TOPIC, format="short", target_seconds=35
    )
    client = StubClient(
        ScenePlanContent(scenes=[design_for([artifacts.script.segments[0].segment_id])])
    )

    with pytest.raises(ScenePlanningError, match="invalid scene planning output"):
        ScenePlanner(client).plan(artifacts.script)
