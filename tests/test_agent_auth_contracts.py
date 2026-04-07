"""Contract tests covering the AgentAuth SDK stubs and artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict
import unittest
from typing import Any, Mapping, cast

from amprealize.agent_auth import (
    AgentAuthClient,
    ConsentRequestNotFoundError,
    DecisionReason,
    EnsureGrantRequest,
    GrantDecision,
    ListGrantsRequest,
    MCP_AUTH_TOOL_NAMES,
    PolicyPreviewRequest,
    RevokeGrantRequest,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient


class AgentAuthContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.telemetry_sink = InMemoryTelemetrySink()
        self.client = AgentAuthClient(telemetry=TelemetryClient(sink=self.telemetry_sink))

    # ------------------------------------------------------------------
    # Artifact validation
    # ------------------------------------------------------------------
    def test_proto_contains_required_rpcs(self) -> None:
        proto_contents = AgentAuthClient.proto_path.read_text(encoding="utf-8")
        for rpc_name in ["EnsureGrant", "RevokeGrant", "ListGrants", "PolicyPreview"]:
            self.assertIn(f"rpc {rpc_name}", proto_contents)

    def test_rest_schema_definitions_present(self) -> None:
        schema = AgentAuthClient.load_rest_schema()
        self.assertIn("definitions", schema)
        definitions_obj = schema["definitions"]
        self.assertIsInstance(definitions_obj, dict)
        definitions = cast(Mapping[str, Any], definitions_obj)
        self.assertIn("EnsureGrantRequest", definitions)
        self.assertIn("GrantMetadata", definitions)

    def test_mcp_tool_contracts_exist(self) -> None:
        tool_names = [json.loads(path.read_text(encoding="utf-8"))["name"] for path in AgentAuthClient.mcp_tool_paths]
        self.assertCountEqual(
            tool_names,
            list(MCP_AUTH_TOOL_NAMES),
        )

    def test_scope_catalog_lists_expected_scopes(self) -> None:
        catalog_text = AgentAuthClient.scope_catalog_path.read_text(encoding="utf-8")
        self.assertIn("actions.replay", catalog_text)
        self.assertIn("agentauth.grant", catalog_text)
        self.assertIn("agentauth.manage", catalog_text)

    # ------------------------------------------------------------------
    # Client stub behavior
    # ------------------------------------------------------------------
    def test_allow_decision_for_low_risk_scopes(self) -> None:
        request = EnsureGrantRequest(
            agent_id="agent-cli",
            user_id="user-123",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
        )
        response = self.client.ensure_grant(request)
        self.assertEqual(response.decision, GrantDecision.ALLOW)
        self.assertIsNotNone(response.grant)
        self.assertIsNotNone(response.audit_action_id)
        initial_grant = response.grant
        assert initial_grant is not None

        # Grant should be returned on subsequent calls without new issuance.
        repeat = self.client.ensure_grant(request)
        self.assertEqual(repeat.decision, GrantDecision.ALLOW)
        self.assertIsNotNone(repeat.grant)
        repeat_grant = repeat.grant
        assert repeat_grant is not None
        self.assertEqual(repeat_grant.grant_id, initial_grant.grant_id)

    def test_consent_flow_for_high_risk_scope(self) -> None:
        request = EnsureGrantRequest(
            agent_id="agent-cli",
            user_id="user-123",
            surface="CLI",
            tool_name="actions.replay",
            scopes=["actions.replay"],
        )
        denied = self.client.ensure_grant(request)
        self.assertEqual(denied.decision, GrantDecision.DENY)
        self.assertEqual(denied.reason, DecisionReason.SECURITY_HOLD)

        mfa_request = EnsureGrantRequest(
            agent_id="agent-cli",
            user_id="user-123",
            surface="CLI",
            tool_name="actions.replay",
            scopes=["actions.replay"],
            context={"mfa_verified": "true"},
        )
        response = self.client.ensure_grant(mfa_request)
        self.assertEqual(response.decision, GrantDecision.CONSENT_REQUIRED)
        self.assertEqual(response.reason, DecisionReason.SCOPE_NOT_APPROVED)
        self.assertIsNotNone(response.consent_request_id)
        self.assertIn("/consent/", response.consent_url or "")
        consent_request_id = response.consent_request_id
        assert consent_request_id is not None

        # Approve the consent and ensure subsequent calls allow execution.
        grant = self.client.approve_consent(consent_request_id, approver="admin-user")
        self.assertEqual(grant.agent_id, mfa_request.agent_id)

        allowed = self.client.ensure_grant(request)
        self.assertEqual(allowed.decision, GrantDecision.ALLOW)
        self.assertIsNotNone(allowed.grant)
        allowed_grant = allowed.grant
        assert allowed_grant is not None
        self.assertEqual(allowed_grant.grant_id, grant.grant_id)
        self.assertTrue(any(obligation.type == "mfa" for obligation in allowed_grant.obligations))

        decision_events = [
            event for event in self.telemetry_sink.events if event.event_type == "auth_grant_decision"
        ]
        self.assertTrue(any(event.payload["decision"] == GrantDecision.DENY.value for event in decision_events))
        self.assertTrue(any(event.payload.get("mfa_required") for event in decision_events))

        consent_events = [
            event for event in self.telemetry_sink.events if event.event_type == "auth_consent_approved"
        ]
        self.assertEqual(len(consent_events), 1)
        self.assertTrue(consent_events[0].payload.get("mfa_required"))

    def test_revoking_grants_updates_listing(self) -> None:
        request = EnsureGrantRequest(
            agent_id="agent-cli",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
        )
        grant = self.client.ensure_grant(request).grant
        self.assertIsNotNone(grant)
        assert grant is not None

        grants = self.client.list_grants(ListGrantsRequest(agent_id="agent-cli"))
        self.assertEqual(len(grants), 1)

        response = self.client.revoke_grant(RevokeGrantRequest(grant_id=grant.grant_id, revoked_by="admin"))
        self.assertTrue(response.success)

        grants_after = self.client.list_grants(ListGrantsRequest(agent_id="agent-cli"))
        self.assertFalse(grants_after)

        failure = self.client.revoke_grant(RevokeGrantRequest(grant_id="missing", revoked_by="admin"))
        self.assertFalse(failure.success)
        self.assertEqual(failure.reason, DecisionReason.SCOPE_NOT_APPROVED)

    def test_policy_preview_mirrors_bundle_rules(self) -> None:
        deny_request = PolicyPreviewRequest(
            agent_id="agent-cli",
            tool_name="actions.replay",
            scopes=["actions.replay"],
            context={"roles": "STUDENT", "mfa_verified": "true"},
        )
        denied = self.client.policy_preview(deny_request)
        self.assertEqual(denied.decision, GrantDecision.DENY)
        self.assertEqual(denied.reason, DecisionReason.POLICY_CONDITION_FAILED)

        consent_request = PolicyPreviewRequest(
            agent_id="agent-cli",
            tool_name="actions.replay",
            scopes=["actions.replay"],
            context={"roles": "Strategist", "mfa_verified": "true"},
        )
        consent = self.client.policy_preview(consent_request)
        self.assertEqual(consent.decision, GrantDecision.CONSENT_REQUIRED)
        self.assertEqual(consent.reason, DecisionReason.SCOPE_NOT_APPROVED)
        self.assertTrue(consent.obligations)
        self.assertTrue(any(obligation.type == "mfa" for obligation in consent.obligations))

        allow_request = PolicyPreviewRequest(
            agent_id="agent-cli",
            tool_name="actions.list",
            scopes=["actions.read"],
        )
        allowed = self.client.policy_preview(allow_request)
        self.assertEqual(allowed.decision, GrantDecision.ALLOW)

    def test_approving_unknown_consent_raises(self) -> None:
        with self.assertRaises(ConsentRequestNotFoundError):
            self.client.approve_consent("missing", approver="admin")

    def test_export_grants_are_serializable(self) -> None:
        request = EnsureGrantRequest(
            agent_id="agent-cli",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
        )
        grant = self.client.ensure_grant(request).grant
        self.assertIsNotNone(grant)
        assert grant is not None
        payload = asdict(grant)
        self.assertIsInstance(payload, dict)


if __name__ == "__main__":
    unittest.main()
