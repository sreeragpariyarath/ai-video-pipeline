import sys
import traceback
import types as module_types
from types import SimpleNamespace

import pytest
import requests

from orchestrator.search_provider import SearchError, TransientSearchError
from orchestrator.tavily_provider import TavilySearchProvider


KEY = "tvly-fake-test-key-not-real"


@pytest.fixture
def fake_tavily(monkeypatch):
    """Inject a fake tavily SDK so the provider never touches the network."""
    errors_mod = module_types.ModuleType("tavily.errors")

    class UsageLimitExceededError(Exception):
        pass

    class TavilyKeylessLimitError(UsageLimitExceededError):
        def __init__(self, message="keyless limit", retry_after_seconds=None):
            super().__init__(message)
            self.retry_after_seconds = retry_after_seconds

    class BadRequestError(Exception):
        pass

    class ForbiddenError(Exception):
        pass

    class InvalidAPIKeyError(Exception):
        pass

    class MissingAPIKeyError(Exception):
        pass

    class KeylessUnsupportedEndpointError(Exception):
        pass

    class TimeoutError(Exception):
        pass

    for cls in (
        UsageLimitExceededError,
        TavilyKeylessLimitError,
        BadRequestError,
        ForbiddenError,
        InvalidAPIKeyError,
        MissingAPIKeyError,
        KeylessUnsupportedEndpointError,
        TimeoutError,
    ):
        setattr(errors_mod, cls.__name__, cls)

    state = SimpleNamespace(responses=[], calls=[], api_key=None, errors=errors_mod)

    class FakeTavilyClient:
        def __init__(self, api_key=None, **kwargs):
            state.api_key = api_key

        def search(self, **kwargs):
            state.calls.append(kwargs)
            if not state.responses:
                raise AssertionError("fake Tavily ran out of scripted responses")
            item = state.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    tavily_mod = module_types.ModuleType("tavily")
    tavily_mod.TavilyClient = FakeTavilyClient
    tavily_mod.errors = errors_mod

    monkeypatch.setitem(sys.modules, "tavily", tavily_mod)
    monkeypatch.setitem(sys.modules, "tavily.errors", errors_mod)
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    return state


@pytest.fixture
def tavily_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr("orchestrator.tavily_provider.time.sleep", sleeps.append)
    return sleeps


def ok_response(results=None):
    if results is None:
        results = [
            {
                "title": "Example article",
                "url": "https://example.com/article",
                "content": "A snippet.",
                "score": 0.8,
                "published_date": "2026-05-01",
            }
        ]
    return {"results": results}


def make_provider(**kwargs):
    return TavilySearchProvider(api_key=KEY, **kwargs)


def test_missing_api_key_raises_actionable_error(monkeypatch, fake_tavily):
    monkeypatch.delenv("TAVILY_API_KEY")
    with pytest.raises(SearchError, match="TAVILY_API_KEY"):
        TavilySearchProvider()
    assert fake_tavily.calls == []


def test_blank_api_key_rejected(monkeypatch, fake_tavily):
    monkeypatch.setenv("TAVILY_API_KEY", "   ")
    with pytest.raises(SearchError, match="TAVILY_API_KEY"):
        TavilySearchProvider()


def test_missing_sdk_raises_clear_error(monkeypatch, fake_tavily):
    monkeypatch.setitem(sys.modules, "tavily", None)
    with pytest.raises(SearchError, match="tavily-python is not installed"):
        make_provider()


def test_key_from_environment(monkeypatch, fake_tavily):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-env-key")
    provider = TavilySearchProvider()
    assert fake_tavily.api_key == "tvly-env-key"
    fake_tavily.responses.append(ok_response())
    provider.search("q")


def test_explicit_key_overrides_environment(fake_tavily):
    make_provider()
    assert fake_tavily.api_key == KEY


def test_maps_tavily_response_to_search_results(fake_tavily):
    fake_tavily.responses.append(ok_response())
    results = make_provider().search("streaming prices", max_results=5)
    assert len(results) == 1
    result = results[0]
    assert result.title == "Example article"
    assert result.url == "https://example.com/article"
    assert result.snippet == "A snippet."
    assert result.relevance_score == 0.8
    assert result.published_date.isoformat() == "2026-05-01"


