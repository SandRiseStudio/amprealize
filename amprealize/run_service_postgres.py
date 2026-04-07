"""RunService PostgreSQL implementation."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - imported lazily for optional dependency
    from psycopg2 import extras as pg_extras  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - handled at runtime
    pg_extras = None  # type: ignore[assignment]

from .action_contracts import Actor
from .run_contracts import (
    Run,
    RunCompletion,
    RunCreateRequest,
    RunProgressUpdate,
    RunStatus,
    RunStep,
    utc_now_iso,
)
from .telemetry import TelemetryClient
from amprealize.storage.postgres_pool import PostgresPool


class RunServiceError(Exception):
    """Base error for RunService operations."""


class RunNotFoundError(RunServiceError):
    """Raised when a run could not be found in the backing store."""


class PostgresRunService:
    """PostgreSQL-backed run orchestration service.

    Parity implementation with SQLite RunService, using the shared SQLAlchemy-backed
    PostgresPool for connection management and JSONB for structured data
    (behavior_ids, outputs, metadata).

    Args:
        dsn: PostgreSQL connection string (postgresql://user:pass@host:port/dbname)
        telemetry: Optional telemetry client for event emission
    min_conn: Minimum connection pool size (retained for compatibility; ignored)
    max_conn: Maximum connection pool size (retained for compatibility; ignored)
    """

    def __init__(
        self,
        dsn: str,
        *,
        telemetry: Optional[TelemetryClient] = None,
        event_hub: Optional[Any] = None,
        min_conn: int = 2,
        max_conn: int = 10,
    ) -> None:
        # `min_conn` and `max_conn` retained for API compatibility; the shared
        # SQLAlchemy-backed PostgresPool governs pooling configuration via
        # environment variables (AMPREALIZE_PG_POOL_*).
        self._ensure_psycopg2()
        assert pg_extras is not None  # for type checkers

        self._dsn = dsn
        self._telemetry = telemetry or TelemetryClient.noop()
        self._event_hub = event_hub
        self._extras: Any = pg_extras
        self._pool = PostgresPool(dsn)

    def _ensure_psycopg2(self) -> None:
        if pg_extras is None:
            raise SystemExit(
                "❌ psycopg2 is not installed. Install with: pip install -e '.[postgres]'"
            )

    @contextmanager
    def _connection(self, *, autocommit: bool = True):
        with self._pool.connection(autocommit=autocommit) as conn:
            yield conn

    # ------------------------------------------------------------------
    # Public API (parity with RunService)
    # ------------------------------------------------------------------
    def create_run(self, request: RunCreateRequest) -> Run:
        """Create a new run with PENDING status."""
        run_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        actor = request.actor

        metadata = self._build_metadata(request)

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runs (
                        id, created_at, updated_at,
                        user_id, project_id, session_id, actor_surface,
                        status, workflow_id, workflow_name,
                        context, error
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    """,
                    (
                        run_id,
                        created_at,
                        created_at,
                        actor.id if actor.id != "api-user" else None,  # Only set if real user
                        metadata.get("project_id"),
                        metadata.get("session_id"),
                        actor.surface,
                        RunStatus.PENDING,
                        request.workflow_id,
                        request.workflow_name,
                        self._extras.Json(metadata),
                        None,  # error
                    ),
                )

        self._pool.run_transaction(
            operation="create_run",
            service_prefix="run",
            actor=asdict(actor),
            metadata={"run_id": run_id, "workflow_id": request.workflow_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        run = self.get_run(run_id)
        self._telemetry.emit_event(
            event_type="run.created",
            actor=asdict(actor),
            run_id=run_id,
            payload={
                "status": run.status,
                "workflow_id": run.workflow_id,
                "template_id": run.template_id,
                "behavior_count": len(run.behavior_ids),
            },
        )
        return run

    def get_run(self, run_id: str) -> Run:
        """Retrieve a single run by ID."""
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")
        return self._row_to_run(row)

    def list_runs(
        self,
        *,
        status: Optional[str] = None,
        workflow_id: Optional[str] = None,
        template_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Run]:
        """List runs with optional filters."""
        clauses: List[str] = []
        params: List[Any] = []

        if status:
            clauses.append("status = %s")
            params.append(status)
        if workflow_id:
            clauses.append("workflow_id = %s")
            params.append(workflow_id)
        if template_id:
            clauses.append("context->>'template_id' = %s")
            params.append(template_id)

        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        params.append(limit)
        query = f"""
            SELECT * FROM runs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """

        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

        return [self._row_to_run(dict(row)) for row in rows]

    def update_run(self, run_id: str, update: RunProgressUpdate) -> Run:
        """Update run progress/status and optionally upsert a step."""
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")

        run = self._row_to_run(row)
        now = utc_now_iso()
        new_status = update.status or run.status
        progress_pct = update.progress_pct if update.progress_pct is not None else run.progress_pct
        message = update.message if update.message is not None else run.message
        started_at = run.started_at
        completed_at = run.completed_at
        duration_ms = run.duration_ms

        # Auto-populate timestamps
        if new_status == RunStatus.RUNNING and not started_at:
            started_at = now
        if new_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED} and not completed_at:
            completed_at = now
            duration_ms = self._calculate_duration_ms(run.created_at, completed_at)

        # Merge metadata
        metadata = dict(run.metadata)
        if update.metadata:
            metadata.update(update.metadata)
        if update.tokens_generated is not None:
            metadata.setdefault("tokens", {})["generated"] = update.tokens_generated
        if update.tokens_baseline is not None:
            metadata.setdefault("tokens", {})["baseline"] = update.tokens_baseline

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Store progress_pct, message, current_step, duration_ms in context
                context = dict(metadata)
                context["progress_pct"] = progress_pct
                if message:
                    context["message"] = message
                if update.step_id or run.current_step:
                    context["current_step"] = update.step_id or run.current_step
                if duration_ms is not None:
                    context["duration_ms"] = duration_ms

                cur.execute(
                    """
                    UPDATE runs
                    SET
                        status = %s,
                        started_at = %s,
                        completed_at = %s,
                        context = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        new_status,
                        started_at,
                        completed_at,
                        self._extras.Json(context),
                        now,
                        run_id,
                    ),
                )
                if update.step_id:
                    self._upsert_step(
                        cur,
                        run_id=run_id,
                        step_id=update.step_id,
                        name=update.step_name or update.step_id,
                        status=update.step_status or new_status,
                        progress_pct=update.progress_pct,
                        metadata=update.metadata,
                    )

        self._pool.run_transaction(
            operation="update_run",
            service_prefix="run",
            actor=asdict(run.actor),
            metadata={"run_id": run_id, "status": new_status},
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated_run = self.get_run(run_id)
        self._telemetry.emit_event(
            event_type="run.progress",
            actor=asdict(updated_run.actor),
            run_id=run_id,
            payload={
                "status": updated_run.status,
                "progress_pct": updated_run.progress_pct,
                "current_step": updated_run.current_step,
                "message": updated_run.message,
            },
        )
        self._publish_run_events(updated_run, update.step_id)
        return updated_run

    def complete_run(self, run_id: str, completion: RunCompletion) -> Run:
        """Mark a run as completed/failed/cancelled with final outputs."""
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")

        run = self._row_to_run(row)
        now = utc_now_iso()
        completed_at = now
        duration_ms = self._calculate_duration_ms(run.started_at or run.created_at, completed_at)
        status = completion.status
        progress_pct = 100.0 if status == RunStatus.COMPLETED else run.progress_pct
        merged_metadata = self._merge_metadata(run.metadata, completion.metadata)

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Store progress_pct, duration_ms, message in context
                context = dict(merged_metadata)
                context["progress_pct"] = progress_pct
                if duration_ms is not None:
                    context["duration_ms"] = duration_ms
                if completion.message:
                    context["message"] = completion.message

                cur.execute(
                    """
                    UPDATE runs
                    SET
                        status = %s,
                        completed_at = %s,
                        result = %s,
                        error = %s,
                        context = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        completed_at,
                        self._extras.Json(completion.outputs or {}),
                        completion.error,
                        self._extras.Json(context),
                        now,
                        run_id,
                    ),
                )

        self._pool.run_transaction(
            operation="complete_run",
            service_prefix="run",
            actor=asdict(run.actor),
            metadata={"run_id": run_id, "status": status},
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated_run = self.get_run(run_id)
        self._telemetry.emit_event(
            event_type="run.completed",
            actor=asdict(updated_run.actor),
            run_id=run_id,
            payload={
                "status": updated_run.status,
                "duration_ms": updated_run.duration_ms,
                "error": updated_run.error,
            },
        )
        self._publish_run_events(updated_run, None)
        return updated_run

    def cancel_run(self, run_id: str, reason: Optional[str] = None) -> Run:
        """Cancel a run and mark it as complete with CANCELLED status."""
        completion = RunCompletion(
            status=RunStatus.CANCELLED,
            message=reason or "Run cancelled",
        )
        return self.complete_run(run_id, completion)

    def update_progress(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        current_step: Optional[str] = None,
        message: Optional[str] = None,
        outputs: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        """Convenience wrapper for updating run progress."""
        if outputs is not None or error is not None:
            completion = RunCompletion(
                status=status or (RunStatus.FAILED if error else RunStatus.COMPLETED),
                outputs=outputs or {},
                message=message,
                error=error,
                metadata=metadata or {},
            )
            return self.complete_run(run_id, completion)

        update = RunProgressUpdate(
            status=status,
            progress_pct=progress,
            message=message,
            step_id=current_step,
            step_name=current_step,
            metadata=metadata or {},
        )
        return self.update_run(run_id, update)

    def add_step(
        self,
        run_id: str,
        *,
        action: str,
        outcome: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> RunStep:
        """Append a run step entry."""
        step_id = str(uuid.uuid4())
        update = RunProgressUpdate(
            step_id=step_id,
            step_name=action,
            step_status=status or RunStatus.RUNNING,
            metadata=metadata or {},
        )
        self.update_run(run_id, update)
        run = self.get_run(run_id)
        for step in run.steps:
            if step.step_id == step_id:
                return step
        return RunStep(step_id=step_id, name=action, status=status or RunStatus.RUNNING, metadata=metadata or {})

    def delete_run(self, run_id: str) -> None:
        """Delete a run (CASCADE will remove run_steps)."""

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM runs WHERE id = %s", (run_id,))
                if cur.rowcount == 0:
                    raise RunNotFoundError(f"Run '{run_id}' not found")

        self._pool.run_transaction(
            operation="delete_run",
            service_prefix="run",
            actor={"id": "system", "role": "SYSTEM", "surface": "INTERNAL"},
            metadata={"run_id": run_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_run_row(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single run row as a dict."""
        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def _row_to_run(self, row: Dict[str, Any]) -> Run:
        """Convert a PostgreSQL row dict to a Run dataclass."""
        # Extract context (stores extra fields)
        context = row.get("context") if isinstance(row.get("context"), dict) else {}
        result = row.get("result") if isinstance(row.get("result"), dict) else {}

        # Build actor from user_id and actor_surface
        actor = Actor(
            id=row.get("user_id") or "system",
            role=context.get("actor_role", "user"),
            surface=row.get("actor_surface", "api"),
        )

        # Convert UUID to string
        run_id_str = str(row["id"])
        steps = self._fetch_steps(run_id_str)

        # Strip internal fields from metadata to match SQLite backend parity
        _internal_keys = {
            "template_id", "template_name", "behavior_ids",
            "message", "actor_role", "current_step", "progress_pct", "duration_ms",
        }
        user_metadata = {k: v for k, v in context.items() if k not in _internal_keys}

        return Run(
            run_id=run_id_str,
            created_at=row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            updated_at=row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            actor=actor,
            status=row["status"],
            workflow_id=row.get("workflow_id"),
            workflow_name=row.get("workflow_name"),
            template_id=context.get("template_id"),
            template_name=context.get("template_name"),
            behavior_ids=context.get("behavior_ids", []),
            current_step=context.get("current_step"),
            progress_pct=context.get("progress_pct", 0.0),
            message=context.get("message"),
            started_at=row["started_at"].isoformat() if row.get("started_at") and hasattr(row["started_at"], "isoformat") else row.get("started_at"),
            completed_at=row["completed_at"].isoformat() if row.get("completed_at") and hasattr(row["completed_at"], "isoformat") else row.get("completed_at"),
            duration_ms=context.get("duration_ms"),
            outputs=result,
            error=row.get("error"),
            metadata=user_metadata,
            steps=steps,
        )

    def _fetch_steps(self, run_id: str) -> List[RunStep]:
        """Fetch all steps for a run, ordered by started_at."""
        with self._connection() as conn:
            with conn.cursor(cursor_factory=self._extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM execution.run_steps
                    WHERE run_id = %s
                    ORDER BY started_at ASC, step_number ASC
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()

        steps = []
        for row in rows:
            # run_steps uses input_data/output_data JSONB columns
            input_data = row.get("input_data") if isinstance(row.get("input_data"), dict) else {}
            output_data = row.get("output_data") if isinstance(row.get("output_data"), dict) else {}

            # Build metadata with flattened token counts for frontend compatibility
            # Frontend expects metadata.input_tokens, metadata.output_tokens at top level
            metadata = {
                "input_data": input_data,
                "output_data": output_data,
                # Flatten token counts to top-level for ExecutionTimeline compatibility
                "input_tokens": input_data.get("input_tokens", 0),
                "output_tokens": input_data.get("output_tokens", 0),
                # Also expose other commonly needed fields
                "step_type": input_data.get("step_type"),
                "phase": input_data.get("phase"),
                "content_preview": input_data.get("content_preview"),
                "tool_calls": input_data.get("tool_calls"),
            }

            steps.append(
                RunStep(
                    step_id=input_data.get("_step_id") or row["name"] or str(row["id"]),
                    name=row["name"],
                    status=row["status"],
                    started_at=row["started_at"].isoformat() if row.get("started_at") and hasattr(row["started_at"], "isoformat") else row.get("started_at"),
                    completed_at=row["completed_at"].isoformat() if row.get("completed_at") and hasattr(row["completed_at"], "isoformat") else row.get("completed_at"),
                    progress_pct=input_data.get("_progress_pct", 0.0),  # from _upsert_step
                    metadata=metadata,
                )
            )
        return steps

    def _upsert_step(
        self,
        cur: Any,
        *,
        run_id: str,
        step_id: str,
        name: str,
        status: str,
        progress_pct: Optional[float],
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Insert or update a run step."""
        now = utc_now_iso()
        metadata_dict = dict(metadata) if metadata else {}
        # Persist step_id so _fetch_steps can return it
        metadata_dict["_step_id"] = step_id
        if progress_pct is not None:
            metadata_dict["_progress_pct"] = progress_pct

        # Check if step exists (using step_id stored in input_data)
        cur.execute(
            "SELECT id, input_data, completed_at FROM run_steps WHERE run_id = %s AND input_data->>'_step_id' = %s ORDER BY step_number DESC LIMIT 1",
            (run_id, step_id),
        )
        row = cur.fetchone()

        if not row:
            # Fallback: look up by name for backward compatibility
            cur.execute(
                "SELECT id, input_data, completed_at FROM run_steps WHERE run_id = %s AND name = %s ORDER BY step_number DESC LIMIT 1",
                (run_id, name),
            )
            row = cur.fetchone()

        if row:
            # Update existing step
            step_db_id = row[0]
            existing_input = row[1] if isinstance(row[1], dict) else {}
            merged_input = self._merge_metadata(existing_input, metadata_dict)
            completed_at_val = row[2]
            if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                completed_at_val = now

            cur.execute(
                """
                UPDATE run_steps
                SET name = %s,
                    status = %s,
                    input_data = %s,
                    completed_at = %s
                WHERE id = %s
                """,
                (
                    name,
                    status,
                    self._extras.Json(merged_input),
                    completed_at_val,
                    step_db_id,
                ),
            )
        else:
            # Insert new step - get next step_number
            cur.execute(
                "SELECT COALESCE(MAX(step_number), 0) + 1 FROM run_steps WHERE run_id = %s",
                (run_id,),
            )
            next_step_number = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO run_steps (
                    run_id, step_number, name, status, started_at, completed_at, input_data
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    run_id,
                    next_step_number,
                    name,
                    status,
                    now,
                    None,
                    self._extras.Json(metadata_dict),
                ),
            )

    def _build_metadata(self, request: RunCreateRequest) -> Dict[str, Any]:
        """Build initial metadata from request."""
        metadata = dict(request.metadata)
        if request.total_steps is not None:
            metadata.setdefault("execution", {})["total_steps"] = request.total_steps
        # Store triggering_user_id for credential resolution during GitHub operations
        if request.triggering_user_id:
            metadata["triggering_user_id"] = request.triggering_user_id
        # Persist fields that _row_to_run reads back from context
        if request.template_id:
            metadata["template_id"] = request.template_id
        if request.template_name:
            metadata["template_name"] = request.template_name
        if request.behavior_ids:
            metadata["behavior_ids"] = request.behavior_ids
        if request.initial_message:
            metadata["message"] = request.initial_message
        if request.actor and request.actor.role:
            metadata["actor_role"] = request.actor.role
        return metadata

    def _merge_metadata(
        self,
        original: Dict[str, Any],
        additional: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge two metadata dicts."""
        merged = dict(original)
        if additional:
            merged.update(additional)
        return merged

    def _publish_run_events(self, run: Run, step_id: Optional[str]) -> None:
        if not self._event_hub:
            return
        metadata = run.metadata or {}
        payload = {
            "run_id": run.run_id,
            "work_item_id": metadata.get("work_item_id"),
            "org_id": metadata.get("org_id"),
            "project_id": metadata.get("project_id"),
            "agent_id": metadata.get("agent_id"),
            "model_id": metadata.get("model_id"),
            "cycle_id": metadata.get("cycle_id"),
            "status": run.status,
            "phase": metadata.get("phase"),
            "progress_pct": run.progress_pct,
            "current_step": run.current_step,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "error": run.error,
            "step_count": len(run.steps),
            "updated_at": run.updated_at,
        }
        self._event_hub.publish_status(payload)

        if not step_id:
            return
        for step in run.steps:
            if step.step_id == step_id:
                step_payload = {
                    "run_id": run.run_id,
                    "work_item_id": metadata.get("work_item_id"),
                    "org_id": metadata.get("org_id"),
                    "project_id": metadata.get("project_id"),
                    "step": step.to_dict(),
                }
                self._event_hub.publish_step(step_payload)
                break

    @staticmethod
    def _calculate_duration_ms(start_iso: Optional[str], end_iso: str) -> Optional[int]:
        """Calculate duration in milliseconds between two ISO timestamps."""
        if not start_iso:
            return None
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        delta = end - start
        return int(delta.total_seconds() * 1000)

    def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            self._pool.close()

    def __enter__(self) -> PostgresRunService:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
