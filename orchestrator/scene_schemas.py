from __future__ import annotations

from datetime import datetime, timezone
import math
import re
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
CompositionPreset = Literal[
    "auto",
    "headline",
    "number_explainer",
    "comparison_two",
    "comparison_three",
    "timeline",
    "process_walkthrough",
    "quote_callout",
    "diagram",
    "split_visual",
    "hero_overlay",
]
Alignment = Literal["start", "center", "end"]
VisualHierarchy = Literal["text_first", "visual_first", "balanced"]
ViewportTreatment = Literal["static", "push_in", "pull_out", "pan_left", "pan_right"]
MotionType = Literal[
    "none", "fade", "slide_up", "slide_down", "slide_left", "slide_right",
    "scale", "pop", "blur_reveal"
]
EmphasisMotion = Literal["none", "pulse", "scale", "underline"]
TextRole = Literal["title", "subtitle", "label", "emphasis", "caption"]
TransitionType = Literal["cut", "fade", "slide"]
GraphicType = Literal[
    "bar_chart", "line_graph", "progress_bar", "percentage_ring", "number_counter"
]

DURATION_TOLERANCE_SECONDS = 0.01
MAX_TRANSITION_SECONDS = 2.0


class SceneModel(BaseModel):
    """Base for renderer-facing artifacts with a closed field vocabulary."""

    model_config = ConfigDict(extra="forbid")


class SceneComposition(SceneModel):
    preset: CompositionPreset = "auto"
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


class GraphicDatum(SceneModel):
    label: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    value_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
    ]

    @model_validator(mode="after")
    def _check_value(self) -> GraphicDatum:
        if not re.fullmatch(
            r"[\$€£]?-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\s*(?:%|[KMBT])?",
            self.value_text,
            re.I,
        ):
            raise ValueError("graphic values must be numeric text with an optional unit")
        return self


class SceneGraphic(SceneModel):
    """A renderer-owned visualization whose labels and values cite narration verbatim."""

    kind: GraphicType
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]
    source_excerpt: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
    ]
    data: list[GraphicDatum] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _check_data(self) -> SceneGraphic:
        if self.kind == "percentage_ring" and len(self.data) != 1:
            raise ValueError("percentage_ring graphics must have exactly one datum")
        if self.kind == "number_counter" and len(self.data) != 1:
            raise ValueError("number_counter graphics must have exactly one datum")
        if self.kind == "progress_bar" and len(self.data) != 1:
            raise ValueError("progress_bar graphics must have exactly one datum")
        if len({item.label.casefold() for item in self.data}) != len(self.data):
            raise ValueError("graphic labels must be unique")
        if self.title not in self.source_excerpt:
            raise ValueError("graphic title must appear in source_excerpt")
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
    graphic: SceneGraphic | None = None
    transition: SceneTransition = Field(default_factory=SceneTransition)

    @model_validator(mode="after")
    def _check_segments(self) -> Scene:
        if len(set(self.script_segment_ids)) != len(self.script_segment_ids):
            raise ValueError("script_segment_ids must not contain duplicates")
        if self.graphic is not None:
            excerpt = self.graphic.source_excerpt
            if self.graphic.source_excerpt not in self.narration_text:
                raise ValueError("graphic source_excerpt must be an exact narration excerpt")
            for datum in self.graphic.data:
                if datum.label not in excerpt or datum.value_text not in excerpt:
                    raise ValueError("graphic labels and values must appear in source_excerpt")
                if not math.isfinite(_graphic_number(datum.value_text)):
                    raise ValueError("graphic values must be finite")
            if self.graphic.kind in {"progress_bar", "percentage_ring"}:
                value = _graphic_number(self.graphic.data[0].value_text)
                if not 0 <= value <= 100:
                    raise ValueError("progress graphics require a value from 0 to 100")
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


def _graphic_number(value_text: str) -> float:
    normalized = value_text.strip().replace(",", "")
    match = re.fullmatch(r"[\$€£]?(-?\d+(?:\.\d+)?)\s*([KMBT%]?)", normalized, re.I)
    if match is None:
        raise ValueError("graphic value must be numeric")
    number = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(suffix, 1)
    return number * multiplier


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
