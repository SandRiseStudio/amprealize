"""Tests for the output_handlers package.

Covers: OutputContext, OutputResult, GitHubPRHandler, GitLabMRHandler,
PatchFileHandler, LocalSyncHandler, and handler registry.

Part of E3 — Agent Execution Loop Rearchitecture (Phase 4 / S3.8).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amprealize.output_handlers import (
    GitHubPRHandler,
    GitLabMRHandler,
    LocalSyncHandler,
    OutputContext,
    OutputHandler,
    OutputResult,
    OutputStatus,
    PatchFileHandler,
    get_handler_class,
)
from amprealize.output_handlers.base import FileChange

# Mark all tests as unit tests
pytestmark = pytest.mark.unit


# =========================================================================
# Helpers
# =========================================================================


def _make_context(**overrides) -> OutputContext:
    """Create a minimal OutputContext for testing."""
    defaults = {
        "run_id": "run-test-001",
        "work_item_id": "wi-test-001",
        "work_item_title": "Fix broken tests",
        "repo": "owner/repo",
        "base_branch": "main",
        "branch_name": "amprealize/fix-broken-tests",
        "project_id": "proj-test",
        "org_id": "org-test",
    }
    defaults.update(overrides)
    return OutputContext(**defaults)


def _add_sample_changes(ctx: OutputContext) -> None:
    """Add a few sample file changes to the context."""
    ctx.add_change("src/app.py", 'print("hello")\n', "create", phase="executing")
    ctx.add_change("README.md", "# Updated\n", "update", phase="executing", original_content="# Old\n")
    ctx.add_change("old_file.py", None, "delete", phase="executing", original_content="# remove\n")


# =========================================================================
# FileChange tests
# =========================================================================


class TestFileChange:
    def test_is_deletion(self):
        fc = FileChange(path="x.py", content=None, action="delete")
        assert fc.is_deletion() is True

    def test_is_not_deletion(self):
        fc = FileChange(path="x.py", content="code", action="create")
        assert fc.is_deletion() is False

    def test_defaults(self):
        fc = FileChange(path="x.py", content="ok", action="update")
        assert fc.phase == ""
        assert fc.encoding == "utf-8"
        assert fc.original_content is None


# =========================================================================
# OutputContext tests
# =========================================================================


class TestOutputContext:
    def test_add_change_basic(self):
        ctx = _make_context()
        ctx.add_change("src/a.py", "content", "create")
        assert ctx.has_changes() is True
        assert len(ctx.changes) == 1
        assert ctx.changes[0].path == "src/a.py"
        assert ctx.changes[0].action == "create"

    def test_add_change_merges_same_path(self):
        ctx = _make_context()
        ctx.add_change("src/a.py", "v1", "create")
        ctx.add_change("src/a.py", "v2", "update")
        assert len(ctx.changes) == 1
        assert ctx.changes[0].content == "v2"
        assert ctx.changes[0].action == "update"

    def test_add_change_preserves_original_content(self):
        ctx = _make_context()
        ctx.add_change("src/a.py", "v1", "create", original_content="orig")
        ctx.add_change("src/a.py", "v2", "update")
        # Original content is preserved from first add
        assert ctx.changes[0].original_content == "orig"

    def test_has_changes_empty(self):
        ctx = _make_context()
        assert ctx.has_changes() is False

    def test_changes_summary(self):
        ctx = _make_context()
        _add_sample_changes(ctx)
        summary = ctx.changes_summary()
        assert summary == {"create": 1, "update": 1, "delete": 1}

    def test_changes_summary_empty(self):
        ctx = _make_context()
        assert ctx.changes_summary() == {"create": 0, "update": 0, "delete": 0}


# =========================================================================
# OutputResult tests
# =========================================================================


class TestOutputResult:
    def test_to_dict_minimal(self):
        r = OutputResult(
            status=OutputStatus.SUCCESS,
            handler_type="test",
            files_changed=3,
            message="OK",
        )
        d = r.to_dict()
        assert d["status"] == "success"
        assert d["handler_type"] == "test"
        assert d["files_changed"] == 3
        assert "pr_url" not in d
        assert "artifact_path" not in d

    def test_to_dict_with_pr_fields(self):
        r = OutputResult(
            status=OutputStatus.SUCCESS,
            handler_type="github_pr",
            files_changed=2,
            message="Created",
            pr_url="https://github.com/o/r/pull/1",
            pr_number=1,
            branch_name="fix/test",
            commit_sha="abc123",
        )
        d = r.to_dict()
        assert d["pr_url"] == "https://github.com/o/r/pull/1"
        assert d["pr_number"] == 1

    def test_to_dict_with_artifact_fields(self):
        r = OutputResult(
            status=OutputStatus.SUCCESS,
            handler_type="patch_file",
            artifact_path="/tmp/test.patch",
            artifact_size_bytes=1234,
        )
        d = r.to_dict()
        assert d["artifact_path"] == "/tmp/test.patch"
        assert d["artifact_size_bytes"] == 1234

    def test_to_dict_with_error(self):
        r = OutputResult(
            status=OutputStatus.FAILED,
            handler_type="test",
            error="Something went wrong",
        )
        d = r.to_dict()
        assert d["error"] == "Something went wrong"


# =========================================================================
# Protocol compliance
# =========================================================================


class TestProtocolCompliance:
    """Verify all handlers satisfy the OutputHandler protocol."""

    def test_github_pr_handler_is_output_handler(self):
        handler = GitHubPRHandler(github_service=MagicMock())
        assert isinstance(handler, OutputHandler)

    def test_gitlab_mr_handler_is_output_handler(self):
        handler = GitLabMRHandler(token="fake-token")
        assert isinstance(handler, OutputHandler)

    def test_patch_file_handler_is_output_handler(self):
        handler = PatchFileHandler()
        assert isinstance(handler, OutputHandler)

    def test_local_sync_handler_is_output_handler(self):
        handler = LocalSyncHandler()
        assert isinstance(handler, OutputHandler)


# =========================================================================
# Handler registry
# =========================================================================


class TestHandlerRegistry:
    def test_pull_request_maps_to_github(self):
        assert get_handler_class("pull_request") is GitHubPRHandler

    def test_patch_file_maps_to_patch(self):
        assert get_handler_class("patch_file") is PatchFileHandler

    def test_local_sync_maps_to_local(self):
        assert get_handler_class("local_sync") is LocalSyncHandler

    def test_unknown_returns_none(self):
        assert get_handler_class("ftp_upload") is None

    def test_archive_not_yet_registered(self):
        assert get_handler_class("archive") is None


# =========================================================================
# GitHubPRHandler tests
# =========================================================================


class TestGitHubPRHandler:
    def test_handler_type(self):
        handler = GitHubPRHandler(github_service=MagicMock())
        assert handler.handler_type == "github_pr"

    @pytest.mark.asyncio
    async def test_deliver_no_changes(self):
        handler = GitHubPRHandler(github_service=MagicMock())
        ctx = _make_context()
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.NO_CHANGES

    @pytest.mark.asyncio
    async def test_deliver_missing_repo(self):
        handler = GitHubPRHandler(github_service=MagicMock())
        ctx = _make_context(repo="")
        ctx.add_change("x.py", "code", "create")
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.FAILED
        assert "repository" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deliver_missing_branch(self):
        handler = GitHubPRHandler(github_service=MagicMock())
        ctx = _make_context(branch_name="")
        ctx.add_change("x.py", "code", "create")
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.FAILED
        assert "branch" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deliver_success(self):
        mock_gh = MagicMock()
        mock_pr_result = MagicMock()
        mock_pr_result.success = True
        mock_pr_result.pr_url = "https://github.com/o/r/pull/42"
        mock_pr_result.pr_number = 42
        mock_pr_result.files_changed = 2
        mock_pr_result.commit_sha = "abc123"
        mock_gh.create_pull_request.return_value = mock_pr_result

        handler = GitHubPRHandler(github_service=mock_gh)
        ctx = _make_context()
        _add_sample_changes(ctx)
        ctx.summary = "Fixed things"

        result = await handler.deliver(ctx)

        assert result.status == OutputStatus.SUCCESS
        assert result.pr_url == "https://github.com/o/r/pull/42"
        assert result.pr_number == 42
        assert result.files_changed == 2
        assert result.commit_sha == "abc123"
        assert result.branch_name == "amprealize/fix-broken-tests"

        # Verify create_pull_request was called with correct args
        call_kwargs = mock_gh.create_pull_request.call_args
        assert call_kwargs.kwargs["repo"] == "owner/repo"
        assert call_kwargs.kwargs["head_branch"] == "amprealize/fix-broken-tests"
        assert call_kwargs.kwargs["base_branch"] == "main"
        assert len(call_kwargs.kwargs["files"]) == 3

    @pytest.mark.asyncio
    async def test_deliver_pr_creation_fails(self):
        mock_gh = MagicMock()
        mock_pr_result = MagicMock()
        mock_pr_result.success = False
        mock_pr_result.error = "Merge conflict"
        mock_gh.create_pull_request.return_value = mock_pr_result

        handler = GitHubPRHandler(github_service=mock_gh)
        ctx = _make_context()
        ctx.add_change("x.py", "code", "create")

        result = await handler.deliver(ctx)

        assert result.status == OutputStatus.FAILED
        assert "Merge conflict" in result.error

    @pytest.mark.asyncio
    async def test_deliver_catches_exceptions(self):
        mock_gh = MagicMock()
        mock_gh.create_pull_request.side_effect = RuntimeError("Network error")

        handler = GitHubPRHandler(github_service=mock_gh)
        ctx = _make_context()
        ctx.add_change("x.py", "code", "create")

        result = await handler.deliver(ctx)

        assert result.status == OutputStatus.FAILED
        assert "Network error" in result.error

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self):
        handler = GitHubPRHandler(github_service=MagicMock())
        ctx = _make_context()
        await handler.cleanup(ctx)  # Should not raise


# =========================================================================
# GitLabMRHandler tests
# =========================================================================


class TestGitLabMRHandler:
    def test_handler_type(self):
        handler = GitLabMRHandler(token="fake")
        assert handler.handler_type == "gitlab_mr"

    @pytest.mark.asyncio
    async def test_deliver_no_changes(self):
        handler = GitLabMRHandler(token="fake")
        ctx = _make_context()
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.NO_CHANGES

    @pytest.mark.asyncio
    async def test_deliver_missing_repo(self):
        handler = GitLabMRHandler(token="fake")
        ctx = _make_context(repo="")
        ctx.add_change("x.py", "code", "create")
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.FAILED

    @pytest.mark.asyncio
    async def test_deliver_missing_branch(self):
        handler = GitLabMRHandler(token="fake")
        ctx = _make_context(branch_name="")
        ctx.add_change("x.py", "code", "create")
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.FAILED

    @pytest.mark.asyncio
    async def test_deliver_success(self):
        """Test successful MR creation with mocked httpx."""
        handler = GitLabMRHandler(token="fake-token", base_url="https://gitlab.example.com")
        ctx = _make_context(repo="group/project")
        _add_sample_changes(ctx)
        ctx.summary = "Fixed issues"

        # Mock all three API calls
        import httpx

        branch_response = MagicMock(status_code=201)
        commit_response = MagicMock(status_code=201)
        commit_response.json.return_value = {"id": "sha456"}
        mr_response = MagicMock(status_code=201)
        mr_response.json.return_value = {
            "web_url": "https://gitlab.example.com/group/project/-/merge_requests/10",
            "iid": 10,
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[branch_response, commit_response, mr_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("amprealize.output_handlers.gitlab_mr.httpx.AsyncClient", return_value=mock_client):
            result = await handler.deliver(ctx)

        assert result.status == OutputStatus.SUCCESS
        assert result.pr_number == 10
        assert result.commit_sha == "sha456"
        assert "merge_requests/10" in result.pr_url

    @pytest.mark.asyncio
    async def test_deliver_branch_creation_failure(self):
        handler = GitLabMRHandler(token="fake")
        ctx = _make_context()
        ctx.add_change("x.py", "code", "create")

        branch_response = MagicMock(status_code=500, text="Internal Server Error")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=branch_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("amprealize.output_handlers.gitlab_mr.httpx.AsyncClient", return_value=mock_client):
            result = await handler.deliver(ctx)

        assert result.status == OutputStatus.FAILED
        assert "branch" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deliver_commit_partial_on_mr_failure(self):
        """Commit succeeds but MR creation fails -> PARTIAL status."""
        handler = GitLabMRHandler(token="fake")
        ctx = _make_context()
        ctx.add_change("x.py", "code", "create")

        branch_resp = MagicMock(status_code=201)
        commit_resp = MagicMock(status_code=201)
        commit_resp.json.return_value = {"id": "sha789"}
        mr_resp = MagicMock(status_code=422, text="Duplicate MR")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[branch_resp, commit_resp, mr_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("amprealize.output_handlers.gitlab_mr.httpx.AsyncClient", return_value=mock_client):
            result = await handler.deliver(ctx)

        assert result.status == OutputStatus.PARTIAL
        assert result.commit_sha == "sha789"

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self):
        handler = GitLabMRHandler(token="fake")
        await handler.cleanup(_make_context())

    def test_build_commit_actions(self):
        changes = [
            FileChange(path="a.py", content="new", action="create"),
            FileChange(path="b.py", content="upd", action="update"),
            FileChange(path="c.py", content=None, action="delete"),
        ]
        actions = GitLabMRHandler._build_commit_actions(changes)
        assert len(actions) == 3
        assert actions[0]["action"] == "create"
        assert actions[0]["file_path"] == "a.py"
        assert actions[1]["action"] == "update"
        assert actions[2]["action"] == "delete"
        assert "content" not in actions[2]  # No content for deletes


# =========================================================================
# PatchFileHandler tests
# =========================================================================


class TestPatchFileHandler:
    def test_handler_type(self):
        handler = PatchFileHandler()
        assert handler.handler_type == "patch_file"

    @pytest.mark.asyncio
    async def test_deliver_no_changes(self):
        handler = PatchFileHandler()
        ctx = _make_context()
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.NO_CHANGES

    @pytest.mark.asyncio
    async def test_deliver_creates_patch_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PatchFileHandler(default_output_dir=tmpdir)
            ctx = _make_context()
            _add_sample_changes(ctx)

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert result.files_changed == 3
            assert result.artifact_path is not None
            assert os.path.exists(result.artifact_path)
            assert result.artifact_size_bytes > 0

            # Verify patch content
            with open(result.artifact_path, "r") as f:
                content = f.read()
            assert "src/app.py" in content
            assert "README.md" in content
            assert "old_file.py" in content

    @pytest.mark.asyncio
    async def test_deliver_uses_context_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PatchFileHandler()
            ctx = _make_context(output_dir=tmpdir)
            ctx.add_change("x.py", "code\n", "create")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert result.artifact_path.startswith(tmpdir)

    @pytest.mark.asyncio
    async def test_deliver_creates_temp_dir_if_none(self):
        handler = PatchFileHandler()  # No default_output_dir
        ctx = _make_context()
        ctx.add_change("x.py", "code\n", "create")

        result = await handler.deliver(ctx)

        assert result.status == OutputStatus.SUCCESS
        assert result.artifact_path is not None
        # Clean up temp file
        os.remove(result.artifact_path)

    @pytest.mark.asyncio
    async def test_patch_content_create(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PatchFileHandler(default_output_dir=tmpdir)
            ctx = _make_context()
            ctx.add_change("new.py", "line1\nline2\n", "create")

            result = await handler.deliver(ctx)

            with open(result.artifact_path, "r") as f:
                content = f.read()
            assert "+line1" in content
            assert "+line2" in content
            assert "a/new.py" in content
            assert "b/new.py" in content

    @pytest.mark.asyncio
    async def test_patch_content_update(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PatchFileHandler(default_output_dir=tmpdir)
            ctx = _make_context()
            ctx.add_change("file.py", "new content\n", "update", original_content="old content\n")

            result = await handler.deliver(ctx)

            with open(result.artifact_path, "r") as f:
                content = f.read()
            assert "-old content" in content
            assert "+new content" in content

    @pytest.mark.asyncio
    async def test_patch_content_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = PatchFileHandler(default_output_dir=tmpdir)
            ctx = _make_context()
            ctx.add_change("old.py", None, "delete", original_content="removed\n")

            result = await handler.deliver(ctx)

            with open(result.artifact_path, "r") as f:
                content = f.read()
            assert "-removed" in content
            assert "a/old.py" in content

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self):
        handler = PatchFileHandler()
        await handler.cleanup(_make_context())


# =========================================================================
# LocalSyncHandler tests
# =========================================================================


class TestLocalSyncHandler:
    def test_handler_type(self):
        handler = LocalSyncHandler()
        assert handler.handler_type == "local_sync"

    @pytest.mark.asyncio
    async def test_deliver_no_changes(self):
        handler = LocalSyncHandler()
        ctx = _make_context()
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.NO_CHANGES

    @pytest.mark.asyncio
    async def test_deliver_missing_workspace_path(self):
        handler = LocalSyncHandler()
        ctx = _make_context(workspace_path=None)
        ctx.add_change("x.py", "code", "create")
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.FAILED
        assert "workspace_path" in result.error

    @pytest.mark.asyncio
    async def test_deliver_nonexistent_workspace(self):
        handler = LocalSyncHandler()
        ctx = _make_context(workspace_path="/nonexistent/path/12345")
        ctx.add_change("x.py", "code", "create")
        result = await handler.deliver(ctx)
        assert result.status == OutputStatus.FAILED
        assert "does not exist" in result.error

    @pytest.mark.asyncio
    async def test_deliver_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            ctx.add_change("src/app.py", 'print("hello")\n', "create")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert result.files_changed == 1
            target = os.path.join(tmpdir, "src", "app.py")
            assert os.path.exists(target)
            with open(target) as f:
                assert f.read() == 'print("hello")\n'

    @pytest.mark.asyncio
    async def test_deliver_updates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create existing file
            target = os.path.join(tmpdir, "file.py")
            with open(target, "w") as f:
                f.write("old\n")

            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            ctx.add_change("file.py", "new\n", "update")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            with open(target) as f:
                assert f.read() == "new\n"

    @pytest.mark.asyncio
    async def test_deliver_deletes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "old.py")
            with open(target, "w") as f:
                f.write("delete me\n")

            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            ctx.add_change("old.py", None, "delete")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert not os.path.exists(target)

    @pytest.mark.asyncio
    async def test_deliver_delete_nonexistent_file(self):
        """Deleting a file that doesn't exist should still succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            ctx.add_change("ghost.py", None, "delete")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert result.files_changed == 1

    @pytest.mark.asyncio
    async def test_deliver_multiple_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            _add_sample_changes(ctx)

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert result.files_changed == 3
            assert os.path.exists(os.path.join(tmpdir, "src", "app.py"))
            assert os.path.exists(os.path.join(tmpdir, "README.md"))

    @pytest.mark.asyncio
    async def test_path_traversal_prevented(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            ctx.add_change("../../etc/passwd", "hacked", "create")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.FAILED
            assert not os.path.exists("/etc/passwd_hacked")

    @pytest.mark.asyncio
    async def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LocalSyncHandler(dry_run=True)
            ctx = _make_context(workspace_path=tmpdir)
            ctx.add_change("test.py", "code", "create")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            assert not os.path.exists(os.path.join(tmpdir, "test.py"))

    @pytest.mark.asyncio
    async def test_deliver_base64_content(self):
        import base64

        with tempfile.TemporaryDirectory() as tmpdir:
            handler = LocalSyncHandler()
            ctx = _make_context(workspace_path=tmpdir)
            encoded = base64.b64encode(b"binary data").decode("ascii")
            ctx.add_change("data.bin", encoded, "create", encoding="base64")

            result = await handler.deliver(ctx)

            assert result.status == OutputStatus.SUCCESS
            with open(os.path.join(tmpdir, "data.bin"), "rb") as f:
                assert f.read() == b"binary data"

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self):
        handler = LocalSyncHandler()
        await handler.cleanup(_make_context())


# =========================================================================
# Handler type identifiers
# =========================================================================


class TestHandlerTypes:
    def test_all_handler_types_unique(self):
        handlers = [
            GitHubPRHandler(github_service=MagicMock()),
            GitLabMRHandler(token="fake"),
            PatchFileHandler(),
            LocalSyncHandler(),
        ]
        types = [h.handler_type for h in handlers]
        assert len(set(types)) == len(types), f"Duplicate handler types: {types}"
