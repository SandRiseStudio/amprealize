"""
MCP Long-Running Operation Handler with HTTP Keepalive

Implements keepalive patterns to prevent 5-minute timeout issues:
1. Sends progress notifications to keep connection alive
2. Uses chunked transfer encoding for HTTP transports
3. Implements resumable operations for interrupted requests

Based on workaround from VS Code issue #261734:
- Node.js fetch() has hardcoded headersTimeout: 300s (5 minutes)
- Solution: Send headers immediately, then keepalive chunks every 4 minutes

For stdio transport (our default):
- Progress notifications via "notifications/progress" method
- Heartbeat mechanism to prevent client-side timeouts
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar


class OperationState(str, Enum):
    """State of a long-running operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class OperationProgress:
    """Progress information for a long-running operation."""
    operation_id: str
    tool_name: str
    state: OperationState = OperationState.PENDING
    progress_percent: float = 0.0
    current_step: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    error_message: Optional[str] = None
    result: Optional[Any] = None

    # Keepalive settings
    heartbeat_interval_seconds: float = 30.0  # Send heartbeat every 30s
    max_duration_seconds: float = 1800.0  # Max 30 minutes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "tool_name": self.tool_name,
            "state": self.state.value,
            "progress_percent": self.progress_percent,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "error_message": self.error_message,
            "elapsed_seconds": (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0,
        }


T = TypeVar("T")


