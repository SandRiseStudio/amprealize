"""Tests for Phase 2 — SourceProvider abstraction and clone execution.

Covers:
- source_providers: SourceProvider protocol, all 4 implementations
- execute_clone: Full, shallow, sparse, mount, and copy strategies
- Provider registry: build_source_provider_registry + resolve_source_provider
- Executor integration: ContainerIsolatedExecutor with source providers
"""

from __future__ import annotations

import asyncio
import os
import sys
import pytest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

from amprealize.execution_gateway_contracts import (
    ExecutionRequest,
    NewExecutionMode,
    OutputTarget,
    ResolvedExecution,
    SourceType,
)
from amprealize.source_providers import (
    BareGitSourceProvider,
    CloneResult,
    CloneSpec,
    CloneStrategy,
    GitHubSourceProvider,
    GitLabSourceProvider,
    LocalDirSourceProvider,
    SourceProvider,
    build_source_provider_registry,
    execute_clone,
    resolve_source_provider,
    _redact_url,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _make_resolved(
    *,
    source_type: SourceType = SourceType.GITHUB,
    source_url: Optional[str] = "owner/repo",
    source_ref: str = "main",
    mode: NewExecutionMode = NewExecutionMode.CONTAINER_ISOLATED,
    project_id: str = "proj-123",
    org_id: Optional[str] = "org-456",
    user_id: str = "user-789",
    workspace_path: Optional[str] = None,
) -> ResolvedExecution:
    """Build a minimal ResolvedExecution for testing."""
    request = ExecutionRequest(
        work_item_id="wi-001",
        project_id=project_id,
        org_id=org_id,
        user_id=user_id,
        surface="api",
        workspace_path=workspace_path,
    )
    return ResolvedExecution(
        run_id="run-test123",
        cycle_id="cycle-test456",
        request=request,
        mode=mode,
        output_target=OutputTarget.PULL_REQUEST,
        source_type=source_type,
        source_url=source_url,
        source_ref=source_ref,
        model_id="claude-sonnet-4-5",
        api_key="sk-test",
        credential_source="platform",
        is_byok=False,
        agent_id="agent-001",
    )


def _make_exec_fn(
    exit_code: int = 0,
    output: str = "ok",
    *,
    per_command: Optional[Dict[str, Tuple[str, int]]] = None,
) -> AsyncMock:
    """Create an async exec function mock.

    Args:
        exit_code: Default exit code.
        output: Default output.
        per_command: Optional dict mapping command substring -> (output, exit_code).
    """
    async def _exec(cmd: str) -> Tuple[str, int]:
        if per_command:
            for pattern, result in per_command.items():
                if pattern in cmd:
                    return result
        return output, exit_code

    mock = AsyncMock(side_effect=_exec)
    return mock


# =============================================================================
# GitHubSourceProvider
# =============================================================================


class TestGitHubSourceProvider:
    """Tests for GitHubSourceProvider."""

    def test_source_type(self):
        provider = GitHubSourceProvider()
        assert provider.source_type == SourceType.GITHUB

    def test_build_clone_spec_with_token(self):
        """Token from credential store is embedded in clone URL."""
        mock_store = MagicMock()
        mock_store.get_resolved_token.return_value = SimpleNamespace(
            token="ghp_test123", source="project_app",
        )
        provider = GitHubSourceProvider(github_credential_store=mock_store)
        resolved = _make_resolved(source_url="myorg/myrepo", source_ref="develop")

        spec = provider.build_clone_spec(resolved)

        assert spec.clone_url == "https://x-access-token:ghp_test123@github.com/myorg/myrepo.git"
        assert spec.ref == "develop"
        assert spec.strategy == CloneStrategy.SHALLOW
        assert spec.has_credentials is True
        assert spec.credential_source == "project_app"
        assert spec.source_type == SourceType.GITHUB
        assert spec.repo_identifier == "myorg/myrepo"

    def test_build_clone_spec_no_token(self):
        """No token -> unauthenticated HTTPS URL."""
        provider = GitHubSourceProvider()
        resolved = _make_resolved(source_url="public/repo")

        env = {k: v for k, v in os.environ.items()
               if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
        with patch.dict(os.environ, env, clear=True):
            spec = provider.build_clone_spec(resolved)

        assert spec.clone_url == "https://github.com/public/repo.git"
        assert spec.has_credentials is False

    @patch.dict(os.environ, {"GITHUB_TOKEN": "env_token_abc"})
    def test_build_clone_spec_env_fallback(self):
        """Falls back to GITHUB_TOKEN env var when no credential store."""
        provider = GitHubSourceProvider()
        resolved = _make_resolved(source_url="owner/repo")

        spec = provider.build_clone_spec(resolved)

        assert "env_token_abc" in spec.clone_url
        assert spec.credential_source == "platform"

    def test_build_clone_spec_sparse(self):
        """Sparse paths trigger SPARSE strategy."""
        provider = GitHubSourceProvider()
        resolved = _make_resolved(source_url="owner/monorepo")

        spec = provider.build_clone_spec(
            resolved,
            sparse_paths=["src/", "tests/"],
        )

        assert spec.strategy == CloneStrategy.SPARSE
        assert spec.sparse_paths == ["src/", "tests/"]

    def test_build_clone_spec_strategy_override(self):
        """Explicit strategy overrides the default."""
        provider = GitHubSourceProvider()
        resolved = _make_resolved(source_url="owner/repo")

        spec = provider.build_clone_spec(resolved, strategy=CloneStrategy.FULL)
        assert spec.strategy == CloneStrategy.FULL

    def test_build_clone_spec_missing_url(self):
        """Raises ValueError if source_url is missing."""
        provider = GitHubSourceProvider()
        resolved = _make_resolved(source_url=None)

        with pytest.raises(ValueError, match="source_url is required"):
            provider.build_clone_spec(resolved)

    def test_token_resolution_failure_falls_through(self):
        """If credential store throws, returns no token."""
        mock_store = MagicMock()
        mock_store.get_resolved_token.side_effect = RuntimeError("DB down")
        provider = GitHubSourceProvider(github_credential_store=mock_store)
        resolved = _make_resolved(source_url="owner/repo")

        env = {k: v for k, v in os.environ.items()
               if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
        with patch.dict(os.environ, env, clear=True):
            spec = provider.build_clone_spec(resolved)

        assert spec.has_credentials is False

    def test_protocol_compliance(self):
        """GitHubSourceProvider satisfies SourceProvider protocol."""
        assert isinstance(GitHubSourceProvider(), SourceProvider)


# =============================================================================
# GitLabSourceProvider
# =============================================================================


class TestGitLabSourceProvider:
    """Tests for GitLabSourceProvider."""

    def test_source_type(self):
        provider = GitLabSourceProvider()
        assert provider.source_type == SourceType.GITLAB

    def test_build_clone_spec_bare_path(self):
        """Bare group/project path uses default host."""
        provider = GitLabSourceProvider(default_host="gitlab.com")
        resolved = _make_resolved(
            source_type=SourceType.GITLAB,
            source_url="mygroup/myproject",
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.clone_url == "https://gitlab.com/mygroup/myproject.git"
        assert spec.source_type == SourceType.GITLAB

    def test_build_clone_spec_full_url(self):
        """Full HTTPS URL is parsed correctly."""
        provider = GitLabSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.GITLAB,
            source_url="https://gitlab.example.com/team/project.git",
        )

        spec = provider.build_clone_spec(resolved)

        assert "gitlab.example.com" in spec.clone_url
        assert "team/project" in spec.clone_url

    def test_build_clone_spec_self_hosted(self):
        """Host prefix without scheme is handled."""
        provider = GitLabSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.GITLAB,
            source_url="git.internal.co/team/repo",
        )

        spec = provider.build_clone_spec(resolved)

        assert "git.internal.co" in spec.clone_url
        assert "team/repo" in spec.clone_url

    def test_build_clone_spec_with_token(self):
        """Token is embedded as oauth2 in clone URL."""
        mock_store = MagicMock()
        mock_store.get_gitlab_token.return_value = ("glpat-abc123", "org_pat")
        provider = GitLabSourceProvider(credential_store=mock_store)
        resolved = _make_resolved(
            source_type=SourceType.GITLAB,
            source_url="group/project",
        )

        spec = provider.build_clone_spec(resolved)

        assert "oauth2:glpat-abc123@" in spec.clone_url
        assert spec.has_credentials is True

    @patch.dict(os.environ, {"GITLAB_TOKEN": "gl_env_token"})
    def test_build_clone_spec_env_fallback(self):
        """Falls back to GITLAB_TOKEN env var."""
        provider = GitLabSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.GITLAB,
            source_url="group/project",
        )

        spec = provider.build_clone_spec(resolved)

        assert "gl_env_token" in spec.clone_url
        assert spec.credential_source == "platform"

    def test_build_clone_spec_missing_url(self):
        provider = GitLabSourceProvider()
        resolved = _make_resolved(source_type=SourceType.GITLAB, source_url=None)

        with pytest.raises(ValueError, match="source_url is required"):
            provider.build_clone_spec(resolved)

    def test_protocol_compliance(self):
        assert isinstance(GitLabSourceProvider(), SourceProvider)


# =============================================================================
# BareGitSourceProvider
# =============================================================================


class TestBareGitSourceProvider:
    """Tests for BareGitSourceProvider."""

    def test_source_type(self):
        assert BareGitSourceProvider().source_type == SourceType.BARE_GIT

    def test_build_clone_spec_https(self):
        provider = BareGitSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.BARE_GIT,
            source_url="https://example.com/repo.git",
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.clone_url == "https://example.com/repo.git"
        assert spec.strategy == CloneStrategy.SHALLOW
        assert spec.has_credentials is False

    def test_build_clone_spec_ssh(self):
        provider = BareGitSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.BARE_GIT,
            source_url="git@github.com:owner/repo.git",
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.clone_url == "git@github.com:owner/repo.git"
        assert spec.has_credentials is False  # SSH uses keys, not URL creds

    def test_build_clone_spec_with_embedded_creds(self):
        provider = BareGitSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.BARE_GIT,
            source_url="https://user:pass@example.com/repo.git",
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.has_credentials is True
        assert spec.credential_source == "url"
        # repo_identifier should be redacted
        assert "pass" not in spec.repo_identifier

    def test_build_clone_spec_missing_url(self):
        provider = BareGitSourceProvider()
        resolved = _make_resolved(source_type=SourceType.BARE_GIT, source_url=None)

        with pytest.raises(ValueError, match="source_url is required"):
            provider.build_clone_spec(resolved)

    def test_protocol_compliance(self):
        assert isinstance(BareGitSourceProvider(), SourceProvider)


# =============================================================================
# LocalDirSourceProvider
# =============================================================================


class TestLocalDirSourceProvider:
    """Tests for LocalDirSourceProvider."""

    def test_source_type(self):
        assert LocalDirSourceProvider().source_type == SourceType.LOCAL_DIR

    def test_build_clone_spec_connected_mount(self, tmp_path):
        """CONTAINER_CONNECTED mode uses MOUNT strategy."""
        provider = LocalDirSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.LOCAL_DIR,
            source_url=str(tmp_path),
            mode=NewExecutionMode.CONTAINER_CONNECTED,
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.strategy == CloneStrategy.MOUNT
        assert spec.clone_url == str(tmp_path.resolve())

    def test_build_clone_spec_isolated_copy(self, tmp_path):
        """CONTAINER_ISOLATED mode uses COPY strategy for local dirs."""
        provider = LocalDirSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.LOCAL_DIR,
            source_url=str(tmp_path),
            mode=NewExecutionMode.CONTAINER_ISOLATED,
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.strategy == CloneStrategy.COPY

    def test_build_clone_spec_local_direct(self, tmp_path):
        """LOCAL_DIRECT mode uses MOUNT strategy (no-op path reference)."""
        provider = LocalDirSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.LOCAL_DIR,
            source_url=str(tmp_path),
            mode=NewExecutionMode.LOCAL_DIRECT,
        )

        spec = provider.build_clone_spec(resolved)

        assert spec.strategy == CloneStrategy.MOUNT

    def test_build_clone_spec_from_workspace_path(self, tmp_path):
        """Falls back to workspace_path if source_url is None."""
        provider = LocalDirSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.LOCAL_DIR,
            source_url=None,
            workspace_path=str(tmp_path),
            mode=NewExecutionMode.LOCAL_DIRECT,
        )

        spec = provider.build_clone_spec(resolved)

        assert str(tmp_path.resolve()) in spec.clone_url

    def test_build_clone_spec_missing_path(self):
        """Raises ValueError if no path available."""
        provider = LocalDirSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.LOCAL_DIR,
            source_url=None,
            workspace_path=None,
        )

        with pytest.raises(ValueError, match="source_url or workspace_path"):
            provider.build_clone_spec(resolved)

    def test_build_clone_spec_nonexistent(self):
        """Raises ValueError if path doesn't exist."""
        provider = LocalDirSourceProvider()
        resolved = _make_resolved(
            source_type=SourceType.LOCAL_DIR,
            source_url="/nonexistent/path/abc123",
        )

        with pytest.raises(ValueError, match="does not exist"):
            provider.build_clone_spec(resolved)

    def test_protocol_compliance(self):
        assert isinstance(LocalDirSourceProvider(), SourceProvider)


