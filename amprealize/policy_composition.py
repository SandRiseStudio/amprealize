"""Policy composition engine for governed agent execution.

GUIDEAI-1052: evaluates user, org, project, conversation, agent, MCP/tool,
attachment, and action-risk policy signals using most-restrictive-wins
semantics. The engine is deliberately side-effect free; callers emit or persist
the returned audit events through their own telemetry/audit services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .conversation_contracts import (
    ChatPermissionAction,
    ChatPermissionEffect,
    ChatPermissionSurface,
    get_chat_permission_requirement,
)
from .work_item_execution_contracts import ExecutionPolicy, ToolPermissionLevel


class PolicyDecision(str, Enum):
    """Runtime policy decision returned by the composition engine."""

    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


class PolicyLayer(str, Enum):
    """Policy layer participating in most-restrictive-wins composition."""

    USER = "user"
    ORG = "org"
    PROJECT = "project"
    CONVERSATION = "conversation"
    AGENT = "agent"
    MCP_TOOL = "mcp_tool"
    ATTACHMENT = "attachment"
    ACTION_RISK = "action_risk"
    CHAT_MATRIX = "chat_matrix"
    BASELINE = "baseline"


_DECISION_RANK = {
    PolicyDecision.ALLOW: 0,
    PolicyDecision.REVIEW: 1,
    PolicyDecision.DENY: 2,
}

_DENY_RISKS = frozenset({"deny", "denied", "blocked", "prohibited"})
_REVIEW_RISKS = frozenset(
    {
        "review",
        "requires_review",
        "approval",
        "high",
        "critical",
        "sensitive",
        "destructive",
        "mutation",
    }
)


@dataclass(frozen=True)
class PolicyDirective:
    """Single policy signal from one layer."""

    layer: PolicyLayer
    decision: PolicyDecision
    reason: str = ""
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(
        cls,
        *,
        layer: str | PolicyLayer,
        decision: str | PolicyDecision,
        reason: str = "",
        source: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "PolicyDirective":
        return cls(
            layer=layer if isinstance(layer, PolicyLayer) else PolicyLayer(layer),
            decision=(
                decision
                if isinstance(decision, PolicyDecision)
                else PolicyDecision(decision)
            ),
            reason=reason,
            source=source,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.value,
            "decision": self.decision.value,
            "reason": self.reason,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PolicyAuditEvent:
    """Audit event produced by policy evaluation."""

    event_type: str
    decision: PolicyDecision
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "decision": self.decision.value,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PolicyEvaluationRequest:
    """Input to the policy composition engine."""

    request_id: str
    user_id: str = ""
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    chat_surface: Optional[ChatPermissionSurface] = None
    chat_action: Optional[ChatPermissionAction] = None
    risk_classification: Optional[str] = None
    policy_context: Dict[str, Any] = field(default_factory=dict)
    directives: Sequence[PolicyDirective] = field(default_factory=tuple)
    execution_policy: Optional[ExecutionPolicy] = None


@dataclass(frozen=True)
class PolicyEvaluationResult:
    """Most-restrictive policy evaluation output."""

    decision: PolicyDecision
    directives: Sequence[PolicyDirective]
    reasons: Sequence[str]
    audit_events: Sequence[PolicyAuditEvent]
    failed_closed: bool = False

    @property
    def requires_review(self) -> bool:
        return self.decision == PolicyDecision.REVIEW

    @property
    def denied(self) -> bool:
        return self.decision == PolicyDecision.DENY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "failed_closed": self.failed_closed,
            "reasons": list(self.reasons),
            "directives": [directive.to_dict() for directive in self.directives],
            "audit_events": [event.to_dict() for event in self.audit_events],
        }


class PolicyCompositionEngine:
    """Compose policy signals with deny > review > allow precedence."""

    def evaluate(self, request: PolicyEvaluationRequest) -> PolicyEvaluationResult:
        try:
            directives = list(request.directives)
            directives.extend(self._directives_from_chat_matrix(request))
            directives.extend(
                self._directives_from_policy_context(request.policy_context)
            )
            directives.extend(self._directives_from_tool_policy(request))
            directives.extend(self._directives_from_action_risk(request))

            if not directives:
                directives.append(
                    PolicyDirective(
                        layer=PolicyLayer.BASELINE,
                        decision=PolicyDecision.ALLOW,
                        reason="No restrictive policy signals were supplied.",
                        source="policy_composition_engine",
                    )
                )

            decision = max(
                directives, key=lambda item: _DECISION_RANK[item.decision]
            ).decision
            reasons = [
                directive.reason
                or f"{directive.layer.value} returned {directive.decision.value}"
                for directive in directives
                if directive.decision == decision
            ]
            audit_events = [
                PolicyAuditEvent(
                    event_type="policy.composition.evaluated",
                    decision=decision,
                    message="Policy composition completed.",
                    metadata={
                        "request_id": request.request_id,
                        "layers": [directive.layer.value for directive in directives],
                        "reasons": reasons,
                    },
                )
            ]
            return PolicyEvaluationResult(
                decision=decision,
                directives=tuple(directives),
                reasons=tuple(reasons),
                audit_events=tuple(audit_events),
            )
        except Exception as exc:
            directive = PolicyDirective(
                layer=PolicyLayer.BASELINE,
                decision=PolicyDecision.DENY,
                reason=f"Policy evaluation failed closed: {exc}",
                source="policy_composition_engine",
            )
            audit_event = PolicyAuditEvent(
                event_type="policy.composition.failed_closed",
                decision=PolicyDecision.DENY,
                message="Policy evaluation failed closed.",
                metadata={"request_id": request.request_id, "error": str(exc)},
            )
            return PolicyEvaluationResult(
                decision=PolicyDecision.DENY,
                directives=(directive,),
                reasons=(directive.reason,),
                audit_events=(audit_event,),
                failed_closed=True,
            )

    def _directives_from_chat_matrix(
        self,
        request: PolicyEvaluationRequest,
    ) -> Iterable[PolicyDirective]:
        if not request.chat_surface or not request.chat_action:
            return ()

        requirement = get_chat_permission_requirement(
            request.chat_surface,
            request.chat_action,
        )
        if requirement.effect == ChatPermissionEffect.DENY:
            decision = PolicyDecision.DENY
        elif requirement.effect == ChatPermissionEffect.REQUIRE_APPROVAL:
            decision = PolicyDecision.REVIEW
        else:
            decision = PolicyDecision.ALLOW

        return (
            PolicyDirective(
                layer=PolicyLayer.CHAT_MATRIX,
                decision=decision,
                reason=requirement.notes
                or (
                    f"{requirement.surface.value}.{requirement.action.value} "
                    f"requires {decision.value}"
                ),
                source="CHAT_PERMISSION_MATRIX",
                metadata={
                    "surface": requirement.surface.value,
                    "action": requirement.action.value,
                    "scopes": [scope.value for scope in requirement.scopes],
                },
            ),
        )

    def _directives_from_policy_context(
        self,
        policy_context: Mapping[str, Any],
    ) -> Iterable[PolicyDirective]:
        directives: List[PolicyDirective] = []
        layer_decisions = policy_context.get("policy_decisions") or {}
        if isinstance(layer_decisions, Mapping):
            for layer, raw_decision in layer_decisions.items():
                if isinstance(raw_decision, Mapping):
                    directives.append(
                        PolicyDirective.from_raw(
                            layer=layer,
                            decision=raw_decision.get("decision"),
                            reason=str(raw_decision.get("reason", "")),
                            source=str(raw_decision.get("source", "policy_context")),
                            metadata=raw_decision.get("metadata") or {},
                        )
                    )
                else:
                    directives.append(
                        PolicyDirective.from_raw(
                            layer=layer,
                            decision=raw_decision,
                            source="policy_context",
                        )
                    )

        raw_policies = policy_context.get("policies") or ()
        if isinstance(raw_policies, Sequence) and not isinstance(
            raw_policies, (str, bytes)
        ):
            for raw_policy in raw_policies:
                if not isinstance(raw_policy, Mapping):
                    continue
                directives.append(
                    PolicyDirective.from_raw(
                        layer=raw_policy.get("layer"),
                        decision=raw_policy.get("decision"),
                        reason=str(raw_policy.get("reason", "")),
                        source=str(raw_policy.get("source", "policy_context")),
                        metadata=raw_policy.get("metadata") or {},
                    )
                )

        if policy_context.get("sensitive_operation") is True:
            directives.append(
                PolicyDirective(
                    layer=PolicyLayer.ACTION_RISK,
                    decision=PolicyDecision.REVIEW,
                    reason="Sensitive operation requires explicit review.",
                    source="policy_context",
                )
            )

        return tuple(directives)

    def _directives_from_tool_policy(
        self,
        request: PolicyEvaluationRequest,
    ) -> Iterable[PolicyDirective]:
        tool_name = request.policy_context.get(
            "mcp_tool_name"
        ) or request.policy_context.get("tool_name")
        if not tool_name or not request.execution_policy:
            return ()

        permission = request.execution_policy.tool_permissions.get(str(tool_name))
        if permission is None:
            return ()
        if permission == ToolPermissionLevel.DENY:
            decision = PolicyDecision.DENY
            reason = f"Tool policy denies {tool_name}."
        elif permission == ToolPermissionLevel.REQUIRE_CONFIRMATION:
            decision = PolicyDecision.REVIEW
            reason = f"Tool policy requires review for {tool_name}."
        else:
            decision = PolicyDecision.ALLOW
            reason = f"Tool policy allows {tool_name}."

        return (
            PolicyDirective(
                layer=PolicyLayer.MCP_TOOL,
                decision=decision,
                reason=reason,
                source="execution_policy.tool_permissions",
                metadata={"tool_name": str(tool_name)},
            ),
        )

    def _directives_from_action_risk(
        self,
        request: PolicyEvaluationRequest,
    ) -> Iterable[PolicyDirective]:
        raw_risk = request.risk_classification or request.policy_context.get(
            "action_risk"
        )
        if not raw_risk:
            return ()

        risk = str(raw_risk).lower()
        if risk in _DENY_RISKS:
            decision = PolicyDecision.DENY
            reason = f"Action risk classification '{raw_risk}' is denied."
        elif risk in _REVIEW_RISKS:
            decision = PolicyDecision.REVIEW
            reason = f"Action risk classification '{raw_risk}' requires review."
        else:
            decision = PolicyDecision.ALLOW
            reason = f"Action risk classification '{raw_risk}' allows execution."

        return (
            PolicyDirective(
                layer=PolicyLayer.ACTION_RISK,
                decision=decision,
                reason=reason,
                source="risk_classification",
                metadata={"risk_classification": str(raw_risk)},
            ),
        )


def build_execution_policy_request(
    *,
    request_id: str,
    user_id: str = "",
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    risk_classification: Optional[str] = None,
    policy_context: Optional[Mapping[str, Any]] = None,
    execution_policy: Optional[ExecutionPolicy] = None,
) -> PolicyEvaluationRequest:
    """Build a policy request from execution gateway context."""

    context = dict(policy_context or {})
    chat_surface = _coerce_enum(
        context.get("chat_surface"),
        ChatPermissionSurface,
    )
    chat_action = _coerce_enum(
        context.get("chat_action"),
        ChatPermissionAction,
    )
    return PolicyEvaluationRequest(
        request_id=request_id,
        user_id=user_id,
        org_id=org_id,
        project_id=project_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        chat_surface=chat_surface,
        chat_action=chat_action,
        risk_classification=risk_classification,
        policy_context=context,
        execution_policy=execution_policy,
    )


def _coerce_enum(value: Any, enum_type: type[Enum]) -> Optional[Enum]:
    if value is None:
        return None
    if isinstance(value, enum_type):
        return value
    return enum_type(str(value))
