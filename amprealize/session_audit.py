"""Session Mode audit logging and escalation detection.

Provides structured audit trails for Session Mode execution where
governance phases (clarifying, architecting, testing, fixing, verifying)
are skipped. The audit logger captures every tool call with full context
so that session executions remain observable and auditable.

Also provides escalation detection — heuristics that suggest when a
session-mode task should be upgraded to full GEP governance.

GUIDEAI-914: Raze audit logging for Session Mode
GUIDEAI-913: Session-to-GEP escalation trigger
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .telemetry import TelemetryClient
from .work_item_execution_contracts import ToolCall, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument sanitiser — strip secrets before persisting to audit log
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = re.compile(
    r"(api[_-]?key|secret|token|password|credential|auth|bearer)"
    r"[\"\']?\s*[:=]\s*[\"\']?([^\s\"\']{8,})",
    re.IGNORECASE,
)


def _sanitize_value(value: Any, *, max_length: int = 2048) -> Any:
    """Redact sensitive values and truncate long strings."""
    if isinstance(value, str):
        # Redact anything that looks like a secret
        sanitized = _SECRET_PATTERNS.sub(r"\1=***REDACTED***", value)
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + f"...[truncated {len(value) - max_length} chars]"
        return sanitized
    if isinstance(value, dict):
        return {k: _sanitize_value(v, max_length=max_length) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, max_length=max_length) for item in value]
    return value


# ---------------------------------------------------------------------------
# Session Audit Logger
# ---------------------------------------------------------------------------


class SessionAuditLogger:
    """Structured audit logger for Session Mode tool execution.

    Enriches the existing TelemetryClient events with session-specific
    context and full tool call details (sanitised args, outputs, timing).

    Optionally integrates with Raze for deeper persistence when the
    Raze service is available.
    """

    def __init__(
        self,
        run_id: str,
        telemetry: TelemetryClient,
        *,
        raze_service: Optional[Any] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        self._run_id = run_id
        self._telemetry = telemetry
        self._raze = raze_service
        self._user_id = user_id
        self._org_id = org_id
        self._project_id = project_id
        self._tool_call_count = 0
        self._tool_call_log: List[Dict[str, Any]] = []

    # -- Core audit operations ------------------------------------------------

    def log_tool_call(
        self,
        tool_call: ToolCall,
        result: ToolResult,
        elapsed_ms: int,
    ) -> None:
        """Log a tool call with full context for audit trail."""
        self._tool_call_count += 1

        entry = {
            "run_id": self._run_id,
            "tool_name": tool_call.tool_name,
            "call_id": tool_call.call_id,
            "sequence": self._tool_call_count,
            "args": _sanitize_value(tool_call.tool_args),
            "success": result.success,
            "elapsed_ms": elapsed_ms,
            "error": result.error if not result.success else None,
        }

        # Capture truncated output for audit (not full output — could be huge)
        if result.success and result.output:
            output_str = str(result.output)
            entry["output_preview"] = output_str[:512] if len(output_str) > 512 else output_str

        self._tool_call_log.append(entry)

        # Emit through TelemetryClient
        self._telemetry.emit_event(
            event_type="session.tool_call",
            payload=entry,
            run_id=self._run_id,
        )

        # Also log through Raze if available
        if self._raze:
            try:
                self._raze.log(
                    "session.tool_call",
                    run_id=self._run_id,
                    user_id=self._user_id,
                    org_id=self._org_id,
                    project_id=self._project_id,
                    **{k: v for k, v in entry.items() if k != "run_id"},
                )
            except Exception:
                logger.debug("Raze logging failed for session tool_call", exc_info=True)

    def log_session_start(self, work_item_id: str, skip_phases: Set[str]) -> None:
        """Log session mode activation."""
        self._telemetry.emit_event(
            event_type="session.started",
            payload={
                "run_id": self._run_id,
                "work_item_id": work_item_id,
                "skip_phases": sorted(skip_phases),
                "user_id": self._user_id,
                "org_id": self._org_id,
                "project_id": self._project_id,
            },
            run_id=self._run_id,
        )

    def log_session_complete(self, success: bool, error: Optional[str] = None) -> None:
        """Log session mode completion with summary."""
        self._telemetry.emit_event(
            event_type="session.completed",
            payload={
                "run_id": self._run_id,
                "success": success,
                "total_tool_calls": self._tool_call_count,
                "error": error,
            },
            run_id=self._run_id,
        )

    def log_phase_transition(self, from_phase: str, to_phase: str) -> None:
        """Log phase transition within session mode."""
        self._telemetry.emit_event(
            event_type="session.phase_transition",
            payload={
                "run_id": self._run_id,
                "from_phase": from_phase,
                "to_phase": to_phase,
            },
            run_id=self._run_id,
        )

    @property
    def tool_call_count(self) -> int:
        return self._tool_call_count

    @property
    def tool_call_log(self) -> List[Dict[str, Any]]:
        return list(self._tool_call_log)


# ---------------------------------------------------------------------------
# Escalation Detection — GUIDEAI-913
# ---------------------------------------------------------------------------


@dataclass
class EscalationSignal:
    """A signal suggesting the current session should escalate to GEP."""

    trigger: str  # e.g. "credential_pattern", "large_change_set", "compliance_keyword"
    severity: str  # "info", "warning", "critical"
    detail: str  # Human-readable explanation
    metadata: Dict[str, Any] = field(default_factory=dict)


class EscalationDetector:
    """Detects patterns that suggest session mode should escalate to full GEP.

    Checks after each tool execution for signals like:
    - Credential/secret patterns in tool arguments
    - Large change sets (many files modified)
    - Compliance-sensitive operations (database, deployment, security)
    """

    # Tool names that are compliance-sensitive
    SENSITIVE_TOOLS: Set[str] = {
        "run_in_terminal",  # Can execute arbitrary commands
        "delete_file",
        "write_file",  # File mutations
        "edit_file",
    }

    # Patterns in tool args that suggest credential handling
    CREDENTIAL_PATTERNS = re.compile(
        r"(api[_-]?key|secret|token|password|credential|private[_-]?key|ssh[_-]?key)"
        r"[\"\']?\s*[:=]",
        re.IGNORECASE,
    )

    # Keywords suggesting compliance-sensitive operations
    COMPLIANCE_KEYWORDS = re.compile(
        r"\b(deploy|migration|rollback|production|staging|database|schema|"
        r"security|firewall|certificate|encrypt|decrypt|permission|sudo|root)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        file_change_threshold: int = 10,
        sensitive_tool_threshold: int = 5,
    ) -> None:
        self._file_change_threshold = file_change_threshold
        self._sensitive_tool_threshold = sensitive_tool_threshold
        self._files_modified: Set[str] = set()
        self._sensitive_tool_count = 0

    def check(self, tool_call: ToolCall, result: ToolResult) -> List[EscalationSignal]:
        """Check a completed tool call for escalation signals.

        Returns list of signals (empty if no escalation needed).
        """
        signals: List[EscalationSignal] = []

        # Track sensitive tool usage
        if tool_call.tool_name in self.SENSITIVE_TOOLS:
            self._sensitive_tool_count += 1

        # Track file modifications
        if tool_call.tool_name in {"write_file", "edit_file", "delete_file"}:
            path = tool_call.tool_args.get("path") or tool_call.tool_args.get("filePath", "")
            if path:
                self._files_modified.add(str(path))

        # Check 1: Credential patterns in arguments
        args_str = json.dumps(tool_call.tool_args, default=str)
        if self.CREDENTIAL_PATTERNS.search(args_str):
            signals.append(EscalationSignal(
                trigger="credential_pattern",
                severity="critical",
                detail="Tool arguments contain credential-like patterns. "
                       "Consider GEP mode for secure handling.",
                metadata={"tool_name": tool_call.tool_name},
            ))

        # Check 2: Large change set
        if len(self._files_modified) >= self._file_change_threshold:
            signals.append(EscalationSignal(
                trigger="large_change_set",
                severity="warning",
                detail=f"Session has modified {len(self._files_modified)} files "
                       f"(threshold: {self._file_change_threshold}). "
                       "GEP mode provides testing and verification phases.",
                metadata={"file_count": len(self._files_modified)},
            ))

        # Check 3: Compliance-sensitive operations
        if self.COMPLIANCE_KEYWORDS.search(args_str):
            if tool_call.tool_name in self.SENSITIVE_TOOLS:
                signals.append(EscalationSignal(
                    trigger="compliance_sensitive",
                    severity="warning",
                    detail=f"Tool '{tool_call.tool_name}' invoked with "
                           "compliance-sensitive arguments. "
                           "GEP mode provides governance guardrails.",
                    metadata={"tool_name": tool_call.tool_name},
                ))

        # Check 4: High sensitive tool usage
        if self._sensitive_tool_count >= self._sensitive_tool_threshold:
            signals.append(EscalationSignal(
                trigger="sensitive_tool_volume",
                severity="info",
                detail=f"Session used {self._sensitive_tool_count} sensitive "
                       f"tool calls (threshold: {self._sensitive_tool_threshold}). "
                       "Consider GEP mode for complex changes.",
                metadata={"count": self._sensitive_tool_count},
            ))

        return signals

    @property
    def files_modified(self) -> Set[str]:
        return set(self._files_modified)

    @property
    def sensitive_tool_count(self) -> int:
        return self._sensitive_tool_count
