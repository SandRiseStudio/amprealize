"""Workspace activity tiers for global prioritization chat (fairness + disclosure).

Uses snapshot work items already loaded into inventory (`work_items_by_project`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

Tier = Literal["active", "quiet", "unknown"]

FairnessMode = Literal["balanced_multi_project", "focused_with_disclosure"]


def workspace_activity_recency_days() -> int:
    raw = os.environ.get("AMPREALIZE_WORKSPACE_ACTIVITY_RECENCY_DAYS", "14").strip()
    try:
        d = int(raw)
    except ValueError:
        return 14
    return max(1, min(d, 365))


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            # ISO8601 from API / pydantic json
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _max_updated_at_from_items(items: Any) -> Optional[datetime]:
    if not isinstance(items, list):
        return None
    best: Optional[datetime] = None
    for row in items:
        if not isinstance(row, dict):
            try:
                if hasattr(row, "model_dump"):
                    row = row.model_dump(mode="json")
                elif hasattr(row, "__dict__"):
                    row = dict(row.__dict__)
                else:
                    continue
            except Exception:
                continue
        raw = row.get("updated_at") or row.get("updatedAt")
        dt = _parse_ts(raw)
        if dt is None:
            continue
        if best is None or dt > best:
            best = dt
    return best


@dataclass(frozen=True)
class ProjectActivitySummary:
    """Per-project activity derived from inventory snapshot only."""

    project_id: str
    display_name: str
    tier: Tier
    last_activity_at: Optional[datetime]


def project_display_names(inventory: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in inventory.get("projects") or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("project_id") or p.get("id") or "")
        if not pid:
            continue
        name = str(p.get("name") or p.get("title") or pid)
        out[pid] = name
    return out


def summarize_project_activity(inventory: Dict[str, Any]) -> List[ProjectActivitySummary]:
    """Classify each project using max(updated_at) over inventory work item snapshots."""
    names = project_display_names(inventory)
    now = datetime.now(timezone.utc)
    window = timedelta(days=workspace_activity_recency_days())
    wip = inventory.get("work_items_by_project") or {}
    summaries: List[ProjectActivitySummary] = []

    project_ids = set(names.keys()) | {str(k) for k in wip.keys()}
    for pid in sorted(project_ids):
        items = wip.get(pid)
        max_dt = _max_updated_at_from_items(items)
        if max_dt is None:
            tier: Tier = "unknown"
        elif (now - max_dt) <= window:
            tier = "active"
        else:
            tier = "quiet"
        summaries.append(
            ProjectActivitySummary(
                project_id=pid,
                display_name=names.get(pid, pid),
                tier=tier,
                last_activity_at=max_dt,
            )
        )
    return summaries


def fairness_mode_for_inventory(
    summaries: List[ProjectActivitySummary],
    allowed_project_ids: Optional[set[str]] = None,
) -> FairnessMode:
    """Balanced only when every allowed project is *active* (recent snapshot movement)."""
    allowed = allowed_project_ids or {s.project_id for s in summaries}
    relevant = [s for s in summaries if s.project_id in allowed]
    if not relevant:
        return "focused_with_disclosure"
    if all(s.tier == "active" for s in relevant):
        return "balanced_multi_project"
    return "focused_with_disclosure"


def disclosure_required(mode: FairnessMode) -> bool:
    return mode == "focused_with_disclosure"


def build_workspace_activity_appendix(
    *,
    summaries: List[ProjectActivitySummary],
    fairness_mode: FairnessMode,
    rows_per_project: Dict[str, int],
    project_ids_in_plan: List[str],
    allowed_project_ids: set[str],
) -> str:
    """Structured instructions appended to synthesis prompt (server-derived)."""
    lines: List[str] = []
    lines.append("## Workspace activity (server-derived)")
    lines.append(
        "Per-project signal uses the newest `updated_at` among work items in the "
        f"composer inventory snapshot (active = touched within the last {workspace_activity_recency_days()} days)."
    )
    for s in summaries:
        if s.project_id not in allowed_project_ids:
            continue
        la = s.last_activity_at.isoformat() if s.last_activity_at else "unknown"
        lines.append(f"- **{s.display_name}** [`{s.project_id}`]: tier={s.tier}; last_activity={la}")

    lines.append("")
    lines.append("## Answer policy")
    if fairness_mode == "balanced_multi_project":
        lines.append(
            "- **Fairness mode: balanced.** For every project that still has at least one row in the "
            "server-fetched list below, give at least one concrete recommendation (or say explicitly "
            "that nothing looks urgent there using only those rows)."
        )
    else:
        lines.append(
            "- **Fairness mode: focused with disclosure.** You may emphasize projects/boards that are "
            "**active**. You **must** add one short sentence naming projects that are **quiet** or "
            "**unknown** in the activity list above and state that you are deprioritizing them due to "
            "lack of recent movement in the snapshot (not because the user lacks work elsewhere)."
        )

    zero_fetch = [pid for pid in project_ids_in_plan if rows_per_project.get(pid, 0) == 0]
    if zero_fetch:
        lines.append(
            "- The fetch returned **no matching tasks** for project id(s): "
            + ", ".join(zero_fetch)
            + ". Say so explicitly; do not imply you analyzed boards there."
        )

    lines.append(
        "- Prefer items from the server-fetched block when recommending work; use inventory digest only as context."
    )
    return "\n".join(lines)


__all__ = [
    "FairnessMode",
    "ProjectActivitySummary",
    "build_workspace_activity_appendix",
    "disclosure_required",
    "fairness_mode_for_inventory",
    "summarize_project_activity",
    "workspace_activity_recency_days",
]
