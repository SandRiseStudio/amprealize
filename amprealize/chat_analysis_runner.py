"""Bounded multi-query workspace analysis for chat (read-only).

Layer-2 optional path: planner LLM proposes short sub-queries; each is executed
in-process via ResourceAnalysisService.answer_sync (no loopback HTTP).

Following `behavior_harden_service_boundaries` (Student).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from amprealize.chat_action_router import ChatWorkspaceIntent
from amprealize.feature_flags import FeatureFlagService
from amprealize.inventory_answer_service import InventoryAnswer
from amprealize.resource_analysis import ResourceAnalysisService
from amprealize.session_audit import GovernedChatAuditLogger

logger = logging.getLogger(__name__)

_MUTATE_PATTERN = re.compile(
    r"\b(create|add|make|execute|run|start|dispatch|trigger|update|set|delete|remove|cancel|stop)\b",
    re.IGNORECASE,
)


def _workspace_inventory_meaningful(inventory: Dict[str, Any]) -> bool:
    if not inventory:
        return False
    projects = inventory.get("projects") or []
    if isinstance(projects, list) and len(projects) > 0:
        return True
    wip = inventory.get("work_items_by_project") or {}
    if isinstance(wip, dict):
        for _pid, rows in wip.items():
            if isinstance(rows, list) and len(rows) > 0:
                return True
    return False


def _looks_mutating(message: str) -> bool:
    return bool(_MUTATE_PATTERN.search(message or ""))


def _extract_sub_queries(planner_text: str, fallback: str) -> List[str]:
    raw = (planner_text or "").strip()
    if not raw:
        return [fallback]
    try:
        if raw.startswith("```"):
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [fallback]
    if not isinstance(data, dict):
        return [fallback]
    sq = data.get("sub_queries") or data.get("queries")
    if not isinstance(sq, list):
        return [fallback]
    out: List[str] = []
    for item in sq[:3]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:500])
    return out or [fallback]


@dataclass
class ChatAnalysisRunner:
    """Optional bounded analysis loop for chat (Layer 2)."""

    resource_analysis_service: ResourceAnalysisService
    feature_flags: FeatureFlagService
    max_sub_queries: int = 3

    async def try_answer(
        self,
        *,
        user_message: str,
        user_id: str,
        conversation_id: str,
        message_id: str,
        inventory: Dict[str, Any],
        scope_hints: Dict[str, Any],
        chat_query_intent: str,
        route_requires_clarification: bool,
        llm_client: Any,
        metadata: Dict[str, Any],
        audit: Optional[GovernedChatAuditLogger],
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        execution_observability: Optional[Dict[str, Any]] = None,
    ) -> Optional[InventoryAnswer]:
        """Return an InventoryAnswer when sub-queries surface a resource analysis hit."""

        if llm_client is None:
            return None
        if route_requires_clarification:
            return None
        if _looks_mutating(user_message):
            return None
        if chat_query_intent not in {
            ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
            ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value,
        }:
            return None
        if not self.feature_flags.is_enabled(
            "feature.chat_analysis_runner",
            {"user_id": user_id or ""},
        ):
            return None
        if not _workspace_inventory_meaningful(inventory):
            return None

        model_id = (metadata or {}).get("llm_model_id")
        prefer_user_credential = (metadata or {}).get("credential_scope") == "user"

        if chat_query_intent == ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value:
            planner_system = (
                "You help decompose questions about which project, board, or workspace scope "
                "into up to 3 short English sub-queries. Each sub-query must be answerable by a "
                "deterministic counter/list over projects, boards, work items, or runs "
                "(no SQL, no code). Return ONLY compact JSON: "
                '{"sub_queries":["first question","optional second",...]} '
                "Use an empty array if the message is not about scoping or inventory."
            )
        else:
            planner_system = (
                "You help decompose a user's analytics-style workspace question into "
                "up to 3 short English sub-queries. Each sub-query must be answerable by a "
                "deterministic counter/list over projects, boards, and work items (no SQL, "
                "no code). Return ONLY compact JSON: "
                '{"sub_queries":["first question","optional second",...]} '
                "Use empty array if the message is not analytic."
            )

        planner_messages = [
            {"role": "system", "content": planner_system},
            {"role": "user", "content": user_message[:4000]},
        ]

        try:
            planner_resp = await asyncio.to_thread(
                llm_client.call,
                planner_messages,
                model=model_id,
                project_id=project_id,
                org_id=org_id,
                user_id=user_id,
                prefer_user_credential=prefer_user_credential,
                max_tokens=400,
                temperature=0,
                execution_observability=execution_observability,
                actor={"id": user_id, "role": "user", "surface": "chat"},
            )
            planner_text = getattr(planner_resp, "content", None) or str(planner_resp)
        except Exception as exc:
            logger.warning("chat_analysis_runner.planner_failed err=%s", exc)
            return None

        sub_queries = _extract_sub_queries(planner_text, user_message)[: self.max_sub_queries]
        cells: List[Dict[str, Any]] = []
        best: Optional[InventoryAnswer] = None

        for idx, sub_q in enumerate(sub_queries):
            cell_id = f"c{idx + 1}"
            if audit:
                audit.log_tool_call(
                    user_id=user_id,
                    action="chat.analysis_runner.sub_query",
                    decision="allow",
                    conversation_id=conversation_id,
                    message_id=message_id,
                    execution_observability=execution_observability or {},
                    metadata={"sub_query": sub_q, "cell_id": cell_id},
                    target_resources=[{"type": "resource_analysis", "id": cell_id}],
                )
            try:
                ra = await asyncio.to_thread(
                    lambda q=sub_q: self.resource_analysis_service.answer_sync(
                        query=q,
                        inventory=inventory,
                        scope_hints=scope_hints,
                    )
                )
            except Exception as exc:
                logger.warning("chat_analysis_runner.answer_sync_failed err=%s", exc)
                cells.append(
                    {
                        "id": cell_id,
                        "kind": "query",
                        "input": sub_q,
                        "status": "error",
                        "detail": str(exc)[:200],
                    }
                )
                continue

            if ra is None:
                cells.append(
                    {
                        "id": cell_id,
                        "kind": "query",
                        "input": sub_q,
                        "status": "miss",
                    }
                )
                continue

            inv = InventoryAnswer(
                content=ra.content,
                answer_type=ra.answer_type,
                structured_payload=dict(ra.structured_payload),
                source_rows=list(ra.source_rows),
                trace_steps=list(ra.trace_steps),
                requires_clarification=ra.requires_clarification,
            )
            cells.append(
                {
                    "id": cell_id,
                    "kind": "query",
                    "input": sub_q,
                    "status": "ok",
                    "answer_type": inv.answer_type,
                }
            )
            if best is None:
                best = inv

        if best is None:
            return None

        payload = dict(best.structured_payload)
        payload["analysis_run"] = {"cells": cells}
        return InventoryAnswer(
            content=best.content,
            answer_type=best.answer_type,
            structured_payload=payload,
            source_rows=list(best.source_rows),
            trace_steps=list(best.trace_steps),
            requires_clarification=best.requires_clarification,
        )


__all__ = ["ChatAnalysisRunner"]
