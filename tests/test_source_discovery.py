from datetime import date

import pytest
from pydantic import ValidationError

from orchestrator.discovery_schemas import (
    DiscoveryCandidate,
    DiscoveryResult,
    QueryReport,
)
from orchestrator.research_planner import MockResearchPlanner
from orchestrator.research_schemas import (
    ResearchPlan,
    ResearchQuestion,
    SearchQuery,
    SourcePreferences,
    StoryDirection,
)
from orchestrator.search_provider import (
    MockSearchProvider,
    SearchError,
    SearchProvider,
    SearchResult,
    TransientSearchError,
)
from orchestrator.source_discovery import (
    DiscoveryConfig,
    SourceDiscovery,
    canonicalize_url,
    classify_tier,
    rank_candidates,
)


def make_plan(search_queries=None, *, prefer_primary=True):
    questions = [
        ResearchQuestion(
            question_id=f"q{i}",
            question=f"Question {i}?",
            reason="reason",
            priority="high",
            expected_evidence="evidence",
        )
        for i in (1, 2)
    ]
    queries = search_queries or [
        SearchQuery(query="alpha search", question_ids=["q1"], purpose="purpose"),
        SearchQuery(query="beta search", question_ids=["q2"], purpose="purpose"),
    ]
    return ResearchPlan(
        topic="Streaming prices",
        core_question="Core question?",
        research_questions=questions,
        search_queries=queries,
        source_preferences=SourcePreferences(
            preferred_categories=["official statistics"],
            avoid_or_caution=[],
            prefer_primary_sources=prefer_primary,
        ),
        story_directions=[
            StoryDirection(angle="Angle", description="Description", questions_to_explore=["q1"])
        ],
        target_audience="viewers",
        target_seconds=35.0,
    )


def result(url, title="Title", snippet=None, score=None, published=None):
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet,
        relevance_score=score,
        published_date=published,
    )


class ScriptedProvider(SearchProvider):
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def _search(self, query, *, max_results):
        self.calls.append(query)
        item = self._responses.get(query, [])
        if isinstance(item, Exception):
            raise item
        return list(item)[:max_results]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM/path", "https://example.com/path"),
        ("https://example.com/path#section", "https://example.com/path"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com/?utm_source=x", "https://example.com"),
        ("https://example.com?id=7", "https://example.com/?id=7"),
        ("https://example.com/article/", "https://example.com/article/"),
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://user:pass@example.com/a", "https://example.com/a"),
        (
            "https://example.com/?utm_source=x&utm_medium=y&id=7",
            "https://example.com/?id=7",
        ),
        (
            "https://example.com/a?fbclid=abc&gclid=def&page=2",
            "https://example.com/a?page=2",
        ),
        (
            "https://example.com/a?UTM_Source=x&keep=1",
            "https://example.com/a?keep=1",
        ),
        (
            "https://example.com/a?q=hello+world&lang=en",
            "https://example.com/a?q=hello+world&lang=en",
        ),
        ("https://example.com/a?flag=&x=1", "https://example.com/a?flag=&x=1"),
        (
            "https://example.com/a?msclkid=z&igshid=w&real=yes",
            "https://example.com/a?real=yes",
        ),
    ],
)
def test_canonicalize_url_normalizes(raw, expected):
    assert canonicalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        123,
        "ftp://example.com",
        "javascript:alert(1)",
        "/relative/path",
        "https://",
        "not a url",
        "https://exa mple.com/a",
        "https://example.com:badport/",
    ],
)
def test_canonicalize_url_rejects_malformed(raw):
    with pytest.raises(ValueError):
        canonicalize_url(raw)


def test_canonicalize_url_is_idempotent():
    once = canonicalize_url("https://Example.com/a?utm_source=x&id=2#frag")
    assert canonicalize_url(once) == once


