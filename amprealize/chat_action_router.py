"""Typed chat action routing for governed platform actions.

The router is intentionally deterministic for the first implementation slice:
natural-language messages and preset commands map to typed action candidates
that policy composition, approval UX, and execution services can consume.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .conversation_contracts import (
    ChatPermissionAction,
    ChatPermissionEffect,
    ChatPermissionRequirement,
    ChatPermissionScope,
    ChatPermissionSurface,
    ConversationScope,
    get_chat_permission_requirement,
    normalize_conversation_scope,
)
from .llm.client import LLMClient


class ChatActionCategory(str, Enum):
    """Top-level action families supported by Amprealize Chat."""

    READ_SYNTHESIS = "read_synthesis"
    RESOURCE_ANALYSIS = "resource_analysis"
    WORK_MANAGEMENT = "work_management"
    AGENT_MANAGEMENT = "agent_management"
    EXECUTION_PLANNING = "execution_planning"
    EXECUTION_START = "execution_start"
    EXECUTION_CANCEL = "execution_cancel"
    MCP_TOOL = "mcp_tool"
    ATTACHMENT = "attachment"
    INVITE_SHARE = "invite_share"


class ChatActionRisk(str, Enum):
    """Risk level used before policy evaluation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ChatActionCandidate:
    """A typed action candidate returned by the router."""

    action_id: str
    category: ChatActionCategory
    permission_surface: ChatPermissionSurface
    permission_action: ChatPermissionAction
    confidence: float
    risk: ChatActionRisk
    required_scopes: Sequence[ChatPermissionScope]
    requires_approval: bool = False
    requires_clarification: bool = False
    preset: Optional[str] = None
    target_resource_type: Optional[str] = None
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_policy_context(self) -> Dict[str, Any]:
        return {
            "chat_surface": self.permission_surface.value,
            "chat_action": self.permission_action.value,
            "action_risk": self.risk.value,
            "sensitive_operation": self.requires_approval,
            "chat_action_candidate": self.to_dict(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "category": self.category.value,
            "permission_surface": self.permission_surface.value,
            "permission_action": self.permission_action.value,
            "confidence": self.confidence,
            "risk": self.risk.value,
            "required_scopes": [scope.value for scope in self.required_scopes],
            "requires_approval": self.requires_approval,
            "requires_clarification": self.requires_clarification,
            "preset": self.preset,
            "target_resource_type": self.target_resource_type,
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ChatActionRouteRequest:
    """Input to the chat action router."""

    message: str
    conversation_scope: ConversationScope = ConversationScope.GLOBAL_USER_HOME
    user_id: str = ""
    org_id: Optional[str] = None
    project_id: Optional[str] = None
    conversation_id: Optional[str] = None
    resource_links: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatActionRouteResult:
    """Router output with one or more action candidates."""

    candidates: Sequence[ChatActionCandidate]
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None

    @property
    def primary(self) -> Optional[ChatActionCandidate]:
        return self.candidates[0] if self.candidates else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "requires_clarification": self.requires_clarification,
            "clarification_prompt": self.clarification_prompt,
        }


@dataclass(frozen=True)
class _RoutePattern:
    category: ChatActionCategory
    permission_surface: ChatPermissionSurface
    permission_action: ChatPermissionAction
    risk: ChatActionRisk
    keywords: frozenset[str]
    action_id: str
    target_resource_type: Optional[str] = None
    preset: Optional[str] = None
    rationale: str = ""


_PRESET_ALIASES = {
    "/plan": "plan",
    "/execute": "execute",
    "/run": "execute",
    "/cancel": "cancel execution",
    "/work-item": "work item",
    "/workitem": "work item",
    "/agent": "agent",
    "/tool": "tool",
    "/attach": "attach",
    "/invite": "invite",
}


_EXECUTION_CANCEL_KEYWORDS = frozenset(
    {
        "cancel execution",
        "stop execution",
        "abort execution",
        "cancel the run",
        "stop the run",
        "halt execution",
        "terminate execution",
        "kill the run",
        "cancel run",
        "stop run",
        "abort run",
        "cancel agent run",
        "stop agent run",
    }
)


_ROUTE_PATTERNS: tuple[_RoutePattern, ...] = (
    _RoutePattern(
        category=ChatActionCategory.EXECUTION_PLANNING,
        permission_surface=ChatPermissionSurface.WORK_ITEM_THREAD,
        permission_action=ChatPermissionAction.EXECUTE,
        risk=ChatActionRisk.MEDIUM,
        keywords=frozenset({"plan", "draft", "proposal", "estimate"}),
        action_id="execution.plan",
        target_resource_type="plan",
        preset="/plan",
        rationale="Generate a plan artifact before execution.",
    ),
    _RoutePattern(
        category=ChatActionCategory.EXECUTION_START,
        permission_surface=ChatPermissionSurface.WORK_ITEM_THREAD,
        permission_action=ChatPermissionAction.EXECUTE,
        risk=ChatActionRisk.HIGH,
        keywords=frozenset({"execute", "start", "run", "implement", "ship"}),
        action_id="execution.start",
        target_resource_type="run",
        preset="/execute",
        rationale="Start or resume a governed execution run.",
    ),
    _RoutePattern(
        category=ChatActionCategory.EXECUTION_CANCEL,
        permission_surface=ChatPermissionSurface.WORK_ITEM_THREAD,
        permission_action=ChatPermissionAction.EXECUTE,
        risk=ChatActionRisk.HIGH,
        keywords=_EXECUTION_CANCEL_KEYWORDS,
        action_id="execution.cancel",
        target_resource_type="run",
        preset="/cancel",
        rationale="Cancel or stop an active governed execution run.",
    ),
    _RoutePattern(
        category=ChatActionCategory.WORK_MANAGEMENT,
        permission_surface=ChatPermissionSurface.PLATFORM_ACTION,
        permission_action=ChatPermissionAction.CREATE,
        risk=ChatActionRisk.MEDIUM,
        keywords=frozenset({"work item", "task", "bug", "feature", "goal", "research", "ticket"}),
        action_id="work_item.manage",
        target_resource_type="work_item",
        preset="/work-item",
        rationale="Create or update work tracking objects.",
    ),
    _RoutePattern(
        category=ChatActionCategory.AGENT_MANAGEMENT,
        permission_surface=ChatPermissionSurface.AGENT_LIFECYCLE,
        permission_action=ChatPermissionAction.UPDATE,
        risk=ChatActionRisk.HIGH,
        keywords=frozenset({"agent", "playbook", "publish", "archive"}),
        action_id="agent.manage",
        target_resource_type="agent",
        preset="/agent",
        rationale="Manage agent lifecycle or policy.",
    ),
    _RoutePattern(
        category=ChatActionCategory.MCP_TOOL,
        permission_surface=ChatPermissionSurface.MCP_TOOL,
        permission_action=ChatPermissionAction.EXECUTE,
        risk=ChatActionRisk.HIGH,
        keywords=frozenset({"mcp", "tool", "invoke"}),
        action_id="mcp_tool.invoke",
        target_resource_type="mcp_tool",
        preset="/tool",
        rationale="Invoke an MCP tool from chat.",
    ),
    _RoutePattern(
        category=ChatActionCategory.ATTACHMENT,
        permission_surface=ChatPermissionSurface.ATTACHMENT,
        permission_action=ChatPermissionAction.CREATE,
        risk=ChatActionRisk.MEDIUM,
        keywords=frozenset({"attach", "upload", "file", "image"}),
        action_id="attachment.add",
        target_resource_type="file",
        preset="/attach",
        rationale="Attach or reference files in the conversation.",
    ),
    _RoutePattern(
        category=ChatActionCategory.INVITE_SHARE,
        permission_surface=ChatPermissionSurface.PROJECT_SPACE,
        permission_action=ChatPermissionAction.INVITE_SHARE,
        risk=ChatActionRisk.HIGH,
        keywords=frozenset({"invite", "share", "add member", "collaborator"}),
        action_id="project.invite_share",
        target_resource_type="project",
        preset="/invite",
        rationale="Invite or share access with another actor.",
    ),
    _RoutePattern(
        category=ChatActionCategory.RESOURCE_ANALYSIS,
        permission_surface=ChatPermissionSurface.GLOBAL_CHAT,
        permission_action=ChatPermissionAction.READ,
        risk=ChatActionRisk.LOW,
        keywords=frozenset({
            "how many",
            "count",
            "number of",
            "total",
            "list",
            "show",
            "which",
            "what",
            "summarize",
            "summary",
            "analyze",
            "insight",
            "group",
            "breakdown",
            "project",
            "board",
            "work item",
            "agent",
            "run",
            "behavior",
            "tool",
            "tools",
            "trace",
            "traces",
            "telemetry",
            "observability",
            "latency",
            "wiki",
            "setting",
            "user",
            "org",
        }),
        action_id="resource.analyze",
        rationale="Read, count, list, or analyze accessible Amprealize resources.",
    ),
    _RoutePattern(
        category=ChatActionCategory.READ_SYNTHESIS,
        permission_surface=ChatPermissionSurface.GLOBAL_CHAT,
        permission_action=ChatPermissionAction.READ,
        risk=ChatActionRisk.LOW,
        keywords=frozenset({"summarize", "explain", "find", "search", "show"}),
        action_id="chat.read_synthesis",
        rationale="Read or synthesize accessible resources.",
    ),
)

_VALID_ACTION_IDS = frozenset(pattern.action_id for pattern in _ROUTE_PATTERNS)

_READ_INTENT_KEYWORDS = frozenset(
    {
        "how many",
        "count",
        "number of",
        "total",
        "list",
        "show",
        "which",
        "what",
        "who",
        "where",
        "find",
        "search",
        "summarize",
        "summary",
        "analyze",
        "insight",
        "group",
        "breakdown",
        "compare",
        "look at",
        "tell me whether",
        "tell me if",
        "check if",
        "check whether",
    }
)

# Polar-question and investigation phrases that signal read intent even when
# they lack explicit read-query keywords.  All checked via substring (phrases
# naturally scope themselves without needing word boundaries).
_READ_INTENT_POLAR_PHRASES = frozenset(
    {
        "have we",
        "has this",
        "has it",
        "has the",
        "did we",
        "did it",
        "already",
        "is it",
        "are any",
        "is there",
        "is this",
        "are there",
        "do we have",
        "do we support",
    }
)

_MUTATION_INTENT_KEYWORDS = frozenset(
    {
        "create",
        "add",
        "new",
        "make",
        "file",
        "update",
        "change",
        "rename",
        "move",
        "assign",
        "archive",
        "delete",
        "remove",
        "publish",
        "invite",
        "share",
        "upload",
        "attach",
    }
)
_EXECUTION_INTENT_KEYWORDS = frozenset(
    {
        "execute",
        "start",
        "run this",
        "implement",
        "ship",
    }
)


class ChatRouteMode(str, Enum):
    """Routing implementation mode."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HYBRID = "hybrid"


class ChatWorkspaceIntent(str, Enum):
    """Intent buckets for workspace chat routing (deterministic vs hybrid)."""

    LIST_INVENTORY = "list_inventory"
    MUTATE = "mutate"
    ANALYTICS_OR_RATE = "analytics_or_rate"
    AMBIGUOUS_SCOPE = "ambiguous_scope"
    WORKSPACE_PRIORITIZE = "workspace_prioritize"
    CONVERSATIONAL_NON_INVENTORY = "conversational_non_inventory"


def detect_chat_workspace_intent(message: str) -> str:
    """Classify the user's message for routing; safe to call on any non-empty string."""

    normalized = re.sub(r"[^a-z0-9]+", " ", message.lower()).strip()
    if not normalized:
        return ChatWorkspaceIntent.LIST_INVENTORY.value
    if re.search(
        r"\b(create|add|make|execute|run|start|dispatch|trigger|update|set|delete|remove|cancel|stop)\b",
        normalized,
    ):
        return ChatWorkspaceIntent.MUTATE.value
    if re.search(
        r"\b(what should i work on|what to work on|what do i work on|prioritize|priorities for today|"
        r"focus today|next up|what should i focus|pick my next|start with what)\b",
        normalized,
    ) or (
        bool(re.search(r"\b(work on|focus on)\b", normalized))
        and bool(re.search(r"\b(today|now|next)\b", normalized))
    ):
        return ChatWorkspaceIntent.WORKSPACE_PRIORITIZE.value
    if re.search(
        r"\b(velocity|throughput|lead time|cycle time|how quickly|how fast|median|p95|percentile)\b",
        normalized,
    ) or (
        bool(re.search(r"\b(backlog|todo|queued|open)\b", normalized))
        and bool(re.search(r"\b(in progress|in-progress|started|doing|wip)\b", normalized))
        and bool(re.search(r"\b(time|duration|moving|transition|days|hours)\b", normalized))
    ):
        return ChatWorkspaceIntent.ANALYTICS_OR_RATE.value
    if _is_conversational_non_inventory_intent(normalized):
        return ChatWorkspaceIntent.CONVERSATIONAL_NON_INVENTORY.value
    if re.search(r"\b(which board|what board|which project|what project)\b", normalized):
        return ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value
    return ChatWorkspaceIntent.LIST_INVENTORY.value


def _is_conversational_non_inventory_intent(normalized: str) -> bool:
    """Meta questions, capability, or local-runtime access — not tabular inventory lists."""

    if re.search(
        r"\b(who are you|what model are you|what llm|which model are you|are you gpt|are you claude|"
        r"how do you work|are you an ai|are you connected to|what can you do for me|"
        r"what are your limitations|where do you run)\b",
        normalized,
    ):
        return True
    if re.search(r"\b(can you|could you)\s+(see|read|open|access)\b", normalized) and re.search(
        r"\b(path|paths|folder|folders|directory|directories|filesystem|file system|"
        r"disk|machine|computer|laptop|local|repo|git)\b",
        normalized,
    ):
        return True
    if re.search(r"\bdo you have access\b", normalized):
        if re.search(
            r"\b(how many|list\b|show me|show all|what are the|which projects?|what projects|count\b)\b",
            normalized,
        ):
            return False
        if re.search(
            r"\b(local|path|paths|filesystem|file system|files?|folders?|directories?|"
            r"disk|machine|computer|laptop|my machine|repo root|workspace path)\b",
            normalized,
        ):
            return True
        return True
    if re.search(r"\b(my|our)\s+(local|machine|computer|disk|laptop)\b", normalized) and re.search(
        r"\b(access|see|read|files?|path|paths|folders?)\b",
        normalized,
    ):
        return True
    return False


def enrich_chat_routing_metadata(metadata: Mapping[str, Any], message: str) -> Dict[str, Any]:
    """Copy metadata, attach ``chat_query_intent``, and optionally select hybrid routing."""

    out = dict(metadata)
    intent = detect_chat_workspace_intent(message)
    out["chat_query_intent"] = intent
    if intent in {
        ChatWorkspaceIntent.ANALYTICS_OR_RATE.value,
        ChatWorkspaceIntent.AMBIGUOUS_SCOPE.value,
    }:
        if not out.get("chat_route_mode"):
            out["chat_route_mode"] = ChatRouteMode.HYBRID.value
    return out


class ChatActionRouter:
    """Route natural-language chat text to typed action candidates."""

    def route(self, request: ChatActionRouteRequest) -> ChatActionRouteResult:
        normalized_message = self._normalize_message(request.message)
        if not normalized_message:
            return ChatActionRouteResult(
                candidates=(),
                requires_clarification=True,
                clarification_prompt="What would you like Amprealize Chat to do?",
            )

        preset = self._extract_preset(normalized_message)
        cancel_intent = self._has_execution_cancel_intent(normalized_message)
        candidates = [
            self._candidate_from_pattern(
                pattern,
                request=request,
                normalized_message=normalized_message,
                preset=preset,
            )
            for pattern in self._matching_patterns(request, normalized_message, preset)
        ]
        if cancel_intent:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.category != ChatActionCategory.EXECUTION_START
            ]
        if not candidates:
            candidates = [
                self._candidate_from_pattern(
                    self._read_synthesis_pattern(),
                    request=request,
                    normalized_message=normalized_message,
                    preset=preset,
                    force_clarification=True,
                )
            ]

        candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
        ambiguous = self._is_ambiguous(candidates)
        if ambiguous:
            candidates = [
                self._with_clarification(
                    candidate,
                    "Multiple chat actions matched this request.",
                )
                for candidate in candidates
            ]
        return ChatActionRouteResult(
            candidates=tuple(candidates),
            requires_clarification=ambiguous or candidates[0].requires_clarification,
            clarification_prompt=(
                "Should I treat this as planning, execution, work management, "
                "agent management, a tool call, attachment handling, or sharing?"
                if ambiguous
                else (
                    "Please clarify the target resource or action."
                    if candidates[0].requires_clarification
                    else None
                )
            ),
        )

    def _matching_patterns(
        self,
        request: ChatActionRouteRequest,
        normalized_message: str,
        preset: Optional[str],
    ) -> Iterable[_RoutePattern]:
        slot_followup = bool((request.metadata or {}).get("work_item_slot_followup"))
        if slot_followup:
            for pattern in _ROUTE_PATTERNS:
                if pattern.category == ChatActionCategory.WORK_MANAGEMENT:
                    yield pattern
            return

        read_intent = self._has_read_intent(normalized_message)
        mutation_intent = self._has_mutation_intent(normalized_message)
        execution_intent = self._has_execution_intent(normalized_message)
        if read_intent and not mutation_intent and not execution_intent:
            if self._mentions_known_resource(normalized_message):
                yield self._resource_analysis_pattern()
            else:
                yield self._read_synthesis_pattern()
            return

        cancel_execution_intent = self._has_execution_cancel_intent(normalized_message)

        for pattern in _ROUTE_PATTERNS:
            if preset and preset == pattern.preset:
                yield pattern
                continue
            if (
                pattern.category == ChatActionCategory.EXECUTION_START
                and cancel_execution_intent
            ):
                continue
            if pattern.category in {
                ChatActionCategory.WORK_MANAGEMENT,
                ChatActionCategory.AGENT_MANAGEMENT,
                ChatActionCategory.INVITE_SHARE,
                ChatActionCategory.ATTACHMENT,
            } and not mutation_intent:
                continue
            if pattern.category == ChatActionCategory.RESOURCE_ANALYSIS and not read_intent:
                continue
            if pattern.category == ChatActionCategory.EXECUTION_START and (
                _has_polar_question_intent(normalized_message)
                and not _has_imperative_execution_intent(normalized_message)
            ):
                # Polar questions like "have we already implemented X?" should not
                # route to EXECUTION_START.  Require an explicit imperative marker.
                continue
            if pattern.category == ChatActionCategory.EXECUTION_START and _has_negated_execution_intent(
                normalized_message
            ):
                # Negated execution phrases like "not asking you to execute anything"
                # explicitly deny execution intent and must not route to EXECUTION_START.
                continue
            if any(_keyword_matches_message(normalized_message, keyword) for keyword in pattern.keywords):
                yield pattern

    def _candidate_from_pattern(
        self,
        pattern: _RoutePattern,
        *,
        request: ChatActionRouteRequest,
        normalized_message: str,
        preset: Optional[str],
        force_clarification: bool = False,
    ) -> ChatActionCandidate:
        permission_surface = self._surface_for_pattern(pattern, request)
        permission = get_chat_permission_requirement(
            permission_surface,
            pattern.permission_action,
        )
        confidence = self._confidence(pattern, normalized_message, preset)
        requires_approval = (
            pattern.risk == ChatActionRisk.HIGH
            or permission.effect == ChatPermissionEffect.REQUIRE_APPROVAL
        )
        requires_clarification = force_clarification or self._needs_clarification(
            pattern,
            request,
            normalized_message,
        )
        return ChatActionCandidate(
            action_id=pattern.action_id,
            category=pattern.category,
            permission_surface=permission_surface,
            permission_action=pattern.permission_action,
            confidence=confidence,
            risk=pattern.risk,
            required_scopes=permission.scopes,
            requires_approval=requires_approval,
            requires_clarification=requires_clarification,
            preset=pattern.preset if preset == pattern.preset else None,
            target_resource_type=pattern.target_resource_type,
            rationale=pattern.rationale or permission.notes,
            metadata={
                "conversation_scope": normalize_conversation_scope(
                    request.conversation_scope
                ).value,
                "conversation_id": request.conversation_id,
                "project_id": request.project_id,
                "org_id": request.org_id,
                "resource_link_count": len(request.resource_links),
                "permission_effect": permission.effect.value,
                "intent_class": self._intent_class(normalized_message),
            },
        )

    def _needs_clarification(
        self,
        pattern: _RoutePattern,
        request: ChatActionRouteRequest,
        normalized_message: str,
    ) -> bool:
        if pattern.category in {
            ChatActionCategory.READ_SYNTHESIS,
            ChatActionCategory.RESOURCE_ANALYSIS,
        }:
            return False
        if pattern.category in {
            ChatActionCategory.EXECUTION_PLANNING,
            ChatActionCategory.EXECUTION_START,
            ChatActionCategory.EXECUTION_CANCEL,
        }:
            has_linked_work = any(
                link.get("resource_type") in {"work_item", "plan", "run"}
                for link in request.resource_links
            )
            return not has_linked_work and not request.project_id
        if pattern.category in {
            ChatActionCategory.WORK_MANAGEMENT,
            ChatActionCategory.AGENT_MANAGEMENT,
            ChatActionCategory.INVITE_SHARE,
        }:
            if pattern.category == ChatActionCategory.WORK_MANAGEMENT:
                if (request.metadata or {}).get("work_item_slot_followup"):
                    return False
                return not any(
                    keyword in normalized_message
                    for keyword in {"work item", "task", "bug", "feature", "goal", "research", "ticket"}
                )
            return pattern.target_resource_type not in normalized_message
        if pattern.category == ChatActionCategory.MCP_TOOL:
            return "tool" not in normalized_message and "mcp" not in normalized_message
        return False

    @staticmethod
    def _confidence(
        pattern: _RoutePattern,
        normalized_message: str,
        preset: Optional[str],
    ) -> float:
        if preset and preset == pattern.preset:
            return 0.98
        matches = sum(1 for keyword in pattern.keywords if keyword in normalized_message)
        return min(0.95, 0.55 + (matches * 0.12))

    @staticmethod
    def _is_ambiguous(candidates: Sequence[ChatActionCandidate]) -> bool:
        if len(candidates) < 2:
            return False
        return candidates[0].confidence - candidates[1].confidence < 0.1

    @staticmethod
    def _with_clarification(
        candidate: ChatActionCandidate,
        reason: str,
    ) -> ChatActionCandidate:
        return ChatActionCandidate(
            **{
                **candidate.__dict__,
                "requires_clarification": True,
                "metadata": {**candidate.metadata, "clarification_reason": reason},
            }
        )

    @staticmethod
    def _extract_preset(normalized_message: str) -> Optional[str]:
        first_token = normalized_message.split(" ", 1)[0]
        alias = _PRESET_ALIASES.get(first_token)
        if not alias:
            return None
        for pattern in _ROUTE_PATTERNS:
            if alias in pattern.keywords or first_token == pattern.preset:
                return pattern.preset
        return None

    @staticmethod
    def _normalize_message(message: str) -> str:
        return " ".join(message.strip().lower().split())

    @staticmethod
    def _read_synthesis_pattern() -> _RoutePattern:
        return next(
            pattern
            for pattern in _ROUTE_PATTERNS
            if pattern.category == ChatActionCategory.READ_SYNTHESIS
        )

    @staticmethod
    def _resource_analysis_pattern() -> _RoutePattern:
        return next(
            pattern
            for pattern in _ROUTE_PATTERNS
            if pattern.category == ChatActionCategory.RESOURCE_ANALYSIS
        )

    @staticmethod
    def _has_read_intent(normalized_message: str) -> bool:
        return any(
            _contains_keyword(normalized_message, keyword) for keyword in _READ_INTENT_KEYWORDS
        ) or any(phrase in normalized_message for phrase in _READ_INTENT_POLAR_PHRASES)

    @staticmethod
    def _has_mutation_intent(normalized_message: str) -> bool:
        return any(_contains_keyword(normalized_message, keyword) for keyword in _MUTATION_INTENT_KEYWORDS)

    @staticmethod
    def _has_execution_intent(normalized_message: str) -> bool:
        return any(_contains_keyword(normalized_message, keyword) for keyword in _EXECUTION_INTENT_KEYWORDS)

    @staticmethod
    def _has_execution_cancel_intent(normalized_message: str) -> bool:
        return any(phrase in normalized_message for phrase in _EXECUTION_CANCEL_KEYWORDS)

    @staticmethod
    def _mentions_known_resource(normalized_message: str) -> bool:
        return any(
            keyword in normalized_message
            for keyword in {
                "user",
                "org",
                "project",
                "board",
                "work item",
                "task",
                "bug",
                "feature",
                "goal",
                "agent",
                "run",
                "execution",
                "behavior",
                "tool",
                "tools",
                "trace",
                "traces",
                "telemetry",
                "observability",
                "latency",
                "wiki",
                "setting",
            }
        )

    @classmethod
    def _intent_class(cls, normalized_message: str) -> str:
        if cls._has_mutation_intent(normalized_message):
            return "mutation"
        if cls._has_execution_intent(normalized_message):
            return "execute"
        if cls._has_read_intent(normalized_message):
            return "read_query"
        return "ambiguous"

    @staticmethod
    def _surface_for_pattern(
        pattern: _RoutePattern,
        request: ChatActionRouteRequest,
    ) -> ChatPermissionSurface:
        if pattern.category not in {
            ChatActionCategory.READ_SYNTHESIS,
            ChatActionCategory.RESOURCE_ANALYSIS,
            ChatActionCategory.EXECUTION_PLANNING,
            ChatActionCategory.EXECUTION_START,
            ChatActionCategory.EXECUTION_CANCEL,
            ChatActionCategory.INVITE_SHARE,
        }:
            return pattern.permission_surface

        scope = normalize_conversation_scope(request.conversation_scope)
        if scope == ConversationScope.GROUP_CHAT:
            return ChatPermissionSurface.GROUP_CHAT
        if scope in {ConversationScope.PROJECT_SPACE, ConversationScope.PROJECT_ROOM}:
            return ChatPermissionSurface.PROJECT_SPACE
        if scope == ConversationScope.RUN_THREAD:
            return ChatPermissionSurface.RUN_THREAD
        if scope == ConversationScope.WORK_ITEM_THREAD:
            return ChatPermissionSurface.WORK_ITEM_THREAD

        if pattern.category in {
            ChatActionCategory.EXECUTION_PLANNING,
            ChatActionCategory.EXECUTION_START,
            ChatActionCategory.EXECUTION_CANCEL,
        }:
            linked_types = {str(link.get("resource_type")) for link in request.resource_links}
            if "run" in linked_types:
                return ChatPermissionSurface.RUN_THREAD
            if linked_types & {"work_item", "plan"}:
                return ChatPermissionSurface.WORK_ITEM_THREAD
            if request.project_id:
                return ChatPermissionSurface.PROJECT_SPACE

        return pattern.permission_surface


