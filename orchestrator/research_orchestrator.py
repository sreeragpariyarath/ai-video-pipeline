from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

from .claim_synthesis import ClaimSynthesizer
from .claim_verifier import ClaimVerifier
from .discovery_schemas import DiscoveryResult
from .evidence_extractor import EvidenceExtraction
from .gemini import GeminiError
from .quality import QualityEvaluator, resource_limits
from .quality_schemas import QualityReport, ResourceUsage
from .research_planner import ResearchPlanner
from .research_schemas import (
    ClaimEvidence,
    ResearchClaim,
    ResearchPackage,
    ResearchPlan,
    ResearchSource,
    StoryAngle,
)
from .source_discovery import SourceDiscovery
from .verification_schemas import MAX_CLAIMS, MAX_EVIDENCE, VerificationResult


class ResearchError(RuntimeError):
    """A research stage could not produce meaningful output; message is sanitized."""


class ResearchResult(BaseModel):
    package: ResearchPackage
    quality: QualityReport
    usage: ResourceUsage


class ResearchOrchestrator:
    def __init__(
        self,
        planner: ResearchPlanner,
        discovery: SourceDiscovery,
        extraction: EvidenceExtraction,
        synthesizer: ClaimSynthesizer,
        verifier: ClaimVerifier,
        evaluator: QualityEvaluator | None = None,
    ):
        self._planner = planner
        self._discovery = discovery
        self._extraction = extraction
        self._synthesizer = synthesizer
        self._verifier = verifier
        self._evaluator = evaluator or QualityEvaluator()

    def research(self, topic: str, *, target_seconds: float = 35.0) -> ResearchResult:
        try:
            plan = self._planner.plan(topic, target_seconds=target_seconds)
        except GeminiError as exc:
            # Planner errors can embed model output; keep the classification only.
            raise ResearchError("Research planning failed.") from None
        discovery = self._discovery.discover(plan)
        if not discovery.candidates:
            raise ResearchError("Source discovery found no usable sources.")
        extraction = self._extraction.extract(plan, discovery)
        pool = [
            evidence
            for source in extraction.sources
            if source.status == "ok"
            for evidence in source.evidence
        ][:MAX_EVIDENCE]
        if not pool:
            raise ResearchError(
                "No evidence could be extracted from the discovered sources."
            )
        # The built-in synthesizers cap their own output, but the orchestrator
        # enforces the run-wide ceiling so a custom component cannot blow it.
        claims = self._synthesizer.synthesize(
            plan.topic, plan.core_question, pool
        )[:MAX_CLAIMS]
        verification = self._verifier.verify(claims, pool)
        package = self._assemble(plan, discovery, pool, claims, verification)
        usage = ResourceUsage(
            queries_executed=discovery.queries_executed,
            queries_failed=sum(q.status == "failed" for q in discovery.queries),
            candidates_discovered=len(discovery.candidates),
            sources_processed=extraction.sources_processed,
            sources_failed=extraction.sources_failed,
            evidence_items=len(pool),
            claims_verified=len(claims),
            limits=resource_limits(self._discovery.config, self._extraction.config),
        )
        return ResearchResult(
            package=package,
            quality=self._evaluator.evaluate(package),
            usage=usage,
        )

    def _assemble(
        self,
        plan: ResearchPlan,
        discovery: DiscoveryResult,
        pool: list[ClaimEvidence],
        claims: list[ResearchClaim],
        verification: VerificationResult,
    ) -> ResearchPackage:
        judged = {item.claim_id: item for item in verification.verifications}
        final_claims = [
            ResearchClaim.model_validate(
                {
                    **claim.model_dump(),
                    "verification_status": judged[claim.claim_id].status,
                    "confidence": judged[claim.claim_id].confidence,
                }
            )
            for claim in claims
        ]
        used_sources = {item.source_id for item in pool}
        sources = [
            ResearchSource(
                source_id=candidate.source_id,
                title=candidate.title,
                url=candidate.canonical_url,
                domain=candidate.domain,
                source_type=candidate.source_tier,
                published_date=candidate.published_date,
                retrieved_at=candidate.discovered_at,
                description=candidate.snippet,
            )
            for candidate in discovery.candidates
            if candidate.source_id in used_sources
        ]
        return ResearchPackage(
            research_id=uuid.uuid4().hex,
            topic=plan.topic,
            created_at=datetime.now(timezone.utc),
            summary=(
                f"Research on {plan.topic}: {len(sources)} sources, "
                f"{len(final_claims)} claims verified against extracted evidence."
            ),
            research_questions=[q.question for q in plan.research_questions],
            sources=sources,
            claims=final_claims,
            story_angles=[
                StoryAngle(
                    title=direction.angle,
                    premise=direction.description,
                    why_interesting=(
                        f"Planner-selected direction for: {plan.target_audience}."
                    ),
                )
                for direction in plan.story_directions
            ],
        )