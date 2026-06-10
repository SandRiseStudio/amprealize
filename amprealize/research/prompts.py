"""Research prompt templates."""

from __future__ import annotations


# --- General research prompts ---

RESEARCH_SYSTEM_PROMPT = (
    "You are a research analyst. Analyze the provided sources and extract key findings."
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You are a research synthesizer. Combine findings into a coherent narrative."
)

SECTION_PROMPT = (
    "Write a detailed section on the given topic using the provided source material."
)

CONCLUSION_PROMPT = (
    "Write a conclusion summarizing the key findings and recommendations."
)

FIGURE_CAPTION_PROMPT = (
    "Generate a descriptive caption for the given figure."
)

TABLE_CAPTION_PROMPT = (
    "Generate a descriptive caption for the given table."
)


# --- Comprehension / evaluation / recommendation prompts ---
#
# Dynamic sections use replace("__TOKEN__", value) in ResearchService so
# playbook/codebase text never passes through str.format (avoids "{" in
# loaded docs breaking templates and fixes silent kwargs when placeholders
# were missing).

COMPREHENSION_SYSTEM_PROMPT = """You are a research comprehension assistant.

__AGENT_PLAYBOOK__

## Output contract (critical)
Respond with **one JSON object only** — no markdown fences, no commentary before or after.
Use **snake_case** keys exactly as listed. For news articles, interviews, and blog posts,
map narrative claims into the same schema (e.g. core_idea = main thesis of the piece).

Required keys:
- "core_idea" (string, 2–5 sentences on the main thesis)
- "problem_addressed" (string)
- "proposed_solution" (string; solutions, predictions, or arguments offered)
- "key_contributions" (array of strings, ≥2 items when the text supports it)
- "technical_approach" (string; may describe product architecture, research method, or reporting angle)
- "algorithms_methods" (array of strings; use [] if none named)
- "claimed_results" (array of objects, each with "metric", "improvement", "conditions" strings; use [] if none)
- "benchmarks_used" (array of strings)
- "limitations_acknowledged" (array of strings; caveats from the text or [])
- "novelty_score" (number 1–10)
- "novelty_rationale" (string, one sentence tying the score to the text)
- "related_work_summary" (string; competitors, prior art, or context named in the material)
- "comprehension_confidence" (number 0–1)
- "key_terms" (array of strings, important entities or technical terms)

If a field has no support in the source, use a short honest phrase (e.g. "Not stated in the source") rather than leaving strings empty when the article clearly discusses that area."""

COMPREHENSION_USER_PROMPT = (
    "The material to analyze is below under '## Material'. Output only the JSON object.\n"
)

EVALUATION_SYSTEM_PROMPT = """You are a research evaluator for an AI-engineering product team.

__AGENT_PLAYBOOK__

## Platform / codebase snapshot (grounding only)
Use this to judge fit and overlap with what we already ship. Do not treat it as the article under review.

__CODEBASE_CONTEXT__

## Output contract
Respond with **one JSON object only** (no markdown fences). Use snake_case keys matching the
EvaluatePaper API / service contract (scores 1–10, rationale strings, honest_assessment string,
arrays for concerns, risks, potential_benefits, conflicts_with_existing, competitive_landscape, etc.).

## honest_assessment (critical)
Write 2–3 sentences about **this specific comprehension summary** (the external article or paper):
what it actually argues, whether it is incremental vs breakthrough for *that* topic, and how it
relates to our product **only where the comprehension ties them**. Do **not** substitute a generic
rant about our stack when the comprehension is about unrelated subject matter."""

EVALUATION_USER_PROMPT = (
    "Evaluate using the user message blocks (comprehension JSON, architecture excerpt, "
    "behaviors excerpt, PRD excerpt). Output only the JSON object.\n"
)

RECOMMENDATION_SYSTEM_PROMPT = """You are a research advisor for an AI-engineering product.

__AGENT_PLAYBOOK__

## Platform / codebase snapshot
__CODEBASE_CONTEXT__

## Output contract
Respond with **one JSON object only** (no markdown fences), snake_case keys per the recommendation
schema (verdict, priority, verdict_rationale, executive_summary, implementation_roadmap, etc.)."""

