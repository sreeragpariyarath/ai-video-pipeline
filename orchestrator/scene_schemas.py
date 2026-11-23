from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from .research_schemas import NonEmptyStr, PositiveSeconds, _reject_bool


PositiveInt = Annotated[int, Field(ge=1), BeforeValidator(_reject_bool)]
NonNegativeSeconds = Annotated[
    float, Field(ge=0, allow_inf_nan=False), BeforeValidator(_reject_bool)
]
SceneType = Literal[
    "title",
    "text_focus",
    "statistic",
    "comparison",
    "process",
    "diagram",
    "timeline",
    "illustration",
    "conclusion",
]
Layout = Literal["centered", "split", "stacked", "full_bleed", "grid"]
Alignment = Literal["start", "center", "end"]
VisualHierarchy = Literal["text_first", "visual_first", "balanced"]
ViewportTreatment = Literal["static", "push_in", "pull_out", "pan_left", "pan_right"]
MotionType = Literal[
    "none", "fade", "slide_up", "slide_down", "slide_left", "slide_right", "scale"
]
EmphasisMotion = Literal["none", "pulse", "scale", "underline"]
TextRole = Literal["title", "subtitle", "label", "emphasis", "caption"]
TransitionType = Literal["cut", "fade", "slide"]

DURATION_TOLERANCE_SECONDS = 0.01
MAX_TRANSITION_SECONDS = 2.0


class SceneModel(BaseModel):
    """Base for renderer-facing artifacts with a closed field vocabulary."""

    model_config = ConfigDict(extra="forbid")


class SceneComposition(SceneModel):
    layout: Layout
    alignment: Alignment = "center"
    hierarchy: VisualHierarchy = "balanced"
    viewport: ViewportTreatment = "static"


class SceneMotion(SceneModel):
    entrance: MotionType = "fade"
    exit: MotionType = "none"
    emphasis: EmphasisMotion = "none"


class OnScreenText(SceneModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
    ]
    role: TextRole | None = None
    start_seconds: NonNegativeSeconds | None = None
    duration_seconds: PositiveSeconds | None = None


class SceneTransition(SceneModel):
    type: TransitionType = "cut"
    duration_seconds: NonNegativeSeconds = 0.0

    @model_validator(mode="after")
    def _check_duration(self) -> SceneTransition:
        if self.type == "cut" and self.duration_seconds != 0:
            raise ValueError("cut transitions must have zero duration")
        if self.type != "cut" and not (
            0 < self.duration_seconds <= MAX_TRANSITION_SECONDS
        ):
            raise ValueError("fade and slide transitions must be 0-2 seconds")
        return self


class Scene(SceneModel):
    scene_id: NonEmptyStr
    order: PositiveInt
    scene_type: SceneType
    duration_seconds: PositiveSeconds
    script_segment_ids: list[NonEmptyStr] = Field(min_length=1)
    narration_text: NonEmptyStr
    visual_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    composition: SceneComposition
    motion: SceneMotion = Field(default_factory=SceneMotion)
    on_screen_text: list[OnScreenText] = Field(default_factory=list)
    transition: SceneTransition = Field(default_factory=SceneTransition)

    @model_validator(mode="after")
    def _check_segments(self) -> Scene:
        if len(set(self.script_segment_ids)) != len(self.script_segment_ids):
            raise ValueError("script_segment_ids must not contain duplicates")
        for index, item in enumerate(self.on_screen_text):
            start = item.start_seconds or 0.0
            if item.start_seconds is not None and start >= self.duration_seconds:
                raise ValueError(
                    f"on_screen_text[{index}].start_seconds must be within the scene"
                )
            if (
                item.duration_seconds is not None
                and start + item.duration_seconds > self.duration_seconds
            ):
                raise ValueError(
                    f"on_screen_text[{index}] timing must fit within the scene"
                )
        if self.transition.duration_seconds >= self.duration_seconds:
            if self.transition.duration_seconds > 0:
                raise ValueError("transition duration must be shorter than the scene")
        return self


class ScenePlan(SceneModel):
    scene_plan_id: NonEmptyStr
    script_id: NonEmptyStr
    research_id: NonEmptyStr
    format: Literal["short", "mid_form", "long_form"]
    target_seconds: PositiveSeconds
    planned_seconds: PositiveSeconds
    scenes: list[Scene] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _check_consistency(self) -> ScenePlan:
        problems: list[str] = []
        ids = [scene.scene_id for scene in self.scenes]
        if len(set(ids)) != len(ids):
            problems.append("scene IDs must be unique")
        orders = [scene.order for scene in self.scenes]
        if orders != list(range(1, len(self.scenes) + 1)):
            problems.append("scene order must be sequential and start at 1")
        total = sum(scene.duration_seconds for scene in self.scenes)
        if abs(self.planned_seconds - total) > DURATION_TOLERANCE_SECONDS:
            problems.append(
                "planned_seconds "
                f"({self.planned_seconds:g}) must match scene duration sum ({total:g})"
            )
        if problems:
            raise ValueError("; ".join(problems))
        return self
