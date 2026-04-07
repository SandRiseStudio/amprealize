"""Local filesystem sync output handler.

Writes accumulated file changes directly to the local filesystem.
Used for LOCAL_DIRECT and CONTAINER_CONNECTED modes where the user's
workspace is directly accessible.

Part of E3 — Agent Execution Loop Rearchitecture (Phase 4 / S3.8).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from .base import (
    FileChange,
    OutputContext,
    OutputHandler,
    OutputResult,
    OutputStatus,
)

logger = logging.getLogger(__name__)


class LocalSyncHandler:
    """Writes file changes directly to the local filesystem.

    Changes are applied relative to `context.workspace_path`. The handler
    creates directories as needed, writes/overwrites files, and deletes
    files marked for deletion.
    """

    def __init__(self, *, dry_run: bool = False) -> None:
        """
        Args:
            dry_run: If True, log changes but don't write to disk.
        """
        self._dry_run = dry_run

    @property
    def handler_type(self) -> str:
        return "local_sync"

    async def deliver(self, context: OutputContext) -> OutputResult:
        """Write file changes to the local filesystem."""
        if not context.has_changes():
            return OutputResult(
                status=OutputStatus.NO_CHANGES,
                handler_type=self.handler_type,
                message="No file changes to sync",
            )

        workspace = context.workspace_path
        if not workspace:
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error="No workspace_path configured in output context",
            )

        if not os.path.isdir(workspace):
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error=f"Workspace path does not exist: {workspace}",
            )

        succeeded = 0
        failed = 0
        errors: List[str] = []

        for change in context.changes:
            try:
                self._apply_change(workspace, change)
                succeeded += 1
            except Exception as e:
                failed += 1
                errors.append(f"{change.path}: {e}")
                logger.warning(
                    f"Failed to sync {change.path} for run {context.run_id}: {e}"
                )

        if failed > 0 and succeeded == 0:
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                files_changed=0,
                error=f"All {failed} file operations failed: {'; '.join(errors[:3])}",
            )

        if failed > 0:
            return OutputResult(
                status=OutputStatus.PARTIAL,
                handler_type=self.handler_type,
                files_changed=succeeded,
                message=f"Synced {succeeded} files, {failed} failed",
                error="; ".join(errors[:3]),
            )

        logger.info(
            f"Local sync completed for run {context.run_id}: "
            f"{succeeded} files synced to {workspace}"
        )

        return OutputResult(
            status=OutputStatus.SUCCESS,
            handler_type=self.handler_type,
            files_changed=succeeded,
            message=f"Synced {succeeded} files to {workspace}",
        )

    async def cleanup(self, context: OutputContext) -> None:
        """No cleanup needed for local sync."""
        pass

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _apply_change(self, workspace: str, change: FileChange) -> None:
        """Apply a single file change to the workspace."""
        # Prevent path traversal
        target = os.path.normpath(os.path.join(workspace, change.path))
        if not target.startswith(os.path.normpath(workspace)):
            raise ValueError(f"Path traversal detected: {change.path}")

        if self._dry_run:
            logger.info(f"[dry-run] Would {change.action} {target}")
            return

        if change.is_deletion():
            if os.path.exists(target):
                os.remove(target)
                logger.debug(f"Deleted {target}")
            return

        # Create parent directories
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)

        if change.encoding == "base64":
            import base64
            data = base64.b64decode(change.content or "")
            with open(target, "wb") as f:
                f.write(data)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write(change.content or "")

        logger.debug(f"{'Created' if change.action == 'create' else 'Updated'} {target}")
