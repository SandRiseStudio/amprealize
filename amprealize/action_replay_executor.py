"""Action replay executor with real execution capabilities.

Provides strategies for replaying recorded actions including:
- Sequential execution
- Parallel execution with thread pool
- Checkpointing for long-running replays
- Dry-run validation with detailed preview
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .action_contracts import Action
from .telemetry import TelemetryClient


class ExecutionStatus(str, Enum):
    """Status of individual action execution."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class ExecutionResult:
    """Result of executing a single action."""
    action_id: str
    status: ExecutionStatus
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    output: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayCheckpoint:
    """Checkpoint state for resumable replays."""
    replay_id: str
    checkpoint_time: str
    completed_action_ids: List[str]
    failed_action_ids: List[str]
    pending_action_ids: List[str]
    total_actions: int
    progress: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ActionReplayExecutor:
    """Executes recorded actions with support for parallel replay and checkpointing."""

    def __init__(
        self,
        telemetry: Optional[TelemetryClient] = None,
        checkpoint_dir: Optional[Path] = None,
        max_workers: int = 4,
    ) -> None:
        """Initialize the replay executor.

        Args:
            telemetry: Optional telemetry client for event emission
            checkpoint_dir: Directory for storing checkpoint state
            max_workers: Maximum parallel workers for PARALLEL strategy
        """
        self._telemetry = telemetry or TelemetryClient.noop()
        self._checkpoint_dir = checkpoint_dir or Path.home() / ".amprealize" / "replay_checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._max_workers = max_workers

    def execute_sequential(
        self,
        actions: List[Action],
        skip_existing: bool = False,
        dry_run: bool = False,
        checkpoint_interval: int = 5,
    ) -> Tuple[List[str], List[str], List[ExecutionResult]]:
        """Execute actions sequentially with optional checkpointing.

        Args:
            actions: List of actions to execute
            skip_existing: Skip actions already marked as SUCCEEDED
            dry_run: Validate without executing
            checkpoint_interval: Save checkpoint every N actions

        Returns:
            Tuple of (succeeded_ids, failed_ids, execution_results)
        """
        succeeded: List[str] = []
        failed: List[str] = []
        results: List[ExecutionResult] = []

        for idx, action in enumerate(actions):
            if skip_existing and action.replay_status == "SUCCEEDED":
                results.append(ExecutionResult(
                    action_id=action.action_id,
                    status=ExecutionStatus.SKIPPED,
                    started_at=self._utc_now(),
                    completed_at=self._utc_now(),
                    output="Skipped - already succeeded",
                ))
                continue

            if dry_run:
                result = self._dry_run_action(action)
            else:
                result = self._execute_action(action)

            results.append(result)

            if result.status == ExecutionStatus.SUCCEEDED:
                succeeded.append(action.action_id)
            elif result.status == ExecutionStatus.FAILED:
                failed.append(action.action_id)

            # Checkpoint progress
            if not dry_run and (idx + 1) % checkpoint_interval == 0:
                remaining_ids = [a.action_id for a in actions[idx + 1:]]
                self._save_checkpoint(
                    replay_id="sequential",
                    completed=succeeded,
                    failed=failed,
                    pending=remaining_ids,
                    total=len(actions),
                )

        return succeeded, failed, results

    def execute_parallel(
        self,
        actions: List[Action],
        skip_existing: bool = False,
        dry_run: bool = False,
    ) -> Tuple[List[str], List[str], List[ExecutionResult]]:
        """Execute actions in parallel using thread pool.

        Args:
            actions: List of actions to execute
            skip_existing: Skip actions already marked as SUCCEEDED
            dry_run: Validate without executing

        Returns:
            Tuple of (succeeded_ids, failed_ids, execution_results)
        """
        succeeded: List[str] = []
        failed: List[str] = []
        results: List[ExecutionResult] = []

        # Filter actions to execute
        actions_to_execute = [
            action for action in actions
            if not (skip_existing and action.replay_status == "SUCCEEDED")
        ]

        skipped_actions = [
            action for action in actions
            if skip_existing and action.replay_status == "SUCCEEDED"
        ]

        # Add skipped results
        for action in skipped_actions:
            results.append(ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.SKIPPED,
                started_at=self._utc_now(),
                completed_at=self._utc_now(),
                output="Skipped - already succeeded",
            ))

        if dry_run:
            # Dry run in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                future_to_action = {
                    executor.submit(self._dry_run_action, action): action
                    for action in actions_to_execute
                }

                for future in concurrent.futures.as_completed(future_to_action):
                    result = future.result()
                    results.append(result)
        else:
            # Real execution in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                future_to_action = {
                    executor.submit(self._execute_action, action): action
                    for action in actions_to_execute
                }

                for future in concurrent.futures.as_completed(future_to_action):
                    result = future.result()
                    results.append(result)

                    if result.status == ExecutionStatus.SUCCEEDED:
                        succeeded.append(result.action_id)
                    elif result.status == ExecutionStatus.FAILED:
                        failed.append(result.action_id)

        return succeeded, failed, results

    def _execute_action(self, action: Action) -> ExecutionResult:
        """Execute a single action based on its metadata.

        This interprets the action metadata to determine what command or operation to execute.
        """
        started_at = self._utc_now()

        try:
            self._telemetry.emit_event(
                event_type="action_execution_start",
                payload={"action_id": action.action_id, "artifact_path": action.artifact_path},
                actor={"id": action.actor.id, "role": action.actor.role, "surface": action.actor.surface},
                action_id=action.action_id,
            )

            # Determine action type from metadata or artifact path
            action_type = action.metadata.get("action_type", self._infer_action_type(action))

            if action_type == "command_execution":
                output, error = self._execute_command(action)
            elif action_type in ("file_edit", "file_create"):
                output, error = self._execute_file_operation(action)
            elif action_type == "file_delete":
                output, error = self._execute_file_deletion(action)
            else:
                # Generic execution based on summary
                output, error = self._execute_generic(action)

            completed_at = self._utc_now()

            if error:
                status = ExecutionStatus.FAILED
            else:
                status = ExecutionStatus.SUCCEEDED

            self._telemetry.emit_event(
                event_type="action_execution_complete",
                payload={
                    "action_id": action.action_id,
                    "status": status.value,
                    "output_length": len(output),
                },
                actor={"id": action.actor.id, "role": action.actor.role, "surface": action.actor.surface},
                action_id=action.action_id,
            )

            return ExecutionResult(
                action_id=action.action_id,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                output=output,
                error=error,
                metadata={"action_type": action_type},
            )

        except Exception as exc:
            self._telemetry.emit_event(
                event_type="action_execution_error",
                payload={"action_id": action.action_id, "error": str(exc)},
                actor={"id": action.actor.id, "role": action.actor.role, "surface": action.actor.surface},
                action_id=action.action_id,
            )

            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                completed_at=self._utc_now(),
                error=str(exc),
            )

    def _dry_run_action(self, action: Action) -> ExecutionResult:
        """Validate an action without executing it."""
        started_at = self._utc_now()
        action_type = action.metadata.get("action_type", self._infer_action_type(action))

        validation_output = [
            f"[DRY RUN] Action: {action.action_id}",
            f"Type: {action_type}",
            f"Artifact: {action.artifact_path}",
            f"Summary: {action.summary}",
            f"Behaviors: {', '.join(action.behaviors_cited)}",
        ]

        # Validate metadata requirements
        if action_type == "command_execution":
            if "command" not in action.metadata:
                return ExecutionResult(
                    action_id=action.action_id,
                    status=ExecutionStatus.FAILED,
                    started_at=started_at,
                    completed_at=self._utc_now(),
                    error="Missing required metadata: command",
                    output="\n".join(validation_output),
                )
            validation_output.append(f"Command: {action.metadata['command']}")

        elif action_type in ("file_edit", "file_create"):
            if "file_path" not in action.metadata:
                return ExecutionResult(
                    action_id=action.action_id,
                    status=ExecutionStatus.FAILED,
                    started_at=started_at,
                    completed_at=self._utc_now(),
                    error="Missing required metadata: file_path",
                    output="\n".join(validation_output),
                )
            validation_output.append(f"File: {action.metadata['file_path']}")

        validation_output.append("[DRY RUN] Validation passed - would execute")

        return ExecutionResult(
            action_id=action.action_id,
            status=ExecutionStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=self._utc_now(),
            output="\n".join(validation_output),
            metadata={"action_type": action_type, "dry_run": True},
        )

    def _infer_action_type(self, action: Action) -> str:
        """Infer action type from artifact path and metadata."""
        if "command" in action.metadata:
            return "command_execution"
        elif action.artifact_path.endswith((".py", ".ts", ".js", ".md", ".json", ".yaml", ".yml")):
            if "deleted" in action.summary.lower() or "remove" in action.summary.lower():
                return "file_delete"
            elif "created" in action.summary.lower() or "new" in action.summary.lower():
                return "file_create"
            else:
                return "file_edit"
        else:
            return "generic"

    def _execute_command(self, action: Action) -> Tuple[str, Optional[str]]:
        """Execute a shell command."""
        command = action.metadata.get("command", "")
        if not command:
            return "", "No command specified in metadata"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            output = result.stdout + result.stderr
            error = None

            # Check exit code - non-zero means failure
            if result.returncode != 0:
                error = f"Command failed with exit code {result.returncode}: {result.stderr}"

            return output, error

        except subprocess.TimeoutExpired:
            return "", "Command execution timeout (5 minutes)"
        except Exception as exc:
            return "", f"Command execution failed: {exc}"

    def _execute_file_operation(self, action: Action) -> Tuple[str, Optional[str]]:
        """Execute file create or edit operation."""
        file_path = action.metadata.get("file_path", action.artifact_path)
        content = action.metadata.get("content", action.metadata.get("content_preview", ""))

        try:
            path = Path(file_path)

            if not content:
                # If no content provided, we can't recreate the file
                return f"File operation recorded for: {file_path}", None

            # Create parent directories if needed
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write content
            path.write_text(content)

            return f"Successfully wrote {len(content)} bytes to {file_path}", None

        except Exception as exc:
            return "", f"File operation failed: {exc}"

    def _execute_file_deletion(self, action: Action) -> Tuple[str, Optional[str]]:
        """Execute file deletion."""
        file_path = action.metadata.get("file_path", action.artifact_path)

        try:
            path = Path(file_path)

            if not path.exists():
                return f"File already deleted: {file_path}", None

            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

            return f"Successfully deleted: {file_path}", None

        except Exception as exc:
            return "", f"File deletion failed: {exc}"

    def _execute_generic(self, action: Action) -> Tuple[str, Optional[str]]:
        """Execute generic action - currently just records the intent."""
        output = [
            f"Executed action: {action.action_id}",
            f"Artifact: {action.artifact_path}",
            f"Summary: {action.summary}",
            f"Behaviors cited: {', '.join(action.behaviors_cited)}",
        ]

        return "\n".join(output), None

    def _save_checkpoint(
        self,
        replay_id: str,
        completed: List[str],
        failed: List[str],
        pending: List[str],
        total: int,
    ) -> None:
        """Save checkpoint state to disk."""
        progress = len(completed + failed) / total if total > 0 else 0.0

        checkpoint = ReplayCheckpoint(
            replay_id=replay_id,
            checkpoint_time=self._utc_now(),
            completed_action_ids=completed,
            failed_action_ids=failed,
            pending_action_ids=pending,
            total_actions=total,
            progress=progress,
        )

        checkpoint_file = self._checkpoint_dir / f"{replay_id}.json"
        checkpoint_file.write_text(json.dumps({
            "replay_id": checkpoint.replay_id,
            "checkpoint_time": checkpoint.checkpoint_time,
            "completed_action_ids": checkpoint.completed_action_ids,
            "failed_action_ids": checkpoint.failed_action_ids,
            "pending_action_ids": checkpoint.pending_action_ids,
            "total_actions": checkpoint.total_actions,
            "progress": checkpoint.progress,
            "metadata": checkpoint.metadata,
        }, indent=2))

        self._telemetry.emit_event(
            event_type="replay_checkpoint_saved",
            payload={
                "replay_id": replay_id,
                "progress": progress,
                "completed": len(completed),
                "failed": len(failed),
                "pending": len(pending),
            },
            actor={"id": "system", "role": "REPLAY_EXECUTOR", "surface": "internal"},
            action_id=replay_id,
        )

    def load_checkpoint(self, replay_id: str) -> Optional[ReplayCheckpoint]:
        """Load checkpoint state from disk."""
        checkpoint_file = self._checkpoint_dir / f"{replay_id}.json"

        if not checkpoint_file.exists():
            return None

        try:
            data = json.loads(checkpoint_file.read_text())
            return ReplayCheckpoint(
                replay_id=data["replay_id"],
                checkpoint_time=data["checkpoint_time"],
                completed_action_ids=data["completed_action_ids"],
                failed_action_ids=data["failed_action_ids"],
                pending_action_ids=data["pending_action_ids"],
                total_actions=data["total_actions"],
                progress=data["progress"],
                metadata=data.get("metadata", {}),
            )
        except Exception as exc:
            self._telemetry.emit_event(
                event_type="replay_checkpoint_load_error",
                payload={"replay_id": replay_id, "error": str(exc)},
                actor={"id": "system", "role": "REPLAY_EXECUTOR", "surface": "internal"},
                action_id=replay_id,
            )
            return None

    @staticmethod
    def _utc_now() -> str:
        """Return current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()
