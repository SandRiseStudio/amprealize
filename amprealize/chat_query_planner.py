"""Fast bounded planner for Amprealize chat resource/action questions.

The planner emits a typed plan, not a final answer. Deterministic validation
then decides whether the plan can be executed, needs approval, or should ask for
clarification.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from amprealize.inventory_answer_service import InventoryAnswer
from amprealize.llm.types import LLMConfig
from amprealize.resource_analysis import (
    ResourceAnalysisAnswer,
    ResourceAnalysisIntent,
    ResourceQueryPlan,
)


class ChatPlanMode(str, Enum):
    """Top-level mode for a chat query plan."""

    ANSWER = "answer"
    ACTION = "action"
    CLARIFY = "clarify"
    DEEP_ANALYSIS = "deep_analysis"


class ChatPlanOperation(str, Enum):
    """Validated operations the chat planner may request."""

    LIST_RESOURCES = "list_resources"
    SUMMARIZE_RESOURCES = "summarize_resources"
    GROUP_RESOURCES = "group_resources"
    COMPARE_RESOURCES = "compare_resources"
    EXPLAIN_RESOURCE = "explain_resource"
    PROPOSE_ACTION = "propose_action"
    START_ACTION = "start_action"


class ChatResourceType(str, Enum):
    """Resource families supported by generic chat planning."""

    PROJECTS = "projects"
    BOARDS = "boards"
    WORK_ITEMS = "work_items"
    RUNS = "runs"
    AGENTS = "agents"
    GUIDES = "guides"
    WIKI = "wiki"
    BEHAVIORS = "behaviors"


class ChatPlanLatencyTier(str, Enum):
    """Planner latency budgets used for routing and telemetry."""

    INSTANT = "instant"
    FAST = "fast"
    ANALYSIS = "analysis"
    BACKGROUND = "background"


@dataclass(frozen=True)
class ChatQueryPlan:
    """A compact resource/action plan emitted before execution."""

    mode: ChatPlanMode
    operation: ChatPlanOperation
    resource_type: Optional[ChatResourceType] = None
    scope: Dict[str, Any] = field(default_factory=dict)
    topic: Optional[str] = None
    metrics: List[str] = field(default_factory=list)
    latency_tier: ChatPlanLatencyTier = ChatPlanLatencyTier.FAST
    requires_approval: bool = False
    confidence: float = 0.0
    clarification_question: Optional[str] = None
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a telemetry-safe dict representation."""

        return {
            "mode": self.mode.value,
            "operation": self.operation.value,
            "resource_type": self.resource_type.value if self.resource_type else None,
            "scope": dict(self.scope),
            "topic": self.topic,
            "metrics": list(self.metrics),
            "latency_tier": self.latency_tier.value,
            "requires_approval": self.requires_approval,
            "confidence": self.confidence,
            "clarification_question": self.clarification_question,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ChatPlanValidation:
    """Validation result for a parsed chat query plan."""

    valid: bool
    reason: str = ""
    requires_approval: bool = False
    requires_clarification: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "requires_approval": self.requires_approval,
            "requires_clarification": self.requires_clarification,
        }


