import json
from datetime import datetime, timezone

import pytest

from orchestrator.claim_synthesis import ClaimSynthesizer, MockClaimSynthesizer, SynthesisError
from orchestrator.claim_verifier import MockClaimVerifier, VerificationError
from orchestrator.discovery_schemas import DiscoveryCandidate, DiscoveryResult
from orchestrator.evidence_extractor import MockEvidenceExtraction
from orchestrator.evidence_schemas import ExtractionResult, SourceExtraction
from orchestrator.gemini import GeminiClient, GeminiError
from orchestrator.research_orchestrator import ResearchError, ResearchOrchestrator
from orchestrator.research_planner import MockResearchPlanner
from orchestrator.research_schemas import ClaimEvidence, ResearchClaim, ResearchPackage
from orchestrator.search_provider import MockSearchProvider, SearchError, SearchProvider
from orchestrator.source_discovery import SourceDiscovery
from orchestrator.verification_schemas import (
    MAX_EVIDENCE,
    ClaimVerification,
    EvidenceJudgment,
    VerificationResult,
)

from conftest import TOPIC, make_response


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def make_candidate(index: int, tier: str = "secondary") -> DiscoveryCandidate:
    url = f"https://s{index}.example.com/article"
    return DiscoveryCandidate(
        source_id=f"s{index}",
        title=f"Source {index}",
        original_url=url,
        canonical_url=url,
        domain=f"s{index}.example.com",
        snippet=f"Snippet about {TOPIC} number {index}.",
        source_tier=tier,
        tier_reason="test fixture",
        question_ids=["q1"],
        discovered_by_queries=["test query"],
        discovered_at=NOW,
    )


def make_discovery(candidates) -> DiscoveryResult:
    return DiscoveryResult(
        topic=TOPIC,
        candidates=candidates,
        queries=[],
        queries_executed=0,
        results_examined=0,
        duplicates_removed=0,
        created_at=NOW,
    )


def make_evidence(source_id: str, index: int = 1) -> ClaimEvidence:
    return ClaimEvidence(
        source_id=source_id,
        excerpt=f"Evidence {index} from {source_id} about streaming prices.",
        relationship="supports",
    )


def ok_source(source_id: str, evidence) -> SourceExtraction:
    return SourceExtraction(
        source_id=source_id,
        canonical_url=f"https://{source_id}.example.com/article",
        status="ok",
        evidence=evidence,
        chars_extracted=100,
    )


def failed_source(source_id: str) -> SourceExtraction:
    return SourceExtraction(
        source_id=source_id,
        canonical_url=f"https://{source_id}.example.com/article",
        status="failed",
        error="Gemini request failed.",
    )


def skipped_source(source_id: str) -> SourceExtraction:
    return SourceExtraction(
        source_id=source_id,
        canonical_url=f"https://{source_id}.example.com/article",
        status="skipped",
    )


def make_extraction_result(sources) -> ExtractionResult:
    return ExtractionResult(
        topic=TOPIC,
        sources=sources,
        sources_processed=len(sources),
        sources_succeeded=sum(s.status == "ok" for s in sources),
        sources_failed=sum(s.status == "failed" for s in sources),
        sources_skipped=sum(s.status == "skipped" for s in sources),
        created_at=NOW,
    )


class FakePlanner:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def plan(self, topic, *, target_seconds=35.0, context=None):
        self.calls.append((topic, target_seconds))
        if self.error:
            raise self.error
        return MockResearchPlanner().plan(topic, target_seconds=target_seconds)


class FakeDiscovery:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def discover(self, plan):
        self.calls.append(plan)
        return self.result


class FakeExtraction:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def extract(self, plan, discovery):
        self.calls.append((plan, discovery))
        return self.result


class FakeSynthesizer:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def synthesize(self, topic, core_question, evidence):
        self.calls.append((topic, core_question, evidence))
        if self.error:
            raise self.error
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
            for index, item in enumerate(evidence, start=1)
        ]


