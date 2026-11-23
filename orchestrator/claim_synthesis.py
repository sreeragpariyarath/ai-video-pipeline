from __future__ import annotations

from pydantic import ValidationError

from .claim_schemas import ClaimSynthesisContent
from .gemini import GeminiClient, GeminiError
from .prompts import CLAIM_SYNTHESIS_SYSTEM, claim_synthesis_prompt
from .research_schemas import ClaimEvidence, ResearchClaim
from .verification_schemas import MAX_CLAIMS, MAX_EVIDENCE


class SynthesisError(RuntimeError):
    """Claim synthesis failed; the message is application-defined and sanitized."""


def _validate_inputs(
    topic: str, core_question: str, evidence: list[ClaimEvidence]
) -> None:
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("Topic must be a non-empty string.")
    if not isinstance(core_question, str) or not core_question.strip():
        raise ValueError("Core question must be a non-empty string.")
    if not isinstance(evidence, list) or not all(
        isinstance(item, ClaimEvidence) for item in evidence
    ):
        raise ValueError("evidence must be a list of ClaimEvidence instances")
    if not evidence:
        raise ValueError("Claim synthesis requires at least one evidence item.")
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError(f"too many evidence items: {len(evidence)} (max {MAX_EVIDENCE})")


def _invalid_output() -> SynthesisError:
    return SynthesisError("Gemini returned invalid claim synthesis output.")


def _sanitized(exc: GeminiError) -> SynthesisError:
    # GeminiError text can embed model output quoting page content; only
    # application-defined classifications are surfaced.
    message = str(exc)
    if "does not match" in message or "empty JSON" in message:
        return _invalid_output()
    return SynthesisError("Gemini request failed.")


class ClaimSynthesizer:
    def __init__(self, client: GeminiClient):
        self._client = client

    def synthesize(
        self, topic: str, core_question: str, evidence: list[ClaimEvidence]
    ) -> list[ResearchClaim]:
        _validate_inputs(topic, core_question, evidence)
        # Same deterministic ID convention as ClaimVerifier, so references
        # stay consistent when the same evidence list is passed to both.
        pool = {f"ev-{index}": item for index, item in enumerate(evidence, start=1)}
        try:
            ai = self._client.generate_json(
                system=CLAIM_SYNTHESIS_SYSTEM,
                prompt=claim_synthesis_prompt(topic, core_question, list(pool.items())),
                schema=ClaimSynthesisContent,
                temperature=0.3,
            )
        except GeminiError as exc:
            raise _sanitized(exc) from None
        claims: list[ResearchClaim] = []
        for index, item in enumerate(ai.claims[:MAX_CLAIMS], start=1):
            seen: set[str] = set()
            attached: list[ClaimEvidence] = []
            for evidence_id in item.evidence_ids:
                if evidence_id not in pool or evidence_id in seen:
                    raise _invalid_output()
                seen.add(evidence_id)
                attached.append(pool[evidence_id])
            try:
                claims.append(
                    ResearchClaim(
                        claim_id=f"cl-{index}",
                        statement=item.statement,
                        category=item.category,
                        # Flat placeholder ranking; quality scoring is a later task.
                        importance=0.5,
                        confidence=0.0,
                        verification_status="unverified",
                        evidence=attached,
                        caveats=item.caveats,
                    )
                )
            except ValidationError:
                raise _invalid_output() from None
        return claims


class MockClaimSynthesizer:
    """Deterministic offline synthesis: one claim per evidence excerpt."""

    def synthesize(
        self, topic: str, core_question: str, evidence: list[ClaimEvidence]
    ) -> list[ResearchClaim]:
        _validate_inputs(topic, core_question, evidence)
        return [
            ResearchClaim(
                claim_id=f"cl-{index}",
                statement=item.excerpt,
                category="general",
                importance=0.5,
                confidence=0.0,
                verification_status="unverified",
                evidence=[item],
            )
            for index, item in enumerate(evidence[:MAX_CLAIMS], start=1)
        ]