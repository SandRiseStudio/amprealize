"""Telemetry KPI projector.

Provides an in-memory implementation that rolls up telemetry-shaped events
into a ``TelemetryProjection``.  The enterprise edition replaces this with
an async production-grade projector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TelemetryProjection:
    """Telemetry projection payload shared across OSS and enterprise."""

    summary: Dict[str, Any] = field(default_factory=dict)
    fact_behavior_usage: List[Dict[str, Any]] = field(default_factory=list)
    fact_token_savings: List[Dict[str, Any]] = field(default_factory=list)
    fact_execution_status: List[Dict[str, Any]] = field(default_factory=list)
    fact_compliance_steps: List[Dict[str, Any]] = field(default_factory=list)
    fact_resource_usage: List[Dict[str, Any]] = field(default_factory=list)
    fact_cost_allocation: List[Dict[str, Any]] = field(default_factory=list)


class _OssTelemetryKPIProjector:
    """Lightweight KPI rollup for OSS (in-memory from telemetry-shaped events)."""

    @staticmethod
    def _to_dict(e: Any) -> Dict[str, Any]:
        """Convert event to dict, supporting both dataclass and dict inputs."""
        if isinstance(e, dict):
            return e
        from dataclasses import asdict as _asdict, fields as _fields

        try:
            _fields(e)
            return _asdict(e)
        except TypeError:
            return {}

    @staticmethod
    def _run_id(e: Dict[str, Any]) -> str | None:
        """Extract run_id from top-level or payload."""
        rid = e.get("run_id")
        if rid:
            return str(rid)
        payload = e.get("payload")
        if isinstance(payload, dict):
            rid = payload.get("run_id")
            if rid:
                return str(rid)
        return None

    def project(self, events: Any = None, **kwargs: Any) -> TelemetryProjection:
        raw = events or []
        if not isinstance(raw, (list, tuple)):
            raw = []
        raw = [self._to_dict(e) for e in raw]

        run_ids = sorted({rid for e in raw if (rid := self._run_id(e))})
        total_runs = len(run_ids)

        plan_by_run: Dict[str, set[str]] = {}
        cited_by_run: Dict[str, set[str]] = {}
        status_by_run: Dict[str, str] = {}
        baseline_by_run: Dict[str, int] = {}
        savings_by_run: Dict[str, float | None] = {}
        compliance_scores: List[float] = []
        fact_compliance_steps: List[Dict[str, Any]] = []
        fact_resource_usage: List[Dict[str, Any]] = []

        cost_per_token = 0.00003

        for e in raw:
            rid = self._run_id(e)
            if not rid:
                continue
            event_type = str(e.get("event_type") or "")
            payload = e.get("payload") or {}
            if not isinstance(payload, dict):
                payload = {}
            timestamp = str(e.get("timestamp") or "")
            if event_type == "plan_created":
                ids = payload.get("behavior_ids") or []
                plan_by_run.setdefault(rid, set()).update(str(x) for x in ids)
                baseline_tokens = payload.get("baseline_tokens")
                if baseline_tokens is not None:
                    try:
                        baseline_by_run[rid] = int(baseline_tokens)
                    except (ValueError, TypeError):
                        pass
                fact_resource_usage.append(
                    {
                        "run_id": rid,
                        "timestamp": timestamp,
                        "service_name": "BehaviorService",
                        "token_count": int(baseline_tokens) if baseline_tokens else 0,
                    }
                )
            elif event_type == "execution_update":
                cited = payload.get("behaviors_cited") or []
                cited_by_run.setdefault(rid, set()).update(str(x) for x in cited)
                status = payload.get("status")
                if status:
                    status_by_run[rid] = str(status).upper()
                token_savings_pct = payload.get("token_savings_pct")
                if token_savings_pct is not None:
                    try:
                        savings_by_run[rid] = float(token_savings_pct)
                    except (ValueError, TypeError):
                        savings_by_run[rid] = None
                else:
                    savings_by_run.setdefault(rid, None)
                output_tokens = payload.get("output_tokens")
                if output_tokens is not None:
                    try:
                        output_tokens = int(output_tokens)
                    except (ValueError, TypeError):
                        output_tokens = 0
                    fact_resource_usage.append(
                        {
                            "run_id": rid,
                            "timestamp": timestamp,
                            "service_name": "ActionService",
                            "token_count": output_tokens,
                        }
                    )
            elif event_type == "compliance_step_recorded":
                coverage_score = payload.get("coverage_score")
                if coverage_score is not None:
                    try:
                        compliance_scores.append(float(coverage_score))
                    except (ValueError, TypeError):
                        pass
                fact_compliance_steps.append(
                    {
                        "run_id": rid,
                        "checklist_id": payload.get("checklist_id"),
                        "step_id": payload.get("step_id"),
                        "status": payload.get("status"),
                        "coverage_score": float(coverage_score) if coverage_score is not None else None,
                    }
                )

        reuse_vals: List[float] = []
        fact_behavior_usage: List[Dict[str, Any]] = []
        for rid in run_ids:
            plan = plan_by_run.get(rid, set())
            cited = cited_by_run.get(rid, set())
            all_behaviors = plan | cited
            baseline = baseline_by_run.get(rid, 0)
            fact_behavior_usage.append(
                {
                    "run_id": rid,
                    "behavior_count": len(all_behaviors),
                    "has_behaviors": bool(all_behaviors),
                    "behavior_ids": sorted(all_behaviors) if all_behaviors else [],
                    "baseline_tokens": baseline,
                }
            )
            if not plan and not cited:
                reuse_vals.append(0.0)
            elif not plan:
                reuse_vals.append(0.0)
            elif cited <= plan:
                reuse_vals.append(100.0)
            elif not cited:
                reuse_vals.append(0.0)
            else:
                reuse_vals.append(100.0 * len(cited & plan) / len(cited))

        behavior_reuse_pct = sum(reuse_vals) / len(reuse_vals) if reuse_vals else 0.0
        runs_with_behaviors = sum(1 for rid in run_ids if plan_by_run.get(rid) or cited_by_run.get(rid))
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED", "ERROR"}
        completed = sum(1 for status in status_by_run.values() if status == "COMPLETED")
        terminal_runs = sum(1 for status in status_by_run.values() if status in terminal_statuses)
        task_completion_rate_pct = 100.0 * completed / total_runs if total_runs else 0.0

        valid_savings = [value for value in savings_by_run.values() if value is not None]
        average_token_savings_pct = 100.0 * sum(valid_savings) / len(valid_savings) if valid_savings else 0.0
        average_compliance_coverage_pct = 100.0 * sum(compliance_scores) / len(compliance_scores) if compliance_scores else 0.0

        fact_token_savings = [
            {
                "run_id": rid,
                "token_savings_pct": savings_by_run.get(rid),
                "baseline_tokens": baseline_by_run.get(rid, 0),
            }
            for rid in run_ids
        ]
        fact_execution_status = [
            {
                "run_id": rid,
                "status": status_by_run.get(rid, "UNKNOWN"),
            }
            for rid in run_ids
        ]

        fact_cost_allocation: List[Dict[str, Any]] = []
        total_cost_usd = 0.0
        cost_by_run: Dict[str, Dict[str, float]] = {}
        for usage in fact_resource_usage:
            rid = usage["run_id"]
            service_name = usage["service_name"]
            token_count = usage.get("token_count", 0) or 0
            cost = token_count * cost_per_token
            cost_by_run.setdefault(rid, {})
            cost_by_run[rid][service_name] = cost_by_run[rid].get(service_name, 0.0) + cost
        for rid in run_ids:
            service_costs = cost_by_run.get(rid, {})
            run_cost = sum(service_costs.values())
            total_cost_usd += run_cost
            fact_cost_allocation.append(
                {
                    "run_id": rid,
                    "total_cost_usd": run_cost,
                    "service_costs": service_costs,
                }
            )

        return TelemetryProjection(
            summary={
                "total_runs": total_runs,
                "runs_with_behaviors": runs_with_behaviors,
                "behavior_reuse_pct": behavior_reuse_pct,
                "average_token_savings_pct": average_token_savings_pct,
                "completed_runs": completed,
                "terminal_runs": terminal_runs,
                "task_completion_rate_pct": task_completion_rate_pct,
                "average_compliance_coverage_pct": average_compliance_coverage_pct,
                "total_cost_usd": total_cost_usd,
            },
            fact_behavior_usage=fact_behavior_usage,
            fact_token_savings=fact_token_savings,
            fact_execution_status=fact_execution_status,
            fact_compliance_steps=fact_compliance_steps,
            fact_resource_usage=fact_resource_usage,
            fact_cost_allocation=fact_cost_allocation,
        )


# Public alias — enterprise edition replaces this entire module.
TelemetryKPIProjector = _OssTelemetryKPIProjector
