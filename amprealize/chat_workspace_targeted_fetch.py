"""LLM-planned targeted work-item fetch for global chat (Phase B).

Planning model emits a bounded JSON fetch plan; the executor calls BoardService
with allow-listed project_ids from workspace inventory (RBAC-aligned).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Set, Tuple

from amprealize.boards.contracts import (
    WorkItem,
    WorkItemStatus,
    WorkItemType,
    normalize_item_type,
)
from amprealize.chat_query_planner import ChatPlanOperation, ChatQueryPlan, ChatResourceType
from amprealize.execution_observability import sanitize_observability_value
from amprealize.llm.types import LLMConfig

logger = logging.getLogger(__name__)

# Guardrails (override via env for operators)
_MAX_PLANNER_QUERIES = int(os.environ.get("AMPREALIZE_TARGETED_FETCH_MAX_QUERIES", "6"))
_MAX_LIMIT_PER_QUERY = int(os.environ.get("AMPREALIZE_TARGETED_FETCH_MAX_LIMIT", "50"))
_MAX_TOTAL_ROWS = int(os.environ.get("AMPREALIZE_TARGETED_FETCH_MAX_TOTAL_ROWS", "200"))
_PLANNER_MAX_TOKENS = int(os.environ.get("AMPREALIZE_TARGETED_FETCH_PLANNER_MAX_TOKENS", "1200"))

# Reliable model used for planning, independent of the user's reply-model pick.
# Planner only emits a small JSON fetch plan — it never needs reasoning depth, so
# this is pinned to a fast, consistently-available endpoint rather than whatever
# (possibly slow or overloaded) model the user selected for the actual answer.
_PLANNER_DEFAULT_MODEL_ID = "nvidia-llama-3-3-70b-instruct"


def _planner_timeout_sec() -> float:
    raw = os.environ.get("AMPREALIZE_TARGETED_FETCH_PLANNER_TIMEOUT_SEC", "12").strip()
    try:
        sec = float(raw)
    except ValueError:
        return 12.0
    return max(5.0, min(sec, 600.0))


def _planner_retry_count() -> int:
    """Extra planner attempts after a planner_timeout (not applied to invalid JSON or provider errors)."""
    raw = os.environ.get("AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_COUNT", "0").strip()
    try:
        n = int(raw)
    except ValueError:
        return 0
    return max(0, min(n, 5))


def _attempt_planner_timeout_sec(attempt_index: int) -> float:
    """Per-attempt HTTP timeout; retries may use a larger budget (still below main chat timeout)."""
    base = _planner_timeout_sec()
    if attempt_index == 0:
        return base
    retry_raw = os.environ.get("AMPREALIZE_TARGETED_FETCH_PLANNER_RETRY_TIMEOUT_SEC", "").strip()
    if retry_raw:
        try:
            sec = float(retry_raw)
        except ValueError:
            sec = max(base, min(base * 1.25, 110.0))
        return max(5.0, min(sec, 600.0))
    # Headroom on retry without exceeding a typical AMPREALIZE_LLM_TIMEOUT (120) budget.
    stretched = max(base, min(base * 1.25, 110.0))
    return max(5.0, min(stretched, 600.0))


def _is_planner_timeout_error(exc: BaseException) -> bool:
    name_l = type(exc).__name__.lower()
    msg_l = str(exc).lower()
    if isinstance(exc, TimeoutError):
        return True
    if "timeout" in name_l:
        return True
    if "timed out" in msg_l or "timeout" in msg_l:
        return True
    return False


@dataclass
class FetchQuerySpec:
    """Single allow-listed list_work_items query."""

    project_id: str
    board_id: Optional[str] = None
    limit: int = 25
    sort_by: str = "updated_at"
    order: str = "desc"
    status: Optional[str] = None
    parent_id: Optional[str] = None
    updated_after: Optional[str] = None
    created_after: Optional[str] = None
    item_types: Optional[List[str]] = None
    text_search: Optional[str] = None
    """Case-insensitive substring to match against work item title AND description."""


@dataclass
class WorkspaceFetchPlan:
    queries: List[FetchQuerySpec]
    rationale: str = ""


@dataclass
class PlannerRunResult:
    """Outcome of `run_planner_llm` (success, parse failure, timeout, or provider error)."""

    plan: Optional[WorkspaceFetchPlan] = None
    failure_reason: Optional[str] = None
    """invalid_or_empty_plan | planner_timeout | planner_error"""
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    planner_latency_ms: Optional[float] = None
    planner_attempts: int = 0
    planner_model_id: Optional[str] = None


def _resolve_planner_model_id(metadata: Dict[str, Any]) -> str:
    raw = os.environ.get("AMPREALIZE_TARGETED_FETCH_PLANNER_MODEL_ID", "").strip()
    if raw:
        return raw
    return _PLANNER_DEFAULT_MODEL_ID


def build_fetch_plan_from_chat_query_plan(
    chat_plan: ChatQueryPlan,
    *,
    allowed_project_ids: Set[str],
) -> Optional[WorkspaceFetchPlan]:
    """Create targeted work-item fetches from a validated chat query plan."""

    if chat_plan.resource_type != ChatResourceType.WORK_ITEMS:
        return None
    if chat_plan.operation not in {
        ChatPlanOperation.LIST_RESOURCES,
        ChatPlanOperation.SUMMARIZE_RESOURCES,
        ChatPlanOperation.GROUP_RESOURCES,
        ChatPlanOperation.COMPARE_RESOURCES,
    }:
        return None
    topic = (chat_plan.topic or "").strip()
    if not topic:
        return None
    requested_project = str(chat_plan.scope.get("project_id") or "").strip()
    if requested_project:
        project_ids = [requested_project] if requested_project in allowed_project_ids else []
    else:
        project_ids = sorted(allowed_project_ids)
    if not project_ids:
        return None
    return WorkspaceFetchPlan(
        queries=[
            FetchQuerySpec(
                project_id=project_id,
                limit=min(25, _MAX_LIMIT_PER_QUERY),
                sort_by="updated_at",
                order="desc",
                text_search=topic,
            )
            for project_id in project_ids[:_MAX_PLANNER_QUERIES]
        ],
        rationale="Fetch work items matching the validated chat query topic.",
    )


def extract_allowed_project_ids(inventory: Dict[str, Any]) -> Set[str]:
    """Collect project ids from composed workspace inventory."""
    out: Set[str] = set()
    for p in inventory.get("projects") or []:
        pid = p.get("project_id") or p.get("id")
        if pid:
            out.add(str(pid))
    return out


def build_inventory_summary_text(inventory: Dict[str, Any]) -> str:
    """Compact summary for the planner (counts + ids; no full WI dumps)."""
    lines: List[str] = []
    projects = inventory.get("projects") or []
    lines.append(f"Projects ({len(projects)}):")
    for p in projects:
        pid = str(p.get("project_id") or p.get("id") or "")
        name = p.get("name") or p.get("title") or "Untitled"
        lines.append(f"- {name} [project_id={pid}]")

    boards_by = inventory.get("boards_by_project") or {}
    lines.append("Boards by project:")
    for pid, boards in boards_by.items():
        if not isinstance(boards, list):
            continue
        for b in boards:
            bid = str(b.get("board_id") or b.get("id") or "")
            bname = b.get("name") or b.get("title") or "Board"
            lines.append(f"- {bname} [board_id={bid}] project={pid}")

    wip = inventory.get("work_items_by_project") or {}
    lines.append("Approximate work items loaded in snapshot (may be capped upstream):")
    for pid, items in wip.items():
        if isinstance(items, list):
            lines.append(f"- project {pid}: {len(items)} items in composer snapshot")

    lines.append(
        "Allowed filter fields for follow-up queries: project_id (required), "
        "board_id, limit (<= %s), sort_by (updated_at|created_at|priority|title), "
        "order (asc|desc), status (backlog|in_progress|in_review|done), parent_id, "
        "updated_after (ISO date), created_after (ISO date), "
        "item_types (goal,feature,task,bug,research)."
        % (_MAX_LIMIT_PER_QUERY,)
    )
    return "\n".join(lines)


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```\s*$", t)
    if m:
        return m.group(1).strip()
    return t


def parse_workspace_fetch_plan(raw: str) -> Optional[WorkspaceFetchPlan]:
    """Parse planner output into a WorkspaceFetchPlan."""
    try:
        data = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        logger.warning("targeted_fetch.planner_json_invalid err=%s", exc)
        return None
    if not isinstance(data, dict):
        return None
    raw_queries = data.get("queries")
    if not isinstance(raw_queries, list):
        return None
    specs: List[FetchQuerySpec] = []
    for q in raw_queries[:_MAX_PLANNER_QUERIES]:
        if not isinstance(q, dict):
            continue
        pid = q.get("project_id")
        if not pid:
            continue
        limit = int(q.get("limit") or 25)
        limit = max(1, min(limit, _MAX_LIMIT_PER_QUERY))
        specs.append(
            FetchQuerySpec(
                project_id=str(pid),
                board_id=str(q["board_id"]) if q.get("board_id") else None,
                limit=limit,
                sort_by=str(q.get("sort_by") or "updated_at"),
                order=str(q.get("order") or "desc"),
                status=str(q["status"]) if q.get("status") else None,
                parent_id=str(q["parent_id"]) if q.get("parent_id") else None,
                updated_after=str(q["updated_after"]) if q.get("updated_after") else None,
                created_after=str(q["created_after"]) if q.get("created_after") else None,
                item_types=list(q["item_types"]) if isinstance(q.get("item_types"), list) else None,
                text_search=str(q["text_search"]) if q.get("text_search") else None,
            )
        )
    if not specs:
        return None
    rationale = str(data.get("rationale") or "")[:500]
    return WorkspaceFetchPlan(queries=specs, rationale=rationale)


PLANNER_SYSTEM_PROMPT = """You are a planning assistant for Amprealize workspace chat.
The user wants prioritization help across projects/boards. You MUST NOT invent project or board ids.