@dataclass(frozen=True)
class ChatQueryPlanResult:
    """Planner output plus validation and observability metadata."""

    plan: Optional[ChatQueryPlan]
    validation: ChatPlanValidation
    source: str
    latency_ms: float
    fallback_reason: Optional[str] = None
    raw_response_preview: str = ""
    requested_model_id: Optional[str] = None
    resolved_provider: Optional[str] = None
    resolved_model: Optional[str] = None
    resolved_api_base: Optional[str] = None
    planner_timeout_seconds: Optional[float] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def telemetry_payload(self) -> Dict[str, Any]:
        """Compact telemetry representation without raw resource text."""

        plan = self.plan.to_dict() if self.plan else None
        return {
            "plan": plan,
            "validation": self.validation.to_dict(),
            "source": self.source,
            "latency_ms": self.latency_ms,
            "fallback_reason": self.fallback_reason,
            "requested_model_id": self.requested_model_id,
            "resolved_provider": self.resolved_provider,
            "resolved_model": self.resolved_model,
            "resolved_api_base": self.resolved_api_base,
            "planner_timeout_seconds": self.planner_timeout_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


class ChatQueryPlanValidator:
    """Deterministically validates LLM-suggested plans."""

    def __init__(self, *, minimum_confidence: float = 0.55) -> None:
        self.minimum_confidence = minimum_confidence

    def validate(
        self,
        plan: Optional[ChatQueryPlan],
        *,
        accessible_project_ids: Optional[Iterable[str]] = None,
    ) -> ChatPlanValidation:
        if plan is None:
            return ChatPlanValidation(
                valid=False,
                reason="No plan was produced.",
                requires_clarification=True,
            )
        if plan.confidence < self.minimum_confidence:
            return ChatPlanValidation(
                valid=False,
                reason="Planner confidence is below the execution threshold.",
                requires_clarification=True,
            )
        if plan.mode == ChatPlanMode.ACTION or plan.operation == ChatPlanOperation.START_ACTION:
            if not plan.requires_approval:
                return ChatPlanValidation(
                    valid=False,
                    reason="Action plans must require explicit approval.",
                    requires_approval=True,
                )
        allowed_projects: Set[str] = {str(pid) for pid in (accessible_project_ids or set())}
        scoped_project_id = str(plan.scope.get("project_id") or "").strip()
        if scoped_project_id and allowed_projects and scoped_project_id not in allowed_projects:
            return ChatPlanValidation(
                valid=False,
                reason="The requested project scope is not accessible.",
                requires_clarification=True,
            )
        if plan.mode in {ChatPlanMode.ANSWER, ChatPlanMode.DEEP_ANALYSIS}:
            if plan.resource_type is None:
                return ChatPlanValidation(
                    valid=False,
                    reason="Read-only answer plans must include a resource type.",
                    requires_clarification=True,
                )
        return ChatPlanValidation(valid=True, reason="Plan validated.")


class ChatQueryPlanner:
    """Bounded planner that interprets user chat into executable plans."""

    _PROJECT_LIST_RE = re.compile(r"\b(list|show|what|which)\b.*\bprojects?\b", re.I)
    _WORK_ITEM_LIST_RE = re.compile(
        r"\b(list|show|what|which)\b.*\b(work\s+items?|tasks?|bugs?)\b",
        re.I,
    )
    _ANALYSIS_HINT_RE = re.compile(
        r"\b(velocity|throughput|cycle\s+time|lead\s+time|median|p95|slow|slowing|blockers?)\b",
        re.I,
    )
    _RUN_LOOKUP_RE = re.compile(r"\b(run|execution)\b.*\b(status|phase|active|running)\b", re.I)
    _IMPLEMENTATION_STATUS_RE = re.compile(
        r"\b(have\s+we|already|implemented|done|built|shipped|complete(?:d)?)\b",
        re.I,
    )

    def __init__(
        self,
        *,
        validator: Optional[ChatQueryPlanValidator] = None,
        planner_timeout_seconds: float = 1.0,
    ) -> None:
        self.validator = validator or ChatQueryPlanValidator()
        self.planner_timeout_seconds = planner_timeout_seconds

    def plan_sync(
        self,
        *,
        user_message: str,
        inventory_summary: str,
        scope_hints: Mapping[str, Any],
        llm_client: Optional[Any],
        metadata: Mapping[str, Any],
        user_id: str,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        accessible_project_ids: Optional[Iterable[str]] = None,
    ) -> ChatQueryPlanResult:
        """Return a validated chat query plan using fallback first, then LLM."""

        started_at = time.monotonic()
        fallback = self._fallback_plan(user_message, scope_hints)
        if fallback is not None:
            validation = self.validator.validate(
                fallback,
                accessible_project_ids=accessible_project_ids,
            )
            return ChatQueryPlanResult(
                plan=fallback if validation.valid else None,
                validation=validation,
                source="fallback",
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
        if llm_client is None:
            fallback = self._implementation_status_fallback(user_message, scope_hints)
            if fallback is not None:
                validation = self.validator.validate(
                    fallback,
                    accessible_project_ids=accessible_project_ids,
                )
                return ChatQueryPlanResult(
                    plan=fallback if validation.valid else None,
                    validation=validation,
                    source="fallback",
                    latency_ms=(time.monotonic() - started_at) * 1000,
                    fallback_reason="llm_client_missing",
                )
            return ChatQueryPlanResult(
                plan=None,
                validation=ChatPlanValidation(
                    valid=False,
                    reason="No planner model is available.",
                    requires_clarification=True,
                ),
                source="unavailable",
                latency_ms=(time.monotonic() - started_at) * 1000,
                fallback_reason="llm_client_missing",
            )

        raw_response = ""
        requested_model_id = (metadata or {}).get("llm_model_id")
        planner_config = self._planner_llm_config(llm_client)
        resolved_metadata = self._resolved_model_metadata(
            llm_client=llm_client,
            requested_model_id=requested_model_id,
            config=planner_config,
            project_id=project_id,
            org_id=org_id,
            user_id=user_id,
            prefer_user_credential=(metadata or {}).get("credential_scope") == "user",
        )
        try:
            response = llm_client.call(
                self._planner_messages(user_message, inventory_summary, scope_hints),
                model=requested_model_id,
                org_id=org_id,
                project_id=project_id,
                user_id=user_id,
                prefer_user_credential=(metadata or {}).get("credential_scope") == "user",
                max_tokens=350,
                temperature=0,
                config=planner_config,
                actor={"id": user_id, "role": "user", "surface": "chat"},
            )
            raw_response = getattr(response, "content", None) or str(response)
            plan = parse_chat_query_plan(raw_response)
            validation = self.validator.validate(
                plan,
                accessible_project_ids=accessible_project_ids,
            )
            return ChatQueryPlanResult(
                plan=plan if validation.valid else None,
                validation=validation,
                source="llm",
                latency_ms=(time.monotonic() - started_at) * 1000,
                raw_response_preview=raw_response[:240],
                requested_model_id=requested_model_id,
                **resolved_metadata,
            )
        except Exception as exc:
            fallback = self._implementation_status_fallback(user_message, scope_hints)
            if fallback is not None:
                validation = self.validator.validate(
                    fallback,
                    accessible_project_ids=accessible_project_ids,
                )
                return ChatQueryPlanResult(
                    plan=fallback if validation.valid else None,
                    validation=validation,
                    source="fallback",
                    latency_ms=(time.monotonic() - started_at) * 1000,
                    fallback_reason=exc.__class__.__name__,
                    raw_response_preview=raw_response[:240],
                    requested_model_id=requested_model_id,
                    error_type=exc.__class__.__name__,
                    error_message=self._safe_error_message(exc),
                    **resolved_metadata,
                )
            return ChatQueryPlanResult(
                plan=None,
                validation=ChatPlanValidation(
                    valid=False,
                    reason=f"Planner failed: {exc}",
                    requires_clarification=True,
                ),
                source="error",
                latency_ms=(time.monotonic() - started_at) * 1000,
                fallback_reason=exc.__class__.__name__,
                raw_response_preview=raw_response[:240],
                requested_model_id=requested_model_id,
                error_type=exc.__class__.__name__,
                error_message=self._safe_error_message(exc),
                **resolved_metadata,
            )

    def _fallback_plan(
        self,
        user_message: str,
        scope_hints: Mapping[str, Any],
    ) -> Optional[ChatQueryPlan]:
        msg = user_message or ""
        scope = {k: v for k, v in dict(scope_hints or {}).items() if v}
        if self._PROJECT_LIST_RE.search(msg):
            return ChatQueryPlan(
                mode=ChatPlanMode.ANSWER,
                operation=ChatPlanOperation.LIST_RESOURCES,
                resource_type=ChatResourceType.PROJECTS,
                scope=scope,
                latency_tier=ChatPlanLatencyTier.INSTANT,
                confidence=0.9,
                rationale="Exact project list fallback.",
            )
        if self._WORK_ITEM_LIST_RE.search(msg):
            if self._ANALYSIS_HINT_RE.search(msg):
                return None
            return ChatQueryPlan(
                mode=ChatPlanMode.ANSWER,
                operation=ChatPlanOperation.LIST_RESOURCES,
                resource_type=ChatResourceType.WORK_ITEMS,
                scope=scope,
                latency_tier=ChatPlanLatencyTier.INSTANT,
                confidence=0.86,
                rationale="Exact work item list fallback.",
            )
        if self._RUN_LOOKUP_RE.search(msg):
            return ChatQueryPlan(
                mode=ChatPlanMode.ANSWER,
                operation=ChatPlanOperation.EXPLAIN_RESOURCE,
                resource_type=ChatResourceType.RUNS,
                scope=scope,
                metrics=["run_phase"],
                latency_tier=ChatPlanLatencyTier.INSTANT,
                confidence=0.82,
                rationale="Run status lookup fallback.",
            )
        return None

    def _implementation_status_fallback(
        self,
        user_message: str,
        scope_hints: Mapping[str, Any],
    ) -> Optional[ChatQueryPlan]:
        if not self._IMPLEMENTATION_STATUS_RE.search(user_message or ""):
            return None
        topic = self._topic_from_implementation_status_query(user_message)
        if not topic:
            return None
        scope = {k: v for k, v in dict(scope_hints or {}).items() if v}
        return ChatQueryPlan(
            mode=ChatPlanMode.ANSWER,
            operation=ChatPlanOperation.SUMMARIZE_RESOURCES,
            resource_type=ChatResourceType.WORK_ITEMS,
            scope=scope,
            topic=topic,
            metrics=["status_breakdown", "matching_items"],
            latency_tier=ChatPlanLatencyTier.INSTANT,
            confidence=0.84,
            rationale="Generic implementation status fallback over work items.",
        )

    @staticmethod
    def _topic_from_implementation_status_query(message: str) -> Optional[str]:
        text = re.sub(r"\s+", " ", message or "").strip(" ?.")
        if not text:
            return None
        text = re.sub(r"\bfrom\s+the\s+[\w -]+\s+project,?\s*", "", text, flags=re.I)
        text = re.sub(r"\bin\s+the\s+[\w -]+\s+project,?\s*", "", text, flags=re.I)
        patterns = [
            r"\bimplemented\s+(.+)$",
            r"\bbuilt\s+(.+)$",
            r"\bshipped\s+(.+)$",
            r"\bcompleted\s+(.+)$",
            r"\bdone\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                topic = match.group(1).strip(" ?.").lower()
                if topic and topic not in {"it", "this", "that"}:
                    return topic
        return None

    @staticmethod
    def _planner_messages(
        user_message: str,
        inventory_summary: str,
        scope_hints: Mapping[str, Any],
    ) -> List[Dict[str, str]]:
        schema = {
            "mode": [mode.value for mode in ChatPlanMode],
            "operation": [op.value for op in ChatPlanOperation],
            "resource_type": [rtype.value for rtype in ChatResourceType],
            "latency_tier": [tier.value for tier in ChatPlanLatencyTier],
        }
        return [
            {
                "role": "system",
                "content": (
                    "Return ONLY compact JSON for an Amprealize chat query plan. "
                    "Do not answer the user. Choose the smallest read-only operation "
                    "that can answer the question. For project-board progress questions, "
                    "use summarize_resources over work_items with topic and status_breakdown. "
                    "Action plans must set requires_approval=true."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": user_message[:2000],
                        "inventory_summary": inventory_summary[:3000],
                        "scope_hints": dict(scope_hints or {}),
                        "allowed_schema": schema,
                    },
                    sort_keys=True,
                ),
            },
        ]

    def _planner_llm_config(self, llm_client: Any) -> LLMConfig:
        base = getattr(llm_client, "_default_config", None) or LLMConfig.from_env()
        return replace(
            base,
            timeout=self.planner_timeout_seconds,
            max_tokens=min(350, base.max_tokens),
            temperature=0,
            max_retries=0,
        )

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc).strip()
        if len(message) > 240:
            message = f"{message[:237]}..."
        return message

    @staticmethod
    def _resolved_model_metadata(
        *,
        llm_client: Any,
        requested_model_id: Optional[str],
        config: LLMConfig,
        project_id: Optional[str],
        org_id: Optional[str],
        user_id: str,
        prefer_user_credential: bool,
    ) -> Dict[str, Any]:
        resolved = config
        resolver = getattr(llm_client, "_resolve_config", None)
        if callable(resolver):
            try:
                resolved = resolver(
                    config,
                    requested_model_id,
                    project_id,
                    org_id,
                    user_id,
                    prefer_user_credential,
                )
            except Exception:
                resolved = config
        provider = getattr(resolved, "provider", None)
        provider_value = getattr(provider, "value", None) or (str(provider) if provider is not None else None)
        return {
            "resolved_provider": provider_value,
            "resolved_model": getattr(resolved, "model", None),
            "resolved_api_base": getattr(resolved, "api_base", None),
            "planner_timeout_seconds": getattr(resolved, "timeout", None),
        }


def parse_chat_query_plan(raw: str) -> ChatQueryPlan:
    """Parse strict JSON into a typed chat query plan."""

    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        raise ValueError("Planner response must be a JSON object.")
    try:
        mode = ChatPlanMode(str(data.get("mode") or "answer"))
        operation = ChatPlanOperation(str(data["operation"]))
        raw_resource_type = data.get("resource_type")
        resource_type = (
            ChatResourceType(str(raw_resource_type)) if raw_resource_type else None
        )
        latency_tier = ChatPlanLatencyTier(str(data.get("latency_tier") or "fast"))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unsupported planner field: {exc}") from exc
    raw_metrics = data.get("metrics") or []
    metrics = [str(item) for item in raw_metrics if isinstance(item, str)]
    raw_scope = data.get("scope") or {}
    scope = dict(raw_scope) if isinstance(raw_scope, dict) else {}
    return ChatQueryPlan(
        mode=mode,
        operation=operation,
        resource_type=resource_type,
        scope=scope,
        topic=str(data.get("topic") or "").strip() or None,
        metrics=metrics,
        latency_tier=latency_tier,
        requires_approval=bool(data.get("requires_approval", False)),
        confidence=_coerce_confidence(data.get("confidence")),
        clarification_question=str(data.get("clarification_question") or "").strip()
        or None,
        rationale=str(data.get("rationale") or "").strip(),
    )


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
        if match:
            text = match.group(1).strip()
    return json.loads(text)


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return confidence


def chat_plan_to_resource_query_plan(plan: ChatQueryPlan) -> ResourceQueryPlan:
    """Convert a validated chat plan into a ResourceAnalysisService plan."""

    if plan.resource_type is None:
        raise ValueError("Chat plan has no resource_type to execute.")
    filters: Dict[str, Any] = {}
    if plan.topic and plan.resource_type == ChatResourceType.WORK_ITEMS:
        filters["text_search"] = plan.topic
    return ResourceQueryPlan(
        intent=_resource_intent_for_operation(plan.operation),
        resource_type=plan.resource_type.value,
        filters=filters,
        group_by="status" if plan.operation == ChatPlanOperation.GROUP_RESOURCES else None,
        llm_assisted=True,
        rationale=plan.rationale or "Planned by fast chat query planner.",
    )


def render_chat_plan_resource_answer(
    plan: ChatQueryPlan,
    answer: ResourceAnalysisAnswer,
) -> InventoryAnswer:
    """Render a resource analysis result through the chat plan's requested shape."""

    if (
        plan.resource_type == ChatResourceType.WORK_ITEMS
        and plan.topic
        and "status_breakdown" in set(plan.metrics)
    ):
        return _render_work_item_status_breakdown(plan, answer)
    payload = dict(answer.structured_payload)
    payload["chat_query_plan"] = plan.to_dict()
    return InventoryAnswer(
        content=answer.content,
        answer_type=answer.answer_type,
        structured_payload=payload,
        source_rows=list(answer.source_rows),
        trace_steps=list(answer.trace_steps),
        requires_clarification=answer.requires_clarification,
    )


def _resource_intent_for_operation(operation: ChatPlanOperation) -> ResourceAnalysisIntent:
    if operation == ChatPlanOperation.LIST_RESOURCES:
        return ResourceAnalysisIntent.LIST
    if operation == ChatPlanOperation.GROUP_RESOURCES:
        return ResourceAnalysisIntent.GROUP
    if operation == ChatPlanOperation.COMPARE_RESOURCES:
        return ResourceAnalysisIntent.ANALYZE
    if operation == ChatPlanOperation.EXPLAIN_RESOURCE:
        return ResourceAnalysisIntent.SUMMARIZE
    return ResourceAnalysisIntent.SUMMARIZE


def _render_work_item_status_breakdown(
    plan: ChatQueryPlan,
    answer: ResourceAnalysisAnswer,
) -> InventoryAnswer:
    rows = list(answer.source_rows)
    status_counts = Counter(_status_value(row.get("status")) for row in rows)
    project_label = str(
        plan.scope.get("project_name")
        or plan.scope.get("project_label")
        or plan.scope.get("project_id")
        or "this scope"
    )
    topic = str(plan.topic or "that topic")
    lines = [
        f"For {project_label}, I found {len(rows)} work items related to {topic}.",
    ]
    if rows:
        status_summary = ", ".join(
            f"{status}: {count}"
            for status, count in sorted(status_counts.items(), key=lambda item: item[0])
        )
        lines.append(f"Status breakdown: {status_summary}.")
        lines.append(f"The board indicates this is {_completion_bucket(status_counts)}.")
        lines.append("Related work items:")
        for row in rows[:10]:
            title = str(row.get("title") or row.get("name") or "(untitled)")
            item_id = str(row.get("item_id") or row.get("id") or "").strip()
            status = _status_value(row.get("status"))
            id_part = f" `{item_id}`" if item_id else ""
            lines.append(f"- {title}{id_part} · `{status}`")
        remaining = len(rows) - 10
        if remaining > 0:
            lines.append(f"...and {remaining} more.")
    else:
        lines.append(
            "I can't confirm progress from the board because no matching work items were found."
        )
    payload = dict(answer.structured_payload)
    payload["chat_query_plan"] = plan.to_dict()
    payload["chat_query_result"] = {
        "status_counts": dict(status_counts),
        "completion_bucket": _completion_bucket(status_counts),
        "related_work_item_count": len(rows),
        "related_work_items": [
            {
                "id": str(row.get("item_id") or row.get("id") or ""),
                "title": str(row.get("title") or row.get("name") or ""),
                "status": _status_value(row.get("status")),
            }
            for row in rows[:10]
        ],
    }
    payload["card_kind"] = "resource_analysis"
    return InventoryAnswer(
        content="\n".join(lines),
        answer_type="work_items.planned_summary",
        structured_payload=payload,
        source_rows=rows,
        trace_steps=list(answer.trace_steps),
        requires_clarification=answer.requires_clarification,
    )


def _status_value(value: Any) -> str:
    status = getattr(value, "value", value)
    return str(status or "unknown").strip() or "unknown"


def _completion_bucket(status_counts: Mapping[str, int]) -> str:
    total = sum(status_counts.values())
    if total <= 0:
        return "unknown"
    done = sum(
        count
        for status, count in status_counts.items()
        if status.lower() in {"done", "completed", "closed"}
    )
    if done == total:
        return "complete"
    if done > 0:
        return "partially complete"
    return "not started"


__all__ = [
    "ChatPlanLatencyTier",
    "ChatPlanMode",
    "ChatPlanOperation",
    "ChatPlanValidation",
    "ChatQueryPlan",
    "ChatQueryPlanner",
    "ChatQueryPlanResult",
    "ChatQueryPlanValidator",
    "ChatResourceType",
    "chat_plan_to_resource_query_plan",
    "parse_chat_query_plan",
    "render_chat_plan_resource_answer",
]
