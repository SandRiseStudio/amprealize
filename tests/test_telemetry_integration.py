"""Telemetry integration tests covering ActionService, AgentAuth, and CLI instrumentation."""

from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from amprealize import cli
from amprealize.action_contracts import ActionCreateRequest, Actor, ReplayRequest
from amprealize.action_service import ActionService
from amprealize.agent_auth import AgentAuthClient, EnsureGrantRequest, GrantDecision
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient


class TelemetryIntegrationTests(unittest.TestCase):
    def test_action_service_emits_record_and_replay_events(self) -> None:
        sink = InMemoryTelemetrySink()
        telemetry = TelemetryClient(sink=sink)
        service = ActionService(telemetry=telemetry)

        actor = Actor(id="strategist-1", role="STRATEGIST", surface="CLI")
        request = ActionCreateRequest(
            artifact_path="docs/sample.md",
            summary="Sample action",
            behaviors_cited=["behavior_update_docs_after_changes"],
            metadata={"commands": ["amprealize record-action"]},
        )
        created = service.create_action(request, actor)

        replay_request = ReplayRequest(action_ids=[created.action_id])
        service.replay_actions(replay_request, actor)

        event_types = [event.event_type for event in sink.events]
        self.assertIn("action_recorded", event_types)
        self.assertIn("action_replay_start", event_types)
        self.assertIn("action_replay_complete", event_types)

        recorded_events = [event for event in sink.events if event.event_type == "action_recorded"]
        self.assertTrue(recorded_events)
        self.assertEqual(recorded_events[0].payload["artifact_path"], request.artifact_path)
        self.assertEqual(recorded_events[0].actor["surface"], "cli")

    def test_agent_auth_emits_decision_events(self) -> None:
        sink = InMemoryTelemetrySink()
        telemetry = TelemetryClient(sink=sink)
        client = AgentAuthClient(telemetry=telemetry)

        request = EnsureGrantRequest(
            agent_id="agent-cli",
            user_id="user-123",
            surface="CLI",
            tool_name="actions.list",
            scopes=["actions.read"],
        )
        response = client.ensure_grant(request)
        self.assertEqual(response.decision, GrantDecision.ALLOW)

        decision_events = [event for event in sink.events if event.event_type == "auth_grant_decision"]
        self.assertTrue(decision_events)
        self.assertEqual(decision_events[0].payload["decision"], GrantDecision.ALLOW.value)
        self.assertEqual(decision_events[0].payload["agent_id"], request.agent_id)
        self.assertEqual(decision_events[0].actor["surface"], "cli")


class TelemetryCLIEmitTests(unittest.TestCase):
    def test_cli_emit_persists_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            # Ensure we use the file sink by unsetting Postgres DSN
            old_dsn = os.environ.pop("AMPREALIZE_TELEMETRY_PG_DSN", None)
            os.environ["AMPREALIZE_TELEMETRY_PATH"] = str(path)
            try:
                args = argparse.Namespace(
                    event_type="behavior_retrieved",
                    payload=json.dumps({"result_count": 1}),
                    actor_id="vscode-user",
                    actor_role="DX",
                    actor_surface="VSCODE",
                    run_id=None,
                    action_id=None,
                    session_id="session-123",
                    format="json",
                    telemetry_command="emit",
                    command="telemetry",
                )
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = cli._command_telemetry_emit(args)

                self.assertEqual(exit_code, 0)
                stdout = buffer.getvalue()
                self.assertIn("behavior_retrieved", stdout)
                self.assertTrue(path.exists())
                lines = path.read_text(encoding="utf-8").strip().splitlines()
                self.assertTrue(lines)
                event = json.loads(lines[-1])
                self.assertEqual(event["event_type"], "behavior_retrieved")
                self.assertEqual(event["actor"]["surface"], "vscode")
                self.assertEqual(event["payload"]["result_count"], 1)
            finally:
                os.environ.pop("AMPREALIZE_TELEMETRY_PATH", None)
                if old_dsn:
                    os.environ["AMPREALIZE_TELEMETRY_PG_DSN"] = old_dsn


if __name__ == "__main__":
    unittest.main()
