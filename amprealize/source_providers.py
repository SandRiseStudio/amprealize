"""Source Providers — Abstractions for multi-git-provider workspace provisioning.

Replaces the GitHub-only clone logic in AmpOrchestrator._clone_repo() with a
pluggable provider system. Each SourceProvider knows how to:

1. Resolve credentials for its hosting platform
2. Build an authenticated clone URL
3. Clone (or mount) a repository into a target directory
4. Optionally support sparse checkout for large repos

Providers:
    - GitHubSourceProvider: GitHub repos via PAT or GitHub App tokens
    - GitLabSourceProvider: GitLab repos via PAT or deploy tokens
    - BareGitSourceProvider: Any git URL (HTTPS/SSH)
    - LocalDirSourceProvider: Local directories (mount or copy)

Part of E3 — Agent Execution Loop Rearchitecture (AMPREALIZE-277 / Phase 2).
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .execution_gateway_contracts import ResolvedExecution, SourceType

logger = logging.getLogger(__name__)


# =============================================================================
# Contracts
# =============================================================================


class CloneStrategy(str, Enum):
    """How to fetch source code into the workspace."""

    FULL = "full"           # Standard git clone
    SHALLOW = "shallow"     # git clone --depth 1
    SPARSE = "sparse"       # Sparse checkout — only clone specified paths
    MOUNT = "mount"         # Bind-mount local directory (no clone)
    COPY = "copy"           # Copy local directory into workspace


@dataclass
class CloneSpec:
    """Fully resolved specification for cloning a source into a workspace.

    Built by a SourceProvider, consumed by an executor or orchestrator
    to perform the actual clone operation.
    """

    # What to clone
    clone_url: str                              # Authenticated URL (or local path)
    ref: str = "main"                           # Branch, tag, or commit SHA
    strategy: CloneStrategy = CloneStrategy.SHALLOW

    # Where to clone
    target_dir: str = "/workspace/repo"         # Path inside the container

    # Sparse checkout paths (only for SPARSE strategy)
    sparse_paths: List[str] = field(default_factory=list)

    # Auth metadata (never logged)
    has_credentials: bool = False
    credential_source: str = ""                 # e.g. "project_app", "platform"

    # Provider metadata
    source_type: SourceType = SourceType.BARE_GIT
    repo_identifier: str = ""                   # e.g. "owner/repo" or URL


@dataclass
class CloneResult:
    """Result of a source provisioning operation."""

    success: bool
    workspace_path: str = ""                    # Path where code landed
    strategy_used: CloneStrategy = CloneStrategy.SHALLOW
    ref_resolved: str = ""                      # Actual ref after checkout
    error: Optional[str] = None


# =============================================================================
# SourceProvider Protocol
# =============================================================================


@runtime_checkable
class SourceProvider(Protocol):
    """Protocol for source code providers.

    Each provider (GitHub, GitLab, bare git, local) implements this protocol
    to handle credential resolution and clone URL construction for its
    platform.
    """

    @property
    def source_type(self) -> SourceType:
        """The type of source this provider handles."""
        ...

    def build_clone_spec(
        self,
        resolved: ResolvedExecution,
        *,
        strategy: Optional[CloneStrategy] = None,
        sparse_paths: Optional[List[str]] = None,
        target_dir: str = "/workspace/repo",
    ) -> CloneSpec:
        """Build a fully resolved CloneSpec for the given execution.

        The provider resolves credentials and constructs the clone URL.
        The caller (executor) uses the CloneSpec to perform the actual clone.

        Args:
            resolved: ResolvedExecution with source_url, source_ref, etc.
            strategy: Override clone strategy. If None, provider picks a default.
            sparse_paths: Paths for sparse checkout (only with SPARSE strategy).
            target_dir: Where to clone inside the container.

        Returns:
            CloneSpec ready for execution.
        """
        ...


# =============================================================================
# Source clone executor (runs commands in a container or locally)
# =============================================================================


async def execute_clone(
    clone_spec: CloneSpec,
    *,
    exec_fn: Any,
) -> CloneResult:
    """Execute a clone operation using the provided exec function.

    This is the shared implementation that all executors and the orchestrator
    call to actually clone source code. It translates a CloneSpec into git
    commands and runs them via the provided exec_fn.

    Args:
        clone_spec: Fully resolved clone specification.
        exec_fn: Async callable (command: str) -> (output: str, exit_code: int).
                 For containers, this wraps podman exec. For local, subprocess.

    Returns:
        CloneResult with success status and resolved path.
    """
    if clone_spec.strategy == CloneStrategy.MOUNT:
        # Mount is handled at container creation time, not via git commands.
        return CloneResult(
            success=True,
            workspace_path=clone_spec.target_dir,
            strategy_used=CloneStrategy.MOUNT,
            ref_resolved=clone_spec.ref,
        )

    if clone_spec.strategy == CloneStrategy.COPY:
        return await _execute_copy(clone_spec, exec_fn=exec_fn)

    if clone_spec.strategy == CloneStrategy.SPARSE:
        return await _execute_sparse_clone(clone_spec, exec_fn=exec_fn)

    # FULL or SHALLOW clone
    return await _execute_git_clone(clone_spec, exec_fn=exec_fn)


async def _execute_git_clone(
    spec: CloneSpec,
    *,
    exec_fn: Any,
) -> CloneResult:
    """Standard or shallow git clone."""
    parts = ["git", "clone"]

    if spec.strategy == CloneStrategy.SHALLOW:
        parts.extend(["--depth", "1"])

    if spec.ref and spec.ref != "HEAD":
        parts.extend(["--branch", spec.ref])

    parts.extend(["--", spec.clone_url, spec.target_dir])
    cmd = _build_safe_command(parts)

    output, exit_code = await exec_fn(cmd)
    if exit_code != 0:
        # Redact credentials from error message
        safe_output = _redact_url(output, spec.clone_url)
        logger.warning(f"Git clone failed (exit {exit_code}): {safe_output}")
        return CloneResult(
            success=False,
            error=f"Git clone failed (exit {exit_code}): {safe_output}",
            strategy_used=spec.strategy,
        )

    return CloneResult(
        success=True,
        workspace_path=spec.target_dir,
        strategy_used=spec.strategy,
        ref_resolved=spec.ref,
    )


async def _execute_sparse_clone(
    spec: CloneSpec,
    *,
    exec_fn: Any,
) -> CloneResult:
    """Sparse checkout — clone only specified paths.

    Uses git sparse-checkout to fetch a minimal working tree. This is
    ideal for large monorepos where the agent only needs specific directories.

    Sequence:
        1. git clone --no-checkout --depth 1 --filter=blob:none <url> <dir>
        2. cd <dir> && git sparse-checkout init --cone
        3. git sparse-checkout set <paths...>
        4. git checkout <ref>
    """
    if not spec.sparse_paths:
        # Fall back to shallow clone if no sparse paths given
        logger.info("No sparse_paths provided, falling back to shallow clone")
        return await _execute_git_clone(
            CloneSpec(
                clone_url=spec.clone_url,
                ref=spec.ref,
                strategy=CloneStrategy.SHALLOW,
                target_dir=spec.target_dir,
                has_credentials=spec.has_credentials,
                source_type=spec.source_type,
                repo_identifier=spec.repo_identifier,
            ),
            exec_fn=exec_fn,
        )

    # Step 1: Clone without checkout
    clone_parts = [
        "git", "clone",
        "--no-checkout", "--depth", "1", "--filter=blob:none",
    ]
    if spec.ref and spec.ref != "HEAD":
        clone_parts.extend(["--branch", spec.ref])
    clone_parts.extend(["--", spec.clone_url, spec.target_dir])
    clone_cmd = _build_safe_command(clone_parts)

    output, exit_code = await exec_fn(clone_cmd)
    if exit_code != 0:
        safe_output = _redact_url(output, spec.clone_url)
        return CloneResult(
            success=False,
            error=f"Sparse clone init failed: {safe_output}",
            strategy_used=CloneStrategy.SPARSE,
        )

    # Step 2: Init sparse-checkout in cone mode
    init_cmd = f"cd {shlex.quote(spec.target_dir)} && git sparse-checkout init --cone"
    output, exit_code = await exec_fn(init_cmd)
    if exit_code != 0:
        return CloneResult(
            success=False,
            error=f"sparse-checkout init failed: {output}",
            strategy_used=CloneStrategy.SPARSE,
        )

    # Step 3: Set sparse paths
    safe_paths = " ".join(shlex.quote(p) for p in spec.sparse_paths)
    set_cmd = f"cd {shlex.quote(spec.target_dir)} && git sparse-checkout set {safe_paths}"
    output, exit_code = await exec_fn(set_cmd)
    if exit_code != 0:
        return CloneResult(
            success=False,
            error=f"sparse-checkout set failed: {output}",
            strategy_used=CloneStrategy.SPARSE,
        )

    # Step 4: Checkout
    ref = spec.ref if spec.ref and spec.ref != "HEAD" else "HEAD"
    checkout_cmd = f"cd {shlex.quote(spec.target_dir)} && git checkout {shlex.quote(ref)}"
    output, exit_code = await exec_fn(checkout_cmd)
    if exit_code != 0:
        return CloneResult(
            success=False,
            error=f"sparse checkout failed: {output}",
            strategy_used=CloneStrategy.SPARSE,
        )

    return CloneResult(
        success=True,
        workspace_path=spec.target_dir,
        strategy_used=CloneStrategy.SPARSE,
        ref_resolved=ref,
    )


async def _execute_copy(
    spec: CloneSpec,
    *,
    exec_fn: Any,
) -> CloneResult:
    """Copy a local directory into the target."""
    src = shlex.quote(spec.clone_url)
    dst = shlex.quote(spec.target_dir)
    cmd = f"cp -a {src}/. {dst}/"
    output, exit_code = await exec_fn(cmd)
    if exit_code != 0:
        return CloneResult(
            success=False,
            error=f"Directory copy failed: {output}",
            strategy_used=CloneStrategy.COPY,
        )

    return CloneResult(
        success=True,
        workspace_path=spec.target_dir,
        strategy_used=CloneStrategy.COPY,
        ref_resolved="local",
    )


# =============================================================================
# Helpers
# =============================================================================


def _build_safe_command(parts: List[str]) -> str:
    """Build a shell command from parts, quoting as needed."""
    return " ".join(shlex.quote(p) for p in parts)


def _redact_url(text: str, clone_url: str) -> str:
    """Redact credentials from clone URL in error messages."""
    # If URL contains embedded credentials (https://token@host/...), redact them
    if "@" in clone_url:
        # Extract the credential portion
        scheme_end = clone_url.find("://")
        if scheme_end != -1:
            at_pos = clone_url.find("@", scheme_end)
            if at_pos != -1:
                cred_part = clone_url[scheme_end + 3:at_pos]
                text = text.replace(cred_part, "***")
                text = text.replace(clone_url, clone_url[:scheme_end + 3] + "***@" + clone_url[at_pos + 1:])
    return text


def resolve_source_provider(
    source_type: SourceType,
    *,
    provider_registry: Optional[Dict[SourceType, "SourceProvider"]] = None,
) -> Optional["SourceProvider"]:
    """Look up the appropriate SourceProvider for a given source type.

    Args:
        source_type: The SourceType to resolve.
        provider_registry: Map of SourceType -> SourceProvider instances.

    Returns:
        The matching SourceProvider, or None if not registered.
    """
    if provider_registry is None:
        return None
    return provider_registry.get(source_type)


# =============================================================================
# GitHubSourceProvider
# =============================================================================


class GitHubSourceProvider:
    """Source provider for GitHub repositories.

    Resolves GitHub tokens via GitHubCredentialStore and constructs
    authenticated HTTPS clone URLs. Supports full, shallow, and sparse
    checkout strategies.
    """

    def __init__(self, github_credential_store: Any = None) -> None:
        """
        Args:
            github_credential_store: GitHubCredentialStore instance for token
                resolution. If None, falls back to GITHUB_TOKEN env var.
        """
        self._cred_store = github_credential_store

    @property
    def source_type(self) -> SourceType:
        return SourceType.GITHUB

    def build_clone_spec(
        self,
        resolved: ResolvedExecution,
        *,
        strategy: Optional[CloneStrategy] = None,
        sparse_paths: Optional[List[str]] = None,
        target_dir: str = "/workspace/repo",
    ) -> CloneSpec:
        repo = resolved.source_url
        if not repo:
            raise ValueError("GitHub source_url is required (e.g. 'owner/repo')")

        # Resolve credentials
        token, cred_source = self._resolve_token(resolved)

        # Build clone URL
        if token:
            clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
        else:
            clone_url = f"https://github.com/{repo}.git"

        effective_strategy = strategy or (
            CloneStrategy.SPARSE if sparse_paths else CloneStrategy.SHALLOW
        )

        return CloneSpec(
            clone_url=clone_url,
            ref=resolved.source_ref or "main",
            strategy=effective_strategy,
            target_dir=target_dir,
            sparse_paths=sparse_paths or [],
            has_credentials=bool(token),
            credential_source=cred_source,
            source_type=SourceType.GITHUB,
            repo_identifier=repo,
        )

    def _resolve_token(self, resolved: ResolvedExecution) -> tuple[Optional[str], str]:
        """Resolve a GitHub token. Returns (token, source)."""
        if not self._cred_store:
            import os
            env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
            return env_token, "platform" if env_token else ""

        try:
            result = self._cred_store.get_resolved_token(
                project_id=resolved.request.project_id,
                org_id=resolved.request.org_id,
                user_id=resolved.request.user_id,
            )
            if result:
                return result.token, result.source
        except Exception as e:
            logger.warning(f"GitHub token resolution failed: {e}")

        return None, ""


# =============================================================================
# GitLabSourceProvider
# =============================================================================


class GitLabSourceProvider:
    """Source provider for GitLab repositories.

    Supports GitLab.com and self-hosted GitLab instances. Resolves tokens
    from a credential store or environment variables.
    """

    def __init__(
        self,
        *,
        credential_store: Any = None,
        default_host: str = "gitlab.com",
    ) -> None:
        """
        Args:
            credential_store: Credential store that supports
                get_gitlab_token(project_id, org_id, user_id).
            default_host: Default GitLab host (for source_url without host).
        """
        self._cred_store = credential_store
        self._default_host = default_host

    @property
    def source_type(self) -> SourceType:
        return SourceType.GITLAB

    def build_clone_spec(
        self,
        resolved: ResolvedExecution,
        *,
        strategy: Optional[CloneStrategy] = None,
        sparse_paths: Optional[List[str]] = None,
        target_dir: str = "/workspace/repo",
    ) -> CloneSpec:
        source_url = resolved.source_url
        if not source_url:
            raise ValueError("GitLab source_url is required")

        token, cred_source = self._resolve_token(resolved)
        host, path = self._parse_gitlab_url(source_url)
        clone_url = self._build_clone_url(host, path, token)

        effective_strategy = strategy or (
            CloneStrategy.SPARSE if sparse_paths else CloneStrategy.SHALLOW
        )

        return CloneSpec(
            clone_url=clone_url,
            ref=resolved.source_ref or "main",
            strategy=effective_strategy,
            target_dir=target_dir,
            sparse_paths=sparse_paths or [],
            has_credentials=bool(token),
            credential_source=cred_source,
            source_type=SourceType.GITLAB,
            repo_identifier=source_url,
        )

    def _parse_gitlab_url(self, source_url: str) -> tuple[str, str]:
        """Parse a GitLab source URL into (host, path).

        Supports:
            - "group/project" -> (default_host, "group/project")
            - "https://gitlab.example.com/group/project" -> ("gitlab.example.com", "group/project")
            - "gitlab.example.com/group/project" -> ("gitlab.example.com", "group/project")
        """
        if source_url.startswith("https://") or source_url.startswith("http://"):
            # Full URL
            from urllib.parse import urlparse
            parsed = urlparse(source_url)
            host = parsed.hostname or self._default_host
            path = parsed.path.lstrip("/").removesuffix(".git")
            return host, path

        # Check if it starts with a hostname pattern (contains dots before first slash)
        slash_pos = source_url.find("/")
        if slash_pos != -1 and "." in source_url[:slash_pos]:
            # "gitlab.example.com/group/project"
            host = source_url[:slash_pos]
            path = source_url[slash_pos + 1:].removesuffix(".git")
            return host, path

        # Bare path: "group/project"
        return self._default_host, source_url.removesuffix(".git")

    def _build_clone_url(self, host: str, path: str, token: Optional[str]) -> str:
        if token:
            return f"https://oauth2:{token}@{host}/{path}.git"
        return f"https://{host}/{path}.git"

    def _resolve_token(self, resolved: ResolvedExecution) -> tuple[Optional[str], str]:
        """Resolve a GitLab token."""
        if self._cred_store and hasattr(self._cred_store, "get_gitlab_token"):
            try:
                result = self._cred_store.get_gitlab_token(
                    project_id=resolved.request.project_id,
                    org_id=resolved.request.org_id,
                    user_id=resolved.request.user_id,
                )
                if result:
                    return result if isinstance(result, tuple) else (result, "credential_store")
            except Exception as e:
                logger.warning(f"GitLab token resolution failed: {e}")

        import os
        env_token = os.getenv("GITLAB_TOKEN") or os.getenv("GL_TOKEN")
        return env_token, "platform" if env_token else ""


# =============================================================================
# BareGitSourceProvider
# =============================================================================


class BareGitSourceProvider:
    """Source provider for any git repository accessible via HTTPS or SSH.

    Works with any standard git remote. No platform-specific credential
    resolution — expects the URL to be pre-authenticated or uses SSH keys.
    """

    @property
    def source_type(self) -> SourceType:
        return SourceType.BARE_GIT

    def build_clone_spec(
        self,
        resolved: ResolvedExecution,
        *,
        strategy: Optional[CloneStrategy] = None,
        sparse_paths: Optional[List[str]] = None,
        target_dir: str = "/workspace/repo",
    ) -> CloneSpec:
        source_url = resolved.source_url
        if not source_url:
            raise ValueError("Bare git source_url is required")

        effective_strategy = strategy or (
            CloneStrategy.SPARSE if sparse_paths else CloneStrategy.SHALLOW
        )

        # Determine if URL has embedded credentials
        has_creds = "@" in source_url and "://" in source_url

        return CloneSpec(
            clone_url=source_url,
            ref=resolved.source_ref or "main",
            strategy=effective_strategy,
            target_dir=target_dir,
            sparse_paths=sparse_paths or [],
            has_credentials=has_creds,
            credential_source="url" if has_creds else "",
            source_type=SourceType.BARE_GIT,
            repo_identifier=_redact_url(source_url, source_url) if has_creds else source_url,
        )


# =============================================================================
# LocalDirSourceProvider
# =============================================================================


class LocalDirSourceProvider:
    """Source provider for local directories.

    For CONTAINER_CONNECTED mode, returns a MOUNT spec (the executor handles
    the actual bind-mount at container creation time).

    For CONTAINER_ISOLATED mode, returns a COPY spec (files are copied into
    the container).

    For LOCAL_DIRECT mode, returns the path directly (no clone needed).
    """

    @property
    def source_type(self) -> SourceType:
        return SourceType.LOCAL_DIR

    def build_clone_spec(
        self,
        resolved: ResolvedExecution,
        *,
        strategy: Optional[CloneStrategy] = None,
        sparse_paths: Optional[List[str]] = None,
        target_dir: str = "/workspace/repo",
    ) -> CloneSpec:
        local_path = resolved.source_url or resolved.request.workspace_path
        if not local_path:
            raise ValueError("Local source requires source_url or workspace_path")

        # Validate path exists
        real_path = Path(local_path).resolve()
        if not real_path.is_dir():
            raise ValueError(f"Local source path does not exist: {real_path}")

        from .execution_gateway_contracts import NewExecutionMode

        if strategy is not None:
            effective_strategy = strategy
        elif resolved.mode == NewExecutionMode.CONTAINER_CONNECTED:
            effective_strategy = CloneStrategy.MOUNT
        elif resolved.mode == NewExecutionMode.LOCAL_DIRECT:
            effective_strategy = CloneStrategy.MOUNT  # No-op: path is the workspace
        else:
            # CONTAINER_ISOLATED with local source — copy into container
            effective_strategy = CloneStrategy.COPY

        return CloneSpec(
            clone_url=str(real_path),
            ref="local",
            strategy=effective_strategy,
            target_dir=target_dir if effective_strategy != CloneStrategy.MOUNT else str(real_path),
            has_credentials=False,
            credential_source="",
            source_type=SourceType.LOCAL_DIR,
            repo_identifier=str(real_path),
        )


# =============================================================================
# Provider Registry Factory
# =============================================================================


def build_source_provider_registry(
    *,
    github_credential_store: Any = None,
    gitlab_credential_store: Any = None,
    gitlab_host: str = "gitlab.com",
) -> Dict[SourceType, SourceProvider]:
    """Build the default SourceProvider registry.

    Args:
        github_credential_store: GitHubCredentialStore for GitHub token resolution.
        gitlab_credential_store: Credential store with get_gitlab_token() for GitLab.
        gitlab_host: Default GitLab host for bare paths.

    Returns:
        Dict mapping SourceType to its provider implementation.
    """
    return {
        SourceType.GITHUB: GitHubSourceProvider(
            github_credential_store=github_credential_store,
        ),
        SourceType.GITLAB: GitLabSourceProvider(
            credential_store=gitlab_credential_store,
            default_host=gitlab_host,
        ),
        SourceType.BARE_GIT: BareGitSourceProvider(),
        SourceType.LOCAL_DIR: LocalDirSourceProvider(),
    }
