from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.evidence_schemas import ExtractionConfig
from orchestrator.quality import QualityEvaluator, resource_limits
from orchestrator.quality_schemas import (
    ClaimMetrics,
    Completeness,
    EvidenceMetrics,
    QualityConfig,
    QualityReport,
    QualityWarning,
    ResourceLimits,
    ResourceUsage,
    SourceMetrics,
)
from orchestrator.research_schemas import (
    ClaimEvidence,
    ResearchClaim,
    ResearchPackage,
    ResearchSource,
    StoryAngle,
)
from orchestrator.source_discovery import DiscoveryConfig

from conftest import TOPIC


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def make_source(index: int, tier: str = "secondary", domain: str | None = None):
    domain = domain or f"d{index}.example.com"
    return ResearchSource(
        source_id=f"s{index}",
        title=f"Source {index}",
        url=f"https://{domain}/article",
        domain=domain,
        source_type=tier,
        retrieved_at=NOW,
    )


def make_claim(
    index: int,
    status: str = "supported",
    statement: str | None = None,
    with_evidence: bool = True,
):
    return ResearchClaim(
        claim_id=f"c{index}",
        statement=statement or f"Claim number {index} about streaming prices.",
        category="financial",
        importance=0.5,
        confidence=0.9 if status == "supported" else 0.0,
        verification_status=status,
        evidence=[
            ClaimEvidence(
                source_id="s1",
                excerpt=f"Evidence for claim {index} about streaming prices.",
                relationship="supports",
            )
        ]
        if with_evidence
        else [],
    )


def make_package(sources, claims, questions=None, angles=None):
    return ResearchPackage(
        research_id="r1",
        topic=TOPIC,
        created_at=NOW,
        summary="Research summary.",
        research_questions=["What drives prices?"] if questions is None else questions,
        sources=sources,
        claims=claims,
        story_angles=[
            StoryAngle(title="Angle", premise="Premise", why_interesting="Because.")
        ]
        if angles is None
        else angles,
    )


def ready_package():
    return make_package(
        [make_source(1, "primary"), make_source(2), make_source(3)],
        [make_claim(1), make_claim(2), make_claim(3)],
    )


def codes(report):
    return [warning.code for warning in report.warnings]


