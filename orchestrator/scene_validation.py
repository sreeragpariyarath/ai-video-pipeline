from __future__ import annotations

from .research_schemas import ResearchPackage
from .scene_schemas import ScenePlan
from .script_schemas import VideoScript, validate_claim_references


def validate_scene_coverage(
    plan: ScenePlan, script: VideoScript, package: ResearchPackage
) -> None:
    """Validate references and complete ordered narration coverage across artifacts."""
    if plan.script_id != script.script_id:
        raise ValueError("scene plan references a different script")
    if plan.research_id != script.research_id or script.research_id != package.research_id:
        raise ValueError("scene plan, script, and research package IDs do not match")
    if plan.format != script.format:
        raise ValueError("scene plan format does not match the script")
    if abs(plan.target_seconds - script.target_seconds) > 0.01:
        raise ValueError("scene plan target duration does not match the script")
    if abs(plan.planned_seconds - script.planned_seconds) > 0.01:
        raise ValueError("scene plan duration does not match the script")

    expected = {segment.segment_id: segment for segment in script.segments}
    actual_ids = [
        segment_id
        for scene in plan.scenes
        for segment_id in scene.script_segment_ids
    ]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("scene plan repeats script segment references")
    if set(actual_ids) != set(expected):
        missing = sorted(set(expected) - set(actual_ids))
        unknown = sorted(set(actual_ids) - set(expected))
        raise ValueError(
            f"scene segment coverage mismatch (missing={missing}, unknown={unknown})"
        )
    expected_order = [segment.segment_id for segment in script.segments]
    if actual_ids != expected_order:
        raise ValueError("scene plan must preserve script segment order")

    for scene in plan.scenes:
        segments = [expected[item] for item in scene.script_segment_ids]
        duration = sum(segment.duration_seconds for segment in segments)
        if abs(scene.duration_seconds - duration) > 0.01:
            raise ValueError(f"scene {scene.scene_id} duration does not match its segments")
        narration = " ".join(segment.narration for segment in segments)
        if scene.narration_text != narration:
            raise ValueError(f"scene {scene.scene_id} narration does not match its segments")
        lowered_narration = narration.casefold()
        for overlay in scene.on_screen_text:
            if overlay.text.casefold() not in lowered_narration:
                raise ValueError(
                    f"scene {scene.scene_id} overlay text must come from its narration"
                )

    validate_claim_references(script, package)
