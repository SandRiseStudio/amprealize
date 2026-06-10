"""ActionService stub implementation aligning with the documented contract."""

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayRequest,
    ReplayStatus,
    utc_now_iso,
)
from .action_replay_executor import ActionReplayExecutor, ExecutionStatus
from .execution_observability import sanitize_observability_payload
from .telemetry import TelemetryClient


class ActionServiceError(Exception):
    """Base error for ActionService operations."""


class ActionNotFoundError(ActionServiceError):
    """Raised when an action is not found in the backing store."""


class ReplayNotFoundError(ActionServiceError):
    """Raised when a replay job is unknown."""


class ActionService:
    """In-memory ActionService stub for parity testing.

    The service mimics the behavior described in `docs/contracts/ACTION_SERVICE_CONTRACT.md` while
    remaining lightweight enough for unit tests. It stores actions in memory and
    uses ActionReplayExecutor for real execution with support for sequential/parallel
    strategies and checkpointing.
    """

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        self._actions: Dict[str, Action] = {}
        self._replays: Dict[str, ReplayStatus] = {}
        self._telemetry = telemetry or TelemetryClient.noop()
        self._executor = ActionReplayExecutor(telemetry=self._telemetry)

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------
    def create_action(self, request: ActionCreateRequest, actor: Actor) -> Action:
        """Create a new action record and return the stored entity."""

        checksum = request.checksum or self._calculate_checksum(request)
        action_id = str(uuid.uuid4())
        trace_id = self._trace_value(request, "trace_id") or request.related_run_id
        span_id = self._trace_value(request, "span_id") or f"action:{action_id}"
        parent_span_id = self._trace_value(request, "parent_span_id")
        outcome_ref = self._trace_value(request, "outcome_ref")
        action = Action(
            action_id=action_id,
            timestamp=utc_now_iso(),
            actor=actor,
            artifact_path=request.artifact_path,
            summary=request.summary,
            behaviors_cited=list(request.behaviors_cited),
            metadata=deepcopy(request.metadata),
            related_run_id=request.related_run_id,
            audit_log_event_id=request.audit_log_event_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            outcome_ref=outcome_ref,
            checksum=checksum,
            replay_status="NOT_STARTED",
        )
        self._actions[action.action_id] = action
        self._telemetry.emit_event(
            event_type="action_recorded",
            payload={
                "artifact_path": action.artifact_path,
                "summary": action.summary,
                "behaviors_cited": list(action.behaviors_cited),
                "metadata": sanitize_observability_payload(deepcopy(action.metadata)),
                "related_run_id": action.related_run_id,
                "audit_log_event_id": action.audit_log_event_id,
                "trace_id": action.trace_id,
                "span_id": action.span_id,
                "parent_span_id": action.parent_span_id,
                "outcome_ref": action.outcome_ref,
            },
            actor=self._actor_payload(actor),
            action_id=action.action_id,
            run_id=action.related_run_id,
        )
        self._emit_action_outcome(
            action,
            outcome_type="action_recorded",
            outcome_ref=action.outcome_ref or f"action:{action.action_id}",
        )
        return deepcopy(action)

    def list_actions(self) -> List[Action]:
        """Return all actions sorted by timestamp ascending."""

        return [deepcopy(action) for action in sorted(self._actions.values(), key=lambda a: a.timestamp)]

    def get_action(self, action_id: str) -> Action:
        """Fetch a single action by identifier."""

        if action_id not in self._actions:
            raise ActionNotFoundError(f"Action '{action_id}' not found")
        return deepcopy(self._actions[action_id])

    # ------------------------------------------------------------------
    # Replay Operations
    # ------------------------------------------------------------------
    def replay_actions(self, request: ReplayRequest, actor: Actor) -> ReplayStatus:
        """Replay a set of actions using real execution."""

        missing = [action_id for action_id in request.action_ids if action_id not in self._actions]
        if missing:
            raise ActionNotFoundError(f"Cannot replay missing actions: {missing}")

        replay_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        audit_log_event_id = f"urn:amprealize:audit:replay:{replay_id}"
        actions = [self._actions[action_id] for action_id in request.action_ids]
        trace_id = self._common_trace_id(actions) or f"replay:{replay_id}"
        span_id = f"replay:{replay_id}"
        parent_span_id = actions[0].span_id if len(actions) == 1 else None
        outcome_ref = audit_log_event_id

        self._telemetry.emit_event(
            event_type="action_replay_start",
            payload={
                "action_ids": list(request.action_ids),
                "strategy": request.strategy,
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "outcome_ref": outcome_ref,
                "options": {
                    "skip_existing": request.options.skip_existing,
                    "dry_run": request.options.dry_run,
                },
            },
            actor=self._actor_payload(actor),
            action_id=replay_id,
        )

        # Execute using real executor
        if request.strategy == "PARALLEL":
            succeeded, failed, results = self._executor.execute_parallel(
                actions=actions,
                skip_existing=request.options.skip_existing,
                dry_run=request.options.dry_run,
            )
        else:  # SEQUENTIAL
            succeeded, failed, results = self._executor.execute_sequential(
                actions=actions,
                skip_existing=request.options.skip_existing,
                dry_run=request.options.dry_run,
            )

        # Update action replay status
        if not request.options.dry_run:
            for action_id in succeeded:
                self._actions[action_id].replay_status = "SUCCEEDED"
            for action_id in failed:
                self._actions[action_id].replay_status = "FAILED"

        # Build logs from execution results
        logs = [
            audit_log_event_id,
            f"Replay triggered by {actor.id} using strategy={request.strategy}",
        ]
        for result in results:
            if result.status == ExecutionStatus.SUCCEEDED:
                logs.append(f"✓ {result.action_id}: {result.output[:100]}")
            elif result.status == ExecutionStatus.FAILED:
                logs.append(f"✗ {result.action_id}: {result.error}")
            elif result.status == ExecutionStatus.SKIPPED:
                logs.append(f"⊘ {result.action_id}: Skipped")

        progress = 1.0 if not request.options.dry_run else 0.0
        status = "SUCCEEDED" if not failed else ("PARTIAL" if succeeded else "FAILED")
        started_at = created_at
        completed_at = utc_now_iso() if progress == 1.0 else None

        replay_status = ReplayStatus(
            replay_id=replay_id,
            status=status,
            progress=progress,
            logs=logs,
            failed_action_ids=failed,
            action_ids=list(request.action_ids),
            completed_action_ids=succeeded,
            audit_log_event_id=audit_log_event_id,
            strategy=request.strategy,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            actor_id=actor.id,
            actor_role=actor.role,
            actor_surface=actor.surface.lower(),
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            outcome_ref=outcome_ref,
        )
        self._replays[replay_id] = replay_status
        self._telemetry.emit_event(
            event_type="action_replay_complete",
            payload={
                "action_ids": list(request.action_ids),
                "status": status,
                "succeeded": succeeded,
                "failed": failed,
                "progress": progress,
                "audit_log_event_id": audit_log_event_id,
                "logs": logs,
                "created_at": created_at,
                "started_at": started_at,
                "completed_at": completed_at,
                "strategy": request.strategy,
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "outcome_ref": outcome_ref,
            },
            actor=self._actor_payload(actor),
            action_id=replay_id,
        )
        self._telemetry.emit_event(
            event_type="action.replay.performance",
            payload={
                "action_ids": list(request.action_ids),
                "status": status,
                "succeeded_count": len(succeeded),
                "failed_count": len(failed),
                "progress": progress,
                "strategy": request.strategy,
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
            },
            actor=self._actor_payload(actor),
            action_id=replay_id,
        )
        self._telemetry.emit_event(
            event_type="action.business_outcome",
            payload={
                "outcome_type": "action_replay",
                "outcome_ref": outcome_ref,
                "replay_id": replay_id,
                "action_ids": list(request.action_ids),
                "completed_action_ids": succeeded,
                "failed_action_ids": failed,
                "status": status,
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
            },
            actor=self._actor_payload(actor),
            action_id=replay_id,
        )
        return deepcopy(replay_status)

    def get_replay_status(self, replay_id: str) -> ReplayStatus:
        """Retrieve an existing replay job status."""

        if replay_id not in self._replays:
            raise ReplayNotFoundError(f"Replay '{replay_id}' not found")
        return deepcopy(self._replays[replay_id])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _calculate_checksum(request: ActionCreateRequest) -> str:
        """Generate a deterministic checksum for the action summary and artifact."""

        hasher = hashlib.sha256()
        hasher.update(request.artifact_path.encode("utf-8"))
        hasher.update(request.summary.encode("utf-8"))
        hasher.update("::".join(request.behaviors_cited).encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Normalize actor metadata for telemetry envelopes."""

        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface.lower(),
        }

    @staticmethod
    def _trace_value(request: ActionCreateRequest, key: str) -> Optional[str]:
        direct_value = getattr(request, key, None)
        if direct_value:
            return str(direct_value)
        metadata = request.metadata or {}
        if key in metadata and metadata[key]:
            return str(metadata[key])
        action_trace = metadata.get("action_trace")
        if isinstance(action_trace, dict) and action_trace.get(key):
            return str(action_trace[key])
        execution_observability = metadata.get("execution_observability")
        if isinstance(execution_observability, dict):
            if key == "trace_id" and execution_observability.get("run_id"):
                return str(execution_observability["run_id"])
            if key == "parent_span_id" and execution_observability.get("cycle_id"):
                return str(execution_observability["cycle_id"])
        return None

    @staticmethod
    def _common_trace_id(actions: List[Action]) -> Optional[str]:
        trace_ids = {action.trace_id for action in actions if action.trace_id}
        if len(trace_ids) == 1:
            return next(iter(trace_ids))
        return None

    def _emit_action_outcome(
        self,
        action: Action,
        *,
        outcome_type: str,
        outcome_ref: str,
    ) -> None:
        self._telemetry.emit_event(
            event_type="action.business_outcome",
            payload={
                "outcome_type": outcome_type,
                "outcome_ref": outcome_ref,
                "action_id": action.action_id,
                "artifact_path": action.artifact_path,
                "summary": action.summary,
                "trace_id": action.trace_id,
                "span_id": action.span_id,
                "parent_span_id": action.parent_span_id,
                "related_run_id": action.related_run_id,
                "audit_log_event_id": action.audit_log_event_id,
            },
            actor=self._actor_payload(action.actor),
            action_id=action.action_id,
            run_id=action.related_run_id,
        )
