"""Project-scoped settings REST routes for OSS (and enterprise fallback).

Persists to ``auth.projects.settings`` JSONB via :class:`OSSProjectService`.
Org-level settings remain enterprise-only.

Following ``behavior_lock_down_security_surface`` (Student): owner-only access.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

_GITHUB_HTTPS_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)


def parse_github_repository_url(url: str) -> Optional[Tuple[str, str]]:
    """Return ``(owner, repo_name)`` if *url* looks like a GitHub repo URL."""
    u = (url or "").strip()
    if not u:
        return None
    m = _GITHUB_HTTPS_RE.match(u) or _GITHUB_SSH_RE.match(u)
    if not m:
        return None
    owner = m.group("owner")
    repo = m.group("repo").removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def _github_api_headers(token: Optional[str]) -> Dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fetch_repo_json(owner: str, repo: str, token: Optional[str]) -> Optional[Dict[str, Any]]:
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=_github_api_headers(token),
            timeout=30.0,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        logger.warning("GitHub repo lookup failed for %s/%s: %s", owner, repo, exc)
    return None


def _fetch_branches_page(
    owner: str,
    repo: str,
    token: Optional[str],
    page: int,
    per_page: int,
) -> List[Dict[str, Any]]:
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/branches",
            headers=_github_api_headers(token),
            params={"page": str(page), "per_page": str(per_page)},
            timeout=30.0,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("GitHub branches list failed for %s/%s: %s", owner, repo, exc)
        return []


def _resolve_project_github_token(project_id: str) -> Optional[str]:
    """Return decrypted PAT for project scope, if configured."""
    try:
        from amprealize.auth.github_credential_repository import (
            CredentialScopeType,
            GitHubCredentialRepository,
        )
        from amprealize.storage.postgres_pool import PostgresPool

        pool = PostgresPool()
        repo = GitHubCredentialRepository(pool)
        cred = repo.get_for_scope(
            scope_type=CredentialScopeType.PROJECT,
            scope_id=project_id,
            decrypt=True,
        )
        if cred and cred.decrypted_token:
            return cred.decrypted_token
    except Exception as exc:
        logger.debug("No GitHub token for project %s: %s", project_id, exc)
    return None


class RepositoryValidateBody(BaseModel):
    repository_url: str = Field(..., min_length=1)


class RepositoryPutBody(BaseModel):
    repository_url: str = Field(..., min_length=1)
    default_branch: str = Field(default="main", min_length=1, max_length=255)


def create_project_settings_routes(
    *,
    org_service: Any,
    get_user_id: Callable[[Request], str],
    tags: Optional[List[str]] = None,
) -> APIRouter:
    """REST routes under ``/v1/projects/{project_id}/settings`` for OSS."""

    router = APIRouter(prefix="/v1/projects", tags=tags or ["settings"])

    async def _require_owner_project(user_id: str, project_id: str):
        project = await run_in_threadpool(org_service.get_project, project_id)
        if project is None or project.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return project

    @router.get("/{project_id}/settings")
    async def get_project_settings(request: Request, project_id: str) -> Dict[str, Any]:
        user_id = get_user_id(request)
        project = await _require_owner_project(user_id, project_id)
        return dict(project.settings or {})

    @router.patch("/{project_id}/settings")
    async def patch_project_settings(
        request: Request,
        project_id: str,
    ) -> Dict[str, Any]:
        user_id = get_user_id(request)
        await _require_owner_project(user_id, project_id)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON object body required",
            )
        updated = await run_in_threadpool(
            org_service.patch_project_settings,
            owner_id=user_id,
            project_id=project_id,
            patch=body,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return updated

    @router.put("/{project_id}/settings/repository")
    async def put_project_repository(
        request: Request,
        project_id: str,
        body: RepositoryPutBody,
    ) -> Dict[str, Any]:
        user_id = get_user_id(request)
        await _require_owner_project(user_id, project_id)
        patch = {
            "github_repo_url": body.repository_url.strip(),
            "github_default_branch": body.default_branch.strip(),
        }
        updated = await run_in_threadpool(
            org_service.patch_project_settings,
            owner_id=user_id,
            project_id=project_id,
            patch=patch,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return updated

    @router.post("/{project_id}/settings/repository/validate")
    async def validate_repository(
        request: Request,
        project_id: str,
        body: RepositoryValidateBody,
    ) -> Dict[str, Any]:
        user_id = get_user_id(request)
        await _require_owner_project(user_id, project_id)
        parsed = parse_github_repository_url(body.repository_url)
        if not parsed:
            return {
                "valid": False,
                "error": "Not a recognized github.com repository URL",
            }
        owner, repo_name = parsed
        token = _resolve_project_github_token(project_id)
        info = _fetch_repo_json(owner, repo_name, token)
        if not info:
            hint = (
                "Repository not found or not accessible. "
                "For private repos, add a project GitHub credential (BYOK)."
            )
            return {"valid": False, "owner": owner, "repo": repo_name, "error": hint}
        vis = info.get("visibility")
        visibility: Optional[str] = vis if vis in ("public", "private") else None
        return {
            "valid": True,
            "owner": owner,
            "repo": repo_name,
            "default_branch": info.get("default_branch") or "main",
            "visibility": visibility,
            "description": info.get("description"),
        }

    @router.get("/{project_id}/settings/repository/branches")
    async def list_repository_branches(
        request: Request,
        project_id: str,
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=30, ge=1, le=100),
    ) -> Dict[str, Any]:
        user_id = get_user_id(request)
        project = await _require_owner_project(user_id, project_id)
        settings = project.settings or {}
        raw_url = settings.get("github_repo_url")
        if not raw_url or not isinstance(raw_url, str):
            return {"branches": [], "total_count": 0, "page": page, "per_page": per_page}
        parsed = parse_github_repository_url(raw_url.strip())
        if not parsed:
            return {"branches": [], "total_count": 0, "page": page, "per_page": per_page}
        owner, repo_name = parsed
        token = _resolve_project_github_token(project_id)
        rows = await run_in_threadpool(
            _fetch_branches_page,
            owner,
            repo_name,
            token,
            page,
            per_page,
        )
        branches = [{"name": b["name"], "sha": (b.get("commit") or {}).get("sha")} for b in rows if "name" in b]
        return {
            "branches": branches,
            "total_count": len(branches),
            "page": page,
            "per_page": per_page,
        }

    return router
