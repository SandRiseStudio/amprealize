"""Parity tests ensuring ActionService stubs behave consistently across surfaces."""

from __future__ import annotations

import unittest

from amprealize.action_service import ActionService
from amprealize.adapters import (
    CLIActionServiceAdapter,
    MCPActionServiceAdapter,
    RestActionServiceAdapter,
)


class ActionServiceParityTests(unittest.TestCase):
    def setUp(self) -> None:
        service = ActionService()
        self.cli = CLIActionServiceAdapter(service)
        self.rest = RestActionServiceAdapter(service)
        self.mcp = MCPActionServiceAdapter(service)
        self.actor_id = "user-strategist"
        self.actor_role = "STRATEGIST"

    def _create_action_via_cli(self, suffix: str) -> dict:
        return self.cli.record_action(
            artifact_path=f"docs/sample-{suffix}.md",
            summary=f"Sample action {suffix}",
            behaviors_cited=["behavior_wire_cli_to_orchestrator"],
            metadata={"commands": ["amprealize record-action"]},
            actor_id=self.actor_id,
            actor_role=self.actor_role,
        )

    def test_get_action_parity_across_surfaces(self) -> None:
        created = self._create_action_via_cli("one")
        action_id = created["action_id"]

        rest_record = self.rest.get_action(action_id)
        mcp_record = self.mcp.get(action_id)

        self.assertDictEqual(rest_record, created)
        self.assertDictEqual(mcp_record, created)

    def test_list_actions_consistent_ordering(self) -> None:
        created_ids = [self._create_action_via_cli(str(index))["action_id"] for index in range(3)]

        cli_list = self.cli.list_actions()
        rest_list = self.rest.list_actions()
        mcp_list = self.mcp.list()

        self.assertEqual([item["action_id"] for item in cli_list], created_ids)
        self.assertEqual(cli_list, rest_list)
        self.assertEqual(cli_list, mcp_list)

    def test_audit_log_event_id_propagates_across_surfaces(self) -> None:
        created = self.cli.record_action(
            artifact_path="docs/audit.md",
            summary="Action with audit link",
            behaviors_cited=["behavior_update_docs_after_changes"],
            metadata={},
            actor_id=self.actor_id,
            actor_role=self.actor_role,
            audit_log_event_id="11111111-1111-4111-8111-111111111111",
        )

        action_id = created["action_id"]
        rest_record = self.rest.get_action(action_id)
        mcp_record = self.mcp.get(action_id)

        self.assertEqual(created["audit_log_event_id"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(rest_record["audit_log_event_id"], created["audit_log_event_id"])
        self.assertEqual(mcp_record["audit_log_event_id"], created["audit_log_event_id"])

    def test_replay_updates_action_status(self) -> None:
        action_ids = [self._create_action_via_cli(str(index))["action_id"] for index in range(2)]

        replay_payload = {
            "action_ids": action_ids,
            "actor": {"id": self.actor_id, "role": self.actor_role},
            "strategy": "SEQUENTIAL",
            "options": {"skip_existing": False, "dry_run": False},
        }
        replay_result = self.rest.replay_actions(replay_payload)

        self.assertEqual(replay_result["status"], "SUCCEEDED")
        self.assertAlmostEqual(replay_result["progress"], 1.0)
        self.assertFalse(replay_result["failed_action_ids"])

        for action_id in action_ids:
            action = self.cli.get_action(action_id)
            self.assertEqual(action["replay_status"], "SUCCEEDED")

    def test_replay_enriched_metadata(self) -> None:
        """Verify replay jobs capture action lists, audit URNs, actor metadata, and timestamps."""
        action_ids = [self._create_action_via_cli(str(index))["action_id"] for index in range(3)]

        replay_payload = {
            "action_ids": action_ids,
            "actor": {"id": self.actor_id, "role": self.actor_role, "surface": "cli"},
            "strategy": "SEQUENTIAL",
            "options": {"skip_existing": False, "dry_run": False},
        }
        replay_result = self.rest.replay_actions(replay_payload)

        # Validate enriched fields
        self.assertIn("replay_id", replay_result)
        self.assertIn("action_ids", replay_result)
        self.assertIn("completed_action_ids", replay_result)
        self.assertIn("audit_log_event_id", replay_result)
        self.assertIn("strategy", replay_result)
        self.assertIn("created_at", replay_result)
        self.assertIn("started_at", replay_result)
        self.assertIn("completed_at", replay_result)
        self.assertIn("actor_id", replay_result)
        self.assertIn("actor_role", replay_result)
        self.assertIn("actor_surface", replay_result)

        # Validate field contents
        self.assertEqual(replay_result["action_ids"], action_ids)
        self.assertEqual(len(replay_result["completed_action_ids"]), 3)
        self.assertTrue(replay_result["audit_log_event_id"].startswith("urn:amprealize:audit:replay:"))
        self.assertEqual(replay_result["strategy"], "SEQUENTIAL")
        self.assertEqual(replay_result["actor_id"], self.actor_id)
        self.assertEqual(replay_result["actor_role"], self.actor_role)
        self.assertEqual(replay_result["actor_surface"], "CLI")
        self.assertIsNotNone(replay_result["created_at"])
        self.assertIsNotNone(replay_result["started_at"])
        self.assertIsNotNone(replay_result["completed_at"])

        # Validate via get_replay_status
        replay_id = replay_result["replay_id"]
        status_result = self.rest.get_replay_status(replay_id)
        self.assertEqual(status_result["action_ids"], action_ids)
        self.assertEqual(status_result["audit_log_event_id"], replay_result["audit_log_event_id"])
        self.assertEqual(status_result["actor_id"], self.actor_id)

    def test_checksum_auto_calculation(self) -> None:
        action = self.cli.record_action(
            artifact_path="docs/capability_matrix.md",
            summary="Document capability matrix",
            behaviors_cited=["behavior_update_docs_after_changes"],
            metadata={},
            actor_id=self.actor_id,
            actor_role=self.actor_role,
        )
        self.assertTrue(action["checksum"])


if __name__ == "__main__":
    unittest.main()
