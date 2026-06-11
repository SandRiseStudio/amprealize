"""GitLab Merge Request output handler.

Commits accumulated file changes via the GitLab API and opens a merge request.

Part of E3 — Agent Execution Loop Rearchitecture (Phase 4 / S3.8).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from urllib.parse import quote

import httpx

from .base import (
    FileChange,
    OutputContext,
    OutputResult,
    OutputStatus,
)

logger = logging.getLogger(__name__)


class GitLabMRHandler:
    """Delivers file changes as a GitLab merge request.

    Uses the GitLab REST API v4 to:
    1. Create a branch from the base ref
    2. Commit all file changes in a single commit
    3. Open a merge request
    """

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://gitlab.com",
    ) -> None:
        """
        Args:
            token: GitLab personal access token or project token with api scope.
            base_url: GitLab instance URL (defaults to gitlab.com).
        """
        self._token = token
        self._base_url = base_url.rstrip("/")

    @property
    def handler_type(self) -> str:
        return "gitlab_mr"

    async def deliver(self, context: OutputContext) -> OutputResult:
        """Commit changes to a branch and open a merge request."""
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
                error="No repository (project path) configured in output context",
            )

        if not context.branch_name:
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error="No branch name configured in output context",
            )

        project_path = quote(context.repo, safe="")
        api = f"{self._base_url}/api/v4/projects/{project_path}"
        headers = {"PRIVATE-TOKEN": self._token}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # 1. Create branch
                branch_resp = await client.post(
                    f"{api}/repository/branches",
                    headers=headers,
                    json={
                        "branch": context.branch_name,
                        "ref": context.base_branch,
                    },
                )
                if branch_resp.status_code not in (201, 400):
                    # 400 = branch already exists, which is ok for retries
                    return OutputResult(
                        status=OutputStatus.FAILED,
                        handler_type=self.handler_type,
                        error=f"Failed to create branch: {branch_resp.status_code} {branch_resp.text[:200]}",
                    )

                # 2. Commit all changes
                actions = self._build_commit_actions(context.changes)
                commit_resp = await client.post(
                    f"{api}/repository/commits",
                    headers=headers,
                    json={
                        "branch": context.branch_name,
                        "commit_message": f"feat: {context.work_item_title}",
                        "actions": actions,
                    },
                )
                if commit_resp.status_code != 201:
                    return OutputResult(
                        status=OutputStatus.FAILED,
                        handler_type=self.handler_type,
                        error=f"Failed to commit: {commit_resp.status_code} {commit_resp.text[:200]}",
                    )
                commit_data = commit_resp.json()
                commit_sha = commit_data.get("id", "")

                # 3. Create merge request
                mr_body = self._build_mr_description(context)
                mr_resp = await client.post(
                    f"{api}/merge_requests",
                    headers=headers,
                    json={
                        "source_branch": context.branch_name,
                        "target_branch": context.base_branch,
                        "title": f"[Amprealize] {context.work_item_title}",
                        "description": mr_body,
                        "labels": ",".join(context.labels) if context.labels else "",
                        "squash": True,
                    },
                )
                if mr_resp.status_code != 201:
                    return OutputResult(
                        status=OutputStatus.PARTIAL,
                        handler_type=self.handler_type,
                        files_changed=len(context.changes),
                        commit_sha=commit_sha,
                        branch_name=context.branch_name,
                        error=f"Changes committed but MR creation failed: {mr_resp.status_code} {mr_resp.text[:200]}",
                    )

                mr_data = mr_resp.json()
                mr_url = mr_data.get("web_url", "")
                mr_iid = mr_data.get("iid")

                logger.info(
                    f"GitLab MR created for run {context.run_id}: {mr_url} "
                    f"({len(context.changes)} files)"
                )

                return OutputResult(
                    status=OutputStatus.SUCCESS,
                    handler_type=self.handler_type,
                    files_changed=len(context.changes),
                    message=f"Merge request created: {mr_url}",
                    pr_url=mr_url,
                    pr_number=mr_iid,
                    branch_name=context.branch_name,
                    commit_sha=commit_sha,
                )

        except httpx.TimeoutException:
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error="GitLab API request timed out",
            )
        except Exception as e:
            logger.exception(f"Error creating GitLab MR for run {context.run_id}: {e}")
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error=str(e),
            )

    async def cleanup(self, context: OutputContext) -> None:
        """No cleanup needed for GitLab MRs."""
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_commit_actions(changes: List[FileChange]) -> List[Dict[str, Any]]:
        """Convert FileChange list to GitLab commit actions."""
        actions: List[Dict[str, Any]] = []
        for change in changes:
            action_type = {
                "create": "create",
                "update": "update",
                "delete": "delete",
            }.get(change.action, "update")

            entry: Dict[str, Any] = {
                "action": action_type,
                "file_path": change.path,
            }
            if not change.is_deletion() and change.content is not None:
                if change.encoding == "base64":
                    entry["content"] = change.content
                    entry["encoding"] = "base64"
                else:
                    entry["content"] = change.content
            actions.append(entry)
        return actions

    def _build_mr_description(self, context: OutputContext) -> str:
        """Build merge request description markdown."""
        sections = [
            "## Summary",
            "",
            context.summary or "Changes generated by Amprealize agent execution.",
            "",
            "## Changes",
            "",
        ]
        for change in context.changes:
            icon = {"create": "+", "update": "~", "delete": "-"}.get(change.action, "?")
            sections.append(f"- `{icon}` `{change.path}`")
        sections.extend([
            "",
            "---",
            f"*Run ID: `{context.run_id}`*  ",
            f"*Work Item: `{context.work_item_id}`*  ",
            "*Generated by Amprealize*",
        ])
        return "\n".join(sections)