class TestQualityLevels:
    def test_ready_research(self):
        report = QualityEvaluator().evaluate(ready_package())
        assert report.status == "ready"
        assert report.warnings == []

    def test_empty_sources_insufficient(self):
        report = QualityEvaluator().evaluate(make_package([], []))
        assert report.status == "insufficient"
        assert "no_sources" in codes(report)
        assert "too_few_claims" in codes(report)
        assert all(w.message for w in report.warnings)

    def test_empty_claims_insufficient(self):
        report = QualityEvaluator().evaluate(
            make_package([make_source(1), make_source(2), make_source(3)], [])
        )
        assert report.status == "insufficient"
        assert "too_few_claims" in codes(report)

    def test_claims_without_sources_insufficient(self):
        package = make_package([], [make_claim(1, with_evidence=False)])
        report = QualityEvaluator().evaluate(package)
        assert report.status == "insufficient"
        assert "no_sources" in codes(report)
        assert any("source" in warning.message for warning in report.warnings)

    def test_all_unverified_needs_review(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(i, "unverified") for i in range(1, 4)],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "all_unverified" in codes(report)

    def test_some_unverified_can_still_be_ready(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(1), make_claim(2), make_claim(3, "unverified")],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "ready"

    def test_significant_contradictions_needs_review(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(1), make_claim(2), make_claim(3, "contradicted")],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "contradictions" in codes(report)

    def test_minor_contradictions_below_threshold_ready(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(i) for i in range(1, 5)] + [make_claim(5, "contradicted")],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "ready"

    def test_disputed_claims_do_not_trigger_contradiction_warning(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(1), make_claim(2), make_claim(3, "disputed")],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "ready"
        assert report.claims.disputed == 1

    def test_duplicate_claims_warned(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [
                make_claim(1, statement="Prices rose in 2026."),
                make_claim(2, statement="  prices   ROSE in 2026.  "),
                make_claim(3),
            ],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "duplicate_claims" in codes(report)
        assert report.claims.duplicate_statements == 1

    def test_similar_claims_warned(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [
                make_claim(1, statement="Streaming prices rose 12 percent in 2026"),
                make_claim(2, statement="In 2026 streaming prices rose 12 percent"),
                make_claim(3),
            ],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "similar_claims" in codes(report)
        assert "duplicate_claims" not in codes(report)
        assert report.claims.duplicate_statements == 0
        assert report.claims.similar_statements == 1

    def test_similar_threshold_is_configurable(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [
                make_claim(
                    1, statement="streaming prices rose sharply in twenty twenty six"
                ),
                make_claim(2, statement="streaming prices rose in twenty twenty six"),
            ],
        )
        strict = QualityEvaluator(QualityConfig(similar_claim_threshold=0.9))
        relaxed = QualityEvaluator(QualityConfig(similar_claim_threshold=0.8))
        assert "similar_claims" not in codes(strict.evaluate(package))
        similar_report = relaxed.evaluate(package)
        assert "similar_claims" in codes(similar_report)
        assert similar_report.claims.similar_statements == 1

    def test_distinct_claims_not_flagged(self):
        report = QualityEvaluator().evaluate(ready_package())
        assert report.claims.duplicate_statements == 0
        assert report.claims.similar_statements == 0

    def test_weak_evidence_coverage_warned(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(1), make_claim(2, with_evidence=False)],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "low_evidence_coverage" in codes(report)
        assert report.evidence.coverage == 0.5

    def test_single_domain_warned(self):
        package = make_package(
            [make_source(i, "secondary", domain="one.example.com") for i in range(1, 4)],
            [make_claim(1), make_claim(2), make_claim(3)],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "low_diversity" in codes(report)
        assert report.sources.distinct_domains == 1

    def test_informal_only_warned(self):
        package = make_package(
            [make_source(i, "informal") for i in range(1, 4)],
            [make_claim(1), make_claim(2), make_claim(3)],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "informal_only" in codes(report)

    def test_few_sources_warned(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2)],
            [make_claim(1), make_claim(2)],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.status == "needs_review"
        assert "few_sources" in codes(report)

    def test_missing_questions_and_angles_warned(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(1), make_claim(2), make_claim(3)],
            questions=[],
            angles=[],
        )
        report = QualityEvaluator().evaluate(package)
        assert "no_questions" in codes(report)
        assert "no_story_angles" in codes(report)
        assert report.completeness.has_research_questions is False
        assert report.completeness.has_story_angles is False
        assert report.completeness.has_summary is True


class TestMetrics:
    def test_source_metrics(self):
        package = make_package(
            [
                make_source(1, "primary"),
                make_source(2, "secondary"),
                make_source(3, "informal"),
                make_source(4, "unknown"),
            ],
            [make_claim(1)],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.sources.total == 4
        assert report.sources.primary == 1
        assert report.sources.secondary == 1
        assert report.sources.informal == 1
        assert report.sources.unknown == 1
        assert report.sources.distinct_domains == 4

    def test_claim_and_evidence_metrics(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [
                make_claim(1),
                make_claim(2, "contradicted"),
                make_claim(3, "disputed"),
                make_claim(4, "unverified", with_evidence=False),
            ],
        )
        report = QualityEvaluator().evaluate(package)
        assert report.claims.total == 4
        assert report.claims.supported == 1
        assert report.claims.contradicted == 1
        assert report.claims.disputed == 1
        assert report.claims.unverified == 1
        assert report.evidence.total_items == 3
        assert report.evidence.claims_with_evidence == 3
        assert report.evidence.coverage == 0.75

    def test_deterministic_output(self):
        package = ready_package()
        first = QualityEvaluator().evaluate(package)
        second = QualityEvaluator().evaluate(package)
        assert first == second

    def test_evaluation_does_not_mutate_package(self):
        package = ready_package()
        snapshot = package.model_dump()
        QualityEvaluator().evaluate(package)
        assert package.model_dump() == snapshot


class TestQualityConfig:
    def test_custom_thresholds(self):
        config = QualityConfig(min_sources=5, min_distinct_domains=4)
        report = QualityEvaluator(config).evaluate(ready_package())
        assert report.status == "needs_review"
        assert "few_sources" in codes(report)
        assert "low_diversity" in codes(report)

    def test_custom_contradiction_ratio(self):
        package = make_package(
            [make_source(1, "primary"), make_source(2), make_source(3)],
            [make_claim(i) for i in range(1, 5)] + [make_claim(5, "contradicted")],
        )
        report = QualityEvaluator(QualityConfig(contradiction_ratio=0.2)).evaluate(package)
        assert "contradictions" in codes(report)

    def test_custom_min_claims(self):
        report = QualityEvaluator(QualityConfig(min_claims=5)).evaluate(ready_package())
        assert report.status == "insufficient"
        assert "too_few_claims" in codes(report)

    @pytest.mark.parametrize("value", [0, -1, True, 1.5])
    def test_invalid_min_sources_rejected(self, value):
        with pytest.raises(ValidationError):
            QualityConfig(min_sources=value)

    @pytest.mark.parametrize("value", [-0.1, 1.5, float("nan"), True])
    def test_invalid_coverage_rejected(self, value):
        with pytest.raises(ValidationError):
            QualityConfig(min_evidence_coverage=value)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            QualityConfig(unknown_threshold=1)


class TestReportValidation:
    def metrics(self, claims_total=1):
        return {
            "sources": SourceMetrics(
                total=1, distinct_domains=1, primary=1, secondary=0, informal=0, unknown=0
            ),
            "claims": ClaimMetrics(
                total=claims_total,
                supported=claims_total,
                contradicted=0,
                disputed=0,
                unverified=0,
                duplicate_statements=0,
            ),
            "evidence": EvidenceMetrics(
                total_items=claims_total, claims_with_evidence=claims_total, coverage=1.0
            ),
            "completeness": Completeness(
                has_summary=True, has_research_questions=True, has_story_angles=True
            ),
        }

    def test_ready_with_warnings_rejected(self):
        with pytest.raises(ValidationError, match="ready reports"):
            QualityReport(
                status="ready",
                warnings=[QualityWarning(code="x", message="Why.")],
                **self.metrics(),
            )

    def test_needs_review_without_warnings_rejected(self):
        with pytest.raises(ValidationError, match="needs_review"):
            QualityReport(status="needs_review", warnings=[], **self.metrics())

    def test_insufficient_without_warnings_rejected(self):
        with pytest.raises(ValidationError, match="insufficient"):
            QualityReport(status="insufficient", warnings=[], **self.metrics())

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            QualityReport(status="excellent", warnings=[], **self.metrics())

    def test_claim_counts_must_sum(self):
        with pytest.raises(ValidationError, match="sum to total"):
            ClaimMetrics(
                total=3, supported=1, contradicted=0, disputed=0, unverified=0,
                duplicate_statements=0,
            )

    def test_claims_with_evidence_cannot_exceed_total(self):
        data = self.metrics(claims_total=1)
        data["evidence"] = EvidenceMetrics(
            total_items=2, claims_with_evidence=2, coverage=1.0
        )
        with pytest.raises(ValidationError, match="cannot exceed"):
            QualityReport(status="ready", warnings=[], **data)

    def test_duplicate_warning_codes_rejected(self):
        with pytest.raises(ValidationError, match="duplicate warning codes"):
            QualityReport(
                status="needs_review",
                warnings=[
                    QualityWarning(code="x", message="One."),
                    QualityWarning(code="x", message="Two."),
                ],
                **self.metrics(),
            )

    def test_boolean_metrics_rejected(self):
        with pytest.raises(ValidationError):
            SourceMetrics(
                total=True, distinct_domains=1, primary=1, secondary=0, informal=0, unknown=0
            )


def default_limits():
    return resource_limits(DiscoveryConfig(), ExtractionConfig())


class TestResourceLimits:
    def test_default_limits(self):
        limits = default_limits()
        assert limits.max_research_questions == 12
        assert limits.max_search_queries == 10
        assert limits.max_candidates == 30
        assert limits.max_sources_fetched == 8
        assert limits.max_fetch_requests_per_source == 18
        assert limits.max_fetch_seconds_per_source == 30.0
        assert limits.max_evidence_items == 60
        assert limits.max_claims == 24
        assert limits.max_gemini_calls == 11

    def test_custom_configs_reflected(self):
        limits = resource_limits(
            DiscoveryConfig(max_queries=4, max_candidates=12),
            ExtractionConfig(max_sources=3, max_retries=1, max_redirects=2),
        )
        assert limits.max_search_queries == 4
        assert limits.max_candidates == 12
        assert limits.max_sources_fetched == 3
        assert limits.max_fetch_requests_per_source == 6
        assert limits.max_gemini_calls == 6

    def test_limits_are_positive(self):
        with pytest.raises(ValidationError):
            ResourceLimits(
                max_research_questions=0,
                max_search_queries=10,
                max_candidates=30,
                max_sources_fetched=8,
                max_fetch_requests_per_source=18,
                max_fetch_seconds_per_source=30.0,
                max_evidence_items=60,
                max_claims=24,
                max_gemini_calls=11,
            )


class TestResourceUsage:
    def usage(self, **overrides):
        data = {
            "queries_executed": 5,
            "queries_failed": 0,
            "candidates_discovered": 9,
            "sources_processed": 9,
            "sources_failed": 0,
            "evidence_items": 8,
            "claims_verified": 8,
            "limits": default_limits(),
        }
        data.update(overrides)
        return ResourceUsage(**data)

    def test_valid_usage(self):
        assert self.usage().queries_executed == 5

    def test_failed_queries_cannot_exceed_executed(self):
        with pytest.raises(ValidationError, match="queries_failed"):
            self.usage(queries_executed=2, queries_failed=3)

    def test_failed_sources_cannot_exceed_processed(self):
        with pytest.raises(ValidationError, match="sources_failed"):
            self.usage(sources_processed=1, sources_failed=2)

    def test_queries_bounded_by_limit(self):
        with pytest.raises(ValidationError, match="max_search_queries"):
            self.usage(queries_executed=11)

    def test_candidates_bounded_by_limit(self):
        with pytest.raises(ValidationError, match="max_candidates"):
            self.usage(candidates_discovered=31)

    def test_processed_bounded_by_discovered(self):
        with pytest.raises(ValidationError, match="candidates_discovered"):
            self.usage(candidates_discovered=5, sources_processed=6)

    def test_failed_sources_bounded_by_fetch_limit(self):
        with pytest.raises(ValidationError, match="max_sources_fetched"):
            self.usage(sources_failed=9)

    def test_evidence_bounded_by_limit(self):
        with pytest.raises(ValidationError, match="max_evidence_items"):
            self.usage(evidence_items=61)

    def test_claims_bounded_by_limit(self):
        with pytest.raises(ValidationError, match="max_claims"):
            self.usage(claims_verified=25)

    def test_boolean_counts_rejected(self):
        with pytest.raises(ValidationError):
            self.usage(queries_executed=True)

    def test_negative_counts_rejected(self):
        with pytest.raises(ValidationError):
            self.usage(evidence_items=-1)

    def test_negative_limits_rejected(self):
        with pytest.raises(ValidationError):
            ResourceLimits(
                max_research_questions=12,
                max_search_queries=10,
                max_candidates=30,
                max_sources_fetched=-1,
                max_fetch_requests_per_source=18,
                max_fetch_seconds_per_source=30.0,
                max_evidence_items=60,
                max_claims=24,
                max_gemini_calls=11,
            )