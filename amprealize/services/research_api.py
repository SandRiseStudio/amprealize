"""REST API routes for AI Research data (read-only).

Provides endpoints for listing/searching evaluated papers,
retrieving paper details, and fetching markdown reports.
All queries are RLS-filtered by the authenticated user's identity.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CompetitiveLandscapeItemModel(BaseModel):
    name: str
    category: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    maturity: Optional[str] = None
    overlap_description: Optional[str] = None
    differentiators: List[str] = []


class StructuredConModel(BaseModel):
    description: str
    severity: Optional[str] = None
    likelihood: Optional[str] = None
    mitigation: Optional[str] = None
    category: Optional[str] = None


class ValuePropositionModel(BaseModel):
    effectiveness_summary: Optional[str] = None
    key_benefits: List[str] = []
    measurable_outcomes: List[str] = []
    value_to_amprealize: Optional[str] = None


class AdoptionStrategyModel(BaseModel):
    approach: Optional[str] = None
    rationale: Optional[str] = None
    direct_use_candidates: List[str] = []
    concepts_to_extract: List[str] = []
    integration_points: List[str] = []
    estimated_time_saved: Optional[str] = None


class PaperSummary(BaseModel):
    id: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    verdict: Optional[str] = None
    overall_score: Optional[float] = None
    core_idea: Optional[str] = None
    created_at: Optional[str] = None


class PaperListResponse(BaseModel):
    papers: List[PaperSummary]
    total_count: int
    has_more: bool


class PaperDetailResponse(BaseModel):
    paper: Dict[str, Any]


class ReportResponse(BaseModel):
    paper_id: str
    report_markdown: Optional[str] = None
    executive_summary: Optional[str] = None
    honest_assessment: Optional[str] = None
    competitive_landscape: List[CompetitiveLandscapeItemModel] = []
    value_proposition: Optional[ValuePropositionModel] = None
    structured_cons: List[StructuredConModel] = []
    adoption_strategy: Optional[AdoptionStrategyModel] = None


class ReportSummary(BaseModel):
    paper_id: str
    title: Optional[str] = None
    verdict: Optional[str] = None
    overall_score: Optional[float] = None
    word_count: Optional[int] = None
    created_at: Optional[str] = None


class ReportListResponse(BaseModel):
    reports: List[ReportSummary]
    total: int


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------

def create_research_routes(
    storage: Any,
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """Create read-only FastAPI router for research data.

    Args:
        storage: ResearchStoragePostgres instance.
        tags: Optional OpenAPI tags.

    Returns:
        APIRouter with GET endpoints for papers and reports.
    """
    resolved_tags: List[Union[str, Enum]] = list(tags) if tags else ["research"]
    router = APIRouter(tags=resolved_tags)

    def _get_user_id(request: Request) -> str:
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return str(user_id)

    def _get_org_id(request: Request) -> Optional[str]:
        return getattr(request.state, "org_id", None)

    # ----- Papers ----------------------------------------------------------

    @router.get(
        "/v1/research/papers",
        response_model=PaperListResponse,
        summary="Search/list research papers",
        description="List evaluated papers with optional filtering. Results are RLS-filtered.",
    )
    async def list_papers(
        request: Request,
        query: Optional[str] = Query(None, description="Free-text search in title/core idea"),
        verdict: Optional[str] = Query(None, description="Filter by verdict (e.g. ADOPT, HOLD)"),
        min_score: Optional[float] = Query(None, ge=0, le=100, description="Minimum overall score"),
        max_score: Optional[float] = Query(None, ge=0, le=100, description="Maximum overall score"),
        source_type: Optional[str] = Query(None, description="Filter by source type"),
        limit: int = Query(20, ge=1, le=100, description="Max papers to return"),
        offset: int = Query(0, ge=0, description="Papers to skip"),
    ) -> PaperListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

        try:
            result = storage.search_papers(
                query=query,
                verdict=verdict,
                min_score=min_score,
                max_score=max_score,
                source_type=source_type,
                limit=limit,
                offset=offset,
                owner_id=user_id,
                org_id=org_id,
            )
            papers = [PaperSummary(**p) for p in result.get("papers", [])]
            return PaperListResponse(
                papers=papers,
                total_count=result.get("total_count", len(papers)),
                has_more=result.get("has_more", False),
            )
        except Exception as e:
            logger.exception("Research paper search failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Research service unavailable",
            ) from e

    @router.get(
        "/v1/research/papers/{paper_id}",
        response_model=PaperDetailResponse,
        summary="Get paper details",
        description="Retrieve full evaluation data for a paper including comprehension, evaluation, and recommendation.",
    )
    async def get_paper(
        request: Request,
        paper_id: str,
    ) -> PaperDetailResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

        try:
            paper = storage.get_paper(paper_id, owner_id=user_id, org_id=org_id)
        except Exception as e:
            logger.exception("Research paper get failed", extra={"paper_id": paper_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Research service unavailable",
            ) from e

        if paper is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Paper {paper_id} not found or not accessible",
            )
        return PaperDetailResponse(paper=paper)

    # ----- Reports ---------------------------------------------------------

    @router.get(
        "/v1/research/papers/{paper_id}/report",
        response_model=ReportResponse,
        summary="Get paper report",
        description="Retrieve the markdown report generated for a paper evaluation.",
    )
    async def get_report(
        request: Request,
        paper_id: str,
    ) -> ReportResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

        try:
            markdown = storage.get_report(paper_id, owner_id=user_id, org_id=org_id)
        except Exception as e:
            logger.exception("Research report get failed", extra={"paper_id": paper_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Research service unavailable",
            ) from e

        if markdown is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Report for paper {paper_id} not found or not accessible",
            )
        return ReportResponse(paper_id=paper_id, report_markdown=markdown)

    @router.get(
        "/v1/research/reports",
        response_model=ReportListResponse,
        summary="List research reports",
        description="List available reports with paper metadata. Results are RLS-filtered.",
    )
    async def list_reports(
        request: Request,
        limit: int = Query(20, ge=1, le=100, description="Max reports to return"),
    ) -> ReportListResponse:
        user_id = _get_user_id(request)
        org_id = _get_org_id(request)

        try:
            reports = storage.list_reports(limit=limit, owner_id=user_id, org_id=org_id)
            items = [ReportSummary(**r) for r in reports]
            return ReportListResponse(reports=items, total=len(items))
        except Exception as e:
            logger.exception("Research report list failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Research service unavailable",
            ) from e

    return router
