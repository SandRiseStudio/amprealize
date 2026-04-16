"""Execution Gateway Contracts — Data models for the unified execution engine.

Defines the new execution mode taxonomy and gateway request/response contracts
that replace the previous LOCAL/GITHUB_PR/LOCAL_AND_PR split with a cleaner
container-first model:

- CONTAINER_ISOLATED: Full sandboxing; output via PR or patch (default)
- CONTAINER_CONNECTED: Container with local mount (IDE/CLI)
- LOCAL_DIRECT: No container; trusted local execution

Part of E3 — Agent Execution Loop Rearchitecture (AMPREALIZE-277 / Phase 1).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from .work_item_execution_contracts import AgentExecutionMode


# =============================================================================
# Execution Modes
# =============================================================================


class NewExecutionMode(str, Enum):
    """Execution mode determines workspace provisioning and output handling.

    CONTAINER_ISOLATED:
        All work happens inside a Podman container. Source code is cloned into
        the container workspace. Output is delivered via PR, patch file, or
        downloadable archive. This is the safest mode — the agent has zero
        access to the host filesystem.

        When: Web UI, REST API, MCP from remote client, CI/CD pipelines.

    CONTAINER_CONNECTED:
        Agent runs inside a Podman container but the user's local project
        directory is mounted (read-write) into the container. Changes made
        by the agent appear directly in the user's workspace.

        When: VS Code extension, local CLI with --connected flag.

    LOCAL_DIRECT:
        No container. Agent runs tools directly on the host filesystem with
        the same permissions as the invoking user. Only for trusted, local
        development scenarios.

        When: CLI with --local flag, user explicitly opts in.
    """

    CONTAINER_ISOLATED = "container_isolated"
    CONTAINER_CONNECTED = "container_connected"
    LOCAL_DIRECT = "local_direct"


class OutputTarget(str, Enum):
    """Where the agent's file changes are delivered."""

    PULL_REQUEST = "pull_request"   # GitHub/GitLab/Bitbucket PR/MR
    PATCH_FILE = "patch_file"       # Downloadable .patch file
    LOCAL_SYNC = "local_sync"       # Direct write to local filesystem
    ARCHIVE = "archive"             # Downloadable .tar.gz of workspace


