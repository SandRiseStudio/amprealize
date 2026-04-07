"""Data contracts for the ActionService stub.

These structures align with the schemas defined in `docs/contracts/ACTION_SERVICE_CONTRACT.md`.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .surfaces import normalize_actor_surface


def utc_now_iso() -> str:
    """Return the current timestamp in RFC3339 format."""

    return datetime.now(timezone.utc).isoformat()


@dataclass
class Actor:
    """Represents the actor performing an action."""

    id: str
    role: str
    surface: str

    def __post_init__(self) -> None:  # noqa: D401 - trivial normalization
        # Normalize the surface once so downstream persistence and telemetry
        # always observe canonical casing regardless of the input source.
        self.surface = normalize_actor_surface(self.surface)


@dataclass
class Action:
    """Stored action record with parity-ready serialization."""

    action_id: str
    timestamp: str
    actor: Actor
    artifact_path: str
    summary: str
    behaviors_cited: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    related_run_id: Optional[str] = None
    audit_log_event_id: Optional[str] = None
    checksum: str = ""
    replay_status: str = "NOT_STARTED"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""

        data = asdict(self)
        data["actor"] = asdict(self.actor)
        return data

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Action":
        """Rehydrate an Action from a cached or serialized dictionary."""

        actor_payload = payload.get("actor") or {}
        actor = Actor(
            id=actor_payload.get("id", "unknown"),
            role=actor_payload.get("role", "UNKNOWN"),
            surface=actor_payload.get("surface", "UNKNOWN"),
        )

        return Action(
            action_id=payload["action_id"],
            timestamp=payload["timestamp"],
            actor=actor,
            artifact_path=payload["artifact_path"],
            summary=payload["summary"],
            behaviors_cited=list(payload.get("behaviors_cited", [])),
            metadata=deepcopy(payload.get("metadata") or {}),
            related_run_id=payload.get("related_run_id"),
            audit_log_event_id=payload.get("audit_log_event_id"),
            checksum=payload.get("checksum", ""),
            replay_status=payload.get("replay_status", "NOT_STARTED"),
        )


@dataclass
class ActionCreateRequest:
    """Incoming payload for creating an action."""

    artifact_path: str
    summary: str
    behaviors_cited: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    related_run_id: Optional[str] = None
    checksum: Optional[str] = None
    audit_log_event_id: Optional[str] = None


@dataclass
class ReplayOptions:
    skip_existing: bool = False
    dry_run: bool = False


@dataclass
class ReplayRequest:
    """Request payload for replaying actions."""

    action_ids: List[str]
    strategy: str = "SEQUENTIAL"
    options: ReplayOptions = field(default_factory=ReplayOptions)


@dataclass
class ReplayStatus:
    """State of a replay job."""

    replay_id: str
    status: str
    progress: float
    logs: List[str] = field(default_factory=list)
    failed_action_ids: List[str] = field(default_factory=list)
    action_ids: List[str] = field(default_factory=list)
    completed_action_ids: List[str] = field(default_factory=list)
    audit_log_event_id: Optional[str] = None
    strategy: str = "SEQUENTIAL"
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    actor_surface: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
