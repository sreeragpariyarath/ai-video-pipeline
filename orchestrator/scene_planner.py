from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .gemini import GeminiClient, GeminiError
from .research_schemas import NonEmptyStr
from .scene_schemas import (
    OnScreenText,
    Scene,
    SceneComposition,
    SceneGraphic,
    SceneMotion,
    ScenePlan,
    SceneTransition,
    SceneType,
)
from .script_schemas import ScriptSegment, VideoScript


class SceneDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_type: SceneType
    script_segment_ids: list[NonEmptyStr] = Field(min_length=1)
    visual_description: NonEmptyStr
    composition: SceneComposition
    motion: SceneMotion
    on_screen_text: list[OnScreenText]
    graphic: SceneGraphic | None = None
    transition: SceneTransition


class ScenePlanContent(BaseModel):
    """AI-authored visual decisions; IDs, order, timing and narration are assigned in code."""

    model_config = ConfigDict(extra="forbid")

    scenes: list[SceneDesign] = Field(min_length=1, max_length=32)


class ScenePlanningError(RuntimeError):
    """Scene planning failed with a safe, application-defined message."""


INVALID_SCENE_OUTPUT = "Gemini returned invalid scene planning output."

_DEFAULT_PRESET_BY_TYPE = {
    "title": "headline",
    "text_focus": "quote_callout",
    "statistic": "number_explainer",
    "comparison": "comparison_two",
    "process": "process_walkthrough",
    "diagram": "diagram",
    "timeline": "timeline",
    "illustration": "split_visual",
    "conclusion": "hero_overlay",
}


def _assemble(content: ScenePlanContent, script: VideoScript) -> ScenePlan:
    segments = {segment.segment_id: segment for segment in script.segments}
    seen: set[str] = set()
    scenes: list[Scene] = []

    for order, design in enumerate(content.scenes, start=1):
        if len(set(design.script_segment_ids)) != len(design.script_segment_ids):
            raise ScenePlanningError(INVALID_SCENE_OUTPUT)
        unknown = set(design.script_segment_ids) - segments.keys()
        if unknown:
            raise ScenePlanningError(INVALID_SCENE_OUTPUT)
        overlap = seen.intersection(design.script_segment_ids)
        if overlap:
            raise ScenePlanningError(INVALID_SCENE_OUTPUT)
        selected = [segments[item] for item in design.script_segment_ids]
        # Segment references must preserve narration order; this also makes the
        # generated voice track deterministic when one scene covers several beats.
        if selected != sorted(selected, key=lambda segment: segment.order):
            raise ScenePlanningError(INVALID_SCENE_OUTPUT)
        seen.update(design.script_segment_ids)
        composition = design.composition
        if composition.preset == "auto":
            composition = composition.model_copy(
                update={"preset": _DEFAULT_PRESET_BY_TYPE[design.scene_type]}
            )
        try:
            scenes.append(
                Scene(
                    scene_id=f"{script.script_id}-scene-{order:02d}",
                    order=order,
                    scene_type=design.scene_type,
                    duration_seconds=sum(s.duration_seconds for s in selected),
                    script_segment_ids=design.script_segment_ids,
                    narration_text=" ".join(s.narration for s in selected),
                    visual_description=design.visual_description,
                    composition=composition,
                    motion=design.motion,
                    on_screen_text=design.on_screen_text,
                    graphic=design.graphic,
                    transition=design.transition,
                )
            )
        except ValidationError as exc:
            raise ScenePlanningError(INVALID_SCENE_OUTPUT) from exc

    if seen != segments.keys():
        raise ScenePlanningError(INVALID_SCENE_OUTPUT)
    try:
        return ScenePlan(
            scene_plan_id=f"scene-plan-{script.script_id}",
            script_id=script.script_id,
            research_id=script.research_id,
            format=script.format,
            target_seconds=script.target_seconds,
            planned_seconds=round(sum(scene.duration_seconds for scene in scenes), 2),
            scenes=scenes,
            created_at=datetime.now(timezone.utc),
        )
    except ValidationError as exc:
        raise ScenePlanningError(INVALID_SCENE_OUTPUT) from exc


