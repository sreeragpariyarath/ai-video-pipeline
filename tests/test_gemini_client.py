import pytest

from orchestrator.gemini import (
    DEFAULT_MODEL,
    GeminiClient,
    GeminiError,
    _extract_sources,
    _strip_json_fences,
)
from orchestrator.schemas import Hook

from conftest import FakeApiError, grounding_response, make_response


HOOK_JSON = '{"text": "Cable bills hide fees.", "alternatives": ["A", "B"]}'


@pytest.fixture
def client(fake_sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-not-real")
    return GeminiClient()


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(GeminiError, match="No Gemini API key"):
        GeminiClient()


def test_google_api_key_fallback(fake_sdk, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-fallback-key")
    GeminiClient()
    assert fake_sdk.api_key == "fake-fallback-key"


def test_model_resolution(fake_sdk, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-not-real")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert GeminiClient().model == DEFAULT_MODEL
    monkeypatch.setenv("GEMINI_MODEL", "gemini-env-model")
    assert GeminiClient().model == "gemini-env-model"
    assert GeminiClient(model="gemini-explicit").model == "gemini-explicit"


def test_grounded_call_returns_text_and_sources(client, fake_sdk):
    fake_sdk.responses.append(
        grounding_response(
            [
                ("https://a.example.com/1", "Source A", "a.example.com"),
                ("https://b.example.com/2", "Source B", "b.example.com"),
            ],
            text="  research notes  ",
        )
    )
    text, sources = client.generate_grounded(system="sys", prompt="p")
    assert text == "research notes"
    assert sources == [
        {"title": "Source A", "url": "https://a.example.com/1"},
        {"title": "Source B", "url": "https://b.example.com/2"},
    ]
    config = fake_sdk.calls[0].config
    assert config.temperature == 0.2
    assert config.tools  # Google Search tool attached


def test_grounded_call_empty_text_raises(client, fake_sdk):
    fake_sdk.responses.append(make_response(text="   "))
    with pytest.raises(GeminiError, match="empty research response"):
        client.generate_grounded(system="sys", prompt="p")


def test_grounded_call_without_grounding_returns_no_sources(client, fake_sdk):
    fake_sdk.responses.append(make_response(text="notes"))
    text, sources = client.generate_grounded(system="sys", prompt="p")
    assert text == "notes"
    assert sources == []


def test_generate_json_uses_parsed_response(client, fake_sdk):
    parsed = Hook(text="parsed hook", alternatives=["A", "B"])
    fake_sdk.responses.append(make_response(text="ignored", parsed=parsed))
    result = client.generate_json(system="sys", prompt="p", schema=Hook)
    assert result is parsed
    config = fake_sdk.calls[0].config
    assert config.response_mime_type == "application/json"
    assert config.response_schema is Hook


def test_generate_json_falls_back_to_fence_stripped_text(client, fake_sdk):
    fake_sdk.responses.append(
        make_response(text=f"```json\n{HOOK_JSON}\n```", parsed=None)
    )
    result = client.generate_json(system="sys", prompt="p", schema=Hook)
    assert result.text == "Cable bills hide fees."
    assert result.alternatives == ["A", "B"]


def test_generate_json_plain_text_without_fences(client, fake_sdk):
    fake_sdk.responses.append(make_response(text=HOOK_JSON, parsed=None))
    result = client.generate_json(system="sys", prompt="p", schema=Hook)
    assert result.text == "Cable bills hide fees."


def test_generate_json_schema_mismatch_raises(client, fake_sdk):
    fake_sdk.responses.append(make_response(text='{"text": "no alternatives"}'))
    with pytest.raises(GeminiError, match="does not match Hook"):
        client.generate_json(system="sys", prompt="p", schema=Hook)


def test_generate_json_empty_response_raises(client, fake_sdk):
    fake_sdk.responses.append(make_response(text="", parsed=None))
    with pytest.raises(GeminiError, match="empty JSON response"):
        client.generate_json(system="sys", prompt="p", schema=Hook)


def test_retry_on_429_then_success(client, fake_sdk, no_sleep):
    parsed = Hook(text="retry hook", alternatives=["A", "B"])
    fake_sdk.responses.extend([FakeApiError(429), make_response(parsed=parsed)])
    result = client.generate_json(system="sys", prompt="p", schema=Hook)
    assert result is parsed
    assert len(fake_sdk.calls) == 2
    assert no_sleep == [2]


def test_retry_exhaustion_raises(client, fake_sdk, no_sleep):
    fake_sdk.responses.extend([FakeApiError(503)] * 3)
    with pytest.raises(GeminiError, match="Gemini request failed"):
        client.generate_json(system="sys", prompt="p", schema=Hook)
    assert len(fake_sdk.calls) == 3
    assert no_sleep == [2, 4]


def test_non_retryable_error_fails_immediately(client, fake_sdk, no_sleep):
    fake_sdk.responses.append(FakeApiError(400))
    with pytest.raises(GeminiError, match="Gemini request failed"):
        client.generate_json(system="sys", prompt="p", schema=Hook)
    assert len(fake_sdk.calls) == 1
    assert no_sleep == []


def test_no_candidates_raises_with_block_reason(client, fake_sdk):
    feedback = type("Feedback", (), {"block_reason": "SAFETY"})()
    fake_sdk.responses.append(make_response(candidates=[], prompt_feedback=feedback))
    with pytest.raises(GeminiError, match="no candidates .*blocked: SAFETY"):
        client.generate_json(system="sys", prompt="p", schema=Hook)


def test_extract_sources_dedupes_across_candidates():
    response = grounding_response(
        [
            ("https://a.example.com/1", "A", "a.example.com"),
            ("https://a.example.com/1", "A again", "a.example.com"),
        ]
    )
    response.candidates.append(
        grounding_response([("https://a.example.com/1", "A third", "a.example.com")]).candidates[0]
    )
    sources = _extract_sources(response)
    assert sources == [{"title": "A", "url": "https://a.example.com/1"}]


def test_extract_sources_title_falls_back_to_domain_then_url():
    response = grounding_response(
        [
            ("https://a.example.com/1", "", "a.example.com"),
            ("https://b.example.com/2", "", ""),
            ("", "no uri", "c.example.com"),
        ]
    )
    sources = _extract_sources(response)
    assert sources == [
        {"title": "a.example.com", "url": "https://a.example.com/1"},
        {"title": "https://b.example.com/2", "url": "https://b.example.com/2"},
    ]


def test_extract_sources_handles_missing_metadata():
    assert _extract_sources(make_response()) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Here you go:\n```json\n{"a": 1}\n```\nHope that helps', '{"a": 1}'),
        ('  {"a": 1}  ', '{"a": 1}'),
    ],
)
def test_strip_json_fences(raw, expected):
    assert _strip_json_fences(raw) == expected