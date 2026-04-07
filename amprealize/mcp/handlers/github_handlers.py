"""GitHub MCP tool handlers.

Handlers for github.* MCP tools:
- github.createPR - Create a pull request with file changes
- github.commitToBranch - Commit files to a branch

Following `behavior_prefer_mcp_tools` for consistent MCP interface.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...services.github_service import FileChange, GitHubService


logger = logging.getLogger(__name__)


# ==============================================================================
# Handler Functions
# ==============================================================================


def handle_create_pr(
    service: GitHubService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle github.createPR tool call.

    Creates a pull request with the specified file changes.

    Args:
        service: GitHubService instance
        arguments: Tool arguments including:
            - project_id: Project ID for credential resolution
            - repo: Repository in "owner/repo" format (required)
            - title: PR title (required)
            - head_branch: Branch name for changes (required)
            - files: List of file changes (required)
            - base_branch: Target branch (default: "main")
            - body: PR description
            - commit_message: Commit message (default: PR title)
            - draft: Create as draft PR
            - labels: Labels to add
            - reviewers: Usernames to request review from

    Returns:
        Dict with success status and PR details
    """
    try:
        # Extract arguments
        repo = arguments.get("repo")
        title = arguments.get("title")
        head_branch = arguments.get("head_branch")
        files_data = arguments.get("files", [])

        # Validate required fields
        if not repo:
            return {"success": False, "error": "Missing required field: repo"}
        if not title:
            return {"success": False, "error": "Missing required field: title"}
        if not head_branch:
            return {"success": False, "error": "Missing required field: head_branch"}
        if not files_data:
            return {"success": False, "error": "Missing required field: files"}

        # Parse file changes
        files = _parse_file_changes(files_data)
        if not files:
            return {"success": False, "error": "No valid file changes provided"}

        # Create PR
        result = service.create_pull_request(
            repo=repo,
            title=title,
            head_branch=head_branch,
            files=files,
            project_id=arguments.get("project_id"),
            org_id=arguments.get("org_id"),
            body=arguments.get("body"),
            base_branch=arguments.get("base_branch", "main"),
            commit_message=arguments.get("commit_message"),
            draft=arguments.get("draft", False),
            labels=arguments.get("labels"),
            reviewers=arguments.get("reviewers"),
        )

        if result.success:
            return {
                "success": True,
                "pr_number": result.pr_number,
                "pr_url": result.pr_url,
                "head_branch": result.head_branch,
                "commit_sha": result.commit_sha,
                "files_changed": result.files_changed,
            }
        else:
            return {"success": False, "error": result.error}

    except Exception as e:
        logger.exception("Failed to create PR via MCP handler")
        return {"success": False, "error": f"Handler error: {e}"}


def handle_commit_to_branch(
    service: GitHubService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Handle github.commitToBranch tool call.

    Commits file changes to a branch, optionally creating it.

    Args:
        service: GitHubService instance
        arguments: Tool arguments including:
            - project_id: Project ID for credential resolution
            - repo: Repository in "owner/repo" format (required)
            - branch: Target branch name (required)
            - message: Commit message (required)
            - files: List of file changes (required)
            - create_branch: Create branch if not exists (default: true)
            - base_branch: Base branch for new branches (default: "main")

    Returns:
        Dict with success status and commit details
    """
    try:
        # Extract arguments
        repo = arguments.get("repo")
        branch = arguments.get("branch")
        message = arguments.get("message")
        files_data = arguments.get("files", [])

        # Validate required fields
        if not repo:
            return {"success": False, "error": "Missing required field: repo"}
        if not branch:
            return {"success": False, "error": "Missing required field: branch"}
        if not message:
            return {"success": False, "error": "Missing required field: message"}
        if not files_data:
            return {"success": False, "error": "Missing required field: files"}

        # Parse file changes
        files = _parse_file_changes(files_data)
        if not files:
            return {"success": False, "error": "No valid file changes provided"}

        # Commit to branch
        result = service.commit_to_branch(
            repo=repo,
            branch=branch,
            message=message,
            files=files,
            project_id=arguments.get("project_id"),
            org_id=arguments.get("org_id"),
            create_branch=arguments.get("create_branch", True),
            base_branch=arguments.get("base_branch", "main"),
        )

        if result.success:
            return {
                "success": True,
                "commit_sha": result.commit_sha,
                "commit_url": result.commit_url,
                "branch": result.branch,
                "branch_created": result.branch_created,
                "files_changed": result.files_changed,
            }
        else:
            return {"success": False, "error": result.error}

    except Exception as e:
        logger.exception("Failed to commit to branch via MCP handler")
        return {"success": False, "error": f"Handler error: {e}"}


# ==============================================================================
# Helper Functions
# ==============================================================================


def _parse_file_changes(files_data: List[Dict[str, Any]]) -> List[FileChange]:
    """Parse file change dictionaries into FileChange objects.

    Args:
        files_data: List of file change dicts with:
            - path: File path (required)
            - content: File content (required for create/update)
            - action: "create", "update", "delete" (default: "update")
            - encoding: "utf-8" or "base64" (default: "utf-8")

    Returns:
        List of FileChange objects
    """
    changes: List[FileChange] = []

    for file_dict in files_data:
        path = file_dict.get("path")
        if not path:
            continue

        action = file_dict.get("action", "update")
        content = file_dict.get("content")

        # For delete, content is not needed
        if action == "delete":
            changes.append(FileChange(
                path=path,
                content=None,
                action="delete",
            ))
        elif content is not None:
            changes.append(FileChange(
                path=path,
                content=content,
                encoding=file_dict.get("encoding", "utf-8"),
                action=action,
            ))

    return changes


# ==============================================================================
# Handler Registry
# ==============================================================================


GITHUB_HANDLERS: Dict[str, Any] = {
    "github.createPR": handle_create_pr,
    "github.commitToBranch": handle_commit_to_branch,
}
