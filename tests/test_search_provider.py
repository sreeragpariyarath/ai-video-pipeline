import pytest
from pydantic import ValidationError

from orchestrator.search_provider import (
    MockSearchProvider,
    SearchProvider,
    SearchResult,
)


def test_mock_provider_returns_valid_results_without_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    results = MockSearchProvider().search("streaming prices", max_results=5)
    assert len(results) == 5
    assert all(isinstance(result, SearchResult) for result in results)


def test_mock_provider_is_deterministic():
    provider = MockSearchProvider()
    first = provider.search("streaming prices", max_results=5)
    second = provider.search("streaming prices", max_results=5)
    assert first == second


def test_mock_provider_respects_max_results():
    provider = MockSearchProvider()
    assert len(provider.search("q", max_results=1)) == 1
    assert len(provider.search("q", max_results=10)) == 10


def test_mock_provider_queries_share_sources():
    provider = MockSearchProvider()
    urls_a = {r.url for r in provider.search("streaming prices", max_results=8)}
    urls_b = {r.url for r in provider.search("cable costs", max_results=8)}
    assert urls_a & urls_b


def test_mock_provider_scores_and_dates():
    results = MockSearchProvider().search("streaming", max_results=10)
    assert all(0.0 <= r.relevance_score <= 1.0 for r in results)
    assert any(r.published_date is None for r in results)
    assert any(r.published_date is not None for r in results)


@pytest.mark.parametrize("query", ["", "   ", None, 123])
def test_provider_rejects_invalid_queries(query):
    with pytest.raises(ValueError, match="non-empty string"):
        MockSearchProvider().search(query)


@pytest.mark.parametrize("max_results", [0, -1, True, False, 1.5, "5", None])
def test_provider_rejects_invalid_max_results(max_results):
    with pytest.raises(ValueError, match="positive integer"):
        MockSearchProvider().search("q", max_results=max_results)


def test_provider_contract_validates_before_delegate():
    seen = []

    class RecordingProvider(SearchProvider):
        def _search(self, query, *, max_results):
            seen.append((query, max_results))
            return []

    provider = RecordingProvider()
    provider.search("  padded query  ", max_results=3)
    assert seen == [("padded query", 3)]
    with pytest.raises(ValueError):
        provider.search("")
    assert len(seen) == 1


def test_search_result_valid():
    result = SearchResult(
        title="Title",
        url="https://example.com/a",
        snippet="text",
        relevance_score=0.7,
        published_date="2026-05-01",
    )
    assert result.relevance_score == 0.7
    assert result.published_date.isoformat() == "2026-05-01"


def test_search_result_optional_fields_default_none():
    result = SearchResult(title="Title", url="https://example.com/a")
    assert result.snippet is None
    assert result.relevance_score is None
    assert result.published_date is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "url": "https://example.com"},
        {"title": "T", "url": "ftp://example.com"},
        {"title": "T", "url": "not a url"},
        {"title": "T", "url": "https://example.com", "relevance_score": 1.5},
        {"title": "T", "url": "https://example.com", "relevance_score": -0.1},
        {"title": "T", "url": "https://example.com", "relevance_score": True},
        {"title": "T", "url": "https://example.com", "published_date": "not-a-date"},
    ],
)
def test_search_result_rejects_invalid_payloads(payload):
    with pytest.raises(ValidationError):
        SearchResult(**payload)