"""Run service data contracts.

These dataclasses are shared across CLI, REST, and MCP surfaces. They align with the
contracts described in `docs/contracts/MCP_SERVER_DESIGN.md` and planned RunService schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from .action_contracts import Actor


def utc_now_iso() -> str:
    """Return the current timestamp in RFC3339 format."""

    return datetime.now(UTC).isoformat()


class RunStatus:
    """String constants for run status values."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class RunStep:
    """Represents a step within a run for progress tracking."""

    step_id: str
    name: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    """Persistent representation of a run."""

    run_id: str
    created_at: str
    updated_at: str
    actor: Actor
    status: str = RunStatus.PENDING
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    behavior_ids: List[str] = field(default_factory=list)
    current_step: Optional[str] = None
    progress_pct: float = 0.0
    message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    steps: List[RunStep] = field(default_factory=list)
    # Agent interaction linking fields
    origin_run_id: Optional[str] = None  # Parent run for delegations
    delegation_id: Optional[str] = None  # Link to DelegationResponse
    handoff_from_run_id: Optional[str] = None  # Previous run in handoff chain
    # User credential context
    triggering_user_id: Optional[str] = None  # User whose credentials to use for GitHub ops

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["actor"] = asdict(self.actor)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


@dataclass
class RunCreateRequest:
    """Incoming payload to create a run."""

    actor: Actor
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    behavior_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    initial_message: Optional[str] = None
    total_steps: Optional[int] = None
    # Agent interaction linking fields
    origin_run_id: Optional[str] = None  # Parent run for delegations
    delegation_id: Optional[str] = None  # Link to DelegationResponse
    handoff_from_run_id: Optional[str] = None  # Previous run in handoff chain
    # User credential context
    triggering_user_id: Optional[str] = None  # User whose credentials to use for GitHub ops


@dataclass
class RunProgressUpdate:
    """Incoming payload for updating run progress."""

    status: Optional[str] = None
    progress_pct: Optional[float] = None
    message: Optional[str] = None
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    step_status: Optional[str] = None
    tokens_generated: Optional[int] = None
    tokens_baseline: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunCompletion:
    """Incoming payload when completing a run."""

    status: str
    outputs: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunLogEntry:
    """A single log entry for a run."""

    log_id: str
    timestamp: str
    level: str
    service: str
    message: str
    action_id: Optional[str] = None
    session_id: Optional[str] = None
    actor_surface: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunLogsRequest:
    """Request parameters for fetching run logs."""

    run_id: str
    level: Optional[str] = None  # Minimum log level
    start_time: Optional[str] = None  # ISO 8601
    end_time: Optional[str] = None  # ISO 8601
    limit: int = 100
    after: Optional[str] = None  # Cursor for pagination (log_id)
    search: Optional[str] = None
    include_steps: bool = True


@dataclass
class RunLogsResponse:
    """Response from fetching run logs."""

    run_id: str
    logs: List[RunLogEntry]
    steps: List[RunStep] = field(default_factory=list)
    total: int = 0
    has_more: bool = False
    next_cursor: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "logs": [log.to_dict() for log in self.logs],
            "steps": [step.to_dict() for step in self.steps],
            "total": self.total,
            "has_more": self.has_more,
            "next_cursor": self.next_cursor,
        }
