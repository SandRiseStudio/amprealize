"""MCP tool handlers for ResearchService operations.

Provides handlers for research.* tools:
- research.evaluate: Run full 4-phase evaluation pipeline on a paper
- research.get: Get evaluation details for a specific paper
- research.search: Search evaluated papers by query/filters
- research.list: List all evaluated papers with summaries

Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple


class ResearchToolValidationError(ValueError):
    """Raised when a research MCP tool has invalid runtime arguments."""


def _require(params: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not params.get(field)]
    if not missing:
        return
    label = "parameter" if len(missing) == 1 else "parameters"
    raise ResearchToolValidationError(f"Missing required {label}: {', '.join(missing)}")


def _parse_enum(enum_cls: type[Enum], value: Any, field_name: str) -> Optional[Enum]:
    if value in (None, ""):
        return None

    raw = str(value)
    candidates = (raw, raw.lower(), raw.upper())
    for candidate in candidates:
        try:
            return enum_cls(candidate)
        except ValueError:
            continue

    valid = ", ".join(str(item.value) for item in enum_cls)
    raise ResearchToolValidationError(f"Invalid {field_name}: {raw}. Must be one of: {valid}")


def _parse_int(params: Dict[str, Any], field_name: str, default: int, *, minimum: int) -> int:
    value = params.get(field_name, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchToolValidationError(f"Invalid {field_name}: must be an integer") from exc
    if parsed < minimum:
        raise ResearchToolValidationError(f"Invalid {field_name}: must be >= {minimum}")
    return parsed


def _extract_identity(params: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract owner_id, org_id, project_id from session-injected params."""
    session = params.get("_session", {})
    return (
        session.get("user_id") or params.get("user_id"),
        session.get("org_id") or params.get("org_id"),
        session.get("project_id") or params.get("project_id"),
    )


# ==============================================================================
# Handler Functions
# ==============================================================================


async def handle_evaluate(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the full 4-phase evaluation pipeline on a paper.

    Required params:
        - source: URL, file path, or arXiv ID of the paper

    Optional params:
        - source_type: url | arxiv | markdown | pdf | docx (auto-detected)
        - body_markdown: Pasted article (markdown or plain text); when set, ingest skips fetching ``source`` HTML (``source`` must still be the canonical http(s) URL)
        - context_documents: Additional context document paths
        - llm_model: LLM model to use for analysis
        - save_to_db: Whether to persist results (default: true)
    """
    from amprealize.research_contracts import EvaluatePaperRequest, SourceType

    _require(params, "source")
    source = params["source"]
    source_type = _parse_enum(SourceType, params.get("source_type"), "source_type")

    body_markdown = params.get("body_markdown")
    if isinstance(body_markdown, str):
        body_markdown = body_markdown.strip() or None
    else:
        body_markdown = None

    request = EvaluatePaperRequest(
        source=source,
        source_type=source_type,
        body_markdown=body_markdown,
        context_documents=params.get("context_documents", []),
        llm_model=params.get("llm_model"),
        save_to_db=params.get("save_to_db", True),
    )

    try:
        owner_id, org_id, project_id = _extract_identity(params)

        # ResearchService.evaluate() is synchronous — run in thread pool
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: service.evaluate(
                request, owner_id=owner_id, org_id=org_id, project_id=project_id
            ),
        )

        return {
            "success": True,
            "paper_id": response.paper_id,
            "paper_title": response.paper_title,
            "verdict": response.recommendation.verdict.value if response.recommendation else None,
            "overall_score": response.evaluation.overall_score if response.evaluation else None,
            "evaluation_duration_seconds": response.evaluation_duration_seconds,
            "total_tokens_used": response.total_tokens_used,
            "markdown_report": response.markdown_report,
            "message": f"Evaluation complete: {response.paper_title}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def handle_get(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get full evaluation details for a specific paper by ID.

    Required params:
        - paper_id: Unique identifier of the paper
    """
    _require(params, "paper_id")
    paper_id = params["paper_id"]

    try:
        owner_id, org_id, _ = _extract_identity(params)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: service.get_paper(paper_id, owner_id=owner_id, org_id=org_id),
        )

        if response is None:
            return {"success": False, "error": f"Paper not found: {paper_id}"}

        return {
            "success": True,
            "paper_id": response.paper_id,
            "paper_title": response.paper_title,
            "verdict": response.recommendation.verdict.value if response.recommendation else None,
            "overall_score": response.evaluation.overall_score if response.evaluation else None,
            "evaluation_duration_seconds": response.evaluation_duration_seconds,
            "total_tokens_used": response.total_tokens_used,
            "markdown_report": response.markdown_report,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_search(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Search evaluated papers by query text, verdict, score range, or source type.

    All params optional:
        - query: Free-text search
        - verdict: ADOPT | ADAPT | DEFER | REJECT
        - min_score / max_score: Score range filter
        - source_type: url | arxiv | markdown | pdf | docx
        - limit: Max results (default 50)
        - offset: Pagination offset (default 0)
    """
    from amprealize.research_contracts import SearchPapersRequest, SourceType, Verdict

    verdict = _parse_enum(Verdict, params.get("verdict"), "verdict")
    source_type = _parse_enum(SourceType, params.get("source_type"), "source_type")
    limit = _parse_int(params, "limit", 50, minimum=1)
    offset = _parse_int(params, "offset", 0, minimum=0)

    request = SearchPapersRequest(
        query=params.get("query"),
        verdict=verdict,
        min_score=params.get("min_score"),
        max_score=params.get("max_score"),
        source_type=source_type,
        limit=limit,
        offset=offset,
    )

    try:
        owner_id, org_id, _ = _extract_identity(params)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: service.search_papers(request, owner_id=owner_id, org_id=org_id),
        )

        papers = []
        for p in response.papers:
            papers.append({
                "paper_id": p.paper_id,
                "title": p.title,
                "source_type": p.source_type,
                "overall_score": p.overall_score,
                "verdict": p.verdict,
                "core_idea": p.core_idea,
                "created_at": p.created_at,
            })

        return {
            "success": True,
            "papers": papers,
            "total_count": response.total_count,
            "has_more": response.has_more,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_list(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """List all evaluated papers with summary information.

    Optional params:
        - limit: Max results (default 50)
        - offset: Pagination offset (default 0)
        - verdict: Filter by verdict
    """
    from amprealize.research_contracts import SearchPapersRequest, Verdict

    verdict = _parse_enum(Verdict, params.get("verdict"), "verdict")
    limit = _parse_int(params, "limit", 50, minimum=1)
    offset = _parse_int(params, "offset", 0, minimum=0)

    request = SearchPapersRequest(
        verdict=verdict,
        limit=limit,
        offset=offset,
    )

    try:
        owner_id, org_id, _ = _extract_identity(params)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: service.search_papers(request, owner_id=owner_id, org_id=org_id),
        )

        papers = []
        for p in response.papers:
            papers.append({
                "paper_id": p.paper_id,
                "title": p.title,
                "source_type": p.source_type,
                "overall_score": p.overall_score,
                "verdict": p.verdict,
                "core_idea": p.core_idea,
                "created_at": p.created_at,
            })

        return {
            "success": True,
            "papers": papers,
            "total_count": response.total_count,
            "has_more": response.has_more,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# Handler Registry
# ==============================================================================

RESEARCH_HANDLERS: Dict[str, Callable] = {
    "research.evaluate": handle_evaluate,
    "research.get": handle_get,
    "research.search": handle_search,
    "research.list": handle_list,
}
