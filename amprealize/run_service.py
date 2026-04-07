"""RunService runtime implementation with SQLite persistence."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .action_contracts import Actor
from .run_contracts import (
    Run,
    RunCompletion,
    RunCreateRequest,
    RunLogEntry,
    RunLogsResponse,
    RunProgressUpdate,
    RunStatus,
    RunStep,
    utc_now_iso,
)
from .telemetry import TelemetryClient

_RUN_DB_ENV = "AMPREALIZE_RUN_DB_PATH"
_DEFAULT_DB_PATH = Path.home() / ".amprealize" / "data" / "runs.db"


class RunServiceError(Exception):
    """Base error for RunService operations."""


class RunNotFoundError(RunServiceError):
    """Raised when a run could not be found in the backing store."""


class RunService:
    """SQLite-backed run orchestration service."""

    def __init__(
        self,
        *,
        db_path: Optional[Path] = None,
        telemetry: Optional[TelemetryClient] = None,
        event_hub: Optional[Any] = None,
    ) -> None:
        self._db_path = self._resolve_db_path(db_path)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._event_hub = event_hub
        self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_run(self, request: RunCreateRequest) -> Run:
        run_id = str(uuid.uuid4())
        created_at = utc_now_iso()
        actor = request.actor

        run_payload = {
            "run_id": run_id,
            "created_at": created_at,
            "updated_at": created_at,
            "actor_id": actor.id,
            "actor_role": actor.role,
            "actor_surface": actor.surface,
            "status": RunStatus.PENDING,
            "workflow_id": request.workflow_id,
            "workflow_name": request.workflow_name,
            "template_id": request.template_id,
            "template_name": request.template_name,
            "behavior_ids": json.dumps(request.behavior_ids),
            "current_step": None,
            "progress_pct": 0.0,
            "message": request.initial_message,
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
            "outputs": json.dumps({}),
            "error": None,
            "metadata": json.dumps(self._build_metadata(request)),
        }

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, created_at, updated_at,
                    actor_id, actor_role, actor_surface,
                    status, workflow_id, workflow_name,
                    template_id, template_name,
                    behavior_ids, current_step, progress_pct,
                    message, started_at, completed_at, duration_ms,
                    outputs, error, metadata
                ) VALUES (
                    :run_id, :created_at, :updated_at,
                    :actor_id, :actor_role, :actor_surface,
                    :status, :workflow_id, :workflow_name,
                    :template_id, :template_name,
                    :behavior_ids, :current_step, :progress_pct,
                    :message, :started_at, :completed_at, :duration_ms,
                    :outputs, :error, :metadata
                )
                """,
                run_payload,
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
        clauses: List[str] = []
        params: Dict[str, Any] = {"limit": limit}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if workflow_id:
            clauses.append("workflow_id = :workflow_id")
            params["workflow_id"] = workflow_id
        if template_id:
            clauses.append("template_id = :template_id")
            params["template_id"] = template_id

        where_clause = ""
        if clauses:
            where_clause = "WHERE " + " AND ".join(clauses)

        query = f"""
            SELECT * FROM runs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_run(row) for row in rows]

    def update_run(self, run_id: str, update: RunProgressUpdate) -> Run:
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

        if new_status == RunStatus.RUNNING and not started_at:
            started_at = now
        if new_status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED} and not completed_at:
            completed_at = now
            duration_ms = self._calculate_duration_ms(run.created_at, completed_at)

        metadata = dict(run.metadata)
        if update.metadata:
            metadata.update(update.metadata)
        if update.tokens_generated is not None:
            metadata.setdefault("tokens", {})["generated"] = update.tokens_generated
        if update.tokens_baseline is not None:
            metadata.setdefault("tokens", {})["baseline"] = update.tokens_baseline

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET
                    status = :status,
                    progress_pct = :progress_pct,
                    message = :message,
                    current_step = :current_step,
                    started_at = :started_at,
                    completed_at = :completed_at,
                    duration_ms = :duration_ms,
                    metadata = :metadata,
                    updated_at = :updated_at
                WHERE run_id = :run_id
                """,
                {
                    "status": new_status,
                    "progress_pct": progress_pct,
                    "message": message,
                    "current_step": update.step_id or run.current_step,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_ms": duration_ms,
                    "metadata": json.dumps(metadata),
                    "updated_at": now,
                    "run_id": run_id,
                },
            )
            if update.step_id:
                self._upsert_step(
                    conn,
                    run_id=run_id,
                    step_id=update.step_id,
                    name=update.step_name or update.step_id,
                    status=update.step_status or new_status,
                    progress_pct=update.progress_pct,
                    metadata=update.metadata,
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
        row = self._fetch_run_row(run_id)
        if row is None:
            raise RunNotFoundError(f"Run '{run_id}' not found")

        run = self._row_to_run(row)
        now = utc_now_iso()
        completed_at = now
        duration_ms = self._calculate_duration_ms(run.started_at or run.created_at, completed_at)
        status = completion.status
        progress_pct = 100.0 if status == RunStatus.COMPLETED else run.progress_pct

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET
                    status = :status,
                    progress_pct = :progress_pct,
                    completed_at = :completed_at,
                    duration_ms = :duration_ms,
                    outputs = :outputs,
                    message = :message,
                    error = :error,
                    metadata = :metadata,
                    updated_at = :updated_at
                WHERE run_id = :run_id
                """,
                {
                    "status": status,
                    "progress_pct": progress_pct,
                    "completed_at": completed_at,
                    "duration_ms": duration_ms,
                    "outputs": json.dumps(completion.outputs or {}),
                    "message": completion.message,
                    "error": completion.error,
                    "metadata": json.dumps(self._merge_metadata(run.metadata, completion.metadata)),
                    "updated_at": now,
                    "run_id": run_id,
                },
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
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            if cur.rowcount == 0:
                raise RunNotFoundError(f"Run '{run_id}' not found")

    async def fetch_logs(
        self,
        run_id: str,
        *,
        raze_service: Any = None,
        level: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        search: Optional[str] = None,
        include_steps: bool = True,
    ) -> "RunLogsResponse":
        """Fetch execution logs for a run from Raze logging system.

        Args:
            run_id: Run identifier.
            raze_service: RazeService instance for querying logs.
            level: Minimum log level (INFO, WARNING, ERROR, etc.).
            start_time: Start of time range (ISO 8601).
            end_time: End of time range (ISO 8601).
            limit: Maximum logs to return (1-1000).
            after: Cursor for pagination (log_id from previous page).
            search: Full-text search in message field.
            include_steps: Whether to include RunSteps in response.

        Returns:
            RunLogsResponse with logs and optional steps.

        Raises:
            RunNotFoundError: If run does not exist.
        """
        from datetime import datetime, UTC
        from .run_contracts import RunLogEntry, RunLogsResponse

        # Verify run exists (also enforces access control at caller level)
        run = self.get_run(run_id)

        logs: List["RunLogEntry"] = []
        total = 0
        has_more = False
        next_cursor: Optional[str] = None

        # Query Raze if service is provided
        if raze_service is not None:
            try:
                # Parse time range
                if start_time:
                    start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                else:
                    start_dt = datetime.fromisoformat(run.created_at.replace("Z", "+00:00"))

                if end_time:
                    end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.now(UTC)

                # Map level string to LogLevel if provided
                level_filter = None
                if level:
                    level_filter = level.upper()

                # Calculate offset from cursor if provided
                offset = 0
                # Note: For true cursor-based pagination, we'd need to track position
                # in Raze. For now, use after as a marker and filter client-side.

                # Query Raze
                response = await raze_service.query(
                    start_time=start_dt,
                    end_time=end_dt,
                    run_id=run_id,
                    level=level_filter,
                    search=search,
                    limit=limit + 1,  # Fetch one extra to detect has_more
                    offset=offset,
                    order="asc",
                )

                # Convert to RunLogEntry
                for log in response.logs:
                    # Skip logs until we pass the cursor
                    if after and log.log_id <= after:
                        continue

                    log_entry = RunLogEntry(
                        log_id=log.log_id,
                        timestamp=log.timestamp.isoformat() if hasattr(log.timestamp, "isoformat") else str(log.timestamp),
                        level=log.level if isinstance(log.level, str) else log.level.value,
                        service=log.service,
                        message=log.message,
                        action_id=getattr(log, "action_id", None),
                        session_id=getattr(log, "session_id", None),
                        actor_surface=getattr(log, "actor_surface", None),
                        context=getattr(log, "context", {}),
                    )
                    logs.append(log_entry)

                    if len(logs) >= limit:
                        break

                total = response.total_count
                has_more = len(logs) == limit and response.has_more
                if logs:
                    next_cursor = logs[-1].log_id if has_more else None

            except Exception as e:
                # Log error but don't fail - return empty logs with run steps
                self._telemetry.emit_event(
                    event_type="run.fetch_logs.error",
                    actor={"id": run.actor.id, "role": run.actor.role, "surface": run.actor.surface},
                    run_id=run_id,
                    payload={"error": str(e)},
                )

        # Include run steps if requested
        steps = run.steps if include_steps else []

        return RunLogsResponse(
            run_id=run_id,
            logs=logs,
            steps=steps,
            total=total,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _fetch_run_row(self, run_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()

    def _row_to_run(self, row: sqlite3.Row) -> Run:
        actor = Actor(
            id=row["actor_id"],
            role=row["actor_role"],
            surface=row["actor_surface"],
        )
        steps = self._fetch_steps(row["run_id"])

        return Run(
            run_id=row["run_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            actor=actor,
            status=row["status"],
            workflow_id=row["workflow_id"],
            workflow_name=row["workflow_name"],
            template_id=row["template_id"],
            template_name=row["template_name"],
            behavior_ids=json.loads(row["behavior_ids"] or "[]"),
            current_step=row["current_step"],
            progress_pct=row["progress_pct"],
            message=row["message"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            duration_ms=row["duration_ms"],
            outputs=json.loads(row["outputs"] or "{}"),
            error=row["error"],
            metadata=json.loads(row["metadata"] or "{}"),
            steps=steps,
        )

    def _fetch_steps(self, run_id: str) -> List[RunStep]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at ASC, step_id ASC",
                (run_id,),
            ).fetchall()
        steps = []
        for row in rows:
            steps.append(
                RunStep(
                    step_id=row["step_id"],
                    name=row["name"],
                    status=row["status"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    progress_pct=row["progress_pct"],
                    metadata=json.loads(row["metadata"] or "{}"),
                )
            )
        return steps

    def _upsert_step(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        step_id: str,
        name: str,
        status: str,
        progress_pct: Optional[float],
        metadata: Optional[Dict[str, Any]],
    ) -> None:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM run_steps WHERE run_id = ? AND step_id = ?",
            (run_id, step_id),
        ).fetchone()

        metadata_dict = metadata or {}
        now = utc_now_iso()

        if row:
            existing_metadata = json.loads(row["metadata"] or "{}")
            merged_metadata = self._merge_metadata(existing_metadata, metadata_dict)
            updated_progress = progress_pct if progress_pct is not None else row["progress_pct"]
            completed_at = row["completed_at"]
            if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                completed_at = now
            conn.execute(
                """
                UPDATE run_steps
                SET name = :name,
                    status = :status,
                    progress_pct = :progress_pct,
                    metadata = :metadata,
                    completed_at = :completed_at
                WHERE run_id = :run_id AND step_id = :step_id
                """,
                {
                    "name": name or row["name"],
                    "status": status,
                    "progress_pct": updated_progress,
                    "metadata": json.dumps(merged_metadata),
                    "completed_at": completed_at,
                    "run_id": run_id,
                    "step_id": step_id,
                },
            )
        else:
            conn.execute(
                """
                INSERT INTO run_steps (
                    run_id, step_id, name, status, started_at, completed_at, progress_pct, metadata
                ) VALUES (
                    :run_id, :step_id, :name, :status, :started_at, :completed_at, :progress_pct, :metadata
                )
                """,
                {
                    "run_id": run_id,
                    "step_id": step_id,
                    "name": name,
                    "status": status,
                    "started_at": now,
                    "completed_at": None,
                    "progress_pct": progress_pct,
                    "metadata": json.dumps(metadata_dict),
                },
            )

    def _build_metadata(self, request: RunCreateRequest) -> Dict[str, Any]:
        metadata = dict(request.metadata)
        if request.total_steps is not None:
            metadata.setdefault("execution", {})["total_steps"] = request.total_steps
        # Store triggering_user_id for credential resolution during GitHub operations
        if request.triggering_user_id:
            metadata["triggering_user_id"] = request.triggering_user_id
        return metadata

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

    def _merge_metadata(
        self,
        original: Dict[str, Any],
        additional: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged = dict(original)
        if additional:
            merged.update(additional)
        return merged

    @staticmethod
    def _calculate_duration_ms(start_iso: Optional[str], end_iso: str) -> Optional[int]:
        if not start_iso:
            return None
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        delta = end - start
        return int(delta.total_seconds() * 1000)

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    actor_surface TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workflow_id TEXT,
                    workflow_name TEXT,
                    template_id TEXT,
                    template_name TEXT,
                    behavior_ids TEXT NOT NULL,
                    current_step TEXT,
                    progress_pct REAL NOT NULL DEFAULT 0.0,
                    message TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms INTEGER,
                    outputs TEXT,
                    error TEXT,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_steps (
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    progress_pct REAL,
                    metadata TEXT NOT NULL,
                    PRIMARY KEY (run_id, step_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_template ON runs(template_id)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _resolve_db_path(db_path: Optional[Path]) -> Path:
        if db_path is not None:
            return db_path.expanduser().resolve()
        env_override = os.getenv(_RUN_DB_ENV)
        if env_override:
            return Path(env_override).expanduser().resolve()
        return _DEFAULT_DB_PATH
