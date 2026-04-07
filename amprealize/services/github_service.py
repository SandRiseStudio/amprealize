"""GitHub service for PR and commit operations.

Provides high-level operations for creating PRs and committing to branches.
Uses project-level GitHub tokens from CredentialStore following `behavior_externalize_configuration`.

Token resolution order (first match wins):
1. Project GitHub App installation token (if configured)
2. Org GitHub App installation token (if configured)
3. Project PAT (BYOK)
4. Org PAT (BYOK)
5. Platform token (GITHUB_TOKEN env var)

Following `behavior_prefer_mcp_tools` - this service is used by github.* MCP handlers.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from urllib.parse import quote

import httpx

from ..storage.postgres_pool import PostgresPool

if TYPE_CHECKING:
    from ..auth.github_credential_repository import (
        GitHubCredentialRepository,
        CredentialScopeType,
    )
    from ..auth.github_app_installation_repository import GitHubAppInstallationRepository
    from ..auth.github_app_service import GitHubAppService


logger = logging.getLogger(__name__)


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass
class FileChange:
    """Represents a file change for commits/PRs."""

    path: str
    content: Optional[str] = None  # None for deletions
    encoding: str = "utf-8"  # "utf-8" or "base64"
    action: str = "update"  # "create", "update", "delete"

    def to_blob_content(self) -> Optional[str]:
        """Get base64-encoded content for GitHub API."""
        if self.content is None:
            return None
        if self.encoding == "base64":
            return self.content
        return base64.b64encode(self.content.encode("utf-8")).decode("ascii")


@dataclass
class CommitResult:
    """Result of a commit operation."""

    success: bool
    commit_sha: Optional[str] = None
    commit_url: Optional[str] = None
    tree_sha: Optional[str] = None
    branch: Optional[str] = None
    branch_created: bool = False
    files_changed: int = 0
    error: Optional[str] = None


@dataclass
class PRResult:
    """Result of a PR creation operation."""

    success: bool
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    head_branch: Optional[str] = None
    commit_sha: Optional[str] = None
    files_changed: int = 0
    error: Optional[str] = None


# ==============================================================================
# Credential Store Integration
# ==============================================================================


@dataclass
class ResolvedGitHubToken:
    """Result of resolving a GitHub token for a project/org/user.

    Contains the token and metadata about its source and capabilities.

    Source values (in resolution order):
    - "user_app": User's linked GitHub App for this project
    - "user_pat": User's linked PAT for this project
    - "project_app": Shared project GitHub App installation
    - "project_pat": Shared project PAT (legacy)
    - "org_app": Organization GitHub App installation
    - "org_pat": Organization PAT (legacy)
    - "platform": Platform-managed token (GITHUB_TOKEN env var)
    """
    token: str
    source: str  # "user_app", "user_pat", "project_app", "org_app", "project_pat", "org_pat", "platform"
    credential_id: Optional[str] = None
    token_type: Optional[str] = None
    github_username: Optional[str] = None
    scopes: Optional[List[str]] = None
    has_required_scopes: bool = True
    scope_warning: Optional[str] = None
    rate_limit_remaining: Optional[int] = None
    # GitHub App specific fields
    installation_id: Optional[int] = None
    app_permissions: Optional[Dict[str, str]] = None
    expires_at: Optional[datetime] = None
    # User-aware resolution fields
    resolved_for_user_id: Optional[str] = None
    link_id: Optional[str] = None  # auth.user_project_github_links.id if user-linked


class GitHubCredentialStore:
    """Manages GitHub tokens at project/org/user level.

    Resolution order (first match wins, if valid):
    1. User's linked GitHub App for this project (if user_id provided)
    2. User's linked PAT for this project (if user_id provided)
    3. Project GitHub App installation token (shared, highest non-user priority)
    4. Org GitHub App installation token
    5. Project PAT (BYOK, shared) - legacy, still supported
    6. Org PAT (BYOK)
    7. Platform token (admin-managed from environment)

    Design decisions:
    - GitHub App installations are SHAREABLE - team members can share one install
    - PATs are PERSONAL - user's token shouldn't be shared with teammates
    - User-project links let each user choose which credential to use
    - If user has linked credential but it's invalid, we fall back to project/org
    - If project has BYOK but it's invalid, we do NOT fall back to platform

    Behavior: behavior_externalize_configuration

    However, GitHub App installations take priority over PATs when both
    are configured, as they are more secure (auto-rotating tokens).

    Behavior: behavior_externalize_configuration
    """

    def __init__(self, pool: Optional[PostgresPool] = None) -> None:
        self._pool = pool
        self._platform_token: Optional[str] = None
        self._repo: Optional["GitHubCredentialRepository"] = None
        self._app_repo: Optional["GitHubAppInstallationRepository"] = None
        self._app_service: Optional["GitHubAppService"] = None
        self._load_platform_token()

    def _load_platform_token(self) -> None:
        """Load platform GitHub token from environment."""
        self._platform_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    def _get_repo(self) -> "GitHubCredentialRepository":
        """Lazy-load the credential repository."""
        if self._repo is None:
            from ..auth.github_credential_repository import GitHubCredentialRepository
            self._repo = GitHubCredentialRepository(pool=self._pool)
        return self._repo

    def _get_app_repo(self) -> "GitHubAppInstallationRepository":
        """Lazy-load the GitHub App installation repository."""
        if self._app_repo is None:
            from ..auth.github_app_installation_repository import GitHubAppInstallationRepository
            self._app_repo = GitHubAppInstallationRepository(pool=self._pool)
        return self._app_repo

    def _get_app_service(self) -> Optional["GitHubAppService"]:
        """Lazy-load the GitHub App service if configured."""
        if self._app_service is None:
            try:
                from ..auth.github_app_service import get_github_app_service
                self._app_service = get_github_app_service()
            except ValueError:
                # GitHub App not configured - this is fine, fall back to PATs
                logger.debug("GitHub App not configured, skipping App token resolution")
                return None
        return self._app_service

    def get_token(
        self,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        """Get GitHub token for a project/user.

        Returns:
            Tuple of (token, source) or None if not available.
            Source is one of: "user_app", "user_pat", "project_app", "org_app",
                             "project_pat", "org_pat", "platform"

        Note: Use get_resolved_token() for full metadata including
        scopes, rate limits, and credential ID for tracking.
        """
        resolved = self.get_resolved_token(project_id, org_id, user_id)
        if resolved:
            return (resolved.token, resolved.source)
        return None

    def get_resolved_token(
        self,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[ResolvedGitHubToken]:
        """Get GitHub token with full resolution metadata.

        Resolution order (user-aware):
        1. User's linked GitHub App for this project (if user_id provided)
        2. User's linked PAT for this project (if user_id provided)
        3. Project GitHub App installation token (shared)
        4. Org GitHub App installation token
        5. Project PAT/BYOK token (shared, legacy)
        6. Org PAT/BYOK token
        7. Platform token (from GITHUB_TOKEN/GH_TOKEN env var)

        User-level credentials (1-2) are checked first when user_id is provided,
        allowing per-user GitHub connections while falling back to shared credentials.

        GitHub App tokens take priority over PATs because they are more secure
        (auto-rotating, fine-grained permissions, auditable).

        If user-linked credential is invalid, we fall back to project/org level.
        If project-level BYOK PAT is configured but invalid, we do NOT fall back
        to platform token - this honors user/project intent.

        Args:
            project_id: Project ID to check for tokens
            org_id: Organization ID to check for tokens
            user_id: User ID for user-specific credential resolution (optional)

        Returns:
            ResolvedGitHubToken with token and metadata, or None if not available
        """
        from ..auth.github_credential_repository import (
            GitHubCredentialRepository,
            CredentialScopeType,
        )

        # -------------------------------------------------------------------------
        # 1. Check for User's linked GitHub App for this project
        # -------------------------------------------------------------------------
        if user_id and project_id:
            user_app_token = self._try_get_user_linked_app_token(user_id, project_id)
            if user_app_token:
                return user_app_token

        # -------------------------------------------------------------------------
        # 2. Check for User's linked PAT for this project
        # -------------------------------------------------------------------------
        if user_id and project_id:
            user_pat_token = self._try_get_user_linked_pat_token(user_id, project_id)
            if user_pat_token:
                return user_pat_token

        # -------------------------------------------------------------------------
        # 3. Check for Project GitHub App installation token (shared)
        # -------------------------------------------------------------------------
        if project_id:
            app_token = self._try_get_app_token(
                scope_type=CredentialScopeType.PROJECT,
                scope_id=project_id,
                source="project_app",
            )
            if app_token:
                return app_token

        # -------------------------------------------------------------------------
        # 4. Check for Org GitHub App installation token
        # -------------------------------------------------------------------------
        if org_id:
            app_token = self._try_get_app_token(
                scope_type=CredentialScopeType.ORG,
                scope_id=org_id,
                source="org_app",
            )
            if app_token:
                return app_token

        # -------------------------------------------------------------------------
        # 5. Check project-level PAT (BYOK, shared)
        # -------------------------------------------------------------------------
        repo = self._get_repo()

        if project_id:
            credential = repo.get_for_scope(
                scope_type=CredentialScopeType.PROJECT,
                scope_id=project_id,
                decrypt=True,
            )
            if credential:
                if credential.is_valid and credential.decrypted_token:
                    return ResolvedGitHubToken(
                        token=credential.decrypted_token,
                        source="project_pat",
                        credential_id=credential.id,
                        token_type=credential.token_type.value if credential.token_type else None,
                        github_username=credential.github_username,
                        scopes=credential.scopes,
                        has_required_scopes=credential.has_required_scopes,
                        scope_warning=credential.scope_warning,
                        rate_limit_remaining=credential.rate_limit_remaining,
                    )
                else:
                    # BYOK configured but invalid - do NOT fall back
                    # This honors project intent
                    logger.warning(
                        f"Project {project_id} has invalid GitHub credential {credential.id}, "
                        "not falling back to org/platform token"
                    )
                    return None

        # -------------------------------------------------------------------------
        # 6. Check org-level PAT (BYOK)
        # -------------------------------------------------------------------------
        if org_id:
            credential = repo.get_for_scope(
                scope_type=CredentialScopeType.ORG,
                scope_id=org_id,
                decrypt=True,
            )
            if credential:
                if credential.is_valid and credential.decrypted_token:
                    return ResolvedGitHubToken(
                        token=credential.decrypted_token,
                        source="org_pat",
                        credential_id=credential.id,
                        token_type=credential.token_type.value if credential.token_type else None,
                        github_username=credential.github_username,
                        scopes=credential.scopes,
                        has_required_scopes=credential.has_required_scopes,
                        scope_warning=credential.scope_warning,
                        rate_limit_remaining=credential.rate_limit_remaining,
                    )
                else:
                    # BYOK configured but invalid - do NOT fall back
                    logger.warning(
                        f"Org {org_id} has invalid GitHub credential {credential.id}, "
                        "not falling back to platform token"
                    )
                    return None

        # -------------------------------------------------------------------------
        # 7. Fall back to platform token
        # -------------------------------------------------------------------------
        if self._platform_token:
            return ResolvedGitHubToken(
                token=self._platform_token,
                source="platform",
            )

        return None

    def _try_get_user_linked_app_token(
        self,
        user_id: str,
        project_id: str,
    ) -> Optional[ResolvedGitHubToken]:
        """Try to get user's linked GitHub App installation token for a project.

        Args:
            user_id: The user ID
            project_id: The project ID

        Returns:
            ResolvedGitHubToken if successful, None otherwise
        """
        app_service = self._get_app_service()
        if not app_service:
            return None

        # Query user's linked app installation for this project
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            upl.id AS link_id,
                            upl.installation_link_id,
                            gail.installation_id,
                            gai.permissions
                        FROM auth.user_project_github_links upl
                        JOIN auth.github_app_installation_links gail
                            ON upl.installation_link_id = gail.id
                        JOIN auth.github_app_installations gai
                            ON gail.installation_id = gai.installation_id
                        WHERE upl.user_id = %s
                          AND upl.project_id = %s
                          AND upl.link_type = 'app'
                          AND gai.is_active = true
                        ORDER BY upl.priority ASC
                        LIMIT 1
                    """, (user_id, project_id))
                    row = cur.fetchone()

            if not row:
                return None

            link_id, installation_link_id, installation_id, permissions = row

            # Get the installation access token
            token = app_service.get_installation_token_sync(installation_id=installation_id)

            if not token:
                logger.warning(
                    f"Failed to get user-linked GitHub App token for user {user_id}, "
                    f"project {project_id}, installation {installation_id}"
                )
                return None

            return ResolvedGitHubToken(
                token=token,
                source="user_app",
                installation_id=installation_id,
                app_permissions=permissions,
                has_required_scopes=True,  # App permissions are always valid
                resolved_for_user_id=user_id,
                link_id=link_id,
            )

        except Exception as e:
            logger.warning(
                f"Error getting user-linked GitHub App token for user {user_id}, "
                f"project {project_id}: {e}"
            )
            return None

    def _try_get_user_linked_pat_token(
        self,
        user_id: str,
        project_id: str,
    ) -> Optional[ResolvedGitHubToken]:
        """Try to get user's linked PAT credential for a project.

        Args:
            user_id: The user ID
            project_id: The project ID

        Returns:
            ResolvedGitHubToken if successful, None otherwise
        """
        repo = self._get_repo()

        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            upl.id AS link_id,
                            upl.github_credential_id
                        FROM auth.user_project_github_links upl
                        WHERE upl.user_id = %s
                          AND upl.project_id = %s
                          AND upl.link_type = 'pat'
                        ORDER BY upl.priority ASC
                        LIMIT 1
                    """, (user_id, project_id))
                    row = cur.fetchone()

            if not row:
                return None

            link_id, credential_id = row

            # Get the credential with decrypted token
            credential = repo.get_by_id(credential_id, decrypt=True)

            if not credential:
                logger.warning(
                    f"User-linked PAT credential {credential_id} not found for "
                    f"user {user_id}, project {project_id}"
                )
                return None

            if not credential.is_valid or not credential.decrypted_token:
                logger.info(
                    f"User-linked PAT credential {credential_id} is invalid for "
                    f"user {user_id}, project {project_id} - falling back to project/org"
                )
                return None

            return ResolvedGitHubToken(
                token=credential.decrypted_token,
                source="user_pat",
                credential_id=credential.id,
                token_type=credential.token_type.value if credential.token_type else None,
                github_username=credential.github_username,
                scopes=credential.scopes,
                has_required_scopes=credential.has_required_scopes,
                scope_warning=credential.scope_warning,
                rate_limit_remaining=credential.rate_limit_remaining,
                resolved_for_user_id=user_id,
                link_id=link_id,
            )

        except Exception as e:
            logger.warning(
                f"Error getting user-linked PAT token for user {user_id}, "
                f"project {project_id}: {e}"
            )
            return None

    def _try_get_app_token(
        self,
        scope_type: "CredentialScopeType",
        scope_id: str,
        source: str,
    ) -> Optional[ResolvedGitHubToken]:
        """Try to get a GitHub App installation token for a scope.

        Args:
            scope_type: PROJECT or ORG
            scope_id: The project or org ID
            source: Token source label for logging

        Returns:
            ResolvedGitHubToken if successful, None otherwise
        """
        app_service = self._get_app_service()
        if not app_service:
            return None

        app_repo = self._get_app_repo()

        try:
            installation = app_repo.get_installation_for_scope(
                scope_type=scope_type,
                scope_id=scope_id,
            )

            if not installation:
                return None

            # Get or refresh the installation token
            # Note: get_installation_token_sync handles caching internally
            # and returns just the token string
            token = app_service.get_installation_token_sync(
                installation_id=installation.installation_id
            )

            if not token:
                logger.warning(
                    f"Failed to get GitHub App token for {source} {scope_id}, "
                    f"installation {installation.installation_id}"
                )
                return None

            return ResolvedGitHubToken(
                token=token,
                source=source,
                installation_id=installation.installation_id,
                app_permissions=installation.permissions,
                # Note: exact expiry is managed by the GitHubAppService's cache
                # Tokens are valid for ~1 hour with auto-refresh
                has_required_scopes=True,  # App permissions are always valid
            )

        except Exception as e:
            logger.warning(
                f"Error getting GitHub App token for {source} {scope_id}: {e}"
            )
            return None

    def record_token_usage(
        self,
        credential_id: str,
        success: bool,
        error_code: Optional[int] = None,
        error_message: Optional[str] = None,
        rate_limit: Optional[int] = None,
        rate_limit_remaining: Optional[int] = None,
        rate_limit_reset: Optional["datetime"] = None,
        run_id: Optional[str] = None,
    ) -> None:
        """Record token usage for tracking and failure handling.

        Call this after using a BYOK token to update rate limits and
        track failures for auto-disable functionality.

        Args:
            credential_id: The credential ID (from ResolvedGitHubToken)
            success: Whether the API call succeeded
            error_code: HTTP error code if failed
            error_message: Error message if failed
            rate_limit: X-RateLimit-Limit header value
            rate_limit_remaining: X-RateLimit-Remaining header value
            rate_limit_reset: X-RateLimit-Reset as datetime
            run_id: Associated run ID for audit trail
        """
        if not credential_id:
            return  # Platform tokens don't need tracking

        repo = self._get_repo()

        if success:
            repo.record_success(
                credential_id=credential_id,
                rate_limit=rate_limit,
                rate_limit_remaining=rate_limit_remaining,
                rate_limit_reset=rate_limit_reset,
                run_id=run_id,
            )
        else:
            disabled = repo.record_failure(
                credential_id=credential_id,
                error_code=error_code or 0,
                error_message=error_message,
                run_id=run_id,
            )
            if disabled:
                logger.warning(
                    f"GitHub credential {credential_id} has been auto-disabled "
                    "due to consecutive failures"
                )


# ==============================================================================
# GitHub API Client
# ==============================================================================


class GitHubClient:
    """Low-level GitHub API client using httpx for performance."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._token = token
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Make an API request."""
        response = self._client.request(method, path, json=json, params=params)
        return response

    def get_repo_info(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        """Get repository information including default branch.

        Returns:
            Repository data including 'default_branch' field, or None if not found.
        """
        resp = self._request("GET", f"/repos/{owner}/{repo}")
        if resp.status_code == 200:
            return resp.json()
        return None

    def get_ref(self, owner: str, repo: str, ref: str) -> Optional[Dict[str, Any]]:
        """Get a git reference (branch/tag)."""
        resp = self._request("GET", f"/repos/{owner}/{repo}/git/refs/{ref}")
        if resp.status_code == 200:
            return resp.json()
        return None

    def create_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        sha: str,
    ) -> Dict[str, Any]:
        """Create a new git reference."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": ref, "sha": sha},
        )
        resp.raise_for_status()
        return resp.json()

    def get_branch(self, owner: str, repo: str, branch: str) -> Optional[Dict[str, Any]]:
        """Get branch details."""
        resp = self._request("GET", f"/repos/{owner}/{repo}/branches/{quote(branch, safe='')}")
        if resp.status_code == 200:
            return resp.json()
        return None

    def create_blob(self, owner: str, repo: str, content: str, encoding: str = "base64") -> str:
        """Create a blob and return its SHA."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            json={"content": content, "encoding": encoding},
        )
        resp.raise_for_status()
        return resp.json()["sha"]

    def get_tree(self, owner: str, repo: str, sha: str) -> Dict[str, Any]:
        """Get a tree object."""
        resp = self._request("GET", f"/repos/{owner}/{repo}/git/trees/{sha}")
        resp.raise_for_status()
        return resp.json()

    def create_tree(
        self,
        owner: str,
        repo: str,
        base_tree: str,
        tree: List[Dict[str, Any]],
    ) -> str:
        """Create a tree and return its SHA."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/trees",
            json={"base_tree": base_tree, "tree": tree},
        )
        resp.raise_for_status()
        return resp.json()["sha"]

    def create_commit(
        self,
        owner: str,
        repo: str,
        message: str,
        tree: str,
        parents: List[str],
    ) -> Dict[str, Any]:
        """Create a commit."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/commits",
            json={"message": message, "tree": tree, "parents": parents},
        )
        resp.raise_for_status()
        return resp.json()

    def update_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        sha: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Update a reference to point to a new commit."""
        resp = self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/git/refs/{ref}",
            json={"sha": sha, "force": force},
        )
        resp.raise_for_status()
        return resp.json()

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False,
    ) -> Dict[str, Any]:
        """Create a pull request."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": draft,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def request_reviewers(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        reviewers: List[str],
    ) -> Dict[str, Any]:
        """Request reviewers for a PR."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers",
            json={"reviewers": reviewers},
        )
        resp.raise_for_status()
        return resp.json()

    def add_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        labels: List[str],
    ) -> List[Dict[str, Any]]:
        """Add labels to an issue/PR."""
        resp = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )
        resp.raise_for_status()
        return resp.json()