Given:
1) An inventory summary listing real project_id and board_id values.
2) The user's question.

Output ONLY valid JSON (no markdown fences) with this shape:
{
  "queries": [
    {
      "project_id": "<uuid from summary>",
      "board_id": "<optional uuid from summary>",
      "limit": <1-%d>,
      "sort_by": "updated_at",
      "order": "desc",
      "status": null,
      "parent_id": null,
      "updated_after": null,
      "created_after": null,
      "item_types": null,
      "text_search": null
    }
  ],
  "rationale": "<one short sentence>"
}

Rules:
- Include up to %d queries total.
- Every project_id MUST appear exactly as given in the inventory summary.
- Multi-project breadth: If the inventory lists two or more distinct projects and the user's question is broad workspace prioritization (e.g. what to work on today, what to pick next, backlog/in-progress mix across the workspace), you MUST allocate queries so each distinct project_id receives at least one query until you hit the query cap above. Only concentrate queries on a single project when the user explicitly asks about that project or a narrow slice of work.
- Prefer recent/active items: sort_by updated_at, order desc unless the question implies otherwise.
- Use status to narrow when helpful (backlog, in_progress, in_review, done).
- Use created_after / updated_after as ISO date strings (YYYY-MM-DD) when "today" / recency matters.
- Use item_types array only when narrowing (e.g. ["goal","feature"]).
- board_id is optional; omit to search across boards for that project.
- Use text_search when the user asks about work items mentioning a specific topic, keyword, or feature name (e.g. "agent execution", "authentication", "billing"). Set to null otherwise.
""" % (_MAX_LIMIT_PER_QUERY, _MAX_PLANNER_QUERIES)


def run_planner_llm(
    *,
    llm_client: Any,
    inventory_summary: str,
    user_question: str,
    metadata: Dict[str, Any],
    execution_observability: Optional[Dict[str, Any]] = None,
    actor: Optional[Dict[str, str]] = None,
) -> PlannerRunResult:
    """Blocking planner call; run inside asyncio.to_thread from async handlers."""
    t0 = time.monotonic()
    model_id = _resolve_planner_model_id(metadata)
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Inventory summary:\n{inventory_summary}\n\nUser question:\n{user_question}",
        },
    ]
    base_cfg = LLMConfig.from_env()
    retries = _planner_retry_count()
    max_attempts = 1 + retries

    for attempt in range(max_attempts):
        planner_timeout = _attempt_planner_timeout_sec(attempt)
        planner_cfg = replace(base_cfg, timeout=planner_timeout)
        try:
            resp = llm_client.call(
                messages,
                model=model_id,
                temperature=0.2,
                max_tokens=_PLANNER_MAX_TOKENS,
                config=planner_cfg,
                project_id=metadata.get("project_id"),
                org_id=metadata.get("org_id"),
                user_id=metadata.get("user_id"),
                prefer_user_credential=metadata.get("credential_scope") == "user",
                execution_observability=execution_observability,
                actor=actor,
            )
        except Exception as exc:
            logger.warning(
                "targeted_fetch.planner_failed attempt=%s/%s timeout_sec=%s err=%s",
                attempt + 1,
                max_attempts,
                planner_timeout,
                exc,
            )
            reason = "planner_timeout" if _is_planner_timeout_error(exc) else "planner_error"
            detail = sanitize_observability_value(str(exc), max_length=400)
            if not isinstance(detail, str):
                detail = str(detail)
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            fail = PlannerRunResult(
                failure_reason=reason,
                error_class=type(exc).__name__,
                error_message=detail,
                planner_latency_ms=elapsed_ms,
                planner_attempts=attempt + 1,
                planner_model_id=model_id,
            )
            if reason == "planner_timeout" and attempt < max_attempts - 1:
                logger.info(
                    "targeted_fetch.planner_retry_after_timeout next_attempt=%s/%s next_timeout_sec=%s",
                    attempt + 2,
                    max_attempts,
                    _attempt_planner_timeout_sec(attempt + 1),
                )
                continue
            logger.info(
                "targeted_fetch.planner_done status=failed reason=%s latency_ms=%.1f attempts=%s model_id=%s",
                reason,
                elapsed_ms,
                attempt + 1,
                model_id,
            )
            return fail

        raw = getattr(resp, "content", None) or str(resp)
        parsed = parse_workspace_fetch_plan(raw)
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if parsed is None:
            logger.info(
                "targeted_fetch.planner_done status=invalid_plan latency_ms=%.1f attempts=%s model_id=%s",
                elapsed_ms,
                attempt + 1,
                model_id,
            )
            return PlannerRunResult(
                failure_reason="invalid_or_empty_plan",
                planner_latency_ms=elapsed_ms,
                planner_attempts=attempt + 1,
                planner_model_id=model_id,
            )
        logger.info(
            "targeted_fetch.planner_done status=ok latency_ms=%.1f attempts=%s model_id=%s",
            elapsed_ms,
            attempt + 1,
            model_id,
        )
        return PlannerRunResult(
            plan=parsed,
            planner_latency_ms=elapsed_ms,
            planner_attempts=attempt + 1,
            planner_model_id=model_id,
        )

    raise RuntimeError("targeted_fetch.planner: loop exited without return")


def _resolve_status(value: Optional[str]) -> Optional[WorkItemStatus]:
    if not value:
        return None
    v = value.strip().lower()
    aliases = {
        "open": WorkItemStatus.BACKLOG,
        "todo": WorkItemStatus.BACKLOG,
        "wip": WorkItemStatus.IN_PROGRESS,
        "review": WorkItemStatus.IN_REVIEW,
        "complete": WorkItemStatus.DONE,
        "completed": WorkItemStatus.DONE,
    }
    if v in aliases:
        return aliases[v]
    try:
        return WorkItemStatus(v)
    except ValueError:
        return None


def _resolve_item_types(raw: Optional[List[str]]) -> Optional[List[WorkItemType]]:
    if not raw:
        return None
    out: List[WorkItemType] = []
    for x in raw:
        if not isinstance(x, str):
            continue
        key = normalize_item_type(x.strip().lower())
        try:
            out.append(WorkItemType(key))
        except ValueError:
            continue
    return out or None


def distinct_project_ids_in_plan(plan: WorkspaceFetchPlan) -> List[str]:
    """Sorted unique project_ids from the planner output (for telemetry)."""
    seen: Set[str] = set()
    ordered: List[str] = []
    for q in plan.queries:
        pid = str(q.project_id)
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)
    return sorted(ordered)


def rows_per_project_counts(items: List[WorkItem]) -> Dict[str, int]:
    """Count fetched work items per project_id for telemetry."""
    counts: Dict[str, int] = {}
    for wi in items:
        pid = getattr(wi, "project_id", None)
        if pid is None:
            try:
                d = wi.model_dump(mode="json")
                pid = d.get("project_id")
            except Exception:
                pid = None
        key = str(pid) if pid else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _fetch_items_for_spec(
    board_service: Any,
    org_id: Optional[str],
    allowed_project_ids: Set[str],
    spec: FetchQuerySpec,
) -> Tuple[int, List[WorkItem]]:
    """Return (queries_run, items) for one plan spec; queries_run is 0 if skipped."""
    if spec.project_id not in allowed_project_ids:
        logger.debug(
            "targeted_fetch.skip_unauthorized_project project_id=%s", spec.project_id
        )
        return 0, []
    st = _resolve_status(spec.status)
    itypes = _resolve_item_types(spec.item_types)
    kwargs: Dict[str, Any] = {
        "project_id": spec.project_id,
        "org_id": org_id,
        "limit": spec.limit,
        "offset": 0,
        "sort_by": spec.sort_by if spec.sort_by in (
            "updated_at", "created_at", "priority", "title", "position", "due_date", "points",
        ) else "updated_at",
        "order": spec.order if spec.order in ("asc", "desc") else "desc",
    }
    if spec.board_id:
        kwargs["board_id"] = spec.board_id
    if st:
        kwargs["status"] = st
    if spec.parent_id:
        kwargs["parent_id"] = spec.parent_id
    if itypes:
        kwargs["item_types"] = itypes
    if spec.text_search:
        kwargs["text_search"] = spec.text_search
    try:
        batch = board_service.list_work_items(**kwargs)
    except TypeError:
        kwargs.pop("item_types", None)
        batch = board_service.list_work_items(**kwargs)
    if isinstance(batch, tuple):
        batch = batch[0]
    out: List[WorkItem] = []
    for item in batch or []:
        if hasattr(item, "item_id"):
            out.append(item)
    return 1, out


def execute_fetch_plan(
    *,
    board_service: Any,
    org_id: Optional[str],
    allowed_project_ids: Set[str],
    plan: WorkspaceFetchPlan,
) -> Tuple[List[WorkItem], int]:
    """Execute plan via BoardService.list_work_items; dedupe by item_id.

    Queries run in parallel per spec; merge preserves plan order and global row cap.
    """
    specs = plan.queries
    if not specs:
        return [], 0

    n = len(specs)
    per_spec: List[Optional[Tuple[int, List[WorkItem]]]] = [None] * n
    pending_idx: List[int] = []
    for idx, spec in enumerate(specs):
        if spec.project_id not in allowed_project_ids:
            per_spec[idx] = (0, [])
        else:
            pending_idx.append(idx)

    max_workers = min(8, max(1, len(pending_idx)))
    if pending_idx:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    _fetch_items_for_spec,
                    board_service,
                    org_id,
                    allowed_project_ids,
                    specs[idx],
                ): idx
                for idx in pending_idx
            }
            for fut in as_completed(future_map):
                idx = future_map[fut]
                per_spec[idx] = fut.result()

    seen: Set[str] = set()
    rows: List[WorkItem] = []
    queries_run = 0
    for idx in range(n):
        slot = per_spec[idx]
        if slot is None:
            continue
        qr, batch = slot
        queries_run += qr
        for item in batch:
            iid = str(item.item_id)
            if iid in seen:
                continue
            seen.add(iid)
            rows.append(item)
            if len(rows) >= _MAX_TOTAL_ROWS:
                return rows, queries_run
    return rows, queries_run


def format_fetched_items_for_prompt(items: List[WorkItem]) -> str:
    """Readable block for synthesis prompt."""
    lines: List[str] = []
    for wi in items:
        try:
            d = wi.model_dump(mode="json")
        except Exception:
            d = {"title": wi.title, "item_id": wi.item_id}
        uid = d.get("item_id")
        title = d.get("title")
        st = d.get("status")
        itype = d.get("item_type")
        pid = d.get("project_id")
        bid = d.get("board_id")
        parent = d.get("parent_id")
        upd = d.get("updated_at")
        crt = d.get("created_at")
        prog = d.get("progress_percent")
        cc = d.get("completed_child_count")
        tc = d.get("child_count")
        lines.append(
            f"- [{uid}] {title} | type={itype} status={st} project={pid} board={bid} "
            f"parent={parent} updated={upd} created={crt} "
            f"progress={prog}% children_done={cc}/{tc}"
        )
    return "\n".join(lines)


__all__ = [
    "PLANNER_SYSTEM_PROMPT",
    "WorkspaceFetchPlan",
    "FetchQuerySpec",
    "build_fetch_plan_from_chat_query_plan",
    "build_inventory_summary_text",
    "distinct_project_ids_in_plan",
    "execute_fetch_plan",
    "extract_allowed_project_ids",
    "format_fetched_items_for_prompt",
    "parse_workspace_fetch_plan",
    "rows_per_project_counts",
    "run_planner_llm",
]
