"""Governed read path for warehouse trace views (run / conversation / span tree)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from amprealize.observability_access import resolve_observability_access_tier

TraceSinkProvider = Callable[[], Any]


@dataclass(frozen=True)
class TraceSummaryFilters:
    """Filters for listing rollups from ``observability_*_summary`` views."""

    project_id: str
    run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    since: Optional[str] = None
    until: Optional[str] = None
    limit: int = 50
    offset: int = 0


class GovernedTraceReadService:
    """Apply RBAC metadata and delegate to :class:`PostgresTelemetrySink` view queries."""

    def __init__(self, sink_provider: TraceSinkProvider) -> None:
        self._sink_provider = sink_provider

    def list_run_summaries(
        self,
        actor: Mapping[str, Any],
        filters: TraceSummaryFilters,
    ) -> Dict[str, Any]:
        tier = resolve_observability_access_tier(actor).value
        sink = self._sink_provider()
        if sink is None:
            return _empty_trace_payload(tier)
        rows = sink.query_run_summaries(
            project_id=filters.project_id,
            run_id=filters.run_id,
            since=filters.since,
            until=filters.until,
            limit=filters.limit,
            offset=filters.offset,
        )
        return {
            "access_tier": tier,
            "records": rows,
            "count": len(rows),
            "truncated": len(rows) >= filters.limit,
        }

    def list_conversation_summaries(
        self,
        actor: Mapping[str, Any],
        filters: TraceSummaryFilters,
    ) -> Dict[str, Any]:
        tier = resolve_observability_access_tier(actor).value
        sink = self._sink_provider()
        if sink is None:
            return _empty_trace_payload(tier)
        rows = sink.query_conversation_summaries(
            project_id=filters.project_id,
            conversation_id=filters.conversation_id,
            since=filters.since,
            until=filters.until,
            limit=filters.limit,
            offset=filters.offset,
        )
        return {
            "access_tier": tier,
            "records": rows,
            "count": len(rows),
            "truncated": len(rows) >= filters.limit,
        }

    def get_span_tree(
        self,
        actor: Mapping[str, Any],
        *,
        project_id: str,
        trace_id: str,
        limit: int = 500,
    ) -> Dict[str, Any]:
        tier = resolve_observability_access_tier(actor).value
        sink = self._sink_provider()
        if sink is None:
            return {**_empty_trace_payload(tier), "trace_id": trace_id}
        rows = sink.query_span_tree(
            project_id=project_id,
            trace_id=trace_id,
            limit=limit,
        )
        return {
            "access_tier": tier,
            "trace_id": trace_id,
            "records": rows,
            "count": len(rows),
            "truncated": len(rows) >= limit,
        }


def _empty_trace_payload(tier: str) -> Dict[str, Any]:
    return {
        "access_tier": tier,
        "records": [],
        "count": 0,
        "truncated": False,
    }


__all__ = [
    "GovernedTraceReadService",
    "TraceSummaryFilters",
]
