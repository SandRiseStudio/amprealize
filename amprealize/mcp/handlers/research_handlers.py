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
from typing import Any, Callable, Dict, Optional, Tuple


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
        - context_documents: Additional context document paths
        - llm_model: LLM model to use for analysis
        - save_to_db: Whether to persist results (default: true)
    """
    from amprealize.research_contracts import EvaluatePaperRequest, SourceType

    source = params.get("source")
    if not source:
        return {"success": False, "error": "Missing required parameter: source"}

    source_type = None
    if params.get("source_type"):
        try:
            source_type = SourceType(params["source_type"].upper())
        except (ValueError, KeyError):
            pass

    request = EvaluatePaperRequest(
        source=source,
        source_type=source_type,
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
    paper_id = params.get("paper_id")
    if not paper_id:
        return {"success": False, "error": "Missing required parameter: paper_id"}

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

    verdict = None
    if params.get("verdict"):
        try:
            verdict = Verdict(params["verdict"].upper())
        except (ValueError, KeyError):
            pass

    source_type = None
    if params.get("source_type"):
        try:
            source_type = SourceType(params["source_type"].upper())
        except (ValueError, KeyError):
            pass

    request = SearchPapersRequest(
        query=params.get("query"),
        verdict=verdict,
        min_score=params.get("min_score"),
        max_score=params.get("max_score"),
        source_type=source_type,
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
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

    verdict = None
    if params.get("verdict"):
        try:
            verdict = Verdict(params["verdict"].upper())
        except (ValueError, KeyError):
            pass

    request = SearchPapersRequest(
        verdict=verdict,
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
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