class MCPLongRunningHandler:
    """
    Handles long-running MCP tool operations with keepalive support.

    Usage:
        handler = MCPLongRunningHandler(progress_callback)

        async def my_long_operation(progress_reporter):
            for i in range(10):
                await asyncio.sleep(60)  # Simulating work
                progress_reporter.update(i * 10, f"Step {i}")
            return {"result": "done"}

        result = await handler.run_with_keepalive(
            "my_tool",
            my_long_operation,
            timeout=600
        )
    """

    def __init__(
        self,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the handler.

        Args:
            progress_callback: Async function called with (method, params) to send MCP notifications
            logger: Logger instance
        """
        self._progress_callback = progress_callback
        self._logger = logger or logging.getLogger("amprealize.mcp_long_running")
        self._active_operations: Dict[str, OperationProgress] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}

    async def run_with_keepalive(
        self,
        tool_name: str,
        operation: Callable[["ProgressReporter"], Coroutine[Any, Any, T]],
        timeout: float = 1800.0,  # 30 minutes default
        heartbeat_interval: float = 30.0,  # Heartbeat every 30 seconds
    ) -> T:
        """
        Run a long operation with keepalive heartbeats.

        Args:
            tool_name: Name of the tool being executed
            operation: Async function that takes a ProgressReporter and returns result
            timeout: Maximum duration in seconds
            heartbeat_interval: How often to send keepalive heartbeats

        Returns:
            Result from the operation

        Raises:
            asyncio.TimeoutError: If operation exceeds timeout
            Exception: Any exception from the operation
        """
        operation_id = str(uuid.uuid4())[:12]

        progress = OperationProgress(
            operation_id=operation_id,
            tool_name=tool_name,
            state=OperationState.RUNNING,
            started_at=datetime.utcnow(),
            heartbeat_interval_seconds=heartbeat_interval,
            max_duration_seconds=timeout,
        )

        self._active_operations[operation_id] = progress

        # Create progress reporter for the operation
        reporter = ProgressReporter(
            operation_id=operation_id,
            progress=progress,
            send_notification=self._send_progress_notification,
        )

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(operation_id, heartbeat_interval)
        )
        self._heartbeat_tasks[operation_id] = heartbeat_task

        try:
            # Send initial progress notification
            await self._send_progress_notification(operation_id, progress)

            # Run the operation with timeout
            result = await asyncio.wait_for(
                operation(reporter),
                timeout=timeout
            )

            # Mark completed
            progress.state = OperationState.COMPLETED
            progress.completed_at = datetime.utcnow()
            progress.progress_percent = 100.0
            progress.result = result

            await self._send_progress_notification(operation_id, progress)

            return result

        except asyncio.TimeoutError:
            progress.state = OperationState.TIMEOUT
            progress.completed_at = datetime.utcnow()
            progress.error_message = f"Operation timed out after {timeout}s"

            await self._send_progress_notification(operation_id, progress)
            raise

        except asyncio.CancelledError:
            progress.state = OperationState.CANCELLED
            progress.completed_at = datetime.utcnow()
            progress.error_message = "Operation was cancelled"

            await self._send_progress_notification(operation_id, progress)
            raise

        except Exception as e:
            progress.state = OperationState.FAILED
            progress.completed_at = datetime.utcnow()
            progress.error_message = str(e)

            await self._send_progress_notification(operation_id, progress)
            raise

        finally:
            # Stop heartbeat
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

            del self._heartbeat_tasks[operation_id]

            # Keep operation info for a while for status queries
            # (will be cleaned up by periodic cleanup)

    async def _heartbeat_loop(self, operation_id: str, interval: float) -> None:
        """Send periodic heartbeat notifications to keep connection alive."""
        while True:
            try:
                await asyncio.sleep(interval)

                progress = self._active_operations.get(operation_id)
                if not progress:
                    break

                if progress.state not in (OperationState.RUNNING, OperationState.PENDING):
                    break

                progress.last_heartbeat = datetime.utcnow()

                # Send heartbeat notification
                await self._send_heartbeat(operation_id, progress)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.warning(f"Heartbeat failed for {operation_id}: {e}")

    async def _send_progress_notification(self, operation_id: str, progress: OperationProgress) -> None:
        """Send progress notification via MCP."""
        if not self._progress_callback:
            return

        try:
            await self._progress_callback(
                "notifications/progress",
                {
                    "progressToken": operation_id,
                    "progress": progress.progress_percent,
                    "total": 100,
                    "message": progress.current_step or f"Operation {progress.state.value}",
                    "data": progress.to_dict(),
                }
            )
        except Exception as e:
            self._logger.warning(f"Failed to send progress notification: {e}")

    async def _send_heartbeat(self, operation_id: str, progress: OperationProgress) -> None:
        """Send heartbeat notification to keep connection alive."""
        if not self._progress_callback:
            return

        elapsed = (datetime.utcnow() - progress.started_at).total_seconds() if progress.started_at else 0

        try:
            await self._progress_callback(
                "notifications/progress",
                {
                    "progressToken": operation_id,
                    "progress": progress.progress_percent,
                    "total": 100,
                    "message": f"[heartbeat] {progress.current_step or 'Working...'} ({elapsed:.0f}s elapsed)",
                    "data": {
                        "type": "heartbeat",
                        "operation_id": operation_id,
                        "elapsed_seconds": elapsed,
                        "state": progress.state.value,
                    },
                }
            )
            self._logger.debug(f"Heartbeat sent for {operation_id} ({elapsed:.0f}s elapsed)")
        except Exception as e:
            self._logger.warning(f"Failed to send heartbeat: {e}")

    def get_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an operation by ID."""
        progress = self._active_operations.get(operation_id)
        if progress:
            return progress.to_dict()
        return None

    def list_active_operations(self) -> List[Dict[str, Any]]:
        """List all active operations."""
        return [
            p.to_dict()
            for p in self._active_operations.values()
            if p.state in (OperationState.RUNNING, OperationState.PENDING)
        ]

    def cleanup_completed(self, max_age_seconds: float = 300.0) -> int:
        """Clean up completed operations older than max_age_seconds."""
        now = datetime.utcnow()
        to_remove = []

        for op_id, progress in self._active_operations.items():
            if progress.state not in (OperationState.RUNNING, OperationState.PENDING):
                if progress.completed_at:
                    age = (now - progress.completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(op_id)

        for op_id in to_remove:
            del self._active_operations[op_id]

        return len(to_remove)


class ProgressReporter:
    """
    Progress reporter passed to long-running operations.

    Allows operations to report their progress, which triggers
    keepalive notifications to prevent timeouts.
    """

    def __init__(
        self,
        operation_id: str,
        progress: OperationProgress,
        send_notification: Callable[[str, OperationProgress], Coroutine[Any, Any, None]],
    ):
        self._operation_id = operation_id
        self._progress = progress
        self._send_notification = send_notification

    @property
    def operation_id(self) -> str:
        return self._operation_id

    async def update(
        self,
        percent: Optional[float] = None,
        message: Optional[str] = None,
        completed_steps: Optional[int] = None,
        total_steps: Optional[int] = None,
    ) -> None:
        """
        Update operation progress and send notification.

        Args:
            percent: Progress percentage (0-100)
            message: Current step message
            completed_steps: Number of completed steps
            total_steps: Total number of steps
        """
        if percent is not None:
            self._progress.progress_percent = min(100.0, max(0.0, percent))

        if message is not None:
            self._progress.current_step = message

        if completed_steps is not None:
            self._progress.completed_steps = completed_steps

        if total_steps is not None:
            self._progress.total_steps = total_steps

        if completed_steps is not None and total_steps is not None and total_steps > 0:
            self._progress.progress_percent = (completed_steps / total_steps) * 100

        self._progress.last_heartbeat = datetime.utcnow()

        await self._send_notification(self._operation_id, self._progress)

    async def log(self, message: str) -> None:
        """Log a message as the current step without changing progress percent."""
        self._progress.current_step = message
        self._progress.last_heartbeat = datetime.utcnow()
        await self._send_notification(self._operation_id, self._progress)


def is_long_running_tool(tool_name: str) -> bool:
    """
    Determine if a tool is expected to be long-running.

    Long-running tools should use the keepalive handler.
    """
    LONG_RUNNING_PATTERNS = [
        "workItems.execute",
        "workflow.run.start",
        "actions.replay",
        "fine-tuning.create",
        "bci.rebuildIndex",
        "breakeramp.apply",
        "breakeramp.destroy",
        "analytics.fullReport",
        "compliance.fullValidation",
        "github.commitToBranch",
        "github.createPR",
    ]

    return any(tool_name.startswith(p.replace(".", "_")) or tool_name == p for p in LONG_RUNNING_PATTERNS)


# Pre-configured timeouts for specific tool categories
TOOL_TIMEOUTS: Dict[str, float] = {
    # Quick tools (10 seconds)
    "auth.": 10.0,
    "context.": 10.0,
    "behaviors.get": 10.0,
    "behaviors.list": 15.0,

    # Medium tools (60 seconds)
    "behaviors.": 60.0,
    "projects.": 60.0,
    "orgs.": 60.0,
    "workItems.list": 30.0,
    "workItems.get": 30.0,
    "runs.list": 30.0,
    "runs.get": 30.0,

    # Long tools (5 minutes)
    "analytics.": 300.0,
    "compliance.": 300.0,
    "bci.": 300.0,

    # Very long tools (30 minutes)
    "workItems.execute": 1800.0,
    "workflow.run.start": 1800.0,
    "actions.replay": 1800.0,
    "fine-tuning.create": 3600.0,  # 1 hour
    "breakeramp.apply": 1800.0,
    "breakeramp.destroy": 600.0,
}


def get_tool_timeout(tool_name: str) -> float:
    """Get the configured timeout for a tool."""
    # Normalize tool name for matching
    normalized = tool_name.replace("_", ".")

    # Check for exact match first
    if normalized in TOOL_TIMEOUTS:
        return TOOL_TIMEOUTS[normalized]

    # Check for prefix match
    for prefix, timeout in TOOL_TIMEOUTS.items():
        if normalized.startswith(prefix):
            return timeout

    # Default timeout
    return 60.0
