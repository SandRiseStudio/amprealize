"""Callback hooks for workspace-agent integration.

These hooks allow the workspace-agent to integrate with external services
(ActionService, ComplianceService, etc.) without depending on them.

Example:
    hooks = WorkspaceHooks(
        on_provision=lambda config, info: log_to_action_service(config, info),
        on_cleanup=lambda run_id, success: update_metrics(run_id, success),
    )
    service = WorkspaceService(hooks=hooks)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from workspace_agent.models import WorkspaceConfig, WorkspaceInfo

logger = logging.getLogger(__name__)


# Type aliases for hook callbacks
OnProvisionHook = Callable[[WorkspaceConfig, WorkspaceInfo], Awaitable[None]]
OnCleanupHook = Callable[[str, bool], Awaitable[None]]
OnExecHook = Callable[[str, str, int], Awaitable[None]]
OnErrorHook = Callable[[str, Exception], Awaitable[None]]


@dataclass
class WorkspaceHooks:
    """Callback hooks for workspace lifecycle events.

    All hooks are optional and async. They should not raise exceptions
    as that would interfere with normal operation.

    Attributes:
        on_provision: Called after workspace is provisioned
        on_cleanup: Called after workspace is cleaned up
        on_exec: Called after command execution (run_id, command, exit_code)
        on_error: Called when an error occurs
    """

    on_provision: Optional[OnProvisionHook] = None
    on_cleanup: Optional[OnCleanupHook] = None
    on_exec: Optional[OnExecHook] = None
    on_error: Optional[OnErrorHook] = None

    async def trigger_provision(self, config: WorkspaceConfig, info: WorkspaceInfo) -> None:
        """Trigger provision hook safely."""
        if self.on_provision:
            try:
                await self.on_provision(config, info)
            except Exception as e:
                logger.warning(f"Provision hook failed: {e}")

    async def trigger_cleanup(self, run_id: str, success: bool) -> None:
        """Trigger cleanup hook safely."""
        if self.on_cleanup:
            try:
                await self.on_cleanup(run_id, success)
            except Exception as e:
                logger.warning(f"Cleanup hook failed: {e}")

    async def trigger_exec(self, run_id: str, command: str, exit_code: int) -> None:
        """Trigger exec hook safely."""
        if self.on_exec:
            try:
                await self.on_exec(run_id, command, exit_code)
            except Exception as e:
                logger.warning(f"Exec hook failed: {e}")

    async def trigger_error(self, run_id: str, error: Exception) -> None:
        """Trigger error hook safely."""
        if self.on_error:
            try:
                await self.on_error(run_id, error)
            except Exception as e:
                logger.warning(f"Error hook failed: {e}")


# Factory functions for common hook patterns

def create_logging_hooks(logger_name: str = "workspace_agent") -> WorkspaceHooks:
    """Create hooks that log all events.

    Args:
        logger_name: Logger name to use

    Returns:
        WorkspaceHooks with logging callbacks
    """
    log = logging.getLogger(logger_name)

    async def on_provision(config: WorkspaceConfig, info: WorkspaceInfo) -> None:
        log.info(f"Provisioned workspace: run_id={info.run_id} container={info.container_name}")

    async def on_cleanup(run_id: str, success: bool) -> None:
        log.info(f"Cleaned up workspace: run_id={run_id} success={success}")

    async def on_exec(run_id: str, command: str, exit_code: int) -> None:
        log.debug(f"Exec in workspace: run_id={run_id} exit_code={exit_code}")

    async def on_error(run_id: str, error: Exception) -> None:
        log.error(f"Workspace error: run_id={run_id} error={error}")

    return WorkspaceHooks(
        on_provision=on_provision,
        on_cleanup=on_cleanup,
        on_exec=on_exec,
        on_error=on_error,
    )