@pytest.mark.parametrize(
    ("domain", "tier"),
    [
        ("www.bls.gov", "primary"),
        ("www.gov.uk", "primary"),
        ("army.mil", "primary"),
        ("who.int", "primary"),
        ("web.mit.edu", "secondary"),
        ("www.ox.ac.uk", "secondary"),
        ("reuters.com", "secondary"),
        ("news.bbc.co.uk", "secondary"),
        ("apnews.com", "secondary"),
        ("medium.com", "informal"),
        ("www.reddit.com", "informal"),
        ("en.wikipedia.org", "informal"),
        ("someone.substack.com", "informal"),
        ("example.com", "unknown"),
        ("netflix.com", "unknown"),
        ("streaming-notes.example.com", "unknown"),
    ],
)
def test_classify_tier(domain, tier):
    actual, reason = classify_tier(domain)
    assert actual == tier
    assert reason.strip()


def test_classify_tier_does_not_reward_lookalike_domains():
    tier, _ = classify_tier("reuters.com.example.com")
    assert tier == "unknown"
    tier, _ = classify_tier("notreuters.com")
    assert tier == "unknown"
    tier, _ = classify_tier("gov.uk.evil.com")
    assert tier == "unknown"
    tier, _ = classify_tier("ac.uk.evil.com")
    assert tier == "unknown"
    tier, _ = classify_tier("bls.gov.evil.com")
    assert tier == "unknown"


def test_dedup_merges_associations_and_metadata():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [
                result("https://example.com/a?utm_source=x", score=0.4)
            ],
            "beta search": [
                result(
                    "https://example.com/a",
                    title="Different title",
                    snippet="filled in",
                    score=0.9,
                    published=date(2026, 1, 1),
                )
            ],
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.canonical_url == "https://example.com/a"
    # Cleaner URL (no tracking params) and longer title win deterministically.
    assert candidate.original_url == "https://example.com/a"
    assert candidate.title == "Different title"
    assert candidate.question_ids == ["q1", "q2"]
    assert candidate.discovered_by_queries == ["alpha search", "beta search"]
    assert candidate.relevance_score == 0.9
    assert candidate.snippet == "filled in"
    assert candidate.published_date == date(2026, 1, 1)
    assert discovery.duplicates_removed == 1
    assert discovery.results_examined == 2
    assert discovery.queries_executed == 2


def test_merge_keeps_best_score_regardless_of_order():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [result("https://example.com/a", score=0.9)],
            "beta search": [result("https://example.com/a", score=0.4)],
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert discovery.candidates[0].relevance_score == 0.9


def test_distinct_paths_are_not_deduplicated():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [result("https://example.com/a")],
            "beta search": [result("https://example.com/b")],
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert len(discovery.candidates) == 2
    assert discovery.duplicates_removed == 0