class FakeVerifier:
    def __init__(self, statuses=None, error=None):
        self.statuses = statuses or {}
        self.error = error
        self.calls = []

    def verify(self, claims, evidence):
        self.calls.append((claims, evidence))
        if self.error:
            raise self.error
        items = []
        for claim in claims:
            status = self.statuses.get(claim.claim_id, "supported")
            if status == "contradicted":
                judgments = [
                    EvidenceJudgment(
                        evidence_id="ev-1", source_id="s1", relationship="contradicts"
                    )
                ]
                confidence = 0.85
            elif status == "unverified":
                judgments = []
                confidence = 0.0
            else:
                status = "supported"
                judgments = [
                    EvidenceJudgment(
                        evidence_id="ev-1", source_id="s1", relationship="supports"
                    )
                ]
                confidence = 0.9
            items.append(
                ClaimVerification(
                    claim_id=claim.claim_id,
                    status=status,
                    confidence=confidence,
                    rationale="Fake judgment.",
                    evidence=judgments,
                )
            )
        return VerificationResult(verifications=items, created_at=NOW)


class ScriptedProvider(SearchProvider):
    def __init__(self, fail_queries=()):
        self.fail_queries = set(fail_queries)
        self.calls = []
        self._inner = MockSearchProvider()

    def _search(self, query, *, max_results):
        self.calls.append(query)
        if query in self.fail_queries:
            raise SearchError("provider unavailable")
        return self._inner._search(query, max_results=max_results)


class Recording:
    def __init__(self, name, inner, log):
        self._name = name
        self._inner = inner
        self._log = log

    def __getattr__(self, attr):
        target = getattr(self._inner, attr)

        def wrapper(*args, **kwargs):
            result = target(*args, **kwargs)
            self._log.append((self._name, attr, args, kwargs, result))
            return result

        return wrapper


def make_orchestrator(
    planner=None, discovery=None, extraction=None, synthesizer=None, verifier=None
):
    return ResearchOrchestrator(
        planner=planner or MockResearchPlanner(),
        discovery=discovery or SourceDiscovery(MockSearchProvider()),
        extraction=extraction or MockEvidenceExtraction(),
        synthesizer=synthesizer or MockClaimSynthesizer(),
        verifier=verifier or MockClaimVerifier(),
    )


class TestEndToEnd:
    def test_mock_pipeline_produces_valid_package(self):
        package = make_orchestrator().research(TOPIC)
        assert isinstance(package, ResearchPackage)
        assert package.topic == TOPIC
        assert package.claims
        assert all(c.verification_status == "supported" for c in package.claims)
        assert all(c.confidence == 0.9 for c in package.claims)
        assert package.sources
        assert TOPIC in package.summary
        assert len(package.research_questions) == 4
        assert [a.title for a in package.story_angles] == [
            "The hidden mechanism",
            "Follow the money",
        ]

    def test_claim_evidence_preserved(self):
        package = make_orchestrator().research(TOPIC)
        source_ids = {s.source_id for s in package.sources}
        for claim in package.claims:
            assert claim.evidence
            for item in claim.evidence:
                assert item.source_id in source_ids

    def test_stage_order_and_data_flow(self):
        log = []
        orchestrator = ResearchOrchestrator(
            planner=Recording("planner", MockResearchPlanner(), log),
            discovery=Recording("discovery", SourceDiscovery(MockSearchProvider()), log),
            extraction=Recording("extraction", MockEvidenceExtraction(), log),
            synthesizer=Recording("synthesizer", MockClaimSynthesizer(), log),
            verifier=Recording("verifier", MockClaimVerifier(), log),
        )
        orchestrator.research(TOPIC)
        assert [(name, attr) for name, attr, *_ in log] == [
            ("planner", "plan"),
            ("discovery", "discover"),
            ("extraction", "extract"),
            ("synthesizer", "synthesize"),
            ("verifier", "verify"),
        ]
        plan = log[0][4]
        discovery = log[1][4]
        assert log[1][2] == (plan,)
        assert log[2][2] == (plan, discovery)
        pool = log[3][2][2]
        assert log[3][2][:2] == (plan.topic, plan.core_question)
        claims = log[3][4]
        assert log[4][2] == (claims, pool)

    def test_target_seconds_passed_to_planner(self):
        log = []
        orchestrator = make_orchestrator(
            planner=Recording("planner", MockResearchPlanner(), log)
        )
        package = orchestrator.research(TOPIC, target_seconds=20.0)
        assert log[0][3] == {"target_seconds": 20.0}
        assert package.topic == TOPIC

    def test_deterministic_with_mocks(self):
        first = make_orchestrator().research(TOPIC)
        second = make_orchestrator().research(TOPIC)
        assert first.claims == second.claims
        assert first.summary == second.summary
        assert first.research_questions == second.research_questions
        assert first.story_angles == second.story_angles
        assert [s.source_id for s in first.sources] == [
            s.source_id for s in second.sources
        ]
        assert first.research_id != second.research_id

    def test_invalid_topic_rejected_before_discovery(self):
        discovery = FakeDiscovery(make_discovery([]))
        with pytest.raises(ValueError):
            make_orchestrator(discovery=discovery).research("   ")
        assert discovery.calls == []


