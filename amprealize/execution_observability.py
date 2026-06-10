"""Shared observability helpers for agent execution.

This module keeps correlation fields and redaction behavior consistent across
chat-triggered and work-item-triggered execution paths.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional


_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|credential|authorization|auth|bearer)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|credential|auth|bearer)"
    r"[\"']?\s*[:=]\s*[\"']?([^\s\"']{8,})",
    re.IGNORECASE,
)
_SAFE_METRIC_KEYS = {
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "credential_scope",
}
REDACTED_VALUE = "***REDACTED***"


@dataclass(frozen=True)
class ExecutionObservabilityContext:
    """Correlation context emitted with execution run metadata and telemetry."""

    run_id: Optional[str]
    cycle_id: Optional[str]
    work_item_id: str
    project_id: str
    org_id: Optional[str] = None
    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    surface: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    request_id: Optional[str] = None
    execution_mode: Optional[str] = None
    source_type: Optional[str] = None
    queue_job_id: Optional[str] = None

    def to_dict(self, *, include_none: bool = True) -> Dict[str, Any]:
        data = asdict(self)
        if include_none:
            return data
        return {key: value for key, value in data.items() if value is not None}

    def to_metadata(self) -> Dict[str, Any]:
        """Return the persisted run/cycle metadata shape."""

        return {"execution_observability": self.to_dict(include_none=False)}


def enum_value(value: Any) -> Any:
    """Return a stable string value for enums without importing every enum type."""

    if isinstance(value, Enum):
        return value.value
    return value


def sanitize_observability_value(value: Any, *, max_length: int = 2048) -> Any:
    """Redact sensitive values and truncate long strings for persisted telemetry."""

    if isinstance(value, str):
        sanitized = _SECRET_VALUE_PATTERN.sub(r"\1=" + REDACTED_VALUE, value)
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + f"...[truncated {len(value) - max_length} chars]"
        return sanitized
    if isinstance(value, Mapping):
        sanitized_dict: Dict[str, Any] = {}
        for key, nested_value in value.items():
            key_text = str(key)
            normalized_key = key_text.lower()
            sanitized_dict[key_text] = (
                REDACTED_VALUE
                if (
                    normalized_key not in _SAFE_METRIC_KEYS
                    and _SECRET_KEY_PATTERN.search(key_text)
                )
                else sanitize_observability_value(nested_value, max_length=max_length)
            )
        return sanitized_dict
    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_observability_value(item, max_length=max_length)
            for item in value
        ]
    return value


def sanitize_observability_payload(
    payload: Mapping[str, Any],
    *,
    max_length: int = 2048,
) -> Dict[str, Any]:
    """Sanitize a mapping before writing it to telemetry or audit logs."""

    return sanitize_observability_value(dict(payload), max_length=max_length)


def execution_context_from_resolved(
    resolved: Any,
    *,
    queue_job_id: Optional[str] = None,
) -> ExecutionObservabilityContext:
    """Build shared execution observability context from a ResolvedExecution."""

    request = resolved.request
    return ExecutionObservabilityContext(
        run_id=resolved.run_id,
        cycle_id=resolved.cycle_id,
        work_item_id=request.work_item_id,
        project_id=request.project_id,
        org_id=request.org_id,
        agent_id=resolved.agent_id,
        model_id=resolved.model_id,
        surface=request.surface,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        request_id=request.request_id,
        execution_mode=enum_value(resolved.mode),
        source_type=enum_value(resolved.source_type),
        queue_job_id=queue_job_id,
    )
