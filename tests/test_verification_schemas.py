from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from orchestrator.verification_schemas import (
    MAX_CLAIMS,
    MAX_EVIDENCE,
    ClaimVerification,
    ClaimVerificationContent,
    ClaimVerificationsContent,
    EvidenceEvaluation,
    EvidenceJudgment,
    VerificationResult,
)


def judgment(evidence_id="ev-1", relationship="supports", source_id="s1"):
    return EvidenceJudgment(
        evidence_id=evidence_id, source_id=source_id, relationship=relationship
    )


def verification(status="supported", evidence=None, **overrides):
    kwargs = {
        "claim_id": "c1",
        "status": status,
        "confidence": 0.8,
        "rationale": "The excerpt directly establishes the claim.",
        "evidence": [judgment()] if evidence is None else evidence,
    }
    kwargs.update(overrides)
    return ClaimVerification(**kwargs)


def content_dict(**overrides):
    data = {
        "claim_id": "c1",
        "status": "supported",
        "confidence": 0.9,
        "rationale": "Directly stated.",
        "evaluations": [
            {"evidence_id": "ev-1", "relationship": "supports", "note": "Direct."}
        ],
    }
    data.update(overrides)
    return data


def now():
    return datetime.now(timezone.utc)


class TestClaimVerification:
    def test_supported_valid(self):
        result = verification("supported", [judgment()])
        assert result.status == "supported"

    def test_contradicted_valid(self):
        result = verification("contradicted", [judgment(relationship="contradicts")])
        assert result.status == "contradicted"

    def test_disputed_valid(self):
        result = verification(
            "disputed",
            [judgment("ev-1", "supports"), judgment("ev-2", "contradicts", "s2")],
        )
        assert result.status == "disputed"

    def test_unverified_valid_without_evidence(self):
        result = verification("unverified", [])
        assert result.evidence == []

    def test_unverified_valid_with_contextual_evidence(self):
        result = verification("unverified", [judgment(relationship="contextualizes")])
        assert result.status == "unverified"

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            verification("likely")

    def test_invalid_relationship_rejected(self):
        with pytest.raises(ValidationError):
            judgment(relationship="refutes")

    @pytest.mark.parametrize("value", [1.5, -0.1, float("nan"), float("inf"), True, False])
    def test_invalid_confidence_rejected(self, value):
        with pytest.raises(ValidationError):
            verification(confidence=value)

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_boundary_confidence_accepted(self, value):
        assert verification(confidence=value).confidence == value

    def test_duplicate_evidence_ids_rejected(self):
        with pytest.raises(ValidationError, match="duplicate evidence ID"):
            verification("supported", [judgment("ev-1"), judgment("ev-1", "supports", "s2")])

    def test_supported_without_supporting_evidence_rejected(self):
        with pytest.raises(ValidationError, match="supporting evidence"):
            verification("supported", [judgment(relationship="contextualizes")])

    def test_supported_without_any_evidence_rejected(self):
        with pytest.raises(ValidationError, match="supporting evidence"):
            verification("supported", [])

    def test_contradicted_without_contradicting_evidence_rejected(self):
        with pytest.raises(ValidationError, match="contradicting evidence"):
            verification("contradicted", [judgment()])

    def test_disputed_requires_both_sides(self):
        with pytest.raises(ValidationError, match="both supporting and contradicting"):
            verification("disputed", [judgment()])
        with pytest.raises(ValidationError, match="both supporting and contradicting"):
            verification("disputed", [judgment(relationship="contradicts")])

    def test_empty_rationale_rejected(self):
        with pytest.raises(ValidationError):
            verification(rationale="   ")

    def test_overlong_rationale_rejected(self):
        with pytest.raises(ValidationError):
            verification(rationale="x" * 501)

    def test_missing_fields_rejected(self):
        with pytest.raises(ValidationError):
            ClaimVerification(claim_id="c1", status="supported")


class TestEvidenceJudgment:
    def test_missing_source_id_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceJudgment(evidence_id="ev-1", relationship="supports")

    def test_empty_ids_rejected(self):
        with pytest.raises(ValidationError):
            judgment(evidence_id="  ")
        with pytest.raises(ValidationError):
            judgment(source_id="  ")


class TestAiContentSchemas:
    def test_valid_content(self):
        content = ClaimVerificationContent.model_validate(content_dict())
        assert content.evaluations[0].evidence_id == "ev-1"

    @pytest.mark.parametrize(
        "field", ["claim_id", "status", "confidence", "rationale", "evaluations"]
    )
    def test_missing_field_rejected(self, field):
        data = content_dict()
        del data[field]
        with pytest.raises(ValidationError):
            ClaimVerificationContent.model_validate(data)

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            ClaimVerificationContent.model_validate(content_dict(status="probably"))

    def test_invalid_relationship_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceEvaluation(evidence_id="ev-1", relationship="mentions", note="")

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 2.0])
    def test_invalid_confidence_rejected(self, value):
        with pytest.raises(ValidationError):
            ClaimVerificationContent.model_validate(content_dict(confidence=value))

    def test_empty_note_allowed(self):
        item = EvidenceEvaluation(evidence_id="ev-1", relationship="supports", note="")
        assert item.note == ""

    def test_overlong_note_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceEvaluation(evidence_id="ev-1", relationship="supports", note="x" * 301)

    def test_evaluations_cap_enforced(self):
        evaluations = [
            {"evidence_id": f"ev-{i}", "relationship": "supports", "note": ""}
            for i in range(MAX_EVIDENCE + 1)
        ]
        with pytest.raises(ValidationError):
            ClaimVerificationContent.model_validate(content_dict(evaluations=evaluations))

    def test_verifications_cap_enforced(self):
        items = [content_dict(claim_id=f"c{i}") for i in range(MAX_CLAIMS + 1)]
        with pytest.raises(ValidationError):
            ClaimVerificationsContent.model_validate({"verifications": items})

    def test_duplicate_evaluation_ids_allowed_in_ai_schema(self):
        # Reference integrity is enforced by the verifier, not the AI schema,
        # so the raw model output can still be parsed and classified.
        evaluations = [
            {"evidence_id": "ev-1", "relationship": "supports", "note": ""},
            {"evidence_id": "ev-1", "relationship": "supports", "note": ""},
        ]
        content = ClaimVerificationContent.model_validate(
            content_dict(evaluations=evaluations)
        )
        assert len(content.evaluations) == 2

    @pytest.mark.parametrize(
        "schema",
        [EvidenceEvaluation, ClaimVerificationContent, ClaimVerificationsContent],
    )
    def test_gemini_schema_compatibility(self, schema):
        def walk(node):
            if isinstance(node, dict):
                assert "anyOf" not in node, schema.__name__
                assert "oneOf" not in node, schema.__name__
                assert "default" not in node, schema.__name__
                if node.get("type") == "object":
                    assert set(node.get("required", [])) == set(
                        node.get("properties", {})
                    ), schema.__name__
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(schema.model_json_schema())


class TestVerificationResult:
    def test_valid_result(self):
        result = VerificationResult(verifications=[verification()], created_at=now())
        assert len(result.verifications) == 1

    def test_empty_result_valid(self):
        result = VerificationResult(verifications=[], created_at=now())
        assert result.verifications == []

    def test_duplicate_claim_ids_rejected(self):
        with pytest.raises(ValidationError, match="duplicate claim ID"):
            VerificationResult(
                verifications=[verification(), verification()], created_at=now()
            )

    def test_missing_created_at_rejected(self):
        with pytest.raises(ValidationError):
            VerificationResult(verifications=[])