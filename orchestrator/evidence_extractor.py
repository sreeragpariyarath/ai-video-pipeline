from __future__ import annotations

from datetime import datetime, timezone

from .discovery_schemas import DiscoveryCandidate, DiscoveryResult
from .evidence_schemas import (
    ExtractionConfig,
    ExtractionResult,
    PageEvidenceContent,
    SourceExtraction,
)
from .gemini import GeminiClient, GeminiError
from .html_extraction import extract_article
from .page_fetcher import FetchError, PageFetcher
from .prompts import EVIDENCE_EXTRACTION_SYSTEM, evidence_extraction_prompt
from .research_schemas import ClaimEvidence, ResearchPlan


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _source_blocks(text: str) -> list[str]:
    # Trafilatura emits one block per line; boundaries must survive
    # normalization so excerpts cannot stitch unrelated paragraphs together.
    return [_normalize_whitespace(block) for block in text.splitlines() if block.strip()]


def _excerpt_in_source(normalized_excerpt: str, blocks: list[str]) -> bool:
    return any(normalized_excerpt in block for block in blocks)


class EvidenceExtraction:
    def __init__(
        self,
        fetcher: PageFetcher,
        client: GeminiClient,
        config: ExtractionConfig | None = None,
    ):
        self._fetcher = fetcher
        self._client = client
        self._config = config or ExtractionConfig()

    def extract(self, plan: ResearchPlan, discovery: DiscoveryResult) -> ExtractionResult:
        if plan.topic != discovery.topic:
            raise ValueError("Discovery result topic does not match the research plan.")
        sources: list[SourceExtraction] = []
        active = discovery.candidates[: self._config.max_sources]
        for candidate in active:
            sources.append(self._process(plan, candidate))
        for candidate in discovery.candidates[self._config.max_sources :]:
            sources.append(
                SourceExtraction(
                    source_id=candidate.source_id,
                    canonical_url=candidate.canonical_url,
                    status="skipped",
                )
            )
        return ExtractionResult(
            topic=plan.topic,
            sources=sources,
            sources_processed=len(sources),
            sources_succeeded=sum(s.status == "ok" for s in sources),
            sources_failed=sum(s.status == "failed" for s in sources),
            sources_skipped=sum(s.status == "skipped" for s in sources),
            created_at=datetime.now(timezone.utc),
        )

    def _process(
        self, plan: ResearchPlan, candidate: DiscoveryCandidate
    ) -> SourceExtraction:
        try:
            page = self._fetcher.fetch(candidate.canonical_url)
            content = extract_article(page.html, page.final_url)
            if content is None:
                return self._failed(candidate, "Article extraction produced no usable content.")
            text = content.text
            text_truncated = len(text) > self._config.max_chars_per_source
            if text_truncated:
                text = text[: self._config.max_chars_per_source]
            ai = self._client.generate_json(
                system=EVIDENCE_EXTRACTION_SYSTEM,
                prompt=evidence_extraction_prompt(
                    topic=plan.topic,
                    questions=[q.question for q in plan.research_questions],
                    url=candidate.canonical_url,
                    title=content.title,
                    text=text,
                    max_excerpts=self._config.max_excerpts_per_source,
                ),
                schema=PageEvidenceContent,
                temperature=0.2,
            )
            normalized_blocks = _source_blocks(text)
            evidence: list[ClaimEvidence] = []
            seen: set[tuple[str, str]] = set()
            rejected = 0
            for item in ai.excerpts[: self._config.max_excerpts_per_source]:
                # Deterministic, case-sensitive substring check within a single
                # source block; fabricated or repeated excerpts are dropped,
                # never fixed. Duplicates count as rejected items.
                normalized = _normalize_whitespace(item.excerpt)
                key = (normalized, item.relationship)
                if key in seen:
                    rejected += 1
                    continue
                seen.add(key)
                if _excerpt_in_source(normalized, normalized_blocks):
                    evidence.append(
                        ClaimEvidence(
                            source_id=candidate.source_id,
                            excerpt=item.excerpt,
                            relationship=item.relationship,
                            notes=item.notes.strip() or None,
                        )
                    )
                else:
                    rejected += 1
            return SourceExtraction(
                source_id=candidate.source_id,
                canonical_url=candidate.canonical_url,
                status="ok",
                evidence=evidence,
                chars_extracted=len(text),
                rejected_excerpts=rejected,
                text_truncated=text_truncated,
            )
        except GeminiError as exc:
            # GeminiError text can embed model output quoting page content;
            # only application-defined classifications are stored.
            message = str(exc)
            if "does not match" in message or "empty JSON" in message:
                return self._failed(candidate, "Gemini returned invalid evidence output.")
            return self._failed(candidate, "Gemini request failed.")
        except FetchError as exc:
            return self._failed(candidate, str(exc))
        except Exception as exc:
            # Unexpected provider failures: type name only, never raw details.
            return self._failed(candidate, f"Extraction failed: {type(exc).__name__}")

    @staticmethod
    def _failed(candidate: DiscoveryCandidate, error: str) -> SourceExtraction:
        return SourceExtraction(
            source_id=candidate.source_id,
            canonical_url=candidate.canonical_url,
            status="failed",
            error=error,
        )


class MockEvidenceExtraction:
    """Deterministic offline extraction built from discovery snippets."""

    def __init__(self, config: ExtractionConfig | None = None):
        self._config = config or ExtractionConfig()

    def extract(self, plan: ResearchPlan, discovery: DiscoveryResult) -> ExtractionResult:
        if plan.topic != discovery.topic:
            raise ValueError("Discovery result topic does not match the research plan.")
        sources: list[SourceExtraction] = []
        for index, candidate in enumerate(discovery.candidates):
            if index >= self._config.max_sources:
                sources.append(
                    SourceExtraction(
                        source_id=candidate.source_id,
                        canonical_url=candidate.canonical_url,
                        status="skipped",
                    )
                )
                continue
            excerpt = candidate.snippet or candidate.title
            sources.append(
                SourceExtraction(
                    source_id=candidate.source_id,
                    canonical_url=candidate.canonical_url,
                    status="ok",
                    evidence=[
                        ClaimEvidence(
                            source_id=candidate.source_id,
                            excerpt=excerpt,
                            relationship="supports",
                            notes="Mock evidence derived from the discovery snippet.",
                        )
                    ],
                    chars_extracted=len(excerpt),
                )
            )
        return ExtractionResult(
            topic=plan.topic,
            sources=sources,
            sources_processed=len(sources),
            sources_succeeded=sum(s.status == "ok" for s in sources),
            sources_failed=sum(s.status == "failed" for s in sources),
            sources_skipped=sum(s.status == "skipped" for s in sources),
            created_at=datetime.now(timezone.utc),
        )