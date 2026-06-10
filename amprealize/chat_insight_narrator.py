"""Optional LLM narration for deterministic resource-analysis replies.

Interprets already-computed structured_payload only — no new numeric facts.
Following `behavior_harden_service_boundaries` (Student): no loopback HTTP;
single in-process LLM call with a tight system contract.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from amprealize.chat_action_router import ChatWorkspaceIntent
from amprealize.feature_flags import FeatureFlagService

logger = logging.getLogger(__name__)

_MAX_NARRATION_CHARS = 1200


def _safe_narration_payload(structured_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Strip bulky / sensitive fields before sending to the narrator model."""

    qp = structured_payload.get("query_plan")
    if hasattr(qp, "to_dict"):
        qp = qp.to_dict()
    return {
        "card_kind": structured_payload.get("card_kind"),
        "summary": structured_payload.get("summary"),
        "title": structured_payload.get("title"),
        "analysis_mode": structured_payload.get("analysis_mode"),
        "query_plan": qp if isinstance(qp, dict) else None,
        "insights": structured_payload.get("insights"),
        "empty_reason": structured_payload.get("empty_reason"),
    }


def _narrator_should_run(
    *,
    structured_payload: Dict[str, Any],
    chat_query_intent: str,
    feature_flags: FeatureFlagService,
    user_id: str,
) -> bool:
    if not feature_flags.is_enabled(
        "feature.chat_insight_narrator",
        {"user_id": user_id or ""},
    ):
        return False
    if structured_payload.get("card_kind") != "resource_analysis":
        return False
    if chat_query_intent == ChatWorkspaceIntent.ANALYTICS_OR_RATE.value:
        return True
    insights = structured_payload.get("insights")
    if isinstance(insights, dict) and insights:
        return True
    if isinstance(insights, dict) and insights.get("by_item_type"):
        return True
    return False


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def maybe_append_insight_narration(
    *,
    structured_payload: Dict[str, Any],
    user_message: str,
    chat_query_intent: str,
    llm_client: Any,
    feature_flags: FeatureFlagService,
    user_id: str,
    org_id: Optional[str],
    project_id: Optional[str],
    model_id: Optional[str],
    prefer_user_credential: bool,
    execution_observability: Optional[Dict[str, Any]] = None,
) -> str:
    """Return extra prose to append after the deterministic answer (may be empty)."""

    if llm_client is None:
        return ""
    if not _narrator_should_run(
        structured_payload=structured_payload,
        chat_query_intent=chat_query_intent,
        feature_flags=feature_flags,
        user_id=user_id,
    ):
        return ""

    payload = _safe_narration_payload(structured_payload)
    system = (
        "You are a concise analytics coach for workspace data. "
        "You ONLY interpret the JSON facts the user already received — do not invent "
        "counts, percentages, dates, or entities that are not explicitly present in the JSON. "
        "If the JSON is thin, give 1–2 short follow-up questions they could ask next. "
        "Write at most two short paragraphs, plain text, no markdown headings, no bullet lists "
        "longer than 3 items."
    )
    user_block = json.dumps(
        {
            "user_question": user_message,
            "structured_facts": payload,
        },
        sort_keys=True,
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_block},
    ]
    try:
        response = llm_client.call(
            messages,
            model=model_id,
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
            prefer_user_credential=prefer_user_credential,
            max_tokens=400,
            temperature=0.2,
            execution_observability=execution_observability,
            actor={"id": user_id, "role": "user", "surface": "chat"},
        )
    except Exception as exc:
        logger.warning("chat_insight_narrator.llm_failed err=%s", exc)
        return ""

    text = getattr(response, "content", None) or str(response)
    text = (text or "").strip()
    if not text:
        return ""
    # Reject accidental JSON-only replies from the model
    if text.startswith("{") and _extract_json_object(text) is not None:
        return ""
    if len(text) > _MAX_NARRATION_CHARS:
        text = text[: _MAX_NARRATION_CHARS - 1].rstrip() + "…"
    return f"\n\n{text}"


__all__ = ["maybe_append_insight_narration"]
