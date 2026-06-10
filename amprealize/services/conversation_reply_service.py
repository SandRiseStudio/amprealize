"""ConversationReplyService — Orchestrates agent replies in conversations.

This service bridges the conversation system with AI-powered response generation:
1. Receives user message context
2. Calls ContextComposer to assemble relevant context
3. Invokes LLM to generate response with composed context
4. Stores agent reply via ConversationService
5. Emits token stream via ConversationEventHub for SSE

Flow:
    User message -> ContextComposer.compose() -> LLM call -> ConversationService.send_message()

AMPREALIZE-581: Integrate ContextComposer with agent execution loop for conversation replies.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from amprealize.chat_action_router import (
    ChatActionCategory,
    ChatActionRouteRequest,
    ChatActionRouteResult,
    ChatRouteGateway,
    ChatRouteMode,
    ChatWorkspaceIntent,
    detect_chat_workspace_intent,
    enrich_chat_routing_metadata,
)
from amprealize.chat_inventory_fast_path_policy import (
    should_use_workspace_inventory_fast_path,
    targeted_fetch_warranted,
)
from amprealize.chat_query_planner import (
    ChatPlanMode,
    ChatQueryPlanner,
    chat_plan_to_resource_query_plan,
    render_chat_plan_resource_answer,
)
from amprealize.chat_resource_actions import (
    ChatResourceActionId,
    ChatResourceActionRegistry,
    ChatResourceActionRequest,
)
from amprealize.chat_analysis_runner import ChatAnalysisRunner
from amprealize.chat_insight_narrator import maybe_append_insight_narration
from amprealize.chat_workspace_targeted_fetch import (
    build_fetch_plan_from_chat_query_plan,
    build_inventory_summary_text,
    distinct_project_ids_in_plan,
    execute_fetch_plan,
    extract_allowed_project_ids,
    format_fetched_items_for_prompt,
    rows_per_project_counts,
    run_planner_llm,
)
from amprealize.workspace_activity import (
    build_workspace_activity_appendix,
    disclosure_required,
    fairness_mode_for_inventory,
    summarize_project_activity,
)
from amprealize.chat_transcript import (
    THREAD_SUMMARY_METADATA_KEY,
    TranscriptBuildResult,
    build_transcript_openai_messages,
    merge_system_and_transcript,
)
from amprealize.context_composer import (
    ComposedContext,
    ContextComposer,
    DataSourceType,
    TokenBudget,
    default_token_budget,
)
from amprealize.conversation_contracts import (
    ActorType,
    ConversationScope,
    MessageType,
    ParticipantRole,
    is_global_workspace_scope,
)

_WORK_ITEM_SLOT_ASSISTANT_MARKERS = (
    "what should i call",
    "what should we call",
    "which project or board should i create",
    "please clarify the work item",
    "i found the project, but i need a board",
    "i still need a board",
    "which board should",
    "need a board before i can create",
)
from amprealize.conversation_event_hub import (
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_REPLY_COMPLETE,
    EVENT_REPLY_ERROR,
    EVENT_REPLY_STARTED,
    EVENT_REPLY_STEP,
    EVENT_REPLY_TOKEN,
    EVENT_TOKEN,
    ConversationEventHub,
)
from amprealize.execution_observability import sanitize_observability_payload
from amprealize.observability_tracing import (
    TraceContext,
    Tracer,
    attach_trace_context,
    detach_trace_context,
)
from amprealize.feature_flags import FeatureFlagService
from amprealize.global_chat_context import build_chat_context_composer
from amprealize.inventory_answer_service import InventoryAnswer, InventoryAnswerService
from amprealize.observability_chat import ObservabilityChatAnswerService
from amprealize.platform_management_actions import PlatformManagementActionService
from amprealize.projects.service import OSSProjectService
from amprealize.resource_analysis import ResourceAnalysisService
from amprealize.session_audit import GovernedChatAuditEventType, GovernedChatAuditLogger

logger = logging.getLogger(__name__)

_STREAM_ERR_ATTR = "_stream_provider_error_class"

# Known-good model the reply stream falls back to when the user-selected model's
# endpoint is unresponsive (e.g. an overloaded NVIDIA NIM free model). Fallback only
# triggers when the primary attempt failed before emitting any tokens, so a partially
# streamed reply is never duplicated. Override via env for operators.
_REPLY_FALLBACK_MODEL_ID = os.environ.get(
    "AMPREALIZE_CHAT_REPLY_FALLBACK_MODEL_ID", "nvidia-llama-3-3-70b-instruct"
).strip()

# Shown when the LLM stream completes with no usable text (and as a last-resort persist guard).
_EMPTY_LLM_REPLY_PLACEHOLDER = (
    "The model returned no text for this reply. "
    "Try again, switch to a different model, or rephrase your question."
)
# Used when routing marks clarification required but the router omitted a prompt string.
_CLARIFICATION_BODY_FALLBACK = (
    "Please clarify what you would like Amprealize Chat to do next."
)

# Pronouns and phrases that reference the prior assistant message's result set.
# When a message only (or mostly) contains these, the LLM should use transcript
# context rather than issuing a generic clarification prompt.
_REFERENTIAL_PRONOUNS = frozenset(
    {
        "these",
        "those",
        "it",
        "them",
        "this",
        "that board",
        "that list",
        "that project",
        "that run",
        "any of these",
        "any of them",
        "any of those",
        "which of these",
        "which of them",
        "which of those",
        "completed?",
        "done?",
        "finished?",
        "status?",
    }
)

# Short meta-correction phrases a user sends to push back on a bad or
# clarification-only reply.  The LLM should synthesize a response using
# transcript context rather than short-circuiting to another clarification.
_META_CORRECTION_PHRASES = frozenset(
    {
        "i'm asking you a question",
        "im asking you a question",
        "i am asking you a question",
        "i asked you a question",
        "that's not what i asked",
        "thats not what i asked",
        "that was a question",
        "answer my question",
        "please answer",
        "you didn't answer",
        "you did not answer",
        "not what i asked",
    }
)


def _is_referential_followup(message: str) -> bool:
    """Return True when the message is short and refers to a prior result set."""
    normalized = " ".join(message.strip().lower().split())
    if not normalized:
        return False
    # A very short message that consists mostly of referential pronouns
    if len(normalized) <= 40 and any(
        normalized.startswith(phrase) or normalized == phrase
        for phrase in _REFERENTIAL_PRONOUNS
    ):
        return True
    # Ends with a referential question mark phrase
    if any(normalized.endswith(phrase) for phrase in {"completed?", "done?", "finished?", "status?"}):
        return True
    return False


def _is_meta_correction(message: str) -> bool:
    """Return True when the user is correcting/redirecting a bad clarification reply."""
    normalized = " ".join(message.strip().lower().split())
    return any(phrase in normalized for phrase in _META_CORRECTION_PHRASES)

# Principal-level DS guidance appended to chat system prompts when data-heavy context is detected.
_PRINCIPAL_DS_MESSAGE_HINT = re.compile(
    r"\b(insight|insights|dashboard|cohort|segmentation|"
    r"visualization|visualisation|visualize|"
    r"\bsql\b|query (the )?data|metric definition|drift|"
    r"a/b test|ab test|hypothesis|population|sample bias|leakage|"
    r"feature importance|correlation|causation|confidence interval|"
    r"p-value|distribution|funnel|retention|root cause)\b",
    re.IGNORECASE,
)

PRINCIPAL_DS_SYSTEM_SUFFIX = (
    "## Principal data science operating mode\n"
    "- Work through: clarify the question → define population and metric → "
    "validate data fit → reproducible query/aggregation → analysis → "
    "visualization → limitations → recommended actions.\n"
    "- Separate correlation from causation; state assumptions, confidence, and data gaps explicitly.\n"
    "- For stakeholders use: claim → evidence → risks → decision ask.\n"
    "When depth is needed, align with `behavior_principal_data_science_workflow` and "
    "`amprealize/agents/playbooks/AGENT_DATA_SCIENCE.md`."
)


def _telemetry_failure_metadata(exc: BaseException) -> Dict[str, Any]:
    """Error class names for chat telemetry: wrapper vs provider or exception chain."""
    meta: Dict[str, Any] = {"error_class": exc.__class__.__name__}
    prov = getattr(exc, _STREAM_ERR_ATTR, None)
    if isinstance(prov, str) and prov.strip():
        meta["provider_error_class"] = prov.strip()
        return meta
    root = exc
    while root.__cause__ is not None:
        root = root.__cause__
    if root is not exc:
        meta["provider_error_class"] = root.__class__.__name__
    return meta


@dataclass
class ReplyRequest:
    """Request to generate an agent reply in a conversation."""

    conversation_id: str
    """ID of the conversation where the agent should reply."""

    user_message_id: str
    """ID of the user message being replied to."""

    user_message_content: str
    """Content of the user message (used for relevance scoring)."""

    user_id: str
    """ID of the user who sent the message."""

    agent_id: str = "amprealize-agent"
    """ID of the agent generating the reply."""

    work_item_id: Optional[str] = None
    """Optional work item context."""

    run_id: Optional[str] = None
    """Optional run context."""

    org_id: Optional[str] = None
    """Organization ID for multi-tenant isolation."""

    project_id: Optional[str] = None
    """Project ID for context scoping."""

    system_prompt_override: Optional[str] = None
    """Optional override for the system prompt."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata for the reply."""

    stream_message_id: Optional[str] = None
    """Stable stream id used from scheduling through final persistence."""


@dataclass
class ReplyResult:
    """Result of generating an agent reply."""

    message_id: str
    """ID of the generated message."""

    content: str
    """Generated reply content."""

    conversation_id: str
    """Conversation where the reply was posted."""

    composed_context: ComposedContext
    """Context that was composed for generation."""

    token_count: int
    """Number of tokens in the generated response."""

    latency_ms: float
    """Total latency in milliseconds."""

    success: bool = True
    """Whether the reply was successful."""

    error: Optional[str] = None
    """Error message if failed."""


class ConversationReplyService:
    """Orchestrates context-aware agent replies in conversations.

    This service integrates:
    - ContextComposer: Assembles project context for grounding
    - LLM Client: Generates responses
    - ConversationService: Persists messages
    - ConversationEventHub: Streams tokens via SSE
    """

    # Default system prompt for conversational replies
    DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant with full context about the user's project.

Filesystem vs execution: This chat reply is generated as text in Amprealize; it does not by itself open or edit paths on the user's machine. Separately, **work-item or governed agent runs** can use **local_connector** when the user has paired the local connector daemon and enabled local workspace execution—those runs may run file/shell tools on the paired device inside a run lease. Projects may store an optional **local project path** for local workflows. If the user asks whether you can edit local files, explain this distinction instead of denying all local access.

Use the provided context to give accurate, relevant answers:
- Reference specific work items, runs, or conversations when relevant
- If you cite information from the context, mention the source
- If the question is about something not in the context, say so
- Respond directly — never show planning, reasoning, or intermediate steps; start with the answer itself
- Open with a direct 1–2 sentence answer or recommendation, then supporting detail
- For prioritization questions ("what should I work on?"): recommend the single best next item in the first sentence, then ≤150 words justifying it. Reason like a senior staff engineer triaging a backlog — weigh, in roughly this order: explicit priority/severity (critical/urgent/P0–P1), blocked or blocking status and dependencies, items already in progress or in review (finish before starting new work), approaching or overdue deadlines, items assigned to the user, and only then recency or staleness. Do NOT default to "the most recently updated item" — recency alone is the weakest signal. State the specific signals that drove the choice (e.g. "P1 and blocking two other items"), and if the context lacks priority/status/deadline signals to judge well, say so and recommend what to check rather than guessing.
- Use bullet lists only for 3+ distinct items; prose for 1–2
- Reference specific IDs (work item IDs, project IDs) using their exact identifiers

