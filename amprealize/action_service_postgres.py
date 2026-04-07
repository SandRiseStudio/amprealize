"""PostgreSQL-backed ActionService for production use.

Provides WORM (Write-Once-Read-Many) storage for platform actions with replay tracking.
Schema defined in ``schema/migrations/004_create_action_service.sql``.
Contract documented in ``docs/contracts/ACTION_SERVICE_CONTRACT.md``.

For in-memory testing, use ActionService from action_service.py instead.
"""

from __future__ import annotations

import random
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

from .action_contracts import (
    Action,
    ActionCreateRequest,
    Actor,
    ReplayRequest,
    ReplayStatus,
    utc_now_iso,
)
from .action_replay_executor import ActionReplayExecutor, ExecutionStatus
from .action_service import (
    ActionService,
    ActionServiceError,
    ActionNotFoundError,
    ReplayNotFoundError,
)
from .telemetry import TelemetryClient
from .utils.dsn import resolve_postgres_dsn
from amprealize.storage import postgres_metrics
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.storage.redis_cache import get_cache

_T = TypeVar("_T")


class PostgresActionService:
    """PostgreSQL-backed ActionService for production use.

    Stores actions in the actions table and replays in the replays table
    using the schema defined in schema/migrations/004_create_action_service.sql.
    Uses ActionReplayExecutor for real execution with support for sequential/parallel
    strategies and checkpointing.

    Args:
        dsn: PostgreSQL connection string (e.g., postgresql://user:pass@localhost:5435/amprealize_action)
        telemetry: Optional telemetry client for event emission
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        self._explicit_dsn = dsn
        self._resolved_dsn: Optional[str] = None
        self._pool: Optional[PostgresPool] = None
        self._pool_lock = Lock()
        self._telemetry = telemetry or TelemetryClient.noop()
        self._executor = ActionReplayExecutor(telemetry=self._telemetry)

    def _ensure_psycopg2(self) -> None:
        """Verify psycopg2 is available."""
        try:
            import psycopg2  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise SystemExit(
                "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
            ) from exc

    def _resolve_dsn(self) -> str:
        """Resolve the PostgreSQL DSN only when first needed."""
        if self._resolved_dsn:
            return self._resolved_dsn

        env_var = "AMPREALIZE_ACTION_PG_DSN"
        default_dsn = "postgresql://amprealize_user:local_dev_pw@localhost:6435/amprealize_action"
        self._resolved_dsn = resolve_postgres_dsn(
            service="ACTION",
            explicit_dsn=self._explicit_dsn,
            env_var=env_var,
            default_dsn=default_dsn,
        )
        return self._resolved_dsn

    def _get_pool(self) -> PostgresPool:
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                self._ensure_psycopg2()
                self._pool = PostgresPool(self._resolve_dsn(), service_name="action")
        return self._pool

    @contextmanager
    def _connection(self, *, autocommit: bool = True):
        """Acquire a pooled PostgreSQL connection with optional transaction control."""
        with self._get_pool().connection(autocommit=autocommit) as conn:
            yield conn

    def _run_transaction(
        self,
        operation: str,
        *,
        actor: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        executor: Callable[[Any], _T],
        service_prefix: str = "action",
        max_attempts: int = 3,
        base_retry_delay: float = 0.05,
    ) -> _T:
        """Execute a transactional executor with retry/telemetry instrumentation."""
        payload_base: Dict[str, Any] = dict(metadata or {})
        last_exception: Optional[Exception] = None
        pool = self._get_pool()
        service_name = getattr(pool, "_service_name", "postgres")

        postgres_metrics.record_transaction_start(service_name, operation)
        start_time = time.time()

        for attempt in range(1, max_attempts + 1):
            try:
                with self._connection(autocommit=False) as conn:
                    self._telemetry.emit_event(
                        event_type=f"{service_prefix}_transaction_start",
                        payload={
                            "operation": operation,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            **payload_base,
                        },
                        actor=actor,
                    )

                    result = executor(conn)

                    self._telemetry.emit_event(
                        event_type=f"{service_prefix}_transaction_commit",
                        payload={
                            "operation": operation,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            **payload_base,
                        },
                        actor=actor,
                    )

                    duration = time.time() - start_time
                    postgres_metrics.transaction_duration_seconds.labels(
                        service=service_name,
                        operation=operation,
                    ).observe(duration)
                    return result
            except Exception as exc:  # noqa: BLE001 - propagate after telemetry
                last_exception = exc
                if (
                    PostgresPool._is_retryable_pg_error(exc)
                    and attempt < max_attempts
                ):
                    postgres_metrics.record_transaction_retry(
                        service_name, operation
                    )
                    self._telemetry.emit_event(
                        event_type=f"{service_prefix}_transaction_retry",
                        payload={
                            "operation": operation,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "error": str(exc),
                            **payload_base,
                        },
                        actor=actor,
                    )
                    delay = (
                        base_retry_delay * (2 ** (attempt - 1))
                        + random.uniform(0, 0.01)
                    )
                    time.sleep(delay)
                    continue

                postgres_metrics.record_transaction_failure(
                    service_name,
                    operation,
                    type(exc).__name__,
                )
                self._telemetry.emit_event(
                    event_type=f"{service_prefix}_transaction_failure",
                    payload={
                        "operation": operation,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": str(exc),
                        **payload_base,
                    },
                    actor=actor,
                )
                raise

        if last_exception is not None:
            raise last_exception
        raise RuntimeError(f"Transaction '{operation}' terminated without executing")

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------
    def create_action(self, request: ActionCreateRequest, actor: Actor) -> Action:
        """Create a new action record in PostgreSQL."""

        from psycopg2.extras import Json

        checksum = request.checksum or ActionService._calculate_checksum(request)
        action_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        def _execute(conn: Any) -> Sequence[Any]:
            with conn.cursor() as cur:  # type: ignore[misc]
                cur.execute(
                    """
                    INSERT INTO actions (
                        action_id, timestamp, actor_id, actor_role, actor_surface,
                        artifact_path, summary, behaviors_cited, metadata,
                        related_run_id, audit_log_event_id, checksum, replay_status
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING action_id, timestamp, actor_id, actor_role, actor_surface,
                              artifact_path, summary, behaviors_cited, metadata,
                              related_run_id, audit_log_event_id, checksum, replay_status;
                    """,
                    (
                        action_id,
                        timestamp,
                        actor.id,
                        actor.role,
                        actor.surface,
                        request.artifact_path,
                        request.summary,
                        Json(request.behaviors_cited),
                        Json(request.metadata),
                        request.related_run_id,
                        request.audit_log_event_id,
                        checksum,
                        "NOT_STARTED",
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise ActionServiceError("Failed to create action")
                return row

        row = self._run_transaction(
            "action.create",
            service_prefix="action",
            actor=ActionService._actor_payload(actor),
            metadata={
                "action_id": action_id,
                "artifact_path": request.artifact_path,
            },
            executor=_execute,
        )

        action = Action(
            action_id=str(row[0]),
            timestamp=row[1].isoformat(),
            actor=Actor(id=row[2], role=row[3], surface=row[4]),
            artifact_path=row[5],
            summary=row[6],
            behaviors_cited=row[7],
            metadata=row[8],
            related_run_id=str(row[9]) if row[9] else None,
            audit_log_event_id=str(row[10]) if row[10] else None,
            checksum=row[11],
            replay_status=row[12],
        )

        # Invalidate list cache since we added a new action
        get_cache().invalidate_service('action')

        self._telemetry.emit_event(
            event_type="action_recorded",
            payload={
                "artifact_path": action.artifact_path,
                "summary": action.summary,
                "behaviors_cited": list(action.behaviors_cited),
                "metadata": dict(action.metadata),
                "related_run_id": action.related_run_id,
                "audit_log_event_id": action.audit_log_event_id,
            },
            actor=ActionService._actor_payload(actor),
            action_id=action.action_id,
            run_id=action.related_run_id,
        )

        return action

    def list_actions(self) -> List[Action]:
        """Return all actions sorted by timestamp ascending."""

        # Try cache first
        cache = get_cache()
        cache_key = cache._make_key('action', 'list', None)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return [self._hydrate_cached_action(a) for a in cached_result]

        # Cache miss - fetch from database
        with self._connection() as conn:
            with conn.cursor() as cur:  # type: ignore[misc]
                cur.execute(
                    """
                    SELECT action_id, timestamp, actor_id, actor_role, actor_surface,
                           artifact_path, summary, behaviors_cited, metadata,
                           related_run_id, audit_log_event_id, checksum, replay_status
                    FROM actions
                    ORDER BY timestamp ASC;
                    """
                )
                rows = cur.fetchall()

        actions = []
        for row in rows:
            actions.append(
                Action(
                    action_id=str(row[0]),
                    timestamp=row[1].isoformat(),
                    actor=Actor(id=row[2], role=row[3], surface=row[4]),
                    artifact_path=row[5],
                    summary=row[6],
                    behaviors_cited=row[7],
                    metadata=row[8],
                    related_run_id=str(row[9]) if row[9] else None,
                    audit_log_event_id=str(row[10]) if row[10] else None,
                    checksum=row[11],
                    replay_status=row[12],
                )
            )

        # Cache result for 10 minutes (600s)
        cache.set(cache_key, [a.to_dict() for a in actions], ttl=600)
        return actions

    def get_action(self, action_id: str) -> Action:
        """Fetch a single action by identifier."""

        import psycopg2  # type: ignore[import-not-found]

        # Try cache first
        cache = get_cache()
        cache_key = cache._make_key('action', 'get', {'action_id': action_id})
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            if cached_result == False:  # Cached "not found"
                raise ActionNotFoundError(f"Action '{action_id}' not found")
            return self._hydrate_cached_action(cached_result)

        # Cache miss - fetch from database
        with self._connection() as conn:
            with conn.cursor() as cur:  # type: ignore[misc]
                cur.execute(
                    """
                    SELECT action_id, timestamp, actor_id, actor_role, actor_surface,
                           artifact_path, summary, behaviors_cited, metadata,
                           related_run_id, audit_log_event_id, checksum, replay_status
                    FROM actions
                    WHERE action_id = %s;
                    """,
                    (action_id,),
                )
                row = cur.fetchone()

        if not row:
            # Cache "not found" to avoid repeated lookups
            cache.set(cache_key, False, ttl=60)
            raise ActionNotFoundError(f"Action '{action_id}' not found")

        action = Action(
            action_id=str(row[0]),
            timestamp=row[1].isoformat(),
            actor=Actor(id=row[2], role=row[3], surface=row[4]),
            artifact_path=row[5],
            summary=row[6],
            behaviors_cited=row[7],
            metadata=row[8],
            related_run_id=str(row[9]) if row[9] else None,
            audit_log_event_id=str(row[10]) if row[10] else None,
            checksum=row[11],
            replay_status=row[12],
        )

        # Cache result for 10 minutes (600s)
        cache.set(cache_key, action.to_dict(), ttl=600)
        return action

    # ------------------------------------------------------------------
    # Replay Operations
    # ------------------------------------------------------------------
    def replay_actions(self, request: ReplayRequest, actor: Actor) -> ReplayStatus:
        """Execute replay of specified actions with real execution."""

        from psycopg2.extras import Json

        action_ids = list(request.action_ids)
        replay_id = str(uuid.uuid4())
        audit_log_event_id = f"urn:amprealize:audit:replay:{replay_id}"
        created_at = datetime.now(timezone.utc)

        self._telemetry.emit_event(
            event_type="action_replay_start",
            payload={
                "action_ids": action_ids,
                "strategy": request.strategy,
                "options": {
                    "skip_existing": request.options.skip_existing,
                    "dry_run": request.options.dry_run,
                },
            },
            actor=ActionService._actor_payload(actor),
            action_id=replay_id,
        )

        # Fetch actions to replay, capturing any missing IDs for clearer errors
        actions: List[Action] = []
        missing_action_ids: List[str] = []
        for action_id in action_ids:
            try:
                actions.append(self.get_action(action_id))
            except ActionNotFoundError:
                missing_action_ids.append(action_id)

        if missing_action_ids:
            raise ActionNotFoundError(
                f"Cannot replay missing actions: {missing_action_ids}"
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

        def _persist(conn: Any) -> ReplayStatus:
            with conn.cursor() as cur:  # type: ignore[misc]
                # Update action replay statuses
                if not request.options.dry_run:
                    for action_id in succeeded:
                        cur.execute(
                            "UPDATE actions SET replay_status = 'SUCCEEDED' WHERE action_id = %s;",
                            (action_id,),
                        )
                    for action_id in failed:
                        cur.execute(
                            "UPDATE actions SET replay_status = 'FAILED' WHERE action_id = %s;",
                            (action_id,),
                        )

                progress_value = 1.0 if not request.options.dry_run else 0.0
                status_value = "SUCCEEDED" if not failed else ("PARTIAL" if succeeded else "FAILED")
                started_at = created_at
                completed_at_value: Optional[datetime] = (
                    datetime.now(timezone.utc) if progress_value == 1.0 else None
                )

                cur.execute(
                    """
                    INSERT INTO replays (
                        replay_id, status, progress, logs, failed_action_ids,
                        action_ids, succeeded_action_ids, audit_log_event_id,
                        strategy, actor_id, actor_role, actor_surface,
                        created_at, started_at, completed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING replay_id, status, progress, logs, failed_action_ids,
                              action_ids, succeeded_action_ids, audit_log_event_id,
                              strategy, actor_id, actor_role, actor_surface,
                              created_at, started_at, completed_at;
                    """,
                    (
                        replay_id,
                        status_value,
                        progress_value,
                        Json(logs),
                        Json(failed),
                        Json(action_ids),
                        Json(succeeded),
                        audit_log_event_id,
                        request.strategy,
                        actor.id,
                        actor.role,
                        actor.surface.lower(),
                        created_at,
                        started_at,
                        completed_at_value,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise ActionServiceError("Failed to store replay status")

            return self._hydrate_replay_status(row)

        replay_status = self._get_pool().run_transaction(
            "action.replay",
            service_prefix="action",
            actor=ActionService._actor_payload(actor),
            metadata={
                "replay_id": replay_id,
                "action_count": len(action_ids),
                "strategy": request.strategy,
                "skip_existing": request.options.skip_existing,
                "dry_run": request.options.dry_run,
            },
            executor=_persist,
            telemetry=self._telemetry,
        )

        # Invalidate action cache since replay updates action replay_status
        get_cache().invalidate_service('action')

        self._telemetry.emit_event(
            event_type="action_replay_complete",
            payload={
                "action_ids": action_ids,
                "status": replay_status.status,
                "succeeded": succeeded,
                "failed": failed,
                "progress": replay_status.progress,
                "audit_log_event_id": audit_log_event_id,
                "logs": logs,
                "created_at": replay_status.created_at,
                "started_at": replay_status.started_at,
                "completed_at": replay_status.completed_at,
                "strategy": request.strategy,
            },
            actor=ActionService._actor_payload(actor),
            action_id=replay_id,
        )

        return replay_status

    def get_replay_status(self, replay_id: str) -> ReplayStatus:
        """Retrieve an existing replay job status."""

        with self._connection() as conn:
            with conn.cursor() as cur:  # type: ignore[misc]
                cur.execute(
                    """
                    SELECT replay_id, status, progress, logs, failed_action_ids,
                           action_ids, succeeded_action_ids, audit_log_event_id,
                           strategy, actor_id, actor_role, actor_surface,
                           created_at, started_at, completed_at
                    FROM replays
                    WHERE replay_id = %s;
                    """,
                    (replay_id,),
                )
                row = cur.fetchone()

        if not row:
            raise ReplayNotFoundError(f"Replay '{replay_id}' not found")

        return self._hydrate_replay_status(row)

    def _hydrate_replay_status(self, row: Sequence[Any]) -> ReplayStatus:
        logs = row[3] or []
        failed = row[4] or []
        action_ids = row[5] or []
        succeeded = row[6] or []
        audit_log_event_id = row[7]
        strategy = row[8]
        actor_id = row[9]
        actor_role = row[10]
        actor_surface = row[11]
        created_at = row[12]
        started_at = row[13]
        completed_at = row[14]

        return ReplayStatus(
            replay_id=str(row[0]),
            status=row[1],
            progress=float(row[2]),
            logs=list(logs),
            failed_action_ids=list(failed),
            action_ids=list(action_ids),
            completed_action_ids=list(succeeded),
            audit_log_event_id=str(audit_log_event_id) if audit_log_event_id else None,
            strategy=strategy or "SEQUENTIAL",
            created_at=created_at.isoformat() if created_at else None,
            started_at=started_at.isoformat() if started_at else None,
            completed_at=completed_at.isoformat() if completed_at else None,
            actor_id=str(actor_id) if actor_id else None,
            actor_role=str(actor_role) if actor_role else None,
            actor_surface=str(actor_surface) if actor_surface else None,
        )

    @staticmethod
    def _hydrate_cached_action(payload: Dict[str, Any]) -> Action:
        """Rebuild an Action from cached dictionaries, restoring Actor dataclasses."""

        if isinstance(payload, Action):
            return payload

        actor_payload = payload.get("actor")
        if isinstance(actor_payload, Actor):
            payload = {
                **payload,
                "actor": {
                    "id": actor_payload.id,
                    "role": actor_payload.role,
                    "surface": actor_payload.surface,
                },
            }
        elif not isinstance(actor_payload, dict):
            raise ActionServiceError("Cached action payload missing actor metadata")

        return Action.from_dict(payload)
