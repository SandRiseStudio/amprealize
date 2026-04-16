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

COMPREHENSION_SYSTEM_PROMPT = (
    "You are a research comprehension assistant. Read the provided material "
    "and extract the core claims, methodology, and findings."
)

COMPREHENSION_USER_PROMPT = (
    "Please analyze the following material and provide a structured "
    "comprehension summary covering: main claims, methodology, key findings, "
    "and limitations."
)

EVALUATION_SYSTEM_PROMPT = (
    "You are a research evaluator. Assess the quality, rigor, and relevance "
    "of the provided research material."
)

EVALUATION_USER_PROMPT = (
    "Please evaluate the following research material for: methodological "
    "rigor, reproducibility, novelty, and practical relevance."
)

RECOMMENDATION_SYSTEM_PROMPT = (
    "You are a research advisor. Based on the evaluation, provide a clear "
    "recommendation on whether to adopt, adapt, defer, or reject."
)

RECOMMENDATION_USER_PROMPT = (
    "Based on the evaluation results below, provide a recommendation "
    "(ADOPT / ADAPT / DEFER / REJECT) with supporting rationale."
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
    """Format a comprehension prompt with the material to analyze."""
    return f"{COMPREHENSION_SYSTEM_PROMPT}\n\n{COMPREHENSION_USER_PROMPT}\n\n{material}"


def format_evaluation_prompt(material: str) -> str:
    """Format an evaluation prompt with the material to assess."""
    return f"{EVALUATION_SYSTEM_PROMPT}\n\n{EVALUATION_USER_PROMPT}\n\n{material}"


def format_recommendation_prompt(evaluation: str) -> str:
    """Format a recommendation prompt with evaluation results."""
    return f"{RECOMMENDATION_SYSTEM_PROMPT}\n\n{RECOMMENDATION_USER_PROMPT}\n\n{evaluation}"
