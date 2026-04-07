"""PostgreSQL-backed AgentOrchestratorService implementation.

Provides durable storage for agent assignments, persona definitions, and switching history.
Replaces in-memory dict storage with PostgreSQL for multi-tenant production deployments.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5, UUID

from amprealize.storage.postgres_pool import PostgresPool
from amprealize.agent_orchestrator_service import (
    AgentPersona,
    AgentSwitchEvent,
    AgentAssignment,
    _DEFAULT_PERSONA_DEFS,
)


class PostgresAgentOrchestratorService:
    """PostgreSQL-backed agent orchestrator with durable state."""

    def __init__(self, dsn: str) -> None:
        """Initialize with PostgreSQL connection.

        Args:
            dsn: PostgreSQL connection string (e.g., postgresql://user:pass@host:port/dbname)
        """
        self._pool = PostgresPool(dsn, service_name="agent_orchestrator")
        self._ensure_default_personas()

    def _ensure_default_personas(self) -> None:
        """Seed default personas if not already present."""
        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                for persona_def in _DEFAULT_PERSONA_DEFS:
                    cur.execute(
                        "SELECT id FROM agent_personas WHERE name = %s",
                        (persona_def["agent_id"],),
                    )
                    if cur.fetchone():
                        continue

                    cur.execute(
                        """
                        INSERT INTO agent_personas (
                            name, description, role,
                            capabilities, default_behaviors, system_prompt, is_active
                        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, TRUE)
                        """,
                        (
                            persona_def["agent_id"],
                            persona_def["display_name"],
                            persona_def["role_alignment"],
                            json.dumps(persona_def["capabilities"]),
                            persona_def["default_behaviors"],
                            json.dumps(persona_def["playbook_refs"]),
                        ),
                    )

        self._pool.run_transaction(
            "seed_default_personas",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def list_personas(self) -> List[AgentPersona]:
        """List all available agent personas."""
        def _query(conn: Any) -> List[AgentPersona]:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT name, description, role,
                           default_behaviors, capabilities, system_prompt
                    FROM agent_personas
                    WHERE is_active = TRUE
                    ORDER BY name
                    """
                )
                rows = cur.fetchall()
                return [
                    self._persona_from_row(row)
                    for row in rows
                ]

        return self._pool.run_transaction(
            "list_personas",
            executor=_query,
            service_prefix="agent_orchestrator",
        )

    def assign_agent(
        self,
        *,
        run_id: Optional[str],
        requested_agent_id: Optional[str],
        stage: str,
        context: Optional[Dict[str, Any]],
        requested_by: Dict[str, Any],
    ) -> AgentAssignment:
        """Assign an agent to a run with context-aware selection.

        Args:
            run_id: Run identifier (None for global assignment)
            requested_agent_id: Specific agent requested (None for heuristic selection)
            stage: Current stage (e.g., 'planning', 'execution', 'review')
            context: Context metadata for heuristics
            requested_by: Actor dict with id/role/surface

        Returns:
            AgentAssignment with assigned persona and heuristics
        """
        def _execute(conn: Any) -> AgentAssignment:
            with conn.cursor() as cur:
                run_identifier = run_id or str(uuid4())
                run_uuid = self._run_uuid(run_identifier)

                # Check for existing assignment
                if run_identifier:
                    cur.execute(
                        """
                        SELECT id, persona_id, status, assigned_at, context
                        FROM agent_assignments
                        WHERE run_id = %s AND unassigned_at IS NULL
                        """,
                        (run_uuid,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        existing_persona = self._fetch_persona_by_uuid(cur, existing[1])
                    else:
                        existing_persona = None

                    if existing and (
                        requested_agent_id is None
                        or (existing_persona and existing_persona.agent_id == requested_agent_id)
                    ):
                        # Return existing assignment
                        assignment_id = existing[0]
                        persona = existing_persona or self._fetch_persona_by_uuid(cur, existing[1])
                        history = self._fetch_history(cur, assignment_id)
                        stage_value, heuristics_value, requested_by_value, metadata_value = self._decode_assignment_context(
                            existing[4]
                        )
                        return AgentAssignment(
                            assignment_id=str(assignment_id),
                            run_id=run_identifier,
                            active_agent=persona,
                            stage=stage_value,
                            heuristics_applied=heuristics_value,
                            requested_by=requested_by_value,
                            timestamp=existing[3].isoformat(),
                            metadata=metadata_value,
                            history=history,
                        )

                # Select persona
                persona_id, persona = self._select_persona(cur, requested_agent_id, context)
                heuristics = self._build_heuristics(persona.agent_id, requested_agent_id, context)
                requested_by_payload = self._normalize_actor_payload(requested_by)
                self._ensure_run_record(
                    cur,
                    run_uuid=run_uuid,
                    run_id=run_identifier,
                    requested_by=requested_by_payload,
                    metadata=context or {},
                )
                assignment_context = self._encode_assignment_context(
                    run_id=run_identifier,
                    stage=stage,
                    heuristics=heuristics,
                    requested_by=requested_by_payload,
                    metadata=context or {},
                )

                # Create new assignment
                assignment_id = uuid4()
                timestamp = datetime.now(timezone.utc)
                cur.execute(
                    """
                    INSERT INTO agent_assignments (
                        id, run_id, persona_id, assigned_at, status, context
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        assignment_id,
                        run_uuid,
                        persona_id,
                        timestamp,
                        stage,
                        json.dumps(assignment_context),
                    ),
                )

                return AgentAssignment(
                        assignment_id=str(assignment_id),
                        run_id=run_identifier,
                        active_agent=persona,
                        stage=stage,
                        heuristics_applied=heuristics,
                        requested_by=requested_by_payload,
                        timestamp=timestamp.isoformat(),
                        metadata=context or {},
                        history=[],
                    )

        return self._pool.run_transaction(
            "assign_agent",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def switch_agent(
        self,
        *,
        assignment_id: str,
        target_agent_id: str,
        reason: Optional[str],
        allow_downgrade: bool,
        stage: Optional[str],
        issued_by: Optional[Dict[str, Any]],
    ) -> AgentAssignment:
        """Switch the assigned agent for a run.

        Args:
            assignment_id: Assignment to modify
            target_agent_id: New agent to assign
            reason: Human-readable reason for switch
            allow_downgrade: Whether to allow switching to less senior agent
            stage: Optional new stage
            issued_by: Actor dict with id/role/surface

        Returns:
            Updated AgentAssignment with switch event added to history
        """
        def _execute(conn: Any) -> AgentAssignment:
            with conn.cursor() as cur:
                # Fetch current assignment
                cur.execute(
                    """
                    SELECT run_id, persona_id, status, assigned_at, context
                    FROM agent_assignments
                    WHERE id = %s
                    """,
                    (UUID(assignment_id),),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(f"Unknown assignment_id: {assignment_id}")

                run_uuid, from_persona_uuid, current_stage, assigned_at, context_json = row
                from_persona = self._fetch_persona_by_uuid(cur, from_persona_uuid)
                to_persona_uuid, to_persona = self._fetch_persona_entity(cur, target_agent_id)
                _, _, requested_by_payload, metadata_json = self._decode_assignment_context(context_json)

                # Create switch event
                event_id = uuid4()
                new_stage = stage or current_stage
                trigger_details = {
                    "reason": reason or "manual_override",
                    "allow_downgrade": allow_downgrade,
                }
                timestamp = datetime.now(timezone.utc)

                cur.execute(
                    """
                    INSERT INTO board.assignment_history (
                        history_id, assignable_id, assignable_type,
                        assignee_id, assignee_type, action, performed_by,
                        performed_at, previous_assignee_id, previous_assignee_type,
                        reason, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        event_id.hex,
                        assignment_id,
                        "task",
                        target_agent_id,
                        "agent_persona",
                        "MANUAL" if reason else "HEURISTIC",
                        (issued_by.get("id") or issued_by.get("actor_id") or "unknown") if issued_by else "unknown",
                        timestamp,
                        from_persona.agent_id,
                        "agent_persona",
                        reason,
                        json.dumps({
                            "stage": new_stage,
                            "trigger_details": trigger_details,
                            "issued_by_role": (issued_by.get("role") or issued_by.get("actor_role") or "STUDENT") if issued_by else "STUDENT",
                            "issued_by_surface": (issued_by.get("surface") or issued_by.get("actor_surface") or "cli") if issued_by else "cli",
                        }),
                    ),
                )

                # Update assignment
                new_heuristics = self._build_heuristics(target_agent_id, target_agent_id, metadata_json if metadata_json else {})
                updated_context = self._encode_assignment_context(
                    run_id=self._run_id_from_uuid(run_uuid, context_json if context_json else {}),
                    stage=new_stage,
                    heuristics=new_heuristics,
                    requested_by=requested_by_payload,
                    metadata=metadata_json if metadata_json else {},
                )
                cur.execute(
                    """
                    UPDATE agent_assignments
                    SET persona_id = %s, status = %s, context = %s::jsonb
                    WHERE id = %s
                    """,
                    (
                        to_persona_uuid,
                        new_stage,
                        json.dumps(updated_context),
                        UUID(assignment_id),
                    ),
                )

                # Fetch full history
                history = self._fetch_history(cur, UUID(assignment_id))

                return AgentAssignment(
                    assignment_id=assignment_id,
                    run_id=self._run_id_from_uuid(run_uuid, metadata_json if metadata_json else {}),
                    active_agent=to_persona,
                    stage=new_stage,
                    heuristics_applied=new_heuristics,
                    requested_by=requested_by_payload,
                    timestamp=timestamp.isoformat(),
                    metadata=metadata_json if metadata_json else {},
                    history=history,
                )

        return self._pool.run_transaction(
            "switch_agent",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def get_status(
        self,
        *,
        run_id: Optional[str],
        assignment_id: Optional[str],
    ) -> Optional[AgentAssignment]:
        """Get current assignment status by run_id or assignment_id.

        Args:
            run_id: Run identifier
            assignment_id: Assignment UUID

        Returns:
            AgentAssignment if found, None otherwise
        """
        def _execute(conn: Any) -> Optional[AgentAssignment]:
            with conn.cursor() as cur:
                if assignment_id:
                    query = """
                        SELECT id, run_id, persona_id, status, assigned_at, context
                        FROM agent_assignments
                        WHERE id = %s
                    """
                    cur.execute(query, (UUID(assignment_id),))
                elif run_id:
                    query = """
                        SELECT id, run_id, persona_id, status, assigned_at, context
                        FROM agent_assignments
                        WHERE run_id = %s AND unassigned_at IS NULL
                    """
                    cur.execute(query, (self._run_uuid(run_id),))
                else:
                    return None

                row = cur.fetchone()
                if not row:
                    return None

                persona = self._fetch_persona_by_uuid(cur, row[2])
                history = self._fetch_history(cur, row[0])
                stage_value, heuristics_value, requested_by_value, metadata_value = self._decode_assignment_context(row[5])

                return AgentAssignment(
                    assignment_id=str(row[0]),
                    run_id=self._run_id_from_uuid(row[1], metadata_value),
                    active_agent=persona,
                    stage=stage_value,
                    heuristics_applied=heuristics_value,
                    requested_by=requested_by_value,
                    timestamp=row[4].isoformat(),
                    metadata=metadata_value,
                    history=history,
                )

        return self._pool.run_transaction(
            "get_status",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def _persona_from_row(self, row: Any) -> AgentPersona:
        playbook_refs: List[str] = []
        if row[5]:
            try:
                parsed = json.loads(row[5]) if isinstance(row[5], str) else row[5]
                if isinstance(parsed, list):
                    playbook_refs = [str(item) for item in parsed]
            except (TypeError, ValueError):
                playbook_refs = []

        return AgentPersona(
            agent_id=row[0],
            display_name=row[1] or row[0].replace("_", " ").title(),
            role_alignment=row[2],
            default_behaviors=list(row[3] or []),
            playbook_refs=playbook_refs,
            capabilities=list(row[4] or []),
        )

    def _fetch_persona_entity(self, cur: Any, agent_id: str) -> tuple[UUID, AgentPersona]:
        """Fetch persona UUID and contract model by logical agent_id."""
        cur.execute(
            """
            SELECT id, name, description, role,
                   default_behaviors, capabilities, system_prompt
            FROM agent_personas
            WHERE name = %s AND is_active = TRUE
            """,
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Unknown agent_id: {agent_id}")

        return row[0], self._persona_from_row(row[1:])

    def _fetch_persona(self, cur: Any, agent_id: str) -> AgentPersona:
        """Fetch persona by logical agent_id."""
        _, persona = self._fetch_persona_entity(cur, agent_id)
        return persona

    def _fetch_persona_by_uuid(self, cur: Any, persona_id: UUID) -> AgentPersona:
        """Fetch persona by database UUID."""
        cur.execute(
            """
            SELECT name, description, role,
                   default_behaviors, capabilities, system_prompt
            FROM agent_personas
            WHERE id = %s
            """,
            (persona_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Unknown persona_id: {persona_id}")

        return self._persona_from_row(row)

    def _fetch_history(self, cur: Any, assignment_id: UUID) -> List[AgentSwitchEvent]:
        """Fetch switch history for an assignment."""
        cur.execute(
            """
            SELECT history_id, previous_assignee_id, assignee_id, action,
                   performed_by, performed_at, metadata
            FROM board.assignment_history
            WHERE assignable_id = %s AND assignable_type = %s
            ORDER BY performed_at ASC
            """,
            (str(assignment_id), "task"),
        )
        rows = cur.fetchall()
        return [
            AgentSwitchEvent(
                event_id=str(row[0]),
                from_agent_id=row[1],
                to_agent_id=row[2],
                stage=(row[6] or {}).get("stage", "planning"),
                trigger=row[3],
                trigger_details=(row[6] or {}).get("trigger_details", {}),
                timestamp=row[5].isoformat(),
                issued_by={
                    "actor_id": row[4],
                    "actor_role": (row[6] or {}).get("issued_by_role"),
                } if row[4] else {},
            )
            for row in rows
        ]

    def _select_persona(
        self,
        cur: Any,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> tuple[UUID, AgentPersona]:
        """Select persona based on request or heuristics."""
        # Direct request takes priority
        if requested_agent_id:
            try:
                return self._fetch_persona_entity(cur, requested_agent_id)
            except KeyError:
                pass  # Fall through to heuristics

        # Apply heuristics from context
        if context:
            task_type = context.get("task_type")
            if task_type:
                cur.execute(
                    """
                    SELECT id, name, description, role,
                           default_behaviors, capabilities, system_prompt
                    FROM agent_personas
                    WHERE name = %s AND is_active = TRUE
                    """,
                    (task_type,),
                )
                row = cur.fetchone()
                if row:
                    return row[0], self._persona_from_row(row[1:])

        # Default to engineering
        try:
            return self._fetch_persona_entity(cur, "engineering")
        except KeyError:
            # Fall back to first available persona
            cur.execute(
                """
                SELECT id, name, description, role,
                       default_behaviors, capabilities, system_prompt
                FROM agent_personas
                WHERE is_active = TRUE
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No agent personas available")

            return row[0], self._persona_from_row(row[1:])

    def _normalize_actor_payload(self, actor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Normalize actor payloads to the in-memory contract shape."""
        actor = actor or {}
        normalized: Dict[str, Any] = {}
        actor_id = actor.get("actor_id") or actor.get("id")
        actor_role = actor.get("actor_role") or actor.get("role")
        actor_surface = actor.get("actor_surface") or actor.get("surface")

        if actor_id is not None:
            normalized["actor_id"] = actor_id
        if actor_role is not None:
            normalized["actor_role"] = actor_role
        if actor_surface is not None:
            normalized["actor_surface"] = actor_surface
        return normalized

    def _encode_assignment_context(
        self,
        *,
        run_id: str,
        stage: str,
        heuristics: Dict[str, Any],
        requested_by: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Store parity-specific fields inside the context JSONB column."""
        return {
            "run_id": run_id,
            "metadata": metadata,
            "stage": stage,
            "heuristics_applied": heuristics,
            "requested_by": requested_by,
        }

    def _decode_assignment_context(
        self,
        payload: Optional[Dict[str, Any]],
    ) -> tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Recover parity fields from the context JSONB column."""
        payload = payload or {}
        metadata = payload.get("metadata") or {}
        stage = payload.get("stage") or "planning"
        heuristics = payload.get("heuristics_applied") or self._build_heuristics(
            selected_agent_id=metadata.get("task_type") or "engineering",
            requested_agent_id=None,
            context=metadata,
        )
        requested_by = payload.get("requested_by") or {}
        return stage, heuristics, requested_by, metadata

    def _run_uuid(self, run_id: str) -> UUID:
        """Map arbitrary run IDs to stable UUIDs required by the execution schema."""
        return uuid5(NAMESPACE_URL, f"amprealize-agent-orchestrator:{run_id}")

    def _run_id_from_uuid(self, run_uuid: UUID, metadata: Dict[str, Any]) -> str:
        """Return the original logical run ID when available."""
        original = metadata.get("run_id")
        return str(original) if original else str(run_uuid)

    def _ensure_run_record(
        self,
        cur: Any,
        *,
        run_uuid: UUID,
        run_id: str,
        requested_by: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> None:
        """Create a minimal execution.runs record when parity tests use synthetic run IDs."""
        cur.execute("SELECT 1 FROM runs WHERE id = %s", (run_uuid,))
        if cur.fetchone():
            return

        cur.execute(
            """
            INSERT INTO runs (
                id, user_id, name, status, actor_surface, context
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                run_uuid,
                None,
                run_id,
                "pending",
                requested_by.get("actor_surface"),
                json.dumps({"run_id": run_id, **metadata}),
            ),
        )

    def _build_heuristics(
        self,
        selected_agent_id: str,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build heuristics metadata for assignment."""
        return {
            "selected_agent_id": selected_agent_id,
            "requested_agent_id": requested_agent_id,
            "task_type": context.get("task_type") if context else None,
            "compliance_tags": context.get("compliance_tags") if context else None,
            "severity": context.get("severity") if context else None,
        }
