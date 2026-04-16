"""REST API routes for Wiki viewer (read-only).

Provides endpoints for browsing wiki pages across three domains
(research, infra, ai-learning), searching content, and viewing
learning paths. All data is read from the filesystem via WikiService.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class WikiPageNode(BaseModel):
    path: str
    title: str
    page_type: str
    difficulty: Optional[str] = None
    folder: str


class WikiTreeResponse(BaseModel):
    domain: str
    pages: List[WikiPageNode]
    total: int


class WikiPageDetail(BaseModel):
    domain: str
    path: str
    title: str
    page_type: str
    body: str
    frontmatter: Dict[str, Any]


class WikiStatusResponse(BaseModel):
    domain: str
    total_pages: int
    pages_by_type: Dict[str, int]
    last_updated: Optional[str] = None


class WikiSearchResult(BaseModel):
    domain: str
    page_path: str
    title: str
    page_type: str
    score: float
    snippet: str


class WikiSearchResponse(BaseModel):
    query: str
    results: List[WikiSearchResult]
    total: int


class WikiLintIssue(BaseModel):
    rule: str
    severity: str
    page: str
    message: str


class WikiLintResponse(BaseModel):
    domain: str
    total_issues: int
    issues: List[WikiLintIssue]
    issues_by_severity: Dict[str, int]


# ---------------------------------------------------------------------------
# Allowed domains (prevent path traversal)
# ---------------------------------------------------------------------------

ALLOWED_DOMAINS = {"research", "infra", "ai-learning", "platform"}


def _validate_domain(domain: str) -> str:
    if domain not in ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown wiki domain: {domain}",
        )
    return domain


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------

def create_wiki_routes(repo_root: Optional[str] = None) -> APIRouter:
    """Create read-only FastAPI router for wiki browsing.

    Args:
        repo_root: Repository root path. Defaults to AMPREALIZE_REPO_ROOT
                   env var or current working directory.

    Returns:
        APIRouter with GET endpoints for wiki pages.
    """
    from amprealize.wiki_service import WikiService

    resolved_root = repo_root or os.environ.get("AMPREALIZE_REPO_ROOT") or os.getcwd()
    service = WikiService(repo_root=resolved_root)

    router = APIRouter(tags=["wiki"])

    # ----- Page tree -------------------------------------------------------

    @router.get(
        "/v1/wiki/{domain}/pages",
        response_model=WikiTreeResponse,
        summary="List wiki pages as a tree",
    )
    async def list_pages(domain: str) -> WikiTreeResponse:
        domain = _validate_domain(domain)
        result = service.status(domain)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail="Failed to read wiki")

        # Walk directory to build page list with metadata
        wiki_dir = service._wiki_dir(domain)
        pages: List[WikiPageNode] = []

        for md_file in sorted(wiki_dir.rglob("*.md")):
            rel = str(md_file.relative_to(wiki_dir))
            if rel in ("index.md", "log.md", "overview.md", "SCHEMA.md"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            from amprealize.wiki_service import _parse_frontmatter
            fm, _ = _parse_frontmatter(text)

            folder = str(md_file.parent.relative_to(wiki_dir))
            if folder == ".":
                folder = ""

            pages.append(WikiPageNode(
                path=rel,
                title=fm.get("title", md_file.stem.replace("-", " ").title()),
                page_type=fm.get("type", "unknown"),
                difficulty=fm.get("difficulty"),
                folder=folder,
            ))

        return WikiTreeResponse(domain=domain, pages=pages, total=len(pages))

    # ----- Single page -----------------------------------------------------

    @router.get(
        "/v1/wiki/{domain}/page",
        response_model=WikiPageDetail,
        summary="Get a single wiki page",
    )
    async def get_page(
        domain: str,
        path: str = Query(..., description="Page path relative to wiki domain root"),
    ) -> WikiPageDetail:
        domain = _validate_domain(domain)
        result = service.read_page(domain, path)
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.get("error", "Page not found"),
            )

        return WikiPageDetail(
            domain=domain,
            path=path,
            title=result["frontmatter"].get("title", ""),
            page_type=result["frontmatter"].get("type", "unknown"),
            body=result["body"],
            frontmatter=result["frontmatter"],
        )

    # ----- Status ----------------------------------------------------------

    @router.get(
        "/v1/wiki/{domain}/status",
        response_model=WikiStatusResponse,
        summary="Wiki domain status (page counts)",
    )
    async def get_status(domain: str) -> WikiStatusResponse:
        domain = _validate_domain(domain)
        result = service.status(domain)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail="Failed to read wiki status")

        return WikiStatusResponse(
            domain=domain,
            total_pages=result["total_pages"],
            pages_by_type=result["pages_by_type"],
            last_updated=result.get("last_updated"),
        )

    # ----- Search ----------------------------------------------------------

    @router.get(
        "/v1/wiki/search",
        response_model=WikiSearchResponse,
        summary="Search across wiki domains",
    )
    async def search_wiki(
        q: str = Query(..., min_length=1, description="Search query"),
        domain: Optional[str] = Query(None, description="Limit to domain"),
        max_results: int = Query(20, ge=1, le=50),
    ) -> WikiSearchResponse:
        domains = [domain] if domain and domain in ALLOWED_DOMAINS else list(ALLOWED_DOMAINS)
        all_results: List[WikiSearchResult] = []

        for d in domains:
            result = service.query(d, q, max_results=max_results)
            if result.get("success"):
                for r in result.get("results", []):
                    all_results.append(WikiSearchResult(
                        domain=d,
                        page_path=r["page_path"],
                        title=r["title"],
                        page_type=r["type"],
                        score=r["score"],
                        snippet=r["snippet"][:200],
                    ))

        # Sort by score descending, limit
        all_results.sort(key=lambda x: x.score, reverse=True)
        all_results = all_results[:max_results]

        return WikiSearchResponse(query=q, results=all_results, total=len(all_results))

    # ----- Lint ------------------------------------------------------------

    @router.get(
        "/v1/wiki/{domain}/lint",
        response_model=WikiLintResponse,
        summary="Run lint checks on a wiki domain",
    )
    async def lint_wiki(domain: str) -> WikiLintResponse:
        domain = _validate_domain(domain)
        result = service.lint(domain)
        if not result.get("success"):
            raise HTTPException(status_code=500, detail="Lint failed")

        return WikiLintResponse(
            domain=domain,
            total_issues=result["total_issues"],
            issues=[WikiLintIssue(**i) for i in result["issues"]],
            issues_by_severity=result["issues_by_severity"],
        )

    return router
