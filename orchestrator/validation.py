from __future__ import annotations

import math
from urllib.parse import urlparse


SCENE_TYPES = {"hook", "explainer", "example", "payoff", "cta"}
VISUAL_COMPONENTS = {"AnimatedText", "SimpleDiagram"}

MIN_SCENES = 3
MAX_SCENES = 10
HOOK_MIN_SECONDS = 1.0
HOOK_MAX_SECONDS = 3.0
SCENE_MIN_SECONDS = 2.0
SCENE_MAX_SECONDS = 12.0
DURATION_TOLERANCE_RATIO = 0.08
DURATION_TOLERANCE_FLOOR = 2.0


class JobValidationError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        message = "Job validation failed:\n" + "\n".join(
            f"  - {problem}" for problem in problems
        )
        super().__init__(message)


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_url(value: object) -> bool:
    if not _is_text(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_job(job: dict) -> dict:
    problems: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    check(job.get("schemaVersion") == 2, "schemaVersion must be 2.")
    check(job.get("status") == "scripted", 'status must be "scripted".')
    check(_is_text(job.get("jobId")), "jobId must be a non-empty string.")
    check(_is_text(job.get("topic")), "topic must be a non-empty string.")

    fmt = job.get("format")
    if not isinstance(fmt, dict):
        problems.append("format must be an object.")
        fmt = {}
    check(
        isinstance(fmt.get("width"), int) and not isinstance(fmt.get("width"), bool) and fmt["width"] > 0,
        "format.width must be a positive integer.",
    )
    check(
        isinstance(fmt.get("height"), int) and not isinstance(fmt.get("height"), bool) and fmt["height"] > 0,
        "format.height must be a positive integer.",
    )
    check(
        isinstance(fmt.get("fps"), int) and not isinstance(fmt.get("fps"), bool) and fmt["fps"] > 0,
        "format.fps must be a positive integer.",
    )
    target = fmt.get("targetDurationSeconds")
    target_seconds = float(target) if _is_number(target) and target > 0 else None
    check(target_seconds is not None, "format.targetDurationSeconds must be a positive number.")

    sources: list[str] = []
    fact_count = 0
    research = job.get("research")
    if not isinstance(research, dict):
        problems.append("research must be an object.")
    else:
        check(_is_text(research.get("summary")), "research.summary must be a non-empty string.")

        raw_sources = research.get("sources")
        if not isinstance(raw_sources, list):
            problems.append("research.sources must be a list.")
        else:
            for index, source in enumerate(raw_sources):
                label = f"research.sources[{index}]"
                if not isinstance(source, dict):
                    problems.append(f"{label} must be an object.")
                    continue
                check(_is_text(source.get("title")), f"{label}.title must be a non-empty string.")
                check(_is_url(source.get("url")), f"{label}.url must be an http(s) URL.")
                if _is_url(source.get("url")):
                    sources.append(source["url"])
            check(bool(sources), "research must include at least one source URL.")
            check(
                len(set(sources)) == len(sources),
                "research source URLs must be unique.",
            )

        raw_facts = research.get("facts")
        if not isinstance(raw_facts, list):
            problems.append("research.facts must be a list.")
        else:
            fact_count = len(raw_facts)
            check(fact_count >= 3, "research must include at least 3 facts.")
            allowed_sources = set(sources)
            for index, fact in enumerate(raw_facts):
                label = f"research.facts[{index}]"
                if not isinstance(fact, dict):
                    problems.append(f"{label} must be an object.")
                    continue
                check(_is_text(fact.get("claim")), f"{label}.claim must be a non-empty string.")
                check(_is_url(fact.get("source")), f"{label}.source must be an http(s) URL.")
                if _is_url(fact.get("source")) and fact["source"] not in allowed_sources:
                    problems.append(f"{label}.source must come from research.sources.")

    hook = job.get("hook")
    if not isinstance(hook, dict):
        problems.append("hook must be an object.")
    else:
        check(_is_text(hook.get("text")), "hook.text must be a non-empty string.")
        alternatives = hook.get("alternatives")
        check(
            isinstance(alternatives, list) and len(alternatives) >= 2,
            "hook.alternatives must contain at least 2 hooks.",
        )
        if isinstance(alternatives, list):
            for index, alternative in enumerate(alternatives):
                check(
                    _is_text(alternative),
                    f"hook.alternatives[{index}] must be a non-empty string.",
                )

    script = job.get("script")
    if not isinstance(script, dict):
        problems.append("script must be an object.")
    else:
        check(_is_text(script.get("narration")), "script.narration must be a non-empty string.")
        word_count = script.get("wordCount")
        check(
            isinstance(word_count, int) and not isinstance(word_count, bool) and word_count >= 0,
            "script.wordCount must be a non-negative integer.",
        )
        if _is_text(script.get("narration")) and isinstance(word_count, int) and not isinstance(word_count, bool):
            check(
                word_count == len(script["narration"].split()),
                "script.wordCount must match the narration word count "
                f"(declared {word_count}, found {len(script['narration'].split())}).",
            )
        beats = script.get("beats")
        check(
            isinstance(beats, list) and len(beats) >= 2,
            "script.beats must contain at least 2 beats.",
        )
        if isinstance(beats, list):
            for index, beat in enumerate(beats):
                check(_is_text(beat), f"script.beats[{index}] must be a non-empty string.")

    scenes = job.get("scenes")
    total_seconds = 0.0
    total_is_valid = True
    if not isinstance(scenes, list):
        problems.append("scenes must be a list.")
        scenes = []
    else:
        check(
            MIN_SCENES <= len(scenes) <= MAX_SCENES,
            f"scenes must contain {MIN_SCENES}-{MAX_SCENES} scenes (found {len(scenes)}).",
        )
        allowed_sources = set(sources)
        scene_ids: list[str] = []
        for index, scene in enumerate(scenes):
            label = f"scenes[{index}]"
            if not isinstance(scene, dict):
                problems.append(f"{label} must be an object.")
                continue

            scene_id = scene.get("id")
            check(_is_text(scene_id), f"{label}.id must be a non-empty string.")
            if _is_text(scene_id):
                check(scene_id not in scene_ids, f"{label}.id duplicates {scene_id}.")
                scene_ids.append(scene_id)

            scene_type = scene.get("type")
            check(
                scene_type in SCENE_TYPES,
                f"{label}.type must be one of {sorted(SCENE_TYPES)}.",
            )
            if index == 0:
                check(scene_type == "hook", "The first scene must be type hook.")
            elif scene_type == "hook":
                problems.append("Only the first scene may be type hook.")

            check(_is_text(scene.get("narration")), f"{label}.narration must be a non-empty string.")

            duration = scene.get("durationSeconds")
            if _is_number(duration) and duration > 0:
                total_seconds += duration
                if index == 0:
                    check(
                        HOOK_MIN_SECONDS <= duration <= HOOK_MAX_SECONDS,
                        f"{label}.durationSeconds must be {HOOK_MIN_SECONDS:g}-{HOOK_MAX_SECONDS:g}s "
                        f"for the hook (found {duration:g}s).",
                    )
                else:
                    check(
                        SCENE_MIN_SECONDS <= duration <= SCENE_MAX_SECONDS,
                        f"{label}.durationSeconds must be {SCENE_MIN_SECONDS:g}-{SCENE_MAX_SECONDS:g}s "
                        f"(found {duration:g}s).",
                    )
            else:
                total_is_valid = False
                problems.append(f"{label}.durationSeconds must be a positive number.")

            visual = scene.get("visual")
            if not isinstance(visual, dict):
                problems.append(f"{label}.visual must be an object.")
            else:
                check(
                    visual.get("component") in VISUAL_COMPONENTS,
                    f"{label}.visual.component must be one of {sorted(VISUAL_COMPONENTS)}.",
                )
                check(_is_text(visual.get("headline")), f"{label}.visual.headline must be a non-empty string.")
                subheadline = visual.get("subheadline")
                if subheadline is not None:
                    check(_is_text(subheadline), f"{label}.visual.subheadline must be a non-empty string.")
                items = visual.get("items")
                if items is not None:
                    check(
                        isinstance(items, list)
                        and 1 <= len(items) <= 6
                        and all(_is_text(item) for item in items),
                        f"{label}.visual.items must be 1-6 non-empty strings.",
                    )
                component = visual.get("component")
                if component == "SimpleDiagram":
                    check(items is not None, f"{label}.visual: SimpleDiagram must include items.")
                elif component == "AnimatedText":
                    check(
                        items is None,
                        f"{label}.visual: AnimatedText must not include items; use subheadline instead.",
                    )

            scene_sources = scene.get("sources")
            if not isinstance(scene_sources, list):
                problems.append(f"{label}.sources must be a list.")
            else:
                if all(isinstance(url, str) for url in scene_sources):
                    check(
                        len(set(scene_sources)) == len(scene_sources),
                        f"{label}.sources must not repeat URLs.",
                    )
                for source_index, url in enumerate(scene_sources):
                    check(
                        _is_url(url),
                        f"{label}.sources[{source_index}] must be an http(s) URL.",
                    )
                    if _is_url(url) and url not in allowed_sources:
                        problems.append(
                            f"{label}.sources[{source_index}] must come from research.sources."
                        )

    if total_is_valid and target_seconds is not None:
        tolerance = max(DURATION_TOLERANCE_FLOOR, target_seconds * DURATION_TOLERANCE_RATIO)
        check(
            abs(total_seconds - target_seconds) <= tolerance,
            f"Scene durations total {total_seconds:g}s; expected {target_seconds:g}s "
            f"({tolerance:g}s tolerance).",
        )

    declared_total = job.get("durationSeconds")
    check(
        _is_number(declared_total) and declared_total > 0,
        "durationSeconds must be a positive number.",
    )
    if total_is_valid and _is_number(declared_total):
        check(
            abs(declared_total - total_seconds) <= 0.01,
            f"durationSeconds ({declared_total:g}s) must equal the scene duration sum "
            f"({total_seconds:g}s).",
        )

    if (
        isinstance(hook, dict)
        and _is_text(hook.get("text"))
        and scenes
        and isinstance(scenes[0], dict)
        and _is_text(scenes[0].get("narration"))
    ):
        check(
            scenes[0]["narration"].strip() == hook["text"].strip(),
            "The first scene's narration must match hook.text exactly.",
        )

    if problems:
        raise JobValidationError(problems)

    return {
        "sceneCount": len(scenes),
        "durationSeconds": round(total_seconds, 2),
        "sourceCount": len(set(sources)),
        "factCount": fact_count,
    }
