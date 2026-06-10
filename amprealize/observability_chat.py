"""Deterministic chat answers for governed observability questions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional

from amprealize.inventory_answer_service import InventoryAnswer
from amprealize.observability_analytics import (
    GovernedObservabilityQueryService,
    ObservabilityQuery,
)


class ObservabilityChatAnswerService:
    """Answer common observability questions without exposing restricted traces."""

    def __init__(self, query_service: GovernedObservabilityQueryService) -> None:
        self._query_service = query_service

    def answer(
        self,
        *,
        query: str,
        actor: Mapping[str, Any],
        run_id: Optional[str] = None,
    ) -> Optional[InventoryAnswer]:
        normalized = " ".join(query.lower().split())
        if not _is_observability_question(normalized):
            return None
        if _asks_tool_failures(normalized):
            return self._tool_failure_answer(actor=actor, run_id=run_id)
        if _asks_behavior_candidates(normalized):
            return self._behavior_candidate_answer(actor=actor, run_id=run_id)
        return self._latency_or_summary_answer(actor=actor, run_id=run_id)

    def _tool_failure_answer(
        self,
        *,
        actor: Mapping[str, Any],
        run_id: Optional[str],
    ) -> InventoryAnswer:
        result = self._query_service.list_events(
            ObservabilityQuery(
                actor=actor,
                event_types=("execution.tool.performance",),
                run_id=run_id,
                limit=1000,
            )
        )
        rows = _tool_failure_rows(result["records"])
        if not rows:
            content = "I don't see tool failure telemetry in the governed observability events I can access."
        else:
            lines = ["Based on governed observability events, these tools fail most often:"]
            lines.extend(
                f"- {row['tool_name']}: {row['failure_count']} failure(s)"
                for row in rows[:5]
            )
            content = "\n".join(lines)
        return _answer(
            content=content,
            answer_type="observability.tool_failures",
            rows=rows,
            result=result,
            title="Tool failure summary",
        )

    def _behavior_candidate_answer(
        self,
        *,
        actor: Mapping[str, Any],
        run_id: Optional[str],
    ) -> InventoryAnswer:
        result = self._query_service.list_events(
            ObservabilityQuery(
                actor=actor,
                event_types=("reflection.candidate_extracted",),
                run_id=run_id,
                limit=100,
            )
        )
        rows = [
            {
                "trace_id": _payload(record).get("trace_id"),
                "candidate_id": _payload(record).get("candidate_id"),
                "confidence": _payload(record).get("confidence"),
            }
            for record in result["records"]
        ]
        rows = [row for row in rows if row.get("trace_id") or row.get("candidate_id")]
        if not rows:
            content = "I don't see behavior-candidate trace telemetry in the governed events I can access."
        else:
            lines = ["These traces produced behavior candidates:"]
            lines.extend(
                f"- {row.get('trace_id') or 'unknown trace'} -> {row.get('candidate_id') or 'candidate'}"
                for row in rows[:5]
            )
            content = "\n".join(lines)
        return _answer(
            content=content,
            answer_type="observability.behavior_candidates",
            rows=rows,
            result=result,
            title="Behavior candidate traces",
        )

    def _latency_or_summary_answer(
        self,
        *,
        actor: Mapping[str, Any],
        run_id: Optional[str],
    ) -> InventoryAnswer:
        result = self._query_service.list_events(
            ObservabilityQuery(
                actor=actor,
                event_types=(
                    "conversation_reply.generated",
                    "chat.phase.latency_ms",
                    "execution.llm.completed",
                    "llm.generation.completed",
                ),
                run_id=run_id,
                limit=1000,
            )
        )
        latencies = [
            float(value)
            for record in result["records"]
            for value in [_latency_value(record)]
            if isinstance(value, (int, float))
        ]
        summary = self._query_service.dashboard_summary(
            ObservabilityQuery(actor=actor, run_id=run_id, max_series=5)
        )
        if latencies:
            avg_latency = round(sum(latencies) / len(latencies), 1)
            max_latency = round(max(latencies), 1)
            content = (
                "Based on governed observability events, "
                f"average reply/LLM latency is {avg_latency}ms and max latency is {max_latency}ms "
                f"across {len(latencies)} measured event(s)."
            )
        else:
            content = (
                "I don't see latency telemetry for that question yet. "
                f"I can access {summary['event_count']} governed observability event(s) in the current scope."
            )
        return _answer(
            content=content,
            answer_type="observability.latency_summary",
            rows=[
                {
                    "metric": "latency_ms",
                    "count": len(latencies),
                    "avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
                    "max": round(max(latencies), 1) if latencies else None,
                }
            ],
            result={"events": result, "summary": summary},
            title="Observability latency summary",
        )


def _answer(
    *,
    content: str,
    answer_type: str,
    rows: List[Dict[str, Any]],
    result: Mapping[str, Any],
    title: str,
) -> InventoryAnswer:
    return InventoryAnswer(
        content=content,
        answer_type=answer_type,
        structured_payload={
            "card_kind": "observability_analysis",
            "title": title,
            "summary": content,
            "rows": rows,
            "access_tier": _extract_access_tier(result),
            "query_result": result,
        },
        source_rows=rows,
        trace_steps=[
            {
                "phase": "observability_analysis",
                "label": title,
                "row_count": len(rows),
                "access_tier": _extract_access_tier(result),
            }
        ],
    )


def _tool_failure_rows(records: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    failures: Counter[str] = Counter()
    for record in records:
        payload = _payload(record)
        status = str(payload.get("status") or "").lower()
        if status not in {"failed", "error", "denied", "timeout"}:
            continue
        tool_name = str(payload.get("tool_name") or "unknown")
        failures[tool_name] += 1
    return [
        {"tool_name": tool_name, "failure_count": count}
        for tool_name, count in failures.most_common()
    ]


def _payload(record: Mapping[str, Any]) -> Dict[str, Any]:
    payload = record.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _latency_value(record: Mapping[str, Any]) -> Optional[float]:
    payload = _payload(record)
    value = payload.get("latency_ms", payload.get("elapsed_ms"))
    return value if isinstance(value, (int, float)) else None


def _extract_access_tier(result: Mapping[str, Any]) -> Optional[str]:
    if "access_tier" in result:
        return str(result["access_tier"])
    nested = result.get("events")
    if isinstance(nested, Mapping) and nested.get("access_tier"):
        return str(nested["access_tier"])
    summary = result.get("summary")
    if isinstance(summary, Mapping) and summary.get("access_tier"):
        return str(summary["access_tier"])
    return None


def _is_observability_question(query: str) -> bool:
    return any(
        keyword in query
        for keyword in {
            "observability",
            "telemetry",
            "trace",
            "traces",
            "span",
            "latency",
            "slow",
            "reply",
            "replies",
            "tool fail",
            "tools fail",
            "fail most",
            "token savings",
            "save tokens",
            "candidate behavior",
            "behavior candidate",
        }
    )


def _asks_tool_failures(query: str) -> bool:
    return "tool" in query and any(keyword in query for keyword in {"fail", "failed", "failure"})


def _asks_behavior_candidates(query: str) -> bool:
    return "candidate" in query and "behavior" in query


__all__ = ["ObservabilityChatAnswerService"]
