"""Codebase analyzer - OSS Stub. Full implementation in amprealize-enterprise."""

try:
    from amprealize_enterprise.research.codebase_analyzer import (
        CodebaseAnalyzer,
        CodebaseSnapshot,
        get_codebase_context,
        TOKEN_BUDGETS,
    )
except ImportError:
    CodebaseAnalyzer = None  # type: ignore[assignment,misc]
    CodebaseSnapshot = None  # type: ignore[assignment,misc]
    get_codebase_context = None  # type: ignore[assignment]
    TOKEN_BUDGETS = {}  # type: ignore[assignment]
