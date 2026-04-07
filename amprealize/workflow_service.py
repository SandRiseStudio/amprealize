"""Workflow Engine Foundation for Strategist/Teacher/Student templates.

Implements behavior-conditioned inference (BCI) integration with the BehaviorService,
enabling runtime template execution that injects retrieved behaviors into prompts.

Aligns with:
- PRD.md: Milestone 1 Workflow Engine Foundation
- AGENTS.md: Strategist/Teacher/Student role definitions
- docs/contracts/MCP_SERVER_DESIGN.md: Control-plane orchestration patterns
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from amprealize.action_contracts import Actor, utc_now_iso
from amprealize.telemetry import TelemetryClient
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.storage.redis_cache import get_cache
from .utils.dsn import resolve_postgres_dsn

_WORKFLOW_PG_DSN_ENV = "AMPREALIZE_WORKFLOW_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize_workflow:dev_workflow_pass@localhost:5434/workflows"


# Module-level telemetry client
_telemetry = TelemetryClient.noop()


def set_telemetry_client(client: TelemetryClient) -> None:
    """Set the module-level telemetry client."""
    global _telemetry
    _telemetry = client


def emit_event(event_type: str, payload: Dict[str, Any]) -> None:
    """Emit a telemetry event using the module client."""
    _telemetry.emit_event(event_type=event_type, payload=payload)


class WorkflowRole(str, Enum):
    """Role focus for workflow templates (matches BehaviorService role_focus)."""

    STRATEGIST = "STRATEGIST"
    TEACHER = "TEACHER"
    STUDENT = "STUDENT"
    MULTI_ROLE = "MULTI_ROLE"


class WorkflowStatus(str, Enum):
    """Execution status for workflow runs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TemplateStep:
    """Individual step within a workflow template."""

    step_id: str
    name: str
    description: str
    prompt_template: str
    behavior_injection_point: str  # Placeholder like {{BEHAVIORS}} in prompt
    required_behaviors: List[str] = field(default_factory=list)  # Behavior IDs to inject
    validation_rules: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowTemplate:
    """Template definition for Strategist/Teacher/Student workflows."""

    template_id: str
    name: str
    description: str
    role_focus: WorkflowRole
    steps: List[TemplateStep]
    created_at: str
    created_by: Actor
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        data = asdict(self)
        data["role_focus"] = self.role_focus.value
        data["created_by"] = asdict(self.created_by)
        data["steps"] = [asdict(step) for step in self.steps]
        # Convert datetime objects to ISO format strings for JSON serialization
        if isinstance(self.created_at, datetime):
            data["created_at"] = self.created_at.isoformat()
        return data


@dataclass
class WorkflowRunStep:
    """Runtime execution state for a template step."""

    step_id: str
    status: WorkflowStatus
    prompt_rendered: str  # Prompt with behaviors injected
    behaviors_used: List[str]
    output: Optional[str] = None
    token_count: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class WorkflowRun:
    """Runtime execution record for a workflow template."""

    run_id: str
    template_id: str
    template_name: str
    role_focus: WorkflowRole
    status: WorkflowStatus
    actor: Actor
    steps: List[WorkflowRunStep]
    started_at: str
    completed_at: Optional[str] = None
    total_tokens: int = 0
    behaviors_cited: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        data = asdict(self)
        data["role_focus"] = self.role_focus.value
        data["status"] = self.status.value
        data["actor"] = asdict(self.actor)
        data["steps"] = [
            {**asdict(step), "status": step.status.value}
            for step in self.steps
        ]
        # Convert datetime objects to ISO format strings for JSON serialization
        if isinstance(self.started_at, datetime):
            data["started_at"] = self.started_at.isoformat()
        if self.completed_at and isinstance(self.completed_at, datetime):
            data["completed_at"] = self.completed_at.isoformat()
        return data