class LLMChatActionRouter:
    """Schema-constrained LLM router with deterministic post-validation."""

    def __init__(
        self,
        *,
        llm_client: Any = None,
        fallback_router: Optional[ChatActionRouter] = None,
        model: Optional[str] = None,
    ) -> None:
        self._llm_client = llm_client
        self._fallback_router = fallback_router or ChatActionRouter()
        self._model = model or os.getenv("AMPREALIZE_CHAT_ROUTING_MODEL")

    def route(self, request: ChatActionRouteRequest) -> ChatActionRouteResult:
        fallback_result = self._fallback_router.route(request)
        try:
            response = self._call_llm(request, fallback_result)
            payload = self._parse_json_payload(response.content)
            result = self._result_from_payload(payload, request)
            if not result.candidates:
                return self._with_fallback_metadata(fallback_result, "empty_llm_candidates")
            return result
        except Exception as exc:
            return self._with_fallback_metadata(
                fallback_result,
                "llm_route_failed",
                {"error": exc.__class__.__name__},
            )

    def _call_llm(
        self,
        request: ChatActionRouteRequest,
        fallback_result: ChatActionRouteResult,
    ) -> Any:
        client = self._llm_client
        if client is None:
            client = LLMClient()

        routing_model = (
            request.metadata.get("routing_model_id")
            or self._model
            or request.metadata.get("llm_model_id")
        )
        messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": request.message,
                        "conversation_scope": normalize_conversation_scope(
                            request.conversation_scope
                        ).value,
                        "project_id": request.project_id,
                        "org_id": request.org_id,
                        "resource_links": list(request.resource_links),
                        "deterministic_route": fallback_result.to_dict(),
                    },
                    sort_keys=True,
                ),
            },
        ]
        return client.call(
            messages,
            model=routing_model,
            temperature=0,
            max_tokens=1200,
            project_id=request.project_id,
            org_id=request.org_id,
            user_id=request.user_id,
            prefer_user_credential=request.metadata.get("credential_scope") == "user",
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You route Amprealize chat messages into a strict JSON object. "
            "Return only JSON with keys candidates, requires_clarification, "
            "clarification_prompt. candidates is an array of objects with keys: "
            "action_id, category, permission_surface, permission_action, "
            "confidence, risk, target_resource_type, rationale. "
            f"Allowed action_id values: {sorted(_VALID_ACTION_IDS)}. "
            f"Allowed category values: {[item.value for item in ChatActionCategory]}. "
            f"Allowed permission_surface values: {[item.value for item in ChatPermissionSurface]}. "
            f"Allowed permission_action values: {[item.value for item in ChatPermissionAction]}. "
            f"Allowed risk values: {[item.value for item in ChatActionRisk]}. "
            "Prefer the deterministic route unless the user intent clearly differs. "
            "Do not invent actions, permissions, tools, or resource identifiers."
        )

    @staticmethod
    def _parse_json_payload(content: str) -> Dict[str, Any]:
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("LLM route response did not contain JSON object")
        payload = json.loads(stripped[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("LLM route response JSON must be an object")
        return payload

    def _result_from_payload(
        self,
        payload: Dict[str, Any],
        request: ChatActionRouteRequest,
    ) -> ChatActionRouteResult:
        raw_candidates = payload.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError("LLM route candidates must be a list")

        candidates: list[ChatActionCandidate] = []
        for raw_candidate in raw_candidates[:3]:
            if not isinstance(raw_candidate, dict):
                continue
            candidates.append(self._candidate_from_payload(raw_candidate, request))

        candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
        requires_clarification = bool(payload.get("requires_clarification"))
        if candidates and candidates[0].confidence < 0.55:
            requires_clarification = True
        return ChatActionRouteResult(
            candidates=tuple(candidates),
            requires_clarification=requires_clarification
            or any(candidate.requires_clarification for candidate in candidates),
            clarification_prompt=(
                str(payload.get("clarification_prompt"))
                if payload.get("clarification_prompt")
                else (
                    "Please clarify the target resource or action."
                    if requires_clarification
                    else None
                )
            ),
        )

    @staticmethod
    def _candidate_from_payload(
        raw_candidate: Dict[str, Any],
        request: ChatActionRouteRequest,
    ) -> ChatActionCandidate:
        action_id = str(raw_candidate.get("action_id", ""))
        if action_id not in _VALID_ACTION_IDS:
            raise ValueError(f"Unknown chat action id: {action_id}")

        category = ChatActionCategory(str(raw_candidate.get("category", "")))
        permission_surface = ChatPermissionSurface(
            str(raw_candidate.get("permission_surface", ""))
        )
        permission_action = ChatPermissionAction(
            str(raw_candidate.get("permission_action", ""))
        )
        risk = ChatActionRisk(str(raw_candidate.get("risk", ChatActionRisk.MEDIUM.value)))
        permission = get_chat_permission_requirement(
            permission_surface,
            permission_action,
        )
        confidence = max(0.0, min(1.0, float(raw_candidate.get("confidence", 0.0))))
        requires_clarification = confidence < 0.55
        requires_approval = (
            risk == ChatActionRisk.HIGH
            or permission.effect == ChatPermissionEffect.REQUIRE_APPROVAL
        )
        return ChatActionCandidate(
            action_id=action_id,
            category=category,
            permission_surface=permission_surface,
            permission_action=permission_action,
            confidence=confidence,
            risk=risk,
            required_scopes=permission.scopes,
            requires_approval=requires_approval,
            requires_clarification=requires_clarification,
            target_resource_type=raw_candidate.get("target_resource_type"),
            rationale=str(raw_candidate.get("rationale") or permission.notes),
            metadata={
                "route_mode": ChatRouteMode.LLM.value,
                "conversation_scope": normalize_conversation_scope(
                    request.conversation_scope
                ).value,
                "conversation_id": request.conversation_id,
                "project_id": request.project_id,
                "org_id": request.org_id,
                "resource_link_count": len(request.resource_links),
                "permission_effect": permission.effect.value,
            },
        )

    @staticmethod
    def _with_fallback_metadata(
        result: ChatActionRouteResult,
        reason: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ChatActionRouteResult:
        candidates = tuple(
            ChatActionCandidate(
                **{
                    **candidate.__dict__,
                    "metadata": {
                        **candidate.metadata,
                        "route_mode": ChatRouteMode.DETERMINISTIC.value,
                        "fallback_reason": reason,
                        **(extra_metadata or {}),
                    },
                }
            )
            for candidate in result.candidates
        )
        return ChatActionRouteResult(
            candidates=candidates,
            requires_clarification=result.requires_clarification,
            clarification_prompt=result.clarification_prompt,
        )


class ChatRouteGateway:
    """Choose deterministic, LLM, or hybrid routing behind one stable contract."""

    def __init__(
        self,
        *,
        deterministic_router: Optional[ChatActionRouter] = None,
        llm_router: Optional[LLMChatActionRouter] = None,
        mode: Optional[ChatRouteMode | str] = None,
    ) -> None:
        self._deterministic_router = deterministic_router or ChatActionRouter()
        self._llm_router = llm_router or LLMChatActionRouter(
            fallback_router=self._deterministic_router
        )
        configured_mode = mode or os.getenv(
            "AMPREALIZE_CHAT_ROUTE_MODE",
            ChatRouteMode.DETERMINISTIC.value,
        )
        self._mode = ChatRouteMode(configured_mode)

    def route(self, request: ChatActionRouteRequest) -> ChatActionRouteResult:
        mode = ChatRouteMode(request.metadata.get("chat_route_mode") or self._mode)
        if mode == ChatRouteMode.DETERMINISTIC:
            return self._deterministic_router.route(request)
        if mode in {ChatRouteMode.LLM, ChatRouteMode.HYBRID}:
            return self._llm_router.route(request)
        return self._deterministic_router.route(request)


def _contains_keyword(normalized_message: str, keyword: str) -> bool:
    return bool(re.search(rf"\b{re.escape(keyword)}\b", normalized_message))


def _keyword_matches_message(normalized_message: str, keyword: str) -> bool:
    """Match a keyword or phrase in a normalized message.

    Single-token keywords use strict word-boundary matching to avoid matching
    substrings inside longer words (e.g. ``execute`` inside ``execution``, or
    ``implement`` inside ``implemented``).  Multi-word phrases already provide
    natural disambiguation so a simple substring check is used for them.
    """
    if " " in keyword:
        return keyword in normalized_message
    return bool(re.search(rf"\b{re.escape(keyword)}\b", normalized_message))


# Phrases that signal a polar/investigation question ("have we?", "did we?").
# Checked via substring since they are already multi-word and self-scoping.
_POLAR_QUESTION_PHRASES = frozenset(
    {
        "have we",
        "has this",
        "has it",
        "has the",
        "did we",
        "did it",
        "is it implemented",
        "is this implemented",
        "is it done",
        "tell me whether",
        "tell me if",
        "do we have",
    }
)

# Imperative execution markers that override the polar-question guard.
# A message must contain one of these to legitimately trigger EXECUTION_START.
_IMPERATIVE_EXECUTION_MARKERS = frozenset(
    {
        "execute this",
        "start this",
        "run this",
        "run it",
        "implement this",
        "ship this",
        "kick off",
        "begin execution",
        "trigger execution",
        "start the run",
        "execute the",
        "start the",
        "go ahead and",
        "please run",
        "please execute",
        "please start",
        "please implement",
    }
)


def _has_polar_question_intent(normalized_message: str) -> bool:
    """Return True when the message reads as a polar/investigation question."""
    return any(phrase in normalized_message for phrase in _POLAR_QUESTION_PHRASES)


def _has_imperative_execution_intent(normalized_message: str) -> bool:
    """Return True when the message contains an explicit imperative execution marker."""
    return any(phrase in normalized_message for phrase in _IMPERATIVE_EXECUTION_MARKERS)


# Phrases where the user explicitly negates execution intent, e.g. meta-corrections.
_NEGATED_EXECUTION_PHRASES = frozenset(
    {
        "not asking you to execute",
        "not asking to execute",
        "not asking you to run",
        "not asking to run",
        "not asking you to start",
        "not asking to start",
        "i'm asking you a question",
        "im asking you a question",
        "asking you a question",
        "not to execute",
        "don't execute",
        "do not execute",
    }
)


def _has_negated_execution_intent(normalized_message: str) -> bool:
    """Return True when the message explicitly denies execution intent."""
    return any(phrase in normalized_message for phrase in _NEGATED_EXECUTION_PHRASES)