def test_same_query_duplicate_does_not_double_associations():
    plan = make_plan(
        [SearchQuery(query="alpha search", question_ids=["q1", "q2"], purpose="p")]
    )
    provider = ScriptedProvider(
        {
            "alpha search": [
                result("https://example.com/a?utm_source=x"),
                result("https://example.com/a"),
            ]
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    candidate = discovery.candidates[0]
    assert candidate.question_ids == ["q1", "q2"]
    assert candidate.discovered_by_queries == ["alpha search"]


def test_ranking_formula_primary_complete():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [
                result(
                    "https://www.bls.gov/a",
                    snippet="text",
                    score=0.8,
                    published=date(2026, 1, 1),
                )
            ]
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert discovery.candidates[0].rank_score == pytest.approx(0.9)


def test_ranking_missing_signals_score_zero_contribution():
    plan = make_plan()
    provider = ScriptedProvider(
        {"alpha search": [result("https://example.com/a")]}
    )
    discovery = SourceDiscovery(provider).discover(plan)
    # unknown tier 0.5 weight, no relevance, no metadata
    assert discovery.candidates[0].rank_score == pytest.approx(0.15)


def test_ranking_is_deterministic_and_ordered():
    plan = make_plan()
    responses = {
        "alpha search": [
            result("https://example.com/low", score=0.1),
            result("https://www.bls.gov/high", score=0.9, snippet="s"),
        ],
        "beta search": [result("https://medium.com/mid", score=0.5)],
    }
    first = SourceDiscovery(ScriptedProvider(responses)).discover(plan)
    second = SourceDiscovery(ScriptedProvider(responses)).discover(plan)
    assert [c.canonical_url for c in first.candidates] == [
        c.canonical_url for c in second.candidates
    ]
    scores = [c.rank_score for c in first.candidates]
    assert scores == sorted(scores, reverse=True)
    assert first.candidates[0].canonical_url == "https://www.bls.gov/high"


def test_ranking_tie_breaks_by_canonical_url():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [
                result("https://example.com/z", score=0.5),
                result("https://example.com/a", score=0.5),
            ]
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert [c.canonical_url for c in discovery.candidates] == [
        "https://example.com/a",
        "https://example.com/z",
    ]


def test_prefer_primary_false_flattens_tier_weight():
    plan = make_plan(prefer_primary=False)
    provider = ScriptedProvider(
        {
            "alpha search": [
                result("https://www.bls.gov/a", score=0.5),
                result("https://medium.com/b", score=0.5),
            ]
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    scores = {c.domain: c.rank_score for c in discovery.candidates}
    assert scores["www.bls.gov"] == scores["medium.com"]


def test_rank_candidates_directly():
    plan = make_plan()
    provider = ScriptedProvider(
        {"alpha search": [result("https://example.com/a", score=0.5)]}
    )
    candidates = SourceDiscovery(provider).discover(plan).candidates
    ranked = rank_candidates(candidates, prefer_primary_sources=True)
    assert ranked[0].rank_score == pytest.approx(0.5 * 0.5 + 0.3 * 0.5)


def test_query_limit_skips_extra_queries():
    queries = [
        SearchQuery(query=f"query {i}", question_ids=["q1"], purpose="p")
        for i in range(12)
    ]
    plan = make_plan(queries)
    provider = ScriptedProvider({})
    discovery = SourceDiscovery(provider, DiscoveryConfig(max_queries=3)).discover(plan)
    assert provider.calls == ["query 0", "query 1", "query 2"]
    assert discovery.queries_executed == 3
    statuses = [report.status for report in discovery.queries]
    assert statuses == ["ok"] * 3 + ["skipped"] * 9
    assert len(discovery.queries) == 12


def test_results_per_query_limit_passed_to_provider():
    plan = make_plan()
    items = [result(f"https://example.com/{i}") for i in range(10)]
    provider = ScriptedProvider({"alpha search": items, "beta search": items})
    discovery = SourceDiscovery(
        provider, DiscoveryConfig(results_per_query=2)
    ).discover(plan)
    assert discovery.results_examined == 4


def test_candidate_limit_keeps_best_ranked():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [
                result(f"https://example.com/{i}", score=i / 10) for i in range(5)
            ]
        }
    )
    discovery = SourceDiscovery(
        provider, DiscoveryConfig(max_candidates=2)
    ).discover(plan)
    assert len(discovery.candidates) == 2
    assert [c.canonical_url for c in discovery.candidates] == [
        "https://example.com/4",
        "https://example.com/3",
    ]


def test_partial_failure_continues_remaining_queries():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": SearchError("boom"),
            "beta search": [result("https://example.com/b")],
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert len(discovery.candidates) == 1
    reports = {report.query: report for report in discovery.queries}
    assert reports["alpha search"].status == "failed"
    assert "boom" in reports["alpha search"].error
    assert reports["beta search"].status == "ok"
    assert discovery.queries_executed == 2


def test_transient_error_after_retries_is_reported_not_raised():
    plan = make_plan()
    provider = ScriptedProvider(
        {"alpha search": TransientSearchError("still failing")}
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert discovery.candidates == []
    assert discovery.queries[0].status == "failed"


def test_all_queries_failed_returns_empty_result():
    plan = make_plan()
    provider = ScriptedProvider(
        {"alpha search": SearchError("x"), "beta search": SearchError("y")}
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert discovery.candidates == []
    assert all(report.status == "failed" for report in discovery.queries)


def test_empty_search_results_produce_empty_candidates():
    plan = make_plan()
    discovery = SourceDiscovery(ScriptedProvider({})).discover(plan)
    assert discovery.candidates == []
    assert discovery.results_examined == 0
    assert all(
        report.status == "ok" and report.results_returned == 0
        for report in discovery.queries
    )


def test_results_with_unnormalizable_urls_are_skipped():
    plan = make_plan()
    bad = SearchResult(title="Bad", url="https://exa mple.com/a")
    provider = ScriptedProvider(
        {"alpha search": [bad, result("https://example.com/good")]}
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert [c.canonical_url for c in discovery.candidates] == [
        "https://example.com/good"
    ]
    assert discovery.results_examined == 2


def test_source_id_is_deterministic():
    plan = make_plan()
    responses = {"alpha search": [result("https://example.com/a")]}
    first = SourceDiscovery(ScriptedProvider(responses)).discover(plan)
    second = SourceDiscovery(ScriptedProvider(responses)).discover(plan)
    assert first.candidates[0].source_id == second.candidates[0].source_id
    assert first.candidates[0].source_id.startswith("src-")


def test_discovery_with_mock_provider_end_to_end(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    plan = MockResearchPlanner().plan("Why is Netflix cheaper than cable TV?")
    discovery = SourceDiscovery(MockSearchProvider()).discover(plan)
    assert discovery.topic == plan.topic
    assert discovery.candidates
    assert discovery.queries_executed == len(plan.search_queries)
    assert discovery.results_examined == 5 * len(plan.search_queries)
    assert discovery.duplicates_removed == (
        discovery.results_examined - len(discovery.candidates)
    )
    scores = [c.rank_score for c in discovery.candidates]
    assert scores == sorted(scores, reverse=True)
    plan_ids = {q.question_id for q in plan.research_questions}
    plan_queries = {q.query for q in plan.search_queries}
    for candidate in discovery.candidates:
        assert set(candidate.question_ids) <= plan_ids
        assert set(candidate.discovered_by_queries) <= plan_queries
        assert candidate.source_tier in {"primary", "secondary", "informal", "unknown"}
        assert candidate.tier_reason.strip()


def test_mock_discovery_is_deterministic():
    plan = MockResearchPlanner().plan("Streaming prices")
    first = SourceDiscovery(MockSearchProvider()).discover(plan)
    second = SourceDiscovery(MockSearchProvider()).discover(plan)
    assert [c.canonical_url for c in first.candidates] == [
        c.canonical_url for c in second.candidates
    ]
    assert [c.rank_score for c in first.candidates] == [
        c.rank_score for c in second.candidates
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_queries": 0},
        {"max_queries": -1},
        {"max_queries": True},
        {"max_queries": 25},
        {"max_queries": 1.5},
        {"results_per_query": 0},
        {"results_per_query": 21},
        {"max_candidates": 0},
        {"max_candidates": 201},
        {"max_candidate": 5},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValidationError):
        DiscoveryConfig(**kwargs)


def test_config_defaults():
    config = DiscoveryConfig()
    assert config.max_queries == 10
    assert config.results_per_query == 5
    assert config.max_candidates == 30


def make_candidate(**overrides):
    payload = {
        "source_id": "src-1",
        "title": "Title",
        "original_url": "https://example.com/a",
        "canonical_url": "https://example.com/a",
        "domain": "example.com",
        "source_tier": "unknown",
        "tier_reason": "reason",
        "question_ids": ["q1"],
        "discovered_by_queries": ["query"],
        "discovered_at": "2026-11-20T00:00:00Z",
    }
    payload.update(overrides)
    return DiscoveryCandidate(**payload)


def test_candidate_rejects_duplicate_associations():
    with pytest.raises(ValidationError, match="question_ids"):
        make_candidate(question_ids=["q1", "q1"])
    with pytest.raises(ValidationError, match="discovered_by_queries"):
        make_candidate(discovered_by_queries=["query", "query"])


def test_candidate_rejects_empty_associations():
    with pytest.raises(ValidationError):
        make_candidate(question_ids=[])
    with pytest.raises(ValidationError):
        make_candidate(discovered_by_queries=[])


def test_query_report_status_consistency():
    with pytest.raises(ValidationError, match="error message"):
        QueryReport(query="q", question_ids=["q1"], status="failed", results_returned=0)
    with pytest.raises(ValidationError, match="error message"):
        QueryReport(
            query="q", question_ids=["q1"], status="ok", results_returned=0, error="x"
        )
    with pytest.raises(ValidationError, match="zero results"):
        QueryReport(query="q", question_ids=["q1"], status="skipped", results_returned=2)


def test_discovery_result_rejects_duplicate_candidates():
    candidate = make_candidate()
    other = make_candidate(source_id="src-2")
    with pytest.raises(ValidationError, match="duplicate"):
        DiscoveryResult(
            topic="t",
            candidates=[candidate, other],
            queries_executed=1,
            results_examined=1,
            duplicates_removed=0,
            created_at="2026-11-20T00:00:00Z",
        )


def _merged_candidate(responses, queries):
    plan = make_plan(queries)
    return SourceDiscovery(ScriptedProvider(responses)).discover(plan).candidates[0]


def test_merge_is_independent_of_query_order():
    qa = SearchQuery(query="alpha", question_ids=["q1"], purpose="p")
    qb = SearchQuery(query="beta", question_ids=["q2"], purpose="p")
    weak = result(
        "https://example.com/a?utm_source=x&fbclid=y", title="Short", score=0.4
    )
    strong = result(
        "https://example.com/a",
        title="A much better and descriptive title",
        snippet="rich snippet",
        score=0.9,
        published=date(2026, 1, 1),
    )
    responses = {"alpha": [weak], "beta": [strong]}
    forward = _merged_candidate(responses, [qa, qb])
    backward = _merged_candidate(responses, [qb, qa])
    assert forward.model_dump(exclude={"discovered_at"}) == backward.model_dump(
        exclude={"discovered_at"}
    )
    assert forward.original_url == "https://example.com/a"
    assert forward.title == "A much better and descriptive title"
    assert forward.snippet == "rich snippet"
    assert forward.relevance_score == 0.9


def test_merge_is_independent_of_result_order():
    queries = [SearchQuery(query="alpha", question_ids=["q1", "q2"], purpose="p")]
    weak = result("https://example.com/a?utm_source=x", title="Short", score=0.4)
    strong = result(
        "https://example.com/a",
        title="A much better and descriptive title",
        snippet="rich snippet",
        score=0.9,
    )
    forward = _merged_candidate({"alpha": [weak, strong]}, queries)
    backward = _merged_candidate({"alpha": [strong, weak]}, queries)
    assert forward.model_dump(exclude={"discovered_at"}) == backward.model_dump(
        exclude={"discovered_at"}
    )


def test_merge_prefers_url_with_fewer_tracking_params():
    queries = [SearchQuery(query="alpha", question_ids=["q1"], purpose="p")]
    one_param = result("https://example.com/a?fbclid=x")
    two_params = result("https://example.com/a?fbclid=x&utm_source=y")
    merged = _merged_candidate({"alpha": [two_params, one_param]}, queries)
    assert merged.original_url == "https://example.com/a?fbclid=x"
    merged_reverse = _merged_candidate({"alpha": [one_param, two_params]}, queries)
    assert merged_reverse.original_url == merged.original_url


def test_merge_title_cap_prevents_runaway_titles():
    queries = [SearchQuery(query="alpha", question_ids=["q1"], purpose="p")]
    at_cap = result("https://example.com/a", title="A" * 120)
    over_cap = result("https://example.com/a", title="Z" * 500)
    forward = _merged_candidate({"alpha": [at_cap, over_cap]}, queries)
    backward = _merged_candidate({"alpha": [over_cap, at_cap]}, queries)
    assert forward.title == "A" * 120
    assert forward.title == backward.title


def test_merge_snippet_cap_prevents_runaway_snippets():
    queries = [SearchQuery(query="alpha", question_ids=["q1"], purpose="p")]
    at_cap = result("https://example.com/a", snippet="A" * 300)
    over_cap = result("https://example.com/a", snippet="Z" * 5000)
    forward = _merged_candidate({"alpha": [at_cap, over_cap]}, queries)
    backward = _merged_candidate({"alpha": [over_cap, at_cap]}, queries)
    assert forward.snippet == "A" * 300
    assert forward.snippet == backward.snippet


def test_merge_keeps_earliest_available_date_deterministically():
    queries = [SearchQuery(query="alpha", question_ids=["q1"], purpose="p")]
    later = result("https://example.com/a", published=date(2026, 5, 1))
    earlier = result("https://example.com/a", published=date(2026, 1, 1))
    forward = _merged_candidate({"alpha": [later, earlier]}, queries)
    backward = _merged_candidate({"alpha": [earlier, later]}, queries)
    assert forward.published_date == date(2026, 1, 1)
    assert forward.published_date == backward.published_date


def test_merge_fills_missing_metadata_from_either_side():
    queries = [SearchQuery(query="alpha", question_ids=["q1"], purpose="p")]
    bare = result("https://example.com/a")
    rich = result(
        "https://example.com/a", snippet="text", published=date(2026, 2, 2), score=0.7
    )
    forward = _merged_candidate({"alpha": [bare, rich]}, queries)
    backward = _merged_candidate({"alpha": [rich, bare]}, queries)
    assert forward.snippet == "text"
    assert forward.published_date == date(2026, 2, 2)
    assert forward.relevance_score == 0.7
    assert forward.model_dump(exclude={"discovered_at"}) == backward.model_dump(
        exclude={"discovered_at"}
    )


def test_unexpected_provider_exception_is_reported_and_loop_continues():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": RuntimeError("failure mentioning secret tvly-XYZ"),
            "beta search": [result("https://example.com/b")],
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert len(discovery.candidates) == 1
    reports = {report.query: report for report in discovery.queries}
    assert reports["alpha search"].status == "failed"
    assert "RuntimeError" in reports["alpha search"].error
    assert "tvly-XYZ" not in reports["alpha search"].error
    assert reports["beta search"].status == "ok"
    assert discovery.queries_executed == 2


def test_unexpected_exceptions_on_all_queries_return_empty_result():
    plan = make_plan()
    provider = ScriptedProvider(
        {"alpha search": RuntimeError("x"), "beta search": KeyError("y")}
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert discovery.candidates == []
    assert all(report.status == "failed" for report in discovery.queries)
    assert all(report.error for report in discovery.queries)


def test_known_search_error_message_is_still_reported():
    plan = make_plan()
    provider = ScriptedProvider({"alpha search": SearchError("sanitized detail")})
    discovery = SourceDiscovery(provider).discover(plan)
    assert discovery.queries[0].error == "sanitized detail"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com./a", "https://example.com/a"),
        ("https://EXAMPLE.COM./a", "https://example.com/a"),
        ("https://example.com./", "https://example.com"),
        ("http://192.168.0.1/a", "http://192.168.0.1/a"),
        ("http://192.168.0.1:8080/a", "http://192.168.0.1:8080/a"),
        ("https://[2001:db8::1]/a", "https://[2001:db8::1]/a"),
        ("https://[::1]:8443/a", "https://[::1]:8443/a"),
        ("https://example.com:65535/a", "https://example.com:65535/a"),
    ],
)
def test_trailing_dot_and_ip_canonicalization(raw, expected):
    assert canonicalize_url(raw) == expected
    assert canonicalize_url(expected) == expected


def test_trailing_dot_host_deduplicates():
    plan = make_plan()
    provider = ScriptedProvider(
        {
            "alpha search": [result("https://example.com./a")],
            "beta search": [result("https://example.com/a")],
        }
    )
    discovery = SourceDiscovery(provider).discover(plan)
    assert len(discovery.candidates) == 1
    assert discovery.candidates[0].domain == "example.com"
    assert discovery.duplicates_removed == 1


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com:0/a",
        "http://example.com:0/",
        "https://example.com:65536/a",
        "https://example.com:99999/a",
        "https://./a",
    ],
)
def test_invalid_ports_and_empty_host_rejected(raw):
    with pytest.raises(ValueError):
        canonicalize_url(raw)