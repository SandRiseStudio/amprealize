"""
Assignment Service for polymorphic assignment (user/agent) on features and tasks.
Supports audit trail in assignment_history and agent suggestion helper.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from amprealize.multi_tenant.board_contracts import (
    AgentSuggestion,
    AgentWorkload,
    AssigneeType,
    AssignmentAction,
    SuggestAgentRequest,
    SuggestAgentResponse,
)
from amprealize.multi_tenant.contracts import AgentStatus
from amprealize.services.board_service import BoardService, Actor
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.telemetry import TelemetryClient
from amprealize.utils.dsn import resolve_postgres_dsn

_BOARD_PG_DSN_ENV = "AMPREALIZE_BOARD_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


class AssignmentServiceError(Exception):
    """Base error for assignment service."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class AssignmentService:
    """Handle assignment/unassignment and agent suggestion for board items."""

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
        board_service: Optional[BoardService] = None,
    ) -> None:
        self._dsn = self._resolve_dsn(dsn)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._pool = PostgresPool(self._dsn)
        self._board_service = board_service or BoardService(dsn=self._dsn, telemetry=self._telemetry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign_agent(
        self,
        *,
        assignable_id: str,
        assignable_type: str,
        agent_id: str,
        actor: Actor,
        org_id: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        return self._assign(
            assignable_id=assignable_id,
            assignable_type=assignable_type,
            assignee_id=agent_id,
            assignee_type=AssigneeType.AGENT,
            actor=actor,
            org_id=org_id,
            reason=reason,
        )

    def assign_user(
        self,
        *,
        assignable_id: str,
        assignable_type: str,
        user_id: str,
        actor: Actor,
        org_id: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        return self._assign(
            assignable_id=assignable_id,
            assignable_type=assignable_type,
            assignee_id=user_id,
            assignee_type=AssigneeType.USER,
            actor=actor,
            org_id=org_id,
            reason=reason,
        )

    def unassign(
        self,
        *,
        assignable_id: str,
        assignable_type: str,
        actor: Actor,
        org_id: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        return self._assign(
            assignable_id=assignable_id,
            assignable_type=assignable_type,
            assignee_id=None,
            assignee_type=None,
            actor=actor,
            org_id=org_id,
            reason=reason,
            action_override=AssignmentAction.UNASSIGNED,
        )

    def suggest_agent(
        self,
        request: SuggestAgentRequest,
        *,
        actor: Optional[Actor] = None,
        org_id: Optional[str] = None,
    ) -> SuggestAgentResponse:
        """Suggest agents based on allowed behaviors + current workload."""
        assignable = self._fetch_assignable_for_context(request.assignable_id, request.assignable_type, org_id)
        required_behaviors = list(dict.fromkeys(request.required_behaviors))

        def _fetch(conn: Any) -> List[AgentSuggestion]:
            self._pool.set_tenant_context(conn, org_id, actor.id if actor else None)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.agent_id, a.name, a.status, av.default_behaviors,
                           COALESCE(w.active_items, 0) AS active_items,
                           COALESCE(w.in_progress_count, 0) AS in_progress_count,
                           COALESCE(w.completed_count, 0) AS completed_count,
                           COALESCE(w.total_points, 0) AS total_story_points
                    FROM agents a
                    LEFT JOIN agent_versions av
                        ON av.agent_id = a.agent_id AND av.version = a.latest_version
                    LEFT JOIN agent_workload w
                        ON w.assignee_id = a.agent_id AND w.assignee_type = 'agent'
                        AND (w.org_id = current_setting('app.current_org_id', TRUE) OR w.org_id IS NULL)
                    WHERE a.status IN ('active', 'idle', 'busy')
                    """,
                )
                rows = cur.fetchall()
                suggestions: List[AgentSuggestion] = []
                for row in rows:
                    agent_id, name, status_value, behaviors_raw, active_items, in_progress, completed, total_points = row
                    if request.exclude_agent_ids and agent_id in request.exclude_agent_ids:
                        continue
                    allowed_behaviors = behaviors_raw or []
                    matched = [b for b in required_behaviors if b in allowed_behaviors] if required_behaviors else []
                    if required_behaviors and not matched:
                        continue

                    behavior_score = 1.0 if not required_behaviors else len(matched) / len(required_behaviors)
                    workload_score = 1.0 / (1 + (active_items or 0))
                    # Slight boost if agent is idle
                    if status_value == AgentStatus.IDLE.value:
                        workload_score = min(1.0, workload_score + 0.1)
                    score = round(0.7 * behavior_score + 0.3 * workload_score, 4)

                    workload = AgentWorkload(
                        agent_id=agent_id,
                        agent_name=name,
                        active_items=active_items or 0,
                        in_progress_count=in_progress or 0,
                        completed_count=completed or 0,
                        total_story_points=int(total_points or 0),
                        allowed_behaviors=list(allowed_behaviors or []),
                    )

                    suggestions.append(
                        AgentSuggestion(
                            agent_id=agent_id,
                            agent_name=name,
                            score=score,
                            behavior_match_score=behavior_score,
                            workload_score=workload_score,
                            current_workload=workload,
                            matched_behaviors=matched,
                            reason=self._format_reason(behavior_score, workload_score, matched, active_items),
                        )
                    )

                suggestions.sort(key=lambda s: s.score, reverse=True)
                return suggestions[: request.max_suggestions]

        suggestions = self._pool.run_transaction(
            operation="assignment.suggest_agent",
            service_prefix="board",
            actor={"id": actor.id, "role": actor.role} if actor else None,
            metadata={"assignable_id": request.assignable_id, "assignable_type": request.assignable_type},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        return SuggestAgentResponse(
            suggestions=suggestions,
            assignable_id=request.assignable_id,
            assignable_type=request.assignable_type,
            required_behaviors=required_behaviors,
            total_eligible_agents=len(suggestions),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assign(
        self,
        *,
        assignable_id: str,
        assignable_type: str,
        assignee_id: Optional[str],
        assignee_type: Optional[AssigneeType],
        actor: Actor,
        org_id: Optional[str],
        reason: Optional[str],
        action_override: Optional[AssignmentAction] = None,
    ):
        if assignable_type not in {"story", "feature", "task"}:
            raise AssignmentServiceError(f"Unsupported assignable_type: {assignable_type}")
        # Normalize: 'feature' maps to legacy 'story' table
        _table_type = "story" if assignable_type in {"story", "feature"} else "task"

        timestamp = _now()
        assignable = self._fetch_assignable_for_context(assignable_id, assignable_type, org_id)
        previous_assignee_id = assignable.get("assignee_id")
        previous_assignee_type = assignable.get("assignee_type")
        action = action_override or self._derive_action(previous_assignee_id, assignee_id)

        def _execute(conn: Any):
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Close previous history if any
                if previous_assignee_id:
                    cur.execute(
                        """
                        INSERT INTO assignment_history (
                            history_id, assignable_id, assignable_type,
                            assignee_id, assignee_type, action,
                            performed_by, performed_at, previous_assignee_id, previous_assignee_type,
                            reason, metadata, org_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            _short("ahist"),
                            assignable_id,
                            assignable_type,
                            assignee_id,
                            assignee_type.value if assignee_type else None,
                            action.value,
                            actor.id,
                            timestamp,
                            previous_assignee_id,
                            previous_assignee_type.value if previous_assignee_type else None,
                            reason,
                            json.dumps({}),
                            org_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO assignment_history (
                            history_id, assignable_id, assignable_type,
                            assignee_id, assignee_type, action,
                            performed_by, performed_at, reason, metadata, org_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            _short("ahist"),
                            assignable_id,
                            assignable_type,
                            assignee_id,
                            assignee_type.value if assignee_type else None,
                            action.value,
                            actor.id,
                            timestamp,
                            reason,
                            json.dumps({}),
                            org_id,
                        ),
                    )

                # Update assignable
                table = "stories" if _table_type == "story" else "board_tasks"
                id_col = "story_id" if _table_type == "story" else "task_id"
                cur.execute(
                    f"""
                    UPDATE {table}
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE {id_col} = %s
                    """,
                    (
                        assignee_id,
                        assignee_type.value if assignee_type else None,
                        timestamp if assignee_id else None,
                        actor.id if assignee_id else None,
                        timestamp,
                        assignable_id,
                    ),
                )

        self._pool.run_transaction(
            operation="assignment.update",
            service_prefix="board",
            actor={"id": actor.id, "role": actor.role},
            metadata={"assignable_id": assignable_id, "assignable_type": assignable_type},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self._fetch_assignable_model(assignable_id, assignable_type, org_id)

    def _fetch_assignable_for_context(self, assignable_id: str, assignable_type: str, org_id: Optional[str]) -> Dict[str, Any]:
        _table_type = "story" if assignable_type in {"story", "feature"} else "task"
        table = "stories" if _table_type == "story" else "board_tasks"
        id_col = "story_id" if _table_type == "story" else "task_id"
        with self._pool.connection() as conn:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {id_col}, assignee_id, assignee_type, board_id, project_id FROM {table} WHERE {id_col} = %s",
                    (assignable_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise AssignmentServiceError(f"Assignable not found: {assignable_type}:{assignable_id}")
                assignee_type_value = row[2]
                assignee_type_enum = AssigneeType(assignee_type_value) if assignee_type_value else None
                return {
                    "id": row[0],
                    "assignee_id": row[1],
                    "assignee_type": assignee_type_enum,
                    "board_id": row[3],
                    "project_id": row[4],
                }

    def _fetch_assignable_model(self, assignable_id: str, assignable_type: str, org_id: Optional[str]):
        if assignable_type in {"story", "feature"}:
            return self._board_service.get_story(assignable_id, org_id=org_id)
        return self._board_service.get_task(assignable_id, org_id=org_id)

    def _resolve_dsn(self, provided: Optional[str]) -> str:
        if provided:
            return provided
        return resolve_postgres_dsn(
            service="board",
            explicit_dsn=None,
            env_var=_BOARD_PG_DSN_ENV,
            default_dsn=_DEFAULT_PG_DSN,
        )

    def _derive_action(self, previous: Optional[str], new: Optional[str]) -> AssignmentAction:
        if previous and new and previous != new:
            return AssignmentAction.REASSIGNED
        if new:
            return AssignmentAction.ASSIGNED
        return AssignmentAction.UNASSIGNED

    def _format_reason(
        self,
        behavior_score: float,
        workload_score: float,
        matched: List[str],
        active_items: int,
    ) -> str:
        parts = []
        parts.append(f"behavior_match={behavior_score:.2f}")
        parts.append(f"workload={workload_score:.2f} (active={active_items})")
        if matched:
            parts.append(f"matched_behaviors={','.join(matched)}")
        return "; ".join(parts)
