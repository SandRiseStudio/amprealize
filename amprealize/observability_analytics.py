"""Governed observability query helpers for analytics surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from amprealize.observability_access import (
    ObservabilityAccessTier,
    filter_observability_event,
    resolve_observability_access_tier,
    summarize_observability_events,
)
from amprealize.telemetry import TelemetryEvent


ObservabilityEventProvider = Callable[[], Iterable[TelemetryEvent | Mapping[str, Any]]]


@dataclass(frozen=True)
class ObservabilityQuery:
    """Governed query shape for telemetry and trace event access."""

    actor: Mapping[str, Any]
    event_types: Sequence[str] = field(default_factory=tuple)
    run_id: Optional[str] = None
    limit: int = 100
    max_series: int = 20


class GovernedObservabilityQueryService:
    """Apply analytics RBAC before returning observability events or summaries."""

    def __init__(self, event_provider: ObservabilityEventProvider) -> None:
        self._event_provider = event_provider

    def list_events(self, query: ObservabilityQuery) -> Dict[str, Any]:
        """Return filtered telemetry events for the actor's access tier."""

        tier = resolve_observability_access_tier(query.actor)
        events = self._matching_events(query)
        filtered_events = [
            filter_observability_event(event, tier=tier)
            for event in events[: _bounded_limit(query.limit)]
        ]
        return {
            "access_tier": tier.value,
            "records": filtered_events,
            "count": len(filtered_events),
            "truncated": len(events) > len(filtered_events),
        }

    def dashboard_summary(self, query: ObservabilityQuery) -> Dict[str, Any]:
        """Return a bounded dashboard summary for the actor's access tier."""

        tier = resolve_observability_access_tier(query.actor)
        events = self._matching_events(query)
        summary = summarize_observability_events(
            events,
            tier=tier,
            max_series=query.max_series,
        )
        summary["access_tier"] = tier.value
        return summary

    def _matching_events(
        self,
        query: ObservabilityQuery,
    ) -> List[TelemetryEvent | Mapping[str, Any]]:
        event_types = {event_type for event_type in query.event_types if event_type}
        events = list(self._event_provider())
        if event_types:
            events = [
                event for event in events
                if _event_type(event) in event_types
            ]
        if query.run_id:
            events = [
                event for event in events
                if _run_id(event) == query.run_id
            ]
        return events


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit), 1000))


def _event_type(event: TelemetryEvent | Mapping[str, Any]) -> Optional[str]:
    if isinstance(event, TelemetryEvent):
        return event.event_type
    value = event.get("event_type")
    return str(value) if value else None


def _run_id(event: TelemetryEvent | Mapping[str, Any]) -> Optional[str]:
    if isinstance(event, TelemetryEvent):
        return event.run_id
    value = event.get("run_id")
    if value:
        return str(value)
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    context = payload.get("execution_observability")
    if isinstance(context, Mapping) and context.get("run_id"):
        return str(context["run_id"])
    return None


__all__ = [
    "GovernedObservabilityQueryService",
    "ObservabilityQuery",
]
