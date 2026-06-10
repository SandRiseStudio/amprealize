"""Role-scoped observability access and bounded dashboard summaries."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from amprealize.execution_observability import (
    REDACTED_VALUE,
    sanitize_observability_payload,
)
from amprealize.telemetry import TelemetryEvent


class ObservabilityAccessTier(str, Enum):
    """Access tiers for observability and analyst data."""

    VIEWER = "viewer"
    DATA_ANALYST = "data_analyst"
    ADMIN = "admin"
    COMPLIANCE = "compliance"


_RESTRICTED_KEYS = {
    "raw_prompt",
    "prompt",
    "raw_response",
    "response",
    "messages",
    "tool_args",
    "inputs",
    "output_preview",
    "content_full",
    "file_diff",
    "command_output",
}

_ROLE_TIER_MAP = {
    "admin": ObservabilityAccessTier.ADMIN,
    "owner": ObservabilityAccessTier.ADMIN,
    "workspace_admin": ObservabilityAccessTier.ADMIN,
    "compliance": ObservabilityAccessTier.COMPLIANCE,
    "auditor": ObservabilityAccessTier.COMPLIANCE,
    "data_analyst": ObservabilityAccessTier.DATA_ANALYST,
    "analyst": ObservabilityAccessTier.DATA_ANALYST,
    "product": ObservabilityAccessTier.DATA_ANALYST,
    "viewer": ObservabilityAccessTier.VIEWER,
    "member": ObservabilityAccessTier.VIEWER,
    "student": ObservabilityAccessTier.VIEWER,
}


def resolve_observability_access_tier(actor: Mapping[str, Any]) -> ObservabilityAccessTier:
    """Resolve a user/actor payload into an observability access tier."""

    explicit_tier = actor.get("observability_access_tier") or actor.get("analytics_access_tier")
    if explicit_tier:
        return ObservabilityAccessTier(str(explicit_tier).lower())
    role = str(actor.get("role") or "viewer").strip().lower()
    return _ROLE_TIER_MAP.get(role, ObservabilityAccessTier.VIEWER)


def filter_observability_event(
    event: TelemetryEvent | Mapping[str, Any],
    *,
    tier: ObservabilityAccessTier | str,
) -> Dict[str, Any]:
    """Return an access-scoped telemetry event safe for the requested tier."""

    access_tier = ObservabilityAccessTier(tier)
    event_dict = event.to_dict() if isinstance(event, TelemetryEvent) else dict(event)
    payload = event_dict.get("payload")
    event_dict["payload"] = _filter_payload(
        payload if isinstance(payload, Mapping) else {},
        tier=access_tier,
    )
    return event_dict


def summarize_observability_events(
    events: Iterable[TelemetryEvent | Mapping[str, Any]],
    *,
    tier: ObservabilityAccessTier | str,
    max_series: int = 20,
) -> Dict[str, Any]:
    """Build a bounded dashboard summary from potentially high-cardinality events."""

    access_tier = ObservabilityAccessTier(tier)
    filtered_events = [
        filter_observability_event(event, tier=access_tier)
        for event in events
    ]
    event_types = Counter(str(event.get("event_type") or "unknown") for event in filtered_events)
    surfaces = Counter(
        str(
            ((event.get("payload") or {}).get("execution_observability") or {}).get("surface")
            or (event.get("actor") or {}).get("surface")
            or "unknown"
        )
        for event in filtered_events
    )
    run_ids = {
        run_id
        for event in filtered_events
        for run_id in [_run_id(event)]
        if run_id
    }
    return {
        "event_count": len(filtered_events),
        "unique_run_count": len(run_ids),
        "event_types": _top_counter(event_types, max_series=max_series),
        "surfaces": _top_counter(surfaces, max_series=max_series),
        "truncated_series": {
            "event_types": max(0, len(event_types) - max_series),
            "surfaces": max(0, len(surfaces) - max_series),
        },
        "sample_events": filtered_events[: min(5, len(filtered_events))],
    }


def _filter_payload(
    payload: Mapping[str, Any],
    *,
    tier: ObservabilityAccessTier,
) -> Dict[str, Any]:
    sanitized = sanitize_observability_payload(payload)
    if tier in {ObservabilityAccessTier.ADMIN, ObservabilityAccessTier.COMPLIANCE}:
        return sanitized
    return _redact_restricted_fields(sanitized)


def _redact_restricted_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: MutableMapping[str, Any] = {}
        for key, nested_value in value.items():
            key_text = str(key)
            result[key_text] = (
                REDACTED_VALUE
                if key_text.lower() in _RESTRICTED_KEYS
                else _redact_restricted_fields(nested_value)
            )
        return dict(result)
    if isinstance(value, list):
        return [_redact_restricted_fields(item) for item in value]
    return value


def _run_id(event: Mapping[str, Any]) -> Optional[str]:
    run_id = event.get("run_id")
    if run_id:
        return str(run_id)
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    context = payload.get("execution_observability") if isinstance(payload, Mapping) else {}
    if isinstance(context, Mapping) and context.get("run_id"):
        return str(context["run_id"])
    return None


def _top_counter(counter: Counter[str], *, max_series: int) -> Dict[str, int]:
    return dict(counter.most_common(max_series))
