from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from .gemini import GeminiClient, GeminiError
from .prompts import CLAIM_VERIFICATION_SYSTEM, claim_verification_prompt
from .research_schemas import ClaimEvidence, ResearchClaim
from .verification_schemas import (
    MAX_CLAIMS,
    MAX_EVIDENCE,
    ClaimVerification,
    ClaimVerificationsContent,
    EvidenceJudgment,
    VerificationResult,
)


class VerificationError(RuntimeError):
    """Claim verification failed; the message is application-defined and sanitized."""


def _validate_inputs(
    claims: list[ResearchClaim], evidence: list[ClaimEvidence]
) -> None:
    if not isinstance(claims, list) or not all(
        isinstance(claim, ResearchClaim) for claim in claims
    ):
        raise ValueError("claims must be a list of ResearchClaim instances")
    if not isinstance(evidence, list) or not all(
        isinstance(item, ClaimEvidence) for item in evidence
    ):
        raise ValueError("evidence must be a list of ClaimEvidence instances")
    if len(claims) > MAX_CLAIMS:
        raise ValueError(f"too many claims: {len(claims)} (max {MAX_CLAIMS})")
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError(f"too many evidence items: {len(evidence)} (max {MAX_EVIDENCE})")
    seen: set[str] = set()
    for claim in claims:
        if claim.claim_id in seen:
            raise ValueError(f"duplicate claim ID: {claim.claim_id}")
        seen.add(claim.claim_id)


def _sanitized(exc: GeminiError) -> VerificationError:
    # GeminiError text can embed model output quoting page content; only
    # application-defined classifications are surfaced.
    message = str(exc)
    if "does not match" in message or "empty JSON" in message:
        return VerificationError("Gemini returned invalid verification output.")
    return VerificationError("Gemini request failed.")


def _invalid_output() -> VerificationError:
    return VerificationError("Gemini returned invalid verification output.")


class ClaimVerifier:
    def __init__(self, client: GeminiClient):
        self._client = client

    def verify(
        self, claims: list[ResearchClaim], evidence: list[ClaimEvidence]
    ) -> VerificationResult:
        _validate_inputs(claims, evidence)
        if not claims:
            return VerificationResult(
                verifications=[], created_at=datetime.now(timezone.utc)
            )
        if not evidence:
            return VerificationResult(
                verifications=[
                    ClaimVerification(
                        claim_id=claim.claim_id,
                        status="unverified",
                        confidence=0.0,
                        rationale="No evidence was supplied for this claim.",
                    )
                    for claim in claims
                ],
                created_at=datetime.now(timezone.utc),
            )
        # ClaimEvidence carries no ID of its own; the application assigns
        # deterministic IDs at this boundary and validates every reference.
        pool = {
            f"ev-{index}": item for index, item in enumerate(evidence, start=1)
        }
        try:
            ai = self._client.generate_json(
                system=CLAIM_VERIFICATION_SYSTEM,
                prompt=claim_verification_prompt(claims, list(pool.items())),
                schema=ClaimVerificationsContent,
                temperature=0.2,
            )
        except GeminiError as exc:
            raise _sanitized(exc) from None
        return self._build_result(claims, pool, ai)

    def _build_result(
        self,
        claims: list[ResearchClaim],
        pool: dict[str, ClaimEvidence],
        ai: ClaimVerificationsContent,
    ) -> VerificationResult:
        by_id = {item.claim_id: item for item in ai.verifications}
        if len(by_id) != len(ai.verifications):
            raise _invalid_output()
        if set(by_id) != {claim.claim_id for claim in claims}:
            raise _invalid_output()
        verifications: list[ClaimVerification] = []
        for claim in claims:
            content = by_id[claim.claim_id]
            seen: set[str] = set()
            judgments: list[EvidenceJudgment] = []
            for evaluation in content.evaluations:
                if evaluation.evidence_id not in pool or evaluation.evidence_id in seen:
                    raise _invalid_output()
                seen.add(evaluation.evidence_id)
                judgments.append(
                    EvidenceJudgment(
                        evidence_id=evaluation.evidence_id,
                        source_id=pool[evaluation.evidence_id].source_id,
                        relationship=evaluation.relationship,
                    )
                )
            try:
                verifications.append(
                    ClaimVerification(
                        claim_id=content.claim_id,
                        status=content.status,
                        confidence=content.confidence,
                        rationale=content.rationale,
                        evidence=judgments,
                    )
                )
            except ValidationError:
                raise _invalid_output() from None
        return VerificationResult(
            verifications=verifications, created_at=datetime.now(timezone.utc)
        )


class MockClaimVerifier:
    """Deterministic offline verification based on extracted relationships."""

    def verify(
        self, claims: list[ResearchClaim], evidence: list[ClaimEvidence]
    ) -> VerificationResult:
        _validate_inputs(claims, evidence)
        relationships = {item.relationship for item in evidence}
        if "supports" in relationships and "contradicts" in relationships:
            status, confidence = "disputed", 0.5
            rationale = "Supplied evidence both supports and contradicts this claim."
        elif "contradicts" in relationships:
            status, confidence = "contradicted", 0.85
            rationale = "Supplied evidence contradicts this claim."
        elif "supports" in relationships:
            status, confidence = "supported", 0.9
            rationale = "Supplied evidence supports this claim."
        else:
            status, confidence = "unverified", 0.0
            rationale = "Supplied evidence does not directly establish this claim."
        judgments = [
            EvidenceJudgment(
                evidence_id=f"ev-{index}",
                source_id=item.source_id,
                relationship=item.relationship,
            )
            for index, item in enumerate(evidence, start=1)
        ]
        return VerificationResult(
            verifications=[
                ClaimVerification(
                    claim_id=claim.claim_id,
                    status=status,
                    confidence=confidence,
                    rationale=rationale,
                    evidence=list(judgments),
                )
                for claim in claims
            ],
            created_at=datetime.now(timezone.utc),
        )