class ScenePlanner:
    def __init__(self, client: GeminiClient):
        self._client = client

    def plan(self, script: VideoScript) -> ScenePlan:
        if not isinstance(script, VideoScript):
            raise ValueError("script must be a VideoScript instance.")
        segment_payload = [
            {
                "segment_id": segment.segment_id,
                "order": segment.order,
                "type": segment.segment_type,
                "duration_seconds": segment.duration_seconds,
                "narration": segment.narration,
                "purpose": segment.purpose,
            }
            for segment in script.segments
        ]
        try:
            content = self._client.generate_json(
                system=(
                    "You are a visual scene designer. Return only structured scene designs. "
                    "Use only the supplied scene types, composition presets, layout, motion, "
                    "text roles, and transitions. "
                    "Group every script segment exactly once, in order. Do not rewrite narration. "
                    "IDs, timing, or invent unsupported visual primitives."
                ),
                prompt=(
                    f"Design renderer-friendly scenes for a {script.format} video.\n"
                    "Available segment IDs and narration (JSON): "
                    f"{json.dumps(segment_payload, ensure_ascii=False)}\n"
                    "Choose practical groups of consecutive segments and keep visual descriptions "
                    "short and concrete. Select composition.preset for every scene: headline, number_explainer, "
                    "comparison_two, comparison_three, timeline, process_walkthrough, "
                    "quote_callout, diagram, split_visual, or hero_overlay. Match the preset "
                    "to the storytelling purpose; use comparison_three only when three "
                    "distinct items are present. Any on-screen text must be an exact excerpt from the "
                    "referenced narration; do not add facts, metrics, or wording. Use overlays "
                    "sparingly. A graphic is optional; if used, every datum label and numeric "
                    "value_text and graphic title must be copied exactly from source_excerpt, and source_excerpt "
                    "must be an exact substring of that scene's narration. Never infer or invent "
                    "chart values. Use number_counter or progress graphics only for one datum; "
                    "use bar_chart or line_graph for multiple narrated data points. "
                    "Return ScenePlanContent."
                ),
                schema=ScenePlanContent,
                temperature=0.3,
            )
        except GeminiError as exc:
            message = str(exc)
            if "does not match" in message or "empty JSON" in message:
                raise ScenePlanningError(INVALID_SCENE_OUTPUT) from None
            raise ScenePlanningError("Scene planning request failed.") from None
        return _assemble(content, script)


_TYPE_BY_SEGMENT = {
    "hook": "title",
    "setup": "text_focus",
    "context": "illustration",
    "explanation": "process",
    "revelation": "statistic",
    "transition": "comparison",
    "payoff": "conclusion",
    "conclusion": "conclusion",
}


def _mock_design(segment: ScriptSegment) -> SceneDesign:
    scene_type = _TYPE_BY_SEGMENT[segment.segment_type]
    overlay_text = segment.narration.split(".", maxsplit=1)[0].strip()[:240]
    layout = (
        "centered"
        if scene_type in {"title", "text_focus", "conclusion"}
        else "stacked"
    )
    role = "title" if scene_type in {"title", "conclusion"} else "label"
    return SceneDesign(
        scene_type=scene_type,
        script_segment_ids=[segment.segment_id],
        visual_description=segment.purpose[:1000],
        composition=SceneComposition(
            preset=_DEFAULT_PRESET_BY_TYPE[scene_type],
            layout=layout,
            alignment="center",
            hierarchy=(
                "text_first"
                if scene_type in {"title", "text_focus", "conclusion"}
                else "balanced"
            ),
            viewport="static",
        ),
        motion=SceneMotion(entrance="fade", exit="none", emphasis="none"),
        on_screen_text=[OnScreenText(text=overlay_text, role=role)],
        transition=SceneTransition(type="cut", duration_seconds=0),
    )


class MockScenePlanner:
    """Deterministic visual mapping that keeps each script beat intact."""

    def plan(self, script: VideoScript) -> ScenePlan:
        if not isinstance(script, VideoScript):
            raise ValueError("script must be a VideoScript instance.")
        return _assemble(
            ScenePlanContent(
                scenes=[_mock_design(segment) for segment in script.segments]
            ),
            script,
        )
