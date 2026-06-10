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
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from .execution_observability import (
    ExecutionObservabilityContext,
    sanitize_observability_value,
)
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

    return sanitize_observability_value(value, max_length=max_length)


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
        governed_chat_audit: Optional["GovernedChatAuditLogger"] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        observability_context: Optional[ExecutionObservabilityContext] = None,
    ) -> None:
        self._run_id = run_id
        self._telemetry = telemetry
        self._raze = raze_service
        self._governed_chat_audit = governed_chat_audit
        self._user_id = user_id
        self._org_id = org_id
        self._project_id = project_id
        self._observability_context = observability_context
        self._tool_call_count = 0
        self._tool_call_log: List[Dict[str, Any]] = []

    def set_observability_context(
        self,
        context: Optional[ExecutionObservabilityContext],
    ) -> None:
        """Set shared execution correlation metadata for future audit records."""
        self._observability_context = context

    # -- Core audit operations ------------------------------------------------

    def log_tool_call(
        self,
        tool_call: ToolCall,
        result: ToolResult,
        elapsed_ms: int,
    ) -> None:
        """Log a tool call with full context for audit trail."""
        self._tool_call_count += 1
        decision = "allow" if result.success else "error"
        if result.error and re.search(r"\b(denied|not permitted|blocked)\b", result.error, re.IGNORECASE):
            decision = "denied"
        target_resources = [
            {
                "type": "mcp_tool",
                "id": tool_call.tool_name,
            }
        ]

        entry = {
            "run_id": self._run_id,
            "tool_name": tool_call.tool_name,
            "call_id": tool_call.call_id,
            "sequence": self._tool_call_count,
            "args": _sanitize_value(tool_call.tool_args),
            "success": result.success,
            "decision": decision,
            "elapsed_ms": elapsed_ms,
            "error": _sanitize_value(result.error if not result.success else None),
            "error_class": self._error_class(result),
            "target_resources": target_resources,
        }
        if self._observability_context:
            entry.update(self._observability_context.to_metadata())

        # Capture truncated output for audit (not full output — could be huge)
        if result.success and result.output:
            output_str = str(_sanitize_value(result.output))
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

        if self._governed_chat_audit:
            self._governed_chat_audit.log_tool_call(
                user_id=self._user_id or "",
                action=tool_call.tool_name,
                decision=decision,
                run_id=self._run_id,
                work_item_id=(
                    self._observability_context.work_item_id
                    if self._observability_context
                    else None
                ),
                conversation_id=(
                    self._observability_context.conversation_id
                    if self._observability_context
                    else None
                ),
                message_id=(
                    self._observability_context.message_id
                    if self._observability_context
                    else None
                ),
                request_id=(
                    self._observability_context.request_id
                    if self._observability_context
                    else None
                ),
                metadata={
                    "call_id": tool_call.call_id,
                    "sequence": self._tool_call_count,
                    "args": _sanitize_value(tool_call.tool_args),
                    "success": result.success,
                    "error": _sanitize_value(result.error),
                    "error_class": self._error_class(result),
                    "elapsed_ms": elapsed_ms,
                    "output_preview": entry.get("output_preview"),
                },
                target_resources=target_resources,
                execution_observability=(
                    self._observability_context.to_dict(include_none=False)
                    if self._observability_context
                    else None
                ),
            )

    @staticmethod
    def _error_class(result: ToolResult) -> Optional[str]:
        if result.success:
            return None
        if result.error and re.search(r"\b(denied|not permitted|blocked)\b", result.error, re.IGNORECASE):
            return "ToolPermissionDenied"
        return "ToolExecutionError"

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
# Governed Chat Audit Records — GUIDEAI-1053
# ---------------------------------------------------------------------------


class GovernedChatAuditEventType(str, Enum):
    """Governed chat audit event categories."""

    INTENT_CLASSIFICATION = "intent_classification"
    SCOPE_RESOLUTION = "scope_resolution"
    POLICY_DECISION = "policy_decision"
    TOOL_CALL = "tool_call"
    PLATFORM_ACTION = "platform_action"
    APPROVAL = "approval"
    DENIAL = "denial"
    EXECUTION_START = "execution_start"


