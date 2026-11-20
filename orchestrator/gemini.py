from __future__ import annotations

import os
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


DEFAULT_MODEL = "gemini-2.5-flash"

_RETRY_CODES = {429, 500, 502, 503, 504}
_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class GeminiError(RuntimeError):
    """The Gemini SDK is missing, misconfigured, or returned unusable output."""


def _load_sdk() -> tuple[Any, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise GeminiError(
            "google-genai is not installed. Run `pip install -r requirements.txt`, "
            "or use --mock for an offline run."
        ) from exc
    return genai, types


class GeminiClient:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise GeminiError(
                "No Gemini API key found. Set GEMINI_API_KEY (or GOOGLE_API_KEY), "
                "or run with --mock."
            )
        genai, types = _load_sdk()
        self._types = types
        self._client = genai.Client(api_key=key)

    def generate_grounded(self, *, system: str, prompt: str) -> tuple[str, list[dict[str, str]]]:
        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        response = self._generate(prompt, config)
        text = (response.text or "").strip()
        if not text:
            raise GeminiError("Gemini returned an empty research response.")
        return text, _extract_sources(response)

    def generate_json(
        self,
        *,
        system: str,
        prompt: str,
        schema: type[SchemaT],
        temperature: float = 0.4,
    ) -> SchemaT:
        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=schema,
        )
        response = self._generate(prompt, config)
        if isinstance(response.parsed, schema):
            return response.parsed
        raw = _strip_json_fences((response.text or "").strip())
        if not raw:
            raise GeminiError("Gemini returned an empty JSON response.")
        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            raise GeminiError(
                f"Gemini returned JSON that does not match {schema.__name__}: {exc}"
            ) from exc

    def _generate(self, prompt: str, config: Any) -> Any:
        for attempt in range(3):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:
                if attempt < 2 and _status_code(exc) in _RETRY_CODES:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise GeminiError(f"Gemini request failed: {exc}") from exc
            if not response.candidates:
                feedback = response.prompt_feedback
                blocked = getattr(feedback, "block_reason", None) if feedback else None
                suffix = f" (blocked: {blocked})" if blocked else ""
                raise GeminiError(f"Gemini returned no candidates{suffix}.")
            return response
        raise AssertionError("retry loop exhausted")


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def _strip_json_fences(raw: str) -> str:
    cleaned = _JSON_FENCE.sub("", raw).strip()
    if cleaned.startswith("{"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    return cleaned[start : end + 1] if start != -1 and end > start else cleaned


def _extract_sources(response: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in response.candidates or []:
        metadata = candidate.grounding_metadata
        if metadata is None:
            continue
        for chunk in metadata.grounding_chunks or []:
            web = chunk.web
            if web is None or not web.uri:
                continue
            url = web.uri.strip()
            if not url or url in seen:
                continue
            seen.add(url)
            title = (web.title or web.domain or url).strip()
            sources.append({"title": title, "url": url})
    return sources
