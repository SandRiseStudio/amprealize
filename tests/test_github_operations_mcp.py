"""Tests for GitHub operations MCP handlers.

Tests following behavior_design_test_strategy:
- Unit tests for GitHub handlers (createPR, commitToBranch)
- Mock GitHub REST API responses
- Test file change parsing and operations
- Error handling for API failures

Note: These tests don't require database infrastructure.
"""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amprealize.mcp.handlers.github_handlers import (
    GITHUB_HANDLERS,
    handle_create_pr,
    handle_commit_to_branch,
    _parse_file_changes,
)
from amprealize.services.github_service import FileChange


# Mark all tests in this module as pure unit tests
pytestmark = pytest.mark.unit


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_github_service():
    """Create a mock GitHubService with async methods."""
    service = MagicMock()
    service.commit_to_branch = AsyncMock()
    service.create_pull_request = AsyncMock()
    return service


@pytest.fixture
def sample_file_changes():
    """Sample file changes for testing."""
    return [
        {"path": "src/file1.py", "content": "print('hello')", "operation": "create"},
        {"path": "src/file2.py", "content": "# Updated", "operation": "update"},
        {"path": "old_file.py", "operation": "delete"},
    ]


# ==============================================================================
# Test _parse_file_changes helper
# ==============================================================================


def test_parse_file_changes_all_operations():
    """Test parsing file changes with all operation types."""
    changes_data = [
        {"path": "new.py", "content": "new content", "action": "create"},
        {"path": "mod.py", "content": "modified", "action": "update"},
        {"path": "del.py", "action": "delete"},
    ]

    changes = _parse_file_changes(changes_data)

    assert len(changes) == 3
    assert isinstance(changes[0], FileChange)
    assert changes[0].path == "new.py"
    assert changes[0].content == "new content"
    assert changes[0].action == "create"

    assert changes[1].action == "update"
    assert changes[2].action == "delete"  # Delete action is preserved
    assert changes[2].content is None


def test_parse_file_changes_default_operation():
    """Test that files without operation specified work."""
    changes_data = [{"path": "file.py", "content": "content"}]

    changes = _parse_file_changes(changes_data)

    assert len(changes) == 1
    assert changes[0].action == "update"  # Default action


def test_parse_file_changes_missing_content():
    """Test that files without content are skipped unless delete."""
    changes_data = [{"path": "file.py"}]

    changes = _parse_file_changes(changes_data)

    # Files without content and not delete action are skipped
    assert len(changes) == 0


def test_parse_file_changes_delete_no_content():
    """Test that delete action works without content."""
    changes_data = [{"path": "file.py", "action": "delete"}]

    changes = _parse_file_changes(changes_data)

    assert len(changes) == 1
    assert changes[0].action == "delete"
    assert changes[0].content is None


def test_parse_file_changes_empty_list():
    """Test parsing empty file changes list."""
    changes = _parse_file_changes([])
    assert changes == []


# ==============================================================================
# Test github.commitToBranch
# ==============================================================================


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_commit_to_branch_success(mock_service_class, sample_file_changes):
    """Test successful commit to branch."""
    mock_service = MagicMock()

    # Create a mock result object with attributes
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.commit_sha = "abc123"
    mock_result.branch = "feature/test"
    mock_result.files_changed = 3

    mock_service.commit_to_branch.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_commit_to_branch(
        mock_service,
        {
            "repo": "owner/repo",
            "branch": "feature/test",
            "message": "Test commit",
            "files": sample_file_changes,
        },
    )

    assert result["success"] is True
    assert result["commit_sha"] == "abc123"
    assert result["branch"] == "feature/test"
    assert result["files_changed"] == 3

    # Verify service was called correctly
    mock_service.commit_to_branch.assert_called_once()
    call_kwargs = mock_service.commit_to_branch.call_args[1]
    assert call_kwargs["branch"] == "feature/test"
    assert call_kwargs["message"] == "Test commit"
    assert len(call_kwargs["files"]) == 2  # Only 2 files have content


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_commit_to_branch_with_base_branch(mock_service_class):
    """Test commit with base branch (creates new branch)."""
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.commit_sha = "def456"
    mock_result.branch = "feature/new"
    mock_result.files_changed = 1

    mock_service.commit_to_branch.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_commit_to_branch(
        mock_service,
        {
            "repo": "owner/repo",
            "branch": "feature/new",
            "base_branch": "main",
            "message": "New branch commit",
            "files": [{"path": "file.py", "content": "test"}],
        },
    )

    assert result["success"] is True
    assert result["branch"] == "feature/new"

    # Verify base_branch was passed
    call_kwargs = mock_service.commit_to_branch.call_args[1]
    assert call_kwargs["base_branch"] == "main"


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_commit_to_branch_api_error(mock_service_class):
    """Test handling of GitHub API errors."""
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error = "API rate limit exceeded"

    mock_service.commit_to_branch.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_commit_to_branch(
        mock_service,
        {
            "repo": "owner/repo",
            "branch": "test",
            "message": "Test",
            "files": [{"path": "file.py", "content": "test"}],
        },
    )

    assert result["success"] is False
    assert "API rate limit" in result["error"]


