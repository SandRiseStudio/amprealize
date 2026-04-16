"""Research evaluation pipeline.

Provides codebase analysis, prompt templates, report rendering, and source
ingesters (Markdown, URL, PDF).  All implementations live in OSS.

Note: research_contracts.py remains in the parent package as shared
interface types.
"""

from amprealize.research.prompts import (
    COMPREHENSION_SYSTEM_PROMPT,
    COMPREHENSION_USER_PROMPT,
    EVALUATION_SYSTEM_PROMPT,
    EVALUATION_USER_PROMPT,
    RECOMMENDATION_SYSTEM_PROMPT,
    RECOMMENDATION_USER_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    SECTION_PROMPT,
    CONCLUSION_PROMPT,
    FIGURE_CAPTION_PROMPT,
    TABLE_CAPTION_PROMPT,
    format_comprehension_prompt,
    format_evaluation_prompt,
    format_recommendation_prompt,
    format_research_prompt,
    format_synthesis_prompt,
    format_section_prompt,
)
from amprealize.research.codebase_analyzer import (
    CodebaseAnalyzer,
    CodebaseSnapshot,
    get_codebase_context,
    TOKEN_BUDGETS,
)
from amprealize.research.report import render_report

__all__ = [
    # Comprehension / evaluation / recommendation prompts
    "COMPREHENSION_SYSTEM_PROMPT",
    "COMPREHENSION_USER_PROMPT",
    "EVALUATION_SYSTEM_PROMPT",
    "EVALUATION_USER_PROMPT",
    "RECOMMENDATION_SYSTEM_PROMPT",
    "RECOMMENDATION_USER_PROMPT",
    # General research prompts
    "RESEARCH_SYSTEM_PROMPT",
    "SYNTHESIS_SYSTEM_PROMPT",
    "SECTION_PROMPT",
    "CONCLUSION_PROMPT",
    "FIGURE_CAPTION_PROMPT",
    "TABLE_CAPTION_PROMPT",
    # Format helpers
    "format_comprehension_prompt",
    "format_evaluation_prompt",
    "format_recommendation_prompt",
    "format_research_prompt",
    "format_synthesis_prompt",
    "format_section_prompt",
    # Codebase analysis
    "CodebaseAnalyzer",
    "CodebaseSnapshot",
    "get_codebase_context",
    "TOKEN_BUDGETS",
    # Report rendering
    "render_report",
]
