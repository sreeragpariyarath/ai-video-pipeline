import pytest

from orchestrator import prompts
from orchestrator.engine import GeminiEngine, MockEngine
from orchestrator.gemini import GeminiClient
from orchestrator.schemas import Fact, ResearchSummary
from orchestrator.validation import HOOK_MAX_SECONDS, JobValidationError, validate_job

from conftest import TOPIC, grounding_response, make_response


@pytest.mark.parametrize("target", [15.0, 25.0, 35.0, 60.0])
def test_research_prompt_uses_supplied_target(target):
    prompt = prompts.research_prompt(TOPIC, target)
    assert f"{target:g}-second video" in prompt


@pytest.mark.parametrize("target", [15.0, 25.0, 60.0])
def test_research_prompt_has_no_hardcoded_35(target):
    prompt = prompts.research_prompt(TOPIC, target)
    assert "35-second" not in prompt


def test_research_prompt_requires_target():
    with pytest.raises(TypeError):
        prompts.research_prompt(TOPIC)


def test_gemini_engine_passes_target_to_research_prompt(fake_sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-not-real")
    url = "https://a.example.com/1"
    fake_sdk.responses.extend(
        [
            grounding_response([(url, "Source A", "a.example.com")]),
            make_response(
                parsed=ResearchSummary(
                    summary="A summary.",
                    facts=[Fact(claim="A claim.", source=url)],
                )
            ),
        ]
    )
    engine = GeminiEngine(GeminiClient())
    engine.research(TOPIC, 25.0)
    assert "25-second video" in fake_sdk.calls[0].contents
    assert "35-second" not in fake_sdk.calls[0].contents


def test_hook_word_limit_is_seven():
    assert prompts.HOOK_MAX_WORDS == 7


def test_hook_limit_consistent_across_system_and_user_prompt():
    research = MockEngine().research(TOPIC)
    user_prompt = prompts.hook_prompt(TOPIC, research)
    assert f"at most {prompts.HOOK_MAX_WORDS} words" in prompts.HOOK_SYSTEM
    assert f"at most {prompts.HOOK_MAX_WORDS} words" in user_prompt
    for text in (prompts.HOOK_SYSTEM, user_prompt):
        assert "10 words" not in text
        assert "12 words" not in text


def test_hook_word_limit_fits_max_hook_duration():
    # Narration timing model: ~2.4 spoken words per second (script_prompt).
    assert prompts.HOOK_MAX_WORDS / 2.4 <= HOOK_MAX_SECONDS


def test_hook_prompt_keeps_duration_and_tease_framing():
    research = MockEngine().research(TOPIC)
    user_prompt = prompts.hook_prompt(TOPIC, research)
    assert "1-3 seconds" in user_prompt
    assert "tease the explanation" in user_prompt
    assert "two alternative hooks" in user_prompt


def test_breakdown_prompt_requests_validator_item_range():
    engine = MockEngine()
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    script = engine.write_script(TOPIC, research, hook, 35.0)
    prompt = prompts.breakdown_prompt(TOPIC, research, hook, script, 35.0)
    assert "1-6 short items" in prompt
    assert "2-4 short items" not in prompt


@pytest.mark.parametrize("count", [1, 6])
def test_validator_accepts_prompt_item_range(valid_job, count):
    valid_job["scenes"][1]["visual"]["items"] = [f"item {i}" for i in range(count)]
    validate_job(valid_job)


def test_validator_rejects_items_above_prompt_range(valid_job):
    valid_job["scenes"][1]["visual"]["items"] = [f"item {i}" for i in range(7)]
    with pytest.raises(JobValidationError, match="visual.items must be 1-6"):
        validate_job(valid_job)