# =============================================================================
# execute_clone
# =============================================================================


class TestExecuteClone:
    """Tests for the execute_clone function."""

    @pytest.mark.asyncio
    async def test_shallow_clone_success(self):
        """Shallow clone runs git clone --depth 1 and succeeds."""
        exec_fn = _make_exec_fn(exit_code=0, output="Cloning into...")
        spec = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.SHALLOW,
            target_dir="/workspace/repo",
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is True
        assert result.workspace_path == "/workspace/repo"
        assert result.strategy_used == CloneStrategy.SHALLOW
        exec_fn.assert_called_once()
        cmd = exec_fn.call_args[0][0]
        assert "--depth" in cmd
        assert "1" in cmd

    @pytest.mark.asyncio
    async def test_full_clone_success(self):
        """Full clone does not use --depth."""
        exec_fn = _make_exec_fn(exit_code=0)
        spec = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.FULL,
            target_dir="/workspace/repo",
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is True
        cmd = exec_fn.call_args[0][0]
        assert "--depth" not in cmd

    @pytest.mark.asyncio
    async def test_clone_failure(self):
        """Failed clone returns error."""
        exec_fn = _make_exec_fn(exit_code=128, output="fatal: repo not found")
        spec = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.SHALLOW,
            target_dir="/workspace/repo",
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is False
        assert result.error is not None
        assert "clone failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_mount_strategy_noop(self):
        """MOUNT strategy returns immediately without running commands."""
        exec_fn = _make_exec_fn()
        spec = CloneSpec(
            clone_url="/local/path",
            ref="local",
            strategy=CloneStrategy.MOUNT,
            target_dir="/local/path",
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is True
        assert result.strategy_used == CloneStrategy.MOUNT
        exec_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_copy_strategy(self):
        """COPY strategy runs cp -a."""
        exec_fn = _make_exec_fn(exit_code=0)
        spec = CloneSpec(
            clone_url="/local/source",
            ref="local",
            strategy=CloneStrategy.COPY,
            target_dir="/workspace/repo",
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is True
        assert result.strategy_used == CloneStrategy.COPY
        cmd = exec_fn.call_args[0][0]
        assert "cp -a" in cmd

    @pytest.mark.asyncio
    async def test_sparse_clone_success(self):
        """Sparse checkout runs multi-step git commands."""
        exec_fn = _make_exec_fn(exit_code=0)
        spec = CloneSpec(
            clone_url="https://github.com/owner/monorepo.git",
            ref="main",
            strategy=CloneStrategy.SPARSE,
            target_dir="/workspace/repo",
            sparse_paths=["src/", "lib/"],
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is True
        assert result.strategy_used == CloneStrategy.SPARSE
        # Should have been called 4 times: clone, init, set, checkout
        assert exec_fn.call_count == 4

    @pytest.mark.asyncio
    async def test_sparse_clone_no_paths_fallback(self):
        """Sparse with no paths falls back to shallow."""
        exec_fn = _make_exec_fn(exit_code=0)
        spec = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.SPARSE,
            target_dir="/workspace/repo",
            sparse_paths=[],
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is True
        # Falls back to shallow, only one command
        assert exec_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_sparse_clone_init_failure(self):
        """Sparse checkout fails if init step fails."""
        exec_fn = _make_exec_fn(
            exit_code=0,
            per_command={
                "sparse-checkout init": ("error: not a git repo", 1),
            },
        )
        spec = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.SPARSE,
            target_dir="/workspace/repo",
            sparse_paths=["src/"],
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is False
        assert result.error is not None
        assert "sparse-checkout init failed" in result.error

    @pytest.mark.asyncio
    async def test_credential_redaction_on_failure(self):
        """Credentials in clone URL are redacted in error messages."""
        exec_fn = _make_exec_fn(
            exit_code=128,
            output="fatal: https://x-access-token:ghp_secret@github.com/o/r.git not found",
        )
        spec = CloneSpec(
            clone_url="https://x-access-token:ghp_secret@github.com/o/r.git",
            ref="main",
            strategy=CloneStrategy.SHALLOW,
            target_dir="/workspace/repo",
            has_credentials=True,
        )

        result = await execute_clone(spec, exec_fn=exec_fn)

        assert result.success is False
        # Token should be redacted
        assert result.error is not None
        assert "ghp_secret" not in result.error


# =============================================================================
# Provider Registry
# =============================================================================


class TestProviderRegistry:
    """Tests for build_source_provider_registry and resolve_source_provider."""

    def test_build_registry_has_all_types(self):
        """Registry includes all 4 provider types."""
        registry = build_source_provider_registry()

        assert SourceType.GITHUB in registry
        assert SourceType.GITLAB in registry
        assert SourceType.BARE_GIT in registry
        assert SourceType.LOCAL_DIR in registry

    def test_resolve_github(self):
        registry = build_source_provider_registry()
        provider = resolve_source_provider(SourceType.GITHUB, provider_registry=registry)

        assert provider is not None
        assert provider.source_type == SourceType.GITHUB

    def test_resolve_unknown_type(self):
        """Unregistered SourceType returns None."""
        registry = build_source_provider_registry()
        provider = resolve_source_provider(
            SourceType.BITBUCKET, provider_registry=registry,
        )

        assert provider is None

    def test_resolve_with_no_registry(self):
        """None registry returns None."""
        provider = resolve_source_provider(SourceType.GITHUB, provider_registry=None)
        assert provider is None

    def test_credential_stores_wired(self):
        """Credential stores are passed through to providers."""
        mock_gh = MagicMock()
        mock_gl = MagicMock()
        registry = build_source_provider_registry(
            github_credential_store=mock_gh,
            gitlab_credential_store=mock_gl,
        )

        gh_provider: GitHubSourceProvider = registry[SourceType.GITHUB]  # type: ignore[assignment]
        gl_provider: GitLabSourceProvider = registry[SourceType.GITLAB]  # type: ignore[assignment]

        assert gh_provider._cred_store is mock_gh
        assert gl_provider._cred_store is mock_gl


# =============================================================================
# Helpers
# =============================================================================


class TestHelpers:
    """Tests for helper functions."""

    def test_redact_url_with_credentials(self):
        text = "fatal: https://x-access-token:secret123@github.com/o/r.git"
        url = "https://x-access-token:secret123@github.com/o/r.git"

        result = _redact_url(text, url)

        assert "secret123" not in result
        assert "***" in result

    def test_redact_url_no_credentials(self):
        text = "Cloning into /workspace..."
        url = "https://github.com/o/r.git"

        result = _redact_url(text, url)

        assert result == text  # Unchanged

    def test_redact_url_oauth2(self):
        text = "failed: https://oauth2:glpat-xyz@gitlab.com/g/p.git"
        url = "https://oauth2:glpat-xyz@gitlab.com/g/p.git"

        result = _redact_url(text, url)

        assert "glpat-xyz" not in result


# =============================================================================
# Executor Integration (ContainerIsolatedExecutor with SourceProviders)
# =============================================================================


class TestExecutorSourceProviderIntegration:
    """Test that ContainerIsolatedExecutor uses SourceProviders correctly."""

    @pytest.mark.asyncio
    async def test_provision_uses_source_provider(self):
        """When a source provider is registered, it's used instead of legacy path."""
        from amprealize.mode_executors import ContainerIsolatedExecutor

        # Mock orchestrator
        mock_orch = AsyncMock()
        mock_info = SimpleNamespace(
            run_id="run-123",
            workspace_path="/workspace",
            container_id="ctr-abc",
        )
        mock_orch.provision_workspace.return_value = mock_info
        mock_orch.exec_in_workspace.return_value = ("ok", 0)

        # Mock source provider
        mock_provider = MagicMock(spec=SourceProvider)
        mock_provider.source_type = SourceType.GITHUB
        mock_provider.build_clone_spec.return_value = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.SHALLOW,
            target_dir="/workspace/repo",
            source_type=SourceType.GITHUB,
            repo_identifier="owner/repo",
        )

        executor = ContainerIsolatedExecutor(
            mock_orch,
            source_providers={SourceType.GITHUB: mock_provider},
        )

        resolved = _make_resolved(source_url="owner/repo")

        # Mock the lazy WorkspaceConfig import inside _provision_with_provider
        mock_wsc = MagicMock()
        with patch.dict("sys.modules", {"breakeramp": MagicMock(WorkspaceConfig=mock_wsc)}):
            result = await executor.provision_workspace(resolved)

        # Verify source provider was called
        mock_provider.build_clone_spec.assert_called_once()
        # Verify exec_in_workspace was called for the clone
        mock_orch.exec_in_workspace.assert_called()
        # Verify workspace was populated
        assert result.workspace_id == "run-123"
        assert result.container_id == "ctr-abc"

    @pytest.mark.asyncio
    async def test_provision_legacy_fallback(self):
        """When no source provider is registered, falls back to legacy."""
        from amprealize.mode_executors import ContainerIsolatedExecutor

        mock_orch = AsyncMock()
        mock_info = SimpleNamespace(
            run_id="run-123",
            workspace_path="/workspace",
            container_id="ctr-abc",
        )
        mock_orch.provision_workspace.return_value = mock_info

        # No source providers registered
        executor = ContainerIsolatedExecutor(mock_orch)

        resolved = _make_resolved(source_url="owner/repo")

        mock_wsc = MagicMock()
        with patch("amprealize.mode_executors.resolve_source_provider", return_value=None), \
             patch.dict("sys.modules", {"breakeramp": MagicMock(WorkspaceConfig=mock_wsc)}):
            result = await executor.provision_workspace(resolved)

        assert result.workspace_id == "run-123"
        # Legacy path uses orchestrator's built-in clone
        mock_orch.provision_workspace.assert_called_once()

    @pytest.mark.asyncio
    async def test_provision_clone_failure_non_fatal(self):
        """Clone failure during provisioning doesn't crash the executor."""
        from amprealize.mode_executors import ContainerIsolatedExecutor

        mock_orch = AsyncMock()
        mock_info = SimpleNamespace(
            run_id="run-123",
            workspace_path="/workspace",
            container_id="ctr-abc",
        )
        mock_orch.provision_workspace.return_value = mock_info
        mock_orch.exec_in_workspace.return_value = ("fatal: not found", 128)

        mock_provider = MagicMock(spec=SourceProvider)
        mock_provider.source_type = SourceType.GITHUB
        mock_provider.build_clone_spec.return_value = CloneSpec(
            clone_url="https://github.com/owner/repo.git",
            ref="main",
            strategy=CloneStrategy.SHALLOW,
            target_dir="/workspace/repo",
            source_type=SourceType.GITHUB,
        )

        executor = ContainerIsolatedExecutor(
            mock_orch,
            source_providers={SourceType.GITHUB: mock_provider},
        )
        resolved = _make_resolved(source_url="owner/repo")

        # Should not raise — clone failure is non-fatal
        mock_wsc = MagicMock()
        with patch.dict("sys.modules", {"breakeramp": MagicMock(WorkspaceConfig=mock_wsc)}):
            result = await executor.provision_workspace(resolved)
        assert result.workspace_id == "run-123"
