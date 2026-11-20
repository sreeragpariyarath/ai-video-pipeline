from __future__ import annotations

import math
import os
import time
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from .search_provider import (
    SearchError,
    SearchProvider,
    SearchResult,
    TransientSearchError,
)


DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRIES = 2
# 429 is excluded: the SDK surfaces it as UsageLimitExceededError (quota, permanent).
_RETRY_STATUS = {500, 502, 503, 504}
# Server-provided retry-after hints longer than this are not worth blocking on.
_MAX_RETRY_AFTER_SECONDS = 30.0


def _load_sdk() -> tuple[Any, Any, Any]:
    try:
        import requests
        from tavily import TavilyClient, errors
    except ImportError as exc:
        raise SearchError(
            "tavily-python is not installed. Run `pip install -r requirements.txt`, "
            "or use MockSearchProvider for offline runs."
        ) from exc
    return TavilyClient, errors, requests


def _parse_published_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _map_result(item: Any) -> SearchResult | None:
    if not isinstance(item, dict):
        return None
    try:
        return SearchResult(
            title=item.get("title"),
            url=item.get("url"),
            snippet=item.get("content") or None,
            relevance_score=item.get("score"),
            published_date=_parse_published_date(item.get("published_date")),
        )
    except (ValidationError, TypeError):
        return None


class TavilySearchProvider(SearchProvider):
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite number greater than 0.")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 5
        ):
            raise ValueError("max_retries must be an integer between 0 and 5.")
        key = (api_key or os.environ.get("TAVILY_API_KEY") or "").strip()
        if not key:
            raise SearchError(
                "No Tavily API key found. Set TAVILY_API_KEY, "
                "or use MockSearchProvider for offline runs."
            )
        self._api_key = key
        self._timeout = float(timeout_seconds)
        self._max_retries = max_retries
        TavilyClient, self._errors, self._requests = _load_sdk()
        self._client = TavilyClient(api_key=self._api_key)

    def _search(self, query: str, *, max_results: int) -> list[SearchResult]:
        raw = self._request(query, max_results)
        if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
            raise SearchError("Tavily returned a response without a results list.")
        results = []
        for item in raw["results"]:
            mapped = _map_result(item)
            if mapped is not None:
                results.append(mapped)
        return results[:max_results]

    def _request(self, query: str, max_results: int) -> Any:
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.search(
                    query=query,
                    max_results=max_results,
                    timeout=self._timeout,
                )
            except Exception as exc:
                transient = self._is_transient(exc)
                delay = self._retry_delay(exc, attempt) if transient else None
                if delay is not None and attempt < self._max_retries:
                    time.sleep(delay)
                    continue
                message = self._sanitize(str(exc)) or type(exc).__name__
                # Suppress chaining: the raw SDK exception may contain the API key.
                if transient:
                    raise TransientSearchError(
                        f"Tavily request failed: {message}"
                    ) from None
                raise SearchError(f"Tavily request failed: {message}") from None
        raise AssertionError("retry loop exhausted")

    def _is_transient(self, exc: Exception) -> bool:
        errors = self._errors
        if isinstance(exc, errors.TimeoutError):
            return True
        # Keyless window limits are the SDK's documented recoverable envelope;
        # plain 429 UsageLimitExceededError means quota exhaustion (permanent).
        if isinstance(exc, errors.TavilyKeylessLimitError):
            return True
        if isinstance(exc, errors.UsageLimitExceededError):
            return False
        requests = self._requests
        if isinstance(
            exc,
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError),
        ):
            return True
        if isinstance(exc, requests.exceptions.HTTPError):
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return isinstance(status, int) and status in _RETRY_STATUS
        return False

    def _retry_delay(self, exc: Exception, attempt: int) -> float | None:
        """None means do not retry. Honor server retry-after only within bounds."""
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is None:
            return float(2**attempt)
        if (
            isinstance(retry_after, bool)
            or not isinstance(retry_after, (int, float))
            or not math.isfinite(retry_after)
            or not 0 <= retry_after <= _MAX_RETRY_AFTER_SECONDS
        ):
            return None
        return float(retry_after)

    def _sanitize(self, message: str) -> str:
        return message.replace(self._api_key, "[redacted]")