from __future__ import annotations

from .schemas import Hook, ResearchBundle, Script, Source


RESEARCH_SYSTEM = (
    "You are a factual researcher for short-form explainer videos. "
    "You verify claims with Google Search, prefer authoritative sources, and write plainly. "
    "Never invent facts, statistics, or URLs."
)

RESEARCH_EXTRACT_SYSTEM = (
    "You convert research notes into a structured fact sheet. "
    "Only use the supplied source URLs, copied exactly. Never invent a URL."
)

HOOK_MAX_WORDS = 7

HOOK_SYSTEM = (
    "You write opening hooks for vertical explainer videos. "
    f"Hooks are accurate, specific, conversational, and at most {HOOK_MAX_WORDS} words. "
    "Never overpromise or mislead."
)

SCRIPT_SYSTEM = (
    "You are a scriptwriter for short vertical explainers. "
    "You write clear, concrete, conversational narration at a natural speaking pace. "
    "You never add claims that are not supported by the research notes."
)

BREAKDOWN_SYSTEM = (
    "You are a video editor who turns narration into timed visual scenes for a vertical video. "
    "You preserve the script's meaning and order, respect timing, and only cite supplied sources."
)


def research_prompt(topic: str, target_seconds: float) -> str:
    return (
        f"Research this topic for a vertical explainer video:\n{topic}\n\n"
        "Use Google Search to gather verifiable, current facts. Focus on details that are "
        f"surprising, clarifying, or directly useful for a {target_seconds:g}-second video "
        "aimed at a general audience.\n"
        "Write 120-180 words of research notes. Note any uncertainty or conflicting claims."
    )


def research_extract_prompt(topic: str, notes: str, sources: list[Source]) -> str:
    source_lines = "\n".join(f"- {source.url}" for source in sources)
    return (
        f"Topic: {topic}\n\n"
        f"Research notes:\n{notes}\n\n"
        f"Allowed source URLs (copy exactly):\n{source_lines}\n\n"
        "Produce a 100-150 word summary and 4-6 distinct facts. "
        "Each fact needs a short claim and the exact URL it came from."
    )


def hook_prompt(topic: str, research: ResearchBundle) -> str:
    facts = "\n".join(
        f"- {fact.claim} ({fact.source})" for fact in research.facts[:4]
    )
    return (
        f"Topic: {topic}\n\n"
        f"Research summary:\n{research.summary}\n\n"
        f"Key facts:\n{facts}\n\n"
        f"Write one opening hook of at most {HOOK_MAX_WORDS} words that can be spoken in 1-3 seconds. "
        "It must tease the explanation rather than give it away: accurate, compelling, and concise. "
        f"Also write two alternative hooks, each at most {HOOK_MAX_WORDS} words."
    )


def script_prompt(
    topic: str,
    research: ResearchBundle,
    hook: Hook,
    target_seconds: float,
) -> str:
    word_budget = round(target_seconds * 2.4)
    facts = "\n".join(f"- {fact.claim} ({fact.source})" for fact in research.facts)
    return (
        f"Topic: {topic}\n"
        f"Target duration: {target_seconds:g} seconds (~{word_budget} spoken words).\n\n"
        f"Open with this exact hook: \"{hook.text}\"\n\n"
        f"Research summary:\n{research.summary}\n\n"
        f"Facts you may use:\n{facts}\n\n"
        "Write the full narration for the video:\n"
        "- Start with the hook, then explain the core idea in plain language.\n"
        "- Build a logical progression and include one concrete example or comparison.\n"
        "- End with a memorable takeaway.\n"
        f"- Aim for {word_budget} words total (within about 10%).\n"
        "- Do not add facts, numbers, or claims that are not in the research above.\n\n"
        "Also return 3-6 short beats describing the story progression in order."
    )


def breakdown_prompt(
    topic: str,
    research: ResearchBundle,
    hook: Hook,
    script: Script,
    target_seconds: float,
) -> str:
    source_lines = "\n".join(f"- {source.url}" for source in research.sources)
    beats = "\n".join(f"- {beat}" for beat in script.beats)
    low = target_seconds - 2
    high = target_seconds + 2
    return (
        f"Topic: {topic}\n"
        f"Target duration: {target_seconds:g} seconds.\n\n"
        f"Script narration:\n{script.narration}\n\n"
        f"Story beats:\n{beats}\n\n"
        f"Hook (first scene, word for word): \"{hook.text}\"\n\n"
        "Break the narration into 4-8 scenes and assign each a duration:\n"
        "- The first scene is type \"hook\", 1-3 seconds, and uses the hook text exactly.\n"
        "- Every other scene is 2-12 seconds and type explainer, example, payoff, or cta.\n"
        f"- Durations must add up to {target_seconds:g} seconds (between {low:g} and {high:g}).\n"
        "- Keep the narration in script order and do not rewrite the facts.\n"
        "- Each scene gets one visual: AnimatedText (headline plus optional subheadline) "
        "or SimpleDiagram (headline plus 1-6 short items).\n"
        "- Add scene sources only when the scene states a fact, using only these URLs:\n"
        f"{source_lines}"
    )
