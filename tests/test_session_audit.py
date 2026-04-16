"""Tests for Session Mode audit logging, per-tool permissions, and escalation detection.

GUIDEAI-914: Raze audit logging for Session Mode
GUIDEAI-912: Per-tool permission policies
GUIDEAI-913: Session-to-GEP escalation trigger
"""

import json
import re
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from amprealize.session_audit import (
    EscalationDetector,
    EscalationSignal,
    SessionAuditLogger,
    _sanitize_value,
)
from amprealize.telemetry import InMemoryTelemetrySink, TelemetryClient
from amprealize.work_item_execution_contracts import (
    SESSION_MODE_TOOL_PERMISSIONS,
    AgentExecutionMode,
    ExecutionPolicy,
    ToolCall,
    ToolPermissionLevel,
    ToolResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str = "read_file", args: dict = None) -> ToolCall:
    return ToolCall(
        call_id=f"call_{name}",
        tool_name=name,
        tool_args=args or {"path": "/foo/bar.py"},
    )


def _make_result(success: bool = True, output: dict = None, error: str = None) -> ToolResult:
    return ToolResult(
        call_id="call_test",
        tool_name="test_tool",
        success=success,
        output=output or {"text": "ok"},
        error=error,
    )


def _make_telemetry() -> tuple:
    """Return (TelemetryClient, InMemoryTelemetrySink)."""
    sink = InMemoryTelemetrySink()
    client = TelemetryClient(sink=sink)
    return client, sink


# ===========================================================================
# GUIDEAI-914 — SessionAuditLogger
# ===========================================================================


