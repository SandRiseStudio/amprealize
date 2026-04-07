"""Data models for the execution queue.

Defines the job structure, priorities, and result types used throughout
the queue system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import json
import uuid


class Priority(str, Enum):
    """Job priority levels.

    Priority affects which stream the job is placed in and the order
    workers process jobs.
    """
    HIGH = "high"      # Human-initiated, interactive - lowest latency
    NORMAL = "normal"  # Standard agent runs
    LOW = "low"        # Background/batch operations - can be delayed


class JobState(str, Enum):
    """Current state of a job in the queue."""
    PENDING = "pending"        # In queue, not yet claimed
    CLAIMED = "claimed"        # Worker has claimed, processing
    COMPLETED = "completed"    # Successfully finished
    FAILED = "failed"          # Failed, may retry
    DEAD_LETTER = "dead_letter"  # Exceeded retries, in DLQ


class ExecutionStatus(str, Enum):
    """Outcome status for completed jobs."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ExecutionJob:
    """A job to be executed by a worker.

    This represents a single agent execution request that flows through
    the queue system. It contains all context needed for:
    - Tenant isolation (user_id, org_id)
    - Quota enforcement (timeout_seconds, priority)
    - Execution (agent_id, work_item_id, payload)

    Attributes:
        job_id: Unique identifier for this job
        run_id: Associated Run record ID for tracking
        work_item_id: The work item being executed
        agent_id: The agent to execute
        priority: Queue priority (affects latency)
        user_id: User who initiated the execution
        org_id: Organization context (None for user-owned projects)
        project_id: Project containing the work item
        model_override: Optional model to use instead of agent default
        timeout_seconds: Max execution time before termination
        submitted_at: When the job was enqueued
        payload: Additional execution parameters
        retry_count: Number of times this job has been retried
        last_error: Error message from last failed attempt
    """
    job_id: str
    run_id: str
    work_item_id: str
    agent_id: str
    priority: Priority
    user_id: str
    project_id: str
    timeout_seconds: int = 600  # 10 minutes default
    org_id: Optional[str] = None
    model_override: Optional[str] = None
    cycle_id: Optional[str] = None  # TaskCycle ID for GEP phase tracking
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    last_error: Optional[str] = None

    @classmethod
    def create(
        cls,
        run_id: str,
        work_item_id: str,
        agent_id: str,
        user_id: str,
        project_id: str,
        priority: Priority = Priority.NORMAL,
        org_id: Optional[str] = None,
        model_override: Optional[str] = None,
        cycle_id: Optional[str] = None,
        timeout_seconds: int = 600,
        payload: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionJob":
        """Create a new execution job with generated ID."""
        return cls(
            job_id=str(uuid.uuid4()),
            run_id=run_id,
            work_item_id=work_item_id,
            agent_id=agent_id,
            priority=priority,
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
            model_override=model_override,
            cycle_id=cycle_id,
            timeout_seconds=timeout_seconds,
            payload=payload or {},
        )

    def get_isolation_scope(self) -> str:
        """Get the tenant isolation scope for this job.

        Returns org-scoped if org_id exists, otherwise user-scoped.
        This determines workspace pool allocation.
        """
        if self.org_id:
            return f"org:{self.org_id}"
        return f"user:{self.user_id}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for Redis storage.

        Note: Redis XADD doesn't accept None values, so we convert them to
        empty strings and filter them on deserialization.
        """
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "work_item_id": self.work_item_id,
            "agent_id": self.agent_id,
            "priority": self.priority.value,
            "user_id": self.user_id,
            "org_id": self.org_id or "",  # Redis doesn't accept None
            "project_id": self.project_id,
            "model_override": self.model_override or "",  # Redis doesn't accept None
            "cycle_id": self.cycle_id or "",  # Redis doesn't accept None
            "timeout_seconds": self.timeout_seconds,
            "submitted_at": self.submitted_at.isoformat(),
            "payload": json.dumps(self.payload),
            "retry_count": self.retry_count,
            "last_error": self.last_error or "",  # Redis doesn't accept None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionJob":
        """Deserialize from dictionary (Redis storage).

        Note: Redis returns keys as bytes (b'key'), so we decode both keys
        and values before processing.
        """
        # Handle bytes from Redis - decode keys AND values
        def decode_key(key: Any) -> str:
            if isinstance(key, bytes):
                return key.decode("utf-8")
            return str(key)

        def decode_value(value: Any) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8")
            return str(value) if value is not None else ""

        # Decode all keys in the data dictionary first (Redis returns bytes keys)
        decoded_data = {decode_key(k): v for k, v in data.items()}

        payload_str = decode_value(decoded_data.get("payload", "{}"))
        try:
            payload = json.loads(payload_str) if payload_str else {}
        except json.JSONDecodeError:
            payload = {}

        submitted_str = decode_value(decoded_data.get("submitted_at", ""))
        try:
            submitted_at = datetime.fromisoformat(submitted_str) if submitted_str else datetime.now(timezone.utc)
        except ValueError:
            submitted_at = datetime.now(timezone.utc)

        org_id_raw = decoded_data.get("org_id")
        org_id_decoded = decode_value(org_id_raw) if org_id_raw else ""
        org_id = org_id_decoded if org_id_decoded and org_id_decoded != "None" else None

        model_override_raw = decoded_data.get("model_override")
        model_override_decoded = decode_value(model_override_raw) if model_override_raw else ""
        model_override = model_override_decoded if model_override_decoded and model_override_decoded != "None" else None

        cycle_id_raw = decoded_data.get("cycle_id")
        cycle_id_decoded = decode_value(cycle_id_raw) if cycle_id_raw else ""
        cycle_id = cycle_id_decoded if cycle_id_decoded and cycle_id_decoded != "None" else None

        last_error_raw = decoded_data.get("last_error")
        last_error_decoded = decode_value(last_error_raw) if last_error_raw else ""
        last_error = last_error_decoded if last_error_decoded and last_error_decoded != "None" else None

        retry_count_raw = decoded_data.get("retry_count", 0)
        retry_count = int(decode_value(retry_count_raw)) if retry_count_raw else 0

        timeout_raw = decoded_data.get("timeout_seconds", 600)
        timeout_seconds = int(decode_value(timeout_raw)) if timeout_raw else 600

        return cls(
            job_id=decode_value(decoded_data.get("job_id", "")),
            run_id=decode_value(decoded_data.get("run_id", "")),
            work_item_id=decode_value(decoded_data.get("work_item_id", "")),
            agent_id=decode_value(decoded_data.get("agent_id", "")),
            priority=Priority(decode_value(decoded_data.get("priority", "normal"))),
            user_id=decode_value(decoded_data.get("user_id", "")),
            org_id=org_id,
            project_id=decode_value(decoded_data.get("project_id", "")),
            model_override=model_override,
            cycle_id=cycle_id,
            timeout_seconds=timeout_seconds,
            submitted_at=submitted_at,
            payload=payload,
            retry_count=retry_count,
            last_error=last_error,
        )


@dataclass
class ExecutionResult:
    """Result of executing a job.

    Returned by workers after job completion (success or failure).
    Used for:
    - Updating run status
    - Determining retry eligibility
    - Metrics collection
    """
    job_id: str
    run_id: str
    status: ExecutionStatus
    started_at: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None
    output: Optional[Dict[str, Any]] = None

    @property
    def duration_seconds(self) -> float:
        """Calculate execution duration in seconds."""
        return (self.completed_at - self.started_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "output": self.output,
        }
