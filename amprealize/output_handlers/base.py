"""OutputHandler protocol and shared types.

Defines the contract that all output handlers must implement, plus the
OutputContext (accumulates file changes) and OutputResult (delivery outcome).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OutputStatus(str, Enum):
    """Delivery status for an output handler push."""

    SUCCESS = "success"
    PARTIAL = "partial"        # Some files delivered, some failed
    FAILED = "failed"
    NO_CHANGES = "no_changes"  # Nothing to deliver


# ---------------------------------------------------------------------------
# File-change dataclass (replaces PendingFileChange for output layer)
# ---------------------------------------------------------------------------


@dataclass
class FileChange:
    """A single file change produced by agent execution.

    This is the canonical representation passed into output handlers.
    It is intentionally decoupled from PendingFileChange (execution-layer)
    and FileChange (GitHub-service-layer) to keep the output abstraction
    independent.
    """

    path: str
    content: Optional[str]  # None for deletions
    action: str  # "create", "update", "delete"
    phase: str = ""  # GEP phase where change was made
    original_content: Optional[str] = None  # For diff generation
    encoding: str = "utf-8"  # "utf-8" or "base64"

    def is_deletion(self) -> bool:
        return self.action == "delete"


# ---------------------------------------------------------------------------
# OutputContext — accumulates changes during execution
# ---------------------------------------------------------------------------


@dataclass
class OutputContext:
    """Accumulates file changes during execution and carries metadata
    needed by output handlers to deliver results.

    Created by the ExecutionGateway at the start of a run and passed
    through the execution loop. After execution completes, the gateway
    hands it to the appropriate OutputHandler.
    """

    # Identity
    run_id: str
    work_item_id: str
    work_item_title: str = ""

    # Repository info (for PR/MR handlers)
    repo: str = ""  # owner/repo
    base_branch: str = "main"
    branch_name: str = ""

    # Project / org (for credential resolution)
    project_id: Optional[str] = None
    org_id: Optional[str] = None

    # Configuration
    draft: bool = False
    labels: List[str] = field(default_factory=lambda: ["amprealize", "automated"])

    # Accumulated changes
    changes: List[FileChange] = field(default_factory=list)

    # Execution summary (populated during COMPLETING phase)
    summary: str = ""
    phase_outputs: Dict[str, Any] = field(default_factory=dict)

    # Local paths (for LocalSyncHandler / PatchFileHandler)
    workspace_path: Optional[str] = None  # Container or local workspace root
    output_dir: Optional[str] = None  # Where to write patch/archive files

    def add_change(
        self,
        path: str,
        content: Optional[str],
        action: str,
        phase: str = "",
        original_content: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> None:
        """Add a file change, merging with existing change for same path."""
        for existing in self.changes:
            if existing.path == path:
                existing.content = content
                existing.action = action
                existing.phase = phase
                if original_content and not existing.original_content:
                    existing.original_content = original_content
                return

        self.changes.append(FileChange(
            path=path,
            content=content,
            action=action,
            phase=phase,
            original_content=original_content,
            encoding=encoding,
        ))

    def has_changes(self) -> bool:
        return len(self.changes) > 0

    def changes_summary(self) -> Dict[str, int]:
        """Count changes by action type."""
        summary: Dict[str, int] = {"create": 0, "update": 0, "delete": 0}
        for c in self.changes:
            if c.action in summary:
                summary[c.action] += 1
        return summary


# ---------------------------------------------------------------------------
# OutputResult — returned by handlers after delivery
# ---------------------------------------------------------------------------


@dataclass
class OutputResult:
    """Result of an output handler delivery attempt."""

    status: OutputStatus
    handler_type: str  # "github_pr", "gitlab_mr", "patch_file", "local_sync"
    files_changed: int = 0
    message: str = ""

    # PR/MR specific
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None

    # Patch/archive specific
    artifact_path: Optional[str] = None  # local path to .patch or .tar.gz
    artifact_size_bytes: Optional[int] = None

    # Error info
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "status": self.status.value,
            "handler_type": self.handler_type,
            "files_changed": self.files_changed,
            "message": self.message,
        }
        if self.pr_url:
            d["pr_url"] = self.pr_url
        if self.pr_number is not None:
            d["pr_number"] = self.pr_number
        if self.branch_name:
            d["branch_name"] = self.branch_name
        if self.commit_sha:
            d["commit_sha"] = self.commit_sha
        if self.artifact_path:
            d["artifact_path"] = self.artifact_path
        if self.artifact_size_bytes is not None:
            d["artifact_size_bytes"] = self.artifact_size_bytes
        if self.error:
            d["error"] = self.error
        return d


# ---------------------------------------------------------------------------
# OutputHandler Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class OutputHandler(Protocol):
    """Protocol for output delivery strategies.

    Each handler knows how to take accumulated file changes and deliver
    them to a specific target (PR, patch file, local filesystem, etc.).
    """

    @property
    def handler_type(self) -> str:
        """Identifier for this handler type (e.g. 'github_pr')."""
        ...

    async def deliver(self, context: OutputContext) -> OutputResult:
        """Deliver accumulated file changes to the target.

        This is the main entry point. Implementations should:
        1. Validate the context has necessary info (repo, branch, etc.)
        2. Convert FileChange objects to target-specific format
        3. Push changes (create PR, write patch, etc.)
        4. Return an OutputResult with delivery status

        Args:
            context: The output context with accumulated changes and metadata.

        Returns:
            OutputResult with status and delivery details.
        """
        ...

    async def cleanup(self, context: OutputContext) -> None:
        """Clean up any resources after delivery (optional).

        Called by the gateway after deliver(), regardless of success/failure.
        Default implementations can be no-ops.
        """
        ...