class SourceType(str, Enum):
    """Type of project source to provision."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    BARE_GIT = "bare_git"
    LOCAL_DIR = "local_dir"


# =============================================================================
# Surface-to-mode mapping
# =============================================================================

#: Default execution mode per surface. Can be overridden by project settings.
SURFACE_DEFAULT_MODE: Dict[str, NewExecutionMode] = {
    "web": NewExecutionMode.CONTAINER_ISOLATED,
    "api": NewExecutionMode.CONTAINER_ISOLATED,
    "mcp": NewExecutionMode.CONTAINER_ISOLATED,
    "cli": NewExecutionMode.CONTAINER_CONNECTED,
    "vscode": NewExecutionMode.CONTAINER_CONNECTED,
    "codespaces": NewExecutionMode.CONTAINER_CONNECTED,
    "gitpod": NewExecutionMode.CONTAINER_CONNECTED,
}

#: Surfaces that support LOCAL_DIRECT mode when user opts in.
LOCAL_CAPABLE_SURFACES: frozenset[str] = frozenset({
    "cli", "vscode", "mcp", "codespaces", "gitpod",
})


# =============================================================================
# Gateway Request / Result
# =============================================================================


@dataclass
class ExecutionRequest:
    """Request to execute a work item through the gateway.

    The gateway uses this to resolve execution mode, provision workspace,
    select model, and start the execution loop.
    """

    # Identity
    work_item_id: str
    project_id: str
    org_id: Optional[str] = None
    user_id: str = ""

    # Surface context
    surface: str = "api"                # web, api, mcp, cli, vscode
    workspace_path: Optional[str] = None  # For local/connected modes

    # Source override (auto-detected from project if absent)
    source_type: Optional[SourceType] = None
    source_url: Optional[str] = None
    source_ref: Optional[str] = None    # branch/tag/commit

    # Execution overrides
    mode_override: Optional[NewExecutionMode] = None
    output_target_override: Optional[OutputTarget] = None
    model_override: Optional[str] = None
    agent_id_override: Optional[str] = None
    agent_execution_mode: Optional["AgentExecutionMode"] = None  # GEP or SESSION

    # Idempotency
    idempotency_key: Optional[str] = None

    # Callback
    callback_url: Optional[str] = None

    # Request metadata
    request_id: str = field(default_factory=lambda: f"req-{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ResolvedExecution:
    """Fully resolved execution configuration — produced by the gateway
    before handing off to a mode executor.
    """

    # Core IDs
    run_id: str
    cycle_id: str
    request: ExecutionRequest

    # Resolved mode + output
    mode: NewExecutionMode
    output_target: OutputTarget

    # Source info
    source_type: SourceType
    source_url: Optional[str]
    source_ref: str  # default branch if unspecified

    # Model + credentials
    model_id: str
    api_key: str
    credential_source: str  # "project", "org", "platform"
    is_byok: bool

    # Agent
    agent_id: str
    agent_version_id: Optional[str] = None
    playbook: Dict[str, Any] = field(default_factory=dict)

    # Workspace (populated by executor after provisioning)
    workspace_id: Optional[str] = None
    workspace_path: Optional[str] = None
    container_id: Optional[str] = None

    # Output handling (populated by gateway before execution)
    output_context: Optional[Any] = None  # OutputContext from output_handlers


@dataclass
class ExecutionGatewayResult:
    """Result returned from ExecutionGateway.execute()."""

    success: bool
    run_id: Optional[str] = None
    cycle_id: Optional[str] = None
    mode: Optional[NewExecutionMode] = None
    output_target: Optional[OutputTarget] = None
    message: str = ""
    error: Optional[str] = None


# =============================================================================
# ModeExecutor Protocol
# =============================================================================


@runtime_checkable
class ModeExecutor(Protocol):
    """Protocol for execution mode implementations.

    Each mode (CONTAINER_ISOLATED, CONTAINER_CONNECTED, LOCAL_DIRECT) provides
    an executor that handles workspace provisioning, execution, and cleanup
    according to its isolation guarantees.
    """

    @property
    def mode(self) -> NewExecutionMode:
        """The execution mode this executor handles."""
        ...

    async def provision_workspace(
        self,
        resolved: ResolvedExecution,
    ) -> ResolvedExecution:
        """Provision workspace for execution.

        For container modes, this creates/starts a Podman container and clones
        or mounts the source. For LOCAL_DIRECT, this validates the local path.

        Args:
            resolved: The resolved execution config (mutated in-place with
                      workspace_id, workspace_path, container_id).

        Returns:
            The updated ResolvedExecution with workspace details populated.
        """
        ...

    async def execute(
        self,
        resolved: ResolvedExecution,
        execution_loop: Any,
        *,
        work_item: Any,
        agent: Any,
        agent_version: Any,
        exec_policy: Any,
    ) -> Dict[str, Any]:
        """Run the agent execution loop in the provisioned workspace.

        Args:
            resolved: Fully resolved execution with workspace provisioned.
            execution_loop: The AgentExecutionLoop instance to drive.
            work_item: The WorkItem being executed.
            agent: The Agent performing execution.
            agent_version: Active agent version with playbook.
            exec_policy: ExecutionPolicy controlling permissions.

        Returns:
            Execution result dict from the loop.
        """
        ...

    async def cleanup(
        self,
        resolved: ResolvedExecution,
    ) -> None:
        """Clean up workspace resources after execution.

        For container modes, this stops/removes the container.
        For LOCAL_DIRECT, this is typically a no-op.
        """
        ...


# =============================================================================
# Mode resolution helpers
# =============================================================================


def resolve_execution_mode(
    surface: str,
    mode_override: Optional[NewExecutionMode] = None,
    project_mode: Optional[NewExecutionMode] = None,
) -> NewExecutionMode:
    """Resolve the effective execution mode.

    Priority:
    1. Explicit mode_override from request
    2. Project-level setting (project_mode)
    3. Surface-specific default

    Validates that the surface supports the resolved mode.

    Args:
        surface: The invoking surface (web, api, cli, vscode, etc.)
        mode_override: Explicit override from ExecutionRequest
        project_mode: Default mode from project settings

    Returns:
        Resolved NewExecutionMode

    Raises:
        ValueError: If surface cannot support the resolved mode
    """
    # Step 1: Pick raw mode
    if mode_override is not None:
        candidate = mode_override
    elif project_mode is not None:
        candidate = project_mode
    else:
        candidate = SURFACE_DEFAULT_MODE.get(
            surface.lower(),
            NewExecutionMode.CONTAINER_ISOLATED,
        )

    # Step 2: Validate surface compatibility
    surface_lower = surface.lower()
    if candidate == NewExecutionMode.LOCAL_DIRECT:
        if surface_lower not in LOCAL_CAPABLE_SURFACES:
            raise ValueError(
                f"LOCAL_DIRECT mode requires a local-capable surface "
                f"({', '.join(sorted(LOCAL_CAPABLE_SURFACES))}), "
                f"but '{surface}' was provided."
            )

    return candidate


def resolve_output_target(
    mode: NewExecutionMode,
    output_override: Optional[OutputTarget] = None,
    source_type: Optional[SourceType] = None,
) -> OutputTarget:
    """Resolve the output target based on mode and overrides.

    Args:
        mode: The resolved execution mode
        output_override: Explicit target from ExecutionRequest
        source_type: Source type (affects default PR target)

    Returns:
        Resolved OutputTarget
    """
    if output_override is not None:
        return output_override

    if mode == NewExecutionMode.LOCAL_DIRECT:
        return OutputTarget.LOCAL_SYNC

    if mode == NewExecutionMode.CONTAINER_CONNECTED:
        return OutputTarget.LOCAL_SYNC

    # CONTAINER_ISOLATED — default to PR for git sources, patch otherwise
    if source_type in (SourceType.GITHUB, SourceType.GITLAB, SourceType.BITBUCKET):
        return OutputTarget.PULL_REQUEST
    return OutputTarget.PATCH_FILE