@dataclass(frozen=True)
class GovernedChatAuditRecord:
    """Append-only audit record for governed chat actions."""

    audit_id: str
    timestamp: float
    event_type: str
    user_id: str
    chat_scope: Optional[str]
    target_resources: List[Dict[str, Any]]
    action: str
    decision: str
    policy_ids: List[str] = field(default_factory=list)
    run_id: Optional[str] = None
    work_item_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    request_id: Optional[str] = None
    execution_observability: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "chat_scope": self.chat_scope,
            "target_resources": list(self.target_resources),
            "action": self.action,
            "decision": self.decision,
            "policy_ids": list(self.policy_ids),
            "run_id": self.run_id,
            "work_item_id": self.work_item_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "execution_observability": dict(self.execution_observability),
            "metadata": dict(self.metadata),
        }


class GovernedChatAuditLogger:
    """Append-only audit trail for governed chat decisions and actions.

    The logger stores sanitized records in memory for local querying and emits
    the same sanitized payload through TelemetryClient for durable sinks.
    """

    REVIEW_DECISIONS = frozenset({"review", "review_required", "require_approval"})
    DENY_DECISIONS = frozenset({"deny", "denied", "blocked"})

    def __init__(
        self,
        *,
        telemetry: Optional[TelemetryClient] = None,
        raze_service: Optional[Any] = None,
    ) -> None:
        self._telemetry = telemetry
        self._raze = raze_service
        self._records: List[GovernedChatAuditRecord] = []

    def log(
        self,
        *,
        event_type: str | GovernedChatAuditEventType,
        user_id: str,
        action: str,
        decision: str,
        chat_scope: Optional[str] = None,
        target_resources: Optional[List[Dict[str, Any]]] = None,
        policy_ids: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        request_id: Optional[str] = None,
        execution_observability: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        actor_surface: str = "chat",
    ) -> GovernedChatAuditRecord:
        """Append and emit one sanitized governed-chat audit record."""

        event_value = event_type.value if isinstance(event_type, Enum) else str(event_type)
        sanitized_targets = _sanitize_value(target_resources or [])
        sanitized_context = _sanitize_value(execution_observability or {})
        sanitized_metadata = _sanitize_value(metadata or {})
        record = GovernedChatAuditRecord(
            audit_id=f"gca-{uuid4().hex}",
            timestamp=time.time(),
            event_type=event_value,
            user_id=user_id or "unknown",
            chat_scope=chat_scope,
            target_resources=sanitized_targets,
            action=action,
            decision=str(decision),
            policy_ids=list(policy_ids or []),
            run_id=run_id,
            work_item_id=work_item_id,
            conversation_id=conversation_id,
            message_id=message_id,
            request_id=request_id,
            execution_observability=sanitized_context,
            metadata=sanitized_metadata,
        )
        self._records.append(record)

        payload = record.to_dict()
        actor = {"id": record.user_id, "role": "user", "surface": actor_surface}
        if self._telemetry:
            self._telemetry.emit_event(
                event_type="governed_chat.audit_record",
                payload=payload,
                actor=actor,
                run_id=run_id,
                session_id=conversation_id,
            )
        if self._raze:
            try:
                self._raze.log(
                    "governed_chat.audit_record",
                    run_id=run_id,
                    user_id=record.user_id,
                    **{k: v for k, v in payload.items() if k not in {"run_id", "user_id"}},
                )
            except Exception:
                logger.debug("Raze logging failed for governed chat audit", exc_info=True)
        return record

    def log_tool_call(self, **kwargs: Any) -> GovernedChatAuditRecord:
        return self.log(event_type=GovernedChatAuditEventType.TOOL_CALL, **kwargs)

    def query(
        self,
        *,
        decisions: Optional[Set[str]] = None,
        event_types: Optional[Set[str]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
    ) -> List[GovernedChatAuditRecord]:
        """Query already-appended audit records without mutating them."""

        normalized_decisions = {d.lower() for d in decisions} if decisions else None
        normalized_event_types = {t.lower() for t in event_types} if event_types else None
        records = self._records
        if normalized_decisions is not None:
            records = [r for r in records if r.decision.lower() in normalized_decisions]
        if normalized_event_types is not None:
            records = [r for r in records if r.event_type.lower() in normalized_event_types]
        if user_id is not None:
            records = [r for r in records if r.user_id == user_id]
        if run_id is not None:
            records = [r for r in records if r.run_id == run_id]
        if work_item_id is not None:
            records = [r for r in records if r.work_item_id == work_item_id]
        return list(records)

    def denied_or_review_required(self) -> List[GovernedChatAuditRecord]:
        """Return denied and review-required governed chat actions."""

        return self.query(decisions=self.DENY_DECISIONS | self.REVIEW_DECISIONS)

    @property
    def records(self) -> List[GovernedChatAuditRecord]:
        return list(self._records)


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
