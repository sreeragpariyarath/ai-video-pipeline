from __future__ import annotations

import math

from . import prompts
from .gemini import GeminiClient, GeminiError
from .schemas import (
    Fact,
    Hook,
    ResearchBundle,
    ResearchSummary,
    LegacyScenePlan,
    Script,
    Source,
)
from .validation import MAX_SCENES, MIN_SCENES, SCENE_MAX_SECONDS, SCENE_MIN_SECONDS


class GeminiEngine:
    def __init__(self, client: GeminiClient):
        self._client = client

    def research(self, topic: str, target_seconds: float) -> ResearchBundle:
        notes, raw_sources = self._client.generate_grounded(
            system=prompts.RESEARCH_SYSTEM,
            prompt=prompts.research_prompt(topic, target_seconds),
        )
        if not raw_sources:
            raise GeminiError(
                "Gemini research returned no web sources. Re-run the job, or use --mock "
                "to exercise the pipeline offline."
            )
        sources = [Source(title=item["title"], url=item["url"]) for item in raw_sources]
        extracted = self._client.generate_json(
            system=prompts.RESEARCH_EXTRACT_SYSTEM,
            prompt=prompts.research_extract_prompt(topic, notes, sources),
            schema=ResearchSummary,
            temperature=0.2,
        )
        return ResearchBundle(
            notes=notes,
            summary=extracted.summary,
            facts=extracted.facts,
            sources=sources,
        )

    def hook(self, topic: str, research: ResearchBundle) -> Hook:
        return self._client.generate_json(
            system=prompts.HOOK_SYSTEM,
            prompt=prompts.hook_prompt(topic, research),
            schema=Hook,
            temperature=0.7,
        )

    def write_script(
        self,
        topic: str,
        research: ResearchBundle,
        hook: Hook,
        target_seconds: float,
    ) -> Script:
        return self._client.generate_json(
            system=prompts.SCRIPT_SYSTEM,
            prompt=prompts.script_prompt(topic, research, hook, target_seconds),
            schema=Script,
            temperature=0.6,
        )

    def breakdown(
        self,
        topic: str,
        research: ResearchBundle,
        hook: Hook,
        script: Script,
        target_seconds: float,
    ) -> LegacyScenePlan:
        return self._client.generate_json(
            system=prompts.BREAKDOWN_SYSTEM,
            prompt=prompts.breakdown_prompt(
                topic, research, hook, script, target_seconds
            ),
            schema=LegacyScenePlan,
            temperature=0.3,
        )


_MOCK_SOURCES = [
    Source(title="Mock source 1", url="https://example.com/mock-source-1"),
    Source(title="Mock source 2", url="https://example.com/mock-source-2"),
    Source(title="Mock source 3", url="https://example.com/mock-source-3"),
]

_MOCK_HOOK_SECONDS = 2.0
MOCK_MIN_TARGET_SECONDS = 10.0
MOCK_MAX_TARGET_SECONDS = 60.0
_MOCK_PREFERRED_BODY_SCENES = 4


def _mock_hook_text(topic: str) -> str:
    subject = topic.rstrip(" ?.!") or topic
    return f"{subject}. Here is what actually matters."


def _mock_body_count(remaining: float) -> int:
    count = _MOCK_PREFERRED_BODY_SCENES
    if remaining > count * SCENE_MAX_SECONDS:
        count = min(MAX_SCENES - 1, math.ceil(remaining / SCENE_MAX_SECONDS))
    elif remaining < count * SCENE_MIN_SECONDS:
        count = max(MIN_SCENES - 1, math.floor(remaining / SCENE_MIN_SECONDS))
    return count


