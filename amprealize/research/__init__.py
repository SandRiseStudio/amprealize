"""Research evaluation pipeline — OSS Stub.

The full implementation has moved to amprealize-enterprise.
Install amprealize-enterprise[research] for PDF/URL ingestion, codebase
analysis, and the research evaluation pipeline.

Note: research_contracts.py remains in OSS as shared interface types.
"""

_INSTALL_MSG = (
    "Research pipeline requires amprealize-enterprise. "
    "Install with: pip install amprealize-enterprise[research]"
)

try:
    from amprealize_enterprise.research.prompts import (
        COMPREHENSION_SYSTEM_PROMPT,
        COMPREHENSION_USER_PROMPT,
        EVALUATION_SYSTEM_PROMPT,
        EVALUATION_USER_PROMPT,
        RECOMMENDATION_SYSTEM_PROMPT,
        RECOMMENDATION_USER_PROMPT,
        format_comprehension_prompt,
        format_evaluation_prompt,
        format_recommendation_prompt,
    )
    from amprealize_enterprise.research.codebase_analyzer import (
        CodebaseAnalyzer,
        CodebaseSnapshot,
        get_codebase_context,
        TOKEN_BUDGETS,
    )
    _ENTERPRISE_AVAILABLE = True
except ImportError:
    _ENTERPRISE_AVAILABLE = False
    COMPREHENSION_SYSTEM_PROMPT = ""
    COMPREHENSION_USER_PROMPT = ""
    EVALUATION_SYSTEM_PROMPT = ""
    EVALUATION_USER_PROMPT = ""
    RECOMMENDATION_SYSTEM_PROMPT = ""
    RECOMMENDATION_USER_PROMPT = ""
    format_comprehension_prompt = None  # type: ignore[assignment]
    format_evaluation_prompt = None  # type: ignore[assignment]
    format_recommendation_prompt = None  # type: ignore[assignment]
    CodebaseAnalyzer = None  # type: ignore[assignment,misc]
    CodebaseSnapshot = None  # type: ignore[assignment,misc]
    get_codebase_context = None  # type: ignore[assignment]
    TOKEN_BUDGETS = {}  # type: ignore[assignment]

__all__ = [
    "COMPREHENSION_SYSTEM_PROMPT",
    "COMPREHENSION_USER_PROMPT",
    "EVALUATION_SYSTEM_PROMPT",
    "EVALUATION_USER_PROMPT",
    "RECOMMENDATION_SYSTEM_PROMPT",
    "RECOMMENDATION_USER_PROMPT",
    "format_comprehension_prompt",
    "format_evaluation_prompt",
    "format_recommendation_prompt",
    "CodebaseAnalyzer",
    "CodebaseSnapshot",
    "get_codebase_context",
    "TOKEN_BUDGETS",
]