# ==============================================================================
# GitHub Service
# ==============================================================================


class GitHubService:
    """High-level GitHub operations service.

    Provides methods for:
    - Creating commits on branches
    - Creating pull requests with file changes

    Uses GitHubCredentialStore for token resolution.
    """

    def __init__(
        self,
        credential_store: Optional[GitHubCredentialStore] = None,
        pool: Optional[PostgresPool] = None,
    ) -> None:
        self._credential_store = credential_store or GitHubCredentialStore(pool=pool)
        self._pool = pool

    def _get_client(
        self,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Tuple[GitHubClient, str]:
        """Get GitHub client with resolved token.

        Returns:
            Tuple of (client, token_source)

        Raises:
            ValueError: If no token is available
        """
        result = self._credential_store.get_token(project_id, org_id)
        if not result:
            raise ValueError(
                "No GitHub token available. Set GITHUB_TOKEN environment variable "
                "or configure project-level BYOK credentials."
            )
        token, source = result
        return GitHubClient(token), source

    def _parse_repo(self, repo: str) -> Tuple[str, str]:
        """Parse owner/repo string."""
        if "/" not in repo:
            raise ValueError(f"Invalid repo format: {repo}. Expected 'owner/repo'.")
        parts = repo.split("/", 1)
        return parts[0], parts[1]

    def get_default_branch(
        self,
        repo: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Get the default branch for a repository.

        Queries the GitHub API to detect the repository's default branch.
        Falls back to 'main' if the API call fails.

        Args:
            repo: Repository in "owner/repo" format
            project_id: Project ID for credential resolution
            org_id: Org ID for credential resolution

        Returns:
            Default branch name (e.g., 'main', 'master', 'develop')
        """
        try:
            owner, repo_name = self._parse_repo(repo)
            client, _ = self._get_client(project_id, org_id)

            with client:
                repo_info = client.get_repo_info(owner, repo_name)
                if repo_info and "default_branch" in repo_info:
                    return repo_info["default_branch"]
        except Exception as e:
            logger.warning(f"Failed to get default branch for {repo}: {e}")

        # Fallback to 'main' if detection fails
        return "main"

    def commit_to_branch(
        self,
        repo: str,
        branch: str,
        message: str,
        files: List[FileChange],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        create_branch: bool = True,
        base_branch: str = "main",
        message_body: Optional[str] = None,
    ) -> CommitResult:
        """Commit file changes to a branch.

        Creates the branch if it doesn't exist and create_branch=True.

        Args:
            repo: Repository in "owner/repo" format
            branch: Target branch name
            message: Commit message (first line)
            files: List of file changes
            project_id: Project ID for credential resolution
            org_id: Org ID for credential resolution
            create_branch: Create branch if it doesn't exist
            base_branch: Base branch for new branches
            message_body: Extended commit message body

        Returns:
            CommitResult with commit details
        """
        try:
            owner, repo_name = self._parse_repo(repo)
            client, token_source = self._get_client(project_id, org_id)

            with client:
                # Check if branch exists
                branch_data = client.get_branch(owner, repo_name, branch)
                branch_created = False

                if not branch_data:
                    if not create_branch:
                        return CommitResult(
                            success=False,
                            error=f"Branch '{branch}' does not exist and create_branch=False",
                        )

                    # Create branch from base
                    base_data = client.get_branch(owner, repo_name, base_branch)
                    if not base_data:
                        return CommitResult(
                            success=False,
                            error=f"Base branch '{base_branch}' does not exist",
                        )

                    base_sha = base_data["commit"]["sha"]
                    client.create_ref(owner, repo_name, f"refs/heads/{branch}", base_sha)
                    branch_created = True
                    parent_sha = base_sha
                    base_tree_sha = base_data["commit"]["commit"]["tree"]["sha"]
                else:
                    parent_sha = branch_data["commit"]["sha"]
                    base_tree_sha = branch_data["commit"]["commit"]["tree"]["sha"]

                # Build tree entries
                tree_entries: List[Dict[str, Any]] = []

                for file_change in files:
                    if file_change.action == "delete":
                        # Delete = entry with sha=None
                        tree_entries.append({
                            "path": file_change.path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": None,
                        })
                    else:
                        # Create/update = create blob first
                        blob_content = file_change.to_blob_content()
                        if blob_content:
                            blob_sha = client.create_blob(owner, repo_name, blob_content)
                            tree_entries.append({
                                "path": file_change.path,
                                "mode": "100644",
                                "type": "blob",
                                "sha": blob_sha,
                            })

                # Create tree
                tree_sha = client.create_tree(owner, repo_name, base_tree_sha, tree_entries)

                # Format commit message
                full_message = message
                if message_body:
                    full_message = f"{message}\n\n{message_body}"

                # Create commit
                commit = client.create_commit(
                    owner, repo_name, full_message, tree_sha, [parent_sha]
                )
                commit_sha = commit["sha"]

                # Update branch ref
                client.update_ref(owner, repo_name, f"heads/{branch}", commit_sha)

                return CommitResult(
                    success=True,
                    commit_sha=commit_sha,
                    commit_url=commit["html_url"],
                    tree_sha=tree_sha,
                    branch=branch,
                    branch_created=branch_created,
                    files_changed=len(files),
                )

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"GitHub API error: {e.response.status_code} - {error_body}")
            return CommitResult(
                success=False,
                error=f"GitHub API error ({e.response.status_code}): {error_body}",
            )
        except ValueError as e:
            return CommitResult(success=False, error=str(e))
        except Exception as e:
            logger.exception("Failed to commit to branch")
            return CommitResult(success=False, error=f"Failed to commit: {e}")

    def create_pull_request(
        self,
        repo: str,
        title: str,
        head_branch: str,
        files: List[FileChange],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        body: Optional[str] = None,
        base_branch: str = "main",
        commit_message: Optional[str] = None,
        draft: bool = False,
        labels: Optional[List[str]] = None,
        reviewers: Optional[List[str]] = None,
    ) -> PRResult:
        """Create a pull request with file changes.

        Creates a new branch, commits changes, and opens a PR.

        Args:
            repo: Repository in "owner/repo" format
            title: PR title
            head_branch: Branch name for changes
            files: List of file changes
            project_id: Project ID for credential resolution
            org_id: Org ID for credential resolution
            body: PR description (markdown)
            base_branch: Target branch to merge into
            commit_message: Commit message (defaults to PR title)
            draft: Create as draft PR
            labels: Labels to add
            reviewers: Usernames to request review from

        Returns:
            PRResult with PR details
        """
        try:
            # First, commit the files to the head branch
            commit_result = self.commit_to_branch(
                repo=repo,
                branch=head_branch,
                message=commit_message or title,
                files=files,
                project_id=project_id,
                org_id=org_id,
                create_branch=True,
                base_branch=base_branch,
            )

            if not commit_result.success:
                return PRResult(
                    success=False,
                    error=f"Failed to commit changes: {commit_result.error}",
                )

            owner, repo_name = self._parse_repo(repo)
            client, _ = self._get_client(project_id, org_id)

            with client:
                # Create the PR
                pr = client.create_pull_request(
                    owner=owner,
                    repo=repo_name,
                    title=title,
                    body=body or "",
                    head=head_branch,
                    base=base_branch,
                    draft=draft,
                )

                pr_number = pr["number"]

                # Add labels if specified
                if labels:
                    try:
                        client.add_labels(owner, repo_name, pr_number, labels)
                    except Exception as e:
                        logger.warning(f"Failed to add labels: {e}")

                # Request reviewers if specified
                if reviewers:
                    try:
                        client.request_reviewers(owner, repo_name, pr_number, reviewers)
                    except Exception as e:
                        logger.warning(f"Failed to request reviewers: {e}")

                return PRResult(
                    success=True,
                    pr_number=pr_number,
                    pr_url=pr["html_url"],
                    head_branch=head_branch,
                    commit_sha=commit_result.commit_sha,
                    files_changed=len(files),
                )

        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            logger.error(f"GitHub API error: {e.response.status_code} - {error_body}")
            return PRResult(
                success=False,
                error=f"GitHub API error ({e.response.status_code}): {error_body}",
            )
        except ValueError as e:
            return PRResult(success=False, error=str(e))
        except Exception as e:
            logger.exception("Failed to create PR")
            return PRResult(success=False, error=f"Failed to create PR: {e}")