def test_passes_query_max_results_and_timeout(fake_tavily):
    fake_tavily.responses.append(ok_response())
    make_provider(timeout_seconds=7.5).search("my query", max_results=3)
    assert fake_tavily.calls == [
        {"query": "my query", "max_results": 3, "timeout": 7.5}
    ]


def test_truncates_results_to_max_results(fake_tavily):
    items = [
        {"title": f"A{i}", "url": f"https://example.com/{i}", "score": 0.5}
        for i in range(6)
    ]
    fake_tavily.responses.append(ok_response(items))
    results = make_provider().search("q", max_results=2)
    assert len(results) == 2


@pytest.mark.parametrize(
    "bad_item",
    [
        {"url": "https://example.com"},
        {"title": "T"},
        {"title": "T", "url": "ftp://example.com"},
        {"title": "T", "url": "https://example.com", "score": 5.0},
        {"title": "", "url": "https://example.com"},
        "not a dict",
        None,
    ],
)
def test_malformed_results_are_skipped(fake_tavily, bad_item):
    good = {"title": "Good", "url": "https://example.com/good"}
    fake_tavily.responses.append(ok_response([bad_item, good]))
    results = make_provider().search("q")
    assert [r.title for r in results] == ["Good"]


def test_non_iso_published_date_becomes_none(fake_tavily):
    item = {
        "title": "T",
        "url": "https://example.com/a",
        "published_date": "Mon, 02 Aug 2026 10:00:00 GMT",
    }
    fake_tavily.responses.append(ok_response([item]))
    results = make_provider().search("q")
    assert len(results) == 1
    assert results[0].published_date is None


@pytest.mark.parametrize("raw", [{}, {"results": "nope"}, [], None, "text"])
def test_unusable_response_shape_raises(fake_tavily, raw):
    fake_tavily.responses.append(raw)
    with pytest.raises(SearchError, match="without a results list"):
        make_provider().search("q")


def test_timeout_retries_then_succeeds(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [fake_tavily.errors.TimeoutError("timed out"), ok_response()]
    )
    results = make_provider().search("q")
    assert len(results) == 1
    assert len(fake_tavily.calls) == 2
    assert tavily_sleeps == [1]


def test_timeout_exhausts_retries(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [fake_tavily.errors.TimeoutError("timed out")] * 3
    )
    with pytest.raises(TransientSearchError, match="timed out"):
        make_provider().search("q")
    assert len(fake_tavily.calls) == 3
    assert tavily_sleeps == [1, 2]


def test_quota_exhaustion_is_permanent_not_retried(fake_tavily, tavily_sleeps):
    fake_tavily.responses.append(
        fake_tavily.errors.UsageLimitExceededError("monthly quota exceeded")
    )
    with pytest.raises(SearchError) as excinfo:
        make_provider().search("q")
    assert not isinstance(excinfo.value, TransientSearchError)
    assert len(fake_tavily.calls) == 1
    assert tavily_sleeps == []


def test_keyless_limit_honors_bounded_retry_after(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [
            fake_tavily.errors.TavilyKeylessLimitError(
                "window limit", retry_after_seconds=5
            ),
            ok_response(),
        ]
    )
    assert len(make_provider().search("q")) == 1
    assert len(fake_tavily.calls) == 2
    assert tavily_sleeps == [5.0]


def test_keyless_limit_without_retry_after_uses_backoff(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [fake_tavily.errors.TavilyKeylessLimitError("window limit"), ok_response()]
    )
    assert len(make_provider().search("q")) == 1
    assert tavily_sleeps == [1]


@pytest.mark.parametrize("retry_after", [31, 3600, -1, float("nan"), float("inf"), True, "soon"])
def test_keyless_limit_unsafe_retry_after_does_not_retry(
    fake_tavily, tavily_sleeps, retry_after
):
    fake_tavily.responses.append(
        fake_tavily.errors.TavilyKeylessLimitError(
            "window limit", retry_after_seconds=retry_after
        )
    )
    with pytest.raises(TransientSearchError):
        make_provider().search("q")
    assert len(fake_tavily.calls) == 1
    assert tavily_sleeps == []


def test_keyless_limit_retry_after_boundary_is_honored(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [
            fake_tavily.errors.TavilyKeylessLimitError(
                "window limit", retry_after_seconds=30
            ),
            ok_response(),
        ]
    )
    assert len(make_provider().search("q")) == 1
    assert tavily_sleeps == [30.0]


