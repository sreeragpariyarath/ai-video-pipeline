from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


SceneType = Literal["hook", "explainer", "example", "payoff", "cta"]
VisualComponent = Literal["AnimatedText", "SimpleDiagram"]


class Fact(BaseModel):
    claim: str
    source: str


class Source(BaseModel):
    title: str
    url: str


class ResearchSummary(BaseModel):
    summary: str
    facts: list[Fact]


class Hook(BaseModel):
    text: str
    alternatives: list[str]


class Script(BaseModel):
    narration: str
    beats: list[str]


class VisualSpec(BaseModel):
    component: VisualComponent
    headline: str
    subheadline: str | None = None
    items: list[str] | None = None


class SceneSpec(BaseModel):
    type: SceneType
    durationSeconds: float
    narration: str
    visual: VisualSpec
    sources: list[str] = Field(default_factory=list)


class ScenePlan(BaseModel):
    scenes: list[SceneSpec]


@dataclass(frozen=True)
class ResearchBundle:
    notes: str
    summary: str
    facts: list[Fact]
    sources: list[Source]
