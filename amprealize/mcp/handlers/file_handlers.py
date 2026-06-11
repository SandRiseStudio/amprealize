"""MCP tool handlers for file operations.

Provides handlers for reading, writing, deleting files and generating diffs.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional



# ==============================================================================
# Path Resolution Helpers
# ==============================================================================


def _resolve_path(
    path: str,
    workspace_root: Optional[str] = None,
) -> Path:
    """Resolve a path to an absolute path.

    Args:
        path: Absolute or relative path
        workspace_root: Workspace root for relative paths

    Returns:
        Resolved absolute Path
    """
    p = Path(path)
    if p.is_absolute():
        return p.resolve()

    # Use workspace_root if provided, otherwise current directory
    root = Path(workspace_root) if workspace_root else Path.cwd()
    return (root / p).resolve()


def _validate_path_security(path: Path, workspace_root: Optional[str] = None) -> Optional[str]:
    """Validate path doesn't escape workspace or access sensitive files.

    Returns error message if path is invalid, None if valid.
    """
    # Check for path traversal attempts
    try:
        resolved = path.resolve()
    except (ValueError, OSError) as e:
        return f"Invalid path: {e}"

    # Disallow access to sensitive directories
    sensitive_patterns = [
        "/.git/",  # Git internals (but allow .gitignore etc)
        "/.env",   # Environment files
        "/node_modules/",  # Large dependency trees
        "/__pycache__/",
        "/.venv/",
        "/venv/",
    ]

    path_str = str(resolved)
    for pattern in sensitive_patterns:
        if pattern in path_str:
            return f"Access to '{pattern}' paths is restricted"

    # If workspace_root is set, ensure path is within it
    if workspace_root:
        ws_root = Path(workspace_root).resolve()
        try:
            resolved.relative_to(ws_root)
        except ValueError:
            return f"Path is outside workspace root: {workspace_root}"

    return None


# ==============================================================================
# File Read Handler
# ==============================================================================


def handle_read_file(
    service: Any,  # Not used, but kept for handler signature consistency
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Read file contents from the local filesystem.

    MCP Tool: files.read

    Args:
        service: Service instance (unused for file ops)
        arguments: Dict containing:
            - path (str): Path to file
            - start_line (int, optional): 1-based start line
            - end_line (int, optional): 1-based end line
            - encoding (str, optional): File encoding, default utf-8

    Returns:
        Dict with success, content, metadata
    """
    path_arg = arguments.get("path")
    start_line = arguments.get("start_line")
    end_line = arguments.get("end_line")
    encoding = arguments.get("encoding", "utf-8")
    workspace_root = arguments.get("workspace_root")  # Optional context

    if not path_arg:
        return {
            "success": False,
            "error": "path is required",
        }

    try:
        # Resolve and validate path
        file_path = _resolve_path(path_arg, workspace_root)

        if error := _validate_path_security(file_path, workspace_root):
            return {"success": False, "error": error}

        if not file_path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}",
                "path": str(file_path),
            }

        if not file_path.is_file():
            return {
                "success": False,
                "error": f"Path is not a file: {file_path}",
                "path": str(file_path),
            }

        # Get file stats
        stats = file_path.stat()

        # Read file content
        with open(file_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        total_lines = len(lines)

        # Handle line range
        if start_line is not None or end_line is not None:
            start_idx = (start_line - 1) if start_line else 0
            end_idx = end_line if end_line else total_lines

            # Clamp to valid range
            start_idx = max(0, min(start_idx, total_lines))
            end_idx = max(0, min(end_idx, total_lines))

            content = "".join(lines[start_idx:end_idx])
            lines_read = {
                "start": start_idx + 1,
                "end": end_idx,
            }
        else:
            content = "".join(lines)
            lines_read = {
                "start": 1,
                "end": total_lines,
            }

        return {
            "success": True,
            "content": content,
            "path": str(file_path),
            "line_count": total_lines,
            "lines_read": lines_read,
            "encoding": encoding,
            "size_bytes": stats.st_size,
        }

    except UnicodeDecodeError as e:
        return {
            "success": False,
            "error": f"Encoding error with {encoding}: {e}",
            "path": path_arg,
        }
    except PermissionError:
        return {
            "success": False,
            "error": f"Permission denied: {path_arg}",
            "path": path_arg,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read file: {e}",
            "path": path_arg,
        }


# ==============================================================================
# File Write Handler
# ==============================================================================


def handle_write_file(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Write content to a file.

    MCP Tool: files.write

    Respects write_scope settings:
    - local_only: Write to filesystem only
    - pr_only: Write to PR branch only (requires GitHub integration)
    - local_and_pr: Write to both
    - inherit: Use project default

    Args:
        service: Service instance (for GitHub integration)
        arguments: Dict containing:
            - path (str): Path to file
            - content (str): Content to write
            - encoding (str, optional): File encoding, default utf-8
            - create_dirs (bool, optional): Create parent dirs, default true
            - overwrite (bool, optional): Overwrite existing, default true
            - write_scope (str, optional): Write target scope
            - commit_message (str, optional): Commit message for PR writes

    Returns:
        Dict with success, path, bytes_written, write_targets
    """
    path_arg = arguments.get("path")
    content = arguments.get("content")
    encoding = arguments.get("encoding", "utf-8")
    create_dirs = arguments.get("create_dirs", True)
    overwrite = arguments.get("overwrite", True)
    write_scope = arguments.get("write_scope", "inherit")
    commit_message = arguments.get("commit_message")
    workspace_root = arguments.get("workspace_root")

    if not path_arg:
        return {"success": False, "error": "path is required"}

    if content is None:
        return {"success": False, "error": "content is required"}

    try:
        # Resolve and validate path
        file_path = _resolve_path(path_arg, workspace_root)

        if error := _validate_path_security(file_path, workspace_root):
            return {"success": False, "error": error}

        # Check overwrite policy
        if file_path.exists() and not overwrite:
            return {
                "success": False,
                "error": f"File exists and overwrite=false: {file_path}",
                "path": str(file_path),
            }

        # Resolve write scope
        effective_scope = _resolve_write_scope(write_scope, arguments)
        write_targets: List[str] = []
        result: Dict[str, Any] = {
            "success": True,
            "path": str(file_path),
        }

        # Handle local writes
        if effective_scope in ("local_only", "local_and_pr", "inherit"):
            # Create parent directories if needed
            if create_dirs:
                file_path.parent.mkdir(parents=True, exist_ok=True)
            elif not file_path.parent.exists():
                return {
                    "success": False,
                    "error": f"Parent directory does not exist: {file_path.parent}",
                    "path": str(file_path),
                }

            # Write file
            content_bytes = content.encode(encoding)
            with open(file_path, "w", encoding=encoding) as f:
                f.write(content)

            write_targets.append("local")
            result["bytes_written"] = len(content_bytes)

        # Handle PR writes (requires GitHub service)
        if effective_scope in ("pr_only", "local_and_pr"):
            # PR writes handled by github.commitToBranch or github.createPR
            # This handler focuses on local writes; PR info added if available
            pr_result = _handle_pr_write(service, arguments, file_path, content)
            if pr_result:
                write_targets.append("pr")
                if "pr_url" in pr_result:
                    result["pr_url"] = pr_result["pr_url"]
                if "commit_sha" in pr_result:
                    result["commit_sha"] = pr_result["commit_sha"]

        result["write_targets"] = write_targets
        return result

    except PermissionError:
        return {
            "success": False,
            "error": f"Permission denied: {path_arg}",
            "path": path_arg,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write file: {e}",
            "path": path_arg,
        }


def _resolve_write_scope(write_scope: str, arguments: Dict[str, Any]) -> str:
    """Resolve effective write scope from arguments or defaults."""
    if write_scope != "inherit":
        return write_scope

    # Check for project-level default from context
    project_write_scope = arguments.get("project_write_scope")
    if project_write_scope:
        return project_write_scope

    # Default to local_only
    return "local_only"


def _handle_pr_write(
    service: Any,
    arguments: Dict[str, Any],
    file_path: Path,
    content: str,
) -> Optional[Dict[str, Any]]:
    """Handle PR write operations.

    This is a stub - actual implementation uses github.commitToBranch handler.
    Returns None if PR writes are not configured.
    """
    # PR writes require:
    # - GitHub token (from CredentialStore)
    # - Repository info
    # - Branch name
    # For now, return None and let caller use github.* tools directly
    return None


# ==============================================================================
# File Delete Handler
# ==============================================================================


def handle_delete_file(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete a file from the filesystem.

    MCP Tool: files.delete

    Args:
        service: Service instance
        arguments: Dict containing:
            - path (str): Path to file
            - write_scope (str, optional): Write target scope
            - commit_message (str, optional): Commit message for PR deletions

    Returns:
        Dict with success, path, existed, write_targets
    """
    path_arg = arguments.get("path")
    write_scope = arguments.get("write_scope", "inherit")
    workspace_root = arguments.get("workspace_root")

    if not path_arg:
        return {"success": False, "error": "path is required"}

    try:
        # Resolve and validate path
        file_path = _resolve_path(path_arg, workspace_root)

        if error := _validate_path_security(file_path, workspace_root):
            return {"success": False, "error": error}

        existed = file_path.exists()

        if existed and file_path.is_dir():
            return {
                "success": False,
                "error": "Cannot delete directory with files.delete (use files.deleteDir)",
                "path": str(file_path),
            }

        # Resolve write scope
        effective_scope = _resolve_write_scope(write_scope, arguments)
        write_targets: List[str] = []
        result: Dict[str, Any] = {
            "success": True,
            "path": str(file_path),
            "existed": existed,
        }

        # Handle local deletion
        if effective_scope in ("local_only", "local_and_pr", "inherit"):
            if existed:
                file_path.unlink()
            write_targets.append("local")

        # Handle PR deletion (stub)
        if effective_scope in ("pr_only", "local_and_pr"):
            pr_result = _handle_pr_delete(service, arguments, file_path)
            if pr_result:
                write_targets.append("pr")
                if "pr_url" in pr_result:
                    result["pr_url"] = pr_result["pr_url"]
                if "commit_sha" in pr_result:
                    result["commit_sha"] = pr_result["commit_sha"]

        result["write_targets"] = write_targets
        return result

    except PermissionError:
        return {
            "success": False,
            "error": f"Permission denied: {path_arg}",
            "path": path_arg,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to delete file: {e}",
            "path": path_arg,
        }


def _handle_pr_delete(
    service: Any,
    arguments: Dict[str, Any],
    file_path: Path,
) -> Optional[Dict[str, Any]]:
    """Handle PR delete operations.

    This is a stub - actual implementation uses github.commitToBranch handler.
    """
    return None


# ==============================================================================
# File Diff Handler
# ==============================================================================


def handle_diff_file(
    service: Any,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate unified diff between current file and proposed content.

    MCP Tool: files.diff

    Args:
        service: Service instance
        arguments: Dict containing:
            - path (str): Path to file
            - new_content (str): Proposed new content
            - context_lines (int, optional): Context lines, default 3
            - encoding (str, optional): File encoding, default utf-8

    Returns:
        Dict with success, diff, has_changes, stats
    """
    path_arg = arguments.get("path")
    new_content = arguments.get("new_content")
    context_lines = arguments.get("context_lines", 3)
    encoding = arguments.get("encoding", "utf-8")
    workspace_root = arguments.get("workspace_root")

    if not path_arg:
        return {"success": False, "error": "path is required"}

    if new_content is None:
        return {"success": False, "error": "new_content is required"}

    try:
        # Resolve path
        file_path = _resolve_path(path_arg, workspace_root)

        if error := _validate_path_security(file_path, workspace_root):
            return {"success": False, "error": error}

        # Get current content (empty if file doesn't exist)
        is_new_file = not file_path.exists()
        if is_new_file:
            old_content = ""
            old_lines = []
        else:
            with open(file_path, "r", encoding=encoding) as f:
                old_content = f.read()
            old_lines = old_content.splitlines(keepends=True)

        new_lines = new_content.splitlines(keepends=True)

        # Ensure trailing newline for proper diff
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        if old_lines and not old_lines[-1].endswith('\n'):
            old_lines[-1] += '\n'

        # Generate unified diff
        diff_lines = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path.name}" if not is_new_file else "/dev/null",
            tofile=f"b/{file_path.name}",
            n=context_lines,
        ))

        diff_text = "".join(diff_lines)
        has_changes = len(diff_lines) > 0

        # Calculate stats
        lines_added = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
        lines_removed = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))

        return {
            "success": True,
            "diff": diff_text,
            "has_changes": has_changes,
            "is_new_file": is_new_file,
            "stats": {
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "lines_changed": max(lines_added, lines_removed),
            },
            "path": str(file_path),
        }

    except UnicodeDecodeError as e:
        return {
            "success": False,
            "error": f"Encoding error with {encoding}: {e}",
            "path": path_arg,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to generate diff: {e}",
            "path": path_arg,
        }


# ==============================================================================
# Handler Registry
# ==============================================================================


FILE_HANDLERS: Dict[str, Any] = {
    "files.read": handle_read_file,
    "files.write": handle_write_file,
    "files.delete": handle_delete_file,
    "files.diff": handle_diff_file,
}