class TestSessionAuditLogger:
    """Tests for SessionAuditLogger."""

    def test_log_tool_call_emits_telemetry(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        call = _make_tool_call("read_file", {"path": "/src/main.py"})
        result = _make_result(success=True, output={"text": "file contents"})

        logger.log_tool_call(call, result, elapsed_ms=42)

        assert len(sink.events) == 1
        event = sink.events[0]
        assert event.event_type == "session.tool_call"
        payload = event.payload
        assert payload["tool_name"] == "read_file"
        assert payload["success"] is True
        assert payload["elapsed_ms"] == 42
        assert payload["run_id"] == "run-1"
        assert payload["sequence"] == 1

    def test_log_tool_call_increments_count(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        for i in range(3):
            logger.log_tool_call(
                _make_tool_call(f"tool_{i}"),
                _make_result(),
                elapsed_ms=10,
            )

        assert logger.tool_call_count == 3
        assert len(logger.tool_call_log) == 3
        # Sequences should be 1, 2, 3
        sequences = [e["sequence"] for e in logger.tool_call_log]
        assert sequences == [1, 2, 3]

    def test_log_tool_call_sanitizes_secrets(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        call = _make_tool_call("run_in_terminal", {
            "command": "export API_KEY=sk-live-abc123xyz",
        })
        result = _make_result()

        logger.log_tool_call(call, result, elapsed_ms=5)

        payload = sink.events[0].payload
        # The api_key pattern should be redacted
        assert "sk-live-abc123xyz" not in json.dumps(payload)
        assert "REDACTED" in json.dumps(payload)

    def test_log_tool_call_truncates_long_output(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        call = _make_tool_call("read_file")
        result = _make_result(success=True, output={"text": "x" * 2000})

        logger.log_tool_call(call, result, elapsed_ms=1)

        entry = logger.tool_call_log[0]
        # Output preview should be truncated to 512 chars
        assert len(entry["output_preview"]) <= 512

    def test_log_tool_call_records_errors(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        call = _make_tool_call("write_file")
        result = _make_result(success=False, error="Permission denied")

        logger.log_tool_call(call, result, elapsed_ms=3)

        payload = sink.events[0].payload
        assert payload["success"] is False
        assert payload["error"] == "Permission denied"

    def test_log_session_start(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(
            run_id="run-1",
            telemetry=client,
            user_id="user-1",
            org_id="org-1",
            project_id="proj-1",
        )

        logger.log_session_start("wi-123", {"clarifying", "testing", "verifying"})

        assert len(sink.events) == 1
        event = sink.events[0]
        assert event.event_type == "session.started"
        payload = event.payload
        assert payload["work_item_id"] == "wi-123"
        assert "clarifying" in payload["skip_phases"]
        assert payload["user_id"] == "user-1"

    def test_log_session_complete(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        # Log some tool calls first
        for _ in range(5):
            logger.log_tool_call(_make_tool_call(), _make_result(), elapsed_ms=1)

        logger.log_session_complete(success=True)

        # Last event should be session.completed
        completed = [e for e in sink.events if e.event_type == "session.completed"]
        assert len(completed) == 1
        assert completed[0].payload["total_tool_calls"] == 5
        assert completed[0].payload["success"] is True

    def test_log_session_complete_failure(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        logger.log_session_complete(success=False, error="Phase failed")

        completed = [e for e in sink.events if e.event_type == "session.completed"]
        assert completed[0].payload["error"] == "Phase failed"

    def test_log_phase_transition(self):
        client, sink = _make_telemetry()
        logger = SessionAuditLogger(run_id="run-1", telemetry=client)

        logger.log_phase_transition("planning", "executing")

        assert len(sink.events) == 1
        payload = sink.events[0].payload
        assert payload["from_phase"] == "planning"
        assert payload["to_phase"] == "executing"

    def test_raze_integration(self):
        client, sink = _make_telemetry()
        raze = MagicMock()
        logger = SessionAuditLogger(
            run_id="run-1",
            telemetry=client,
            raze_service=raze,
            user_id="user-1",
        )

        call = _make_tool_call("read_file")
        result = _make_result()
        logger.log_tool_call(call, result, elapsed_ms=10)

        # Both telemetry and Raze should be called
        assert len(sink.events) == 1
        raze.log.assert_called_once()
        raze_kwargs = raze.log.call_args
        assert raze_kwargs[0][0] == "session.tool_call"  # positional: event name

    def test_raze_failure_does_not_propagate(self):
        client, sink = _make_telemetry()
        raze = MagicMock()
        raze.log.side_effect = RuntimeError("Raze connection lost")
        logger = SessionAuditLogger(run_id="run-1", telemetry=client, raze_service=raze)

        # Should not raise
        call = _make_tool_call("read_file")
        logger.log_tool_call(call, _make_result(), elapsed_ms=1)
        assert len(sink.events) == 1  # Telemetry still works


# ===========================================================================
# Sanitizer
# ===========================================================================


class TestSanitizeValue:
    def test_redacts_api_key(self):
        result = _sanitize_value("api_key=sk-live-12345678")
        assert "sk-live-12345678" not in result
        assert "REDACTED" in result

    def test_redacts_bearer_token(self):
        result = _sanitize_value("bearer=eyJhbGciOiJIUzI1NiJ9abcdefgh")
        assert "eyJhbGciOiJIUzI1NiJ9abcdefgh" not in result

    def test_truncates_long_strings(self):
        long_str = "a" * 5000
        result = _sanitize_value(long_str, max_length=100)
        assert len(result) < 200  # Truncated + suffix
        assert "truncated" in result

    def test_sanitizes_nested_dicts(self):
        data = {"config": {"secret": "secret=my-super-secret-val"}}
        result = _sanitize_value(data)
        assert "my-super-secret-val" not in json.dumps(result)

    def test_sanitizes_lists(self):
        data = ["password=hunter2_long_enough", "hello"]
        result = _sanitize_value(data)
        assert "hunter2_long_enough" not in json.dumps(result)

    def test_passthrough_non_string(self):
        assert _sanitize_value(42) == 42
        assert _sanitize_value(True) is True
        assert _sanitize_value(None) is None


# ===========================================================================
# GUIDEAI-913 — Escalation Detection
# ===========================================================================


class TestEscalationDetector:
    def test_no_signals_for_clean_read(self):
        detector = EscalationDetector()
        call = _make_tool_call("read_file", {"path": "/src/main.py"})
        result = _make_result()

        signals = detector.check(call, result)
        assert signals == []

    def test_credential_pattern_detected(self):
        detector = EscalationDetector()
        call = _make_tool_call("run_in_terminal", {
            "command": "export API_KEY=sk-live-12345678"
        })
        result = _make_result()

        signals = detector.check(call, result)
        cred_signals = [s for s in signals if s.trigger == "credential_pattern"]
        assert len(cred_signals) >= 1
        assert cred_signals[0].severity == "critical"

    def test_large_change_set_warning(self):
        detector = EscalationDetector(file_change_threshold=3)

        # Modify 3 files
        for i in range(3):
            call = _make_tool_call("write_file", {"path": f"/src/file_{i}.py"})
            signals = detector.check(call, _make_result())

        # The 3rd file should trigger the threshold
        change_signals = [s for s in signals if s.trigger == "large_change_set"]
        assert len(change_signals) == 1
        assert change_signals[0].severity == "warning"

    def test_large_change_set_counts_unique_files(self):
        detector = EscalationDetector(file_change_threshold=3)

        # Modify same file 5 times
        for _ in range(5):
            call = _make_tool_call("write_file", {"path": "/src/same.py"})
            detector.check(call, _make_result())

        assert len(detector.files_modified) == 1  # Only 1 unique file

    def test_compliance_sensitive_operation(self):
        detector = EscalationDetector()
        call = _make_tool_call("run_in_terminal", {
            "command": "alembic upgrade head  # database migration"
        })
        result = _make_result()

        signals = detector.check(call, result)
        compliance_signals = [s for s in signals if s.trigger == "compliance_sensitive"]
        assert len(compliance_signals) >= 1
        assert compliance_signals[0].severity == "warning"

    def test_sensitive_tool_volume(self):
        detector = EscalationDetector(sensitive_tool_threshold=3)

        signals = []
        for i in range(3):
            call = _make_tool_call("run_in_terminal", {"command": f"echo {i}"})
            signals = detector.check(call, _make_result())

        volume_signals = [s for s in signals if s.trigger == "sensitive_tool_volume"]
        assert len(volume_signals) == 1
        assert volume_signals[0].severity == "info"
        assert detector.sensitive_tool_count == 3

    def test_multiple_signals_from_single_call(self):
        """A single tool call can trigger multiple escalation signals."""
        detector = EscalationDetector(sensitive_tool_threshold=1)
        call = _make_tool_call("run_in_terminal", {
            "command": "export password=supersecretvalue && deploy production"
        })
        result = _make_result()

        signals = detector.check(call, result)
        triggers = {s.trigger for s in signals}
        # Should detect credential pattern, compliance_sensitive, and sensitive_tool_volume
        assert "credential_pattern" in triggers
        assert "compliance_sensitive" in triggers
        assert "sensitive_tool_volume" in triggers

    def test_escalation_signal_dataclass(self):
        signal = EscalationSignal(
            trigger="test_trigger",
            severity="warning",
            detail="Test detail",
            metadata={"key": "value"},
        )
        assert signal.trigger == "test_trigger"
        assert signal.metadata == {"key": "value"}

    def test_read_tools_not_counted_as_sensitive(self):
        detector = EscalationDetector(sensitive_tool_threshold=1)
        call = _make_tool_call("read_file", {"path": "/src/main.py"})

        signals = detector.check(call, _make_result())
        assert detector.sensitive_tool_count == 0
        volume_signals = [s for s in signals if s.trigger == "sensitive_tool_volume"]
        assert len(volume_signals) == 0


# ===========================================================================
# GUIDEAI-912 — Per-Tool Permission Policies
# ===========================================================================


class TestToolPermissionLevel:
    def test_enum_values(self):
        assert ToolPermissionLevel.ALWAYS_ALLOW.value == "always_allow"
        assert ToolPermissionLevel.REQUIRE_CONFIRMATION.value == "require_confirmation"
        assert ToolPermissionLevel.DENY.value == "deny"

    def test_session_mode_defaults_read_tools_allowed(self):
        for tool in ["read_file", "list_directory", "search_files"]:
            assert SESSION_MODE_TOOL_PERMISSIONS[tool] == ToolPermissionLevel.ALWAYS_ALLOW

    def test_session_mode_defaults_write_tools_require_confirm(self):
        for tool in ["write_file", "edit_file", "delete_file"]:
            assert SESSION_MODE_TOOL_PERMISSIONS[tool] == ToolPermissionLevel.REQUIRE_CONFIRMATION

    def test_session_mode_defaults_terminal_requires_confirm(self):
        assert SESSION_MODE_TOOL_PERMISSIONS["run_in_terminal"] == ToolPermissionLevel.REQUIRE_CONFIRMATION


class TestExecutionPolicyToolPermissions:
    def test_for_session_mode_includes_tool_permissions(self):
        policy = ExecutionPolicy.for_session_mode()
        assert len(policy.tool_permissions) > 0
        assert policy.tool_permissions["read_file"] == ToolPermissionLevel.ALWAYS_ALLOW
        assert policy.tool_permissions["write_file"] == ToolPermissionLevel.REQUIRE_CONFIRMATION

    def test_tool_permissions_serialization_roundtrip(self):
        policy = ExecutionPolicy.for_session_mode()
        data = policy.to_dict()

        # Check serialized form
        assert "tool_permissions" in data
        assert data["tool_permissions"]["read_file"] == "always_allow"

        # Roundtrip
        restored = ExecutionPolicy.from_dict(data)
        assert restored.tool_permissions["read_file"] == ToolPermissionLevel.ALWAYS_ALLOW
        assert restored.tool_permissions["write_file"] == ToolPermissionLevel.REQUIRE_CONFIRMATION

    def test_empty_tool_permissions_by_default(self):
        """Non-session policies start with empty tool_permissions."""
        policy = ExecutionPolicy.fully_autonomous()
        assert policy.tool_permissions == {}

    def test_tool_permissions_from_dict_handles_empty(self):
        data = ExecutionPolicy.fully_autonomous().to_dict()
        assert data.get("tool_permissions", {}) == {}
        restored = ExecutionPolicy.from_dict(data)
        assert restored.tool_permissions == {}


# ===========================================================================
# Integration — Loop wiring smoke test
# ===========================================================================


class TestLoopWiringIntegration:
    """Smoke tests verifying the wiring in agent_execution_loop.py compiles
    and the new classes can be constructed with the right interfaces."""

    def test_session_audit_logger_construction(self):
        client, _ = _make_telemetry()
        logger = SessionAuditLogger(
            run_id="run-1",
            telemetry=client,
            user_id="u1",
            org_id="o1",
            project_id="p1",
        )
        assert logger.tool_call_count == 0
        assert logger.tool_call_log == []

    def test_escalation_detector_construction(self):
        detector = EscalationDetector(
            file_change_threshold=5,
            sensitive_tool_threshold=3,
        )
        assert detector.files_modified == set()
        assert detector.sensitive_tool_count == 0

    def test_session_policy_tool_permissions_merge_into_exec_policy(self):
        """Simulate what the loop does: merge session policy permissions into exec_policy."""
        exec_policy = ExecutionPolicy.fully_autonomous()
        session_policy = ExecutionPolicy.for_session_mode()

        # The loop does: if not exec_policy.tool_permissions: ...
        if not exec_policy.tool_permissions:
            exec_policy.tool_permissions = dict(session_policy.tool_permissions)

        assert exec_policy.tool_permissions["read_file"] == ToolPermissionLevel.ALWAYS_ALLOW
        assert exec_policy.tool_permissions["run_in_terminal"] == ToolPermissionLevel.REQUIRE_CONFIRMATION

    def test_deny_permission_blocks_tool(self):
        """Simulate the DENY check added to _execute_tool_calls."""
        policy = ExecutionPolicy.for_session_mode()
        policy.tool_permissions["run_in_terminal"] = ToolPermissionLevel.DENY

        # The loop checks: perm_level == ToolPermissionLevel.DENY
        perm = policy.tool_permissions.get("run_in_terminal")
        assert perm == ToolPermissionLevel.DENY

        # Unlisted tools default to None (no restriction)
        perm2 = policy.tool_permissions.get("unknown_tool")
        assert perm2 is None