RECOMMENDATION_USER_PROMPT = (
    "Based on the evaluation results in the user message, produce the recommendation JSON only.\n"
)


# --- Format functions ---

def format_research_prompt(topic: str, sources: list[str] | None = None) -> str:
    """Format a research prompt with topic and optional sources."""
    parts = [RESEARCH_SYSTEM_PROMPT, f"\nTopic: {topic}"]
    if sources:
        parts.append("\nSources:\n" + "\n".join(f"- {s}" for s in sources))
    return "\n".join(parts)


def format_synthesis_prompt(findings: list[str]) -> str:
    """Format a synthesis prompt from a list of findings."""
    return SYNTHESIS_SYSTEM_PROMPT + "\n\nFindings:\n" + "\n".join(
        f"{i+1}. {f}" for i, f in enumerate(findings)
    )


def format_section_prompt(topic: str, material: str = "") -> str:
    """Format a section-writing prompt."""
    return f"{SECTION_PROMPT}\n\nTopic: {topic}\n\nMaterial:\n{material}"


def format_comprehension_prompt(material: str) -> str:
    """User-turn only: material body (system role is ``COMPREHENSION_SYSTEM_PROMPT`` separately)."""
    return f"{COMPREHENSION_USER_PROMPT}\n## Material\n\n{material}"


def format_evaluation_prompt(
    *,
    comprehension_summary: str,
    architecture_context: str,
    behaviors_context: str,
    product_context: str,
) -> str:
    """Build the **user** message for the evaluation phase.

    The system role is assembled separately in ``ResearchService.evaluate_paper``
    from ``EVALUATION_SYSTEM_PROMPT``; this string is only the user turn.
    """
    blocks: list[str] = [EVALUATION_USER_PROMPT.rstrip(), ""]
    blocks.append("## Comprehension summary (JSON)\n```json")
    blocks.append(comprehension_summary.strip())
    blocks.append("```\n")
    if architecture_context.strip():
        blocks.append("## Platform architecture context\n")
        blocks.append(architecture_context.strip())
        blocks.append("")
    if behaviors_context.strip():
        blocks.append("## Behaviors / agent handbook excerpt\n")
        blocks.append(behaviors_context.strip())
        blocks.append("")
    if product_context.strip():
        blocks.append("## Product requirements excerpt\n")
        blocks.append(product_context.strip())
        blocks.append("")
    return "\n".join(blocks).strip()


def _bullet_block(title: str, items: list[str]) -> str:
    if not items:
        return f"## {title}\nNone\n"
    body = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n{body}\n"


def format_recommendation_prompt(
    *,
    paper_title: str,
    core_idea: str,
    relevance_score: float,
    feasibility_score: float,
    novelty_score: float,
    roi_score: float,
    safety_score: float,
    overall_score: float,
    concerns: list[str],
    risks: list[str],
    benefits: list[str],
    conflicts: list[str],
) -> str:
    """Build the **user** message for the recommendation phase.

    The system role is assembled separately in ``ResearchService.recommend``
    from ``RECOMMENDATION_SYSTEM_PROMPT``.
    """
    scores = (
        f"- Relevance: {relevance_score:.1f}/10\n"
        f"- Feasibility: {feasibility_score:.1f}/10\n"
        f"- Novelty: {novelty_score:.1f}/10\n"
        f"- ROI: {roi_score:.1f}/10\n"
        f"- Safety: {safety_score:.1f}/10\n"
        f"- **Overall: {overall_score:.2f}/10**"
    )
    parts: list[str] = [
        RECOMMENDATION_USER_PROMPT.rstrip(),
        "",
        f"## Paper title\n{paper_title.strip()}",
        "",
        "## Core idea (from comprehension)\n",
        core_idea.strip() or "(not provided)",
        "",
        "## Evaluation scores\n",
        scores,
        "",
        _bullet_block("Concerns", concerns),
        _bullet_block("Risks", risks),
        _bullet_block("Potential benefits", benefits),
        _bullet_block("Conflicts with existing behaviors / systems", conflicts),
    ]
    return "\n".join(parts).strip()
