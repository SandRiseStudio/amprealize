"""GitHub Pull Request output handler.

Commits accumulated file changes to a new branch and opens a pull request
via GitHubService. Extracted from the monolithic PR-creation logic
previously embedded in AgentExecutionLoop._create_pull_request_if_needed().

Part of E3 — Agent Execution Loop Rearchitecture (Phase 4 / S3.8).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import (
    FileChange,
    OutputContext,
    OutputHandler,
    OutputResult,
    OutputStatus,
)

logger = logging.getLogger(__name__)


class GitHubPRHandler:
    """Delivers file changes as a GitHub pull request.

    Requires a configured GitHubService instance to perform the actual
    Git tree / commit / PR API calls.
    """

    def __init__(self, github_service: Any) -> None:
        """
        Args:
            github_service: A GitHubService (from amprealize.services.github_service)
                that handles token resolution and GitHub API calls.
        """
        self._github = github_service

    @property
    def handler_type(self) -> str:
        return "github_pr"

    async def deliver(self, context: OutputContext) -> OutputResult:
        """Commit changes to a branch and open a pull request."""
        if not context.has_changes():
            return OutputResult(
                status=OutputStatus.NO_CHANGES,
                handler_type=self.handler_type,
                message="No file changes to deliver",
            )

        if not context.repo:
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error="No repository configured in output context",
            )

        if not context.branch_name:
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error="No branch name configured in output context",
            )

        try:
            from amprealize.services.github_service import FileChange as GHFileChange

            # Convert our FileChange to GitHub-service FileChange
            gh_changes: List[GHFileChange] = []
            for change in context.changes:
                gh_changes.append(GHFileChange(
                    path=change.path,
                    content=change.content if not change.is_deletion() else None,
                    encoding=change.encoding,
                    action=change.action,
                ))

            pr_title = f"[Amprealize] {context.work_item_title}"
            pr_body = self._build_pr_body(context)
            commit_msg = f"feat: {context.work_item_title}"

            logger.info(
                f"Creating GitHub PR for run {context.run_id}: "
                f"{len(gh_changes)} file(s) on branch {context.branch_name}"
            )

            pr_result = self._github.create_pull_request(
                repo=context.repo,
                title=pr_title,
                head_branch=context.branch_name,
                files=gh_changes,
                project_id=context.project_id,
                org_id=context.org_id,
                body=pr_body,
                base_branch=context.base_branch,
                commit_message=commit_msg,
                draft=context.draft,
                labels=context.labels,
            )

            if pr_result.success:
                logger.info(
                    f"PR created for run {context.run_id}: {pr_result.pr_url} "
                    f"({pr_result.files_changed} files)"
                )
                return OutputResult(
                    status=OutputStatus.SUCCESS,
                    handler_type=self.handler_type,
                    files_changed=pr_result.files_changed,
                    message=f"Pull request created: {pr_result.pr_url}",
                    pr_url=pr_result.pr_url,
                    pr_number=pr_result.pr_number,
                    branch_name=context.branch_name,
                    commit_sha=pr_result.commit_sha,
                )
            else:
                logger.error(
                    f"Failed to create PR for run {context.run_id}: {pr_result.error}"
                )
                return OutputResult(
                    status=OutputStatus.FAILED,
                    handler_type=self.handler_type,
                    error=f"PR creation failed: {pr_result.error}",
                )

        except Exception as e:
            logger.exception(f"Error creating PR for run {context.run_id}: {e}")
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error=str(e),
            )

    async def cleanup(self, context: OutputContext) -> None:
        """No cleanup needed for GitHub PRs."""
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_pr_body(self, context: OutputContext) -> str:
        """Build the markdown body for the pull request."""
        sections = [
            "## Summary",
            "",
            context.summary or "Changes generated by Amprealize agent execution.",
            "",
        ]

        # File changes table
        summary = context.changes_summary()
        sections.extend([
            "## Changes",
            "",
            f"| Action | Count |",
            f"|--------|-------|",
            f"| Created | {summary.get('create', 0)} |",
            f"| Updated | {summary.get('update', 0)} |",
            f"| Deleted | {summary.get('delete', 0)} |",
            "",
        ])

        # Files list
        sections.append("### Files")
        sections.append("")
        for change in context.changes:
            icon = {"create": "+", "update": "~", "delete": "-"}.get(change.action, "?")
            sections.append(f"- `{icon}` `{change.path}`")
        sections.append("")

        # Metadata
        sections.extend([
            "---",
            f"*Run ID: `{context.run_id}`*  ",
            f"*Work Item: `{context.work_item_id}`*  ",
            "*Generated by Amprealize*",
        ])

        return "\n".join(sections)
