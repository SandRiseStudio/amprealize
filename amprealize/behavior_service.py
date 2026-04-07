"""BehaviorService runtime implementation with PostgreSQL persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg2.errors

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from amprealize.storage.postgres_pool import PostgresPool
from amprealize.storage.redis_cache import get_cache
from .utils.dsn import resolve_postgres_dsn

from .action_contracts import Actor, utc_now_iso
from .telemetry import TelemetryClient

_BEHAVIOR_PG_DSN_ENV = "AMPREALIZE_BEHAVIOR_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize_behavior:dev_behavior_pass@localhost:6433/behaviors"
DEFAULT_BEHAVIOR_NAMESPACE = "core"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Behavior:
    behavior_id: str
    name: str
    description: str
    tags: List[str]
    created_at: str
    updated_at: str
    latest_version: str
    status: str
    namespace: str = DEFAULT_BEHAVIOR_NAMESPACE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior_id": self.behavior_id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "latest_version": self.latest_version,
            "status": self.status,
            "namespace": self.namespace,
        }


@dataclass(frozen=True)
class BehaviorVersion:
    behavior_id: str
    version: str
    instruction: str
    role_focus: str
    status: str
    trigger_keywords: List[str]
    examples: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    effective_from: str
    effective_to: Optional[str]
    created_by: str
    approval_action_id: Optional[str]
    embedding_checksum: Optional[str]
    embedding: Optional[List[float]] = None
    confidence_score: Optional[float] = None  # 0.0-1.0, >=0.8 eligible for auto-approval
    historical_validations: Optional[List[str]] = None  # List of run_ids that validated this behavior

    def to_dict(self, include_metadata: bool = True) -> Dict[str, Any]:
        payload = {
            "behavior_id": self.behavior_id,
            "version": self.version,
            "instruction": self.instruction,
            "role_focus": self.role_focus,
            "status": self.status,
            "trigger_keywords": list(self.trigger_keywords),
            "examples": [dict(example) for example in self.examples],
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "created_by": self.created_by,
            "approval_action_id": self.approval_action_id,
            "embedding_checksum": self.embedding_checksum,
            "confidence_score": self.confidence_score,
            "historical_validations": list(self.historical_validations) if self.historical_validations else [],
        }
        if include_metadata:
            payload["metadata"] = dict(self.metadata)
            if self.embedding is not None:
                payload["embedding"] = list(self.embedding)
        return payload

    @property
    def eligible_for_auto_approval(self) -> bool:
        """Check if behavior meets auto-approval threshold per AGENTS.md.

        Auto-approval criteria (confidence >= 0.8):
        - Validated against 3+ historical cases
        - Clear, unambiguous triggers
        - No overlap with existing behaviors
        - Follows behavior_<verb>_<noun> naming
        """
        return (self.confidence_score or 0.0) >= 0.8


@dataclass(frozen=True)
class BehaviorSearchResult:
    behavior: Behavior
    active_version: BehaviorVersion
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "behavior": self.behavior.to_dict(),
            "active_version": self.active_version.to_dict(),
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@dataclass
class CreateBehaviorDraftRequest:
    name: str
    description: str
    instruction: str
    role_focus: str
    trigger_keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    base_version: Optional[str] = None
    confidence_score: Optional[float] = None  # 0.0-1.0, >=0.8 eligible for auto-approval
    historical_validations: Optional[List[str]] = None  # Run IDs that validated this pattern


@dataclass
class UpdateBehaviorDraftRequest:
    behavior_id: str
    version: str
    instruction: Optional[str] = None
    description: Optional[str] = None
    trigger_keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    examples: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None
    confidence_score: Optional[float] = None  # 0.0-1.0, >=0.8 eligible for auto-approval
    historical_validations: Optional[List[str]] = None  # Run IDs to add to validation history


@dataclass
class ApproveBehaviorRequest:
    behavior_id: str
    version: str
    effective_from: str
    approval_action_id: Optional[str] = None


@dataclass
class DeprecateBehaviorRequest:
    behavior_id: str
    version: str
    effective_to: str
    successor_behavior_id: Optional[str] = None


@dataclass
class SearchBehaviorsRequest:
    query: Optional[str] = None
    tags: Optional[List[str]] = None
    role_focus: Optional[str] = None
    status: Optional[str] = None
    limit: int = 25
    namespace: Optional[str] = DEFAULT_BEHAVIOR_NAMESPACE


@dataclass
class ProposeBehaviorRequest:
    """Request to propose a new behavior from observed patterns.

    Follows the Behavior Lifecycle from AGENTS.md:
    Phase 1 (DISCOVER) -> Phase 2 (PROPOSE) -> Phase 3 (APPROVE) -> Phase 4 (INTEGRATE)

    This request is used by Students to escalate patterns to Strategists,
    and by Strategists to emit new behaviors from reflection traces.
    """
    name: str  # Must follow behavior_<verb>_<noun> pattern
    description: str
    instruction: str
    role_focus: str  # Student, Teacher, or Strategist
    trigger_keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Proposal-specific fields
    confidence_score: float = 0.0  # 0.0-1.0, calculated from historical validation
    historical_validations: List[str] = field(default_factory=list)  # Run IDs that validated pattern
    pattern_id: Optional[str] = None  # Link to TraceAnalysisService pattern
    proposed_by_role: str = "Strategist"  # Role that proposed (Student escalates, Strategist emits)
    rationale: Optional[str] = None  # Why this behavior should exist


@dataclass
class RoleContext:
    """Context for role-based execution tracking.

    Used to capture which role (Student/Teacher/Strategist) is performing
    an operation for telemetry and audit purposes. Role declarations are
    emphasized but do not fail if missing.
    """
    role: str  # Student, Teacher, or Strategist
    rationale: Optional[str] = None  # Why this role was chosen
    behaviors_cited: List[str] = field(default_factory=list)  # Behaviors being applied
    escalated_from: Optional[str] = None  # If escalated, the previous role
    escalation_reason: Optional[str] = None  # Why escalation occurred

    def to_telemetry_payload(self) -> Dict[str, Any]:
        """Convert to telemetry payload for tracking."""
        return {
            "role": self.role,
            "rationale": self.rationale,
            "behaviors_cited": self.behaviors_cited,
            "escalated_from": self.escalated_from,
            "escalation_reason": self.escalation_reason,
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BehaviorServiceError(Exception):
    """Base error for behavior operations."""


class BehaviorNotFoundError(BehaviorServiceError):
    """Raised when a behavior is missing."""


class BehaviorVersionError(BehaviorServiceError):
    """Raised when version transitions are invalid."""


class PersistenceError(BehaviorServiceError):
    """Raised when the underlying store fails."""


# ---------------------------------------------------------------------------
# BehaviorService implementation
# ---------------------------------------------------------------------------


class BehaviorService:
    """PostgreSQL-backed behavior service runtime."""

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
        behavior_retriever: Optional[Any] = None,
        quality_gate: Optional[Any] = None,
    ) -> None:
        self._dsn = self._resolve_dsn(dsn)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._behavior_retriever = behavior_retriever
        self._quality_gate = quality_gate
        self._pool = PostgresPool(self._dsn)
        self._embedding_model = None

    def _get_embedding_model(self):
        """Lazy load the embedding model."""
        if self._embedding_model is None and SentenceTransformer is not None:
            model_name = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
            self._embedding_model = SentenceTransformer(model_name)
        return self._embedding_model

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using sentence-transformers."""
        model = self._get_embedding_model()
        if model is None:
            return None
        # Force numpy array return
        embedding = model.encode(text, convert_to_numpy=True)
        # Type checker might still be confused, but runtime is safe
        if hasattr(embedding, "tolist"):
            return embedding.tolist()  # type: ignore
        return list(embedding)  # type: ignore

    @staticmethod
    def _normalize_version_input(version: Any) -> int:
        """Convert public version strings like '1' or '1.0.0' into DB integer versions."""
        if version is None:
            raise BehaviorVersionError("Version is required")
        if isinstance(version, int):
            return version

        version_text = str(version).strip()
        if not version_text:
            raise BehaviorVersionError("Version is required")

        try:
            return int(version_text)
        except ValueError:
            pass

        match = re.fullmatch(r"(\d+)(?:\.\d+){0,2}", version_text)
        if match:
            return int(match.group(1))

        raise BehaviorVersionError(f"Invalid version '{version}'")

    @classmethod
    def _format_public_version(cls, version: Any) -> str:
        """Format DB integer versions as semver-style public values."""
        return f"{cls._normalize_version_input(version)}.0.0"

    @staticmethod
    def _parse_embedding(raw_embedding: Any) -> Optional[List[float]]:
        """Parse embedding from database format to List[float].

        PostgreSQL BYTEA columns return memoryview objects via psycopg2.
        The embedding is stored as JSON string, so we need to decode and parse it.
        """
        if raw_embedding is None:
            return None
        if isinstance(raw_embedding, memoryview):
            return json.loads(raw_embedding.tobytes().decode('utf-8'))
        elif isinstance(raw_embedding, bytes):
            return json.loads(raw_embedding.decode('utf-8'))
        elif isinstance(raw_embedding, str):
            return json.loads(raw_embedding)
        elif isinstance(raw_embedding, list):
            return raw_embedding
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_behavior_draft(self, request: CreateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Create a new behavior and initial draft version.

        Uses actual DB schema: behavior.behaviors (id, keywords, is_active, is_deprecated, version)
        and behavior.behavior_versions (id, behavior_id, version, name, description, triggers, steps, etc.)
        """

        behavior_id = str(uuid.uuid4())
        version = 1  # Integer version in DB schema
        timestamp = utc_now_iso()

        # Generate embedding if not provided
        if request.embedding is None:
            embedding_text = f"{request.name} {request.description} {request.instruction}"
            request.embedding = self._generate_embedding(embedding_text)

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Insert behavior into actual schema
                # DB columns: id, org_id, name, namespace, description, category, triggers, steps, role,
                #             confidence_threshold, keywords, version, is_active, is_deprecated, created_at, updated_at
                cur.execute(
                    """
                    INSERT INTO behavior.behaviors (
                        id, name, namespace, description, category, triggers, steps, role,
                        confidence_threshold, keywords, version, is_active, is_deprecated, status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        behavior_id,
                        request.name,
                        DEFAULT_BEHAVIOR_NAMESPACE,
                        request.description,
                        request.role_focus or "general",  # category
                        json.dumps(request.trigger_keywords),  # triggers as JSONB
                        json.dumps(request.examples),  # steps as JSONB
                        request.role_focus or "Student",  # role
                        0.8,  # confidence_threshold
                        request.tags,  # keywords as varchar[]
                        version,
                        False,  # is_active (draft)
                        False,  # is_deprecated
                        "DRAFT",  # status
                        timestamp,
                        timestamp,
                    ),
                )
                # Insert behavior version
                # DB columns: id, behavior_id, version, name, description, triggers, steps, change_reason, changed_by, created_at
                cur.execute(
                    """
                    INSERT INTO behavior.behavior_versions (
                        id, behavior_id, version, name, description, triggers, steps, change_reason, changed_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()),  # version record id
                        behavior_id,
                        version,
                        request.name,
                        request.instruction,  # description in versions = instruction
                        json.dumps(request.trigger_keywords),
                        json.dumps(request.examples),
                        "Initial draft",
                        actor.id,
                        timestamp,
                    ),
                )

        self._pool.run_transaction(
            "behavior.create_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": behavior_id,
                "version": self._format_public_version(version),
                "role_focus": request.role_focus,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        behavior = self._fetch_behavior(behavior_id)
        version_obj = self._fetch_behavior_version(behavior_id, self._format_public_version(version))
        self._telemetry.emit_event(
            event_type="behaviors.draft_created",
            payload={
                "behavior_id": behavior_id,
                "version": self._format_public_version(version),
                "tags": list(request.tags),
                "role_focus": request.role_focus,
            },
            actor=self._actor_payload(actor),
        )

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return version_obj

    def propose_behavior(
        self,
        request: ProposeBehaviorRequest,
        actor: Actor,
        role_context: Optional[RoleContext] = None,
    ) -> Dict[str, Any]:
        """Propose a new behavior from observed patterns.

        Follows the Behavior Lifecycle from AGENTS.md:
        Phase 1 (DISCOVER): Student escalates pattern to Strategist
        Phase 2 (PROPOSE): Strategist drafts behavior via this method
        Phase 3 (APPROVE): Teacher validates, or auto-approve if confidence >= 0.8
        Phase 4 (INTEGRATE): Add to handbook and retrieval index

        Args:
            request: ProposeBehaviorRequest with behavior details and confidence scoring
            actor: The actor proposing the behavior
            role_context: Optional role context for telemetry (emphasized but not required)

        Returns:
            Dict with proposal result including auto_approved flag and behavior_id
        """
        # Validate behavior name follows pattern: behavior_<verb>_<noun>
        if not request.name.startswith("behavior_"):
            raise BehaviorValidationError(
                f"Behavior name must follow 'behavior_<verb>_<noun>' pattern: {request.name}"
            )

        # Emit role context telemetry (advisory, not mandatory)
        if role_context:
            self._telemetry.emit_event(
                event_type="behaviors.proposal_role_context",
                payload=role_context.to_telemetry_payload(),
                actor=self._actor_payload(actor),
            )
        else:
            # Log that role context was not provided (advisory warning)
            self._telemetry.emit_event(
                event_type="behaviors.proposal_role_context_missing",
                payload={"behavior_name": request.name, "advisory": True},
                actor=self._actor_payload(actor),
            )

        # Create the behavior draft with confidence scoring
        create_request = CreateBehaviorDraftRequest(
            name=request.name,
            description=request.description,
            instruction=request.instruction,
            role_focus=request.role_focus,
            trigger_keywords=request.trigger_keywords,
            tags=request.tags,
            examples=request.examples,
            metadata={
                **request.metadata,
                "proposed_by_role": request.proposed_by_role,
                "pattern_id": request.pattern_id,
                "rationale": request.rationale,
            },
            confidence_score=request.confidence_score,
            historical_validations=request.historical_validations,
        )

        version_obj = self.create_behavior_draft(create_request, actor)

        # Check for auto-approval eligibility
        auto_approved = False
        if request.confidence_score >= 0.8 and len(request.historical_validations) >= 3:
            # Auto-approve per AGENTS.md criteria
            approval_request = ApproveBehaviorRequest(
                behavior_id=version_obj.behavior_id,
                version=version_obj.version,
                effective_from=utc_now_iso(),
                approval_action_id=f"auto_approval_{version_obj.behavior_id}",
            )
            self.approve_behavior(approval_request, actor)
            auto_approved = True

            self._telemetry.emit_event(
                event_type="behaviors.auto_approved",
                payload={
                    "behavior_id": version_obj.behavior_id,
                    "version": version_obj.version,
                    "confidence_score": request.confidence_score,
                    "historical_validations_count": len(request.historical_validations),
                    "proposed_by_role": request.proposed_by_role,
                },
                actor=self._actor_payload(actor),
            )
        else:
            # Emit proposal event for Teacher review
            self._telemetry.emit_event(
                event_type="behaviors.proposed",
                payload={
                    "behavior_id": version_obj.behavior_id,
                    "version": version_obj.version,
                    "confidence_score": request.confidence_score,
                    "historical_validations_count": len(request.historical_validations),
                    "needs_teacher_review": True,
                    "proposed_by_role": request.proposed_by_role,
                    "rationale": request.rationale,
                },
                actor=self._actor_payload(actor),
            )

        return {
            "behavior_id": version_obj.behavior_id,
            "version": version_obj.version,
            "status": "APPROVED" if auto_approved else "DRAFT",
            "auto_approved": auto_approved,
            "confidence_score": request.confidence_score,
            "needs_teacher_review": not auto_approved,
            "message": (
                f"Behavior auto-approved (confidence={request.confidence_score}, validations={len(request.historical_validations)})"
                if auto_approved
                else f"Behavior proposed for Teacher review (confidence={request.confidence_score})"
            ),
        }

    def update_behavior_draft(self, request: UpdateBehaviorDraftRequest, actor: Actor) -> BehaviorVersion:
        """Update an existing draft or in-review behavior version.

        Uses actual DB schema: behavior.behaviors and behavior.behavior_versions
        """

        normalized_version = self._normalize_version_input(request.version)
        public_version = self._format_public_version(normalized_version)
        version = self._fetch_behavior_version(request.behavior_id, public_version)
        if version.status not in {"DRAFT", "IN_REVIEW"}:
            raise BehaviorVersionError(
                f"Cannot update behavior {request.behavior_id} version {public_version}: status={version.status}"
            )

        def _execute(conn: Any) -> List[str]:
            with conn.cursor() as cur:
                # Update behavior version fields
                # DB columns: name, description (=instruction), triggers (=trigger_keywords), steps (=examples)
                updates = []
                values = []

                if request.instruction is not None:
                    updates.append("description = %s")  # instruction stored as description in version table
                    values.append(request.instruction)
                if request.trigger_keywords is not None:
                    updates.append("triggers = %s")
                    values.append(json.dumps(request.trigger_keywords))
                if request.examples is not None:
                    updates.append("steps = %s")
                    values.append(json.dumps(request.examples))

                if updates:
                    values.extend([request.behavior_id, normalized_version])
                    cur.execute(
                        f"UPDATE behavior.behavior_versions SET {', '.join(updates)} WHERE behavior_id = %s AND version = %s::int",
                        values,
                    )

                # Update behavior table if needed
                # DB columns: name, description, keywords (=tags), triggers, steps, updated_at
                behavior_updates = []
                behavior_values = []
                if request.description is not None:
                    behavior_updates.append("description = %s")
                    behavior_values.append(request.description)
                if request.tags is not None:
                    behavior_updates.append("keywords = %s")
                    behavior_values.append(request.tags)  # varchar[] directly
                if request.trigger_keywords is not None:
                    behavior_updates.append("triggers = %s")
                    behavior_values.append(json.dumps(request.trigger_keywords))
                if request.examples is not None:
                    behavior_updates.append("steps = %s")
                    behavior_values.append(json.dumps(request.examples))
                if behavior_updates:
                    behavior_updates.append("updated_at = %s")
                    behavior_values.append(utc_now_iso())
                    behavior_values.append(request.behavior_id)
                    cur.execute(
                        f"UPDATE behavior.behaviors SET {', '.join(behavior_updates)} WHERE id = %s",
                        behavior_values,
                    )
                return [k.split()[0] for k in updates]

        updated_fields = self._pool.run_transaction(
            "behavior.update_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": request.behavior_id,
                "version": public_version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated_version = self._fetch_behavior_version(request.behavior_id, public_version)
        self._telemetry.emit_event(
            event_type="behaviors.draft_updated",
            payload={
                "behavior_id": request.behavior_id,
                "version": public_version,
                "updated_fields": updated_fields,
            },
            actor=self._actor_payload(actor),
        )

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return updated_version

    def submit_for_review(self, behavior_id: str, version: str, actor: Actor) -> BehaviorVersion:
        """Move a draft version into review.

        Note: The actual DB schema doesn't have a status column in behavior_versions.
        We track review state via is_active flag on the behaviors table.
        For now, we just update timestamps and log the event.
        """

        normalized_version = self._normalize_version_input(version)
        public_version = self._format_public_version(normalized_version)
        version_obj = self._fetch_behavior_version(behavior_id, public_version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError(
                f"Only drafts can be submitted for review (status={version_obj.status})."
            )

        timestamp = utc_now_iso()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Update behavior_versions with change_reason to track review submission
                cur.execute(
                    """
                    UPDATE behavior.behavior_versions
                       SET change_reason = %s
                     WHERE behavior_id = %s AND version = %s::int
                    """,
                                        (f"Submitted for review at {timestamp}", behavior_id, normalized_version),
                )
                # Update behaviors timestamp and status
                cur.execute(
                    "UPDATE behavior.behaviors SET status = 'IN_REVIEW', updated_at = %s WHERE id = %s",
                    (timestamp, behavior_id),
                )

        self._pool.run_transaction(
            operation="submit_for_review",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={"behavior_id": behavior_id, "version": public_version},
            executor=_execute,
            telemetry=self._telemetry,
        )

        updated = self._fetch_behavior_version(behavior_id, public_version)
        self._telemetry.emit_event(
            event_type="behaviors.submitted_for_review",
            payload={"behavior_id": behavior_id, "version": public_version},
            actor=self._actor_payload(actor),
        )
        return updated

    def approve_behavior(self, request: ApproveBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Approve a behavior version and mark it active.

        Uses actual DB schema: is_active/is_deprecated flags instead of status column.
        When a quality_gate is configured, checks adherence score before approval.
        """

        normalized_version = self._normalize_version_input(request.version)
        public_version = self._format_public_version(normalized_version)
        version_obj = self._fetch_behavior_version(request.behavior_id, public_version)
        if version_obj.status not in {"IN_REVIEW", "DRAFT"}:
            raise BehaviorVersionError(f"Cannot approve version with status={version_obj.status}.")

        # Quality gate: pre-approval check
        if self._quality_gate is not None and hasattr(self._quality_gate, "check_behavior_approval"):
            adherence = getattr(request, "adherence_score", None)
            if adherence is not None:
                gate_result = self._quality_gate.check_behavior_approval(
                    behavior_id=request.behavior_id,
                    adherence_score=adherence,
                )
                if not gate_result.passed:
                    self._telemetry.emit_event(
                        event_type="behaviors.approval_gate_failed",
                        payload={
                            "behavior_id": request.behavior_id,
                            "version": public_version,
                            "gate_failures": gate_result.failures,
                        },
                        actor=self._actor_payload(actor),
                    )
                    raise BehaviorVersionError(
                        f"Quality gate failed for {request.behavior_id}: "
                        + "; ".join(gate_result.failures)
                    )

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                # Update behavior_versions change_reason
                cur.execute(
                    """
                    UPDATE behavior.behavior_versions
                       SET change_reason = %s
                     WHERE behavior_id = %s AND version = %s::int
                    """,
                                        (f"Approved at {request.effective_from}", request.behavior_id, normalized_version),
                )
                # Update behaviors: set is_active=true, update version and timestamp
                cur.execute(
                    """
                    UPDATE behavior.behaviors
                       SET version = %s::int, is_active = true, is_deprecated = false, status = 'APPROVED', updated_at = %s
                     WHERE id = %s
                    """,
                                        (normalized_version, utc_now_iso(), request.behavior_id),
                )

        self._pool.run_transaction(
            "behavior.approve",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": request.behavior_id,
                "version": public_version,
                "approval_action_id": request.approval_action_id,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        approved = self._fetch_behavior_version(request.behavior_id, public_version)
        self._telemetry.emit_event(
            event_type="behaviors.approved",
            payload={
                "behavior_id": request.behavior_id,
                "version": public_version,
                "approval_action_id": request.approval_action_id,
            },
            actor=self._actor_payload(actor),
        )

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        # Trigger index rebuild when behaviors are approved
        if self._behavior_retriever is not None:
            try:
                rebuild_result = self._behavior_retriever.rebuild_index()
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.auto_rebuild",
                    payload={
                        "trigger": "behavior_approved",
                        "behavior_id": request.behavior_id,
                        "version": public_version,
                        "rebuild_status": rebuild_result.get("status"),
                        "behavior_count": rebuild_result.get("behavior_count", 0),
                        "mode": rebuild_result.get("mode"),
                    },
                )
            except Exception as exc:
                self._telemetry.emit_event(
                    event_type="bci.behavior_retriever.auto_rebuild_failed",
                    payload={
                        "trigger": "behavior_approved",
                        "behavior_id": request.behavior_id,
                        "error": str(exc),
                    },
                )

        return approved

    def deprecate_behavior(self, request: DeprecateBehaviorRequest, actor: Actor) -> BehaviorVersion:
        """Deprecate an active behavior version.

        Uses actual DB schema: is_deprecated flag instead of status column
        """

        normalized_version = self._normalize_version_input(request.version)
        public_version = self._format_public_version(normalized_version)
        version_obj = self._fetch_behavior_version(request.behavior_id, public_version)
        if version_obj.status != "APPROVED":
            raise BehaviorVersionError("Only approved versions can be deprecated.")

        timestamp = utc_now_iso()
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Update behavior_versions change_reason
            cur.execute(
                """
                UPDATE behavior.behavior_versions
                   SET change_reason = %s
                 WHERE behavior_id = %s AND version = %s::int
                """,
                                (f"Deprecated at {request.effective_to}", request.behavior_id, normalized_version),
            )
            # Update behaviors: set is_deprecated=true
            cur.execute(
                """
                UPDATE behavior.behaviors
                   SET is_deprecated = true, is_active = false, status = 'DEPRECATED', deprecation_reason = %s, updated_at = %s
                 WHERE id = %s
                """,
                (f"Deprecated, successor: {request.successor_behavior_id or 'none'}", timestamp, request.behavior_id),
            )
        conn.commit()

        deprecated = self._fetch_behavior_version(request.behavior_id, public_version)
        self._telemetry.emit_event(
            event_type="behaviors.deprecated",
            payload={
                "behavior_id": request.behavior_id,
                "version": public_version,
                "successor_behavior_id": request.successor_behavior_id,
            },
            actor=self._actor_payload(actor),
        )

        # Explicit invalidation on write operations
        get_cache().invalidate_behavior()

        return deprecated

    def delete_behavior_draft(self, behavior_id: str, version: str, actor: Actor) -> None:
        """Delete a draft version.

        Uses actual DB schema: behavior.behaviors and behavior.behavior_versions
        """

        normalized_version = self._normalize_version_input(version)
        public_version = self._format_public_version(normalized_version)
        version_obj = self._fetch_behavior_version(behavior_id, public_version)
        if version_obj.status != "DRAFT":
            raise BehaviorVersionError("Only draft versions can be deleted.")

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM behavior.behavior_versions WHERE behavior_id = %s AND version = %s::int",
                    (behavior_id, normalized_version),
                )
                cur.execute(
                    "SELECT COUNT(*) FROM behavior.behavior_versions WHERE behavior_id = %s",
                    (behavior_id,),
                )
                remaining = cur.fetchone()[0]
                if remaining == 0:
                    cur.execute("DELETE FROM behavior.behaviors WHERE id = %s", (behavior_id,))

        self._pool.run_transaction(
            "behavior.delete_draft",
            service_prefix="behavior",
            actor=self._actor_payload(actor),
            metadata={
                "behavior_id": behavior_id,
                "version": version,
            },
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._telemetry.emit_event(
            event_type="behaviors.draft_deleted",
            payload={"behavior_id": behavior_id, "version": version},
            actor=self._actor_payload(actor),
        )

    def get_behavior(self, behavior_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        """Get a behavior and its versions."""

        behavior = self._fetch_behavior(behavior_id)
        versions = self._fetch_behavior_versions(behavior_id)
        if version:
            versions = [v for v in versions if v.version == version]
            if not versions:
                raise BehaviorVersionError(f"Version {version} not found for behavior {behavior_id}")
        return {
            "behavior": behavior.to_dict(),
            "versions": [v.to_dict() for v in versions],
        }

    def list_behaviors(
        self,
        *,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        role_focus: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List behaviors matching criteria.

        Uses optimized JOIN query + Redis caching to achieve P95 <100ms:
        1. Check cache for matching query (5-min TTL)
        2. If miss, fetch from DB with optimized JOIN
        3. Cache result for subsequent requests

        Cache invalidated on: create_behavior_draft, approve_behavior, deprecate_behavior
        """

        # Build cache key from query parameters
        cache = get_cache()
        cache_params = {}
        if status:
            cache_params['status'] = status
        if tags:
            cache_params['tags'] = sorted(tags)  # Sort for consistent hashing
        if role_focus:
            cache_params['role_focus'] = role_focus

        cache_key = cache._make_key('behavior', 'list', cache_params if cache_params else None)

        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Cache miss - fetch from database with optimized query
        behavior_tuples = self._fetch_behaviors_with_versions(status=status)
        results = []

        for behavior, active_versions in behavior_tuples:
            # Filter by role_focus if specified
            if role_focus:
                active_versions = [v for v in active_versions if v.role_focus == role_focus]
                if not active_versions:
                    continue

            # Filter by tags if specified
            if tags:
                if not set(tags).issubset(set(behavior.tags)):
                    continue

            results.append({
                "behavior": behavior.to_dict(),
                "active_version": active_versions[0].to_dict() if active_versions else None,
            })

        # Cache result using centralized TTL (30 minutes)
        from amprealize.storage.redis_cache import get_ttl
        cache.set(cache_key, results, ttl=get_ttl('behavior', 'list'))

        return results

    def search_behaviors(self, request: SearchBehaviorsRequest, actor: Optional[Actor] = None) -> List[BehaviorSearchResult]:
        """Search behaviors by query, tags, role focus.

        Uses optimized JOIN query to eliminate N+1 performance problem.
        Results are cached with explicit invalidation on write operations.
        """
        # Build cache key from search parameters
        cache = get_cache()
        from amprealize.storage.redis_cache import get_ttl

        cache_params = {
            'query': (request.query or "").lower(),
            'status': request.status,
            'namespace': request.namespace,
            'role_focus': request.role_focus.upper() if request.role_focus else None,
            'tags': sorted(request.tags) if request.tags else [],
            'limit': request.limit,
        }
        cache_key = cache._make_key('behavior', 'search', cache_params)

        # Try cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            # Deserialize from cached dict format
            return [
                BehaviorSearchResult(
                    behavior=Behavior(**r['behavior']),
                    active_version=BehaviorVersion(**r['active_version']) if r.get('active_version') else None,
                    score=r['score']
                )
                for r in cached_result
            ]

        query = (request.query or "").lower()
        # Use optimized fetch that gets behaviors + versions in single query
        behavior_tuples = self._fetch_behaviors_with_versions(
            status=request.status,
            namespace=request.namespace
        )
        matches: List[BehaviorSearchResult] = []

        for behavior, versions in behavior_tuples:
            # Get active (APPROVED) version or first version
            active = next((v for v in versions if v.status == "APPROVED"), versions[0] if versions else None)
            if not active:
                continue
            if request.role_focus and active.role_focus.upper() != request.role_focus.upper():
                continue
            if request.tags and not set(request.tags).issubset(set(behavior.tags)):
                continue

            score = self._calculate_score(query, behavior, active)
            if request.query and score == 0.0:
                continue
            matches.append(BehaviorSearchResult(behavior=behavior, active_version=active, score=score))

        matches.sort(key=lambda result: result.score, reverse=True)
        limited = matches[: request.limit]

        # Cache the result
        cached_data = [
            {
                'behavior': r.behavior.to_dict(),
                'active_version': r.active_version.to_dict() if r.active_version else None,
                'score': r.score
            }
            for r in limited
        ]
        cache.set(cache_key, cached_data, ttl=get_ttl('behavior', 'search'))

        self._telemetry.emit_event(
            event_type="behaviors.search_performed",
            payload={
                "query": request.query or "",
                "tags": request.tags or [],
                "role_focus": request.role_focus,
                "status": request.status,
                "results": len(limited),
            },
            actor=self._actor_payload(actor) if actor else None,
        )
        return limited

    def get_relevant_behaviors_for_task(
        self,
        task_description: str,
        role: str = "Student",
        limit: int = 5,
        actor: Optional[Actor] = None,
        role_context: Optional[RoleContext] = None,
    ) -> Dict[str, Any]:
        """Get relevant behaviors for a task before execution.

        This is the primary method agents should call at the start of any task
        to retrieve applicable behaviors. Follows behavior_prefer_mcp_tools pattern.

        Args:
            task_description: Natural language description of the task
            role: The agent's current role (Student, Teacher, Strategist)
            limit: Maximum number of behaviors to return
            actor: Optional actor for telemetry
            role_context: Optional role context (emphasized for telemetry)

        Returns:
            Dict with:
                - behaviors: List of relevant BehaviorSearchResult
                - recommended_behaviors: Top behaviors formatted for agent prompt
                - role_advisory: Guidance on role-based behavior application
        """
        # Emit role context telemetry (advisory)
        if role_context:
            self._telemetry.emit_event(
                event_type="behaviors.task_retrieval_with_role",
                payload={
                    "task_description": task_description[:200],
                    **role_context.to_telemetry_payload(),
                },
                actor=self._actor_payload(actor) if actor else None,
            )

        # Search for relevant behaviors
        # NOTE: `role` is the agent consumption role (Student/Teacher/Strategist),
        # NOT the behavior domain focus (ENGINEER/SECURITY/DEVOPS/etc.).
        # Do not pass it as role_focus — that would filter out all behaviors.
        search_request = SearchBehaviorsRequest(
            query=task_description,
            role_focus=None,
            status="APPROVED",
            limit=limit,
        )
        results = self.search_behaviors(search_request, actor)

        # Format behaviors for agent prompt consumption
        recommended = []
        for result in results[:limit]:
            if result.active_version:
                behavior_info = {
                    "name": result.behavior.name,
                    "instruction": result.active_version.instruction,
                    "role_focus": result.active_version.role_focus,
                    "trigger_keywords": result.active_version.trigger_keywords,
                    "score": result.score,
                    "confidence_score": result.active_version.confidence_score,
                }
                recommended.append(behavior_info)

        # Generate role-specific advisory
        role_advisory = self._get_role_advisory(role, recommended)

        # Emit task context retrieval event
        self._telemetry.emit_event(
            event_type="behaviors.task_context_retrieved",
            payload={
                "task_description": task_description[:200],
                "role": role,
                "behaviors_found": len(results),
                "recommended_count": len(recommended),
                "behavior_names": [r.behavior.name for r in results[:limit]],
            },
            actor=self._actor_payload(actor) if actor else None,
        )

        return {
            "behaviors": results,
            "recommended_behaviors": recommended,
            "role_advisory": role_advisory,
            "role": role,
            "task_description": task_description,
        }

    def _get_role_advisory(self, role: str, behaviors: List[Dict[str, Any]]) -> str:
        """Generate role-specific advisory for behavior application.

        Based on AGENTS.md role definitions:
        - Student: Execute with guidance, cite behaviors
        - Teacher: Create examples, validate quality
        - Strategist: Analyze patterns, propose new behaviors
        """
        if not behaviors:
            return f"No matching behaviors found. As {role}, consider whether this task requires a new behavior proposal."

        behavior_names = [b["name"] for b in behaviors[:3]]

        if role == "Student":
            return (
                f"📖 Role: Student\n"
                f"Apply these behaviors during execution: {', '.join(behavior_names)}\n"
                f"Cite each behavior in your work output.\n"
                f"If pattern occurs 3+ times without behavior, escalate to Strategist."
            )
        elif role == "Teacher":
            return (
                f"🎓 Role: Teacher\n"
                f"Reference behaviors for validation: {', '.join(behavior_names)}\n"
                f"Create examples, review for quality, mentor Students.\n"
                f"If behavior gaps found, escalate to Strategist."
            )
        elif role == "Strategist":
            return (
                f"🧠 Role: Metacognitive Strategist\n"
                f"Available behaviors: {', '.join(behavior_names)}\n"
                f"If novel pattern detected, propose new behavior.\n"
                f"Follow 3-step process: Solve → Reflect → Emit."
            )
        else:
            return f"Behaviors for task: {', '.join(behavior_names)}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connection(self):
        """Acquire a pooled PostgreSQL connection proxy."""
        return self._pool.proxy()

    def _fetch_behavior(self, behavior_id: str) -> Behavior:
        """Fetch a single behavior by ID."""
        conn = self._ensure_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM behavior.behaviors WHERE id = %s",
                    (behavior_id,),
                )
                row = cur.fetchone()
                desc = cur.description
        except psycopg2.errors.InvalidTextRepresentation:
            # Invalid UUID format - treat as not found
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")

        if row is None:
            raise BehaviorNotFoundError(f"Behavior '{behavior_id}' not found")
        return self._row_to_behavior(row, desc)

    def _fetch_behaviors(self, status: Optional[str] = None) -> List[Behavior]:
        """Fetch behaviors optionally filtered by status."""
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            if status:
                # Map status to is_active/is_deprecated
                if status == "APPROVED":
                    cur.execute(
                        "SELECT * FROM behavior.behaviors WHERE is_active = true AND is_deprecated = false ORDER BY updated_at DESC"
                    )
                elif status == "DEPRECATED":
                    cur.execute(
                        "SELECT * FROM behavior.behaviors WHERE is_deprecated = true ORDER BY updated_at DESC"
                    )
                elif status == "DRAFT":
                    cur.execute(
                        "SELECT * FROM behavior.behaviors WHERE is_active = false AND is_deprecated = false ORDER BY updated_at DESC"
                    )
                else:
                    cur.execute("SELECT * FROM behavior.behaviors ORDER BY updated_at DESC")
            else:
                cur.execute("SELECT * FROM behavior.behaviors ORDER BY updated_at DESC")
            rows = cur.fetchall()
            desc = cur.description

        return [self._row_to_behavior(row, desc) for row in rows]

    def _fetch_behaviors_with_versions(
        self, status: Optional[str] = None, namespace: Optional[str] = None
    ) -> List[Tuple[Behavior, List[BehaviorVersion]]]:
        """Fetch behaviors with their versions in a single optimized JOIN query.

        This method eliminates N+1 query problems by fetching all behaviors and their
        versions in one database round trip, reducing query count from 1+N to 1.

        Performance improvement: ~13x faster for list operations under load.

        Note: Maps actual DB schema (behavior.behaviors with 'id', 'keywords', 'is_active')
        to the Behavior/BehaviorVersion dataclasses expected by the service layer.

        Returns:
            List of (behavior, versions) tuples, where versions are ordered by version DESC.
        """
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Query actual DB schema and map to expected fields
            # DB: id, keywords (varchar[]), is_active, is_deprecated, version (int)
            # Code expects: behavior_id, tags (list), status (str), latest_version (str)
            query = """
                SELECT
                    b.id, b.name, b.description, b.keywords, b.created_at,
                    b.updated_at, b.version, b.is_active, b.is_deprecated, b.namespace,
                    b.category, b.role, b.triggers, b.steps, b.confidence_threshold,
                    bv.id as version_id, bv.version as bv_version, bv.name as bv_name,
                    bv.description as bv_description, bv.triggers as bv_triggers,
                    bv.steps as bv_steps, bv.change_reason, bv.changed_by, bv.created_at as bv_created_at
                FROM behavior.behaviors b
                LEFT JOIN behavior.behavior_versions bv ON b.id = bv.behavior_id
                WHERE 1=1
            """
            params = []

            # Map status filter to is_active/is_deprecated
            if status:
                if status == "APPROVED":
                    query += " AND b.is_active = true AND b.is_deprecated = false"
                elif status == "DEPRECATED":
                    query += " AND b.is_deprecated = true"
                elif status == "DRAFT":
                    query += " AND b.is_active = false AND b.is_deprecated = false"

            if namespace:
                query += " AND COALESCE(b.namespace, %s) = %s"
                params.extend([DEFAULT_BEHAVIOR_NAMESPACE, namespace])

            query += " ORDER BY b.updated_at DESC, bv.version DESC"

            cur.execute(query, params)
            rows = cur.fetchall()

        # Group results by behavior_id since we're now getting all versions
        behavior_map: Dict[str, Tuple[Behavior, List[BehaviorVersion]]] = {}

        for row in rows:
            behavior_id = str(row[0])
            # Map is_active/is_deprecated to status string
            is_active = row[7]
            is_deprecated = row[8]
            derived_status = self._derive_status(
                is_active=bool(is_active),
                is_deprecated=bool(is_deprecated),
                change_reason=row[21],
            )

            # Create or reuse Behavior object
            if behavior_id not in behavior_map:
                behavior = Behavior(
                    behavior_id=str(row[0]),
                    name=row[1],
                    description=row[2] or "",
                    tags=list(row[3]) if row[3] else [],  # keywords (varchar[]) -> tags
                    created_at=str(row[4]) if row[4] else "",
                    updated_at=str(row[5]) if row[5] else "",
                    latest_version=self._format_public_version(row[6] if row[6] else 1),
                    status=derived_status,
                    namespace=row[9] if row[9] else DEFAULT_BEHAVIOR_NAMESPACE,
                )
                behavior_map[behavior_id] = (behavior, [])

            # Add BehaviorVersion if exists (bv_version is at index 16)
            if row[16] is not None:
                # Map behavior_versions schema to BehaviorVersion dataclass
                # DB has: id, behavior_id, version, name, description, triggers, steps, change_reason, changed_by, created_at
                # Code expects: behavior_id, version, instruction, role_focus, status, trigger_keywords, examples, metadata, ...
                version = BehaviorVersion(
                    behavior_id=str(row[0]),
                    version=self._format_public_version(row[16]),
                    instruction=row[18] or "",  # bv.description -> instruction
                    trigger_keywords=row[19] if isinstance(row[19], list) else [],  # bv.triggers -> trigger_keywords
                    role_focus=row[11] or "Student",  # b.role -> role_focus
                    status=self._derive_status(
                        is_active=bool(row[7]),
                        is_deprecated=bool(row[8]),
                        change_reason=row[21],
                    ),
                    examples=row[20] if isinstance(row[20], list) else [],  # bv.steps -> examples
                    metadata={},
                    embedding_checksum=None,
                    embedding=None,
                    effective_from=str(row[23]) if row[23] else "",  # bv.created_at -> effective_from
                    effective_to=None,
                    created_by=row[22] or "",  # bv.changed_by -> created_by
                    approval_action_id=None,
                )
                behavior_map[behavior_id][1].append(version)

        # Return in order (already sorted by b.updated_at DESC in query)
        return list(behavior_map.values())

    def _fetch_behavior_version(self, behavior_id: str, version: str) -> BehaviorVersion:
        """Fetch a single behavior version.

        Uses actual DB schema: behavior.behavior_versions joined with behavior.behaviors
        to get role information.
        """
        normalized_version = self._normalize_version_input(version)
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Join with behaviors to get role and is_active/is_deprecated for status
            cur.execute(
                """
                SELECT bv.id, bv.behavior_id, bv.version, bv.name, bv.description,
                       bv.triggers, bv.steps, bv.change_reason, bv.changed_by, bv.created_at,
                       b.role, b.is_active, b.is_deprecated
                FROM behavior.behavior_versions bv
                JOIN behavior.behaviors b ON b.id = bv.behavior_id
                WHERE bv.behavior_id = %s AND bv.version = %s::int
                """,
                (behavior_id, normalized_version),
            )
            row = cur.fetchone()
            desc = cur.description

        if row is None:
            raise BehaviorVersionError(f"Version '{version}' not found for behavior '{behavior_id}'")

        # Use helper method to convert row to BehaviorVersion
        return self._row_to_behavior_version(row, desc)

    def _fetch_behavior_versions(self, behavior_id: str) -> List[BehaviorVersion]:
        """Fetch all versions for a behavior.

        Uses actual DB schema: behavior.behavior_versions
        """
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            # Join with behaviors to get role and is_active/is_deprecated for status
            cur.execute(
                """
                SELECT bv.id, bv.behavior_id, bv.version, bv.name, bv.description,
                       bv.triggers, bv.steps, bv.change_reason, bv.changed_by, bv.created_at,
                       b.role, b.is_active, b.is_deprecated
                FROM behavior.behavior_versions bv
                JOIN behavior.behaviors b ON b.id = bv.behavior_id
                WHERE bv.behavior_id = %s
                ORDER BY bv.version DESC
                """,
                (behavior_id,),
            )
            rows = cur.fetchall()
            desc = cur.description

        return [self._row_to_behavior_version(row, desc) for row in rows]

    @staticmethod
    def _calculate_embedding_checksum(embedding: Optional[Iterable[float]]) -> Optional[str]:
        """Calculate SHA256 checksum of embedding."""
        if embedding is None:
            return None
        encoded = json.dumps(list(embedding))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    @classmethod
    def _calculate_score(cls, query: str, behavior: Behavior, version: BehaviorVersion) -> float:
        """Approximate text match score using keyword overlap."""
        query_tokens = cls._tokenize(query)
        if not query_tokens:
            return 1.0

        haystack_tokens: List[str] = []
        for content in (
            behavior.name,
            behavior.description,
            " ".join(behavior.tags),
            version.instruction,
            " ".join(version.trigger_keywords),
        ):
            haystack_tokens.extend(cls._tokenize(content))

        if not haystack_tokens:
            return 0.0

        token_set = set(haystack_tokens)
        matches = sum(1 for token in query_tokens if token in token_set)
        return matches / len(query_tokens)

    @staticmethod
    def _resolve_dsn(dsn: Optional[str]) -> str:
        """Resolve PostgreSQL DSN from argument or environment."""
        return resolve_postgres_dsn(
            service="BEHAVIOR",
            explicit_dsn=dsn,
            env_var=_BEHAVIOR_PG_DSN_ENV,
            default_dsn=_DEFAULT_PG_DSN,
        )

    @staticmethod
    def _actor_payload(actor: Actor) -> Dict[str, str]:
        """Convert Actor to telemetry payload."""
        return {
            "id": actor.id,
            "role": actor.role,
            "surface": actor.surface,
        }

    @staticmethod
    def _derive_status(
        *,
        is_active: bool,
        is_deprecated: bool,
        change_reason: Optional[str] = None,
    ) -> str:
        """Map persisted flags and review markers to public lifecycle status."""
        if is_deprecated:
            return "DEPRECATED"
        if is_active:
            return "APPROVED"
        if change_reason and str(change_reason).lower().startswith("submitted for review"):
            return "IN_REVIEW"
        return "DRAFT"

    @staticmethod
    def _row_to_behavior(row: tuple, description) -> Behavior:
        """Convert PostgreSQL row to Behavior object.

        Maps actual DB schema (id, keywords, is_active, is_deprecated, version)
        to Behavior dataclass (behavior_id, tags, status, latest_version).
        """
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Map is_active/is_deprecated to status string
        is_active = data.get("is_active", False)
        is_deprecated = data.get("is_deprecated", False)
        if is_deprecated:
            derived_status = "DEPRECATED"
        elif is_active:
            derived_status = "APPROVED"
        else:
            derived_status = "DRAFT"

        # Handle both old schema (behavior_id) and new schema (id)
        behavior_id = data.get("behavior_id") or data.get("id")

        # Handle both old schema (tags as JSONB) and new schema (keywords as varchar[])
        tags_data = data.get("tags") or data.get("keywords") or []
        if isinstance(tags_data, str):
            tags = json.loads(tags_data)
        else:
            tags = list(tags_data) if tags_data else []

        return Behavior(
            behavior_id=str(behavior_id),
            name=data["name"],
            description=data.get("description") or "",
            tags=tags,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            latest_version=BehaviorService._format_public_version(data.get("latest_version") or data.get("version") or 1),
            status=data.get("status") or derived_status,
            namespace=data.get("namespace", DEFAULT_BEHAVIOR_NAMESPACE),
        )

    @staticmethod
    def _row_to_behavior_version(row: tuple, description) -> BehaviorVersion:
        """Convert PostgreSQL row to BehaviorVersion object.

        Handles both old schema (instruction, trigger_keywords, examples) and
        new schema (description, triggers, steps) columns.
        """
        columns = [desc[0] for desc in description]
        data = dict(zip(columns, row))

        # Handle embedding deserialization from BYTEA column
        # psycopg2 returns memoryview for BYTEA, need to convert properly
        embedding = None
        raw_embedding = data.get("embedding")
        if raw_embedding is not None:
            if isinstance(raw_embedding, memoryview):
                embedding = json.loads(raw_embedding.tobytes().decode('utf-8'))
            elif isinstance(raw_embedding, bytes):
                embedding = json.loads(raw_embedding.decode('utf-8'))
            elif isinstance(raw_embedding, str):
                embedding = json.loads(raw_embedding)
            elif isinstance(raw_embedding, list):
                embedding = raw_embedding

        # Map new schema columns to expected dataclass fields
        # New schema: description -> instruction, triggers -> trigger_keywords, steps -> examples
        instruction = data.get("instruction") or data.get("description", "")

        # Handle triggers/trigger_keywords - can be JSONB (dict/list) or string
        raw_triggers = data.get("trigger_keywords") or data.get("triggers")
        if isinstance(raw_triggers, str):
            trigger_keywords = json.loads(raw_triggers)
        elif isinstance(raw_triggers, list):
            trigger_keywords = raw_triggers
        else:
            trigger_keywords = []

        # Handle examples/steps - can be JSONB (dict/list) or string
        raw_examples = data.get("examples") or data.get("steps")
        if isinstance(raw_examples, str):
            examples = json.loads(raw_examples)
        elif isinstance(raw_examples, list):
            examples = raw_examples
        else:
            examples = []

        # Handle metadata
        raw_metadata = data.get("metadata", {})
        if isinstance(raw_metadata, str):
            metadata = json.loads(raw_metadata)
        elif raw_metadata is None:
            metadata = {}
        else:
            metadata = raw_metadata

        # Derive status from is_active/is_deprecated if available
        if "is_deprecated" in data and "is_active" in data:
            status = BehaviorService._derive_status(
                is_active=bool(data["is_active"]),
                is_deprecated=bool(data["is_deprecated"]),
                change_reason=data.get("change_reason"),
            )
        else:
            status = data.get("status", "DRAFT")

        # Use role from join or role_focus column
        role_focus = data.get("role_focus") or data.get("role", "Student")

        # Handle effective_from/created_at
        effective_from = data.get("effective_from") or data.get("created_at", "")

        # Handle created_by/changed_by
        created_by = data.get("created_by") or data.get("changed_by", "")

        # Handle confidence_score and historical_validations
        confidence_score = data.get("confidence_score")
        if confidence_score is not None:
            confidence_score = float(confidence_score)

        raw_validations = data.get("historical_validations")
        if isinstance(raw_validations, str):
            historical_validations = json.loads(raw_validations)
        elif isinstance(raw_validations, list):
            historical_validations = raw_validations
        else:
            historical_validations = None

        return BehaviorVersion(
            behavior_id=str(data["behavior_id"]),
            version=BehaviorService._format_public_version(data["version"]),
            instruction=instruction,
            role_focus=role_focus,
            status=status,
            trigger_keywords=trigger_keywords,
            examples=examples,
            metadata=metadata,
            effective_from=str(effective_from) if effective_from else "",
            effective_to=str(data["effective_to"]) if data.get("effective_to") else (
                # effective_to is not a dedicated DB column; parse from change_reason
                data.get("change_reason", "").removeprefix("Deprecated at ") or None
            ) if data.get("change_reason", "").startswith("Deprecated at ") else None,
            created_by=created_by,
            approval_action_id=str(data["approval_action_id"]) if data.get("approval_action_id") else None,
            embedding_checksum=data.get("embedding_checksum"),
            embedding=embedding,
            confidence_score=confidence_score,
            historical_validations=historical_validations,
        )

    # ------------------------------------------------------------------
    # Effectiveness & Benchmark Methods
    # ------------------------------------------------------------------

    def get_effectiveness_metrics(
        self,
        status_filter: Optional[str] = None,
        sort_by: str = "usage_count",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Get aggregated effectiveness metrics for behaviors.

        Note: behavior_feedback table doesn't exist in current schema,
        so we return behaviors with zero feedback metrics for now.
        """
        conn = self._ensure_connection()

        # Build query with optional status filter (map to is_active/is_deprecated)
        status_clause = ""
        params: List[Any] = []
        if status_filter:
            if status_filter == "APPROVED":
                status_clause = "WHERE b.is_active = true AND b.is_deprecated = false"
            elif status_filter == "DEPRECATED":
                status_clause = "WHERE b.is_deprecated = true"
            elif status_filter == "DRAFT":
                status_clause = "WHERE b.is_active = false AND b.is_deprecated = false"

        params.append(limit)

        with conn.cursor() as cur:
            # Query behaviors - behavior_feedback doesn't exist, so no join
            cur.execute(
                f"""
                SELECT
                    b.id,
                    b.name,
                    b.is_active,
                    b.is_deprecated,
                    b.updated_at
                FROM behavior.behaviors b
                {status_clause}
                ORDER BY b.updated_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

            # Get aggregate stats using is_active/is_deprecated
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_behaviors,
                    COUNT(*) FILTER (WHERE is_active = true AND is_deprecated = false) as approved_count,
                    COUNT(*) FILTER (WHERE is_active = false AND is_deprecated = false) as draft_count,
                    COUNT(*) FILTER (WHERE is_deprecated = true) as deprecated_count
                FROM behavior.behaviors
                """
            )
            totals = cur.fetchone()

        behaviors = []
        for row in rows:
            # Map is_active/is_deprecated to status string
            is_active = row[2]
            is_deprecated = row[3]
            if is_deprecated:
                derived_status = "DEPRECATED"
            elif is_active:
                derived_status = "APPROVED"
            else:
                derived_status = "DRAFT"

            behaviors.append({
                "behavior_id": str(row[0]),
                "name": row[1],
                "status": derived_status,
                "updated_at": str(row[4]) if row[4] else "",
                "usage_count": 0,  # No feedback table yet
                "avg_relevance": 0.0,
                "avg_helpfulness": 0.0,
                "avg_token_reduction": 0.0,
                "feedback_count": 0,
            })

        return {
            "behaviors": behaviors,
            "summary": {
                "total_behaviors": totals[0] if totals else 0,
                "approved_count": totals[1] if totals else 0,
                "draft_count": totals[2] if totals else 0,
                "deprecated_count": totals[3] if totals else 0,
                "total_feedback": 0,  # No feedback table yet
                "overall_avg_relevance": 0.0,
                "overall_avg_token_reduction": 0.0,
            },
        }

    def record_feedback(
        self,
        behavior_id: str,
        relevance_score: int,
        helpfulness_score: Optional[int],
        token_reduction_observed: Optional[float],
        comment: Optional[str],
        actor_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record curator feedback for a behavior.

        Note: behavior_feedback table doesn't exist in current schema.
        This method validates the behavior exists and logs the feedback
        via telemetry only.
        """
        # Validate behavior exists
        self._fetch_behavior(behavior_id)

        feedback_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        # Log feedback via telemetry since table doesn't exist
        self._telemetry.emit_event(
            event_type="behaviors.feedback_recorded",
            payload={
                "behavior_id": behavior_id,
                "feedback_id": feedback_id,
                "relevance_score": relevance_score,
                "helpfulness_score": helpfulness_score,
                "token_reduction_observed": token_reduction_observed,
                "comment": comment,
            },
            actor={"id": actor_id, "role": "curator", "surface": "api"},
        )

        return {
            "feedback_id": feedback_id,
            "behavior_id": behavior_id,
            "relevance_score": relevance_score,
            "helpfulness_score": helpfulness_score,
            "token_reduction_observed": token_reduction_observed,
            "created_at": timestamp,
        }

    def get_feedback(self, behavior_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get feedback entries for a specific behavior.

        Note: behavior_feedback table doesn't exist in current schema.
        Returns empty list.
        """
        self._fetch_behavior(behavior_id)  # Validate behavior exists
        return []  # No feedback table yet

    def get_benchmark_results(self, limit: int = 20) -> Dict[str, Any]:
        """Get latest benchmark results.

        Note: behavior_benchmarks table doesn't exist in current schema.
        Returns empty list.
        """
        return {"benchmarks": [], "total": 0}

    def trigger_benchmark(
        self,
        corpus_path: Optional[str] = None,
        sample_size: int = 100,
        actor_id: str = "system",
    ) -> Dict[str, Any]:
        """Trigger a new benchmark run.

        Note: behavior_benchmarks table doesn't exist in current schema.
        Logs to telemetry instead.
        """
        benchmark_id = str(uuid.uuid4())
        timestamp = utc_now_iso()

        # Log via telemetry since table doesn't exist
        if self._telemetry:
            self._telemetry.info(
                "behavior_benchmark_triggered",
                benchmark_id=benchmark_id,
                sample_size=sample_size,
                corpus_path=corpus_path,
                actor_id=actor_id,
                timestamp=timestamp,
            )

        return {
            "benchmark_id": benchmark_id,
            "status": "NOT_IMPLEMENTED",
            "message": "Benchmark table not available in current schema",
            "sample_size": sample_size,
            "triggered_at": timestamp,
        }

    # ------------------------------------------------------------------
    # Lifecycle policies (T4.2.3)
    # ------------------------------------------------------------------

    def promote_candidate_to_behavior(
        self,
        *,
        candidate_name: str,
        candidate_summary: str,
        candidate_triggers: List[str],
        candidate_steps: List[str],
        candidate_keywords: List[str],
        candidate_confidence: float,
        candidate_role: str = "Student",
        actor: Actor,
    ) -> Dict[str, Any]:
        """Promote an approved reflection candidate to a full behavior.

        Creates a new behavior via propose_behavior() which handles
        auto-approval when confidence >= 0.8 and historical_validations >= 3.

        Returns:
            Dict with behavior_id, version, status, auto_approved flag.
        """
        # Ensure name follows behavior_<verb>_<noun> pattern
        name = candidate_name
        if not name.startswith("behavior_"):
            name = f"behavior_{name}"

        request = ProposeBehaviorRequest(
            name=name,
            description=candidate_summary,
            instruction="\n".join(candidate_steps) if candidate_steps else candidate_summary,
            role_focus=candidate_role,
            trigger_keywords=candidate_triggers,
            tags=candidate_keywords,
            examples=[],
            confidence_score=candidate_confidence,
            historical_validations=[],
            proposed_by_role="Strategist",
            rationale="Auto-promoted from approved reflection candidate",
        )

        return self.propose_behavior(request, actor)

    def list_expiring_behaviors(self, *, days: int = 30) -> List[Dict[str, Any]]:
        """List active behaviors that haven't been reviewed/updated recently.

        Since effective_to is not a dedicated DB column, we use updated_at
        as a staleness proxy: behaviors not updated in (days) days are
        considered candidates for review.

        Returns:
            List of behavior dicts with staleness info.
        """
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, version, updated_at, keywords
                FROM behavior.behaviors
                WHERE is_active = true AND is_deprecated = false
                  AND updated_at < %s
                ORDER BY updated_at ASC
                """,
                (cutoff_iso,),
            )
            rows = cur.fetchall()

        results = []
        now = datetime.now(timezone.utc)
        for row in rows:
            updated_str = row[4]
            if isinstance(updated_str, str):
                try:
                    updated_dt = datetime.fromisoformat(updated_str)
                except ValueError:
                    updated_dt = now
            else:
                updated_dt = updated_str if updated_str else now

            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)

            stale_days = (now - updated_dt).days
            results.append({
                "behavior_id": row[0],
                "name": row[1],
                "description": row[2],
                "version": row[3],
                "updated_at": str(row[4]),
                "keywords": row[5] if row[5] else [],
                "stale_days": stale_days,
            })

        return results

    def flag_stale_behaviors(
        self,
        *,
        stale_days: int = 90,
        actor: Actor,
    ) -> Dict[str, Any]:
        """Flag behaviors that exceed staleness threshold for deprecation review.

        Emits telemetry events for each flagged behavior so dashboards and
        GateNotifier consumers can act on them.

        Returns:
            Dict with flagged behavior IDs and count.
        """
        expiring = self.list_expiring_behaviors(days=stale_days)

        flagged_ids = []
        for beh in expiring:
            flagged_ids.append(beh["behavior_id"])
            self._telemetry.emit_event(
                event_type="behaviors.flagged_stale",
                payload={
                    "behavior_id": beh["behavior_id"],
                    "name": beh["name"],
                    "stale_days": beh["stale_days"],
                    "threshold_days": stale_days,
                },
                actor=self._actor_payload(actor),
            )

        return {
            "flagged_count": len(flagged_ids),
            "flagged_behavior_ids": flagged_ids,
            "threshold_days": stale_days,
        }

    def check_overlay_compliance(
        self,
        *,
        min_citation_rate: float = 0.3,
        lookback_days: int = 30,
        actor: Actor,
    ) -> Dict[str, Any]:
        """Check overlay/behavior citation compliance and flag poor outcomes.

        Identifies behaviors that were retrieved but rarely cited in outputs,
        indicating poor adherence or relevance. Emits telemetry events for
        each flagged item so that GateNotifier consumers can trigger
        review notifications.

        Args:
            min_citation_rate: Minimum ratio of citations/retrievals (0.0-1.0).
            lookback_days: Number of days to look back for telemetry data.
            actor: Actor performing the compliance check.

        Returns:
            Dict with flagged behaviors and compliance stats.
        """
        flagged = []

        # Query behavior effectiveness from DB if available
        try:
            conn = self._ensure_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, description
                    FROM behavior.behaviors
                    WHERE is_active = true AND is_deprecated = false
                    """,
                )
                active_rows = cur.fetchall()
        except Exception:
            active_rows = []

        # For each active behavior, check if effectiveness data exists
        for row in active_rows:
            behavior_id, name, description = row[0], row[1], row[2]
            try:
                metrics = self.get_effectiveness_metrics(behavior_id)
                retrieval_count = metrics.get("retrieval_count", 0)
                citation_count = metrics.get("citation_count", 0)
                if retrieval_count > 0:
                    citation_rate = citation_count / retrieval_count
                    if citation_rate < min_citation_rate:
                        flagged.append({
                            "behavior_id": behavior_id,
                            "name": name,
                            "retrieval_count": retrieval_count,
                            "citation_count": citation_count,
                            "citation_rate": round(citation_rate, 3),
                        })
                        self._telemetry.emit_event(
                            event_type="behaviors.poor_compliance",
                            payload={
                                "behavior_id": behavior_id,
                                "name": name,
                                "citation_rate": round(citation_rate, 3),
                                "min_citation_rate": min_citation_rate,
                                "retrieval_count": retrieval_count,
                                "citation_count": citation_count,
                                "lookback_days": lookback_days,
                            },
                            actor=self._actor_payload(actor),
                        )
            except Exception:
                continue

        return {
            "flagged_count": len(flagged),
            "flagged_behaviors": flagged,
            "min_citation_rate": min_citation_rate,
            "lookback_days": lookback_days,
        }
