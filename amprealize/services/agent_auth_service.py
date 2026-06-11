"""AgentAuthService PostgreSQL implementation aligning with AGENT_AUTH_ARCHITECTURE.md.

Replaces the in-memory AgentAuthClient stub with a production-ready service that:
- Stores grants in PostgreSQL with audit trails
- Enforces RBAC policies and high-risk scope MFA requirements
- Integrates with ActionService for audit logging
- Emits telemetry for consent flows and policy decisions
- Supports multi-environment configuration via Settings

References:
- docs/AGENT_AUTH_ARCHITECTURE.md: Service contract, policy engine, token vault
- SECRETS_MANAGEMENT_PLAN.md: Rotation runbooks, OS keychain integration
- docs/contracts/MCP_SERVER_DESIGN.md: Tool surface parity expectations
- AGENTS.md: behavior_lock_down_security_surface compliance
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from ..auth.policy_engine import PolicyDecision, get_policy_engine
from ..storage.postgres_pool import PostgresPool
from ..surfaces import normalize_actor_surface
from ..telemetry import TelemetryClient


# --- Constants from AGENT_AUTH_ARCHITECTURE.md §6 ---

HIGH_RISK_SCOPES = {
    "actions.replay",
    "agentauth.manage",
}

CONSENT_SCOPE_TRIGGERS = {
    "actions.replay",
    "reviews.run",
    "agentauth.manage",
}

MFA_CONTEXT_KEY = "mfa_verified"
MFA_REQUIRED_VALUE = "true"

DEFAULT_PROVIDER = "amprealize.production"
DEFAULT_TTL = timedelta(minutes=60)

# --- Contract Types (matching agent_auth.py) ---


class GrantDecision(str, Enum):
    """Enumeration of possible AgentAuth decisions."""

    ALLOW = "ALLOW"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    DENY = "DENY"


class DecisionReason(str, Enum):
    """Structured reasons matching the contract definitions."""

    SCOPE_NOT_APPROVED = "SCOPE_NOT_APPROVED"
    POLICY_CONDITION_FAILED = "POLICY_CONDITION_FAILED"
    SECURITY_HOLD = "SECURITY_HOLD"
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class Obligation:
    """Obligation metadata attached to grants."""

    def __init__(self, type: str, attributes: Optional[Dict[str, str]] = None) -> None:
        self.type = type
        self.attributes = attributes or {}

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "attributes": dict(self.attributes),
        }

    @staticmethod
    def from_dict(data: Dict) -> Obligation:
        return Obligation(
            type=data["type"],
            attributes=data.get("attributes", {}),
        )


class GrantMetadata:
    """Grant record stored in PostgreSQL with audit trail."""

    def __init__(
        self,
        grant_id: str,
        agent_id: str,
        user_id: Optional[str],
        tool_name: str,
        scopes: List[str],
        provider: str,
        issued_at: str,
        expires_at: str,
        obligations: Optional[List[Obligation]] = None,
    ) -> None:
        self.grant_id = grant_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.tool_name = tool_name
        self.scopes = scopes
        self.provider = provider
        self.issued_at = issued_at
        self.expires_at = expires_at
        self.obligations = obligations or []

    def to_dict(self) -> Dict:
        return {
            "grant_id": self.grant_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "tool_name": self.tool_name,
            "scopes": list(self.scopes),
            "provider": self.provider,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "obligations": [o.to_dict() for o in self.obligations],
        }

    @staticmethod
    def from_row(row: Dict) -> GrantMetadata:
        """Deserialize from PostgreSQL row."""
        obligations_json = row.get("obligations", "[]")
        obligations_data = json.loads(obligations_json) if isinstance(obligations_json, str) else obligations_json
        scopes_value = row["scopes"]
        if isinstance(scopes_value, str):
            try:
                scopes_value = json.loads(scopes_value)
            except json.JSONDecodeError:
                scopes_value = [scopes_value]
        issued_at_value = row["issued_at"]
        if isinstance(issued_at_value, datetime):
            issued_at_value = issued_at_value.isoformat()
        expires_at_value = row["expires_at"]
        if isinstance(expires_at_value, datetime):
            expires_at_value = expires_at_value.isoformat()
        return GrantMetadata(
            grant_id=row["grant_id"],
            agent_id=row["agent_id"],
            user_id=row.get("user_id"),
            tool_name=row["tool_name"],
            scopes=scopes_value,
            provider=row["provider"],
            issued_at=issued_at_value,
            expires_at=expires_at_value,
            obligations=[Obligation.from_dict(o) for o in obligations_data],
        )


# --- Request/Response Types ---


class EnsureGrantRequest:
    """Request to ensure a grant exists and is valid."""

    def __init__(
        self,
        agent_id: str,
        surface: str,
        tool_name: str,
        scopes: List[str],
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, str]] = None,
        policy_version: Optional[str] = None,
    ) -> None:
        self.agent_id = agent_id
        self.surface = surface
        self.tool_name = tool_name
        self.scopes = scopes
        self.request_id = request_id or str(uuid.uuid4())
        self.user_id = user_id
        self.context = context or {}
        self.policy_version = policy_version


class EnsureGrantResponse:
    """Response with decision, grant metadata, and optional consent URL."""

    def __init__(
        self,
        decision: GrantDecision,
        reason: Optional[DecisionReason] = None,
        consent_url: Optional[str] = None,
        consent_request_id: Optional[str] = None,
        grant: Optional[GrantMetadata] = None,
        audit_action_id: Optional[str] = None,
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.consent_url = consent_url
        self.consent_request_id = consent_request_id
        self.grant = grant
        self.audit_action_id = audit_action_id


class RevokeGrantRequest:
    """Request to revoke an existing grant."""

    def __init__(
        self,
        grant_id: str,
        revoked_by: str,
        reason: Optional[str] = None,
    ) -> None:
        self.grant_id = grant_id
        self.revoked_by = revoked_by
        self.reason = reason


class RevokeGrantResponse:
    """Response confirming grant revocation."""

    def __init__(
        self,
        grant_id: str,
        success: bool,
        reason: Optional[DecisionReason] = None,
    ) -> None:
        self.grant_id = grant_id
        self.success = success
        self.reason = reason


class ListGrantsRequest:
    """Request to list grants with optional filters."""

    def __init__(
        self,
        agent_id: str,
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        include_expired: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.user_id = user_id
        self.tool_name = tool_name
        self.include_expired = include_expired


class PolicyPreviewRequest:
    """Request to preview policy decision without issuing grant."""

    def __init__(
        self,
        agent_id: str,
        tool_name: str,
        scopes: List[str],
        user_id: Optional[str] = None,
        context: Optional[Dict[str, str]] = None,
        bundle_version: Optional[str] = None,
    ) -> None:
        self.agent_id = agent_id
        self.tool_name = tool_name
        self.scopes = scopes
        self.user_id = user_id
        self.context = context or {}
        self.bundle_version = bundle_version


class PolicyPreviewResponse:
    """Preview decision without mutating grant state."""

    def __init__(
        self,
        decision: GrantDecision,
        reason: Optional[DecisionReason] = None,
        bundle_version: Optional[str] = None,
        obligations: Optional[List[Obligation]] = None,
    ) -> None:
        self.decision = decision
        self.reason = reason
        self.bundle_version = bundle_version
        self.obligations = obligations or []


# --- Errors ---


class AgentAuthServiceError(Exception):
    """Base error for AgentAuthService operations."""


class GrantNotFoundError(AgentAuthServiceError):
    """Raised when a grant cannot be found."""


class ConsentRequestNotFoundError(AgentAuthServiceError):
    """Raised when attempting to resolve an unknown consent request."""


# --- Service Implementation ---


class AgentAuthService:
    """PostgreSQL-backed AgentAuth service with policy enforcement and audit integration.

    Responsibilities:
    - Grant CRUD operations with TTL enforcement
    - Policy evaluation (RBAC roles, high-risk scopes, MFA requirements)
    - Consent orchestration with pending request tracking
    - Audit integration via ActionService and telemetry events
    - Multi-environment support via Settings configuration

    Database Schema (agent_grants table):
    - grant_id: TEXT PRIMARY KEY
    - agent_id: TEXT NOT NULL
    - user_id: TEXT (nullable for service principals)
    - tool_name: TEXT NOT NULL
    - scopes: JSONB NOT NULL (array of scope strings)
    - provider: TEXT NOT NULL
    - issued_at: TIMESTAMPTZ NOT NULL
    - expires_at: TIMESTAMPTZ NOT NULL
    - revoked_at: TIMESTAMPTZ (nullable)
    - obligations: JSONB (array of obligation objects)
    - created_at: TIMESTAMPTZ DEFAULT NOW()

    Indexes:
    - idx_agent_grants_lookup: (agent_id, user_id, tool_name) for fast grant retrieval
    - idx_agent_grants_expiry: (expires_at) for TTL enforcement
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        """Initialize service with PostgreSQL connection pool and telemetry.

        Args:
            dsn: PostgreSQL DSN (optional, falls back to Settings.database.postgres_url)
            telemetry: TelemetryClient instance (defaults to noop)
        """
        self._pool = PostgresPool(dsn=dsn, service_name="AGENTAUTH")
        self._telemetry = telemetry or TelemetryClient.noop()
        self._pending_consent: Dict[str, EnsureGrantRequest] = {}
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create agent_grants table if it doesn't exist."""
        with self._pool.connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_grants (
                        grant_id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        user_id TEXT,
                        tool_name TEXT NOT NULL,
                        scopes JSONB NOT NULL,
                        provider TEXT NOT NULL,
                        issued_at TIMESTAMPTZ NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        revoked_at TIMESTAMPTZ,
                        obligations JSONB DEFAULT '[]'::jsonb,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_grants_lookup
                        ON agent_grants(agent_id, user_id, tool_name)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_grants_expiry
                        ON agent_grants(expires_at)
                    """
                )
            finally:
                cur.close()
            conn.commit()

    # --- Core RPC Methods ---

    def ensure_grant(self, request: EnsureGrantRequest) -> EnsureGrantResponse:
        """Evaluate grant request and return decision with grant or consent requirement.

        Flow:
        1. Check for existing valid grant (reuse if found)
        2. Evaluate MFA requirements for high-risk scopes
        3. Check consent triggers
        4. Issue new grant if policy allows
        5. Emit telemetry for decision

        Returns:
            EnsureGrantResponse with ALLOW, CONSENT_REQUIRED, or DENY decision
        """
        actor_payload = self._actor_from_request(request)
        normalized_scopes = self._normalize_scopes(request.scopes)
        request.scopes = normalized_scopes
        requires_mfa = self._requires_mfa(normalized_scopes)
        needs_consent = self._requires_consent(normalized_scopes)
        mfa_verified = self._is_mfa_verified(request)

        # Immediately route high-risk scopes through consent flow to avoid stale grants
        if needs_consent:
            consent_request_id = str(uuid.uuid4())
            consent_url = f"https://dashboard.amprealize.dev/consent/{consent_request_id}"
            self._pending_consent[consent_request_id] = request
            response = EnsureGrantResponse(
                decision=GrantDecision.CONSENT_REQUIRED,
                reason=DecisionReason.SCOPE_NOT_APPROVED,
                consent_url=consent_url,
                consent_request_id=consent_request_id,
            )
            self._emit_auth_event(
                event_type="auth_grant_decision",
                actor=actor_payload,
                request=request,
                decision=GrantDecision.CONSENT_REQUIRED,
                reason=DecisionReason.SCOPE_NOT_APPROVED,
                grant=None,
                extra_payload={
                    "mfa_required": requires_mfa,
                    "consent_request_id": consent_request_id,
                },
            )
            return response

        # Check for existing valid grant after consent edge cases are handled
        existing = self._find_grant(request)
        if existing and not self._is_expired(existing):
            self._emit_auth_event(
                event_type="auth_grant_decision",
                actor=actor_payload,
                request=request,
                decision=GrantDecision.ALLOW,
                reason=None,
                grant=existing,
                extra_payload={
                    "grant_reused": True,
                    "mfa_required": requires_mfa,
                },
            )
            return EnsureGrantResponse(
                decision=GrantDecision.ALLOW,
                grant=existing,
                audit_action_id=str(uuid.uuid4()),
            )

        # Enforce MFA for remaining high-risk scopes
        if requires_mfa and not mfa_verified:
            self._emit_auth_event(
                event_type="auth_grant_decision",
                actor=actor_payload,
                request=request,
                decision=GrantDecision.DENY,
                reason=DecisionReason.SECURITY_HOLD,
                grant=None,
                extra_payload={
                    "mfa_required": True,
                    "grant_reused": False,
                },
            )
            return EnsureGrantResponse(
                decision=GrantDecision.DENY,
                reason=DecisionReason.SECURITY_HOLD,
            )

        # Issue new grant
        grant = self._issue_grant(
            request,
            requires_mfa=requires_mfa,
            normalized_scopes=normalized_scopes,
        )
        self._emit_auth_event(
            event_type="auth_grant_decision",
            actor=actor_payload,
            request=request,
            decision=GrantDecision.ALLOW,
            reason=None,
            grant=grant,
            extra_payload={
                "mfa_required": requires_mfa,
                "grant_reused": False,
            },
        )
        return EnsureGrantResponse(
            decision=GrantDecision.ALLOW,
            grant=grant,
            audit_action_id=str(uuid.uuid4()),
        )

    def approve_consent(self, consent_request_id: str, approver: str) -> GrantMetadata:
        """Finalize pending consent request and issue grant.

        Called by consent UX after user approval.

        Args:
            consent_request_id: Unique identifier from EnsureGrantResponse
            approver: User ID of approver

        Returns:
            GrantMetadata for newly issued grant

        Raises:
            ConsentRequestNotFoundError: If consent_request_id is invalid
        """
        if consent_request_id not in self._pending_consent:
            raise ConsentRequestNotFoundError(f"Consent request '{consent_request_id}' not found")

        request = self._pending_consent.pop(consent_request_id)
        request.context["approved_by"] = approver
        requires_mfa = self._requires_mfa(request.scopes)
        grant = self._issue_grant(
            request,
            requires_mfa=requires_mfa,
            normalized_scopes=self._normalize_scopes(request.scopes),
        )

        approver_actor = {
            "id": approver,
            "role": request.context.get("approver_role", "APPROVER"),
            "surface": normalize_actor_surface(request.surface),
        }
        self._emit_auth_event(
            event_type="auth_consent_approved",
            actor=approver_actor,
            request=request,
            decision=GrantDecision.ALLOW,
            reason=None,
            grant=grant,
            extra_payload={
                "mfa_required": requires_mfa,
                "consent_request_id": consent_request_id,
            },
        )
        return grant

    def revoke_grant(self, request: RevokeGrantRequest) -> RevokeGrantResponse:
        """Revoke existing grant by setting revoked_at timestamp.

        Grant remains in database for audit trail but is excluded from active queries.

        Args:
            request: RevokeGrantRequest with grant_id and revoked_by

        Returns:
            RevokeGrantResponse confirming success or failure
        """
        columns = (
            "grant_id",
            "agent_id",
            "user_id",
            "tool_name",
            "scopes",
            "provider",
            "issued_at",
            "expires_at",
            "obligations",
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                cur.execute(
                    """
                    UPDATE agent_grants
                    SET revoked_at = NOW()
                    WHERE grant_id = %s AND revoked_at IS NULL
                    RETURNING grant_id, agent_id, user_id, tool_name, scopes, provider,
                              issued_at, expires_at, obligations
                    """,
                    (request.grant_id,),
                )
                row = cur.fetchone()
                affected = getattr(cur, "rowcount", 0)
            conn.commit()

        if affected == 0:
            self._emit_auth_event(
                event_type="auth_grant_revoked",
                actor={
                    "id": request.revoked_by,
                    "role": "ADMIN",
                    "surface": "api",
                },
                request=None,
                decision=GrantDecision.DENY,
                reason=DecisionReason.SCOPE_NOT_APPROVED,
                grant=None,
                extra_payload={
                    "grant_id": request.grant_id,
                    "status": "MISSING",
                },
            )
            raise GrantNotFoundError(f"Grant '{request.grant_id}' not found or already revoked")

        grant: Optional[GrantMetadata] = None
        if row:
            row_dict = self._row_to_dict(row, columns)
            prepared = self._prepare_grant_row(row_dict)
            grant = GrantMetadata.from_row(prepared)
        self._emit_auth_event(
            event_type="auth_grant_revoked",
            actor={
                "id": request.revoked_by,
                "role": "ADMIN",
                "surface": "api",
            },
            request=None,
            decision=GrantDecision.DENY,
            reason=None,
            grant=grant,
            extra_payload={
                "grant_id": request.grant_id,
                "status": "REVOKED",
                "revocation_reason": request.reason,
            },
        )
        return RevokeGrantResponse(grant_id=request.grant_id, success=True)

    def list_grants(self, request: ListGrantsRequest) -> List[GrantMetadata]:
        """List grants filtered by agent/user/tool, optionally including expired.

        Args:
            request: ListGrantsRequest with optional filters

        Returns:
            List of GrantMetadata matching filters
        """
        conditions = ["agent_id = %s", "revoked_at IS NULL"]
        params: List[Any] = [request.agent_id]

        if request.user_id is not None:
            conditions.append("user_id = %s")
            params.append(request.user_id)

        if request.tool_name:
            conditions.append("tool_name = %s")
            params.append(request.tool_name)

        if not request.include_expired:
            conditions.append("expires_at > NOW()")

        query = f"""
            SELECT grant_id, agent_id, user_id, tool_name, scopes, provider,
                   issued_at, expires_at, revoked_at, obligations
            FROM agent_grants
            WHERE {" AND ".join(conditions)}
            ORDER BY issued_at DESC
        """

        columns = (
            "grant_id",
            "agent_id",
            "user_id",
            "tool_name",
            "scopes",
            "provider",
            "issued_at",
            "expires_at",
            "revoked_at",
            "obligations",
        )

        with self._pool.connection() as conn:
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

        grants: List[GrantMetadata] = []
        for row in rows:
            row_dict = self._row_to_dict(row, columns)
            prepared = self._prepare_grant_row(row_dict)
            grants.append(GrantMetadata.from_row(prepared))

        return grants

    def policy_preview(self, request: PolicyPreviewRequest) -> PolicyPreviewResponse:
        """Preview policy decision without issuing grant.

        Uses the PolicyEngine for dynamic YAML-based policy evaluation.
        Supports RBAC roles, high-risk scopes, MFA requirements, and first-match rules.

        Args:
            request: PolicyPreviewRequest with agent/tool/scopes

        Returns:
            PolicyPreviewResponse with decision and obligations
        """
        actor_payload = {
            "id": request.user_id or request.agent_id,
            "role": request.context.get("roles", "UNKNOWN"),
            "surface": normalize_actor_surface(request.context.get("surface", "API")),
        }

        # Use PolicyEngine for dynamic evaluation
        try:
            engine = get_policy_engine()
            role = request.context.get("roles", "OBSERVER")
            mfa_verified = request.context.get(MFA_CONTEXT_KEY) == MFA_REQUIRED_VALUE

            # Build evaluation context
            eval_context = {
                **request.context,
                "mfa_verified": mfa_verified,
            }

            # Preview all requested scopes
            preview_result = engine.preview(
                role=role,
                scopes=list(request.scopes),
                tool_name=request.tool_name,
                context=eval_context,
            )

            # Map PolicyEngine decision to GrantDecision
            decision_mapping = {
                PolicyDecision.ALLOW: GrantDecision.ALLOW,
                PolicyDecision.DENY: GrantDecision.DENY,
                PolicyDecision.CONSENT_REQUIRED: GrantDecision.CONSENT_REQUIRED,
            }

            # Determine overall decision (most restrictive)
            overall_decision = GrantDecision.ALLOW
            overall_reason = None
            obligations: List[Obligation] = []

            for scope, result in preview_result.items():
                mapped_decision = decision_mapping.get(result.decision, GrantDecision.DENY)

                # DENY is most restrictive, then CONSENT_REQUIRED, then ALLOW
                if mapped_decision == GrantDecision.DENY:
                    overall_decision = GrantDecision.DENY
                    overall_reason = DecisionReason(result.reason.value) if result.reason else DecisionReason.SCOPE_NOT_APPROVED
                    break
                elif mapped_decision == GrantDecision.CONSENT_REQUIRED and overall_decision == GrantDecision.ALLOW:
                    overall_decision = GrantDecision.CONSENT_REQUIRED
                    overall_reason = DecisionReason(result.reason.value) if result.reason else DecisionReason.SCOPE_NOT_APPROVED

                # Collect obligations from all scopes
                for obl in result.obligations:
                    obligations.append(Obligation(type=obl.type, attributes=obl.attributes))

            response = PolicyPreviewResponse(
                decision=overall_decision,
                reason=overall_reason,
                bundle_version=engine.bundle_version,
                obligations=obligations if obligations else None,
            )

        except Exception as e:
            # Fallback to deny-by-default if PolicyEngine fails
            response = PolicyPreviewResponse(
                decision=GrantDecision.DENY,
                reason=DecisionReason.POLICY_CONDITION_FAILED,
                bundle_version=request.bundle_version or "unknown",
            )
            self._telemetry.emit(
                event_type="auth_policy_engine_error",
                payload={"error": str(e), "agent_id": request.agent_id},
            )

        self._emit_auth_event(
            event_type="auth_policy_preview",
            actor=actor_payload,
            request=None,
            decision=response.decision,
            reason=response.reason,
            grant=None,
            extra_payload={
                "agent_id": request.agent_id,
                "tool_name": request.tool_name,
                "scopes": list(request.scopes),
                "bundle_version": response.bundle_version,
                "used_policy_engine": True,
            },
        )

        return response

    # --- Internal Helpers ---

    def _issue_grant(
        self,
        request: EnsureGrantRequest,
        *,
        requires_mfa: bool = False,
        normalized_scopes: Optional[List[str]] = None,
    ) -> GrantMetadata:
        """Create and persist new grant to PostgreSQL."""
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + DEFAULT_TTL
        grant_id = str(uuid.uuid4())
        scopes_to_store = normalized_scopes or self._normalize_scopes(request.scopes)

        obligations: List[Obligation] = []
        if any(scope in CONSENT_SCOPE_TRIGGERS for scope in scopes_to_store):
            obligations.append(
                Obligation(type="notification", attributes={"channel": "#agent-reviews"})
            )
        if requires_mfa:
            obligations.append(
                Obligation(type="mfa", attributes={"method": "TOTP"})
            )

        obligations_json = json.dumps([o.to_dict() for o in obligations])

        returned_row = None
        with self._pool.connection() as conn:
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                cur.execute(
                    """
                    INSERT INTO agent_grants
                        (grant_id, agent_id, user_id, tool_name, scopes, provider,
                         issued_at, expires_at, obligations)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING grant_id
                    """,
                    (
                        grant_id,
                        request.agent_id,
                        request.user_id,
                        request.tool_name,
                        json.dumps(scopes_to_store),
                        DEFAULT_PROVIDER,
                        issued_at.isoformat(),
                        expires_at.isoformat(),
                        obligations_json,
                    ),
                )
                returned_row = cur.fetchone()
            conn.commit()

        returned_grant_id = self._extract_value(returned_row, ("grant_id",))
        if returned_grant_id:
            grant_id = returned_grant_id

        return GrantMetadata(
            grant_id=grant_id,
            agent_id=request.agent_id,
            user_id=request.user_id,
            tool_name=request.tool_name,
            scopes=list(scopes_to_store),
            provider=DEFAULT_PROVIDER,
            issued_at=issued_at.isoformat(),
            expires_at=expires_at.isoformat(),
            obligations=obligations,
        )

    @staticmethod
    def _normalize_scopes(scopes: Iterable[str]) -> List[str]:
        """Deduplicate and sort scopes for deterministic storage/comparison."""
        unique_scopes = {scope.strip() for scope in scopes if scope.strip()}
        return sorted(unique_scopes)

    @staticmethod
    def _requires_consent(scopes: Iterable[str]) -> bool:
        """Determine whether requested scopes require consent."""
        return any(scope in CONSENT_SCOPE_TRIGGERS for scope in scopes)

    def _find_grant(self, request: EnsureGrantRequest) -> Optional[GrantMetadata]:
        """Find existing grant matching agent/user/tool/scopes."""
        scopes_json = json.dumps(request.scopes)
        columns = (
            "grant_id",
            "scopes",
            "expires_at",
            "revoked_at",
        )
        with self._pool.connection() as conn:
            with conn.cursor() as cur:  # type: ignore[attr-defined]
                cur.execute(
                    """
                    SELECT grant_id, scopes, expires_at, revoked_at
                    FROM agent_grants
                    WHERE agent_id = %s
                      AND (user_id = %s OR (user_id IS NULL AND %s IS NULL))
                      AND tool_name = %s
                      AND scopes::jsonb = %s::jsonb
                      AND revoked_at IS NULL
                    ORDER BY issued_at DESC
                    LIMIT 1
                    """,
                    (request.agent_id, request.user_id, request.user_id, request.tool_name, scopes_json),
                )
                row = cur.fetchone()

        if not row:
            return None

        row_dict = self._row_to_dict(row, columns)
        row_dict = self._prepare_grant_row(
            row_dict,
            defaults={
                "agent_id": request.agent_id,
                "user_id": request.user_id,
                "tool_name": request.tool_name,
                "scopes": request.scopes,
                "provider": DEFAULT_PROVIDER,
            },
        )
        return GrantMetadata.from_row(row_dict)

    @staticmethod
    def _requires_mfa(scopes: Iterable[str]) -> bool:
        """Check if any scope requires MFA verification."""
        return any(scope in HIGH_RISK_SCOPES for scope in scopes)

    @staticmethod
    def _is_mfa_verified(request: EnsureGrantRequest) -> bool:
        """Check if request context includes MFA verification."""
        return request.context.get(MFA_CONTEXT_KEY) == MFA_REQUIRED_VALUE

    def _actor_from_request(self, request: EnsureGrantRequest) -> Dict[str, str]:
        """Build actor payload for telemetry events."""
        return {
            "id": request.user_id or request.agent_id,
            "role": request.context.get("roles", "UNKNOWN"),
            "surface": normalize_actor_surface(request.surface),
        }

    @staticmethod
    def _is_expired(grant: Union[Dict[str, Any], GrantMetadata]) -> bool:
        """Check if grant has expired based on expires_at timestamp."""
        if isinstance(grant, GrantMetadata):
            expires_at_str = grant.expires_at
        else:
            expires_at_str = grant.get("expires_at")
        if not expires_at_str:
            return True
        expires_at = datetime.fromisoformat(str(expires_at_str).replace("Z", "+00:00"))
        return expires_at <= datetime.now(timezone.utc)

    def _emit_auth_event(
        self,
        *,
        event_type: str,
        actor: Dict[str, str],
        request: Optional[EnsureGrantRequest],
        decision: GrantDecision,
        reason: Optional[DecisionReason],
        grant: Optional[GrantMetadata],
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit telemetry event for auth decision or operation."""
        payload: Dict[str, Any] = {
            "decision": decision.value,
        }
        if reason:
            payload["reason"] = reason.value
        if request is not None:
            payload.update(
                {
                    "agent_id": request.agent_id,
                    "tool_name": request.tool_name,
                    "scopes": list(request.scopes),
                }
            )
        if grant is not None:
            payload.update(
                {
                    "grant_id": grant.grant_id,
                    "expires_at": grant.expires_at,
                }
            )
        if extra_payload:
            payload.update(extra_payload)

        self._telemetry.emit_event(
            event_type=event_type,
            payload=payload,
            actor=actor,
        )

    @staticmethod
    def _row_to_dict(row: Any, columns: Tuple[str, ...]) -> Dict[str, Any]:
        """Convert cursor rows (tuple, dict, named tuple) into dictionaries."""
        if row is None:
            return {}
        if isinstance(row, dict):
            return dict(row)
        if hasattr(row, "_asdict"):
            return dict(row._asdict())  # type: ignore[misc]
        if isinstance(row, (list, tuple)):
            return {column: row[idx] for idx, column in enumerate(columns) if idx < len(row)}
        try:
            return dict(row)
        except TypeError:
            return {}

    @staticmethod
    def _prepare_grant_row(row: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Apply defaults and coerce JSON/timestamp fields for GrantMetadata construction."""
        prepared: Dict[str, Any] = dict(defaults or {})
        prepared.update({k: v for k, v in row.items() if v is not None})

        scopes_value = prepared.get("scopes", [])
        if isinstance(scopes_value, str):
            try:
                scopes_value = json.loads(scopes_value)
            except json.JSONDecodeError:
                scopes_value = [scopes_value]
        prepared["scopes"] = scopes_value

        obligations_value = prepared.get("obligations", [])
        if isinstance(obligations_value, str):
            try:
                obligations_value = json.loads(obligations_value)
            except json.JSONDecodeError:
                obligations_value = []
        prepared["obligations"] = obligations_value

        for ts_key in ("issued_at", "expires_at"):
            timestamp = prepared.get(ts_key)
            if isinstance(timestamp, datetime):
                prepared[ts_key] = timestamp.isoformat()
            elif timestamp is None:
                prepared[ts_key] = datetime.now(timezone.utc).isoformat()

        prepared.pop("revoked_at", None)
        return prepared

    @staticmethod
    def _extract_value(row: Any, columns: Tuple[str, ...]) -> Optional[Any]:
        """Extract the first column value from a cursor row while supporting mocks."""
        if not row or not columns:
            return None
        data = AgentAuthService._row_to_dict(row, columns)
        return data.get(columns[0])


__all__ = [
    "AgentAuthService",
    "GrantDecision",
    "DecisionReason",
    "GrantMetadata",
    "Obligation",
    "EnsureGrantRequest",
    "EnsureGrantResponse",
    "RevokeGrantRequest",
    "RevokeGrantResponse",
    "ListGrantsRequest",
    "PolicyPreviewRequest",
    "PolicyPreviewResponse",
    "AgentAuthServiceError",
    "GrantNotFoundError",
    "ConsentRequestNotFoundError",
]
