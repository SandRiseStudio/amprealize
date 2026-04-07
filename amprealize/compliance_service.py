"""ComplianceService PostgreSQL implementation aligning with COMPLIANCE_SERVICE_CONTRACT.md."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from threading import Lock
from typing import Any, Dict, List, Optional

from .action_contracts import Actor, utc_now_iso
from .storage.postgres_pool import PostgresPool
from .telemetry import TelemetryClient
from .utils.dsn import resolve_postgres_dsn


class ComplianceServiceError(Exception):
    """Base error for ComplianceService operations."""


class ChecklistNotFoundError(ComplianceServiceError):
    """Raised when a checklist is not found in the backing store."""


class StepNotFoundError(ComplianceServiceError):
    """Raised when a step is not found within a checklist."""


class PolicyNotFoundError(ComplianceServiceError):
    """Raised when a compliance policy is not found in the backing store."""


class CompliancePolicy:
    """Represents a compliance policy with scope (global/org/project).

    Policies define rules, required behaviors, and enforcement levels for compliance validation.
    Scope hierarchy:
    - Global: org_id=None, project_id=None
    - Org-scoped: org_id set, project_id=None
    - Project-scoped: org_id set, project_id set
    """

    def __init__(
        self,
        policy_id: str,
        name: str,
        description: str,
        version: str,
        org_id: Optional[str],
        project_id: Optional[str],
        policy_type: str,
        enforcement_level: str,
        rules: List[Dict],
        required_behaviors: List[str],
        compliance_categories: List[str],
        is_active: bool,
        created_by: Actor,
        created_at: str,
        updated_at: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        self.policy_id = policy_id
        self.name = name
        self.description = description
        self.version = version
        self.org_id = org_id
        self.project_id = project_id
        self.policy_type = policy_type
        self.enforcement_level = enforcement_level
        self.rules = rules
        self.required_behaviors = required_behaviors
        self.compliance_categories = compliance_categories
        self.is_active = is_active
        self.created_by = created_by
        self.created_at = created_at
        self.updated_at = updated_at
        self.metadata = metadata or {}

    @property
    def scope(self) -> str:
        """Return the policy scope: 'global', 'org', or 'project'."""
        if self.project_id:
            return "project"
        elif self.org_id:
            return "org"
        return "global"

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "scope": self.scope,
            "org_id": self.org_id,
            "project_id": self.project_id,
            "policy_type": self.policy_type,
            "enforcement_level": self.enforcement_level,
            "rules": deepcopy(self.rules),
            "required_behaviors": list(self.required_behaviors),
            "compliance_categories": list(self.compliance_categories),
            "is_active": self.is_active,
            "created_by": {
                "id": self.created_by.id,
                "role": self.created_by.role,
                "surface": self.created_by.surface,
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": deepcopy(self.metadata),
        }


class AuditTrailEntry:
    """Represents a single entry in a compliance audit trail."""

    def __init__(
        self,
        entry_id: str,
        checklist_id: str,
        step_id: Optional[str],
        run_id: Optional[str],
        action_id: Optional[str],
        event_type: str,
        timestamp: str,
        actor: Actor,
        title: str,
        status: str,
        evidence: Optional[Dict] = None,
        behaviors_cited: Optional[List[str]] = None,
        validation_result: Optional[Dict] = None,
    ) -> None:
        self.entry_id = entry_id
        self.checklist_id = checklist_id
        self.step_id = step_id
        self.run_id = run_id
        self.action_id = action_id
        self.event_type = event_type
        self.timestamp = timestamp
        self.actor = actor
        self.title = title
        self.status = status
        self.evidence = evidence or {}
        self.behaviors_cited = behaviors_cited or []
        self.validation_result = validation_result or {}

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "entry_id": self.entry_id,
            "checklist_id": self.checklist_id,
            "step_id": self.step_id,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "actor": {
                "id": self.actor.id,
                "role": self.actor.role,
                "surface": self.actor.surface,
            },
            "title": self.title,
            "status": self.status,
            "evidence": deepcopy(self.evidence),
            "behaviors_cited": list(self.behaviors_cited),
            "validation_result": deepcopy(self.validation_result),
        }


class AuditTrailReport:
    """Aggregated audit trail report for a run or checklist."""

    def __init__(
        self,
        run_id: Optional[str],
        checklist_ids: List[str],
        entries: List[AuditTrailEntry],
        summary: Dict,
        generated_at: str,
    ) -> None:
        self.run_id = run_id
        self.checklist_ids = checklist_ids
        self.entries = entries
        self.summary = summary
        self.generated_at = generated_at

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "run_id": self.run_id,
            "checklist_ids": list(self.checklist_ids),
            "entries": [e.to_dict() for e in self.entries],
            "summary": deepcopy(self.summary),
            "generated_at": self.generated_at,
        }


class ChecklistStep:
    """Represents a single checklist step with evidence and validation results."""

    def __init__(
        self,
        step_id: str,
        checklist_id: str,
        timestamp: str,
        actor: Actor,
        title: str,
        status: str,
        evidence: Optional[Dict] = None,
        behaviors_cited: Optional[List[str]] = None,
        related_run_id: Optional[str] = None,
        audit_log_event_id: Optional[str] = None,
        validation_result: Optional[Dict] = None,
    ) -> None:
        self.step_id = step_id
        self.checklist_id = checklist_id
        self.timestamp = timestamp
        self.actor = actor
        self.title = title
        self.status = status
        self.evidence = evidence or {}
        self.behaviors_cited = behaviors_cited or []
        self.related_run_id = related_run_id
        self.audit_log_event_id = audit_log_event_id
        self.validation_result = validation_result or {}

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "step_id": self.step_id,
            "checklist_id": self.checklist_id,
            "timestamp": self.timestamp,
            "actor": {
                "id": self.actor.id,
                "role": self.actor.role,
                "surface": self.actor.surface,
            },
            "title": self.title,
            "status": self.status,
            "evidence": deepcopy(self.evidence),
            "behaviors_cited": list(self.behaviors_cited),
            "related_run_id": self.related_run_id,
            "audit_log_event_id": self.audit_log_event_id,
            "validation_result": deepcopy(self.validation_result),
        }


class Checklist:
    """Represents a compliance checklist with ordered steps and coverage scoring."""

    def __init__(
        self,
        checklist_id: str,
        title: str,
        description: str,
        template_id: Optional[str],
        milestone: Optional[str],
        compliance_category: List[str],
        steps: List[ChecklistStep],
        created_at: str,
        completed_at: Optional[str] = None,
        coverage_score: float = 0.0,
    ) -> None:
        self.checklist_id = checklist_id
        self.title = title
        self.description = description
        self.template_id = template_id
        self.milestone = milestone
        self.compliance_category = compliance_category
        self.steps = steps
        self.created_at = created_at
        self.completed_at = completed_at
        self.coverage_score = coverage_score

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "checklist_id": self.checklist_id,
            "title": self.title,
            "description": self.description,
            "template_id": self.template_id,
            "milestone": self.milestone,
            "compliance_category": list(self.compliance_category),
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "coverage_score": self.coverage_score,
        }


class RecordStepRequest:
    """Request to record a new checklist step."""

    def __init__(
        self,
        checklist_id: str,
        title: str,
        status: str,
        evidence: Optional[Dict] = None,
        behaviors_cited: Optional[List[str]] = None,
        related_run_id: Optional[str] = None,
    ) -> None:
        self.checklist_id = checklist_id
        self.title = title
        self.status = status
        self.evidence = evidence or {}
        self.behaviors_cited = behaviors_cited or []
        self.related_run_id = related_run_id


class ValidateChecklistResponse:
    """Response from checklist validation including coverage score and errors."""

    def __init__(
        self,
        checklist_id: str,
        valid: bool,
        coverage_score: float,
        missing_steps: List[str],
        failed_steps: List[str],
        warnings: List[str],
    ) -> None:
        self.checklist_id = checklist_id
        self.valid = valid
        self.coverage_score = coverage_score
        self.missing_steps = missing_steps
        self.failed_steps = failed_steps
        self.warnings = warnings

    def to_dict(self) -> Dict:
        """Serialize to dictionary matching the contract schema."""
        return {
            "checklist_id": self.checklist_id,
            "valid": self.valid,
            "coverage_score": self.coverage_score,
            "missing_steps": list(self.missing_steps),
            "failed_steps": list(self.failed_steps),
            "warnings": list(self.warnings),
        }


class ComplianceService:
    """PostgreSQL-backed ComplianceService for compliance checklist tracking.

    This service implements the behavior described in `COMPLIANCE_SERVICE_CONTRACT.md` using
    PostgreSQL for durable storage. It supports checklist creation, step recording, and validation
    with coverage scoring across Web, CLI, API, and MCP surfaces.
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        self._explicit_dsn = dsn
        self._resolved_dsn: Optional[str] = None
        self._telemetry = telemetry or TelemetryClient.noop()
        self._pool: Optional[PostgresPool] = None
        self._pool_lock = Lock()

    def _resolve_dsn(self) -> str:
        """Resolve the PostgreSQL DSN from args or environment lazily."""
        if self._resolved_dsn:
            return self._resolved_dsn

        env_var = "AMPREALIZE_COMPLIANCE_PG_DSN"
        fallback = os.getenv(env_var)
        candidate = self._explicit_dsn or fallback
        default_dsn = fallback or "postgresql://amprealize_compliance:dev_compliance_pass@localhost:6437/amprealize_compliance"
        if not candidate and not fallback and self._explicit_dsn is None:
            # Allow default DSN even when no env var is provided to support offline bootstrapping
            candidate = default_dsn

        self._resolved_dsn = resolve_postgres_dsn(
            service="COMPLIANCE",
            explicit_dsn=candidate,
            env_var=env_var,
            default_dsn=default_dsn,
        )
        return self._resolved_dsn

    def _get_pool(self) -> PostgresPool:
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is None:
                self._pool = PostgresPool(self._resolve_dsn())
        return self._pool

    # ------------------------------------------------------------------
    # Checklist Management
    # ------------------------------------------------------------------
    def create_checklist(
        self,
        title: str,
        description: str,
        template_id: Optional[str],
        milestone: Optional[str],
        compliance_category: List[str],
        actor: Actor,
    ) -> Checklist:
        """Create a new empty checklist and return the stored entity."""

        checklist_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        with self._get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO checklists (
                        checklist_id, title, description, template_id, milestone,
                        compliance_category, created_at, completed_at, coverage_score
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        checklist_id,
                        title,
                        description,
                        template_id,
                        milestone,
                        json.dumps(compliance_category),
                        timestamp,
                        None,
                        0.0,
                    ),
                )

        self._telemetry.emit_event(
            event_type="compliance_checklist_created",
            payload={
                "checklist_id": checklist_id,
                "title": title,
                "milestone": milestone,
                "compliance_category": list(compliance_category),
            },
            actor=self._actor_payload(actor),
            action_id=checklist_id,
        )

        return Checklist(
            checklist_id=checklist_id,
            title=title,
            description=description,
            template_id=template_id,
            milestone=milestone,
            compliance_category=compliance_category,
            steps=[],
            created_at=timestamp,
            completed_at=None,
            coverage_score=0.0,
        )

    def get_checklist(self, checklist_id: str) -> Checklist:
        """Fetch a single checklist by identifier with all steps."""

        with self._get_pool().connection() as conn:
            cur = conn.cursor()
            # Fetch checklist
            cur.execute(
                """
                SELECT checklist_id, title, description, template_id, milestone,
                       compliance_category, created_at, completed_at, coverage_score
                FROM checklists
                WHERE checklist_id = %s
                """,
                (checklist_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ChecklistNotFoundError(f"Checklist '{checklist_id}' not found")

            # Fetch steps
            cur.execute(
                """
                SELECT step_id, checklist_id, title, status, actor_id, actor_role, actor_surface,
                       evidence, behaviors_cited, related_run_id, audit_log_event_id,
                       validation_result, created_at
                FROM checklist_steps
                WHERE checklist_id = %s
                ORDER BY created_at ASC
                """,
                (checklist_id,),
            )
            step_rows = cur.fetchall()

        steps = [self._row_to_step(step_row) for step_row in step_rows]
        return self._row_to_checklist(row, steps)

    def list_checklists(
        self,
        milestone: Optional[str] = None,
        compliance_category: Optional[List[str]] = None,
        status_filter: Optional[str] = None,
    ) -> List[Checklist]:
        """Return checklists filtered by milestone, category, or status."""

        query = "SELECT checklist_id FROM checklists WHERE 1=1"
        params: List[Any] = []

        if milestone:
            query += " AND milestone = %s"
            params.append(milestone)

        if compliance_category:
            query += " AND compliance_category ?| %s"
            params.append(compliance_category)

        if status_filter == "COMPLETED":
            query += " AND completed_at IS NOT NULL"
        elif status_filter == "ACTIVE":
            query += " AND completed_at IS NULL"

        query += " ORDER BY created_at ASC"

        with self._get_pool().connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            checklist_ids = [row[0] for row in cur.fetchall()]

        # Fetch full checklists (could be optimized with JOIN but keeping it simple)
        return [self.get_checklist(str(cid)) for cid in checklist_ids]

    # ------------------------------------------------------------------
    # Step Recording
    # ------------------------------------------------------------------
    def record_step(self, request: RecordStepRequest, actor: Actor) -> ChecklistStep:
        """Record a new step in an existing checklist and recalculate coverage."""

        step_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        with self._get_pool().connection() as conn:
            cur = conn.cursor()
            # Verify checklist exists
            cur.execute("SELECT checklist_id FROM checklists WHERE checklist_id = %s", (request.checklist_id,))
            if not cur.fetchone():
                raise ChecklistNotFoundError(f"Checklist '{request.checklist_id}' not found")

            # Insert step
            cur.execute(
                """
                INSERT INTO checklist_steps (
                    step_id, checklist_id, title, status, actor_id, actor_role, actor_surface,
                    evidence, behaviors_cited, related_run_id, audit_log_event_id,
                    validation_result, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    step_id,
                    request.checklist_id,
                    request.title,
                    request.status,
                    actor.id,
                    actor.role,
                    actor.surface,
                    json.dumps(request.evidence),
                    json.dumps(request.behaviors_cited),
                    request.related_run_id,
                    None,  # audit_log_event_id populated by audit integration
                    json.dumps({}),
                    timestamp,
                ),
            )

            # Recalculate coverage
            cur.execute(
                """
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status IN ('COMPLETED', 'SKIPPED')) as terminal
                FROM checklist_steps
                WHERE checklist_id = %s
                """,
                (request.checklist_id,),
            )
            total, terminal = cur.fetchone()
            coverage_score = float(terminal) / float(total) if total > 0 else 0.0

            # Check if all steps are terminal
            cur.execute(
                """
                SELECT COUNT(*) FROM checklist_steps
                WHERE checklist_id = %s AND status NOT IN ('COMPLETED', 'SKIPPED', 'FAILED')
                """,
                (request.checklist_id,),
            )
            non_terminal_count = cur.fetchone()[0]
            completed_at = None if non_terminal_count > 0 else timestamp

            # Update checklist
            cur.execute(
                """
                UPDATE checklists
                SET coverage_score = %s, completed_at = %s
                WHERE checklist_id = %s
                """,
                (coverage_score, completed_at, request.checklist_id),
            )

        self._telemetry.emit_event(
            event_type="compliance_step_recorded",
            payload={
                "checklist_id": request.checklist_id,
                "step_id": step_id,
                "title": request.title,
                "status": request.status,
                "coverage_score": coverage_score,
            },
            actor=self._actor_payload(actor),
            action_id=step_id,
            run_id=request.related_run_id,
        )

        return ChecklistStep(
            step_id=step_id,
            checklist_id=request.checklist_id,
            timestamp=timestamp,
            actor=actor,
            title=request.title,
            status=request.status,
            evidence=request.evidence,
            behaviors_cited=request.behaviors_cited,
            related_run_id=request.related_run_id,
            audit_log_event_id=None,
            validation_result={},
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_checklist(self, checklist_id: str, actor: Actor) -> ValidateChecklistResponse:
        """Validate a checklist and return coverage score with errors/warnings."""

        checklist = self.get_checklist(checklist_id)
        missing_steps: List[str] = []
        failed_steps: List[str] = []
        warnings: List[str] = []

        self._telemetry.emit_event(
            event_type="compliance_validation_triggered",
            payload={
                "checklist_id": checklist_id,
                "milestone": checklist.milestone,
            },
            actor=self._actor_payload(actor),
            action_id=checklist_id,
        )

        for step in checklist.steps:
            if step.status == "PENDING":
                missing_steps.append(step.title)
            elif step.status == "FAILED":
                failed_steps.append(step.title)
            elif step.status == "SKIPPED":
                warnings.append(f"Step '{step.title}' was skipped without completion.")

        valid = len(missing_steps) == 0 and len(failed_steps) == 0

        self._telemetry.emit_event(
            event_type="compliance_validation_completed",
            payload={
                "checklist_id": checklist_id,
                "valid": valid,
                "coverage_score": checklist.coverage_score,
                "failed_count": len(failed_steps),
            },
            actor=self._actor_payload(actor),
            action_id=checklist_id,
        )

        return ValidateChecklistResponse(
            checklist_id=checklist_id,
            valid=valid,
            coverage_score=checklist.coverage_score,
            missing_steps=missing_steps,
            failed_steps=failed_steps,
            warnings=warnings,
        )

    def validate_by_action_id(
        self,
        action_id: str,
        actor: Actor,
        action_service: Optional[Any] = None,
    ) -> ValidateChecklistResponse:
        """Validate compliance for checklists associated with an action.

        Looks up the action via ActionService, finds related checklists through
        the action's related_run_id or direct checklist associations, and validates.

        Args:
            action_id: The action identifier to validate compliance for
            actor: Actor performing the validation
            action_service: Optional ActionService instance (lazy-loaded if not provided)

        Returns:
            ValidateChecklistResponse with aggregated results from related checklists
        """
        # Lazy-load ActionService if not provided
        if action_service is None:
            from .action_service_postgres import PostgresActionService
            action_service = PostgresActionService()

        # Get the action to find related run_id
        try:
            action = action_service.get_action(action_id)
        except Exception as exc:
            raise ComplianceServiceError(f"Action '{action_id}' not found: {exc}") from exc

        related_run_id = action.related_run_id

        # Find checklists associated with this run or action
        # First, look for steps that reference this run
        with self._get_pool().connection() as conn:
            cur = conn.cursor()

            # Find checklist IDs from steps that reference this run
            cur.execute(
                """
                SELECT DISTINCT checklist_id FROM checklist_steps
                WHERE related_run_id = %s
                """,
                (related_run_id,) if related_run_id else (action_id,),
            )
            checklist_ids = [str(row[0]) for row in cur.fetchall()]

        if not checklist_ids:
            # No associated checklists found
            return ValidateChecklistResponse(
                checklist_id=action_id,
                valid=True,
                coverage_score=1.0,
                missing_steps=[],
                failed_steps=[],
                warnings=[f"No compliance checklists found for action '{action_id}'"],
            )

        # Aggregate validation across all related checklists
        all_missing: List[str] = []
        all_failed: List[str] = []
        all_warnings: List[str] = []
        total_coverage = 0.0

        for cid in checklist_ids:
            result = self.validate_checklist(cid, actor)
            all_missing.extend([f"[{cid[:8]}] {s}" for s in result.missing_steps])
            all_failed.extend([f"[{cid[:8]}] {s}" for s in result.failed_steps])
            all_warnings.extend([f"[{cid[:8]}] {w}" for w in result.warnings])
            total_coverage += result.coverage_score

        avg_coverage = total_coverage / len(checklist_ids) if checklist_ids else 0.0
        valid = len(all_missing) == 0 and len(all_failed) == 0

        self._telemetry.emit_event(
            event_type="compliance_action_validation_completed",
            payload={
                "action_id": action_id,
                "checklist_count": len(checklist_ids),
                "valid": valid,
                "coverage_score": avg_coverage,
            },
            actor=self._actor_payload(actor),
            action_id=action_id,
        )

        return ValidateChecklistResponse(
            checklist_id=action_id,  # Use action_id as identifier for aggregated result
            valid=valid,
            coverage_score=avg_coverage,
            missing_steps=all_missing,
            failed_steps=all_failed,
            warnings=all_warnings,
        )

    # ------------------------------------------------------------------
    # Policy Management
    # ------------------------------------------------------------------
    def create_policy(
        self,
        name: str,
        description: str,
        policy_type: str,
        enforcement_level: str,
        actor: Actor,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        version: str = "1.0.0",
        rules: Optional[List[Dict]] = None,
        required_behaviors: Optional[List[str]] = None,
        compliance_categories: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> CompliancePolicy:
        """Create a new compliance policy.

        Args:
            name: Policy name (unique within scope)
            description: Policy description
            policy_type: One of AUDIT, SECURITY, COMPLIANCE, GOVERNANCE, CUSTOM
            enforcement_level: One of ADVISORY, WARNING, BLOCKING
            actor: Actor creating the policy
            org_id: Organization ID for org/project scope (None for global)
            project_id: Project ID for project scope (requires org_id)
            version: Semantic version string
            rules: List of rule definitions
            required_behaviors: List of behavior IDs required for compliance
            compliance_categories: List of compliance categories (SOC2, GDPR, etc.)
            metadata: Additional metadata

        Returns:
            The created CompliancePolicy
        """
        policy_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        # Validate scope: project_id requires org_id
        if project_id and not org_id:
            raise ComplianceServiceError("project_id requires org_id to be set")

        with self._get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO compliance_policies (
                        policy_id, name, description, version, org_id, project_id,
                        policy_type, enforcement_level, rules, required_behaviors,
                        compliance_categories, is_active, created_by_id, created_by_role,
                        created_by_surface, created_at, updated_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        policy_id,
                        name,
                        description,
                        version,
                        org_id,
                        project_id,
                        policy_type,
                        enforcement_level,
                        json.dumps(rules or []),
                        json.dumps(required_behaviors or []),
                        json.dumps(compliance_categories or []),
                        True,  # is_active
                        actor.id,
                        actor.role,
                        actor.surface,
                        timestamp,
                        timestamp,
                        json.dumps(metadata or {}),
                    ),
                )

        self._telemetry.emit_event(
            event_type="compliance_policy_created",
            payload={
                "policy_id": policy_id,
                "name": name,
                "policy_type": policy_type,
                "enforcement_level": enforcement_level,
                "scope": "project" if project_id else ("org" if org_id else "global"),
            },
            actor=self._actor_payload(actor),
            action_id=policy_id,
        )

        return CompliancePolicy(
            policy_id=policy_id,
            name=name,
            description=description,
            version=version,
            org_id=org_id,
            project_id=project_id,
            policy_type=policy_type,
            enforcement_level=enforcement_level,
            rules=rules or [],
            required_behaviors=required_behaviors or [],
            compliance_categories=compliance_categories or [],
            is_active=True,
            created_by=actor,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=metadata,
        )

    def get_policy(self, policy_id: str) -> CompliancePolicy:
        """Fetch a single policy by identifier."""
        with self._get_pool().connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT policy_id, name, description, version, org_id, project_id,
                       policy_type, enforcement_level, rules, required_behaviors,
                       compliance_categories, is_active, created_by_id, created_by_role,
                       created_by_surface, created_at, updated_at, metadata
                FROM compliance_policies
                WHERE policy_id = %s
                """,
                (policy_id,),
            )
            row = cur.fetchone()
            if not row:
                raise PolicyNotFoundError(f"Policy '{policy_id}' not found")

        return self._row_to_policy(row)

    def list_policies(
        self,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        policy_type: Optional[str] = None,
        enforcement_level: Optional[str] = None,
        is_active: Optional[bool] = None,
        include_global: bool = True,
    ) -> List[CompliancePolicy]:
        """List policies with optional scope and type filters.

        Args:
            org_id: Filter by organization (also includes global if include_global=True)
            project_id: Filter by project (also includes org/global if include_global=True)
            policy_type: Filter by policy type
            enforcement_level: Filter by enforcement level
            is_active: Filter by active status
            include_global: Whether to include global/parent-scope policies (default True)

        Returns:
            List of matching CompliancePolicy objects
        """
        query = "SELECT policy_id FROM compliance_policies WHERE 1=1"
        params: List[Any] = []

        # Build scope filter with hierarchy
        if project_id and include_global:
            # Include project-scoped, org-scoped, and global policies
            query += " AND (project_id = %s OR (project_id IS NULL AND org_id = %s) OR (project_id IS NULL AND org_id IS NULL))"
            params.extend([project_id, org_id])
        elif project_id:
            query += " AND project_id = %s"
            params.append(project_id)
        elif org_id and include_global:
            # Include org-scoped and global policies
            query += " AND (org_id = %s OR org_id IS NULL) AND project_id IS NULL"
            params.append(org_id)
        elif org_id:
            query += " AND org_id = %s AND project_id IS NULL"
            params.append(org_id)
        elif include_global:
            # Just global policies
            query += " AND org_id IS NULL AND project_id IS NULL"

        if policy_type:
            query += " AND policy_type = %s"
            params.append(policy_type)

        if enforcement_level:
            query += " AND enforcement_level = %s"
            params.append(enforcement_level)

        if is_active is not None:
            query += " AND is_active = %s"
            params.append(is_active)

        query += " ORDER BY created_at DESC"

        with self._get_pool().connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            policy_ids = [str(row[0]) for row in cur.fetchall()]

        return [self.get_policy(pid) for pid in policy_ids]

    # ------------------------------------------------------------------
    # Audit Trail
    # ------------------------------------------------------------------
    def get_audit_trail(
        self,
        run_id: Optional[str] = None,
        checklist_id: Optional[str] = None,
        action_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> AuditTrailReport:
        """Generate an audit trail report aggregating compliance steps and evidence.

        Args:
            run_id: Filter by run ID (steps with related_run_id matching)
            checklist_id: Filter by specific checklist ID
            action_id: Filter by action ID (looks up action's related_run_id)
            start_date: Filter steps created after this ISO timestamp
            end_date: Filter steps created before this ISO timestamp

        Returns:
            AuditTrailReport with entries and summary statistics
        """
        query = """
            SELECT s.step_id, s.checklist_id, s.title, s.status,
                   s.actor_id, s.actor_role, s.actor_surface,
                   s.evidence, s.behaviors_cited, s.related_run_id,
                   s.audit_log_event_id, s.validation_result, s.created_at,
                   c.title as checklist_title
            FROM checklist_steps s
            JOIN checklists c ON s.checklist_id = c.checklist_id
            WHERE 1=1
        """
        params: List[Any] = []

        # If action_id provided, resolve to run_id
        if action_id and not run_id:
            try:
                from .action_service_postgres import PostgresActionService
                action_service = PostgresActionService()
                action = action_service.get_action(action_id)
                run_id = action.related_run_id
            except Exception:
                pass  # Continue without run_id filter

        if run_id:
            query += " AND s.related_run_id = %s"
            params.append(run_id)

        if checklist_id:
            query += " AND s.checklist_id = %s"
            params.append(checklist_id)

        if start_date:
            query += " AND s.created_at >= %s"
            params.append(start_date)

        if end_date:
            query += " AND s.created_at <= %s"
            params.append(end_date)

        query += " ORDER BY s.created_at ASC"

        with self._get_pool().connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        entries: List[AuditTrailEntry] = []
        checklist_ids_set: set = set()
        status_counts: Dict[str, int] = {}
        behaviors_used: set = set()

        for row in rows:
            step_id = str(row[0])
            cid = str(row[1])
            checklist_ids_set.add(cid)
            status = row[3]
            status_counts[status] = status_counts.get(status, 0) + 1

            behaviors = json.loads(row[8]) if isinstance(row[8], str) else (row[8] or [])
            for b in behaviors:
                behaviors_used.add(b)

            entry = AuditTrailEntry(
                entry_id=step_id,
                checklist_id=cid,
                step_id=step_id,
                run_id=row[9],
                action_id=action_id,
                event_type="compliance_step",
                timestamp=str(row[12]),
                actor=Actor(id=row[4], role=row[5], surface=row[6]),
                title=row[2],
                status=status,
                evidence=json.loads(row[7]) if isinstance(row[7], str) else (row[7] or {}),
                behaviors_cited=behaviors,
                validation_result=json.loads(row[11]) if isinstance(row[11], str) else (row[11] or {}),
            )
            entries.append(entry)

        summary = {
            "total_entries": len(entries),
            "checklist_count": len(checklist_ids_set),
            "status_breakdown": status_counts,
            "behaviors_cited": list(behaviors_used),
            "coverage_complete": status_counts.get("COMPLETED", 0),
            "coverage_failed": status_counts.get("FAILED", 0),
            "coverage_pending": status_counts.get("PENDING", 0),
        }

        return AuditTrailReport(
            run_id=run_id,
            checklist_ids=list(checklist_ids_set),
            entries=entries,
            summary=summary,
            generated_at=utc_now_iso(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _row_to_checklist(self, row: Any, steps: List[ChecklistStep]) -> Checklist:
        """Convert database row to Checklist with UUID serialization."""
        return Checklist(
            checklist_id=str(row[0]),  # UUID → str
            title=row[1],
            description=row[2],
            template_id=row[3],
            milestone=row[4],
            compliance_category=json.loads(row[5]) if isinstance(row[5], str) else row[5],
            steps=steps,
            created_at=str(row[6]),  # datetime → str
            completed_at=str(row[7]) if row[7] else None,  # datetime → str
            coverage_score=float(row[8]),
        )

    def _row_to_step(self, row: Any) -> ChecklistStep:
        """Convert database row to ChecklistStep with UUID serialization."""
        return ChecklistStep(
            step_id=str(row[0]),  # UUID → str
            checklist_id=str(row[1]),  # UUID → str
            title=row[2],
            status=row[3],
            actor=Actor(id=row[4], role=row[5], surface=row[6]),
            evidence=json.loads(row[7]) if isinstance(row[7], str) else row[7],
            behaviors_cited=json.loads(row[8]) if isinstance(row[8], str) else row[8],
            related_run_id=row[9],
            audit_log_event_id=row[10],
            validation_result=json.loads(row[11]) if isinstance(row[11], str) else row[11],
            timestamp=str(row[12]),  # datetime → str
        )

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Normalize actor metadata for telemetry envelopes."""
        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface.lower(),
        }

    def _row_to_policy(self, row: Any) -> CompliancePolicy:
        """Convert database row to CompliancePolicy with proper deserialization."""
        return CompliancePolicy(
            policy_id=str(row[0]),
            name=row[1],
            description=row[2],
            version=row[3],
            org_id=row[4],
            project_id=row[5],
            policy_type=row[6],
            enforcement_level=row[7],
            rules=json.loads(row[8]) if isinstance(row[8], str) else (row[8] or []),
            required_behaviors=json.loads(row[9]) if isinstance(row[9], str) else (row[9] or []),
            compliance_categories=json.loads(row[10]) if isinstance(row[10], str) else (row[10] or []),
            is_active=row[11],
            created_by=Actor(id=row[12], role=row[13], surface=row[14]),
            created_at=str(row[15]),
            updated_at=str(row[16]),
            metadata=json.loads(row[17]) if isinstance(row[17], str) else (row[17] or {}),
        )
