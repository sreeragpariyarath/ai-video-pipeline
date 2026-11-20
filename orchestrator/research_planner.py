from __future__ import annotations

import math
from datetime import datetime, timezone

from .gemini import GeminiClient
from .prompts import RESEARCH_PLANNING_SYSTEM, research_planning_prompt
from .research_schemas import (
    ResearchPlan,
    ResearchQuestion,
    SearchQuery,
    SourcePreferences,
    StoryDirection,
)


def _validate_inputs(topic: str, target_seconds: float) -> str:
    topic = topic.strip()
    if not topic:
        raise ValueError("Topic must not be empty.")
    if not math.isfinite(target_seconds) or target_seconds <= 0:
        raise ValueError("Target duration must be a finite number greater than 0.")
    return topic


class ResearchPlanner:
    def __init__(self, client: GeminiClient):
        self._client = client

    def plan(
        self,
        topic: str,
        *,
        target_seconds: float = 35.0,
        context: str | None = None,
    ) -> ResearchPlan:
        topic = _validate_inputs(topic, target_seconds)
        plan = self._client.generate_json(
            system=RESEARCH_PLANNING_SYSTEM,
            prompt=research_planning_prompt(topic, target_seconds, context),
            schema=ResearchPlan,
            temperature=0.5,
        )
        # The planner owns identity and timing; the model only supplies content.
        return plan.model_copy(
            update={
                "topic": topic,
                "target_seconds": target_seconds,
                "created_at": datetime.now(timezone.utc),
            }
        )


class MockResearchPlanner:
    def plan(
        self,
        topic: str,
        *,
        target_seconds: float = 35.0,
        context: str | None = None,
    ) -> ResearchPlan:
        topic = _validate_inputs(topic, target_seconds)
        questions = [
            ResearchQuestion(
                question_id="q1",
                question=f"What is the core mechanism behind {topic}?",
                reason="The explanation lives or dies on getting the mechanism right.",
                priority="high",
                expected_evidence="Primary documentation or official explanations of how it works.",
            ),
            ResearchQuestion(
                question_id="q2",
                question=f"What does {topic} cost, and who pays?",
                reason="The economics are usually the surprising part of the story.",
                priority="high",
                expected_evidence="Pricing pages, filings, or official statistics with numbers.",
            ),
            ResearchQuestion(
                question_id="q3",
                question=f"What is a concrete real-world example of {topic}?",
                reason="One grounded example makes the abstract mechanism tangible.",
                priority="medium",
                expected_evidence="Reputable journalism or case studies naming specific actors.",
            ),
            ResearchQuestion(
                question_id="q4",
                question=f"What are the trade-offs or downsides of {topic}?",
                reason="A balanced payoff needs the catch, not just the upside.",
                priority="low",
                expected_evidence="Analyst commentary or studies documenting limitations.",
            ),
        ]
        queries = [
            SearchQuery(
                query=f"{topic} how it works mechanism",
                question_ids=["q1"],
                purpose="Find primary explanations of the underlying mechanism.",
            ),
            SearchQuery(
                query=f"{topic} pricing costs statistics",
                question_ids=["q2"],
                purpose="Locate concrete numbers on costs and who bears them.",
            ),
            SearchQuery(
                query=f"{topic} case study example",
                question_ids=["q3"],
                purpose="Find a named, verifiable real-world example.",
            ),
            SearchQuery(
                query=f"{topic} trade-offs criticism limitations",
                question_ids=["q4"],
                purpose="Surface documented downsides for a balanced ending.",
            ),
            SearchQuery(
                query=f"{topic} official report data",
                question_ids=["q1", "q2"],
                purpose="Cross-check mechanism and numbers against primary sources.",
            ),
        ]
        preferences = SourcePreferences(
            preferred_categories=[
                "official statistics and filings",
                "primary documentation",
                "reputable journalism",
            ],
            avoid_or_caution=["content marketing", "forums and Q&A sites", "SEO listicles"],
            prefer_primary_sources=True,
        )
        directions = [
            StoryDirection(
                angle="The hidden mechanism",
                description=f"Open with the surprising surface of {topic}, then reveal the mechanism underneath.",
                questions_to_explore=["q1", "q3"],
            ),
            StoryDirection(
                angle="Follow the money",
                description="Frame the story around who pays and who benefits, then land the trade-off.",
                questions_to_explore=["q2", "q4"],
            ),
        ]
        return ResearchPlan(
            topic=topic,
            core_question=f"What actually drives {topic}?",
            research_questions=questions,
            search_queries=queries,
            source_preferences=preferences,
            story_directions=directions,
            target_audience="Curious general audience watching YouTube Shorts",
            target_seconds=target_seconds,
            created_at=datetime.now(timezone.utc),
        )