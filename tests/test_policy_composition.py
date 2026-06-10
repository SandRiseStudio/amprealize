"""Tests for GUIDEAI-1052 policy composition engine."""

from __future__ import annotations

import pytest

from amprealize.conversation_contracts import (
    ChatPermissionAction,
    ChatPermissionSurface,
)
from amprealize.policy_composition import (
    PolicyCompositionEngine,
    PolicyDecision,
    PolicyDirective,
    PolicyEvaluationRequest,
    PolicyLayer,
)
from amprealize.work_item_execution_contracts import (
    ExecutionPolicy,
    ToolPermissionLevel,
)

pytestmark = pytest.mark.unit


def test_most_restrictive_wins_denies_over_review_and_allow():
    engine = PolicyCompositionEngine()

    result = engine.evaluate(
        PolicyEvaluationRequest(
            request_id="req-1",
            directives=(
                PolicyDirective(
                    layer=PolicyLayer.USER,
                    decision=PolicyDecision.ALLOW,
                    reason="User may execute.",
                ),
                PolicyDirective(
                    layer=PolicyLayer.PROJECT,
                    decision=PolicyDecision.REVIEW,
                    reason="Project requires approval.",
                ),
                PolicyDirective(
                    layer=PolicyLayer.ORG,
                    decision=PolicyDecision.DENY,
                    reason="Org blocks this action.",
                ),
            ),
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert result.denied is True
    assert result.reasons == ("Org blocks this action.",)


def test_chat_execute_matrix_returns_review():
    engine = PolicyCompositionEngine()

    result = engine.evaluate(
        PolicyEvaluationRequest(
            request_id="req-2",
            chat_surface=ChatPermissionSurface.WORK_ITEM_THREAD,
            chat_action=ChatPermissionAction.EXECUTE,
        )
    )

    assert result.decision == PolicyDecision.REVIEW
    assert result.requires_review is True
    assert result.directives[0].source == "CHAT_PERMISSION_MATRIX"


def test_tool_permission_policy_contributes_mcp_tool_decision():
    engine = PolicyCompositionEngine()
    execution_policy = ExecutionPolicy(
        tool_permissions={"delete_file": ToolPermissionLevel.DENY}
    )

    result = engine.evaluate(
        PolicyEvaluationRequest(
            request_id="req-3",
            execution_policy=execution_policy,
            policy_context={"mcp_tool_name": "delete_file"},
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert result.directives[0].layer == PolicyLayer.MCP_TOOL


def test_sensitive_action_risk_requires_review():
    engine = PolicyCompositionEngine()

    result = engine.evaluate(
        PolicyEvaluationRequest(
            request_id="req-4",
            risk_classification="critical",
        )
    )

    assert result.decision == PolicyDecision.REVIEW
    assert "critical" in result.reasons[0]


def test_invalid_policy_context_fails_closed_with_audit_event():
    engine = PolicyCompositionEngine()

    result = engine.evaluate(
        PolicyEvaluationRequest(
            request_id="req-5",
            policy_context={"policy_decisions": {"not_a_layer": "allow"}},
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert result.failed_closed is True
    assert result.audit_events[0].event_type == "policy.composition.failed_closed"
