from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import date

from pydantic import BaseModel

from .research_schemas import HttpUrlStr, NonEmptyStr, UnitInterval


class SearchError(RuntimeError):
    """Search failed permanently: bad configuration, auth, or unusable response."""


class TransientSearchError(SearchError):
    """Search failed temporarily (timeout, rate limit, network); safe to retry."""


class SearchResult(BaseModel):
    title: NonEmptyStr
    url: HttpUrlStr
    snippet: NonEmptyStr | None = None
    relevance_score: UnitInterval | None = None
    published_date: date | None = None


def _validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be a non-empty string.")
    return query.strip()


def _validate_max_results(max_results: int) -> int:
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or max_results < 1
    ):
        raise ValueError("max_results must be a positive integer.")
    return max_results


class SearchProvider(ABC):
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        query = _validate_query(query)
        max_results = _validate_max_results(max_results)
        return self._search(query, max_results=max_results)

    @abstractmethod
    def _search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Return provider-neutral results; raise SearchError on failure."""


# Illustrative offline articles spanning every source tier. Paths are fake.
_MOCK_POOL: list[tuple[str, str, str, date | None]] = [
    (
        "https://www.bls.gov/news.release/jolts.nr0.htm",
        "BLS Job Openings and Labor Turnover Summary",
        "Official monthly labor-market statistics.",
        date(2026, 9, 4),
    ),
    (
        "https://www.fcc.gov/reports-research/reports/cable-price-report",
        "FCC Report on Cable Industry Prices",
        "Official report comparing cable and streaming prices.",
        date(2026, 6, 15),
    ),
    (
        "https://www.reuters.com/business/media/streaming-costs-2026/",
        "Streaming services face rising content costs",
        "Wire coverage of streaming economics.",
        date(2026, 8, 2),
    ),
    (
        "https://apnews.com/article/streaming-prices-cable-comparison",
        "How streaming prices compare with cable",
        "News analysis of household video spending.",
        None,
    ),
    (
        "https://www.netflix.com/tudum/articles/how-pricing-works",
        "Netflix explains its pricing tiers",
        "Company publication about its own plans.",
        None,
    ),
    (
        "https://medium.com/@media-analyst/the-real-cost-of-streaming",
        "The real cost of streaming",
        "Independent analyst essay.",
        date(2026, 3, 10),
    ),
    (
        "https://www.reddit.com/r/cordcutters/comments/mock1/is_cable_cheaper/",
        "Is cable actually cheaper now?",
        "Community discussion thread.",
        None,
    ),
    (
        "https://streaming-notes.example.com/pricing-breakdown",
        "A pricing breakdown of major streamers",
        "Independent blog post.",
        date(2026, 1, 20),
    ),
    (
        "https://en.wikipedia.org/wiki/Streaming_television",
        "Streaming television",
        "Encyclopedia overview.",
        None,
    ),
    (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=NFLX",
        "Netflix SEC filings index",
        "Regulatory filings index.",
        None,
    ),
]


class MockSearchProvider(SearchProvider):
    """Deterministic offline provider; needs no API key and makes no network calls."""

    def _search(self, query: str, *, max_results: int) -> list[SearchResult]:
        ranked = sorted(
            _MOCK_POOL,
            key=lambda item: hashlib.sha256(f"{query}|{item[0]}".encode()).hexdigest(),
        )
        results = []
        for url, title, snippet, published in ranked[:max_results]:
            digest = hashlib.sha256(f"{url}|{query}".encode()).digest()
            score = round(0.5 + (digest[0] % 50) / 100, 2)
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    relevance_score=score,
                    published_date=published,
                )
            )
        return results