# ==============================================================================
# Test github.createPR
# ==============================================================================


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_create_pr_basic(mock_service_class, sample_file_changes):
    """Test creating a basic PR."""
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.pr_number = 42
    mock_result.pr_url = "https://github.com/owner/repo/pull/42"
    mock_result.commit_sha = "abc123"

    mock_service.create_pull_request.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_create_pr(
        mock_service,
        {
            "repo": "owner/repo",
            "head_branch": "feature/test",
            "base_branch": "main",
            "title": "Test PR",
            "body": "Test description",
            "files": sample_file_changes,
        },
    )

    assert result["success"] is True
    assert result["pr_number"] == 42
    assert result["pr_url"] == "https://github.com/owner/repo/pull/42"
    assert result["commit_sha"] == "abc123"

    # Verify service call
    mock_service.create_pull_request.assert_called_once()
    call_kwargs = mock_service.create_pull_request.call_args[1]
    assert call_kwargs["title"] == "Test PR"
    assert call_kwargs["body"] == "Test description"
    assert call_kwargs["head_branch"] == "feature/test"
    assert call_kwargs["base_branch"] == "main"


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_create_pr_with_labels_and_reviewers(mock_service_class):
    """Test creating PR with labels and reviewers."""
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.pr_number = 43
    mock_result.pr_url = "https://github.com/owner/repo/pull/43"
    mock_result.commit_sha = "def456"

    mock_service.create_pull_request.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_create_pr(
        mock_service,
        {
            "repo": "owner/repo",
            "head_branch": "feature/test",
            "base_branch": "main",
            "title": "Test PR",
            "body": "Description",
            "files": [{"path": "file.py", "content": "test"}],
            "labels": ["enhancement", "needs-review"],
            "reviewers": ["user1", "user2"],
        },
    )

    assert result["success"] is True

    # Verify labels and reviewers were passed
    call_kwargs = mock_service.create_pull_request.call_args[1]
    assert call_kwargs["labels"] == ["enhancement", "needs-review"]
    assert call_kwargs["reviewers"] == ["user1", "user2"]


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_create_pr_draft_mode(mock_service_class):
    """Test creating a draft PR."""
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.pr_number = 44
    mock_result.pr_url = "https://github.com/owner/repo/pull/44"
    mock_result.commit_sha = "ghi789"

    mock_service.create_pull_request.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_create_pr(
        mock_service,
        {
            "repo": "owner/repo",
            "head_branch": "feature/test",
            "base_branch": "main",
            "title": "Draft PR",
            "body": "Work in progress",
            "files": [{"path": "file.py", "content": "test"}],
            "draft": True,
        },
    )

    assert result["success"] is True

    # Verify draft flag was passed
    call_kwargs = mock_service.create_pull_request.call_args[1]
    assert call_kwargs["draft"] is True


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_create_pr_api_error(mock_service_class):
    """Test handling PR creation errors."""
    mock_service = MagicMock()

    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error = "Branch already has open PR"

    mock_service.create_pull_request.return_value = mock_result
    mock_service_class.return_value = mock_service

    result = handle_create_pr(
        mock_service,
        {
            "repo": "owner/repo",
            "head_branch": "feature/test",
            "base_branch": "main",
            "title": "Test",
            "body": "Test",
            "files": [{"path": "file.py", "content": "test"}],
        },
    )

    assert result["success"] is False
    assert "Branch already has open PR" in result["error"]


# ==============================================================================
# Test Handler Registry
# ==============================================================================


def test_handler_registry():
    """Test that GitHub handlers are registered."""
    assert "github.commitToBranch" in GITHUB_HANDLERS
    assert "github.createPR" in GITHUB_HANDLERS

    # Verify they're callable
    assert callable(GITHUB_HANDLERS["github.commitToBranch"])
    assert callable(GITHUB_HANDLERS["github.createPR"])


# ==============================================================================
# Integration Test
# ==============================================================================


@patch("amprealize.mcp.handlers.github_handlers.GitHubService")
def test_github_workflow(mock_service_class):
    """Test complete workflow: commit -> create PR."""
    mock_service = MagicMock()

    # Mock commit response
    mock_commit_result = MagicMock()
    mock_commit_result.success = True
    mock_commit_result.commit_sha = "abc123"
    mock_commit_result.branch = "feature/test"
    mock_commit_result.files_changed = 2
    mock_service.commit_to_branch.return_value = mock_commit_result

    # Mock PR response
    mock_pr_result = MagicMock()
    mock_pr_result.success = True
    mock_pr_result.pr_number = 42
    mock_pr_result.pr_url = "https://github.com/owner/repo/pull/42"
    mock_pr_result.commit_sha = "abc123"
    mock_service.create_pull_request.return_value = mock_pr_result

    mock_service_class.return_value = mock_service

    # 1. Commit to branch
    commit_result = handle_commit_to_branch(
        mock_service,
        {
            "repo": "owner/repo",
            "branch": "feature/test",
            "message": "Add new feature",
            "files": [
                {"path": "src/feature.py", "content": "def feature(): pass"},
                {"path": "tests/test_feature.py", "content": "def test_feature(): pass"},
            ],
        },
    )

    assert commit_result["success"] is True
    assert commit_result["commit_sha"] == "abc123"

    # 2. Create PR (still need at least one file for validation)
    pr_result = handle_create_pr(
        mock_service,
        {
            "repo": "owner/repo",
            "head_branch": "feature/test",
            "base_branch": "main",
            "title": "Add new feature",
            "body": "This PR adds a new feature",
            "files": [{"path": "dummy.txt", "content": "placeholder"}],
            "labels": ["feature"],
        },
    )

    assert pr_result["success"] is True
    assert pr_result["pr_number"] == 42

    # Verify both service methods were called
    assert mock_service.commit_to_branch.call_count == 1
    assert mock_service.create_pull_request.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