class WorkflowService:
    """Service for workflow template management and execution with BCI."""

    def __init__(self, dsn: Optional[str] = None, behavior_service=None):
        """Initialize the WorkflowService with PostgreSQL backend.

        Args:
            dsn: PostgreSQL DSN connection string
            behavior_service: Optional BehaviorService instance for behavior retrieval
        """
        self.dsn = resolve_postgres_dsn(
            service="WORKFLOW",
            explicit_dsn=dsn,
            env_var=_WORKFLOW_PG_DSN_ENV,
            default_dsn=os.getenv(_WORKFLOW_PG_DSN_ENV, _DEFAULT_PG_DSN),
        )
        self.behavior_service = behavior_service
        self._pool = PostgresPool(self.dsn)
        self._workflow_template_mode: Optional[str] = None
        self._workflow_run_mode: Optional[str] = None

    def _ensure_connection(self):
        """Acquire a pooled PostgreSQL connection proxy."""
        return self._pool.proxy()

    def _has_column(self, table_name: str, column_name: str) -> bool:
        """Check whether a table column exists in the active search path."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
                LIMIT 1
                """,
                (table_name, column_name),
            )
            return cur.fetchone() is not None

    def _template_schema_mode(self) -> str:
        """Return workflow template schema mode: legacy or compact."""
        if self._workflow_template_mode is None:
            self._workflow_template_mode = "legacy" if self._has_column("workflow_templates", "template_id") else "compact"
        return self._workflow_template_mode

    def _run_schema_mode(self) -> str:
        """Return workflow run schema mode: legacy or compact."""
        if self._workflow_run_mode is None:
            self._workflow_run_mode = "legacy" if self._has_column("workflow_runs", "run_id") else "compact"
        return self._workflow_run_mode

    def _template_uuid(self, template_id: str) -> UUID:
        """Map external workflow template IDs to stable UUIDs."""
        return uuid5(NAMESPACE_URL, f"amprealize-workflow-template:{template_id}")

    def _run_uuid(self, run_id: str) -> UUID:
        """Map external workflow run IDs to stable UUIDs."""
        return uuid5(NAMESPACE_URL, f"amprealize-workflow-run:{run_id}")

    def _serialize_steps(self, steps: List[TemplateStep]) -> List[Dict[str, Any]]:
        """Serialize template steps for JSON storage."""
        return [asdict(step) for step in steps]

    def _build_compact_template_triggers(
        self,
        *,
        template_id: str,
        role_focus: WorkflowRole,
        actor: Actor,
        tags: List[str],
        metadata: Dict[str, Any],
        version: str,
    ) -> Dict[str, Any]:
        """Encode the legacy template contract into the compact triggers column."""
        return {
            "_contract": {
                "template_id": template_id,
                "role_focus": role_focus.value,
                "created_by": asdict(actor),
                "tags": list(tags),
                "metadata": metadata,
                "version": version,
            }
        }

    def _build_template_from_compact_row(self, row: Any) -> WorkflowTemplate:
        """Reconstruct WorkflowTemplate from the compact live schema."""
        triggers = row[5] if isinstance(row[5], dict) else {}
        contract = triggers.get("_contract", {}) if isinstance(triggers, dict) else {}
        created_by_payload = contract.get("created_by") or {"id": "unknown", "role": "UNKNOWN", "surface": "api"}
        created_at = row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6])
        return WorkflowTemplate(
            template_id=contract.get("template_id", f"wf-{str(row[0])[:12]}"),
            name=row[1],
            description=row[2] or "",
            role_focus=WorkflowRole(contract.get("role_focus", WorkflowRole.MULTI_ROLE.value)),
            steps=[TemplateStep(**step) for step in (row[4] or [])],
            created_at=created_at,
            created_by=Actor(**created_by_payload),
            version=str(contract.get("version", row[3])),
            tags=list(contract.get("tags") or []),
            metadata=contract.get("metadata") or {},
        )

    def _build_compact_run_payload(self, run: WorkflowRun) -> Dict[str, Any]:
        """Encode workflow run contract data into compact run storage."""
        return {"run_data": run.to_dict()}

    def _run_from_payload(self, data: Dict[str, Any]) -> WorkflowRun:
        """Reconstruct WorkflowRun from persisted JSON payload."""
        payload = data.get("run_data", data)
        return WorkflowRun(
            run_id=payload["run_id"],
            template_id=payload["template_id"],
            template_name=payload["template_name"],
            role_focus=WorkflowRole(payload["role_focus"]),
            status=WorkflowStatus(payload["status"]),
            actor=Actor(**payload["actor"]),
            steps=[
                WorkflowRunStep(
                    step_id=s["step_id"],
                    status=WorkflowStatus(s["status"]),
                    prompt_rendered=s["prompt_rendered"],
                    behaviors_used=s["behaviors_used"],
                    output=s.get("output"),
                    token_count=s.get("token_count"),
                    started_at=s.get("started_at"),
                    completed_at=s.get("completed_at"),
                    error=s.get("error"),
                )
                for s in payload["steps"]
            ],
            started_at=payload["started_at"],
            completed_at=payload.get("completed_at"),
            total_tokens=payload["total_tokens"],
            behaviors_cited=payload["behaviors_cited"],
            metadata=payload["metadata"],
        )

    def create_template(
        self,
        name: str,
        description: str,
        role_focus: WorkflowRole,
        steps: List[TemplateStep],
        actor: Actor,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowTemplate:
        """Create a new workflow template.

        Args:
            name: Template name
            description: Template description
            role_focus: Primary role (STRATEGIST/TEACHER/STUDENT/MULTI_ROLE)
            steps: List of template steps with behavior injection points
            actor: Actor creating the template
            tags: Optional tags for categorization
            metadata: Optional additional metadata

        Returns:
            Created WorkflowTemplate
        """
        template_id = f"wf-{uuid4().hex[:12]}"
        created_at = utc_now_iso()
        version = "1.0.0"

        template = WorkflowTemplate(
            template_id=template_id,
            name=name,
            description=description,
            role_focus=role_focus,
            steps=steps,
            created_at=created_at,
            created_by=actor,
            version=version,
            tags=tags or [],
            metadata=metadata or {},
        )

        if self._template_schema_mode() == "compact":
            created_at_dt = datetime.now(timezone.utc)
            template.created_at = created_at_dt.isoformat()

            def _execute_compact(conn: Any) -> None:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO workflow_templates (
                            id, name, description, version, steps, triggers,
                            is_active, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                        """,
                        (
                            self._template_uuid(template_id),
                            name,
                            description,
                            1,
                            json.dumps(self._serialize_steps(steps)),
                            json.dumps(
                                self._build_compact_template_triggers(
                                    template_id=template_id,
                                    role_focus=role_focus,
                                    actor=actor,
                                    tags=tags or [],
                                    metadata=metadata or {},
                                    version=version,
                                )
                            ),
                            True,
                            created_at_dt,
                            created_at_dt,
                        ),
                    )

            self._pool.run_transaction(
                operation="create_template",
                service_prefix="workflow",
                actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
                metadata={"template_id": template_id, "name": name},
                executor=_execute_compact,
                telemetry=None,
            )

            get_cache().invalidate_service('workflow')

            emit_event(
                "workflow.template.created",
                {
                    "template_id": template_id,
                    "name": name,
                    "role_focus": role_focus.value,
                    "step_count": len(steps),
                    "actor": asdict(actor),
                },
            )

            return template

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Insert into workflow_templates header table
                cur.execute(
                    """
                    INSERT INTO workflow_templates (
                        template_id, name, description, role_focus, version,
                        created_at, created_by_id, created_by_role, created_by_surface,
                        template_data, tags, status, latest_version, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        template_id,
                        name,
                        description,
                        role_focus.value,
                        version,  # Old version column (kept for compatibility)
                        created_at,
                        actor.id,
                        actor.role,
                        actor.surface,
                        json.dumps({}),  # Empty template_data (deprecated, kept for schema compat)
                        json.dumps(tags or []),
                        'APPROVED',  # New templates are approved by default
                        version,
                        created_at,
                    ),
                )

                # Insert into workflow_template_versions table
                cur.execute(
                    """
                    INSERT INTO workflow_template_versions (
                        template_id, version, steps, status, metadata,
                        effective_from, effective_to,
                        created_by_id, created_by_role, created_by_surface,
                        approval_action_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        template_id,
                        version,
                        json.dumps([asdict(step) for step in steps]),
                        'APPROVED',
                        json.dumps(metadata or {}),
                        created_at,
                        None,  # effective_to NULL for current version
                        actor.id,
                        actor.role,
                        actor.surface,
                        None,  # approval_action_id can be added later
                    ),
                )

        self._pool.run_transaction(
            operation="create_template",
            service_prefix="workflow",
            actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
            metadata={"template_id": template_id, "name": name},
            executor=_execute,
            telemetry=None,  # WorkflowService uses global emit_event
        )

        # Invalidate list cache since we added a new template
        get_cache().invalidate_service('workflow')

        emit_event(
            "workflow.template.created",
            {
                "template_id": template_id,
                "name": name,
                "role_focus": role_focus.value,
                "step_count": len(steps),
                "actor": asdict(actor),
            },
        )

        return template

    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """Retrieve a workflow template by ID using JOIN query with cache-first pattern.

        Args:
            template_id: Template identifier

        Returns:
            WorkflowTemplate if found with APPROVED version, None otherwise
        """
        # Try cache first
        cache = get_cache()
        cache_key = cache._make_key('workflow', 'get', {'template_id': template_id})
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            if cached_result:
                # Reconstruct from cached dict with proper types
                cached_result['steps'] = [TemplateStep(**step) for step in cached_result['steps']]
                cached_result['role_focus'] = WorkflowRole(cached_result['role_focus'])
                cached_result['created_by'] = Actor(**cached_result['created_by'])
                return WorkflowTemplate(**cached_result)
            return None

        # Cache miss - fetch from database
        if self._template_schema_mode() == "compact":
            conn = self._ensure_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, description, version, steps, triggers, created_at
                    FROM workflow_templates
                    WHERE id = %s AND is_active = TRUE
                    """,
                    (self._template_uuid(template_id),),
                )
                row = cur.fetchone()

                if not row:
                    cache.set(cache_key, None, ttl=60)
                    return None

                template = self._build_template_from_compact_row(row)
                cache.set(cache_key, template.to_dict(), ttl=600)
                return template

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # JOIN query to get template header + current APPROVED version
            cur.execute(
                """
                SELECT
                    wt.template_id, wt.name, wt.description, wt.role_focus,
                    wt.created_at, wt.created_by_id, wt.created_by_role, wt.created_by_surface,
                    wt.tags, wt.latest_version,
                    wtv.version, wtv.steps, wtv.metadata
                FROM workflow_templates wt
                LEFT JOIN workflow_template_versions wtv
                    ON wt.template_id = wtv.template_id
                    AND wtv.status = 'APPROVED'
                    AND wtv.effective_to IS NULL
                WHERE wt.template_id = %s
                """,
                (template_id,),
            )
            row = cur.fetchone()

            if not row or row[10] is None:  # No template or no APPROVED version
                # Cache the None result to avoid repeated lookups
                cache.set(cache_key, None, ttl=60)
                return None

            # Reconstruct WorkflowTemplate from JOIN result
            template = WorkflowTemplate(
                template_id=row[0],
                name=row[1],
                description=row[2],
                role_focus=WorkflowRole(row[3]),
                created_at=row[4],
                created_by=Actor(id=row[5], role=row[6], surface=row[7]),
                tags=row[8] or [],
                version=row[10],  # version from workflow_template_versions
                steps=[TemplateStep(**step) for step in (row[11] or [])],  # steps JSONB
                metadata=row[12] or {},
            )

            # Cache result for 10 minutes (600s) - templates change less frequently than behaviors
            cache.set(cache_key, template.to_dict(), ttl=600)
            return template

    def list_templates(
        self,
        role_focus: Optional[WorkflowRole] = None,
        tags: Optional[List[str]] = None,
    ) -> List[WorkflowTemplate]:
        """List workflow templates with optional filters using JOIN query with caching.

        Args:
            role_focus: Filter by role (optional)
            tags: Filter by tags (optional)

        Returns:
            List of matching WorkflowTemplate instances with APPROVED versions
        """
        # Build cache key from query parameters
        cache = get_cache()
        cache_params = {}
        if role_focus:
            cache_params['role_focus'] = role_focus.value
        if tags:
            cache_params['tags'] = sorted(tags)  # Sort for consistent hashing

        cache_key = cache._make_key('workflow', 'list', cache_params if cache_params else None)

        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            # Reconstruct from cached dicts with proper types
            templates = []
            for t in cached_result:
                t['steps'] = [TemplateStep(**step) for step in t['steps']]
                t['role_focus'] = WorkflowRole(t['role_focus'])
                t['created_by'] = Actor(**t['created_by'])
                templates.append(WorkflowTemplate(**t))
            return templates

        # Cache miss - fetch from database
        if self._template_schema_mode() == "compact":
            conn = self._ensure_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, description, version, steps, triggers, created_at
                    FROM workflow_templates
                    WHERE is_active = TRUE
                    ORDER BY updated_at DESC, created_at DESC
                    """
                )
                rows = cur.fetchall()

                templates = []
                for row in rows:
                    template = self._build_template_from_compact_row(row)
                    if role_focus and template.role_focus != role_focus:
                        continue
                    if tags and not any(tag in template.tags for tag in tags):
                        continue
                    templates.append(template)

                cache.set(cache_key, [t.to_dict() for t in templates], ttl=600)
                return templates

        query = """
            SELECT
                wt.template_id, wt.name, wt.description, wt.role_focus,
                wt.created_at, wt.created_by_id, wt.created_by_role, wt.created_by_surface,
                wt.tags, wt.latest_version, wt.updated_at,
                wtv.version, wtv.steps, wtv.metadata
            FROM workflow_templates wt
            LEFT JOIN workflow_template_versions wtv
                ON wt.template_id = wtv.template_id
                AND wtv.status = 'APPROVED'
                AND wtv.effective_to IS NULL
            WHERE wt.status = 'APPROVED'
        """
        params: List[Any] = []

        if role_focus:
            query += " AND wt.role_focus = %s"
            params.append(role_focus.value)

        query += " ORDER BY wt.updated_at DESC"

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

            templates = []
            for row in rows:
                if row[11] is None:  # No APPROVED version, skip
                    continue

                template_tags = row[8] or []

                # Filter by tags if specified
                if tags and not any(tag in template_tags for tag in tags):
                    continue

                templates.append(
                    WorkflowTemplate(
                        template_id=row[0],
                        name=row[1],
                        description=row[2],
                        role_focus=WorkflowRole(row[3]),
                        created_at=row[4],
                        created_by=Actor(id=row[5], role=row[6], surface=row[7]),
                        tags=template_tags,
                        version=row[11],  # version from workflow_template_versions
                        steps=[TemplateStep(**step) for step in (row[12] or [])],
                        metadata=row[13] or {},
                    )
                )

            # Cache result for 10 minutes (600s) - templates change less frequently than behaviors
            cache.set(cache_key, [t.to_dict() for t in templates], ttl=600)
            return templates

    def run_workflow(
        self,
        template_id: str,
        actor: Actor,
        behavior_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        enable_early_retrieval: bool = True,
    ) -> WorkflowRun:
        """Execute a workflow template with behavior-conditioned inference.

        Args:
            template_id: Template to execute
            actor: Actor running the workflow
            behavior_ids: Optional list of behavior IDs to inject (auto-retrieves if None)
            metadata: Optional run metadata
            enable_early_retrieval: Whether to enable Early Knowledge Alignment (EKA)

        Returns:
            WorkflowRun with execution state
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")

        run_id = f"run-{uuid4().hex[:12]}"
        started_at = utc_now_iso()

        # Initialize run with pending steps
        metadata_copy: Dict[str, Any] = dict(metadata or {})

        # Store EKA config in metadata for execution loop to read
        metadata_copy["enable_early_retrieval"] = enable_early_retrieval

        baseline_tokens = metadata_copy.get("baseline_tokens")
        if baseline_tokens is not None:
            try:
                baseline_tokens = int(baseline_tokens)
            except (TypeError, ValueError):
                baseline_tokens = None

        run = WorkflowRun(
            run_id=run_id,
            template_id=template_id,
            template_name=template.name,
            role_focus=template.role_focus,
            status=WorkflowStatus.PENDING,
            actor=actor,
            steps=[],
            started_at=started_at,
            metadata=metadata_copy,
        )

        # Consolidate behaviors cited from explicit injections and template requirements
        cited_behaviors: List[str] = []
        if behavior_ids:
            cited_behaviors.extend(list(behavior_ids))
        for step in template.steps:
            cited_behaviors.extend(step.required_behaviors)

        if cited_behaviors:
            unique_behaviors = list(dict.fromkeys(cited_behaviors))
            run.behaviors_cited = unique_behaviors
        else:
            run.behaviors_cited = []

        if baseline_tokens is None:
            # Default baseline equals number of required behaviors * 500 tokens (rough heuristic)
            baseline_tokens = max(len(run.behaviors_cited) * 500, 0)
            if baseline_tokens:
                metadata_copy["baseline_tokens"] = baseline_tokens
        else:
            metadata_copy["baseline_tokens"] = baseline_tokens

        emit_event(
            "workflow.run.started",
            {
                "run_id": run_id,
                "template_id": template_id,
                "role_focus": template.role_focus.value,
                "actor": asdict(actor),
            },
        )

        if self._run_schema_mode() == "compact":
            started_at_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))

            def _execute_compact(conn: Any) -> None:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO workflow_runs (
                            id, template_id, template_version, status, current_step,
                            context, result, error, started_at, completed_at, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                        """,
                        (
                            self._run_uuid(run_id),
                            self._template_uuid(template_id),
                            1,
                            WorkflowStatus.PENDING.value,
                            0,
                            json.dumps(self._build_compact_run_payload(run)),
                            json.dumps({}),
                            None,
                            started_at_dt,
                            None,
                            datetime.now(timezone.utc),
                        ),
                    )

            self._pool.run_transaction(
                operation="run_workflow",
                service_prefix="workflow",
                actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
                metadata={"run_id": run_id, "template_id": template_id},
                executor=_execute_compact,
                telemetry=None,
            )

            emit_event(
                "plan_created",
                {
                    "run_id": run_id,
                    "template_id": template_id,
                    "template_name": template.name,
                    "role_focus": template.role_focus.value,
                    "behavior_ids": list(run.behaviors_cited),
                    "behavior_count": len(run.behaviors_cited),
                    "baseline_tokens": metadata_copy.get("baseline_tokens"),
                    "checklist_snapshot": metadata_copy.get("checklist_snapshot"),
                    "metadata_keys": sorted(metadata_copy.keys()),
                },
            )

            return run

        # Store run record
        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_id, template_id, template_name, role_focus, status,
                        actor_id, actor_role, actor_surface, started_at, run_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        template_id,
                        template.name,
                        template.role_focus.value,
                        WorkflowStatus.PENDING.value,
                        actor.id,
                        actor.role,
                        actor.surface,
                        started_at,
                        json.dumps(run.to_dict()),
                    ),
                )

        self._pool.run_transaction(
            operation="run_workflow",
            service_prefix="workflow",
            actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
            metadata={"run_id": run_id, "template_id": template_id},
            executor=_execute,
            telemetry=None,  # WorkflowService uses global emit_event
        )

        emit_event(
            "plan_created",
            {
                "run_id": run_id,
                "template_id": template_id,
                "template_name": template.name,
                "role_focus": template.role_focus.value,
                "behavior_ids": list(run.behaviors_cited),
                "behavior_count": len(run.behaviors_cited),
                "baseline_tokens": metadata_copy.get("baseline_tokens"),
                "checklist_snapshot": metadata_copy.get("checklist_snapshot"),
                "metadata_keys": sorted(metadata_copy.keys()),
            },
        )

        return run

    def inject_behaviors(
        self,
        prompt_template: str,
        injection_point: str,
        behavior_ids: List[str],
    ) -> Tuple[str, List[str]]:
        """Inject behaviors into a prompt template at the specified point.

        Args:
            prompt_template: Template string with injection point
            injection_point: Placeholder to replace (e.g., {{BEHAVIORS}})
            behavior_ids: List of behavior IDs to inject

        Returns:
            Tuple of (rendered_prompt, behaviors_used)
        """
        behaviors_used = []
        behavior_text = ""

        if self.behavior_service and behavior_ids:
            behaviors = []
            for bid in behavior_ids:
                behavior = self.behavior_service.get_behavior(bid)
                if behavior:
                    behaviors.append(behavior)
                    behaviors_used.append(bid)

            # Format behaviors for injection
            if behaviors:
                behavior_text = "\n\n## Available Behaviors\n\n"
                for b in behaviors:
                    behavior_text += f"- **{b['name']}**: {b['description']}\n"
                behavior_text += "\nReference these behaviors by name when applicable.\n"

        # Replace injection point
        rendered = prompt_template.replace(injection_point, behavior_text)

        return rendered, behaviors_used

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        """Retrieve a workflow run by ID.

        Args:
            run_id: Run identifier

        Returns:
            WorkflowRun if found, None otherwise
        """
        if self._run_schema_mode() == "compact":
            conn = self._ensure_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT context, result FROM workflow_runs WHERE id = %s",
                    (self._run_uuid(run_id),),
                )
                row = cur.fetchone()

                if not row:
                    return None

                context_payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                result_payload = row[1] if isinstance(row[1], dict) else (json.loads(row[1]) if row[1] else {})
                payload = context_payload or result_payload
                if not payload:
                    return None
                return self._run_from_payload(payload)

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_data FROM workflow_runs WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()

            if not row:
                return None

            # PostgreSQL returns JSONB as dict, SQLite returned string
            data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            return self._run_from_payload(data)

    def update_run_status(
        self,
        run_id: str,
        status: WorkflowStatus,
        total_tokens: Optional[int] = None,
    ) -> None:
        """Update workflow run status and token count.

        Args:
            run_id: Run identifier
            status: New status
            total_tokens: Optional updated token count
        """
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        run.status = status
        if total_tokens is not None:
            run.total_tokens = total_tokens

        if status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
            run.completed_at = utc_now_iso()

        baseline_tokens = run.metadata.get("baseline_tokens")
        if isinstance(baseline_tokens, str):
            try:
                baseline_tokens = int(baseline_tokens)
            except ValueError:
                baseline_tokens = None

        if baseline_tokens is None and run.total_tokens:
            baseline_tokens = run.total_tokens
            run.metadata["baseline_tokens"] = baseline_tokens

        token_savings_pct: Optional[float] = None
        if baseline_tokens and baseline_tokens > 0:
            calculated = 1 - (run.total_tokens / baseline_tokens)
            token_savings_pct = max(min(calculated, 1.0), -1.0)

        context_keys: List[str] = []
        context = run.metadata.get("context")
        if isinstance(context, dict):
            context_keys = sorted(context.keys())

        if self._run_schema_mode() == "compact":
            completed_at_dt = (
                datetime.fromisoformat(run.completed_at.replace("Z", "+00:00"))
                if isinstance(run.completed_at, str) and run.completed_at
                else None
            )

            def _execute_compact(conn: Any) -> None:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE workflow_runs
                        SET status = %s,
                            current_step = %s,
                            context = %s::jsonb,
                            result = %s::jsonb,
                            error = %s,
                            completed_at = %s
                        WHERE id = %s
                        """,
                        (
                            status.value,
                            len(run.steps),
                            json.dumps(self._build_compact_run_payload(run)),
                            json.dumps(self._build_compact_run_payload(run) if status == WorkflowStatus.COMPLETED else {}),
                            run.metadata.get("error") if status == WorkflowStatus.FAILED else None,
                            completed_at_dt,
                            self._run_uuid(run_id),
                        ),
                    )

            self._pool.run_transaction(
                operation="update_run_status",
                service_prefix="workflow",
                actor={"id": run.actor.id, "role": run.actor.role, "surface": run.actor.surface},
                metadata={"run_id": run_id, "status": status.value},
                executor=_execute_compact,
                telemetry=None,
            )

            emit_event(
                "execution_update",
                {
                    "run_id": run_id,
                    "template_id": run.template_id,
                    "status": status.value,
                    "output_tokens": run.total_tokens,
                    "baseline_tokens": baseline_tokens,
                    "token_savings_pct": token_savings_pct,
                    "behaviors_cited": list(run.behaviors_cited),
                    "step": "SUMMARY",
                    "context_keys": context_keys,
                    "completed_at": run.completed_at,
                },
            )
            return

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE workflow_runs
                    SET status = %s, total_tokens = %s, completed_at = %s, run_data = %s
                    WHERE run_id = %s
                    """,
                    (
                        status.value,
                        run.total_tokens,
                        run.completed_at,
                        json.dumps(run.to_dict()),
                        run_id,
                    ),
                )

        self._pool.run_transaction(
            operation="update_run_status",
            service_prefix="workflow",
            actor={"id": run.actor.id, "role": run.actor.role, "surface": run.actor.surface},
            metadata={"run_id": run_id, "status": status.value},
            executor=_execute,
            telemetry=None,  # WorkflowService uses global emit_event
        )

        emit_event(
            "execution_update",
            {
                "run_id": run_id,
                "template_id": run.template_id,
                "status": status.value,
                "output_tokens": run.total_tokens,
                "baseline_tokens": baseline_tokens,
                "token_savings_pct": token_savings_pct,
                "behaviors_cited": list(run.behaviors_cited),
                "step": "SUMMARY",
                "context_keys": context_keys,
                "completed_at": run.completed_at,
            },
        )
