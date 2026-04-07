"""Patch file output handler.

Generates a unified diff (.patch) file from accumulated file changes.
Used when the agent runs in CONTAINER_ISOLATED mode against a non-git
source, or when the user explicitly requests patch output.

Part of E3 — Agent Execution Loop Rearchitecture (Phase 4 / S3.8).
"""

from __future__ import annotations

import difflib
import logging
import os
import uuid
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


class PatchFileHandler:
    """Generates a unified diff patch file from accumulated changes.

    The patch is written to `context.output_dir` (or a temp directory)
    and the path is returned in the OutputResult.
    """

    def __init__(self, *, default_output_dir: Optional[str] = None) -> None:
        """
        Args:
            default_output_dir: Fallback directory for patch files when
                context.output_dir is not set.
        """
        self._default_output_dir = default_output_dir

    @property
    def handler_type(self) -> str:
        return "patch_file"

    async def deliver(self, context: OutputContext) -> OutputResult:
        """Generate a unified diff patch file."""
        if not context.has_changes():
            return OutputResult(
                status=OutputStatus.NO_CHANGES,
                handler_type=self.handler_type,
                message="No file changes to generate patch for",
            )

        try:
            patch_content = self._generate_patch(context.changes)
            if not patch_content.strip():
                return OutputResult(
                    status=OutputStatus.NO_CHANGES,
                    handler_type=self.handler_type,
                    message="Generated patch is empty (only deletions without original content?)",
                )

            output_dir = context.output_dir or self._default_output_dir
            if not output_dir:
                import tempfile
                output_dir = tempfile.mkdtemp(prefix="amprealize-patch-")

            os.makedirs(output_dir, exist_ok=True)
            safe_run_id = context.run_id.replace("/", "_")
            filename = f"amprealize-{safe_run_id}.patch"
            patch_path = os.path.join(output_dir, filename)

            with open(patch_path, "w", encoding="utf-8") as f:
                f.write(patch_content)

            patch_size = os.path.getsize(patch_path)

            logger.info(
                f"Patch file generated for run {context.run_id}: "
                f"{patch_path} ({len(context.changes)} files, {patch_size} bytes)"
            )

            return OutputResult(
                status=OutputStatus.SUCCESS,
                handler_type=self.handler_type,
                files_changed=len(context.changes),
                message=f"Patch file generated: {filename}",
                artifact_path=patch_path,
                artifact_size_bytes=patch_size,
            )

        except Exception as e:
            logger.exception(f"Error generating patch for run {context.run_id}: {e}")
            return OutputResult(
                status=OutputStatus.FAILED,
                handler_type=self.handler_type,
                error=str(e),
            )

    async def cleanup(self, context: OutputContext) -> None:
        """No cleanup — patch files are kept for download."""
        pass

    # ------------------------------------------------------------------
    # Patch generation
    # ------------------------------------------------------------------

    def _generate_patch(self, changes: List[FileChange]) -> str:
        """Generate a unified diff from file changes.

        For creates: diff against empty file (/dev/null → new file).
        For updates: diff original_content vs content.
        For deletes: diff original_content → /dev/null.
        """
        parts: List[str] = []

        for change in changes:
            if change.action == "create":
                diff = self._diff_create(change)
            elif change.action == "delete":
                diff = self._diff_delete(change)
            else:  # update
                diff = self._diff_update(change)

            if diff:
                parts.append(diff)

        return "\n".join(parts) + "\n" if parts else ""

    @staticmethod
    def _diff_create(change: FileChange) -> str:
        """Generate diff for a new file."""
        if change.content is None:
            return ""
        new_lines = change.content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            [],
            new_lines,
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
            lineterm="",
        )
        return "\n".join(diff)

    @staticmethod
    def _diff_delete(change: FileChange) -> str:
        """Generate diff for a deleted file."""
        old_lines = (change.original_content or "").splitlines(keepends=True)
        if not old_lines:
            # Can't generate a meaningful diff without original content
            return f"--- a/{change.path}\n+++ /dev/null\n"
        diff = difflib.unified_diff(
            old_lines,
            [],
            fromfile=f"a/{change.path}",
            tofile=f"/dev/null",
            lineterm="",
        )
        return "\n".join(diff)

    @staticmethod
    def _diff_update(change: FileChange) -> str:
        """Generate diff for an updated file."""
        old_lines = (change.original_content or "").splitlines(keepends=True)
        new_lines = (change.content or "").splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{change.path}",
            tofile=f"b/{change.path}",
            lineterm="",
        )
        return "\n".join(diff)