def test_keyless_limit_retry_after_exhausts_retries(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [
            fake_tavily.errors.TavilyKeylessLimitError(
                "window limit", retry_after_seconds=2
            )
        ] * 3
    )
    with pytest.raises(TransientSearchError):
        make_provider().search("q")
    assert len(fake_tavily.calls) == 3
    assert tavily_sleeps == [2.0, 2.0]


def test_raw_http_429_is_permanent(fake_tavily, tavily_sleeps):
    error = requests.exceptions.HTTPError(
        "429 Too Many Requests", response=SimpleNamespace(status_code=429)
    )
    fake_tavily.responses.append(error)
    with pytest.raises(SearchError) as excinfo:
        make_provider().search("q")
    assert not isinstance(excinfo.value, TransientSearchError)
    assert len(fake_tavily.calls) == 1
    assert tavily_sleeps == []


def test_server_http_error_is_transient(fake_tavily, tavily_sleeps):
    error = requests.exceptions.HTTPError(
        "503 Server Error", response=SimpleNamespace(status_code=503)
    )
    fake_tavily.responses.extend([error, ok_response()])
    assert len(make_provider().search("q")) == 1
    assert len(fake_tavily.calls) == 2


def test_client_http_error_is_permanent(fake_tavily, tavily_sleeps):
    error = requests.exceptions.HTTPError(
        "404 Not Found", response=SimpleNamespace(status_code=404)
    )
    fake_tavily.responses.append(error)
    with pytest.raises(SearchError) as excinfo:
        make_provider().search("q")
    assert not isinstance(excinfo.value, TransientSearchError)
    assert len(fake_tavily.calls) == 1
    assert tavily_sleeps == []


def test_invalid_api_key_is_permanent(fake_tavily, tavily_sleeps):
    fake_tavily.responses.append(fake_tavily.errors.InvalidAPIKeyError("bad key"))
    with pytest.raises(SearchError) as excinfo:
        make_provider().search("q")
    assert not isinstance(excinfo.value, TransientSearchError)
    assert len(fake_tavily.calls) == 1
    assert tavily_sleeps == []


def test_connection_error_is_transient(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [requests.exceptions.ConnectionError("reset"), ok_response()]
    )
    assert len(make_provider().search("q")) == 1
    assert len(fake_tavily.calls) == 2


def test_zero_retries_means_single_attempt(fake_tavily, tavily_sleeps):
    fake_tavily.responses.append(fake_tavily.errors.TimeoutError("timed out"))
    with pytest.raises(TransientSearchError):
        make_provider(max_retries=0).search("q")
    assert len(fake_tavily.calls) == 1
    assert tavily_sleeps == []


def test_api_key_never_leaks_in_error_messages(fake_tavily, tavily_sleeps):
    fake_tavily.responses.append(
        fake_tavily.errors.BadRequestError(f"invalid request for key {KEY}")
    )
    with pytest.raises(SearchError) as excinfo:
        make_provider().search("q")
    assert KEY not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


def test_api_key_never_leaks_through_exception_chain_or_traceback(
    fake_tavily, tavily_sleeps
):
    fake_tavily.responses.append(
        fake_tavily.errors.BadRequestError(f"invalid request for key {KEY}")
    )
    with pytest.raises(SearchError) as excinfo:
        make_provider().search("q")
    error = excinfo.value
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    formatted = "".join(traceback.format_exception(error))
    assert KEY not in formatted
    assert "[redacted]" in formatted


def test_transient_exhaustion_also_suppresses_chain(fake_tavily, tavily_sleeps):
    fake_tavily.responses.extend(
        [fake_tavily.errors.TimeoutError(f"timed out with key {KEY}")] * 3
    )
    with pytest.raises(TransientSearchError) as excinfo:
        make_provider().search("q")
    error = excinfo.value
    assert error.__cause__ is None
    assert KEY not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize(
    "timeout", [0, -1, True, False, "15", None, float("nan"), float("inf")]
)
def test_invalid_timeout_rejected(fake_tavily, timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        make_provider(timeout_seconds=timeout)
    assert fake_tavily.calls == []


@pytest.mark.parametrize("retries", [-1, 6, True, False, 1.5, "2", None])
def test_invalid_max_retries_rejected(fake_tavily, retries):
    with pytest.raises(ValueError, match="max_retries"):
        make_provider(max_retries=retries)
    assert fake_tavily.calls == []