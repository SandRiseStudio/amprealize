"""AgentAuth client stubs that mirror the documented contract artifacts.

The goal of this module is to provide lightweight in-memory implementations of the
AgentAuth flows described in `docs/AGENT_AUTH_ARCHITECTURE.md` while
consuming the proto/JSON schema artifacts shipped in the repository. These stubs
are used for parity tests and as a reference for downstream SDKs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .surfaces import normalize_actor_surface
from .telemetry import TelemetryClient


REPO_ROOT = Path(__file__).resolve().parent.parent

PROTO_PATH = REPO_ROOT / "schema" / "proto" / "agentauth" / "v1" / "agent_auth.proto"
REST_SCHEMA_PATH = REPO_ROOT / "schema" / "agentauth" / "v1" / "agent_auth.json"
SCOPE_CATALOG_PATH = REPO_ROOT / "schema" / "agentauth" / "scope_catalog.yaml"
POLICY_BUNDLE_PATH = REPO_ROOT / "schema" / "policy" / "agentauth" / "bundle.yaml"
MCP_TOOLS_DIR = REPO_ROOT / "mcp" / "tools"
MCP_AUTH_TOOL_NAMES: Tuple[str, ...] = (
    "auth.deviceLogin",
    "auth.authStatus",
    "auth.refreshToken",
    "auth.logout",
    "auth.ensureGrant",
    "auth.listGrants",
    "auth.policy.preview",
    "auth.revoke",
)


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

DEFAULT_PROVIDER = "amprealize.stubs"
DEFAULT_TTL = timedelta(minutes=60)

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Obligation:
    type: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class GrantMetadata:
    grant_id: str
    agent_id: str
    user_id: Optional[str]
    tool_name: str
    scopes: List[str]
    provider: str
    issued_at: str
    expires_at: str
    obligations: List[Obligation] = field(default_factory=list)


@dataclass
class EnsureGrantRequest:
    agent_id: str
    surface: str
    tool_name: str
    scopes: List[str]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: Optional[str] = None
    context: Dict[str, str] = field(default_factory=dict)
    policy_version: Optional[str] = None


@dataclass
class EnsureGrantResponse:
    decision: GrantDecision
    reason: Optional[DecisionReason] = None
    consent_url: Optional[str] = None
    consent_request_id: Optional[str] = None
    grant: Optional[GrantMetadata] = None
    audit_action_id: Optional[str] = None


@dataclass
class RevokeGrantRequest:
    grant_id: str
    revoked_by: str
    reason: Optional[str] = None


@dataclass
class RevokeGrantResponse:
    grant_id: str
    success: bool
    reason: Optional[DecisionReason] = None


@dataclass
class ListGrantsRequest:
    agent_id: str
    user_id: Optional[str] = None
    tool_name: Optional[str] = None
    include_expired: bool = False


@dataclass
class PolicyPreviewRequest:
    agent_id: str
    tool_name: str
    scopes: List[str]
    user_id: Optional[str] = None
    context: Dict[str, str] = field(default_factory=dict)
    bundle_version: Optional[str] = None


@dataclass
class PolicyPreviewResponse:
    decision: GrantDecision
    reason: Optional[DecisionReason] = None
    bundle_version: Optional[str] = None
    obligations: List[Obligation] = field(default_factory=list)


class AgentAuthError(Exception):
    """Base error for AgentAuth client operations."""


class ConsentRequestNotFoundError(AgentAuthError):
    """Raised when attempting to resolve an unknown consent request."""


class GrantNotFoundError(AgentAuthError):
    """Raised when a grant cannot be found for revocation."""


class AgentAuthClient:
    """In-memory AgentAuth client used for tests and SDK parity checks."""

    proto_path = PROTO_PATH
    rest_schema_path = REST_SCHEMA_PATH
    scope_catalog_path = SCOPE_CATALOG_PATH
    policy_bundle_path = POLICY_BUNDLE_PATH
    mcp_tool_names = MCP_AUTH_TOOL_NAMES
    mcp_tool_paths = tuple(MCP_TOOLS_DIR / f"{name}.json" for name in MCP_AUTH_TOOL_NAMES)

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        self._grants: Dict[str, GrantMetadata] = {}
        self._grant_index: Dict[Tuple[str, str, str, Tuple[str, ...]], str] = {}
        self._pending_consent: Dict[str, EnsureGrantRequest] = {}
        self._telemetry = telemetry or TelemetryClient.noop()

    # ------------------------------------------------------------------
    # Contract helpers
    # ------------------------------------------------------------------
    @staticmethod
    def load_rest_schema() -> Dict[str, object]:
        """Load the REST JSON schema definitions for external verification."""

        with REST_SCHEMA_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    # ------------------------------------------------------------------
    # Core RPC stubs
    # ------------------------------------------------------------------
    def ensure_grant(self, request: EnsureGrantRequest) -> EnsureGrantResponse:
        """Evaluate the incoming grant request and return a decision."""

        key = self._grant_key(request.agent_id, request.user_id, request.tool_name, request.scopes)
        actor_payload = self._actor_from_request(request)
        requires_mfa = self._requires_mfa(request.scopes)
        mfa_verified = self._is_mfa_verified(request)

        # Return existing grant when still valid.
        existing = self._grants.get(self._grant_index.get(key, ""))
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
                grant=self._clone_grant(existing),
                audit_action_id=str(uuid.uuid4()),
            )

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

        if any(scope in CONSENT_SCOPE_TRIGGERS for scope in request.scopes):
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

        grant = self._issue_grant(request, requires_mfa=requires_mfa)
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
        """Finalize a pending consent request and issue a grant."""

        if consent_request_id not in self._pending_consent:
            raise ConsentRequestNotFoundError(f"Consent request '{consent_request_id}' not found")

        request = self._pending_consent.pop(consent_request_id)
        request.context["approved_by"] = approver
        requires_mfa = self._requires_mfa(request.scopes)
        grant = self._issue_grant(request, requires_mfa=requires_mfa)
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
        """Revoke an existing grant."""

        grant = self._grants.get(request.grant_id)
        if not grant:
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
            return RevokeGrantResponse(
                grant_id=request.grant_id,
                success=False,
                reason=DecisionReason.SCOPE_NOT_APPROVED,
            )

        key = self._grant_key(grant.agent_id, grant.user_id, grant.tool_name, grant.scopes)
        self._grants.pop(request.grant_id, None)
        self._grant_index.pop(key, None)
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
            grant=self._clone_grant(grant),
            extra_payload={
                "grant_id": request.grant_id,
                "status": "REVOKED",
                "revocation_reason": request.reason,
            },
        )
        return RevokeGrantResponse(grant_id=request.grant_id, success=True)

    def list_grants(self, request: ListGrantsRequest) -> List[GrantMetadata]:
        """Return grants filtered by agent/user/tool, optionally including expired grants."""

        def predicate(grant: GrantMetadata) -> bool:
            if request.agent_id and grant.agent_id != request.agent_id:
                return False
            if request.user_id is not None and grant.user_id != request.user_id:
                return False
            if request.tool_name and grant.tool_name != request.tool_name:
                return False
            if not request.include_expired and self._is_expired(grant):
                return False
            return True

        return [self._clone_grant(grant) for grant in self._grants.values() if predicate(grant)]

    def policy_preview(self, request: PolicyPreviewRequest) -> PolicyPreviewResponse:
        """Dry-run a policy decision without mutating stored grants."""

        contains_high_risk = any(scope in CONSENT_SCOPE_TRIGGERS for scope in request.scopes)
        requires_mfa = any(scope in HIGH_RISK_SCOPES for scope in request.scopes)
        mfa_verified = request.context.get(MFA_CONTEXT_KEY) == MFA_REQUIRED_VALUE
        roles = {
            role.strip().upper()
            for role in request.context.get("roles", "").split(",")
            if role.strip()
        }

        actor_payload = {
            "id": request.user_id or request.agent_id,
            "role": request.context.get("roles", "UNKNOWN"),
            "surface": normalize_actor_surface(request.context.get("surface", "API")),
        }

        if requires_mfa and not mfa_verified:
            response = PolicyPreviewResponse(
                decision=GrantDecision.DENY,
                reason=DecisionReason.SECURITY_HOLD,
                bundle_version=request.bundle_version,
            )
        elif contains_high_risk and "ADMIN" not in roles and "STRATEGIST" not in roles:
            response = PolicyPreviewResponse(
                decision=GrantDecision.DENY,
                reason=DecisionReason.POLICY_CONDITION_FAILED,
                bundle_version=request.bundle_version,
            )
        elif contains_high_risk:
            response = PolicyPreviewResponse(
                decision=GrantDecision.CONSENT_REQUIRED,
                reason=DecisionReason.SCOPE_NOT_APPROVED,
                bundle_version=request.bundle_version,
                obligations=[
                    Obligation(type="notification", attributes={"channel": "#agent-reviews"}),
                    *(
                        [Obligation(type="mfa", attributes={"method": "TOTP"})]
                        if requires_mfa
                        else []
                    ),
                ],
            )
        else:
            response = PolicyPreviewResponse(
                decision=GrantDecision.ALLOW,
                bundle_version=request.bundle_version,
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
                "bundle_version": request.bundle_version,
                "mfa_required": requires_mfa,
            },
        )

        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _issue_grant(self, request: EnsureGrantRequest, *, requires_mfa: bool = False) -> GrantMetadata:
        issued_at = _now_utc()
        expires_at = issued_at + DEFAULT_TTL
        grant_id = str(uuid.uuid4())
        obligations: List[Obligation] = []
        if any(scope in CONSENT_SCOPE_TRIGGERS for scope in request.scopes):
            obligations.append(
                Obligation(type="notification", attributes={"channel": "#agent-reviews"})
            )
        if requires_mfa:
            obligations.append(
                Obligation(type="mfa", attributes={"method": "TOTP"})
            )

        grant = GrantMetadata(
            grant_id=grant_id,
            agent_id=request.agent_id,
            user_id=request.user_id,
            tool_name=request.tool_name,
            scopes=list(request.scopes),
            provider=DEFAULT_PROVIDER,
            issued_at=_isoformat(issued_at),
            expires_at=_isoformat(expires_at),
            obligations=obligations,
        )

        key = self._grant_key(request.agent_id, request.user_id, request.tool_name, request.scopes)
        self._grants[grant_id] = grant
        self._grant_index[key] = grant_id
        return self._clone_grant(grant)

    @staticmethod
    def _requires_mfa(scopes: Iterable[str]) -> bool:
        return any(scope in HIGH_RISK_SCOPES for scope in scopes)

    @staticmethod
    def _is_mfa_verified(request: EnsureGrantRequest) -> bool:
        return request.context.get(MFA_CONTEXT_KEY) == MFA_REQUIRED_VALUE

    def _actor_from_request(self, request: EnsureGrantRequest) -> Dict[str, str]:
        return {
            "id": request.user_id or request.agent_id,
            "role": request.context.get("roles", "UNKNOWN"),
            "surface": normalize_actor_surface(request.surface),
        }

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
    def _grant_key(
        agent_id: str,
        user_id: Optional[str],
        tool_name: str,
        scopes: Iterable[str],
    ) -> Tuple[str, str, str, Tuple[str, ...]]:
        normalized_scopes = tuple(sorted(scopes))
        return agent_id, user_id or "", tool_name, normalized_scopes

    @staticmethod
    def _is_expired(grant: GrantMetadata) -> bool:
        expires_at = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        return expires_at <= _now_utc()

    @staticmethod
    def _clone_grant(grant: GrantMetadata) -> GrantMetadata:
        return GrantMetadata(
            grant_id=grant.grant_id,
            agent_id=grant.agent_id,
            user_id=grant.user_id,
            tool_name=grant.tool_name,
            scopes=list(grant.scopes),
            provider=grant.provider,
            issued_at=grant.issued_at,
            expires_at=grant.expires_at,
            obligations=[Obligation(type=o.type, attributes=dict(o.attributes)) for o in grant.obligations],
        )


__all__ = [
    "AgentAuthClient",
    "GrantDecision",
    "DecisionReason",
    "GrantMetadata",
    "EnsureGrantRequest",
    "EnsureGrantResponse",
    "RevokeGrantRequest",
    "RevokeGrantResponse",
    "ListGrantsRequest",
    "PolicyPreviewRequest",
    "PolicyPreviewResponse",
    "Obligation",
    "ConsentRequestNotFoundError",
    "GrantNotFoundError",
]