class TestPartialFailures:
    def test_empty_discovery_fails_clearly(self):
        extraction = FakeExtraction(make_extraction_result([]))
        synthesizer = FakeSynthesizer()
        verifier = FakeVerifier()
        with pytest.raises(ResearchError, match="no usable sources"):
            make_orchestrator(
                discovery=FakeDiscovery(make_discovery([])),
                extraction=extraction,
                synthesizer=synthesizer,
                verifier=verifier,
            ).research(TOPIC)
        assert extraction.calls == []
        assert synthesizer.calls == []
        assert verifier.calls == []

    def test_single_failed_source_does_not_abort(self):
        discovery = make_discovery([make_candidate(1), make_candidate(2)])
        extraction = make_extraction_result(
            [ok_source("s1", [make_evidence("s1")]), failed_source("s2")]
        )
        package = make_orchestrator(
            discovery=FakeDiscovery(discovery),
            extraction=FakeExtraction(extraction),
            synthesizer=FakeSynthesizer(),
            verifier=FakeVerifier(),
        ).research(TOPIC)
        assert [s.source_id for s in package.sources] == ["s1"]
        assert len(package.claims) == 1

    def test_all_sources_failed_fails_clearly(self):
        discovery = make_discovery([make_candidate(1), make_candidate(2)])
        extraction = make_extraction_result([failed_source("s1"), failed_source("s2")])
        synthesizer = FakeSynthesizer()
        with pytest.raises(ResearchError, match="No evidence"):
            make_orchestrator(
                discovery=FakeDiscovery(discovery),
                extraction=FakeExtraction(extraction),
                synthesizer=synthesizer,
            ).research(TOPIC)
        assert synthesizer.calls == []

    def test_ok_sources_without_evidence_fails_clearly(self):
        discovery = make_discovery([make_candidate(1)])
        extraction = make_extraction_result([ok_source("s1", [])])
        with pytest.raises(ResearchError, match="No evidence"):
            make_orchestrator(
                discovery=FakeDiscovery(discovery),
                extraction=FakeExtraction(extraction),
            ).research(TOPIC)

    def test_skipped_sources_excluded_from_package(self):
        discovery = make_discovery([make_candidate(1), make_candidate(2)])
        extraction = make_extraction_result(
            [ok_source("s1", [make_evidence("s1")]), skipped_source("s2")]
        )
        package = make_orchestrator(
            discovery=FakeDiscovery(discovery),
            extraction=FakeExtraction(extraction),
            synthesizer=FakeSynthesizer(),
            verifier=FakeVerifier(),
        ).research(TOPIC)
        assert [s.source_id for s in package.sources] == ["s1"]

    def test_individual_query_failures_tolerated(self):
        provider = ScriptedProvider(fail_queries=[f"{TOPIC} pricing costs statistics"])
        package = make_orchestrator(
            discovery=SourceDiscovery(provider)
        ).research(TOPIC)
        assert package.claims
        assert len(provider.calls) == 5

    def test_all_queries_failed_fails_clearly(self):
        plan = MockResearchPlanner().plan(TOPIC)
        provider = ScriptedProvider(fail_queries=[q.query for q in plan.search_queries])
        with pytest.raises(ResearchError, match="no usable sources"):
            make_orchestrator(discovery=SourceDiscovery(provider)).research(TOPIC)

    def test_verification_failure_propagates(self):
        discovery = make_discovery([make_candidate(1)])
        extraction = make_extraction_result([ok_source("s1", [make_evidence("s1")])])
        verifier = FakeVerifier(error=VerificationError("Gemini request failed."))
        with pytest.raises(VerificationError, match="Gemini request failed"):
            make_orchestrator(
                discovery=FakeDiscovery(discovery),
                extraction=FakeExtraction(extraction),
                synthesizer=FakeSynthesizer(),
                verifier=verifier,
            ).research(TOPIC)

    def test_fatal_planning_failure_sanitized(self):
        secret = "SECRET-MODEL-OUTPUT-2k4j"
        discovery = FakeDiscovery(make_discovery([]))
        with pytest.raises(ResearchError) as excinfo:
            make_orchestrator(
                planner=FakePlanner(error=GeminiError(f"bad output: {secret}")),
                discovery=discovery,
            ).research(TOPIC)
        assert str(excinfo.value) == "Research planning failed."
        assert secret not in str(excinfo.value)
        assert discovery.calls == []

    def test_invalid_synthesis_output_propagates(self, fake_sdk, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-not-real")
        fake_sdk.responses.append(
            make_response(
                text=json.dumps(
                    {
                        "claims": [
                            {
                                "statement": "A fabricated claim.",
                                "category": "general",
                                "evidence_ids": ["ev-999"],
                                "caveats": [],
                            }
                        ]
                    }
                )
            )
        )
        with pytest.raises(SynthesisError, match="invalid claim synthesis output"):
            make_orchestrator(
                synthesizer=ClaimSynthesizer(GeminiClient())
            ).research(TOPIC)


class TestAssembly:
    def test_verification_results_mapped_to_claims(self):
        discovery = make_discovery([make_candidate(1)])
        extraction = make_extraction_result(
            [ok_source("s1", [make_evidence("s1", 1), make_evidence("s1", 2)])]
        )
        verifier = FakeVerifier(statuses={"cl-1": "contradicted", "cl-2": "unverified"})
        package = make_orchestrator(
            discovery=FakeDiscovery(discovery),
            extraction=FakeExtraction(extraction),
            synthesizer=FakeSynthesizer(),
            verifier=verifier,
        ).research(TOPIC)
        assert [c.verification_status for c in package.claims] == [
            "contradicted",
            "unverified",
        ]
        assert [c.confidence for c in package.claims] == [0.85, 0.0]

    def test_unknown_tier_preserved(self):
        discovery = make_discovery([make_candidate(1, tier="unknown")])
        extraction = make_extraction_result([ok_source("s1", [make_evidence("s1")])])
        package = make_orchestrator(
            discovery=FakeDiscovery(discovery),
            extraction=FakeExtraction(extraction),
            synthesizer=FakeSynthesizer(),
            verifier=FakeVerifier(),
        ).research(TOPIC)
        assert package.sources[0].source_type == "unknown"

    def test_source_metadata_from_discovery(self):
        candidate = make_candidate(1)
        discovery = make_discovery([candidate])
        extraction = make_extraction_result([ok_source("s1", [make_evidence("s1")])])
        package = make_orchestrator(
            discovery=FakeDiscovery(discovery),
            extraction=FakeExtraction(extraction),
            synthesizer=FakeSynthesizer(),
            verifier=FakeVerifier(),
        ).research(TOPIC)
        source = package.sources[0]
        assert source.url == candidate.canonical_url
        assert source.title == candidate.title
        assert source.domain == candidate.domain
        assert source.retrieved_at == candidate.discovered_at
        assert source.description == candidate.snippet

    def test_evidence_pool_capped(self):
        discovery = make_discovery([make_candidate(1)])
        evidence = [make_evidence("s1", i) for i in range(MAX_EVIDENCE + 10)]
        extraction = make_extraction_result([ok_source("s1", evidence)])
        synthesizer = FakeSynthesizer()
        verifier = FakeVerifier()
        make_orchestrator(
            discovery=FakeDiscovery(discovery),
            extraction=FakeExtraction(extraction),
            synthesizer=synthesizer,
            verifier=verifier,
        ).research(TOPIC)
        assert len(synthesizer.calls[0][2]) == MAX_EVIDENCE
        assert len(verifier.calls[0][1]) == MAX_EVIDENCE