from __future__ import annotations

from collections import Counter

from annotated_types import MaxLen
from pydantic import BaseModel

from .evidence_schemas import ExtractionConfig
from .quality_schemas import (
    ClaimMetrics,
    Completeness,
    EvidenceMetrics,
    QualityConfig,
    QualityReport,
    QualityWarning,
    ResourceLimits,
    SourceMetrics,
)
from .research_schemas import ResearchPackage, ResearchPlanContent
from .source_discovery import DiscoveryConfig
from .verification_schemas import MAX_CLAIMS, MAX_EVIDENCE


def _field_max_length(model: type[BaseModel], field: str) -> int:
    for item in model.model_fields[field].metadata:
        if isinstance(item, MaxLen):
            return item.max_length
    raise ValueError(f"{model.__name__}.{field} has no max length")


def resource_limits(
    discovery: DiscoveryConfig, extraction: ExtractionConfig
) -> ResourceLimits:
    """Configured ceilings for one research run; counts, not monetary costs."""
    return ResourceLimits(
        max_research_questions=_field_max_length(
            ResearchPlanContent, "research_questions"
        ),
        max_search_queries=discovery.max_queries,
        max_candidates=discovery.max_candidates,
        max_sources_fetched=extraction.max_sources,
        max_fetch_requests_per_source=(
            (1 + extraction.max_retries) * (1 + extraction.max_redirects)
        ),
        max_fetch_seconds_per_source=extraction.max_fetch_seconds,
        max_evidence_items=MAX_EVIDENCE,
        max_claims=MAX_CLAIMS,
        # One planning call, one per fetched source, one synthesis, one verification.
        max_gemini_calls=3 + extraction.max_sources,
    )


def _normalized_statement(statement: str) -> str:
    return " ".join(statement.casefold().split())


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _similar_pairs(statements: list[str], threshold: float) -> int:
    """Count non-identical statement pairs with token overlap >= threshold.

    Jaccard overlap is deterministic and easy to explain; it ignores word
    order, so it catches restatements without extra dependencies.
    """
    pairs = 0
    for index, left in enumerate(statements):
        for right in statements[index + 1 :]:
            if left != right and _token_overlap(left, right) >= threshold:
                pairs += 1
    return pairs


class QualityEvaluator:
    """Deterministic, explainable assessment; never mutates the package."""

    def __init__(self, config: QualityConfig | None = None):
        self._config = config or QualityConfig()

    def evaluate(self, package: ResearchPackage) -> QualityReport:
        cfg = self._config
        warnings: list[QualityWarning] = []
        sources = package.sources
        claims = package.claims

        def warn(code: str, message: str) -> None:
            warnings.append(QualityWarning(code=code, message=message))

        if not sources:
            warn(
                "no_sources",
                "The package contains no sources, so no claim has traceable origin evidence.",
            )
        if len(claims) < cfg.min_claims:
            warn(
                "too_few_claims",
                f"The package has {len(claims)} claims; at least {cfg.min_claims} required.",
            )
        if sources and len(sources) < cfg.min_sources:
            warn(
                "few_sources",
                f"Only {len(sources)} usable sources; at least {cfg.min_sources} recommended.",
            )
        tiers = Counter(source.source_type for source in sources)
        domains = {source.domain for source in sources}
        if sources and len(domains) < cfg.min_distinct_domains:
            warn(
                "low_diversity",
                f"Sources span {len(domains)} distinct domain(s); "
                f"at least {cfg.min_distinct_domains} expected.",
            )
        if sources and tiers["informal"] == len(sources):
            warn(
                "informal_only",
                "All sources are informal (user-generated); "
                "no primary or secondary coverage.",
            )
        statuses = Counter(claim.verification_status for claim in claims)
        decisive = statuses["supported"] + statuses["contradicted"] + statuses["disputed"]
        if claims and decisive == 0:
            warn(
                "all_unverified",
                "Every claim is unverified; no claim has decisive evidence.",
            )
        contradicted = statuses["contradicted"]
        if claims and contradicted and contradicted / len(claims) >= cfg.contradiction_ratio:
            warn(
                "contradictions",
                f"{contradicted} of {len(claims)} claims are contradicted "
                f"(threshold {cfg.contradiction_ratio:.0%}).",
            )
        # Exact-match duplicates after case/whitespace normalization are counted
        # separately from near-duplicates, so both warnings stay specific.
        normalized = [_normalized_statement(c.statement) for c in claims]
        duplicates = len(normalized) - len(set(normalized))
        if duplicates:
            warn(
                "duplicate_claims",
                f"{duplicates} claim(s) repeat another claim's statement "
                "after case/whitespace normalization.",
            )
        similar = _similar_pairs(normalized, cfg.similar_claim_threshold)
        if similar:
            warn(
                "similar_claims",
                f"{similar} pair(s) of claims share at least "
                f"{cfg.similar_claim_threshold:.0%} of their words; "
                "merge them or state a distinct point.",
            )
        with_evidence = sum(1 for claim in claims if claim.evidence)
        coverage = with_evidence / len(claims) if claims else 0.0
        if claims and coverage < cfg.min_evidence_coverage:
            warn(
                "low_evidence_coverage",
                f"Only {with_evidence}/{len(claims)} claims carry evidence "
                f"({coverage:.0%}); minimum {cfg.min_evidence_coverage:.0%}.",
            )
        if not package.research_questions:
            warn(
                "no_questions",
                "No research questions recorded; the investigation scope is undocumented.",
            )
        if not package.story_angles:
            warn(
                "no_story_angles",
                "No story angles recorded; the package has no narrative direction.",
            )

        if not sources or len(claims) < cfg.min_claims:
            status = "insufficient"
        elif warnings:
            status = "needs_review"
        else:
            status = "ready"
        return QualityReport(
            status=status,
            warnings=warnings,
            sources=SourceMetrics(
                total=len(sources),
                distinct_domains=len(domains),
                primary=tiers["primary"],
                secondary=tiers["secondary"],
                informal=tiers["informal"],
                unknown=tiers["unknown"],
            ),
            claims=ClaimMetrics(
                total=len(claims),
                supported=statuses["supported"],
                contradicted=contradicted,
                disputed=statuses["disputed"],
                unverified=statuses["unverified"],
                duplicate_statements=duplicates,
                similar_statements=similar,
            ),
            evidence=EvidenceMetrics(
                total_items=sum(len(claim.evidence) for claim in claims),
                claims_with_evidence=with_evidence,
                coverage=coverage,
            ),
            completeness=Completeness(
                has_summary=bool(package.summary.strip()),
                has_research_questions=bool(package.research_questions),
                has_story_angles=bool(package.story_angles),
            ),
        )