{context}"""

    @staticmethod
    def _should_inject_principal_ds_guidance(request: ReplyRequest) -> bool:
        """True when chat should apply principal-level data science operating principles."""
        if request.system_prompt_override:
            return False
        md = request.metadata or {}
        if md.get("principal_data_science") is True:
            return True
        fk = md.get("function_key") or md.get("work_item_function_key")
        if fk == "data_science":
            return True
        msg = request.user_message_content or ""
        intent = detect_chat_workspace_intent(msg)
        if intent in (
            ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
            ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value,
        ):
            return True
        if _PRINCIPAL_DS_MESSAGE_HINT.search(msg):
            return True
        return False

    def __init__(
        self,
        *,
        context_composer: Optional[ContextComposer] = None,
        conversation_service: Optional[Any] = None,  # ConversationService
        llm_client: Optional[Any] = None,  # LLMClient
        event_hub: Optional[ConversationEventHub] = None,
        telemetry: Optional[Any] = None,
        route_gateway: Optional[ChatRouteGateway] = None,
        governed_chat_audit: Optional[GovernedChatAuditLogger] = None,
        platform_management_service: Optional[PlatformManagementActionService] = None,
        resource_action_registry: Optional[ChatResourceActionRegistry] = None,
        resource_analysis_service: Optional[ResourceAnalysisService] = None,
        observability_answer_service: Optional[ObservabilityChatAnswerService] = None,
        board_service: Optional[Any] = None,
        reply_project_service: Optional[Any] = None,
        local_execution_connector_hub: Optional[Any] = None,
    ):
        """Initialize ConversationReplyService.

        Args:
            context_composer: Composer for assembling context
            conversation_service: Service for message CRUD
            llm_client: Client for LLM calls
            event_hub: Hub for token streaming events
            telemetry: Telemetry client
            reply_project_service: Optional ``OrganizationService`` / ``OSSProjectService`` with
                ``get_project`` for ``local_project_path`` snapshot in composed context.
            local_execution_connector_hub: Optional hub for connector socket presence; when
                omitted, ``get_local_execution_connector_hub()`` is used if importable.
        """
        self._composer = context_composer or ContextComposer()
        self._conversation_service = conversation_service
        self._llm_client = llm_client
        self._event_hub = event_hub
        self._telemetry = telemetry
        self._tracer = Tracer(telemetry)
        self._route_gateway = route_gateway or ChatRouteGateway()
        self._governed_chat_audit = governed_chat_audit
        self._resource_analysis_service = (
            resource_analysis_service or ResourceAnalysisService()
        )
        self._inventory_answer_service = InventoryAnswerService(
            resource_analysis_service=self._resource_analysis_service,
        )
        self._feature_flags = FeatureFlagService()
        self._chat_analysis_runner = ChatAnalysisRunner(
            resource_analysis_service=self._resource_analysis_service,
            feature_flags=self._feature_flags,
        )
        self._chat_query_planner = ChatQueryPlanner()
        self._resource_action_registry = resource_action_registry or (
            ChatResourceActionRegistry(platform_service=platform_management_service)
            if platform_management_service is not None
            else None
        )
        self._observability_answer_service = observability_answer_service
        self._board_service = board_service
        self._reply_project_service = reply_project_service
        self._local_execution_connector_hub = local_execution_connector_hub

    def set_board_service(self, service: Any) -> None:
        """Optional BoardService for targeted work-item fetch (Phase B)."""
        self._board_service = service

    def set_llm_client(self, client: Any) -> None:
        """Set the LLM client (avoids circular import)."""
        self._llm_client = client

    def set_conversation_service(self, service: Any) -> None:
        """Set the conversation service."""
        self._conversation_service = service

    @staticmethod
    def _coerce_project_settings(settings: Any) -> Dict[str, Any]:
        if settings is None:
            return {}
        if isinstance(settings, dict):
            return dict(settings)
        if hasattr(settings, "model_dump"):
            try:
                raw = settings.model_dump()
                return dict(raw) if isinstance(raw, dict) else {}
            except Exception:
                return {}
        if isinstance(settings, str):
            try:
                raw = json.loads(settings)
                return dict(raw) if isinstance(raw, dict) else {}
            except Exception:
                return {}
        return {}

    def _get_reply_project(self, request: ReplyRequest) -> Optional[Any]:
        svc = self._reply_project_service
        if svc is None or not request.project_id:
            return None
        try:
            sig = inspect.signature(svc.get_project)
            if len(sig.parameters) >= 2:
                return svc.get_project(request.project_id, request.org_id)
            return svc.get_project(request.project_id)
        except TypeError:
            try:
                return svc.get_project(request.project_id)
            except Exception as exc:
                logger.debug(
                    "conversation_reply.reply_project_lookup_failed project_id=%s err=%s",
                    request.project_id,
                    exc,
                )
                return None
        except Exception as exc:
            logger.debug(
                "conversation_reply.reply_project_lookup_failed project_id=%s err=%s",
                request.project_id,
                exc,
            )
            return None

    def _connector_hub_resolved(self) -> Optional[Any]:
        if self._local_execution_connector_hub is not None:
            return self._local_execution_connector_hub
        try:
            from amprealize.local_execution_connector_hub import get_local_execution_connector_hub

            return get_local_execution_connector_hub()
        except Exception:
            return None

    def _local_execution_context_snapshot(self, request: ReplyRequest) -> Optional[str]:
        """Factual snapshot for ContextComposer ``extra_context`` (paths + connector presence)."""
        parts: List[str] = []
        project = self._get_reply_project(request)
        if project is not None:
            settings = self._coerce_project_settings(getattr(project, "settings", None))
            raw_path = settings.get("local_project_path")
            path = str(raw_path).strip() if raw_path is not None else ""
            label = (
                str(getattr(project, "name", "") or "").strip()
                or str(getattr(project, "slug", "") or "").strip()
                or str(getattr(project, "id", "") or request.project_id or "").strip()
            )
            if path:
                parts.append(
                    f'Project "{label}" has local_project_path set for local/off-repo workflows.'
                )
                parts.append(f"local_project_path: {path}")
        md = request.metadata or {}
        ewk = md.get("execution_workspace_kind")
        if ewk:
            parts.append(f"This message metadata includes execution_workspace_kind={ewk!r}.")
        hub = self._connector_hub_resolved()
        uid = request.user_id or ""
        if hub is not None and uid:
            try:
                live = bool(hub.user_has_live_connector_socket(uid))
            except Exception as exc:
                logger.debug(
                    "conversation_reply.connector_presence_failed user_id=%s err=%s",
                    uid,
                    exc,
                )
                live = False
            parts.append(
                "Local connector daemon (this API process): WebSocket "
                f"{'connected' if live else 'not connected'} for this user."
            )
        blob = " ".join(parts).strip()
        if not blob:
            return None
        max_chars = 2000
        if len(blob) > max_chars:
            return f"{blob[: max_chars - 1].rstrip()}…"
        return blob

    async def _compose_context(
        self,
        request: ReplyRequest,
        *,
        include_conversation_history: bool,
    ) -> ComposedContext:
        """Compose reply context, with a DSN-backed global inventory fallback."""
        conversation_scope = request.metadata.get("conversation_scope")
        md = request.metadata or {}
        intent = md.get("chat_query_intent") or detect_chat_workspace_intent(
            request.user_message_content or ""
        )
        extra_context: Optional[Dict[str, Any]] = None
        budget_override: Optional[TokenBudget] = None
        if intent == ChatWorkspaceIntent.WORKSPACE_PRIORITIZE.value:
            extra_context = {
                "workspace_prioritization": (
                    "The user is asking what to work on, how to prioritize, or what to focus on. "
                    "Use workspace inventory hierarchy hints (parent id, updated/created timestamps) "
                    "when recommending next steps."
                ),
            }
            base = default_token_budget()
            new_max = dict(base.maximum_tokens)
            wi_cap = new_max.get(DataSourceType.WORKSPACE_INVENTORY, 1800)
            new_max[DataSourceType.WORKSPACE_INVENTORY] = min(wi_cap + 800, 4000)
            budget_override = TokenBudget(
                total_tokens=min(base.total_tokens + 512, 20000),
                reserved_tokens=base.reserved_tokens,
                weights=base.weights,
                minimum_tokens=base.minimum_tokens,
                maximum_tokens=new_max,
            )

        merged_extra: Dict[str, Any] = {}
        if extra_context:
            merged_extra.update(extra_context)
        le_snapshot = self._local_execution_context_snapshot(request)
        if le_snapshot:
            merged_extra["Local execution (live)"] = le_snapshot
        compose_extra = merged_extra if merged_extra else None

        composed = await self._composer.compose(
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            query=request.user_message_content,
            work_item_id=request.work_item_id,
            run_id=request.run_id,
            org_id=request.org_id,
            project_id=request.project_id,
            conversation_scope=conversation_scope,
            include_conversation_history=include_conversation_history,
            extra_context=compose_extra,
            budget_override=budget_override,
        )
        if composed.sources_included or not is_global_workspace_scope(conversation_scope):
            return composed

        fallback_dsn = (
            os.environ.get("AMPREALIZE_ORG_PG_DSN")
            or os.environ.get("AMPREALIZE_AUTH_PG_DSN")
            or os.environ.get("DATABASE_URL")
        )
        if not fallback_dsn:
            return composed

        try:
            fallback_composer = build_chat_context_composer(
                project_service=OSSProjectService(dsn=fallback_dsn),
            )
            fallback = await fallback_composer.compose(
                conversation_id=request.conversation_id,
                user_id=request.user_id,
                query=request.user_message_content,
                work_item_id=request.work_item_id,
                run_id=request.run_id,
                org_id=request.org_id,
                project_id=request.project_id,
                conversation_scope=conversation_scope,
                include_conversation_history=include_conversation_history,
                extra_context=compose_extra,
                budget_override=budget_override,
            )
        except Exception as exc:
            logger.warning(
                "conversation_reply.context_fallback_failed conversation_id=%s err=%s",
                request.conversation_id,
                exc,
            )
            return composed

        if fallback.sources_included:
            logger.info(
                "conversation_reply.context_fallback_used conversation_id=%s tokens=%s sources=%s",
                request.conversation_id,
                fallback.total_tokens,
                len(fallback.sources_included),
            )
            return fallback
        return composed

    async def _build_llm_messages(
        self,
        request: ReplyRequest,
        composed: ComposedContext,
    ) -> List[Dict[str, str]]:
        """Build OpenAI-style messages with native multi-turn transcript when messaging is wired."""
        base_prompt = (
            request.system_prompt_override
            or self.DEFAULT_SYSTEM_PROMPT.format(context=composed.composed_text)
        )
        system_prompt = (
            f"{base_prompt}\n\n{PRINCIPAL_DS_SYSTEM_SUFFIX}"
            if self._should_inject_principal_ds_guidance(request)
            else base_prompt
        )
        if self._conversation_service is not None:

            def _transcript_sync() -> TranscriptBuildResult:
                try:
                    conv = self._conversation_service.get_conversation(
                        request.conversation_id,
                        user_id=request.user_id,
                        org_id=request.org_id,
                    )
                    summary = (conv.metadata or {}).get(THREAD_SUMMARY_METADATA_KEY)
                except Exception as exc:
                    logger.warning(
                        "conversation_reply.thread_summary_lookup_failed err=%s",
                        exc,
                    )
                    summary = None
                return build_transcript_openai_messages(
                    conversation_service=self._conversation_service,
                    conversation_id=request.conversation_id,
                    user_id=request.user_id,
                    org_id=request.org_id,
                    user_message_id=request.user_message_id,
                    model_id=(request.metadata or {}).get("llm_model_id"),
                    thread_summary=summary,
                )

            t_result = await asyncio.to_thread(_transcript_sync)
            self._emit_chat_event(
                "chat.context.transcript_turns",
                request,
                {
                    "transcript_turns": t_result.transcript_turns,
                    "thread_summary_injected": t_result.thread_summary_injected,
                },
            )
            self._emit_chat_event(
                "chat.context.duplicate_history_avoided",
                request,
                {"value": True},
            )
            if t_result.messages:
                return merge_system_and_transcript(system_prompt, t_result.messages)
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.user_message_content},
            ]

        self._emit_chat_event(
            "chat.context.duplicate_history_avoided",
            request,
            {"value": False},
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.user_message_content},
        ]

    @staticmethod
    def _planning_fallback_sse_labels(
        reason: str,
        *,
        error_message: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """Return (phase, stream_label, trace_step_label) for planning fallback reply.step events."""
        if reason == "planner_timeout":
            return (
                "planning_fallback_timeout",
                "Planner timed out — answering from your workspace summary",
                "The workspace task planner took too long. Answering from your "
                "workspace summary instead of fetching fresh tasks per project.",
            )
        if reason == "planner_error":
            detail = (error_message or "unexpected error").strip()
            if len(detail) > 160:
                detail = detail[:157] + "..."
            return (
                "planning_fallback",
                "Planner error — answering from your workspace summary",
                f"Planning failed ({detail}). Using your workspace summary.",
            )
        if reason == "invalid_or_empty_plan":
            return (
                "planning_fallback",
                "Couldn't match tasks to a plan — answering from your workspace summary",
                "The planner did not return a usable query plan. Using your workspace summary.",
            )
        return (
            "planning_fallback",
            "Couldn't narrow tasks automatically — answering from your workspace summary",
            f"Planning stopped ({reason}). Using your workspace summary.",
        )

    async def _maybe_targeted_workspace_reply(
        self,
        request: ReplyRequest,
        composed: ComposedContext,
        route_metadata: Dict[str, Any],
        message_id: str,
        source_counts: Dict[str, int],
        execution_observability: Optional[Dict[str, Any]],
        chat_trace: Dict[str, Any],
    ) -> Optional[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]]:
        """LLM plans bounded fetches, then stream-synthesize an answer. Optional Phase B path.

        On success returns (content, telemetry_fields_for_reply_event, source_rows).
        """
        if not self._feature_flags.is_enabled(
            "feature.chat_workspace_targeted_fetch",
            context={"user_id": request.user_id or ""},
        ):
            return None
        if route_metadata.get("chat_query_intent") != ChatWorkspaceIntent.WORKSPACE_PRIORITIZE.value:
            return None
        if request.project_id:
            return None
        scope = (request.metadata or {}).get("conversation_scope")
        if scope and not is_global_workspace_scope(scope):
            return None
        if self._board_service is None or self._llm_client is None:
            return None
        inventory = self._workspace_inventory_from_context(composed)
        if not inventory:
            return None
        allowed = extract_allowed_project_ids(inventory)
        if not allowed:
            return None

        # Conditional planner: a broad prioritization ask ("what should I work on
        # today?") is answerable from the deterministic inventory already in
        # context. Running the planner there only adds a slow, failure-prone extra
        # LLM round-trip with no quality gain, so skip straight to the normal
        # reply path. Only specific asks (a project/board/bug/blocker/status/etc.)
        # warrant the targeted fetch.
        if not targeted_fetch_warranted(request.user_message_content):
            self._emit_chat_event(
                "chat.planning.skipped",
                request,
                {"intent": "targeted_fetch", "reason": "broad_query_uses_inventory"},
            )
            return None

        self._emit_chat_event(
            "chat.planning.started",
            request,
            {
                "intent": "targeted_fetch",
                "source_counts": source_counts,
            },
        )
        self._publish_reply_event(
            request,
            message_id,
            EVENT_REPLY_STEP,
            phase="planning",
            label=f"Planning — asking {(request.metadata or {}).get('llm_model_id') or 'LLM'} which projects to check",
            source_counts=source_counts,
            trace_steps=[
                {
                    "phase": "planning",
                    "label": "Scanning your workspace…",
                }
            ],
        )
        summary = build_inventory_summary_text(inventory)
        meta = {
            **(request.metadata or {}),
            "user_id": request.user_id,
            "org_id": request.org_id,
            "project_id": request.project_id,
        }
        try:
            planner_result = await asyncio.to_thread(
                run_planner_llm,
                llm_client=self._llm_client,
                inventory_summary=summary,
                user_question=request.user_message_content,
                metadata=meta,
                execution_observability=execution_observability,
                actor={"id": request.user_id, "role": "user", "surface": "chat"},
            )
        except Exception as exc:
            logger.warning(
                "conversation_reply.targeted_fetch.planner_thread_failed conversation_id=%s err=%s",
                request.conversation_id,
                exc,
            )
            detail_msg = str(exc)
            self._emit_chat_event(
                "chat.planning.failed",
                request,
                {
                    "reason": "planner_error",
                    "error_class": exc.__class__.__name__,
                    "error_message": detail_msg[:400],
                },
            )
            fb_phase, fb_label, fb_trace = self._planning_fallback_sse_labels(
                "planner_error",
                error_message=detail_msg,
            )
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STEP,
                phase=fb_phase,
                label=fb_label,
                source_counts=source_counts,
                trace_steps=[
                    {
                        "phase": fb_phase,
                        "label": fb_trace,
                        "failure_reason": "planner_error",
                    }
                ],
            )
            return None

        plan = planner_result.plan
        if plan is None:
            reason = planner_result.failure_reason or "invalid_or_empty_plan"
            fail_payload: Dict[str, Any] = {"reason": reason}
            if planner_result.error_class:
                fail_payload["error_class"] = planner_result.error_class
            if planner_result.error_message:
                fail_payload["error_message"] = planner_result.error_message
            if planner_result.planner_latency_ms is not None:
                fail_payload["planner_latency_ms"] = planner_result.planner_latency_ms
            if planner_result.planner_attempts:
                fail_payload["planner_attempts"] = planner_result.planner_attempts
            if planner_result.planner_model_id:
                fail_payload["planner_model_id"] = planner_result.planner_model_id
            self._emit_chat_event("chat.planning.failed", request, fail_payload)
            fb_phase, fb_label, fb_trace = self._planning_fallback_sse_labels(
                reason,
                error_message=planner_result.error_message,
            )
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STEP,
                phase=fb_phase,
                label=fb_label,
                source_counts=source_counts,
                trace_steps=[
                    {
                        "phase": fb_phase,
                        "label": fb_trace,
                        "failure_reason": reason,
                    }
                ],
            )
            return None

        pid_plan = distinct_project_ids_in_plan(plan)
        self._emit_chat_event(
            "chat.planning.completed",
            request,
            {
                "queries_planned": len(plan.queries),
                "rationale": (plan.rationale or "")[:240],
                "project_ids_in_plan": pid_plan,
                "project_ids_in_inventory_count": len(allowed),
                "planner_latency_ms": planner_result.planner_latency_ms,
                "planner_attempts": planner_result.planner_attempts,
                "planner_model_id": planner_result.planner_model_id,
            },
        )
        nq = len(plan.queries)
        area_label = "area" if nq == 1 else "areas"
        self._publish_reply_event(
            request,
            message_id,
            EVENT_REPLY_STEP,
            phase="planning_ready",
            label=f"Ready — reviewing tasks from {nq} {area_label}",
            source_counts=source_counts,
            trace_steps=[
                {
                    "phase": "planning_ready",
                    "label": f"Organized {nq} checks across your workspace",
                    "queries_planned": nq,
                }
            ],
        )

        _short_pids = [p[:8] for p in pid_plan[:3]]
        _pid_str = ", ".join(_short_pids) + ("…" if len(pid_plan) > 3 else "")
        self._publish_reply_event(
            request,
            message_id,
            EVENT_REPLY_STEP,
            phase="fetching",
            label=f"Fetching tasks from {len(pid_plan)} project(s): {_pid_str}",
            source_counts=source_counts,
            trace_steps=[
                {
                    "phase": "fetching",
                    "label": f"Querying BoardService for {_pid_str}",
                }
            ],
        )

        try:

            def _run_exec() -> Tuple[Any, int]:
                return execute_fetch_plan(
                    board_service=self._board_service,
                    org_id=request.org_id,
                    allowed_project_ids=allowed,
                    plan=plan,
                )

            rows, queries_run = await asyncio.to_thread(_run_exec)
        except Exception as exc:
            logger.warning(
                "conversation_reply.targeted_fetch.exec_failed conversation_id=%s err=%s",
                request.conversation_id,
                exc,
            )
            self._emit_chat_event(
                "chat.targeted_fetch.failed",
                request,
                {"error_class": exc.__class__.__name__},
            )
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STEP,
                phase="fetch_failed",
                label="Couldn't load tasks from boards — using your full workspace summary",
                source_counts=source_counts,
                trace_steps=[
                    {
                        "phase": "fetch_failed",
                        "label": "Couldn't complete task lookup",
                    }
                ],
            )
            return None

        rpc = rows_per_project_counts(rows)
        activity_summaries = summarize_project_activity(inventory)
        ff_mode = fairness_mode_for_inventory(activity_summaries, allowed)
        disc_req = disclosure_required(ff_mode)
        tier_map = {s.project_id: s.tier for s in activity_summaries if s.project_id in allowed}
        self._emit_chat_event(
            "chat.targeted_fetch.completed",
            request,
            {
                "rows_fetched": len(rows),
                "queries_run": queries_run,
                "rows_per_project": rpc,
                "distinct_projects_in_results": len([k for k in rpc if k != "unknown"]),
                "fairness_mode": ff_mode,
                "projects_activity_tiers": tier_map,
                "disclosure_required": disc_req,
            },
        )

        cq_label = "check" if queries_run == 1 else "checks"
        self._publish_reply_event(
            request,
            message_id,
            EVENT_REPLY_STEP,
            phase="fetch_ready",
            label=f"Pulled {len(rows)} tasks from {queries_run} {cq_label}",
            source_counts=source_counts,
            trace_steps=[
                {
                    "phase": "fetch_ready",
                    "label": f"Collected {len(rows)} tasks",
                    "rows_fetched": len(rows),
                    "queries_run": queries_run,
                    "row_count": len(rows),
                }
            ],
        )

        if not rows:
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STEP,
                phase="fetch_empty",
                label="No tasks matched — using your full workspace summary",
                source_counts=source_counts,
                trace_steps=[
                    {
                        "phase": "fetch_empty",
                        "label": "Nothing matched those filters",
                    }
                ],
            )
            return None

        fetch_blob = format_fetched_items_for_prompt(rows)
        activity_blob = build_workspace_activity_appendix(
            summaries=activity_summaries,
            fairness_mode=ff_mode,
            rows_per_project=rpc,
            project_ids_in_plan=pid_plan,
            allowed_project_ids=allowed,
        )
        messages = await self._build_llm_messages(request, composed)
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = (
                messages[0]["content"]
                + "\n\n## Server-fetched work items (authoritative subset — prioritize these)\n"
                + fetch_blob
                + "\n\n"
                + activity_blob
            )
        else:
            extra = (
                "\n\n## Server-fetched work items (authoritative subset)\n"
                + fetch_blob
                + "\n\n"
                + activity_blob
            )
            if messages:
                messages[-1]["content"] = str(messages[-1].get("content") or "") + extra
            else:
                messages = [
                    {
                        "role": "user",
                        "content": request.user_message_content + extra,
                    }
                ]

        self._publish_reply_event(
            request,
            message_id,
            EVENT_REPLY_STEP,
            phase="generation",
            label=f"Drafting answer with {(request.metadata or {}).get('llm_model_id') or 'LLM'} ({len(rows)} tasks loaded)",
            source_counts=source_counts,
        )
        generation_started = time.monotonic()
        actor = {"id": request.user_id, "role": "user", "surface": "chat"}
        content = await self._generate_with_streaming(
            messages=messages,
            conversation_id=request.conversation_id,
            message_id=message_id,
            metadata=request.metadata,
            project_id=request.project_id,
            org_id=request.org_id,
            user_id=request.user_id,
            user_message_id=request.user_message_id,
            execution_observability=execution_observability,
            actor=actor,
        )
        _tf_gen_latency_ms = (time.monotonic() - generation_started) * 1000
        self._emit_chat_span_completed(
            request,
            span_name="generation",
            started_at=generation_started,
            attributes={
                "answer_path": "targeted_fetch",
                "model_id": request.metadata.get("llm_model_id"),
            },
        )
        self._emit_chat_event(
            "execution.llm.completed",
            request,
            {
                "model_id": request.metadata.get("llm_model_id"),
                "duration_ms": int(_tf_gen_latency_ms),
                "phase": "generation",
                "execution_observability": {
                    "org_id": request.org_id,
                    "project_id": request.project_id,
                    "conversation_id": request.conversation_id,
                    "message_id": request.user_message_id,
                    "answer_path": "targeted_fetch",
                    "rows_fetched": len(rows),
                },
            },
        )
        tf_meta = {
            "project_ids_in_plan": pid_plan,
            "project_ids_in_inventory_count": len(allowed),
            "rows_per_project": rpc,
            "fairness_mode": ff_mode,
            "projects_activity_tiers": tier_map,
            "disclosure_required": disc_req,
            "planner_latency_ms": planner_result.planner_latency_ms,
            "planner_attempts": planner_result.planner_attempts,
            "planner_model_id": planner_result.planner_model_id,
        }
        return content, tf_meta, rows

    @staticmethod
    def _prior_assistant_suggests_work_item_slot(assistant_text: str) -> bool:
        if not assistant_text:
            return False
        lowered = assistant_text.lower()
        return any(marker in lowered for marker in _WORK_ITEM_SLOT_ASSISTANT_MARKERS)

    @staticmethod
    def _looks_like_short_slot_reply(user_text: str) -> bool:
        raw = (user_text or "").strip()
        if not raw or len(raw) > 140:
            return False
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        if len(lines) > 3:
            return False
        if len(raw.split()) > 12:
            return False
        bail = (
            "never mind",
            "forget it",
            "cancel",
            "stop",
            "no thanks",
            "nope",
            "ignore",
        )
        low = raw.lower()
        if any(phrase in low for phrase in bail):
            return False
        return True

    @staticmethod
    def _fallback_title_from_slot_reply(user_text: str) -> Optional[str]:
        raw = (user_text or "").strip()
        if not raw or len(raw) > 120:
            return None
        if "\n" in raw:
            return None
        low = raw.lower()
        if low in {"yes", "no", "ok", "okay", "sure", "none"}:
            return None
        cleaned = re.sub(r"\s+", " ", raw).strip()
        return cleaned or None

    def _routing_tail_hints_sync(self, request: ReplyRequest) -> Dict[str, Any]:
        """Load last assistant + prior user message to support follow-up detection.

        Returns hints for:
        - Work-item slot follow-ups (unchanged behavior).
        - Referential follow-ups (e.g. "are any of these completed?") that should
          bypass the clarification short-circuit and use LLM with transcript context.
        - Meta-correction messages (e.g. "I'm asking you a question") that indicate
          the user is pushing back on a bad/clarification-only prior reply.
        """
        svc = self._conversation_service
        if svc is None or not request.conversation_id or not request.user_id:
            return {}
        try:
            msgs, _, _ = svc.list_messages(
                request.conversation_id,
                user_id=request.user_id,
                org_id=request.org_id,
                limit=24,
                offset=0,
                include_total=False,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "conversation_reply.routing_tail_failed conversation_id=%s err=%s",
                request.conversation_id,
                exc,
            )
            return {}
        if not msgs:
            return {}
        current_id = request.user_message_id
        prior_assistant = ""
        prior_user = ""
        for i, m in enumerate(msgs):
            if m.id != current_id:
                continue
            if m.sender_type != ActorType.USER:
                return {}
            j = i + 1
            if j >= len(msgs):
                # Current message is the first message in the conversation.
                return {}
            nxt = msgs[j]
            if nxt.sender_type not in (ActorType.AGENT, ActorType.SYSTEM):
                return {}
            prior_assistant = (nxt.content or "").strip()
            k = j + 1
            while k < len(msgs):
                if msgs[k].sender_type == ActorType.USER:
                    prior_user = (msgs[k].content or "").strip()
                    break
                k += 1
            break
        else:
            return {}

        user_msg = request.user_message_content or ""
        hints: Dict[str, Any] = {}

        # Always surface prior context so downstream clarification checks can use it.
        if prior_assistant:
            hints["routing_prior_assistant_message"] = prior_assistant
        if prior_user:
            hints["routing_prior_user_message"] = prior_user
        if prior_assistant or prior_user:
            hints["has_prior_turns"] = True

        # Work-item slot follow-up (unchanged behaviour).
        if self._prior_assistant_suggests_work_item_slot(
            prior_assistant
        ) and self._looks_like_short_slot_reply(user_msg):
            hints["work_item_slot_followup"] = True

        # Referential follow-up: user refers to prior result set with pronouns.
        if _is_referential_followup(user_msg):
            hints["referential_followup"] = True

        # Meta correction: user is pushing back on a clarification-only reply.
        if _is_meta_correction(user_msg):
            hints["meta_correction"] = True

        return hints

    async def generate_reply(
        self,
        request: ReplyRequest,
    ) -> ReplyResult:
        """Generate and store an agent reply in a conversation.

        Flow:
        1. Compose context via ContextComposer
        2. Build LLM messages with context
        3. Call LLM and stream tokens
        4. Store completed reply via ConversationService

        Args:
            request: Reply request with conversation context

        Returns:
            ReplyResult with generated message details
        """
        t_start = time.monotonic()
        message_id = request.stream_message_id or str(
            request.metadata.get("stream_message_id") or f"msg-{uuid.uuid4().hex[:12]}"
        )
        logger.info(
            "conversation_reply.generate_reply.start conversation_id=%s "
            "user_message_id=%s model=%s project_id=%s org_id=%s",
            request.conversation_id,
            request.user_message_id,
            (request.metadata or {}).get("llm_model_id"),
            request.project_id,
            request.org_id,
        )

        _routing_original_metadata = request.metadata
        routing_hints: Dict[str, Any] = {}
        trace_token = None
        try:
            routing_hints = await asyncio.to_thread(self._routing_tail_hints_sync, request)
            if routing_hints:
                request.metadata = {**(_routing_original_metadata or {}), **routing_hints}
            llm_answer_path = "llm"
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STARTED,
                phase="scheduled",
                label="Preparing reply",
            )
            route_started = time.monotonic()
            route_result = self._route_user_message(request)
            enriched_routing = enrich_chat_routing_metadata(
                request.metadata or {},
                request.user_message_content or "",
            )
            primary_route_mode = (
                route_result.primary.metadata.get("route_mode")
                if route_result.primary
                else None
            )
            route_metadata = {
                "chat_route": route_result.to_dict(),
                "chat_query_intent": str(
                    enriched_routing.get("chat_query_intent")
                    or detect_chat_workspace_intent(request.user_message_content or "")
                ),
                "chat_route_mode": (
                    enriched_routing.get("chat_route_mode")
                    or primary_route_mode
                    or ChatRouteMode.DETERMINISTIC.value
                ),
                "chat_route_confidence": (
                    route_result.primary.confidence if route_result.primary else None
                ),
                "chat_route_requires_clarification": route_result.requires_clarification,
                "chat_route_requires_approval": (
                    route_result.primary.requires_approval if route_result.primary else False
                ),
                "chat_route_policy_context": (
                    route_result.primary.to_policy_context()
                    if route_result.primary
                    else {}
                ),
            }
            chat_trace = self._chat_trace_metadata(
                request=request,
                message_id=message_id,
                route_metadata=route_metadata,
            )
            execution_observability = self._chat_execution_observability(
                request=request,
                message_id=message_id,
                chat_trace=chat_trace,
            )
            trace_token = attach_trace_context(TraceContext.from_chat_trace(chat_trace))
            self._emit_chat_trace_event(
                "chat.trace.started",
                request,
                {
                    "status": "started",
                    "execution_observability": execution_observability,
                },
            )
            self._emit_chat_span_completed(
                request,
                span_name="routing",
                started_at=route_started,
                attributes=route_metadata,
            )
            if self._is_execution_handoff(route_metadata, request):
                self._emit_chat_span_completed(
                    request,
                    span_name="execution_handoff",
                    started_at=route_started,
                    attributes={
                        "route_action_id": chat_trace.get("route_action_id"),
                        "run_id": request.run_id,
                        "work_item_id": request.work_item_id,
                        "handoff_status": "linked"
                        if request.run_id or request.work_item_id
                        else "routed",
                        "execution_observability": execution_observability,
                    },
                )
            self._log_route_audit(request, route_metadata)

            # Step 1: Compose context
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STEP,
                phase="context",
                label="Gathering workspace context",
            )
            context_started = time.monotonic()
            include_history_in_composer = self._conversation_service is None
            composed = await self._compose_context(
                request,
                include_conversation_history=include_history_in_composer,
            )
            context_latency_ms = (time.monotonic() - context_started) * 1000
            source_counts = self._source_counts(composed)
            self._emit_chat_event(
                "chat.phase.latency_ms",
                request,
                {"phase": "context", "latency_ms": context_latency_ms},
            )
            self._emit_chat_event(
                "chat.context.source_count",
                request,
                {"source_counts": source_counts, "sources_count": len(composed.sources_included)},
            )
            self._emit_chat_span_completed(
                request,
                span_name="context",
                started_at=context_started,
                attributes={
                    "source_counts": source_counts,
                    "sources_count": len(composed.sources_included),
                    "context_tokens": composed.total_tokens,
                },
            )
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_STEP,
                phase="context_ready",
                label=f"Context ready — {composed.total_tokens:,} tokens from {len(composed.sources_included)} source(s)",
                source_counts=source_counts,
                trace_steps=[
                    {
                        "phase": "context_ready",
                        "label": f"Context ready — {composed.total_tokens:,} tokens",
                        "source_counts": source_counts,
                        "latency_ms": context_latency_ms,
                        "context_tokens": composed.total_tokens,
                    }
                ],
            )

            logger.info(
                f"Composed context for reply: {composed.total_tokens} tokens, "
                f"{len(composed.sources_included)} sources"
            )

            fast_path_started = time.monotonic()
            planner_answer = self._try_chat_query_plan_answer(request, composed)
            capability_answer = self._try_execution_capability_answer(request, composed)
            observability_answer = self._try_observability_answer(request)
            platform_answer = await self._try_platform_management_answer(
                request,
                route_result,
                route_metadata,
                composed,
            )
            execution_cancel_answer = await self._try_chat_execution_cancel_answer(
                request,
                route_result,
                route_metadata,
                composed,
            )
            execution_start_answer = await self._try_chat_execution_answer(
                request,
                route_result,
                route_metadata,
                composed,
            )
            execution_answer = execution_cancel_answer or execution_start_answer
            workspace_direct = None
            if should_use_workspace_inventory_fast_path(
                message=request.user_message_content or "",
                chat_query_intent=route_metadata.get("chat_query_intent") or "",
                feature_flags=self._feature_flags,
                user_id=request.user_id or "",
            ):
                workspace_direct = self._try_direct_workspace_answer(request, composed)
            direct_answer = (
                planner_answer
                or capability_answer
                or observability_answer
                or platform_answer
                or execution_answer
                or workspace_direct
            )
            if direct_answer is None and self._llm_client is not None:
                inv_runner = self._workspace_inventory_from_context(composed)
                if inv_runner is not None:
                    try:
                        runner_answer = await self._chat_analysis_runner.try_answer(
                            user_message=request.user_message_content,
                            user_id=request.user_id,
                            conversation_id=request.conversation_id,
                            message_id=message_id,
                            inventory=inv_runner,
                            scope_hints=self._workspace_scope_hints(request),
                            chat_query_intent=route_metadata.get(
                                "chat_query_intent", ""
                            ),
                            route_requires_clarification=bool(
                                route_result.requires_clarification
                            ),
                            llm_client=self._llm_client,
                            metadata=request.metadata or {},
                            audit=self._governed_chat_audit,
                            org_id=request.org_id,
                            project_id=request.project_id,
                            execution_observability=execution_observability,
                        )
                    except Exception as exc:
                        logger.warning(
                            "conversation_reply.chat_analysis_runner_failed "
                            "conversation_id=%s err=%s",
                            request.conversation_id,
                            exc,
                        )
                    else:
                        if runner_answer is not None:
                            direct_answer = runner_answer
            structured_payload: Optional[Dict[str, Any]] = None
            answer_metadata: Dict[str, Any] = {}
            used_targeted_fetch = False
            llm_answer_path = "llm"
            if direct_answer is not None:
                is_platform_action = direct_answer.answer_type.startswith("platform_action")
                is_chat_execution = direct_answer.answer_type.startswith("chat_execution")
                is_chat_query_planner = bool(
                    (direct_answer.structured_payload or {}).get("chat_query_plan_result")
                ) and not is_platform_action and not is_chat_execution
                is_analysis_runner = bool(
                    (direct_answer.structured_payload or {}).get("analysis_run")
                ) and not is_platform_action and not is_chat_execution
                structured_payload = direct_answer.structured_payload
                answer_metadata = {
                    "direct_answer": True,
                    "direct_answer_type": direct_answer.answer_type,
                    "context_source_rows": direct_answer.source_rows,
                    "trace_steps": direct_answer.trace_steps,
                    "requires_clarification": direct_answer.requires_clarification,
                    "chat_trace": {
                        **chat_trace,
                        "answer_path": (
                            "platform_action"
                            if is_platform_action
                            else "chat_execution"
                            if is_chat_execution
                            else "chat_query_planner"
                            if is_chat_query_planner
                            else "analysis_runner"
                            if is_analysis_runner
                            else "deterministic"
                        ),
                        "answer_type": direct_answer.answer_type,
                    },
                }
                if structured_payload and structured_payload.get("card_kind") == "resource_analysis":
                    answer_metadata["resource_analysis"] = {
                        "analysis_mode": structured_payload.get("analysis_mode"),
                        "query_plan": structured_payload.get("query_plan"),
                        "row_count": len(direct_answer.source_rows),
                    }
                if structured_payload and structured_payload.get("chat_query_plan_result"):
                    _plan_result = structured_payload.get("chat_query_plan_result") or {}
                    _plan = (_plan_result.get("plan") or {}) if isinstance(_plan_result, dict) else {}
                    _validation = (
                        (_plan_result.get("validation") or {})
                        if isinstance(_plan_result, dict)
                        else {}
                    )
                    answer_metadata["chat_query_plan"] = {
                        "operation": _plan.get("operation"),
                        "resource_type": _plan.get("resource_type"),
                        "latency_tier": _plan.get("latency_tier"),
                        "confidence": _plan.get("confidence"),
                        "validation_result": _validation.get("valid"),
                        "validation_reason": _validation.get("reason"),
                        "planner_latency_ms": _plan_result.get("latency_ms")
                        if isinstance(_plan_result, dict)
                        else None,
                        "planner_source": _plan_result.get("source")
                        if isinstance(_plan_result, dict)
                        else None,
                        "fallback_reason": _plan_result.get("fallback_reason")
                        if isinstance(_plan_result, dict)
                        else None,
                        "requested_model_id": _plan_result.get("requested_model_id")
                        if isinstance(_plan_result, dict)
                        else None,
                        "resolved_provider": _plan_result.get("resolved_provider")
                        if isinstance(_plan_result, dict)
                        else None,
                        "resolved_model": _plan_result.get("resolved_model")
                        if isinstance(_plan_result, dict)
                        else None,
                        "planner_timeout_seconds": _plan_result.get("planner_timeout_seconds")
                        if isinstance(_plan_result, dict)
                        else None,
                        "error_type": _plan_result.get("error_type")
                        if isinstance(_plan_result, dict)
                        else None,
                        "error_message": _plan_result.get("error_message")
                        if isinstance(_plan_result, dict)
                        else None,
                        "retrieval_count": len(direct_answer.source_rows),
                        "render_path": direct_answer.answer_type,
                    }
                    if direct_answer.answer_type == "work_items.planned_summary":
                        # The planned summary renderer already inlines the useful work-item
                        # chips. Do not stream every source row again, or the UI renders a
                        # duplicate raw chip dump after the answer.
                        answer_metadata["context_source_rows"] = []
                if structured_payload and structured_payload.get("card_kind") == "capability_answer":
                    answer_metadata["capability_answer"] = {
                        "feature_flag": structured_payload.get("feature_flag"),
                        "related_work_item_count": structured_payload.get(
                            "related_work_item_count", 0
                        ),
                        "related_work_items": structured_payload.get("related_work_items", []),
                    }
                self._publish_reply_event(
                    request,
                    message_id,
                    EVENT_REPLY_STEP,
                    phase="platform_action" if is_platform_action else "chat_execution" if is_chat_execution else "direct_answer",
                    label="Completing platform action"
                    if is_platform_action
                    else "Starting governed execution"
                    if is_chat_execution
                    else "Answering from workspace inventory",
                    source_counts=source_counts,
                    trace_steps=direct_answer.trace_steps,
                    source_rows=answer_metadata.get("context_source_rows"),
                    badge="Platform action" if is_platform_action else "Execution" if is_chat_execution else "Workspace inventory",
                )
                response_content = direct_answer.content
                narration = await asyncio.to_thread(
                    functools.partial(
                        maybe_append_insight_narration,
                        structured_payload=dict(
                            direct_answer.structured_payload or {}
                        ),
                        user_message=request.user_message_content,
                        chat_query_intent=route_metadata.get("chat_query_intent", ""),
                        llm_client=self._llm_client,
                        feature_flags=self._feature_flags,
                        user_id=request.user_id,
                        org_id=request.org_id,
                        project_id=request.project_id,
                        model_id=request.metadata.get("llm_model_id"),
                        prefer_user_credential=request.metadata.get(
                            "credential_scope"
                        )
                        == "user",
                        execution_observability=execution_observability,
                    ),
                )
                if narration:
                    response_content = f"{response_content}{narration}"
                self._emit_chat_event(
                    "chat.fast_path.hit",
                    request,
                    {
                        "answer_type": direct_answer.answer_type,
                        "source_rows_count": len(direct_answer.source_rows),
                        "requires_clarification": direct_answer.requires_clarification,
                    },
                )
                self._emit_chat_span_completed(
                    request,
                    span_name="platform_action" if is_platform_action else "chat_execution" if is_chat_execution else "fast_path",
                    started_at=fast_path_started,
                    attributes={
                        "hit": True,
                        "answer_type": direct_answer.answer_type,
                        "source_rows_count": len(direct_answer.source_rows),
                        "requires_clarification": direct_answer.requires_clarification,
                    },
                )
            else:
                self._emit_chat_event(
                    "chat.fast_path.miss",
                    request,
                    {"source_counts": source_counts},
                )
                self._emit_chat_span_completed(
                    request,
                    span_name="fast_path",
                    started_at=fast_path_started,
                    attributes={"hit": False, "source_counts": source_counts},
                )
                response_content = None
                clarification_short_circuit = False
                if self._llm_client is not None:
                    tf = await self._maybe_targeted_workspace_reply(
                        request,
                        composed,
                        route_metadata,
                        message_id,
                        source_counts,
                        execution_observability,
                        chat_trace,
                    )
                    if tf is not None:
                        response_content, tf_meta, tf_source_rows = tf
                        used_targeted_fetch = True
                        answer_metadata["targeted_fetch_telemetry"] = tf_meta
                        answer_metadata["context_source_rows"] = tf_source_rows
                # Conversational messages may still need the LLM even when the action router
                # asks for clarification (e.g. access/capability questions).
                #
                # Skip the short-circuit when there is transcript context AND the current
                # message is either:
                #   - a referential follow-up ("are any of these completed?", "those", …)
                #   - a meta-correction ("I'm asking you a question", "you didn't answer", …)
                # In both cases the LLM can answer using multi-turn conversation history.
                _meta = request.metadata or {}
                _followup_bypass = bool(
                    _meta.get("has_prior_turns")
                    and (
                        _meta.get("referential_followup")
                        or _meta.get("meta_correction")
                    )
                )
                if (
                    response_content is None
                    and route_result.requires_clarification
                    and not _followup_bypass
                    and detect_chat_workspace_intent(request.user_message_content or "")
                    != ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value
                ):
                    clarification_short_circuit = True
                    prompt = (route_result.clarification_prompt or "").strip()
                    response_content = prompt or _CLARIFICATION_BODY_FALLBACK
                    self._publish_reply_event(
                        request,
                        message_id,
                        EVENT_REPLY_STEP,
                        phase="generation",
                        label="Clarification needed",
                        source_counts=source_counts,
                    )
                    generation_started = time.monotonic()
                    self._emit_chat_span_completed(
                        request,
                        span_name="generation",
                        started_at=generation_started,
                        attributes={
                            "answer_path": "routing_clarification",
                            "skipped_llm": True,
                            "model_id": (request.metadata or {}).get("llm_model_id"),
                        },
                    )
                elif response_content is None:
                    if self._llm_client is None:
                        raise RuntimeError("LLM client not configured")
                    # Step 2: Build LLM messages (multi-turn transcript when ConversationService is wired)
                    messages = await self._build_llm_messages(request, composed)

                    # Step 3: Generate response
                    _main_model = (request.metadata or {}).get("llm_model_id") or "LLM"
                    _gen_label = (
                        f"Drafting follow-up answer with {_main_model}"
                        if _followup_bypass
                        else f"Drafting answer with {_main_model}"
                    )
                    self._publish_reply_event(
                        request,
                        message_id,
                        EVENT_REPLY_STEP,
                        phase="generation",
                        label=_gen_label,
                        source_counts=source_counts,
                    )
                    generation_started = time.monotonic()
                    response_content = await self._generate_with_streaming(
                        messages=messages,
                        conversation_id=request.conversation_id,
                        message_id=message_id,
                        metadata=request.metadata,
                        project_id=request.project_id,
                        org_id=request.org_id,
                        user_id=request.user_id,
                        user_message_id=request.user_message_id,
                        execution_observability=execution_observability,
                        actor={"id": request.user_id, "role": "user", "surface": "chat"},
                    )
                    _main_gen_latency_ms = (time.monotonic() - generation_started) * 1000
                    _llm_answer_path = (
                        "llm_followup_bypass" if _followup_bypass else "llm"
                    )
                    self._emit_chat_span_completed(
                        request,
                        span_name="generation",
                        started_at=generation_started,
                        attributes={
                            "answer_path": _llm_answer_path,
                            "followup_bypass": _followup_bypass,
                            "model_id": (request.metadata or {}).get("llm_model_id"),
                        },
                    )
                    self._emit_chat_event(
                        "execution.llm.completed",
                        request,
                        {
                            "model_id": (request.metadata or {}).get("llm_model_id"),
                            "duration_ms": int(_main_gen_latency_ms),
                            "phase": "generation",
                            "execution_observability": {
                                "org_id": request.org_id,
                                "project_id": request.project_id,
                                "conversation_id": request.conversation_id,
                                "message_id": request.user_message_id,
                                "answer_path": "llm",
                            },
                        },
                    )
                if clarification_short_circuit:
                    llm_answer_path = "routing_clarification"
                else:
                    llm_answer_path = "targeted_fetch" if used_targeted_fetch else "llm"

            if structured_payload is None and not str(response_content or "").strip():
                logger.info(
                    "conversation_reply.persist.empty_body_guard conversation_id=%s "
                    "message_id=%s",
                    request.conversation_id,
                    message_id,
                )
                response_content = _EMPTY_LLM_REPLY_PLACEHOLDER

            # Step 4: Store the reply
            if self._conversation_service is not None:
                persistence_started = time.monotonic()
                self._publish_reply_event(
                    request,
                    message_id,
                    EVENT_REPLY_STEP,
                    phase="persisting",
                    label="Saving answer",
                    source_counts=source_counts,
                )
                # Agent sender must be a participant; conversations are often user-only until first reply.
                self._conversation_service.add_participant(
                    request.conversation_id,
                    actor_id=request.agent_id,
                    actor_type=ActorType.AGENT,
                    role=ParticipantRole.MEMBER,
                    added_by=request.user_id,
                    org_id=request.org_id,
                )
                self._conversation_service.send_message(
                    request.conversation_id,
                    sender_id=request.agent_id,
                    content=response_content,
                    message_type=MessageType.TEXT,
                    parent_id=request.user_message_id,
                    run_id=request.run_id,
                    work_item_id=request.work_item_id,
                    metadata={
                        **request.metadata,
                        **route_metadata,
                        **answer_metadata,
                        "chat_trace": (
                            {**chat_trace, **(answer_metadata.get("chat_trace") or {})}
                            if answer_metadata.get("chat_trace")
                            else {
                                **chat_trace,
                                "answer_path": llm_answer_path,
                                "answer_type": None,
                            }
                        ),
                        "generated": True,
                        "stream_message_id": message_id,
                        "composed_context_tokens": composed.total_tokens,
                        "sources_used": composed.sources_included,
                        "source_counts": source_counts,
                        "execution_observability": execution_observability,
                    },
                    structured_payload=structured_payload,
                    org_id=request.org_id,
                    sender_type=ActorType.AGENT,
                )
                self._emit_chat_span_completed(
                    request,
                    span_name="persistence",
                    started_at=persistence_started,
                    attributes={"message_id": message_id},
                )

            latency_ms = (time.monotonic() - t_start) * 1000

            reply_answer_path = (
                (answer_metadata.get("chat_trace") or {}).get("answer_path") or llm_answer_path
            )

            tfm = answer_metadata.get("targeted_fetch_telemetry") or {}
            tf_payload = (
                {
                    "project_ids_in_plan": tfm.get("project_ids_in_plan"),
                    "project_ids_in_inventory_count": tfm.get(
                        "project_ids_in_inventory_count"
                    ),
                    "rows_per_project": tfm.get("rows_per_project"),
                    "fairness_mode": tfm.get("fairness_mode"),
                    "projects_activity_tiers": tfm.get("projects_activity_tiers"),
                    "disclosure_required": tfm.get("disclosure_required"),
                    "planner_latency_ms": tfm.get("planner_latency_ms"),
                    "planner_attempts": tfm.get("planner_attempts"),
                    "planner_model_id": tfm.get("planner_model_id"),
                }
                if tfm
                else {}
            )

            # Capability answer telemetry — mirrors tf_payload pattern.
            _cap_meta = answer_metadata.get("capability_answer") or {}
            cap_payload = (
                {
                    "capability_answer": {
                        "feature_flag": _cap_meta.get("feature_flag"),
                        "related_work_item_count": _cap_meta.get(
                            "related_work_item_count", 0
                        ),
                        "related_work_items": _cap_meta.get("related_work_items", []),
                    }
                }
                if _cap_meta
                else {}
            )
            _chat_plan_meta = answer_metadata.get("chat_query_plan") or {}
            chat_plan_payload = (
                {"chat_query_plan": _chat_plan_meta} if _chat_plan_meta else {}
            )

            # Emit telemetry
            if self._telemetry:
                self._telemetry.emit_event(
                    event_type="conversation_reply.generated",
                    payload=sanitize_observability_payload(
                        {
                            "conversation_id": request.conversation_id,
                            "message_id": message_id,
                            "user_message_id": request.user_message_id,
                            "agent_id": request.agent_id,
                            "context_tokens": composed.total_tokens,
                            "response_length": len(response_content),
                            "latency_ms": latency_ms,
                            "sources_count": len(composed.sources_included),
                            "composed_sources_count": len(composed.sources_included),
                            "source_counts": source_counts,
                            "model_id": (request.metadata or {}).get("llm_model_id"),
                            "answer_path": reply_answer_path,
                            "used_targeted_fetch": used_targeted_fetch,
                            "chat_trace": {
                                **chat_trace,
                                **(answer_metadata.get("chat_trace") or {}),
                            },
                            **route_metadata,
                            **tf_payload,
                            **cap_payload,
                            **chat_plan_payload,
                        }
                    ),
                    actor={
                        "id": request.user_id,
                        "role": "user",
                        "surface": "chat",
                    },
                    run_id=request.run_id,
                    session_id=request.conversation_id,
                )

            logger.info(
                "conversation_reply.generate_reply.done conversation_id=%s "
                "stream_message_id=%s latency_ms=%.1f response_chars=%s",
                request.conversation_id,
                message_id,
                latency_ms,
                len(response_content),
            )
            completion_started = time.monotonic()
            self._publish_reply_event(
                request,
                message_id,
                EVENT_REPLY_COMPLETE,
                phase="complete",
                label="Answer ready",
                content=response_content,
                source_counts=source_counts,
                trace_steps=answer_metadata.get("trace_steps"),
                source_rows=answer_metadata.get("context_source_rows"),
                badge=(
                    "Platform action"
                    if direct_answer is not None
                    and str(answer_metadata.get("direct_answer_type", "")).startswith("platform_action")
                    else "Workspace inventory" if direct_answer is not None else None
                ),
            )
            if self._event_hub:
                self._event_hub.publish_token(
                    request.conversation_id,
                    message_id,
                    {
                        "message_id": message_id,
                        "stream_message_id": message_id,
                        "user_message_id": request.user_message_id,
                        "conversation_id": request.conversation_id,
                        "phase": "complete",
                        "label": "Answer ready",
                        "content": response_content,
                        "source_counts": source_counts,
                    },
                    event_type=EVENT_COMPLETE,
                )
            self._emit_chat_span_completed(
                request,
                span_name="sse_streaming",
                started_at=completion_started,
                attributes={"event_type": EVENT_COMPLETE},
            )
            self._emit_chat_span_completed(
                request,
                span_name="completion",
                started_at=t_start,
                attributes={
                    "answer_path": (
                        (answer_metadata.get("chat_trace") or {}).get("answer_path")
                        if direct_answer is not None
                        else "llm"
                    ),
                    "response_length": len(response_content),
                    "sources_count": len(composed.sources_included),
                },
            )
            self._emit_chat_trace_event(
                "chat.trace.completed",
                request,
                {
                    "status": "completed",
                    "latency_ms": latency_ms,
                    "response_length": len(response_content),
                    "execution_observability": execution_observability,
                },
            )
            return ReplyResult(
                message_id=message_id,
                content=response_content,
                conversation_id=request.conversation_id,
                composed_context=composed,
                token_count=len(response_content.split()),  # Rough estimate
                latency_ms=latency_ms,
            )

        except Exception as exc:
            logger.error(
                "conversation_reply.generate_reply.failed conversation_id=%s "
                "user_message_id=%s stream_message_id=%s err=%s",
                request.conversation_id,
                request.user_message_id,
                message_id,
                exc,
                exc_info=True,
            )
            latency_ms = (time.monotonic() - t_start) * 1000
            failure_trace = self._chat_trace_metadata(
                request=request,
                message_id=message_id,
                route_metadata={},
            )
            self._emit_chat_span_failed(
                request,
                span_name="reply",
                started_at=t_start,
                error=exc,
                chat_trace=failure_trace,
            )
            self._emit_chat_trace_event(
                "chat.trace.failed",
                request,
                {
                    "status": "failed",
                    "latency_ms": latency_ms,
                    "error": str(exc),
                    **_telemetry_failure_metadata(exc),
                    "execution_observability": self._chat_execution_observability(
                        request=request,
                        message_id=message_id,
                        chat_trace=failure_trace,
                    ),
                },
                chat_trace=failure_trace,
            )

            # Emit error event to SSE
            if self._event_hub:
                error_payload = self._reply_payload(
                    request,
                    message_id,
                    phase="error",
                    label="Reply failed",
                    error=str(exc),
                )
                self._event_hub.publish_token(
                    request.conversation_id,
                    message_id,
                    error_payload,
                    event_type=EVENT_REPLY_ERROR,
                )
                self._event_hub.publish_token(
                    request.conversation_id,
                    message_id,
                    error_payload,
                    event_type=EVENT_ERROR,
                )

            return ReplyResult(
                message_id=message_id,
                content="",
                conversation_id=request.conversation_id,
                composed_context=ComposedContext(
                    composed_text="",
                    total_tokens=0,
                    fragments_included=[],
                    fragments_excluded=[],
                    sources_included=[],
                    token_allocation={},
                    budget_utilization=0.0,
                    composition_time_ms=0.0,
                ),
                token_count=0,
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )

        finally:
            if routing_hints:
                request.metadata = _routing_original_metadata
            detach_trace_context(trace_token)

    async def _generate_with_streaming(
        self,
        messages: List[Dict[str, str]],
        conversation_id: str,
        message_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_message_id: Optional[str] = None,
        execution_observability: Optional[Dict[str, Any]] = None,
        actor: Optional[Dict[str, str]] = None,
    ) -> str:
        """Generate LLM response with optional token streaming.

        Args:
            messages: Chat messages for LLM
            conversation_id: For event routing
            message_id: For event routing

        Returns:
            Complete generated text
        """
        selected_model = (metadata or {}).get("llm_model_id")
        prefer_user_credential = (metadata or {}).get("credential_scope") == "user"
        chat_temp_raw = os.environ.get("AMPREALIZE_CHAT_LLM_TEMPERATURE")
        stream_temperature: Optional[float] = None
        if chat_temp_raw is not None and str(chat_temp_raw).strip() != "":
            try:
                stream_temperature = float(chat_temp_raw)
            except ValueError:
                stream_temperature = None

        # Check if LLM client supports async streaming
        if hasattr(self._llm_client, "astream"):
            tokens: List[str] = []
            last_stream_response: Any = None

            async def _stream_once(_stream_model: Optional[str]) -> None:
                nonlocal last_stream_response
                async for chunk in self._llm_client.astream(
                    messages,
                    model=_stream_model,
                    project_id=project_id,
                    org_id=org_id,
                    user_id=user_id,
                    prefer_user_credential=prefer_user_credential,
                    execution_observability=execution_observability,
                    actor=actor,
                    temperature=stream_temperature,
                ):
                    err = getattr(chunk, "error", None)
                    if err:
                        ec = getattr(chunk, "error_class", None)
                        rx = RuntimeError(str(err))
                        if isinstance(ec, str) and ec.strip():
                            setattr(rx, _STREAM_ERR_ATTR, ec.strip())
                        raise rx
                    resp = getattr(chunk, "response", None)
                    if resp is not None:
                        last_stream_response = resp
                    token = getattr(chunk, "text", None) or ""
                    if not token:
                        continue
                    tokens.append(token)

                    # Broadcast token via event hub
                    if self._event_hub:
                        reply_payload = {
                            "message_id": message_id,
                            "stream_message_id": message_id,
                            "user_message_id": user_message_id,
                            "conversation_id": conversation_id,
                            "phase": "generation",
                            "label": "Drafting answer",
                            "token": token,
                        }
                        self._event_hub.publish_token(
                            conversation_id,
                            message_id,
                            reply_payload,
                            event_type=EVENT_REPLY_TOKEN,
                        )
                        self._event_hub.publish_token(
                            conversation_id,
                            message_id,
                            {
                                "message_id": message_id,
                                "token": token,
                            },
                            event_type=EVENT_TOKEN,
                        )

            try:
                await _stream_once(selected_model)
            except Exception as primary_exc:
                # Fail-fast fallback: only safe when nothing was streamed yet, so a
                # partially delivered reply is never duplicated. A dead model endpoint
                # should degrade to a working model, not hang or error the whole turn.
                if (
                    tokens
                    or not _REPLY_FALLBACK_MODEL_ID
                    or selected_model == _REPLY_FALLBACK_MODEL_ID
                ):
                    raise
                logger.warning(
                    "conversation_reply.streaming.model_fallback conversation_id=%s "
                    "message_id=%s primary_model=%s fallback_model=%s err=%s",
                    conversation_id,
                    message_id,
                    selected_model,
                    _REPLY_FALLBACK_MODEL_ID,
                    primary_exc,
                )
                last_stream_response = None
                await _stream_once(_REPLY_FALLBACK_MODEL_ID)

            content = "".join(tokens)
            # Some OpenAI-compatible streams (e.g. NVIDIA NIM / DeepSeek) may omit per-delta
            # `text`/`reasoning` but attach final text on MESSAGE_COMPLETE.response.content,
            # or only populate reasoning_content on the final LLMResponse.
            if (not content or not str(content).strip()) and last_stream_response is not None:
                fb_content = str(getattr(last_stream_response, "content", None) or "").strip()
                fb_reason = str(getattr(last_stream_response, "reasoning_content", None) or "").strip()
                if fb_content:
                    content = fb_content
                elif fb_reason:
                    content = fb_reason
                    logger.info(
                        "conversation_reply.streaming.reasoning_fallback conversation_id=%s "
                        "message_id=%s reasoning_chars=%s",
                        conversation_id,
                        message_id,
                        len(fb_reason),
                    )
            if not str(content or "").strip():
                logger.info(
                    "conversation_reply.streaming.empty_completion conversation_id=%s "
                    "message_id=%s had_final_response=%s content_len=%s reasoning_len=%s",
                    conversation_id,
                    message_id,
                    last_stream_response is not None,
                    len(str(getattr(last_stream_response, "content", None) or ""))
                    if last_stream_response
                    else 0,
                    len(str(getattr(last_stream_response, "reasoning_content", None) or ""))
                    if last_stream_response
                    else 0,
                )

        elif hasattr(self._llm_client, "stream"):
            tokens = []
            async for token in self._llm_client.stream(messages):
                tokens.append(token)

                # Broadcast token via event hub
                if self._event_hub:
                    reply_payload = {
                        "message_id": message_id,
                        "stream_message_id": message_id,
                        "user_message_id": user_message_id,
                        "conversation_id": conversation_id,
                        "phase": "generation",
                        "label": "Drafting answer",
                        "token": token,
                    }
                    self._event_hub.publish_token(
                        conversation_id,
                        message_id,
                        reply_payload,
                        event_type=EVENT_REPLY_TOKEN,
                    )
                    self._event_hub.publish_token(
                        conversation_id,
                        message_id,
                        {
                            "message_id": message_id,
                            "token": token,
                        },
                        event_type=EVENT_TOKEN,
                    )

            content = "".join(tokens)

        else:
            # Non-streaming fallback
            response = self._llm_client.call(
                messages,
                model=selected_model,
                project_id=project_id,
                org_id=org_id,
                user_id=user_id,
                prefer_user_credential=prefer_user_credential,
                execution_observability=execution_observability,
                actor=actor,
                temperature=stream_temperature,
            )
            content = response.content if hasattr(response, "content") else str(response)

        if not str(content or "").strip():
            logger.info(
                "conversation_reply.streaming.empty_completion_replaced conversation_id=%s "
                "message_id=%s",
                conversation_id,
                message_id,
            )
            content = _EMPTY_LLM_REPLY_PLACEHOLDER
        return content

    def _reply_payload(
        self,
        request: ReplyRequest,
        stream_message_id: str,
        *,
        phase: str,
        label: str,
        token: Optional[str] = None,
        content: Optional[str] = None,
        error: Optional[str] = None,
        source_counts: Optional[Dict[str, int]] = None,
        trace_steps: Optional[List[Dict[str, Any]]] = None,
        source_rows: Optional[List[Dict[str, Any]]] = None,
        badge: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "message_id": stream_message_id,
            "stream_message_id": stream_message_id,
            "user_message_id": request.user_message_id,
            "conversation_id": request.conversation_id,
            "phase": phase,
            "label": label,
        }
        if token is not None:
            payload["token"] = token
        if content is not None:
            payload["content"] = content
        if error is not None:
            payload["error"] = error
        if source_counts is not None:
            payload["source_counts"] = source_counts
        if trace_steps:
            payload["trace_steps"] = trace_steps
        if source_rows:
            payload["source_rows"] = source_rows
        if badge:
            payload["badge"] = badge
        return payload

    def _publish_reply_event(
        self,
        request: ReplyRequest,
        stream_message_id: str,
        event_type: str,
        *,
        phase: str,
        label: str,
        content: Optional[str] = None,
        error: Optional[str] = None,
        source_counts: Optional[Dict[str, int]] = None,
        trace_steps: Optional[List[Dict[str, Any]]] = None,
        source_rows: Optional[List[Dict[str, Any]]] = None,
        badge: Optional[str] = None,
    ) -> None:
        if not self._event_hub:
            return
        self._event_hub.publish_token(
            request.conversation_id,
            stream_message_id,
            self._reply_payload(
                request,
                stream_message_id,
                phase=phase,
                label=label,
                content=content,
                error=error,
                source_counts=source_counts,
                trace_steps=trace_steps,
                source_rows=source_rows,
                badge=badge,
            ),
            event_type=event_type,
        )

    @staticmethod
    def _source_counts(composed: ComposedContext) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for fragment in composed.fragments_included:
            source = getattr(fragment.source, "value", str(fragment.source))
            counts[source] = counts.get(source, 0) + 1
            metadata_counts = fragment.metadata.get("source_counts") if fragment.metadata else None
            if isinstance(metadata_counts, dict):
                for key, value in metadata_counts.items():
                    if isinstance(value, int):
                        counts[f"workspace.{key}"] = value
        return counts

    @staticmethod
    def _workspace_scope_hints(request: ReplyRequest) -> Dict[str, Any]:
        hints: Dict[str, Any] = {}
        if request.project_id:
            hints["project_id"] = str(request.project_id)
        meta = request.metadata or {}
        board_id = meta.get("board_id")
        if board_id:
            hints["board_id"] = str(board_id)
        for link in meta.get("resource_links") or ():
            if not isinstance(link, dict):
                continue
            rtype = str(link.get("resource_type") or "").lower()
            rid = link.get("resource_id")
            if not rid:
                continue
            if rtype == "board":
                hints["board_id"] = str(rid)
            elif rtype == "project" and not hints.get("project_id"):
                hints["project_id"] = str(rid)
        hints["chat_query_intent"] = detect_chat_workspace_intent(request.user_message_content)
        return hints

    def _try_direct_workspace_answer(
        self,
        request: ReplyRequest,
        composed: ComposedContext,
    ) -> Optional[InventoryAnswer]:
        """Answer simple workspace inventory questions without an LLM round-trip."""
        inventory = self._workspace_inventory_from_context(composed)
        if inventory is not None:
            return self._inventory_answer_service.answer(
                query=request.user_message_content,
                inventory=inventory,
                scope_hints=self._workspace_scope_hints(request),
            )
        lowered = request.user_message_content.lower()
        if re.search(
            r"\b(create|add|make|execute|run|start|dispatch|trigger|update|set|delete|remove|cancel|stop)\b",
            lowered,
        ):
            return None
        # Inventory-driven NL questions without an included fragment (often token budget).
        probe = ResourceAnalysisService().answer_sync(
            query=request.user_message_content,
            inventory={},
            scope_hints=self._workspace_scope_hints(request),
        )
        if probe is None:
            return None
        if self._composed_includes_workspace_inventory(composed):
            return None
        return InventoryAnswer(
            content=(
                "Workspace data for your boards and work items was not included in this reply "
                "(it may have been trimmed for size or is unavailable in this room). "
                "Open the project board for live items, or try again in a shorter thread."
            ),
            answer_type="workspace_inventory.context_miss",
            structured_payload={
                "card_kind": "resource_analysis",
                "title": "Workspace data unavailable",
                "summary": "Workspace snapshot missing from composed context.",
                "analysis_mode": "deterministic",
                "empty_reason": "context_fragment_missing",
                "query_plan": probe.query_plan.to_dict() if probe.query_plan else {},
                "rows": [],
            },
            trace_steps=[
                {
                    "phase": "workspace_inventory",
                    "label": "Workspace inventory fragment missing from context composer output",
                }
            ],
        )

    def _try_chat_query_plan_answer(
        self,
        request: ReplyRequest,
        composed: ComposedContext,
    ) -> Optional[InventoryAnswer]:
        """Use a typed read-only plan before static topic-specific answers."""

        if not self._feature_flags.is_enabled(
            "feature.chat_query_planner",
            {
                "user_id": request.user_id or "",
                "org_id": request.org_id,
                "project_id": request.project_id,
            },
        ):
            return None
        inventory = self._workspace_inventory_from_context(composed)
        if not inventory:
            return None
        allowed_project_ids = extract_allowed_project_ids(inventory)
        scope_hints = self._workspace_scope_hints(request)
        planner_result = self._chat_query_planner.plan_sync(
            user_message=request.user_message_content or "",
            inventory_summary=build_inventory_summary_text(inventory),
            scope_hints=scope_hints,
            llm_client=self._llm_client,
            metadata=request.metadata,
            user_id=request.user_id or "",
            org_id=request.org_id,
            project_id=request.project_id,
            accessible_project_ids=allowed_project_ids,
        )
        if getattr(self, "_tracer", None) is not None:
            self._emit_chat_event(
                "chat.query_plan.evaluated",
                request,
                {
                    "source": planner_result.source,
                    "has_plan": planner_result.plan is not None,
                    "validation_valid": planner_result.validation.valid,
                    "validation_reason": planner_result.validation.reason,
                    "fallback_reason": planner_result.fallback_reason,
                    "latency_ms": planner_result.latency_ms,
                    "raw_response_preview": planner_result.raw_response_preview,
                    "requested_model_id": planner_result.requested_model_id,
                    "resolved_provider": planner_result.resolved_provider,
                    "resolved_model": planner_result.resolved_model,
                    "resolved_api_base": planner_result.resolved_api_base,
                    "planner_timeout_seconds": planner_result.planner_timeout_seconds,
                    "error_type": planner_result.error_type,
                    "error_message": planner_result.error_message,
                    "chat_query_plan": (
                        planner_result.plan.to_dict() if planner_result.plan is not None else None
                    ),
                },
            )
        plan = planner_result.plan
        if plan is None:
            if planner_result.validation.requires_clarification and planner_result.source == "llm":
                reason = (
                    planner_result.validation.reason
                    or "Please clarify which workspace resources you want me to inspect."
                )
                return InventoryAnswer(
                    content=reason,
                    answer_type="chat_query_plan.clarification",
                    structured_payload={
                        "card_kind": "resource_analysis",
                        "title": "Clarification needed",
                        "summary": reason,
                        "chat_query_plan": None,
                        "chat_query_plan_result": planner_result.telemetry_payload(),
                    },
                    requires_clarification=True,
                )
            return None
        if plan.mode not in {ChatPlanMode.ANSWER, ChatPlanMode.DEEP_ANALYSIS}:
            return None
        try:
            resource_plan = chat_plan_to_resource_query_plan(plan)
        except ValueError:
            return None
        merged_scope = dict(scope_hints)
        for key in ("project_id", "project_name", "board_id", "time_range"):
            if plan.scope.get(key) and not merged_scope.get(key):
                merged_scope[key] = plan.scope[key]
        answer = self._resource_analysis_service.answer_plan_sync(
            query=request.user_message_content or "",
            query_plan=resource_plan,
            inventory=inventory,
            scope_hints=merged_scope,
        )
        if answer is not None and not answer.source_rows and self._board_service is not None:
            fetch_plan = build_fetch_plan_from_chat_query_plan(
                plan,
                allowed_project_ids=allowed_project_ids,
            )
            if fetch_plan is not None:
                fetched_items, _queries_run = execute_fetch_plan(
                    board_service=self._board_service,
                    org_id=request.org_id,
                    allowed_project_ids=allowed_project_ids,
                    plan=fetch_plan,
                )
                if fetched_items:
                    refreshed_inventory = dict(inventory)
                    by_project = dict(refreshed_inventory.get("work_items_by_project") or {})
                    for item in fetched_items:
                        row = self._work_item_to_inventory_row(item)
                        pid = str(row.get("project_id") or "")
                        if not pid:
                            continue
                        by_project.setdefault(pid, [])
                        by_project[pid] = [*by_project[pid], row]
                    refreshed_inventory["work_items_by_project"] = by_project
                    answer = self._resource_analysis_service.answer_plan_sync(
                        query=request.user_message_content or "",
                        query_plan=resource_plan,
                        inventory=refreshed_inventory,
                        scope_hints=merged_scope,
                    )
        if answer is None:
            return None
        rendered = render_chat_plan_resource_answer(plan, answer)
        payload = dict(rendered.structured_payload)
        payload["chat_query_plan_result"] = planner_result.telemetry_payload()
        return InventoryAnswer(
            content=rendered.content,
            answer_type=rendered.answer_type,
            structured_payload=payload,
            source_rows=rendered.source_rows,
            trace_steps=rendered.trace_steps,
            requires_clarification=rendered.requires_clarification,
        )

    @staticmethod
    def _work_item_to_inventory_row(item: Any) -> Dict[str, Any]:
        try:
            data = item.model_dump(mode="json")
        except Exception:
            data = dict(item) if isinstance(item, dict) else {}
        if not data and item is not None:
            data = {
                "item_id": getattr(item, "item_id", None),
                "id": getattr(item, "id", None),
                "project_id": getattr(item, "project_id", None),
                "title": getattr(item, "title", None),
                "status": getattr(item, "status", None),
                "item_type": getattr(item, "item_type", None),
            }
        return data

    # Static capability facts for "have we implemented agent execution?" questions.
    # Kept here rather than in a config file so it stays in sync with the code.
    _EXECUTION_CAPABILITY_FACTS: str = (
        "**Agent execution is implemented in Amprealize.**\n\n"
        "- **Core work-item execution** (WorkItemExecutionService / GEP phases) is fully "
        "implemented and available to all users with the right project permissions.\n"
        "- **Chat-triggered execution** (starting a run directly from chat) is controlled by "
        "the `feature.chat_agent_work_item_execution` feature flag. It is not enabled by default "
        "and requires explicit flag enablement per workspace or user.\n"
        "- **Adapter and UX gaps** still exist — for example, not all output handlers, "
        "run-status streaming endpoints, and MCP surfaces are fully wired for all project types.\n\n"
        "> **Work items vs runs:** *Work items* are planned tasks on the board (features, tasks, "
        "goals, bugs). *Runs* are live execution instances — a run is created when a work item "
        "is executed by the agent. Work items represent *what to do*; runs represent *an attempt "
        "to do it*.\n\n"
        "To check whether a specific run is active or what phase it is in, ask about the run "
        "by name or ID and I will look it up in the current workspace context."
    )

    # Strong phrases: present anywhere in title+description → definite match.
    # These are specific enough that any mention is meaningful.
    _EXECUTION_ITEM_STRONG_PHRASES: frozenset = frozenset(
        {
            "agent execution",
            "work item execution",
            "workitemexecution",
            "execution service",
            "execution phase",
            "execution flow",
            "gep phase",
            "gep execution",
            "chat-triggered execution",
            "chat triggered execution",
        }
    )
    # Weak tokens: only match when found in the *title* (not description).
    # "execution" alone is too broad for description matching (catches instrumentation,
    # tracing, etc.) but is meaningful when it's the subject of the title.
    _EXECUTION_ITEM_TITLE_TOKENS: frozenset = frozenset(
        {
            "execution",
            "execute",
            "gep",
        }
    )

    _EXECUTION_CAPABILITY_PATTERNS: re.Pattern[str] = re.compile(
        r"\b("
        r"implement(?:ed)?|built|created?|exist(?:s)?|available|released?|shipped|"
        r"support(?:ed)?|done|finish(?:ed)?|complete(?:d)?|ready|deployed?"
        r")\b",
        re.IGNORECASE,
    )

    def _try_execution_capability_answer(
        self,
        request: ReplyRequest,
        composed: Optional["ComposedContext"] = None,
    ) -> Optional[InventoryAnswer]:
        """Return a factual static answer for 'have we implemented agent execution?' style questions.

        When a workspace inventory is available in *composed*, related work items mentioning
        execution are appended so the user can see the actual board tasks behind the facts.
        """
        msg = (request.user_message_content or "").lower()
        # Must mention agent execution (or work item execution) as the subject.
        if not re.search(r"\b(agent execution|work[- ]item execution|execution)\b", msg):
            return None
        # Must be a capability/polar question, not an imperative to start execution.
        if not re.search(
            r"\b(have we|has|did we|is|are|does|do|was|were|already|implemented|exist|available)\b",
            msg,
        ):
            return None
        # Don't intercept if the user is asking about a specific run's status/phase.
        if re.search(r"\b(phase|stage|step|running|active|progress|status)\b", msg) and re.search(
            r"\b(this|the|current|my)\b", msg
        ):
            return None
        # Must not be an action intent.
        if re.search(
            r"\b(run|start|execute|trigger|dispatch|launch|begin)\b\s+(it|this|the|a)\b",
            msg,
        ):
            return None
        if not self._EXECUTION_CAPABILITY_PATTERNS.search(msg):
            return None

        # --- Enrich with work items from inventory when available ---
        related_items: List[Dict[str, Any]] = []
        project_label: Optional[str] = None
        if composed is not None:
            inventory = self._workspace_inventory_from_context(composed) or {}
            related_items, project_label = self._find_execution_work_items(
                msg, inventory
            )

        content = self._EXECUTION_CAPABILITY_FACTS
        if related_items:
            lines = [
                f"\n\n**Related work items{' in ' + project_label if project_label else ''}:**"
            ]
            for item in related_items[:10]:
                title = str(item.get("title") or item.get("name") or "(untitled)")
                status_raw = item.get("status")
                status = str(getattr(status_raw, "value", status_raw) or "").strip()
                item_id = str(item.get("id") or item.get("item_id") or "").strip()
                status_badge = f" · `{status}`" if status else ""
                id_badge = f" `{item_id}`" if item_id else ""
                lines.append(f"- {title}{id_badge}{status_badge}")
            content = content + "\n".join(lines)

        return InventoryAnswer(
            content=content,
            answer_type="capability.agent_execution",
            structured_payload={
                "card_kind": "capability_answer",
                "title": "Agent execution capability",
                "summary": "Static capability facts for agent execution.",
                "analysis_mode": "deterministic",
                "feature_flag": "feature.chat_agent_work_item_execution",
                "related_work_item_count": len(related_items),
                "related_work_items": [
                    {
                        "id": str(i.get("id") or i.get("item_id") or ""),
                        "title": str(i.get("title") or i.get("name") or ""),
                        "status": str(
                            getattr(i.get("status"), "value", i.get("status")) or ""
                        ),
                    }
                    for i in related_items[:10]
                ],
            },
            trace_steps=[
                {
                    "phase": "execution_capability",
                    "label": "Answered from static execution capability facts",
                    "answer_type": "capability.agent_execution",
                    "related_work_items": len(related_items),
                }
            ],
        )

    def _find_execution_work_items(
        self,
        msg: str,
        inventory: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Return (matching_work_items, project_label) from inventory for execution questions."""
        projects = [
            self._first_present(p if isinstance(p, dict) else {}, "id", "project_id", default="")
            and (p if isinstance(p, dict) else {})
            for p in (inventory.get("projects") or [])
        ]
        # Resolve to proper dicts, filtering out falsy entries from the list comprehension.
        project_list: List[Dict[str, Any]] = [
            p if isinstance(p, dict) else {}
            for p in (inventory.get("projects") or [])
        ]
        work_items_by_project: Dict[str, Any] = inventory.get("work_items_by_project") or {}

        # Try to identify a specific project from the user's message.
        target_project: Optional[Dict[str, Any]] = None
        if project_list:
            target_project = self._find_project_for_query(msg, project_list)

        # Determine which project IDs to search.
        if target_project is not None:
            pid = str(
                self._first_present(target_project, "project_id", "id", default="")
            )
            project_ids = [pid] if pid else list(work_items_by_project.keys())
            project_label: Optional[str] = str(
                self._first_present(target_project, "name", "title", "slug", default="")
            ) or None
        else:
            project_ids = list(work_items_by_project.keys())
            project_label = None

        strong = self._EXECUTION_ITEM_STRONG_PHRASES
        weak = self._EXECUTION_ITEM_TITLE_TOKENS
        matched: List[Dict[str, Any]] = []
        for pid in project_ids:
            items = work_items_by_project.get(pid) or []
            if not isinstance(items, list):
                continue
            for raw in items:
                item = raw if isinstance(raw, dict) else {}
                title = (item.get("title") or "").lower()
                desc = (item.get("description") or "").lower()
                full_text = title + " " + desc
                # Strong phrase → match anywhere in title+description.
                if any(ph in full_text for ph in strong):
                    matched.append(item)
                    continue
                # Weak token → only match when found in the title.
                if any(tok in title for tok in weak):
                    matched.append(item)

        # Sort: items with "execution" in the title first, then by status stability.
        def _sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
            title = (item.get("title") or "").lower()
            status_raw = item.get("status")
            status = str(getattr(status_raw, "value", status_raw) or "").lower()
            title_rank = 0 if "execution" in title else 1
            return (title_rank, status)

        matched.sort(key=_sort_key)
        return matched, project_label

    def _try_observability_answer(
        self,
        request: ReplyRequest,
    ) -> Optional[InventoryAnswer]:
        """Answer governed telemetry questions using the same RBAC layer as analytics APIs."""
        service = self._observability_answer_service
        if service is None:
            return None
        actor = {
            "id": request.user_id,
            "role": request.metadata.get("role")
            or request.metadata.get("actor_role")
            or request.metadata.get("observability_role")
            or "viewer",
        }
        if request.org_id:
            actor["org_id"] = request.org_id
        if request.project_id:
            actor["project_id"] = request.project_id
        return service.answer(
            query=request.user_message_content,
            actor=actor,
            run_id=request.run_id,
        )

    async def _try_platform_management_answer(
        self,
        request: ReplyRequest,
        route_result: ChatActionRouteResult,
        route_metadata: Dict[str, Any],
        composed: ComposedContext,
    ) -> Optional[InventoryAnswer]:
        """Execute low-risk governed platform actions directly from chat."""
        registry = self._resource_action_registry
        candidate = route_result.primary
        if registry is None or candidate is None:
            return None
        if candidate.category != ChatActionCategory.WORK_MANAGEMENT:
            return None
        if candidate.requires_clarification or candidate.requires_approval:
            return None

        inventory = self._workspace_inventory_from_context(composed) or {}
        payload = self._work_item_create_payload_from_query(
            request,
            inventory,
        )
        if payload.get("requires_clarification") and payload.get("missing") == "board":
            discovered_boards = await self._discover_boards_for_project(
                request,
                registry,
                str(payload.get("project_id") or ""),
            )
            if discovered_boards:
                board = self._find_board_for_query(request.user_message_content, discovered_boards)
                board_id = self._first_present(board or {}, "id", "board_id")
                if board_id:
                    payload = {
                        "title": self._normalize_work_item_title(str(payload.get("title") or "")),
                        "item_type": str(payload.get("item_type") or "task"),
                        "project_id": str(payload.get("project_id")),
                        "board_id": str(board_id),
                        "metadata": {
                            "created_from": "chat",
                            "conversation_id": request.conversation_id,
                            "user_message_id": request.user_message_id,
                            "board_resolved_via": "platform_discover",
                        },
                    }
        if payload.get("requires_clarification"):
            reason = str(payload.get("message") or "Please clarify the work item target.")
            return InventoryAnswer(
                answer_type="platform_action_clarification",
                content=reason,
                structured_payload=self._structured_payload(
                    "platform_action_clarification",
                    "Clarification needed",
                    reason,
                    payload,
                ),
                source_rows=[],
                trace_steps=[
                    {
                        "phase": "platform_action",
                        "label": "Clarification needed",
                        "reason": reason,
                    }
                ],
                requires_clarification=True,
            )

        result = await registry.execute(
            ChatResourceActionRequest(
                action_id=ChatResourceActionId.WORK_ITEM_CREATE,
                user_id=request.user_id,
                org_id=request.org_id,
                project_id=payload.get("project_id"),
                conversation_id=request.conversation_id,
                message_id=request.user_message_id,
                payload=payload,
                policy_context={
                    **route_metadata.get("chat_route_policy_context", {}),
                    "chat_scope": request.metadata.get("conversation_scope")
                    or (
                        ConversationScope.PROJECT_SPACE.value
                        if payload.get("project_id")
                        else ConversationScope.GLOBAL_USER_HOME.value
                    ),
                },
                request_id=f"chat-work-item-create-{request.user_message_id}",
            )
        )
        result_payload = result.to_dict()
        created = result.result if isinstance(result.result, dict) else {}
        title = str(created.get("title") or payload.get("title") or "work item")
        if result.success:
            content = f"Created {payload.get('item_type', 'work')} work item: {title}."
            label = "Work item created"
        elif result.requires_approval:
            content = "This work item action needs approval before I can complete it."
            label = "Approval required"
        else:
            content = result.message or "I could not create the work item."
            label = "Action failed"

        return InventoryAnswer(
            answer_type="platform_action_result",
            content=content,
            structured_payload=self._structured_payload(
                "platform_action_result",
                label,
                content,
                result_payload,
            ),
            source_rows=[
                {
                    "source": "platform_management",
                    "resource_type": "work_item",
                    "resource_id": created.get("item_id")
                    or created.get("work_item_id")
                    or created.get("id"),
                    "project_id": payload.get("project_id"),
                    "board_id": payload.get("board_id"),
                    "title": title,
                }
            ],
            trace_steps=[
                {
                    "phase": "platform_action",
                    "label": label,
                    "action": "work_item.create",
                    "success": result.success,
                }
            ],
            requires_clarification=False,
        )

    async def _try_chat_execution_cancel_answer(
        self,
        request: ReplyRequest,
        route_result: ChatActionRouteResult,
        route_metadata: Dict[str, Any],
        composed: ComposedContext,
    ) -> Optional[InventoryAnswer]:
        """Cancel server-side work item execution when routing matches stop/cancel intent."""
        registry = self._resource_action_registry
        candidate = route_result.primary
        if registry is None or candidate is None:
            return None
        if candidate.category != ChatActionCategory.EXECUTION_CANCEL:
            return None
        if route_result.requires_clarification:
            return None
        if not self._feature_flags.is_enabled(
            "feature.chat_agent_work_item_execution",
            {"user_id": request.user_id, "org_id": request.org_id, "project_id": request.project_id},
        ):
            return None
        if not (request.metadata or {}).get("confirm_chat_execution_cancel"):
            return None

        work_item_id = request.work_item_id or (request.metadata or {}).get("work_item_id")
        project_id = request.project_id or (request.metadata or {}).get("project_id")
        if not work_item_id:
            return InventoryAnswer(
                answer_type="chat_execution_cancel_clarification",
                content=(
                    "To cancel execution from chat, provide the work item "
                    "(work_item_id on the message or in metadata)."
                ),
                structured_payload=self._structured_payload(
                    "chat_execution_cancel_clarification",
                    "Work item required",
                    "Provide work_item_id for the run to cancel.",
                    {"work_item_id": work_item_id, "project_id": project_id},
                ),
                source_rows=[],
                trace_steps=[
                    {
                        "phase": "chat_execution",
                        "label": "Missing work item for cancel",
                    }
                ],
                requires_clarification=True,
            )

        payload: Dict[str, Any] = {
            "work_item_id": str(work_item_id),
            "confirm_chat_execution_cancel": True,
        }
        if project_id:
            payload["project_id"] = str(project_id)
        if request.org_id:
            payload["org_id"] = request.org_id
        if (request.metadata or {}).get("cancellation_reason"):
            payload["reason"] = (request.metadata or {}).get("cancellation_reason")

        raw = await registry.execute(
            ChatResourceActionRequest(
                action_id=ChatResourceActionId.RUN_CANCEL,
                user_id=request.user_id,
                org_id=request.org_id,
                project_id=str(project_id) if project_id else None,
                resource_id=str(work_item_id),
                conversation_id=request.conversation_id,
                message_id=request.user_message_id,
                payload=payload,
                policy_context={
                    **route_metadata.get("chat_route_policy_context", {}),
                    "chat_scope": (request.metadata or {}).get("conversation_scope")
                    or (
                        ConversationScope.PROJECT_SPACE.value
                        if project_id
                        else ConversationScope.GLOBAL_USER_HOME.value
                    ),
                },
                request_id=f"chat-run-cancel-{request.user_message_id}",
            )
        )
        outcome = raw if isinstance(raw, dict) else {}
        success = bool(outcome.get("success"))
        message = str(
            outcome.get("message")
            or ("Execution cancelled." if success else "Could not cancel execution.")
        )
        result_body = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}

        label = "Execution cancelled" if success else "Execution not cancelled"
        return InventoryAnswer(
            answer_type="chat_execution_cancel_result",
            content=message,
            structured_payload=self._structured_payload(
                "chat_execution_cancel_result",
                label,
                message,
                {"raw": outcome},
            ),
            source_rows=[
                {
                    "source": "chat_execution",
                    "resource_type": "work_item",
                    "resource_id": str(work_item_id),
                    "project_id": str(project_id) if project_id else None,
                    "work_item_id": str(work_item_id),
                }
            ],
            trace_steps=[
                {
                    "phase": "chat_execution",
                    "label": label,
                    "action": "run.cancel",
                    "success": success,
                }
            ],
            requires_clarification=bool(outcome.get("requires_approval")),
        )

    async def _try_chat_execution_answer(
        self,
        request: ReplyRequest,
        route_result: ChatActionRouteResult,
        route_metadata: Dict[str, Any],
        composed: ComposedContext,
    ) -> Optional[InventoryAnswer]:
        """Start a server-side work item execution when chat routing matches execution intent."""
        registry = self._resource_action_registry
        candidate = route_result.primary
        if registry is None or candidate is None:
            return None
        if candidate.category != ChatActionCategory.EXECUTION_START:
            return None
        if route_result.requires_clarification:
            return None
        if not self._feature_flags.is_enabled(
            "feature.chat_agent_work_item_execution",
            {"user_id": request.user_id, "org_id": request.org_id, "project_id": request.project_id},
        ):
            return None
        if not (request.metadata or {}).get("confirm_chat_execution"):
            return None

        work_item_id = request.work_item_id or (request.metadata or {}).get("work_item_id")
        project_id = request.project_id or (request.metadata or {}).get("project_id")
        if not work_item_id or not project_id:
            return InventoryAnswer(
                answer_type="chat_execution_clarification",
                content=(
                    "To start execution from chat, link a work item and project "
                    "(work_item_id + project_id on the message or conversation context)."
                ),
                structured_payload=self._structured_payload(
                    "chat_execution_clarification",
                    "Execution context missing",
                    "Provide work_item_id and project_id.",
                    {"work_item_id": work_item_id, "project_id": project_id},
                ),
                source_rows=[],
                trace_steps=[
                    {
                        "phase": "chat_execution",
                        "label": "Missing work item or project",
                    }
                ],
                requires_clarification=True,
            )

        payload: Dict[str, Any] = {
            "work_item_id": str(work_item_id),
            "project_id": str(project_id),
            "confirm_chat_execution": True,
            "model_id": (request.metadata or {}).get("llm_model_id"),
            "agent_execution_mode": (request.metadata or {}).get("agent_execution_mode"),
            "execution_workspace_kind": (request.metadata or {}).get(
                "execution_workspace_kind", "cloud_git"
            ),
        }
        if (request.metadata or {}).get("source_type"):
            payload["source_type"] = (request.metadata or {}).get("source_type")
        if (request.metadata or {}).get("source_url"):
            payload["source_url"] = (request.metadata or {}).get("source_url")
        if (request.metadata or {}).get("source_ref"):
            payload["source_ref"] = (request.metadata or {}).get("source_ref")

        raw = await registry.execute(
            ChatResourceActionRequest(
                action_id=ChatResourceActionId.RUN_START,
                user_id=request.user_id,
                org_id=request.org_id,
                project_id=str(project_id),
                resource_id=str(work_item_id),
                conversation_id=request.conversation_id,
                message_id=request.user_message_id,
                payload=payload,
                policy_context={
                    **route_metadata.get("chat_route_policy_context", {}),
                    "chat_scope": (request.metadata or {}).get("conversation_scope")
                    or (
                        ConversationScope.PROJECT_SPACE.value
                        if project_id
                        else ConversationScope.GLOBAL_USER_HOME.value
                    ),
                },
                request_id=f"chat-run-start-{request.user_message_id}",
            )
        )
        outcome = raw if isinstance(raw, dict) else {}
        success = bool(outcome.get("success"))
        message = str(outcome.get("message") or ("Execution started." if success else "Execution failed."))
        result_body = outcome.get("result") if isinstance(outcome.get("result"), dict) else {}
        run_id = result_body.get("run_id") if isinstance(result_body, dict) else None

        label = "Execution started" if success else "Execution not started"
        return InventoryAnswer(
            answer_type="chat_execution_result",
            content=message,
            structured_payload=self._structured_payload(
                "chat_execution_result",
                label,
                message,
                {"raw": outcome},
            ),
            source_rows=[
                {
                    "source": "chat_execution",
                    "resource_type": "run",
                    "resource_id": run_id,
                    "project_id": str(project_id),
                    "work_item_id": str(work_item_id),
                }
            ],
            trace_steps=[
                {
                    "phase": "chat_execution",
                    "label": label,
                    "action": "run.start",
                    "success": success,
                }
            ],
            requires_clarification=bool(outcome.get("requires_approval")),
        )

    def _work_item_create_payload_from_query(
        self,
        request: ReplyRequest,
        inventory: Dict[str, Any],
    ) -> Dict[str, Any]:
        md = request.metadata or {}
        slot_followup = bool(md.get("work_item_slot_followup"))
        prior_user = str(md.get("routing_prior_user_message") or "").strip()
        current = request.user_message_content or ""
        full_query = f"{prior_user}\n{current}" if (slot_followup and prior_user) else current

        title = self._extract_work_item_title(full_query)
        if not title and slot_followup:
            title = self._fallback_title_from_slot_reply(current)
        item_type = self._extract_work_item_type(full_query)
        projects = list(inventory.get("projects") or [])
        project = self._find_project_for_query(full_query, projects)
        project_id = request.project_id or self._first_present(project or {}, "id", "project_id")
        if not title:
            return {
                "requires_clarification": True,
                "missing": "title",
                "message": (
                    "What should we call this work item? "
                    "Reply with a short title, or say it in one line "
                    "(for example: create a **task called … on the GuideAI board**)."
                ),
            }
        if not project_id:
            return {
                "requires_clarification": True,
                "missing": "project",
                "message": (
                    "Which project or board should this go on? "
                    "Name a project you can access (for example **GuideAI**), "
                    "or open this chat from that project space."
                ),
            }

        board = self._find_board_for_query(
            full_query,
            list((inventory.get("boards_by_project") or {}).get(str(project_id), [])),
        )
        board_id = self._first_present(board or {}, "id", "board_id")
        if not board_id:
            return {
                "requires_clarification": True,
                "missing": "board",
                "message": (
                    "I found the project, but I still need a **board** to file this on. "
                    "Name the board (for example **GuideAI project board**), or say **default board**."
                ),
                "title": title,
                "item_type": item_type,
                "project_id": str(project_id),
            }

        return {
            "title": self._normalize_work_item_title(title),
            "item_type": item_type,
            "project_id": str(project_id),
            "board_id": str(board_id),
            "metadata": {
                "created_from": "chat",
                "conversation_id": request.conversation_id,
                "user_message_id": request.user_message_id,
            },
        }

    async def _discover_boards_for_project(
        self,
        request: ReplyRequest,
        registry: ChatResourceActionRegistry,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        if not project_id:
            return []
        try:
            result = await registry.execute(
                ChatResourceActionRequest(
                    action_id=ChatResourceActionId.BOARD_DISCOVER,
                    user_id=request.user_id,
                    org_id=request.org_id,
                    project_id=project_id,
                    conversation_id=request.conversation_id,
                    message_id=request.user_message_id,
                    payload={"project_id": project_id, "limit": 100, "offset": 0},
                    policy_context={
                        "chat_scope": request.metadata.get("conversation_scope")
                        or ConversationScope.PROJECT_SPACE.value,
                    },
                    request_id=f"chat-board-discover-{request.user_message_id}",
                )
            )
        except Exception as exc:
            logger.debug(
                "conversation_reply.board_discover_failed project_id=%s err=%s",
                project_id,
                exc,
            )
            return []
        if not result.success or not isinstance(result.result, list):
            return []
        return [board for board in result.result if isinstance(board, dict)]

    @staticmethod
    def _structured_payload(
        payload_type: str,
        title: str,
        summary: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "type": payload_type,
            "title": title,
            "summary": summary,
            "data": data,
        }

    @staticmethod
    def _extract_work_item_title(query: str) -> Optional[str]:
        if not (query or "").strip():
            return None
        text = query.strip()
        quoted = (
            r"\bcalled\s+[\"']([^\"']+)[\"']",
            r"\bnamed\s+[\"']([^\"']+)[\"']",
            r"\btitled\s+[\"']([^\"']+)[\"']",
        )
        for pattern in quoted:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                t = match.group(1).strip()
                if t:
                    return t
        # Unquoted titles: "task called testing on the … board"
        boundary = (
            r"(?=\s+on\s+|\s+for\s+the\s+|\s+for\s+|\s+in\s+|\s+at\s+|\s+under\s+|\s+onto\s+|[\,\.\!\?]|\s+board\b|\s+project\b|$)"
        )
        unquoted = (
            rf"\bcalled\s+([^\"',\n]{{1,200}}?){boundary}",
            rf"\bnamed\s+([^\"',\n]{{1,200}}?){boundary}",
            rf"\btitled\s+([^\"',\n]{{1,200}}?){boundary}",
        )
        for pattern in unquoted:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                t = match.group(1).strip().strip("\"'")
                if t:
                    return t
        loose = (
            r"\btitle\s+is\s+[\"']?([^\"'\n,]{1,200}?)(?=[\,\.\!\?]|$)",
            r"\bcall\s+it\s+[\"']?([^\"'\n,]{1,200}?)(?=[\,\.\!\?]|$)",
        )
        for pattern in loose:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                t = match.group(1).strip().strip("\"'")
                if t:
                    return t
        return None

    @staticmethod
    def _extract_work_item_type(query: str) -> str:
        normalized = ConversationReplyService._normalize_lookup_text(query)
        for item_type in ("goal", "feature", "task", "bug", "research"):
            if re.search(rf"\b(work type\s+)?{item_type}\b", normalized):
                return item_type
        return "task"

    @staticmethod
    def _normalize_work_item_title(title: str) -> str:
        cleaned = " ".join(title.strip().strip("\"'").split())
        if not cleaned:
            return cleaned
        return cleaned[0].upper() + cleaned[1:]

    @staticmethod
    def _find_board_for_query(query: str, boards: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not boards:
            return None
        normalized_query = ConversationReplyService._normalize_lookup_text(query)
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0
        for board in boards:
            candidates = [
                ConversationReplyService._first_present(board, "id", "board_id", default=""),
                ConversationReplyService._first_present(board, "name", "title", default=""),
            ]
            for candidate in candidates:
                candidate_text = ConversationReplyService._normalize_lookup_text(str(candidate))
                if not candidate_text:
                    continue
                if re.search(rf"\b{re.escape(candidate_text)}\b", normalized_query):
                    score = len(candidate_text)
                    if score > best_score:
                        best_match = board
                        best_score = score
        if best_match is not None:
            return best_match
        default_board = next((board for board in boards if board.get("is_default")), None)
        return default_board or boards[0]

    def _emit_chat_event(
        self,
        event_type: str,
        request: ReplyRequest,
        payload: Dict[str, Any],
    ) -> None:
        self._tracer.emit_chat_event(request, event_type, payload)

    def _emit_chat_trace_event(
        self,
        event_type: str,
        request: ReplyRequest,
        payload: Dict[str, Any],
        chat_trace: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._tracer.emit_chat_trace_event(
            request, event_type, payload, chat_trace=chat_trace
        )

    def _emit_chat_span_completed(
        self,
        request: ReplyRequest,
        *,
        span_name: str,
        started_at: float,
        attributes: Optional[Dict[str, Any]] = None,
        chat_trace: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._tracer.emit_chat_span_completed(
            request,
            span_name=span_name,
            started_at=started_at,
            attributes=attributes,
            chat_trace=chat_trace,
        )

    def _emit_chat_span_failed(
        self,
        request: ReplyRequest,
        *,
        span_name: str,
        started_at: float,
        error: BaseException,
        chat_trace: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._tracer.emit_chat_span_failed(
            request,
            span_name=span_name,
            started_at=started_at,
            error=error,
            failure_metadata=_telemetry_failure_metadata(error),
            chat_trace=chat_trace,
        )

    @staticmethod
    def _chat_execution_observability(
        *,
        request: ReplyRequest,
        message_id: str,
        chat_trace: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata_context = request.metadata.get("execution_observability")
        context: Dict[str, Any] = (
            dict(metadata_context) if isinstance(metadata_context, dict) else {}
        )
        context.update(
            {
                "run_id": request.run_id,
                "cycle_id": context.get("cycle_id"),
                "work_item_id": request.work_item_id,
                "project_id": request.project_id,
                "org_id": request.org_id,
                "agent_id": request.agent_id,
                "model_id": request.metadata.get("llm_model_id"),
                "surface": "chat",
                "conversation_id": request.conversation_id,
                "message_id": request.user_message_id,
                "reply_message_id": message_id,
                "request_id": request.metadata.get("request_id")
                or f"chat:{request.conversation_id}:{request.user_message_id}",
                "execution_mode": context.get("execution_mode"),
                "source_type": "chat",
                "queue_job_id": context.get("queue_job_id"),
                "trace_id": chat_trace.get("trace_id"),
                "span_id": chat_trace.get("span_id"),
            }
        )
        return {key: value for key, value in context.items() if value is not None}

    @staticmethod
    def _is_execution_handoff(
        route_metadata: Dict[str, Any],
        request: ReplyRequest,
    ) -> bool:
        route = route_metadata.get("chat_route") or {}
        candidates = route.get("candidates") or []
        action_ids = {str(candidate.get("action_id") or "") for candidate in candidates}
        return bool(
            request.run_id
            or request.work_item_id
            or "execution.start" in action_ids
            or "execution.cancel" in action_ids
        )

    @staticmethod
    def _chat_trace_metadata(
        *,
        request: ReplyRequest,
        message_id: str,
        route_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        route = route_metadata.get("chat_route") or {}
        candidates = route.get("candidates") or []
        primary = candidates[0] if candidates else {}
        return sanitize_observability_payload({
            "trace_id": f"chat:{request.conversation_id}:{request.user_message_id}",
            "span_id": f"reply:{message_id}",
            "parent_span_id": f"user_message:{request.user_message_id}",
            "conversation_id": request.conversation_id,
            "user_message_id": request.user_message_id,
            "reply_message_id": message_id,
            "work_item_id": request.work_item_id,
            "run_id": request.run_id,
            "org_id": request.org_id,
            "project_id": request.project_id,
            "route_action_id": primary.get("action_id"),
            "route_category": primary.get("category"),
            "route_mode": route_metadata.get("chat_route_mode"),
            "requires_approval": route_metadata.get("chat_route_requires_approval"),
            "requires_clarification": route_metadata.get(
                "chat_route_requires_clarification"
            ),
        })

    @staticmethod
    def _composed_includes_workspace_inventory(composed: ComposedContext) -> bool:
        for src in composed.sources_included:
            value = getattr(src, "value", src)
            if value == DataSourceType.WORKSPACE_INVENTORY.value:
                return True
        return False

    @staticmethod
    def _workspace_inventory_from_context(composed: ComposedContext) -> Optional[Dict[str, Any]]:
        for fragment in composed.fragments_included:
            if getattr(fragment.source, "value", str(fragment.source)) != "workspace_inventory":
                continue
            inventory = fragment.metadata.get("inventory") if fragment.metadata else None
            if isinstance(inventory, dict):
                return inventory
        return None

    @staticmethod
    def _find_project_for_query(query: str, projects: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        normalized_query = ConversationReplyService._normalize_lookup_text(query)
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0
        for project in projects:
            candidates = [
                ConversationReplyService._first_present(project, "id", "project_id", default=""),
                ConversationReplyService._first_present(project, "slug", default=""),
                ConversationReplyService._first_present(project, "name", "title", default=""),
            ]
            for candidate in candidates:
                candidate_text = ConversationReplyService._normalize_lookup_text(str(candidate))
                if not candidate_text:
                    continue
                if re.search(rf"\b{re.escape(candidate_text)}\b", normalized_query):
                    score = len(candidate_text)
                    if score > best_score:
                        best_match = project
                        best_score = score
        return best_match

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @staticmethod
    def _first_present(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            value = data.get(key)
            if value is not None:
                return value
        return default

    def _route_user_message(self, request: ReplyRequest):
        conversation_scope = request.metadata.get("conversation_scope")
        if not conversation_scope:
            conversation_scope = (
                ConversationScope.PROJECT_SPACE.value
                if request.project_id
                else ConversationScope.GLOBAL_USER_HOME.value
            )
        route_request = ChatActionRouteRequest(
            message=request.user_message_content,
            conversation_scope=ConversationScope(conversation_scope),
            user_id=request.user_id,
            org_id=request.org_id,
            project_id=request.project_id,
            conversation_id=request.conversation_id,
            resource_links=request.metadata.get("resource_links", ()),
            metadata=enrich_chat_routing_metadata(request.metadata or {}, request.user_message_content),
        )
        return self._route_gateway.route(route_request)

    def _log_route_audit(
        self,
        request: ReplyRequest,
        route_metadata: Dict[str, Any],
    ) -> None:
        audit = self._governed_chat_audit
        if audit is None and self._telemetry is not None:
            audit = GovernedChatAuditLogger(telemetry=self._telemetry)
        if audit is None:
            return

        route = route_metadata.get("chat_route", {})
        candidates = route.get("candidates", [])
        primary = candidates[0] if candidates else {}
        audit.log(
            event_type=GovernedChatAuditEventType.INTENT_CLASSIFICATION,
            user_id=request.user_id,
            action=str(primary.get("action_id") or "chat.unclassified"),
            decision=(
                "clarification_required"
                if route_metadata.get("chat_route_requires_clarification")
                else "classified"
            ),
            chat_scope=str(
                request.metadata.get("conversation_scope")
                or (
                    ConversationScope.PROJECT_SPACE.value
                    if request.project_id
                    else ConversationScope.GLOBAL_USER_HOME.value
                )
            ),
            target_resources=[
                {
                    "type": primary.get("target_resource_type") or "conversation",
                    "id": request.conversation_id,
                }
            ],
            run_id=request.run_id,
            work_item_id=request.work_item_id,
            conversation_id=request.conversation_id,
            message_id=request.user_message_id,
            metadata={
                "route_mode": route_metadata.get("chat_route_mode"),
                "chat_query_intent": route_metadata.get("chat_query_intent"),
                "selected_model": request.metadata.get("llm_model_id"),
                "credential_scope": request.metadata.get("credential_scope"),
                "confidence": route_metadata.get("chat_route_confidence"),
                "requires_approval": route_metadata.get("chat_route_requires_approval"),
                "requires_clarification": route_metadata.get(
                    "chat_route_requires_clarification"
                ),
                "permission_surface": primary.get("permission_surface"),
                "permission_action": primary.get("permission_action"),
            },
        )

    async def generate_reply_stream(
        self,
        request: ReplyRequest,
    ) -> AsyncGenerator[str, None]:
        """Generate reply as an async token stream.

        Yields tokens as they are generated. Useful for direct SSE streaming
        without going through ConversationEventHub.

        Args:
            request: Reply request

        Yields:
            Generated tokens
        """
        # Compose context
        composed = await self._compose_context(
            request,
            include_conversation_history=self._conversation_service is None,
        )

        messages = await self._build_llm_messages(request, composed)

        if self._llm_client is None:
            raise RuntimeError("LLM client not configured")

        # Stream tokens
        if hasattr(self._llm_client, "stream"):
            async for token in self._llm_client.stream(messages):
                yield token
        else:
            # Non-streaming fallback - yield entire response
            response = self._llm_client.call(messages)
            content = response.content if hasattr(response, "content") else str(response)
            yield content


__all__ = [
    "ConversationReplyService",
    "ReplyRequest",
    "ReplyResult",
]
