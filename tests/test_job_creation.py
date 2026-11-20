import json
import re

import pytest

from orchestrator.engine import MockEngine
from orchestrator.pipeline import build_job, save_job, slugify
from orchestrator.schemas import ScenePlan

from conftest import TOPIC, make_job


def test_build_job_top_level_structure(valid_job):
    assert set(valid_job) == {
        "schemaVersion",
        "jobId",
        "createdAt",
        "topic",
        "status",
        "format",
        "generation",
        "research",
        "hook",
        "script",
        "scenes",
        "durationSeconds",
    }
    assert valid_job["schemaVersion"] == 2
    assert valid_job["status"] == "scripted"
    assert valid_job["topic"] == TOPIC


def test_build_job_format_and_generation(valid_job):
    assert valid_job["format"] == {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "targetDurationSeconds": 35.0,
    }
    assert valid_job["generation"] == {
        "provider": "offline",
        "model": "mock",
        "mode": "mock",
    }


def test_build_job_id_uses_slug_and_utc_timestamp(valid_job):
    assert re.fullmatch(
        r"why-is-netflix-cheaper-than-cable-tv-\d{14}", valid_job["jobId"]
    )


def test_build_job_scene_ids_and_order(valid_job):
    ids = [scene["id"] for scene in valid_job["scenes"]]
    assert ids == ["scene-01", "scene-02", "scene-03", "scene-04", "scene-05"]
    assert valid_job["scenes"][0]["type"] == "hook"


def test_build_job_duration_is_scene_sum(valid_job):
    total = sum(scene["durationSeconds"] for scene in valid_job["scenes"])
    assert valid_job["durationSeconds"] == round(total, 2)


def test_build_job_word_count_matches_narration(valid_job):
    narration = valid_job["script"]["narration"]
    assert valid_job["script"]["wordCount"] == len(narration.split())


def test_build_job_rounds_scene_durations():
    engine = MockEngine()
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    script = engine.write_script(TOPIC, research, hook, 35.0)
    plan = engine.breakdown(TOPIC, research, hook, script, 35.0)
    plan.scenes[1].durationSeconds = 7.777
    job = build_job(
        TOPIC, research, hook, script, plan,
        provider="offline", model="mock", mode="mock", target_seconds=35.0,
    )
    assert job["scenes"][1]["durationSeconds"] == 7.78


def test_build_job_visual_omits_none_fields(valid_job):
    hook_visual = valid_job["scenes"][0]["visual"]
    assert hook_visual["component"] == "AnimatedText"
    assert "subheadline" in hook_visual
    assert "items" not in hook_visual

    diagram_visual = valid_job["scenes"][1]["visual"]
    assert diagram_visual["component"] == "SimpleDiagram"
    assert "items" in diagram_visual
    assert "subheadline" not in diagram_visual


def test_build_job_research_and_hook_shape(valid_job):
    research = valid_job["research"]
    assert set(research) == {"summary", "facts", "sources"}
    assert all(set(fact) == {"claim", "source"} for fact in research["facts"])
    assert all(set(source) == {"title", "url"} for source in research["sources"])
    assert set(valid_job["hook"]) == {"text", "alternatives"}
    assert len(valid_job["hook"]["alternatives"]) == 2


def test_slugify_normal_topic():
    assert slugify("Why is Netflix cheaper than cable TV?") == (
        "why-is-netflix-cheaper-than-cable-tv"
    )


def test_slugify_collapses_punctuation_and_whitespace():
    assert slugify("  Hello,   World!  ") == "hello-world"


def test_slugify_non_latin_falls_back():
    assert slugify("日本語") == "video-topic"


def test_slugify_empty_and_symbol_only_fall_back():
    assert slugify("") == "video-topic"
    assert slugify("!!! ???") == "video-topic"


def test_slugify_truncates_to_64_chars():
    assert slugify("a" * 100) == "a" * 64


def test_slugify_strips_trailing_dash_after_truncation():
    slug = slugify("word " * 30)
    assert len(slug) <= 64
    assert not slug.endswith("-")


def test_save_job_writes_utf8_json_roundtrip(tmp_path):
    job = make_job()
    out = tmp_path / "nested" / "job.json"
    returned = save_job(job, out)
    assert returned == out
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == job


def test_run_rejects_empty_topic():
    from orchestrator.pipeline import run

    with pytest.raises(ValueError, match="Topic must not be empty"):
        run("   ", mock=True)


def test_run_rejects_non_positive_target():
    from orchestrator.pipeline import run

    with pytest.raises(ValueError, match="greater than 0"):
        run(TOPIC, mock=True, target_seconds=0)