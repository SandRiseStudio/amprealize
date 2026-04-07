"""Tests for file operations MCP handlers.

Tests following behavior_design_test_strategy:
- Unit tests for each file handler (read, write, delete, diff)
- Path security validation tests
- Write scope resolution tests
- Error handling for missing/invalid paths

Note: These tests don't require database infrastructure.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

from amprealize.mcp.handlers.file_handlers import (
    FILE_HANDLERS,
    handle_read_file,
    handle_write_file,
    handle_delete_file,
    handle_diff_file,
)


# Mark all tests in this module as pure unit tests
pytestmark = pytest.mark.unit


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def sample_file(temp_workspace: Path) -> Path:
    """Create a sample file for testing."""
    file_path = temp_workspace / "sample.txt"
    content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
    file_path.write_text(content)
    return file_path


# ==============================================================================
# Test files.read
# ==============================================================================


def test_read_file_success(sample_file: Path):
    """Test reading a complete file."""
    result = handle_read_file(None, {"path": str(sample_file)})

    assert result["success"] is True
    assert "Line 1" in result["content"]
    assert result["line_count"] == 5
    assert result["lines_read"]["start"] == 1
    assert result["lines_read"]["end"] == 5


def test_read_file_line_range(sample_file: Path):
    """Test reading a specific line range."""
    result = handle_read_file(
        None,
        {"path": str(sample_file), "start_line": 2, "end_line": 4},
    )

    assert result["success"] is True
    assert "Line 1" not in result["content"]
    assert "Line 2" in result["content"]
    assert "Line 4" in result["content"]
    assert "Line 5" not in result["content"]
    assert result["lines_read"]["start"] == 2
    assert result["lines_read"]["end"] == 4


def test_read_file_not_found(temp_workspace: Path):
    """Test reading a non-existent file."""
    result = handle_read_file(None, {"path": str(temp_workspace / "missing.txt")})

    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_read_file_security_validation(temp_workspace: Path):
    """Test path security validation prevents directory traversal."""
    # Try to read outside workspace
    result = handle_read_file(
        None,
        {
            "path": str(temp_workspace / "../../../etc/passwd"),
            "workspace_root": str(temp_workspace),
        },
    )

    assert result["success"] is False
    assert "outside workspace" in result["error"].lower()


def test_read_file_sensitive_paths():
    """Test that sensitive paths are blocked."""
    # Try to read .env file
    result = handle_read_file(None, {"path": "/tmp/.env"})

    assert result["success"] is False
    assert ".env" in result["error"]


# ==============================================================================
# Test files.write
# ==============================================================================


def test_write_file_success(temp_workspace: Path):
    """Test writing a new file."""
    file_path = temp_workspace / "new_file.txt"
    content = "Hello, World!"

    result = handle_write_file(
        None,
        {"path": str(file_path), "content": content},
    )

    assert result["success"] is True
    assert result["bytes_written"] == len(content.encode("utf-8"))
    assert "local" in result["write_targets"]
    assert file_path.read_text() == content


def test_write_file_create_dirs(temp_workspace: Path):
    """Test creating parent directories."""
    file_path = temp_workspace / "subdir" / "nested" / "file.txt"
    content = "Nested content"

    result = handle_write_file(
        None,
        {"path": str(file_path), "content": content, "create_dirs": True},
    )

    assert result["success"] is True
    assert file_path.exists()
    assert file_path.read_text() == content


def test_write_file_no_overwrite(sample_file: Path):
    """Test overwrite protection."""
    result = handle_write_file(
        None,
        {"path": str(sample_file), "content": "New content", "overwrite": False},
    )

    assert result["success"] is False
    assert "exists" in result["error"].lower()
    assert "overwrite" in result["error"].lower()


@patch("amprealize.mcp.handlers.file_handlers.WriteTargetResolver")
def test_write_file_scope_resolution(mock_resolver, temp_workspace: Path):
    """Test write scope resolution."""
    file_path = temp_workspace / "scoped.txt"

    # Mock the resolver to return local_only
    mock_resolver_instance = MagicMock()
    mock_resolver_instance.resolve.return_value = ["local"]
    mock_resolver.return_value = mock_resolver_instance

    # Test local_only scope (default)
    result = handle_write_file(
        None,
        {
            "path": str(file_path),
            "content": "Test",
            "write_scope": "local_only",
        },
    )

    assert result["success"] is True
    assert result["write_targets"] == ["local"]


# ==============================================================================
# Test files.delete
# ==============================================================================


def test_delete_file_success(sample_file: Path):
    """Test deleting an existing file."""
    result = handle_delete_file(None, {"path": str(sample_file)})

    assert result["success"] is True
    assert result["existed"] is True
    assert "local" in result["write_targets"]
    assert not sample_file.exists()


def test_delete_file_not_exists(temp_workspace: Path):
    """Test deleting a non-existent file."""
    file_path = temp_workspace / "missing.txt"
    result = handle_delete_file(None, {"path": str(file_path)})

    assert result["success"] is True
    assert result["existed"] is False


def test_delete_directory_blocked(temp_workspace: Path):
    """Test that deleting directories is blocked."""
    subdir = temp_workspace / "subdir"
    subdir.mkdir()

    result = handle_delete_file(None, {"path": str(subdir)})

    assert result["success"] is False
    assert "directory" in result["error"].lower()


# ==============================================================================
# Test files.diff
# ==============================================================================


def test_diff_file_changes(sample_file: Path):
    """Test generating diff with changes."""
    new_content = "Line 1\nLine 2 MODIFIED\nLine 3\nLine 4\nLine 5\n"

    result = handle_diff_file(
        None,
        {"path": str(sample_file), "new_content": new_content},
    )

    assert result["success"] is True
    assert result["has_changes"] is True
    assert "Line 2 MODIFIED" in result["diff"]
    assert result["stats"]["lines_added"] > 0
    assert result["stats"]["lines_removed"] > 0


def test_diff_file_no_changes(sample_file: Path):
    """Test diff with identical content."""
    original_content = sample_file.read_text()

    result = handle_diff_file(
        None,
        {"path": str(sample_file), "new_content": original_content},
    )

    assert result["success"] is True
    assert result["has_changes"] is False
    assert result["diff"] == ""


def test_diff_new_file(temp_workspace: Path):
    """Test diff for a new file."""
    file_path = temp_workspace / "new.txt"
    new_content = "Brand new file\n"

    result = handle_diff_file(
        None,
        {"path": str(file_path), "new_content": new_content},
    )

    assert result["success"] is True
    assert result["is_new_file"] is True
    assert result["has_changes"] is True
    assert result["stats"]["lines_added"] > 0
    assert result["stats"]["lines_removed"] == 0


def test_diff_context_lines(sample_file: Path):
    """Test configurable context lines."""
    new_content = "Line 1\nLine 2 MODIFIED\nLine 3\nLine 4\nLine 5\n"

    # With 1 line of context
    result = handle_diff_file(
        None,
        {"path": str(sample_file), "new_content": new_content, "context_lines": 1},
    )

    assert result["success"] is True
    assert result["has_changes"] is True


# ==============================================================================
# Test Handler Registry
# ==============================================================================


def test_handler_registry():
    """Test that all handlers are registered."""
    assert "files.read" in FILE_HANDLERS
    assert "files.write" in FILE_HANDLERS
    assert "files.delete" in FILE_HANDLERS
    assert "files.diff" in FILE_HANDLERS

    # Verify they're callable
    assert callable(FILE_HANDLERS["files.read"])
    assert callable(FILE_HANDLERS["files.write"])
    assert callable(FILE_HANDLERS["files.delete"])
    assert callable(FILE_HANDLERS["files.diff"])


# ==============================================================================
# Integration Test
# ==============================================================================


def test_file_operations_workflow(temp_workspace: Path):
    """Test a complete workflow: write -> read -> diff -> delete."""
    file_path = temp_workspace / "workflow_test.txt"
    original_content = "Original content\nLine 2\n"
    modified_content = "Modified content\nLine 2\nLine 3\n"

    # 1. Write file
    write_result = handle_write_file(
        None,
        {"path": str(file_path), "content": original_content},
    )
    assert write_result["success"] is True

    # 2. Read file
    read_result = handle_read_file(None, {"path": str(file_path)})
    assert read_result["success"] is True
    assert read_result["content"] == original_content

    # 3. Generate diff
    diff_result = handle_diff_file(
        None,
        {"path": str(file_path), "new_content": modified_content},
    )
    assert diff_result["success"] is True
    assert diff_result["has_changes"] is True

    # 4. Write modified content
    write_result2 = handle_write_file(
        None,
        {"path": str(file_path), "content": modified_content, "overwrite": True},
    )
    assert write_result2["success"] is True

    # 5. Read modified file
    read_result2 = handle_read_file(None, {"path": str(file_path)})
    assert read_result2["success"] is True
    assert read_result2["content"] == modified_content

    # 6. Delete file
    delete_result = handle_delete_file(None, {"path": str(file_path)})
    assert delete_result["success"] is True
    assert not file_path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