def _mock_scenes(topic: str, target_seconds: float) -> list[dict]:
    if not MOCK_MIN_TARGET_SECONDS <= target_seconds <= MOCK_MAX_TARGET_SECONDS:
        raise ValueError(
            f"MockEngine supports target durations from {MOCK_MIN_TARGET_SECONDS:g} to "
            f"{MOCK_MAX_TARGET_SECONDS:g} seconds (got {target_seconds:g}). "
            "Choose a --target-seconds value in that range."
        )
    remaining = target_seconds - _MOCK_HOOK_SECONDS
    count = _mock_body_count(remaining)
    # Split in whole tenths of a second so the total is exact and deterministic.
    base, extra = divmod(round(remaining * 10), count)
    durations = [(base + (1 if index < extra else 0)) / 10 for index in range(count)]

    bodies = [
        {
            "type": "explainer",
            "narration": (
                "Strip away the surface details and the same pattern appears. "
                "A few forces do most of the work, and the rest is noise."
            ),
            "visual": {
                "component": "SimpleDiagram",
                "headline": "The pattern",
                "items": ["Forces", "Result", "Noise"],
            },
            "sources": [_MOCK_SOURCES[0].url],
        },
        {
            "type": "explainer",
            "narration": (
                "That pattern matters because it changes what you should look at first. "
                "Most people start with the visible result instead of the underlying cause."
            ),
            "visual": {
                "component": "AnimatedText",
                "headline": "Start with the cause",
                "subheadline": "Results come later",
            },
            "sources": [_MOCK_SOURCES[1].url],
        },
        {
            "type": "example",
            "narration": (
                "Take a simple comparison: one approach adds pressure, while the other removes "
                "friction. The second usually wins because it works with human behavior."
            ),
            "visual": {
                "component": "SimpleDiagram",
                "headline": "Two approaches",
                "items": ["Pressure", "Friction", "Behavior"],
            },
            "sources": [_MOCK_SOURCES[2].url],
        },
        {
            "type": "explainer",
            "narration": (
                "There is a second layer to this: the same forces repeat at a larger scale. "
                "Once you see the pattern up close, you start noticing it everywhere."
            ),
            "visual": {
                "component": "SimpleDiagram",
                "headline": "Zoom out",
                "items": ["Same forces", "Larger scale", "Same pattern"],
            },
            "sources": [_MOCK_SOURCES[0].url],
        },
    ][: count - 1]
    bodies.append(
        {
            "type": "payoff",
            "narration": (
                f"So the next time you think about {topic}, look for the friction, "
                "not the headline."
            ),
            "visual": {
                "component": "AnimatedText",
                "headline": "The takeaway",
                "subheadline": "Look for friction",
            },
            "sources": [],
        }
    )

    scenes = [
        {
            "type": "hook",
            "durationSeconds": _MOCK_HOOK_SECONDS,
            "narration": _mock_hook_text(topic),
            "visual": {
                "component": "AnimatedText",
                "headline": topic,
                "subheadline": "The hidden mechanism",
            },
            "sources": [],
        }
    ]
    for body, duration in zip(bodies, durations):
        scenes.append({**body, "durationSeconds": duration})
    return scenes


class MockEngine:
    # target_seconds is accepted for interface parity; mock research is duration-independent.
    def research(self, topic: str, target_seconds: float | None = None) -> ResearchBundle:
        facts = [
            Fact(
                claim=f"Mock fact {index + 1} about {topic}: placeholder detail for pipeline testing.",
                source=source.url,
            )
            for index, source in enumerate(_MOCK_SOURCES)
        ]
        return ResearchBundle(
            notes=f"Offline mock notes about {topic}. No network research was performed.",
            summary=(
                f"Offline mock summary for \"{topic}\". This job exercises the pipeline "
                "end to end without calling Gemini, so the facts and sources are placeholders."
            ),
            facts=facts,
            sources=list(_MOCK_SOURCES),
        )

    def hook(self, topic: str, research: ResearchBundle) -> Hook:
        return Hook(
            text=_mock_hook_text(topic),
            alternatives=[
                f"Most people get {topic} backwards.",
                f"The real story behind {topic} is simpler than it looks.",
            ],
        )

    def write_script(
        self,
        topic: str,
        research: ResearchBundle,
        hook: Hook,
        target_seconds: float,
    ) -> Script:
        scenes = _mock_scenes(topic, target_seconds)
        return Script(
            narration=" ".join(scene["narration"] for scene in scenes),
            beats=[
                "Open with the hook",
                "Reveal the underlying pattern",
                "Explain why the pattern matters",
                "Ground it with a comparison",
                "Close with the takeaway",
            ],
        )

    def breakdown(
        self,
        topic: str,
        research: ResearchBundle,
        hook: Hook,
        script: Script,
        target_seconds: float,
    ) -> LegacyScenePlan:
        return LegacyScenePlan.model_validate(
            {"scenes": _mock_scenes(topic, target_seconds)}
        )
