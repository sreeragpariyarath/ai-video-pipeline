from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .discovery_schemas import (
    DiscoveryCandidate,
    DiscoveryResult,
    QueryReport,
    SourceTier,
)
from .research_schemas import ResearchPlan, _reject_bool
from .search_provider import SearchError, SearchProvider, SearchResult


PositiveInt = Annotated[int, BeforeValidator(_reject_bool)]


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_queries: PositiveInt = Field(default=10, ge=1, le=24)
    results_per_query: PositiveInt = Field(default=5, ge=1, le=20)
    max_candidates: PositiveInt = Field(default=30, ge=1, le=200)


_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "yclid",
    "twclid",
}


def _is_tracking_param(key: str) -> bool:
    key = key.lower()
    return key in _TRACKING_PARAMS or key.startswith("utm_")


def canonicalize_url(url: str) -> str:
    """Conservative normalization for deduplication.

    Lowercases the hostname, drops trailing DNS dots, fragments, default
    ports, userinfo, and known tracking parameters, and removes a root-only
    trailing slash. Meaningful query parameters and non-root paths are
    preserved as-is.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string.")
    url = url.strip()
    if any(char.isspace() for char in url):
        raise ValueError("URL must not contain whitespace.")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Malformed URL: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must be an absolute http(s) URL with a hostname.")
    if port == 0:
        raise ValueError("Malformed URL: port 0 is not valid.")
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        raise ValueError("URL must be an absolute http(s) URL with a hostname.")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        netloc = f"{netloc}:{port}"
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    query = urlencode(kept)
    if parsed.path in ("", "/"):
        path = "/" if query else ""
    else:
        path = parsed.path
    return urlunparse((parsed.scheme, netloc, path, parsed.params, query, ""))


# Tiers describe the publisher's relationship to the topic, never its
# trustworthiness. Only structural signals are used; anything else is unknown.
_NEWS_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "theguardian.com",
    "economist.com",
}
_UGC_DOMAINS = {
    "medium.com",
    "substack.com",
    "reddit.com",
    "quora.com",
    "wordpress.com",
    "blogspot.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "linkedin.com",
    "wikipedia.org",
}


def _matches_domain(domain: str, registered: str) -> bool:
    return domain == registered or domain.endswith(f".{registered}")


def classify_tier(domain: str) -> tuple[SourceTier, str]:
    domain = domain.lower().strip(".")
    labels = domain.split(".")
    tld = labels[-1]
    second_level = labels[-2] if len(labels) >= 2 else ""
    is_government = tld in {"gov", "mil", "int"} or (
        second_level == "gov" and len(tld) == 2
    )
    if is_government:
        return (
            "primary",
            "Government or intergovernmental domain; publisher is an official body.",
        )
    is_academic = tld == "edu" or (second_level == "ac" and len(tld) == 2)
    if is_academic:
        return (
            "secondary",
            "Academic institution domain; research or educational publishing, "
            "credibility not assessed.",
        )
    if any(_matches_domain(domain, news) for news in _NEWS_DOMAINS):
        return (
            "secondary",
            "Recognized news publisher; journalism is secondary coverage, "
            "credibility not assessed.",
        )
    if any(_matches_domain(domain, ugc) for ugc in _UGC_DOMAINS):
        return (
            "informal",
            "User-generated content platform; anyone can publish without review.",
        )
    return (
        "unknown",
        "No structural signal justifies a tier; classify manually after review.",
    )


_TIER_WEIGHTS = {"primary": 1.0, "secondary": 0.75, "unknown": 0.5, "informal": 0.25}


def rank_candidates(
    candidates: list[DiscoveryCandidate],
    *,
    prefer_primary_sources: bool,
) -> list[DiscoveryCandidate]:
    """Deterministic ranking, not a credibility judgment.

    rank_score = 0.5 * relevance (0 when missing)
               + 0.3 * tier weight (primary 1.0, secondary 0.75, unknown 0.5,
                 informal 0.25; flat 0.5 when prefer_primary_sources is False)
               + 0.2 * completeness (fraction of snippet/published_date present)
    Ties break by canonical URL so ordering is stable across runs.
    """
    scored = []
    for candidate in candidates:
        relevance = candidate.relevance_score or 0.0
        tier = _TIER_WEIGHTS[candidate.source_tier] if prefer_primary_sources else 0.5
        completeness = (
            int(candidate.snippet is not None)
            + int(candidate.published_date is not None)
        ) / 2
        score = round(0.5 * relevance + 0.3 * tier + 0.2 * completeness, 4)
        scored.append(
            DiscoveryCandidate.model_validate(
                {**candidate.model_dump(), "rank_score": score}
            )
        )
    return sorted(scored, key=lambda c: (-c.rank_score, c.canonical_url))


def _source_id(canonical_url: str) -> str:
    return "src-" + hashlib.sha256(canonical_url.encode()).hexdigest()[:12]


_TITLE_LENGTH_CAP = 120
_SNIPPET_LENGTH_CAP = 300


def _tracking_param_count(url: str) -> int:
    return sum(
        1
        for key, _ in parse_qsl(urlparse(url).query, keep_blank_values=True)
        if _is_tracking_param(key)
    )


def _better_text(current: str | None, other: str | None, cap: int) -> str | None:
    """Longer text wins up to a cap; ties break lexicographically.

    The key is order-independent, so merging is commutative.
    """
    if current is None:
        return other
    if other is None:
        return current
    return min((current, other), key=lambda text: (-min(len(text), cap), text))


def _merge(
    existing: DiscoveryCandidate, result: SearchResult, query_text: str, question_ids: list[str]
) -> DiscoveryCandidate:
    """Deterministic metadata selection, independent of query execution order.

    - original_url: fewest tracking parameters wins; ties break by URL text.
    - title/snippet: longer wins up to a length cap; ties break lexicographically.
    - published_date: earliest available date wins.
    - relevance_score: maximum is kept. Limitation: provider scores are
      query-relative, so the max across queries is optimistic, not calibrated.
    - question IDs and discovery queries: merged as sorted unions.
    """
    merged_questions = sorted(set(existing.question_ids) | set(question_ids))
    merged_queries = sorted(set(existing.discovered_by_queries) | {query_text})
    best = existing.relevance_score
    if result.relevance_score is not None and (
        best is None or result.relevance_score > best
    ):
        best = result.relevance_score
    original_url = min(
        (existing.original_url, result.url),
        key=lambda url: (_tracking_param_count(url), url),
    )
    dates = [
        value
        for value in (existing.published_date, result.published_date)
        if value is not None
    ]
    return DiscoveryCandidate.model_validate(
        {
            **existing.model_dump(),
            "original_url": original_url,
            "title": _better_text(existing.title, result.title, _TITLE_LENGTH_CAP),
            "question_ids": merged_questions,
            "discovered_by_queries": merged_queries,
            "snippet": _better_text(
                existing.snippet, result.snippet, _SNIPPET_LENGTH_CAP
            ),
            "published_date": min(dates) if dates else None,
            "relevance_score": best,
        }
    )


class SourceDiscovery:
    def __init__(self, provider: SearchProvider, config: DiscoveryConfig | None = None):
        self._provider = provider
        self._config = config or DiscoveryConfig()

    @property
    def config(self) -> DiscoveryConfig:
        return self._config

    def discover(self, plan: ResearchPlan) -> DiscoveryResult:
        config = self._config
        now = datetime.now(timezone.utc)
        reports: list[QueryReport] = []
        by_canonical: dict[str, DiscoveryCandidate] = {}
        examined = 0
        duplicates = 0
        executed = 0

        active = plan.search_queries[: config.max_queries]
        skipped = plan.search_queries[config.max_queries :]

        for query in active:
            executed += 1
            try:
                results = self._provider.search(
                    query.query, max_results=config.results_per_query
                )
            except SearchError as exc:
                reports.append(
                    QueryReport(
                        query=query.query,
                        question_ids=query.question_ids,
                        status="failed",
                        results_returned=0,
                        error=str(exc),
                    )
                )
                continue
            except Exception as exc:
                # Provider contract violations must not abort remaining queries.
                # Report only the type: arbitrary messages may carry secrets.
                reports.append(
                    QueryReport(
                        query=query.query,
                        question_ids=query.question_ids,
                        status="failed",
                        results_returned=0,
                        error=f"Unexpected {type(exc).__name__} from search provider.",
                    )
                )
                continue
            examined += len(results)
            for result in results:
                try:
                    canonical = canonicalize_url(result.url)
                except ValueError:
                    continue
                if canonical in by_canonical:
                    duplicates += 1
                    by_canonical[canonical] = _merge(
                        by_canonical[canonical], result, query.query, query.question_ids
                    )
                    continue
                domain = urlparse(canonical).hostname or ""
                tier, reason = classify_tier(domain)
                by_canonical[canonical] = DiscoveryCandidate(
                    source_id=_source_id(canonical),
                    title=result.title,
                    original_url=result.url,
                    canonical_url=canonical,
                    domain=domain,
                    snippet=result.snippet,
                    published_date=result.published_date,
                    relevance_score=result.relevance_score,
                    source_tier=tier,
                    tier_reason=reason,
                    question_ids=list(query.question_ids),
                    discovered_by_queries=[query.query],
                    discovered_at=now,
                )
            reports.append(
                QueryReport(
                    query=query.query,
                    question_ids=query.question_ids,
                    status="ok",
                    results_returned=len(results),
                )
            )

        for query in skipped:
            reports.append(
                QueryReport(
                    query=query.query,
                    question_ids=query.question_ids,
                    status="skipped",
                    results_returned=0,
                )
            )

        ranked = rank_candidates(
            list(by_canonical.values()),
            prefer_primary_sources=plan.source_preferences.prefer_primary_sources,
        )
        return DiscoveryResult(
            topic=plan.topic,
            candidates=ranked[: config.max_candidates],
            queries=reports,
            queries_executed=executed,
            results_examined=examined,
            duplicates_removed=duplicates,
            created_at=now,
        )