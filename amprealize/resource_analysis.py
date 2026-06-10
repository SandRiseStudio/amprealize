"""Natural-language analysis over accessible Amprealize resources.

Following `behavior_validate_cross_surface_parity` (Student): this module is a
shared read-only capability that chat and work-item agents can both call instead
of growing separate resource-question implementations per surface.
"""

from __future__ import annotations

import json
import math
import re
import secrets
from collections import Counter
import statistics
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


class ResourceAnalysisIntent(str, Enum):
    """High-level read-only intent detected from natural language."""

    COUNT = "count"
    LIST = "list"
    GROUP = "group"
    SUMMARIZE = "summarize"
    ANALYZE = "analyze"


@dataclass(frozen=True)
class ResourceFieldSpec:
    """Field metadata for safe resource analysis."""

    name: str
    label: str
    filterable: bool = True
    groupable: bool = True


@dataclass(frozen=True)
class ResourceSpec:
    """Catalog entry for one Amprealize resource family."""

    resource_type: str
    label: str
    aliases: Sequence[str]
    id_fields: Sequence[str]
    display_fields: Sequence[str]
    fields: Sequence[ResourceFieldSpec] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResourceQueryPlan:
    """A compact, auditable plan for a natural-language resource query."""

    intent: ResourceAnalysisIntent
    resource_type: str
    filters: Dict[str, Any] = field(default_factory=dict)
    group_by: Optional[str] = None
    llm_assisted: bool = False
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "resource_type": self.resource_type,
            "filters": {
                key: sorted(value) if isinstance(value, set) else value
                for key, value in self.filters.items()
            },
            "group_by": self.group_by,
            "llm_assisted": self.llm_assisted,
            "rationale": self.rationale,
        }


@dataclass
class ResourceAnalysisAnswer:
    """A read-only answer produced from accessible resource data."""

    content: str
    answer_type: str
    query_plan: ResourceQueryPlan
    structured_payload: Dict[str, Any] = field(default_factory=dict)
    source_rows: List[Dict[str, Any]] = field(default_factory=list)
    trace_steps: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    requires_clarification: bool = False


ResourceInventoryProvider = Callable[..., Any]


def _emit_resource_analysis_telemetry(
    answer: ResourceAnalysisAnswer,
    *,
    query: str,
    actor_surface: str,
) -> None:
    """Structured audit log for resource analysis (Raze when installed)."""

    try:
        from raze import RazeLogger
    except ImportError:
        return
    meta = answer.metadata
    logger = RazeLogger(service="resource-analysis", actor_surface=actor_surface)
    logger.info(
        "resource_analysis.completed",
        intent=answer.query_plan.intent.value,
        resource_type=answer.query_plan.resource_type,
        row_count=meta.get("row_count"),
        analysis_mode=meta.get("analysis_mode"),
        llm_assisted=meta.get("llm_assisted"),
        answer_type=answer.answer_type,
        empty_reason=meta.get("empty_reason"),
        chat_query_intent=meta.get("chat_query_intent"),
        query_preview=(query[:240] if query else ""),
    )


class ServiceBackedResourceInventoryProvider:
    """Builds access-scoped resource inventory from optional service objects.

    The analysis service only reasons over rows this provider returns. Each
    service call receives the current user/org/project context when the service
    signature supports it, keeping authorization at the adapter boundary.
    """

    def __init__(self, **services: Any) -> None:
        self._services = {name: service for name, service in services.items() if service is not None}

    async def __call__(
        self,
        *,
        query: str = "",
        user_id: str = "",
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        conversation_scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        context = {
            "query": query,
            "user_id": user_id,
            "org_id": org_id,
            "project_id": project_id,
            "conversation_scope": conversation_scope,
        }
        inventory: Dict[str, Any] = {}
        await self._collect_scalar_resources(inventory, context)
        await self._collect_project_scoped_resources(inventory, context)
        return {key: value for key, value in inventory.items() if value not in (None, [], {})}

    async def _collect_scalar_resources(self, inventory: Dict[str, Any], context: Mapping[str, Any]) -> None:
        scalar_specs = {
            "users": ("user_service", ("list_accessible_users", "list_users", "get_users")),
            "orgs": ("org_service", ("list_accessible_orgs", "list_orgs", "list_organizations")),
            "projects": ("project_service", ("list_accessible_projects", "list_projects", "get_projects")),
            "agent_assignments": ("agent_service", ("list_agent_assignments", "list_agents", "get_agents")),
            "runs": ("run_service", ("list_runs", "get_runs", "list_accessible_runs")),
            "behaviors": ("behavior_service", ("list_behaviors", "get_behaviors")),
            "wiki_pages": ("wiki_service", ("list_pages", "search_pages", "search")),
            "files": ("file_service", ("list_files", "get_files")),
            "credentials": ("credential_service", ("list_credentials", "get_credentials")),
            "conversations": ("conversation_service", ("list_conversations", "get_conversations")),
            "conversation_messages": ("conversation_service", ("list_messages", "get_messages")),
            "settings": ("settings_service", ("list_settings", "get_settings")),
        }
        for inventory_key, (service_name, method_names) in scalar_specs.items():
            result = await self._first_service_result(service_name, method_names, context)
            if result is not None:
                inventory[inventory_key] = result

    async def _collect_project_scoped_resources(self, inventory: Dict[str, Any], context: Mapping[str, Any]) -> None:
        projects = _list(inventory.get("projects"))
        project_ids = [
            str(_first_present(_to_dict(project), "project_id", "id"))
            for project in projects
            if _first_present(_to_dict(project), "project_id", "id")
        ]
        if context.get("project_id") and str(context["project_id"]) not in project_ids:
            project_ids.append(str(context["project_id"]))
        if not project_ids:
            return
        boards_by_project: Dict[str, Any] = {}
        work_items_by_project: Dict[str, Any] = {}
        for current_project_id in project_ids:
            scoped_context = {**context, "project_id": current_project_id}
            boards = await self._first_service_result(
                "board_service",
                ("list_boards", "get_boards", "list_project_boards"),
                scoped_context,
            )
            work_items = await self._first_service_result(
                "work_item_service",
                ("list_work_items", "get_work_items", "list_board_items"),
                scoped_context,
            )
            if work_items is None:
                work_items = await self._first_service_result(
                    "board_service",
                    ("list_work_items", "get_work_items", "list_board_items"),
                    scoped_context,
                )
            if boards is not None:
                boards_by_project[current_project_id] = boards
            if work_items is not None:
                work_items_by_project[current_project_id] = work_items
        if boards_by_project:
            inventory["boards_by_project"] = boards_by_project
        if work_items_by_project:
            inventory["work_items_by_project"] = work_items_by_project

    async def _first_service_result(
        self,
        service_name: str,
        method_names: Sequence[str],
        context: Mapping[str, Any],
    ) -> Any:
        service = self._services.get(service_name)
        if service is None:
            return None
        for method_name in method_names:
            method = getattr(service, method_name, None)
            if method is None:
                continue
            result = await _call_with_supported_context(method, context)
            if result is not None:
                return result
        return None


def _query_is_local_runtime_path_question(normalized_query: str) -> bool:
    """True when the user asks about local disk/IDE paths, not Amprealize projects.

    Without this guard, ``project`` in phrases like *local project path* matches
    the projects resource alias and yields a misleading *I found N projects…*
    inventory list instead of letting the conversational model answer.
    """

    if not normalized_query:
        return False
    if re.search(r"\bdo you have access\b", normalized_query):
        if re.search(
            r"\b(local|path|paths|filesystem|file system|folder|folders|directory|directories|"
            r"disk|machine|computer|laptop|checkout|repo root|workspace path)\b",
            normalized_query,
        ):
            return True
        if re.search(r"\bfiles?\b", normalized_query) and re.search(
            r"\b(local|path|paths|machine|computer|laptop|disk)\b",
            normalized_query,
        ):
            return True
    if re.search(
        r"\b(local project|project path|local path|repo root|workspace path|"
        r"on my machine|this machine|filesystem|file system|absolute path)\b",
        normalized_query,
    ):
        return True
    if re.search(r"\b(could you|can you)\s+(see|read|open|access)\b", normalized_query) and re.search(
        r"\b(path|paths|folder|folders|directory|directories|disk|filesystem|local)\b",
        normalized_query,
    ):
        return True
    if re.search(r"\b(my|our)\s+(local|machine|computer|disk|laptop)\b", normalized_query):
        return True
    if (
        re.search(r"\b(local|path|paths)\b", normalized_query)
        and re.search(r"\b(files?|folders?|directories?)\b", normalized_query)
        and re.search(r"\b(project|repo|git)\b", normalized_query)
    ):
        return True
    return False


class ResourceCatalog:
    """Describes supported Amprealize resource families for safe analysis."""

    def __init__(self, specs: Optional[Iterable[ResourceSpec]] = None) -> None:
        self._specs = {spec.resource_type: spec for spec in (specs or _DEFAULT_SPECS)}
        self._alias_to_type: Dict[str, str] = {}
        for spec in self._specs.values():
            self._alias_to_type[spec.resource_type] = spec.resource_type
            for alias in spec.aliases:
                self._alias_to_type[_normalize(alias)] = spec.resource_type

    def get(self, resource_type: str) -> ResourceSpec:
        return self._specs[resource_type]

    def resource_types(self) -> List[str]:
        return sorted(self._specs)

    def detect_resource_type(self, query: str) -> Optional[str]:
        normalized = _normalize(query)
        if _query_is_local_runtime_path_question(normalized):
            return None
        # Prefer specific resource nouns over generic "project(s)" / org tokens.
        priority: tuple[tuple[str, str], ...] = (
            (
                r"\b(work item|work items|board item|board items|task|tasks|bug|bugs|feature|features)\b",
                "work_items",
            ),
            # Prefer work items when agile flow + generic "items" beats bare "board" in "project board".
            (
                r"\b(items?|tasks?|bugs?)\b.*\b(backlog|todo|queued|open)\b.*\b(in progress|in-progress|started|doing|wip)\b",
                "work_items",
            ),
            (
                r"\b(backlog|todo|queued|open)\b.*\b(in progress|in-progress|started|doing|wip)\b.*\b(items?|tasks?|bugs?)\b",
                "work_items",
            ),
            (
                r"\b(items?|tasks?|bugs?)\b.*\b(moving|velocity|throughput|how quickly|how fast|lead time|cycle time)\b",
                "work_items",
            ),
            (r"\b(board|boards)\b", "boards"),
            (r"\b(agent|agents)\b", "agents"),
            (r"\b(run|runs|execution|executions)\b", "runs"),
            (r"\b(behavior|behaviors)\b", "behaviors"),
            (r"\b(wiki|wiki page|wiki pages|doc|docs)\b", "wiki_pages"),
            (r"\b(credential|credentials|secret|secrets|token|tokens)\b", "credentials"),
            (r"\b(chat message|chat messages)\b", "conversation_messages"),
            (r"\b(conversation|conversations|chat|chats|thread|threads)\b", "conversations"),
        )
        for pattern, rtype in priority:
            if rtype in self._specs and re.search(pattern, normalized):
                return rtype
        best_type: Optional[str] = None
        best_len = 0
        for alias, resource_type in self._alias_to_type.items():
            if re.search(rf"\b{re.escape(alias)}\b", normalized) and len(alias) > best_len:
                best_type = resource_type
                best_len = len(alias)
        return best_type


class ResourceAnalysisService:
    """Answers natural-language questions over already access-checked resources."""

    def __init__(
        self,
        *,
        catalog: Optional[ResourceCatalog] = None,
        inventory_provider: Optional[ResourceInventoryProvider] = None,
        llm_client: Optional[Any] = None,
    ) -> None:
        self._catalog = catalog or ResourceCatalog()
        self._inventory_provider = inventory_provider
        self._llm_client = llm_client

    @staticmethod
    def _telemetry_extra_from_hints(scope_hints: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        if not scope_hints:
            return None
        intent = scope_hints.get("chat_query_intent")
        if intent:
            return {"chat_query_intent": intent}
        return None

    def _finalize_answer(
        self,
        answer: Optional[ResourceAnalysisAnswer],
        *,
        query: str,
        actor_surface: str,
        telemetry_extra: Optional[Mapping[str, Any]] = None,
    ) -> Optional[ResourceAnalysisAnswer]:
        if answer is not None:
            for key, value in (telemetry_extra or {}).items():
                if value is not None:
                    answer.metadata[key] = value
            _emit_resource_analysis_telemetry(answer, query=query, actor_surface=actor_surface)
        return answer

    async def answer(
        self,
        *,
        query: str,
        inventory: Optional[Mapping[str, Any]] = None,
        user_id: str = "",
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        conversation_scope: Optional[str] = None,
        scope_hints: Optional[Mapping[str, Any]] = None,
    ) -> Optional[ResourceAnalysisAnswer]:
        normalized_query = _normalize(query)
        if not normalized_query:
            return None

        resolved_inventory = dict(inventory or {})
        if not resolved_inventory and self._inventory_provider is not None:
            provided = self._inventory_provider(
                query=query,
                user_id=user_id,
                org_id=org_id,
                project_id=project_id,
                conversation_scope=conversation_scope,
            )
            if hasattr(provided, "__await__"):
                provided = await provided
            if isinstance(provided, Mapping):
                resolved_inventory = dict(provided)

        plan = self._build_plan(normalized_query, query=query)
        if plan is None:
            return None
        plan = self._try_llm_plan(query, plan)
        merged_hints = dict(scope_hints or {})
        if project_id and not merged_hints.get("project_id"):
            merged_hints["project_id"] = str(project_id)
        telem = self._telemetry_extra_from_hints(merged_hints)

        rows = self._rows_for_resource(plan.resource_type, resolved_inventory)
        rows, scope_meta = self._apply_named_scope(
            normalized_query, plan.resource_type, rows, resolved_inventory, merged_hints
        )
        if scope_meta.get("ambiguous_board") and plan.resource_type == "work_items":
            eff = scope_meta.get("effective_project_id")
            clarify = self._try_multi_board_clarification_answer(
                query=query,
                plan=plan,
                inventory=resolved_inventory,
                project_id=str(eff) if eff else None,
            )
            if clarify is not None:
                return self._finalize_answer(
                    clarify, query=query, actor_surface="async", telemetry_extra=telem
                )

        rows_pre_filter = list(rows)
        if plan.resource_type == "work_items" and self._is_backlog_in_progress_velocity_question(
            normalized_query
        ):
            vrows = self._apply_filters(rows_pre_filter, plan.filters)
            vrows = self._maybe_take_latest_recency_rows(
                normalized_query, plan.resource_type, plan.intent, vrows
            )
            metric = self._backlog_to_in_progress_velocity_answer(
                query=query, plan=plan, rows=vrows
            )
            return self._finalize_answer(
                metric, query=query, actor_surface="async", telemetry_extra=telem
            )

        rows = self._apply_filters(rows_pre_filter, plan.filters)
        rows = self._maybe_take_latest_recency_rows(
            normalized_query, plan.resource_type, plan.intent, rows
        )

        if plan.resource_type == "agents" and self._is_agent_project_membership_question(
            normalized_query
        ):
            mem = ResourceAnalysisService._agent_project_membership_answer(
                query=query,
                plan=plan,
                rows=rows,
                inventory=resolved_inventory,
                scope_meta=scope_meta,
            )
            if mem is not None:
                return self._finalize_answer(
                    mem, query=query, actor_surface="async", telemetry_extra=telem
                )

        if plan.intent == ResourceAnalysisIntent.COUNT:
            return self._finalize_answer(
                self._count_answer(
                    plan,
                    rows,
                    inventory=resolved_inventory,
                    scope_meta=scope_meta,
                    rows_pre_filter=rows_pre_filter,
                ),
                query=query,
                actor_surface="async",
                telemetry_extra=telem,
            )
        if plan.intent == ResourceAnalysisIntent.GROUP:
            return self._finalize_answer(
                self._group_answer(plan, rows),
                query=query,
                actor_surface="async",
                telemetry_extra=telem,
            )
        if plan.intent in {ResourceAnalysisIntent.SUMMARIZE, ResourceAnalysisIntent.ANALYZE}:
            llm_answer = self._try_llm_summary(query, plan, rows)
            if llm_answer:
                return self._finalize_answer(
                    llm_answer, query=query, actor_surface="async", telemetry_extra=telem
                )
        if plan.intent == ResourceAnalysisIntent.SUMMARIZE:
            return self._finalize_answer(
                self._summary_answer(plan, rows),
                query=query,
                actor_surface="async",
                telemetry_extra=telem,
            )
        return self._finalize_answer(
            self._list_answer(
                plan,
                rows,
                inventory=resolved_inventory,
                rows_pre_filter=rows_pre_filter,
            ),
            query=query,
            actor_surface="async",
            telemetry_extra=telem,
        )

    def answer_sync(
        self,
        *,
        query: str,
        inventory: Optional[Mapping[str, Any]] = None,
        scope_hints: Optional[Mapping[str, Any]] = None,
    ) -> Optional[ResourceAnalysisAnswer]:
        """Synchronous deterministic path for callers that already have inventory."""

        normalized_query = _normalize(query)
        resource_type = self._catalog.detect_resource_type(query)
        if not normalized_query or resource_type is None:
            return None
        plan = self._build_plan(normalized_query, query=query)
        if plan is None:
            return None
        resolved_inventory = dict(inventory or {})
        merged_hints = dict(scope_hints or {})
        telem = self._telemetry_extra_from_hints(merged_hints)

        rows = self._rows_for_resource(resource_type, resolved_inventory)
        rows, scope_meta = self._apply_named_scope(
            normalized_query, resource_type, rows, resolved_inventory, merged_hints
        )
        if scope_meta.get("ambiguous_board") and resource_type == "work_items":
            eff = scope_meta.get("effective_project_id")
            clarify = self._try_multi_board_clarification_answer(
                query=query,
                plan=plan,
                inventory=resolved_inventory,
                project_id=str(eff) if eff else None,
            )
            if clarify is not None:
                return self._finalize_answer(
                    clarify,
                    query=query,
                    actor_surface="sync_inventory_fragment",
                    telemetry_extra=telem,
                )

        rows_pre_filter = list(rows)
        if resource_type == "work_items" and self._is_backlog_in_progress_velocity_question(
            normalized_query
        ):
            vrows = self._apply_filters(rows_pre_filter, plan.filters)
            vrows = self._maybe_take_latest_recency_rows(
                normalized_query, resource_type, plan.intent, vrows
            )
            metric = self._backlog_to_in_progress_velocity_answer(
                query=query, plan=plan, rows=vrows
            )
            return self._finalize_answer(
                metric,
                query=query,
                actor_surface="sync_inventory_fragment",
                telemetry_extra=telem,
            )

        rows = self._apply_filters(rows_pre_filter, plan.filters)
        rows = self._maybe_take_latest_recency_rows(
            normalized_query, resource_type, plan.intent, rows
        )
        if plan.resource_type == "agents" and ResourceAnalysisService._is_agent_project_membership_question(
            normalized_query
        ):
            mem = ResourceAnalysisService._agent_project_membership_answer(
                query=query,
                plan=plan,
                rows=rows,
                inventory=resolved_inventory,
                scope_meta=scope_meta,
            )
            if mem is not None:
                return self._finalize_answer(
                    mem,
                    query=query,
                    actor_surface="sync_inventory_fragment",
                    telemetry_extra=telem,
                )
        if plan.intent == ResourceAnalysisIntent.COUNT:
            return self._finalize_answer(
                self._count_answer(
                    plan,
                    rows,
                    inventory=resolved_inventory,
                    scope_meta=scope_meta,
                    rows_pre_filter=rows_pre_filter,
                ),
                query=query,
                actor_surface="sync_inventory_fragment",
                telemetry_extra=telem,
            )
        if plan.intent == ResourceAnalysisIntent.GROUP:
            return self._finalize_answer(
                self._group_answer(plan, rows),
                query=query,
                actor_surface="sync_inventory_fragment",
                telemetry_extra=telem,
            )
        if plan.intent == ResourceAnalysisIntent.SUMMARIZE:
            return self._finalize_answer(
                self._summary_answer(plan, rows),
                query=query,
                actor_surface="sync_inventory_fragment",
                telemetry_extra=telem,
            )
        return self._finalize_answer(
            self._list_answer(
                plan,
                rows,
                inventory=resolved_inventory,
                rows_pre_filter=rows_pre_filter,
            ),
            query=query,
            actor_surface="sync_inventory_fragment",
            telemetry_extra=telem,
        )

    def answer_plan_sync(
        self,
        *,
        query: str,
        query_plan: ResourceQueryPlan,
        inventory: Optional[Mapping[str, Any]] = None,
        scope_hints: Optional[Mapping[str, Any]] = None,
    ) -> Optional[ResourceAnalysisAnswer]:
        """Synchronous execution for a prevalidated resource query plan."""

        normalized_query = _normalize(query)
        if not normalized_query:
            return None
        resolved_inventory = dict(inventory or {})
        merged_hints = dict(scope_hints or {})
        telem = self._telemetry_extra_from_hints(merged_hints)

        rows = self._rows_for_resource(query_plan.resource_type, resolved_inventory)
        rows, scope_meta = self._apply_named_scope(
            normalized_query,
            query_plan.resource_type,
            rows,
            resolved_inventory,
            merged_hints,
        )
        if scope_meta.get("ambiguous_board") and query_plan.resource_type == "work_items":
            eff = scope_meta.get("effective_project_id")
            clarify = self._try_multi_board_clarification_answer(
                query=query,
                plan=query_plan,
                inventory=resolved_inventory,
                project_id=str(eff) if eff else None,
            )
            if clarify is not None:
                return self._finalize_answer(
                    clarify,
                    query=query,
                    actor_surface="sync_chat_query_plan",
                    telemetry_extra=telem,
                )

        rows_pre_filter = list(rows)
        rows = self._apply_filters(rows_pre_filter, query_plan.filters)
        rows = self._maybe_take_latest_recency_rows(
            normalized_query,
            query_plan.resource_type,
            query_plan.intent,
            rows,
        )
        if query_plan.intent == ResourceAnalysisIntent.COUNT:
            return self._finalize_answer(
                self._count_answer(
                    query_plan,
                    rows,
                    inventory=resolved_inventory,
                    scope_meta=scope_meta,
                    rows_pre_filter=rows_pre_filter,
                ),
                query=query,
                actor_surface="sync_chat_query_plan",
                telemetry_extra=telem,
            )
        if query_plan.intent == ResourceAnalysisIntent.GROUP:
            return self._finalize_answer(
                self._group_answer(query_plan, rows),
                query=query,
                actor_surface="sync_chat_query_plan",
                telemetry_extra=telem,
            )
        if query_plan.intent == ResourceAnalysisIntent.SUMMARIZE:
            return self._finalize_answer(
                self._summary_answer(query_plan, rows),
                query=query,
                actor_surface="sync_chat_query_plan",
                telemetry_extra=telem,
            )
        return self._finalize_answer(
            self._list_answer(
                query_plan,
                rows,
                inventory=resolved_inventory,
                rows_pre_filter=rows_pre_filter,
            ),
            query=query,
            actor_surface="sync_chat_query_plan",
            telemetry_extra=telem,
        )

    def _build_plan(self, normalized_query: str, *, query: str) -> Optional[ResourceQueryPlan]:
        resource_type = self._catalog.detect_resource_type(query)
        if resource_type is None:
            return None
        return ResourceQueryPlan(
            intent=self._detect_intent(normalized_query),
            resource_type=resource_type,
            filters=self._detect_filters(normalized_query, resource_type),
            group_by=self._detect_group_by(normalized_query, resource_type),
        )

    def _try_llm_plan(self, query: str, fallback_plan: ResourceQueryPlan) -> ResourceQueryPlan:
        """Let an LLM refine the plan, then validate it against the catalog.

        The LLM can choose a resource, intent, basic filters, and group key. It
        cannot see or answer from data here; the final answer is still computed
        from access-checked rows after validation.
        """

        if self._llm_client is None or fallback_plan.intent not in {
            ResourceAnalysisIntent.GROUP,
            ResourceAnalysisIntent.SUMMARIZE,
            ResourceAnalysisIntent.ANALYZE,
        }:
            return fallback_plan
        allowed_fields = {
            resource_type: [field.name for field in self._catalog.get(resource_type).fields]
            for resource_type in self._catalog.resource_types()
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Return compact JSON for an Amprealize read-only query plan. "
                    "Allowed keys: resource_type, intent, filters, group_by, rationale. "
                    "Use only allowed resource types, intents, and fields. Do not answer the user."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "query": query,
                        "fallback_plan": fallback_plan.to_dict(),
                        "allowed_resource_types": self._catalog.resource_types(),
                        "allowed_intents": [intent.value for intent in ResourceAnalysisIntent],
                        "allowed_fields": allowed_fields,
                    },
                    sort_keys=True,
                ),
            },
        ]
        try:
            response = self._llm_client.call(messages, temperature=0, max_tokens=500)
            raw_content = getattr(response, "content", str(response)).strip()
            payload = json.loads(raw_content)
        except Exception:
            return fallback_plan
        if not isinstance(payload, Mapping):
            return fallback_plan
        resource_type = str(payload.get("resource_type") or fallback_plan.resource_type)
        if resource_type not in self._catalog.resource_types():
            resource_type = fallback_plan.resource_type
        intent_value = str(payload.get("intent") or fallback_plan.intent.value)
        try:
            intent = ResourceAnalysisIntent(intent_value)
        except ValueError:
            intent = fallback_plan.intent
        valid_fields = {field.name for field in self._catalog.get(resource_type).fields}
        filters = self._validated_llm_filters(payload.get("filters"), fallback_plan.filters)
        group_by = payload.get("group_by") or fallback_plan.group_by
        if group_by is not None and str(group_by) not in valid_fields:
            group_by = fallback_plan.group_by
        return ResourceQueryPlan(
            intent=intent,
            resource_type=resource_type,
            filters=filters,
            group_by=str(group_by) if group_by else None,
            llm_assisted=True,
            rationale=str(payload.get("rationale") or "LLM refined the query plan."),
        )

    @staticmethod
    def _validated_llm_filters(value: Any, fallback_filters: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            return dict(fallback_filters)
        allowed_filter_keys = {"status_contains", "status_in", "status_not_in"}
        filters: Dict[str, Any] = {}
        for key, raw_value in value.items():
            if key not in allowed_filter_keys:
                continue
            if key in {"status_in", "status_not_in"}:
                if isinstance(raw_value, list):
                    filters[key] = {_normalize(str(item)) for item in raw_value}
                continue
            if isinstance(raw_value, str):
                filters[key] = _normalize(raw_value)
        return filters or dict(fallback_filters)

    @staticmethod
    def _detect_intent(query: str) -> ResourceAnalysisIntent:
        if re.search(r"\b(how many|count|number of|total)\b", query):
            return ResourceAnalysisIntent.COUNT
        if re.search(r"\b(group|grouped by|by project|by status|breakdown|distribution)\b", query):
            return ResourceAnalysisIntent.GROUP
        if re.search(r"\b(summarize|summary|state of|health|overview)\b", query):
            return ResourceAnalysisIntent.SUMMARIZE
        # Recency / "latest" phrasing should stay on the deterministic list path, not generic analyze.
        if re.search(
            r"\b(most recent|most recently|latest|newest|last added|last created|"
            r"most recently updated|most recently created)\b",
            query,
        ):
            return ResourceAnalysisIntent.LIST
        if re.search(
            r"\b(last|latest)\s+(work item|work items|task|tasks|bug|bugs|run|runs)\b",
            query,
        ):
            return ResourceAnalysisIntent.LIST
        if re.search(r"\b(analyze|compare|trend|correlat|insight|most|least|top)\b", query):
            return ResourceAnalysisIntent.ANALYZE
        return ResourceAnalysisIntent.LIST

    @staticmethod
    def _is_backlog_in_progress_velocity_question(normalized: str) -> bool:
        has_backlogish = bool(re.search(r"\b(backlog|todo|queued|planned|open)\b", normalized))
        has_progressish = bool(
            re.search(r"\b(in progress|in-progress|started|doing|wip|active)\b", normalized)
        )
        has_timingish = bool(
            re.search(
                r"\b(quickly|velocity|moving|move|transition|time|duration|how long|lead|cycle|throughput|lag|days|hours)\b",
                normalized,
            )
        )
        return has_backlogish and has_progressish and has_timingish

    @staticmethod
    def _is_agent_project_membership_question(normalized: str) -> bool:
        if "agent" not in normalized:
            return False
        if re.match(
            r"^(what|which|list|show|tell|give|name|enumerate|how many|how\s+much)\b",
            normalized,
        ):
            return False
        # Capability / implementation questions should NOT be treated as membership questions.
        # Examples: "have we implemented agent execution", "does agent execution exist".
        if re.search(
            r"\b(implement|implemented|built|created|exist|exists|available|released|"
            r"shipped|execution|run|runs|running)\b",
            normalized,
        ):
            return False
        polar = bool(
            re.search(
                r"\b(is|are|does|do|was|were|has|have|can|could|should|will)\b",
                normalized,
            )
        )
        assign_or_scope = bool(
            re.search(
                r"\b(assign|assigned|assignment|belong|member|contributor|primary|secondary|"
                r"role|workspace|project|scope|attached|linked)\b",
                normalized,
            )
        )
        return polar and assign_or_scope

    @staticmethod
    def _cleanup_agent_phrase_fragment(fragment: str) -> Optional[str]:
        frag = (fragment or "").strip()
        if not frag:
            return None
        frag = re.sub(r"^\s*(the|named|called)\s+", "", frag, flags=re.IGNORECASE)
        frag = frag.strip()
        return frag or None

    @staticmethod
    def _extract_agent_name_phrase_for_membership(query: str) -> Optional[str]:
        low = query.strip().lower()
        m = re.search(r"\bthe\s+(.+?)\s+agent\b", low)
        if m:
            return ResourceAnalysisService._cleanup_agent_phrase_fragment(m.group(1))
        m2 = re.search(
            r"\b(?:is|are|does|do|was|were|has|have)\s+(?:the\s+)?(.+?)\s+agent\b",
            low,
        )
        if m2:
            return ResourceAnalysisService._cleanup_agent_phrase_fragment(m2.group(1))
        return None

    @staticmethod
    def _agent_rows_matching_membership_tokens(
        rows: Sequence[Mapping[str, Any]],
        tokens: Sequence[str],
    ) -> List[Dict[str, Any]]:
        if not tokens:
            return []
        out: List[Dict[str, Any]] = []
        for row in rows:
            rd = _to_dict(row)
            blob = _normalize(
                " ".join(
                    str(x)
                    for x in (
                        rd.get("name"),
                        rd.get("title"),
                        rd.get("slug"),
                        rd.get("agent_slug"),
                        rd.get("display_name"),
                    )
                    if x
                )
            )
            if all(tok in blob for tok in tokens):
                out.append(dict(rd))
        return out

    @staticmethod
    def _agent_project_membership_answer(
        *,
        query: str,
        plan: ResourceQueryPlan,
        rows: Sequence[Mapping[str, Any]],
        inventory: Mapping[str, Any],
        scope_meta: Mapping[str, Any],
    ) -> Optional[ResourceAnalysisAnswer]:
        phrase = ResourceAnalysisService._extract_agent_name_phrase_for_membership(query)
        if not phrase:
            return None
        raw_tokens = re.findall(r"[a-z0-9]+", _normalize(phrase))
        tokens = [t for t in raw_tokens if len(t) >= 2]
        if not raw_tokens:
            return None
        if not tokens:
            tokens = list(raw_tokens)
        matched = ResourceAnalysisService._agent_rows_matching_membership_tokens(rows, tokens)
        proj = scope_meta.get("effective_project_id")
        pname = ResourceAnalysisService._lookup_project_name(inventory, str(proj)) if proj else None
        loc = f"**{pname}**" if pname else "the agents in this workspace snapshot"

        if not matched:
            return ResourceAnalysisService._answer(
                content=(
                    f"I do not see an agent whose name matches **{phrase}** among the assignments "
                    f"I have for {loc}."
                ),
                answer_type="agents.membership",
                plan=plan,
                rows=[],
                summary="No matching agent assignment in scoped rows.",
            )

        def _rank(r: Mapping[str, Any]) -> tuple[int, str]:
            role = str(_first_present(r, "role", default="") or "").lower()
            if "primary" in role:
                return (0, role)
            if "contribut" in role or "member" in role:
                return (1, role)
            return (2, role)

        best = sorted(matched, key=_rank)[0]
        bd = _to_dict(best)
        name = str(_first_present(bd, "name", "title", "display_name", default="Agent"))
        slug = str(bd.get("slug") or bd.get("agent_slug") or "").strip()
        role_val = getattr(bd.get("role"), "value", bd.get("role"))
        role = str(role_val).strip() if role_val else "assigned"
        pid = str(_first_present(bd, "project_id", default="") or "")
        row_pname = ResourceAnalysisService._lookup_project_name(inventory, pid) or pid
        slug_part = f" (`{slug}`)" if slug else ""
        content = (
            f"Yes — **{name}**{slug_part} is assigned to **{row_pname}** as **{role}** "
            f"in the agent assignments I have loaded for this reply."
        )
        return ResourceAnalysisService._answer(
            content=content,
            answer_type="agents.membership",
            plan=plan,
            rows=[best],
            summary=f"Confirmed assignment for {name} on {row_pname}.",
        )

    @staticmethod
    def _detect_filters(query: str, resource_type: str) -> Dict[str, Any]:
        filters: Dict[str, Any] = {}
        normalized = _normalize(query)
        if ResourceAnalysisService._is_backlog_in_progress_velocity_question(normalized):
            return filters
        if "blocked" in query and resource_type == "work_items":
            filters["status_contains"] = "blocked"
        if re.search(r"\b(active|running|in progress|queued|pending)\b", query):
            filters["status_in"] = {"active", "running", "in progress", "queued", "pending"}
        if resource_type == "runs" and re.search(r"\b(failed|failure|errored)\b", query):
            filters["status_in"] = {"failed", "error", "errored"}
        if re.search(r"\b(open|todo|to do|not done)\b", query):
            filters["status_not_in"] = {"done", "completed", "closed", "cancelled"}
        # Positive "done/completed" filter — user asks which items ARE completed.
        if re.search(r"\b(completed|done|finished|closed)\b", query) and not filters.get("status_not_in"):
            # Only apply when the phrase is clearly requesting completed items, not negations.
            if not re.search(r"\b(not|no|none|aren\s*'?t|haven\s*'?t|haven't|not\s+done|not\s+completed)\b", query):
                filters["status_in"] = {"done", "completed", "closed"}
        if resource_type == "work_items":
            item_types = ResourceAnalysisService._work_item_types_from_query(normalized)
            if item_types:
                filters["item_type_in"] = set(item_types)
        return filters

    @staticmethod
    def _work_item_types_from_query(normalized: str) -> set[str]:
        """Return canonical item_type tokens mentioned explicitly in the query."""

        mapping = (
            ("feature", r"\bfeatures?\b"),
            ("bug", r"\bbugs?\b"),
            ("task", r"\btasks?\b"),
            ("goal", r"\bgoals?\b"),
            ("research", r"\bresearch(?:\s+items?)?\b"),
        )
        found: set[str] = set()
        for singular, pattern in mapping:
            if re.search(pattern, normalized):
                found.add(singular)
        return found

    @staticmethod
    def _normalize_item_type_value(value: Any) -> str:
        raw = getattr(value, "value", value)
        return _normalize(str(raw or ""))

    @staticmethod
    def _count_label_phrase(*, catalog_label: str, filters: Mapping[str, Any], count: int) -> str:
        """Human-readable noun phrase for counts (e.g. features vs generic work items)."""

        raw = filters.get("item_type_in")
        if not isinstance(raw, set) or len(raw) != 1:
            lowered = catalog_label.lower()
            if count == 1:
                if lowered.endswith("items"):
                    return lowered[:-1]
                if lowered.endswith("s") and not lowered.endswith("ss"):
                    return lowered[:-1]
                return lowered
            return lowered

        singular = next(iter(raw))
        plural_map = {
            "feature": "features",
            "bug": "bugs",
            "task": "tasks",
            "goal": "goals",
            "research": "research items",
        }
        if count == 1:
            return singular
        return plural_map.get(singular, f"{singular}s")

    @staticmethod
    def _detect_group_by(query: str, resource_type: str) -> Optional[str]:
        if "by project" in query:
            return "project_id"
        if "by status" in query:
            return "status"
        if "by agent" in query:
            return "agent_id" if resource_type == "runs" else "assignee"
        if "by board" in query:
            return "board_id"
        if "by type" in query:
            return "item_type"
        return "project_id" if resource_type in {"work_items", "boards", "runs"} else None

    def _rows_for_resource(
        self,
        resource_type: str,
        inventory: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        if resource_type == "projects":
            return [_row("project", item) for item in _list(inventory.get("projects"))]
        if resource_type == "boards":
            return self._flatten_by_project(inventory.get("boards_by_project"), "board")
        if resource_type == "work_items":
            return self._flatten_by_project(inventory.get("work_items_by_project"), "work_item")
        if resource_type == "agents":
            return [_row("agent", item) for item in _list(inventory.get("agent_assignments"))]
        if resource_type == "runs":
            return [_row("run", item) for item in _list(inventory.get("runs"))]
        if resource_type == "behaviors":
            return [_row("behavior", item) for item in _list(inventory.get("behaviors"))]
        if resource_type == "wiki_pages":
            return [_row("wiki_page", item) for item in _list(inventory.get("wiki_hits") or inventory.get("wiki_pages"))]
        if resource_type == "settings":
            settings = inventory.get("settings")
            if isinstance(settings, Mapping):
                return [
                    {"resource_type": "setting", "id": key, "name": key, "value": value}
                    for key, value in settings.items()
                ]
        if resource_type == "users":
            return [_row("user", item) for item in _list(inventory.get("users"))]
        if resource_type == "orgs":
            return [_row("org", item) for item in _list(inventory.get("orgs") or inventory.get("organizations"))]
        if resource_type == "files":
            return [_row("file", item) for item in _list(inventory.get("files"))]
        if resource_type == "credentials":
            return [_row("credential", item) for item in _list(inventory.get("credentials"))]
        if resource_type == "conversations":
            return [_row("conversation", item) for item in _list(inventory.get("conversations"))]
        if resource_type == "conversation_messages":
            return [_row("conversation_message", item) for item in _list(inventory.get("conversation_messages"))]
        return []

    @staticmethod
    def _flatten_by_project(value: Any, row_type: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not isinstance(value, Mapping):
            return rows
        for project_id, items in value.items():
            for item in _list(items):
                row = _row(row_type, item)
                row.setdefault("project_id", str(project_id))
                rows.append(row)
        return rows

    def _apply_named_scope(
        self,
        query: str,
        resource_type: str,
        rows: List[Dict[str, Any]],
        inventory: Mapping[str, Any],
        scope_hints: Optional[Mapping[str, Any]] = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Narrow rows by project/board from query text and optional scope hints.

        Returns ``(rows, meta)`` where ``meta`` may include ``ambiguous_board`` when the
        user references a board but several boards match the resolved project.
        """

        hints = dict(scope_hints or {})
        hint_pid = hints.get("project_id")
        hint_bid = hints.get("board_id")
        meta: Dict[str, Any] = {
            "ambiguous_board": False,
            "effective_project_id": None,
            "effective_board_id": None,
        }

        project = self._find_named_resource(query, _list(inventory.get("projects")))
        named_pid = _first_present(project or {}, "project_id", "id")
        named_pid_str = str(named_pid) if named_pid else None
        project_id = named_pid_str or (str(hint_pid) if hint_pid else None)

        if project_id:
            meta["effective_project_id"] = project_id
        if project_id and resource_type in {"boards", "work_items", "runs", "agents"}:
            rows = [row for row in rows if str(row.get("project_id") or "") == str(project_id)]

        board_rows = self._flatten_by_project(inventory.get("boards_by_project"), "board")
        board = self._find_named_resource(query, board_rows)
        named_bid = _first_present(board or {}, "board_id", "id")
        board_id = str(named_bid) if named_bid else None
        if not board_id and hint_bid:
            board_id = str(hint_bid)

        boards_for_project: List[Any] = []
        if project_id:
            boards_for_project = _list((inventory.get("boards_by_project") or {}).get(str(project_id)))

        if (
            resource_type == "work_items"
            and project_id
            and not board_id
            and re.search(r"\b(board|boards)\b", query, re.I)
            and len(boards_for_project) == 1
        ):
            sole = _to_dict(boards_for_project[0])
            board_id = str(_first_present(sole, "board_id", "id") or "") or None

        if (
            resource_type == "work_items"
            and project_id
            and not board_id
            and re.search(r"\b(board|boards)\b", query, re.I)
            and len(boards_for_project) > 1
        ):
            meta["ambiguous_board"] = True

        if board_id and resource_type == "work_items":
            rows = [row for row in rows if str(row.get("board_id") or "") == str(board_id)]
            meta["effective_board_id"] = board_id

        return rows, meta

    def _try_multi_board_clarification_answer(
        self,
        *,
        query: str,
        plan: ResourceQueryPlan,
        inventory: Mapping[str, Any],
        project_id: Optional[str],
    ) -> Optional[ResourceAnalysisAnswer]:
        if not project_id:
            return None
        boards_raw = _list((inventory.get("boards_by_project") or {}).get(str(project_id)))
        if len(boards_raw) <= 1:
            return None
        names: List[str] = []
        for b in boards_raw:
            bd = _to_dict(b)
            title = str(_first_present(bd, "name", "title", default="Untitled board"))
            names.append(title)
        lines = [
            "This project has several boards that could match your question. "
            "Which board should I use?",
        ]
        lines.extend(f"- {name}" for name in names)
        content = "\n".join(lines)
        answer = self._answer(
            content=content,
            answer_type=f"{plan.resource_type}.clarify_board",
            plan=plan,
            rows=[],
            summary="Multiple boards matched the project; user clarification requested.",
            extra={"empty_reason": "ambiguous_board", "board_names": names},
            requires_clarification=True,
        )
        answer.metadata["empty_reason"] = "ambiguous_board"
        return answer

    @staticmethod
    def _backlog_to_in_progress_duration_hours(row: Mapping[str, Any]) -> Optional[float]:
        created = ResourceAnalysisService._parse_row_timestamp(row.get("created_at"))
        progressed = ResourceAnalysisService._parse_row_timestamp(
            row.get("in_progress_at")
            or row.get("started_at")
            or row.get("first_in_progress_at")
            or row.get("transitioned_to_in_progress_at")
            or row.get("status_entered_in_progress_at")
        )
        if created <= 0 or progressed <= 0 or progressed < created:
            return None
        return (progressed - created) / 3600.0

    def _backlog_to_in_progress_velocity_answer(
        self,
        *,
        query: str,
        plan: ResourceQueryPlan,
        rows: Sequence[Mapping[str, Any]],
    ) -> ResourceAnalysisAnswer:
        durations = [
            hours
            for row in rows
            if (hours := self._backlog_to_in_progress_duration_hours(row)) is not None
        ]
        label = self._catalog.get(plan.resource_type).label
        if not durations:
            content = (
                f"From the {label.lower()} included with this reply, I do not see reliable "
                "timestamps for when each item left backlog for in progress "
                "(for example `created_at` plus `in_progress_at` or `started_at`). "
                "Open the board in the app for full history, or try again when that data is in context."
            )
            answer = self._answer(
                content=content,
                answer_type="work_items.velocity.insufficient_data",
                plan=plan,
                rows=[],
                summary="Insufficient timestamp fields for backlog-to-in-progress timing.",
                extra={"empty_reason": "insufficient_transition_timestamps", "analysis_mode": "metric"},
            )
            answer.metadata["empty_reason"] = "insufficient_transition_timestamps"
            return answer

        median_h = float(statistics.median(durations))
        sorted_d = sorted(durations)
        p95_idx = min(len(sorted_d) - 1, max(0, int(math.ceil(0.95 * len(sorted_d))) - 1))
        p95_h = float(sorted_d[p95_idx])

        def _fmt_hours(hours: float) -> str:
            if hours >= 72:
                return f"{hours / 24:.1f} days"
            return f"{hours:.1f} hours"

        content = (
            f"Using timestamp fields on {len(durations)} {label.lower()} in this context, "
            "time from creation (proxy for backlog) to in progress has "
            f"median {_fmt_hours(median_h)} and 95th percentile {_fmt_hours(p95_h)}."
        )
        answer = self._answer(
            content=content,
            answer_type="work_items.velocity.backlog_to_in_progress",
            plan=plan,
            rows=list(rows),
            summary=f"Median {_fmt_hours(median_h)}; p95 {_fmt_hours(p95_h)} over {len(durations)} items.",
            extra={
                "analysis_mode": "metric",
                "sample_count": len(durations),
                "median_hours": median_h,
                "p95_hours": p95_h,
            },
        )
        return answer

    @staticmethod
    def _find_named_resource(query: str, rows: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
        """Match a row by stable id substring first, then by name/slug word boundaries.

        Word-boundary matching on normalized text breaks hyphenated ids (``proj-abc`` → ``proj``),
        which previously picked the wrong project when the user pasted a full ``proj-…`` id.
        """

        if not rows:
            return None
        q_compact = _alnum_compact(query)
        best: Optional[Mapping[str, Any]] = None
        best_score = 0
        for row in rows:
            data = _to_dict(row)
            for key in ("project_id", "board_id", "id", "item_id", "run_id", "agent_id"):
                raw = data.get(key)
                if raw is None:
                    continue
                ident = str(raw).strip()
                if len(ident) < 10:
                    continue
                compact = _alnum_compact(ident)
                if len(compact) < 12:
                    continue
                if compact in q_compact:
                    score = 400 + len(compact)
                    if score > best_score:
                        best = row
                        best_score = score
        if best_score >= 400:
            return best

        normalized_query = _normalize(query)
        trivial_tokens = frozenset({"proj", "brd", "org", "id", "run", "item"})
        for row in rows:
            data = _to_dict(row)
            candidates = [
                _first_present(data, "name", "title", "slug", "id", "project_id", "board_id", default=""),
            ]
            for candidate in candidates:
                candidate_text = _normalize(str(candidate))
                if not candidate_text or len(candidate_text) <= 2:
                    continue
                if candidate_text in trivial_tokens:
                    continue
                try:
                    if re.search(rf"\b{re.escape(candidate_text)}\b", normalized_query):
                        score = len(candidate_text)
                        if score > best_score:
                            best = row
                            best_score = score
                except re.error:
                    continue
        return best

    @staticmethod
    def _apply_filters(rows: List[Dict[str, Any]], filters: Mapping[str, Any]) -> List[Dict[str, Any]]:
        selected = rows
        status_contains = filters.get("status_contains")
        if status_contains:
            selected = [
                row for row in selected
                if status_contains in _normalize(str(row.get("status", "")))
                or status_contains in _normalize(str(row.get("blocked_reason", "")))
            ]
        status_in = filters.get("status_in")
        if status_in:
            norm_in = {_normalize(str(s)) for s in status_in}
            selected = [
                row for row in selected
                if _normalize(str(row.get("status", ""))) in norm_in
            ]
        status_not_in = filters.get("status_not_in")
        if status_not_in:
            norm_not = {_normalize(str(s)) for s in status_not_in}
            selected = [
                row for row in selected
                if _normalize(str(row.get("status", ""))) not in norm_not
            ]
        item_type_in = filters.get("item_type_in")
        if item_type_in:
            allowed = {_normalize(str(x)) for x in item_type_in}
            selected = [
                row for row in selected
                if ResourceAnalysisService._normalize_item_type_value(row.get("item_type")) in allowed
            ]
        # Topic/keyword text search across title and description.
        text_search = filters.get("text_search")
        if text_search:
            term = _normalize(str(text_search))
            selected = [
                row for row in selected
                if term in _normalize(str(row.get("title", "")))
                or term in _normalize(str(row.get("description") or ""))
            ]
        return selected

    def _maybe_take_latest_recency_rows(
        self,
        normalized_query: str,
        resource_type: str,
        intent: ResourceAnalysisIntent,
        rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if intent != ResourceAnalysisIntent.LIST or not rows:
            return rows
        if resource_type not in {"work_items", "runs"}:
            return rows
        if self._wants_single_random(normalized_query):
            return [secrets.choice(rows)]
        if not self._wants_single_latest_recency(normalized_query):
            return rows
        sorted_rows = self._sort_rows_by_recency(rows)
        return sorted_rows[:1]

    @staticmethod
    def _wants_single_random(query: str) -> bool:
        return bool(
            re.search(
                r"\b("
                r"random|arbitrary|shuffle|surprise\s+me|"
                r"pick\s+(a|an|one)|"
                r"give\s+me\s+(a|an|one)|"
                r"any\s+(work\s+)?item|"
                r"one\s+(random\s+)?(work\s+)?item"
                r")\b",
                query,
                re.I,
            )
        )

    @staticmethod
    def _wants_single_latest_recency(query: str) -> bool:
        if re.search(
            r"\b(most recent|most recently|latest|newest|last added|last created|"
            r"most recently updated|most recently created)\b",
            query,
        ):
            return True
        if re.search(
            r"\b(last|latest)\s+(work item|work items|task|tasks|bug|bugs|run|runs)\b",
            query,
        ):
            return True
        return False

    @staticmethod
    def _parse_row_timestamp(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def _row_recency_ts(self, row: Dict[str, Any]) -> float:
        for key in ("updated_at", "created_at", "edited_at", "completed_at", "started_at"):
            ts = self._parse_row_timestamp(row.get(key))
            if ts > 0:
                return ts
        return 0.0

    def _sort_rows_by_recency(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(rows, key=self._row_recency_ts, reverse=True)

    @staticmethod
    def _inventory_has_rows_for_resource(inventory: Mapping[str, Any], resource_type: str) -> bool:
        if resource_type == "work_items":
            wip = inventory.get("work_items_by_project") or {}
            return sum(len(v or []) for v in wip.values()) > 0
        if resource_type == "runs":
            return len(_list(inventory.get("runs"))) > 0
        if resource_type == "projects":
            return len(_list(inventory.get("projects"))) > 0
        if resource_type == "boards":
            bbp = inventory.get("boards_by_project") or {}
            return sum(len(v or []) for v in bbp.values()) > 0
        if resource_type == "agents":
            return len(_list(inventory.get("agent_assignments"))) > 0
        return True

    @staticmethod
    def _lookup_project_name(inventory: Mapping[str, Any], project_id: Optional[str]) -> Optional[str]:
        if not project_id:
            return None
        for project in _list(inventory.get("projects")):
            data = _to_dict(project)
            pid = str(_first_present(data, "project_id", "id") or "")
            if pid == str(project_id):
                name = _first_present(data, "name", "title")
                return str(name).strip() if name else None
        return None

    @staticmethod
    def _lookup_board_name(
        inventory: Mapping[str, Any],
        project_id: Optional[str],
        board_id: Optional[str],
    ) -> Optional[str]:
        if not project_id or not board_id:
            return None
        for board in _list((inventory.get("boards_by_project") or {}).get(str(project_id))):
            data = _to_dict(board)
            bid = str(_first_present(data, "board_id", "id") or "")
            if bid == str(board_id):
                name = _first_present(data, "name", "title")
                return str(name).strip() if name else None
        return None

    @staticmethod
    def _count_scope_tail(
        *,
        plan: ResourceQueryPlan,
        scope_meta: Mapping[str, Any],
        inventory: Mapping[str, Any],
    ) -> str:
        """Short trailing phrase for count answers (includes leading space + terminal period)."""

        pid = scope_meta.get("effective_project_id")
        bid = scope_meta.get("effective_board_id")
        project_name = ResourceAnalysisService._lookup_project_name(inventory, str(pid) if pid else None)
        board_name = ResourceAnalysisService._lookup_board_name(
            inventory, str(pid) if pid else None, str(bid) if bid else None
        )

        if plan.resource_type != "work_items":
            if project_name:
                return f" in the {project_name} project."
            if pid:
                return " in this project."
            # Global scope (e.g. org/home chat): avoid meta phrasing like "data included with this reply".
            return "."

        if bid and board_name:
            return f" on the {board_name} board."
        if bid:
            return " on this board."
        if project_name:
            return f" in the {project_name} project."
        if pid:
            return " in this project."
        return " in the work items shown in this workspace view."

    @staticmethod
    def _item_type_plural_label(normalized_type: str, count: int) -> str:
        key = (normalized_type or "").strip() or "(unspecified)"
        if key == "(unspecified)":
            return f"{count} unspecified" if count == 1 else f"{count} unspecified items"
        singular = key
        plural_map = {
            "feature": "features",
            "bug": "bugs",
            "task": "tasks",
            "goal": "goals",
            "research": "research items",
        }
        plural = plural_map.get(singular, f"{singular}s")
        if count == 1:
            return f"1 {singular}"
        return f"{count} {plural}"

    @staticmethod
    def _item_type_label_title(normalized_type: str) -> str:
        key = (normalized_type or "").strip() or "(unspecified)"
        if key == "(unspecified)":
            return "Unspecified"
        return key.replace("_", " ").title()

    def _work_item_type_breakdown_for_count(
        self,
        plan: ResourceQueryPlan,
        rows_pre_filter: List[Dict[str, Any]],
        counted_rows: List[Dict[str, Any]],
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Histogram of item types in the same scope with non-type filters applied."""

        if plan.resource_type != "work_items" or not rows_pre_filter:
            return None, None
        filters_wo = {k: v for k, v in plan.filters.items() if k != "item_type_in"}
        base = self._apply_filters(list(rows_pre_filter), filters_wo)
        if not base:
            return None, None
        tallies: Counter[str] = Counter()
        for row in base:
            raw = self._normalize_item_type_value(row.get("item_type"))
            key = raw if raw else "(unspecified)"
            tallies[key] += 1
        positive = [(t, c) for t, c in tallies.most_common() if c > 0]
        if not positive:
            return None, None

        by_item_type: List[Dict[str, Any]] = []
        for t, c in positive:
            by_item_type.append(
                {
                    "item_type": t,
                    "count": c,
                    "item_type_label": self._item_type_label_title(t),
                }
            )
        insights: Dict[str, Any] = {
            "by_item_type": by_item_type,
            "scoped_total": len(base),
        }

        type_filter = plan.filters.get("item_type_in")
        filtered_single_type = isinstance(type_filter, set) and len(type_filter) == 1

        def _supplementary_line() -> Optional[str]:
            if len(positive) >= 2:
                parts = [self._item_type_plural_label(t, c) for t, c in positive[:5]]
                rest = len(positive) - 5
                tail = f", and {rest} other types" if rest > 0 else ""
                return f"Across the same scope there are {', '.join(parts)}{tail}."
            if len(counted_rows) == 0 and filtered_single_type and positive:
                only_t, only_c = positive[0]
                return (
                    f"In the same scope there {('is' if only_c == 1 else 'are')} "
                    f"{self._item_type_plural_label(only_t, only_c)}; none match the type you asked about."
                )
            if len(positive) == 1 and not filtered_single_type:
                t, c = positive[0]
                if t == "(unspecified)":
                    return None
                return f"Everything in this scope is typed as {self._item_type_plural_label(t, c)}."
            return None

        return insights, _supplementary_line()

    @staticmethod
    def _format_project_count_lines(rows: List[Dict[str, Any]], *, limit: int = 25) -> List[str]:
        """Human-readable project lines for count replies (name, optional slug, id)."""

        lines: List[str] = []
        for row in rows[:limit]:
            name = str(
                _first_present(row, "name", "title", "display_name", default="Untitled project")
                or "Untitled project"
            ).strip()
            pid = str(_first_present(row, "project_id", "id", default="") or "").strip()
            slug = row.get("slug")
            slug_part = f" ({slug})" if slug else ""
            if pid:
                lines.append(f"- {name}{slug_part} — `{pid}`")
            else:
                lines.append(f"- {name}{slug_part}")
        return lines

    def _count_answer(
        self,
        plan: ResourceQueryPlan,
        rows: List[Dict[str, Any]],
        *,
        inventory: Optional[Mapping[str, Any]] = None,
        scope_meta: Optional[Mapping[str, Any]] = None,
        rows_pre_filter: Optional[List[Dict[str, Any]]] = None,
    ) -> ResourceAnalysisAnswer:
        label = self._catalog.get(plan.resource_type).label
        phrase = self._count_label_phrase(
            catalog_label=label, filters=plan.filters, count=len(rows)
        )
        meta = dict(scope_meta or {})
        inv = inventory or {}
        scope_tail = self._count_scope_tail(plan=plan, scope_meta=meta, inventory=inv)
        n = len(rows)
        if n == 0:
            lead = f"You don't have any {phrase}{scope_tail}"
        else:
            lead = f"You have {n} {phrase}{scope_tail}"

        extra: Dict[str, Any] = {}
        insights_block: Optional[Dict[str, Any]] = None
        supp: Optional[str] = None
        if plan.resource_type == "work_items" and rows_pre_filter is not None:
            insights_block, supp = self._work_item_type_breakdown_for_count(
                plan, rows_pre_filter, rows
            )
            if insights_block:
                extra["insights"] = insights_block
        head_parts = [lead.rstrip()]
        if supp:
            head_parts.append(supp)
        head = " ".join(head_parts)
        project_lines = (
            self._format_project_count_lines(rows)
            if plan.resource_type == "projects" and n > 0 and rows
            else []
        )
        if project_lines:
            content = head + "\n\n" + "\n".join(project_lines)
        else:
            content = head
        summary = f"{n} {phrase} in scope." if n else f"No matching {phrase} in scope."
        return self._answer(
            content=content,
            answer_type=f"{plan.resource_type}.count",
            plan=plan,
            rows=rows,
            summary=summary,
            extra=extra or None,
        )

    def _list_answer(
        self,
        plan: ResourceQueryPlan,
        rows: List[Dict[str, Any]],
        *,
        inventory: Optional[Mapping[str, Any]] = None,
        rows_pre_filter: Optional[List[Dict[str, Any]]] = None,
    ) -> ResourceAnalysisAnswer:
        label = self._catalog.get(plan.resource_type).label
        if not rows:
            inv = inventory or {}
            pre = rows_pre_filter if rows_pre_filter is not None else []
            empty_reason: Optional[str] = None
            content: str
            summary: str
            if not self._inventory_has_rows_for_resource(inv, plan.resource_type):
                empty_reason = "empty_inventory"
                content = (
                    f"No {label.lower()} are included with this reply yet. "
                    "If you expected data here, open the project board or use a shorter thread "
                    "so the assistant can load the right snapshot."
                )
                summary = "No workspace data attached for this resource type."
            elif not pre:
                empty_reason = "scope_no_rows"
                content = (
                    f"I do not see any {label.lower()} in the current project or board scope "
                    "that match how I read your question."
                )
                summary = "Nothing in scope matched before applying status wording."
            elif pre and not rows:
                empty_reason = "filters_excluded_all"
                content = (
                    f"I found {label.lower()} in scope, but none stayed after applying the status "
                    "or wording I inferred from your question. Try naming the board or status again, "
                    "or loosen how you describe the set you want."
                )
                summary = "Status interpretation removed all scoped matches."
            else:
                content = f"I don't see any {label.lower()} in this scope."
                summary = "No matching rows found."
            answer = self._answer(
                content=content,
                answer_type=f"{plan.resource_type}.list",
                plan=plan,
                rows=[],
                summary=summary,
            )
            if empty_reason:
                answer.structured_payload["empty_reason"] = empty_reason
                answer.metadata["empty_reason"] = empty_reason
            return answer
        _INLINE_LIMIT = 10
        _SYNTHESIS_THRESHOLD = 15
        if len(rows) == 1:
            lines = [f"Here's one {label.lower().rstrip('s')} from this scope:"]
            lines.append(f"- {self._row_label(rows[0])}")
        elif len(rows) <= _INLINE_LIMIT:
            lines = [f"I found {len(rows)} {label.lower()} in this scope:"]
            lines.extend(f"- {self._row_label(row)}" for row in rows)
        else:
            # Large result set: emit a concise summary with status breakdown + top examples
            # rather than dumping all rows, which is unhelpful in chat.
            status_counts: Dict[str, int] = {}
            for row in rows:
                st = _normalize(str(row.get("status") or "unknown"))
                status_counts[st] = status_counts.get(st, 0) + 1
            status_summary = ", ".join(
                f"{cnt} {st}" for st, cnt in sorted(status_counts.items(), key=lambda x: -x[1])
            )
            lines = [
                f"I found {len(rows)} {label.lower()} in this scope.",
                f"Status breakdown: {status_summary}.",
                f"Top {min(_INLINE_LIMIT, len(rows))} items:",
            ]
            lines.extend(f"- {self._row_label(row)}" for row in rows[:_INLINE_LIMIT])
            remaining = len(rows) - _INLINE_LIMIT
            if remaining > 0:
                lines.append(
                    f"...and {remaining} more. Use a filter (e.g. status, type, or keyword) to narrow the list."
                )
        return self._answer(
            content="\n".join(lines),
            answer_type=f"{plan.resource_type}.list",
            plan=plan,
            rows=rows,
            summary=f"{len(rows)} {label.lower()} found.",
        )

    def _group_answer(
        self,
        plan: ResourceQueryPlan,
        rows: List[Dict[str, Any]],
    ) -> ResourceAnalysisAnswer:
        group_by = plan.group_by or "status"
        counts: Dict[str, int] = {}
        for row in rows:
            key = str(row.get(group_by) or "unknown")
            counts[key] = counts.get(key, 0) + 1
        sorted_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if not sorted_counts:
            content = "I do not see any matches in this scope to group."
        else:
            lines = [f"Grouped by {group_by}:"]
            lines.extend(f"- {key}: {count}" for key, count in sorted_counts)
            content = "\n".join(lines)
        payload_rows = [{"group": key, "count": count} for key, count in sorted_counts]
        return self._answer(
            content=content,
            answer_type=f"{plan.resource_type}.group",
            plan=plan,
            rows=rows,
            summary=f"{len(payload_rows)} group{'s' if len(payload_rows) != 1 else ''} found.",
            extra={"groups": payload_rows},
        )

    def _summary_answer(
        self,
        plan: ResourceQueryPlan,
        rows: List[Dict[str, Any]],
    ) -> ResourceAnalysisAnswer:
        label = self._catalog.get(plan.resource_type).label
        status_counts: Dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        parts = [f"I found {len(rows)} {label.lower()} matching that scope."]
        if status_counts:
            breakdown = ", ".join(
                f"{status}: {count}"
                for status, count in sorted(status_counts.items(), key=lambda item: item[0])
            )
            parts.append(f"Status breakdown: {breakdown}.")
        if rows:
            parts.append("Most relevant examples: " + "; ".join(self._row_label(row) for row in rows[:3]) + ".")
        return self._answer(
            content=" ".join(parts),
            answer_type=f"{plan.resource_type}.summary",
            plan=plan,
            rows=rows,
            summary=f"Summary across {len(rows)} matching {label.lower()}.",
        )

    def _try_llm_summary(
        self,
        query: str,
        plan: ResourceQueryPlan,
        rows: List[Dict[str, Any]],
    ) -> Optional[ResourceAnalysisAnswer]:
        if self._llm_client is None or not rows:
            return None
        messages = [
            {
                "role": "system",
                "content": (
                    "Summarize access-checked Amprealize resource records. "
                    "Do not invent data. Keep the answer concise and cite counts."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"query": query, "plan": plan.to_dict(), "rows": rows[:50]},
                    sort_keys=True,
                    default=str,
                ),
            },
        ]
        response = self._llm_client.call(messages, temperature=0, max_tokens=700)
        content = getattr(response, "content", str(response)).strip()
        if not content:
            return None
        return self._answer(
            content=content,
            answer_type=f"{plan.resource_type}.llm_summary",
            plan=plan,
            rows=rows,
            summary=f"LLM-assisted summary across {len(rows)} matching records.",
        )

    @staticmethod
    def _row_label(row: Mapping[str, Any]) -> str:
        raw_title = _first_present(
            row,
            "title",
            "name",
            "agent_name",
            "display_name",
            "label",
            "summary",
            "id",
            default="Untitled",
        )
        slug = row.get("slug") or row.get("agent_slug")
        if slug:
            title = f"{raw_title} ({slug})"
        else:
            title = raw_title
        row_id = _first_present(row, "id", "item_id", "run_id", "project_id", "board_id", "agent_id")
        status = row.get("status")
        suffixes = []
        if row_id and str(row_id) != str(title):
            suffixes.append(f"[{row_id}]")
        if status:
            suffixes.append(f"- {status}")
        if row.get("resource_type") == "agent":
            role_val = getattr(row.get("role"), "value", row.get("role"))
            if role_val:
                suffixes.append(f"- {role_val}")
        if row.get("project_id"):
            suffixes.append(f"in project {row['project_id']}")
        return " ".join([str(title), *suffixes])

    @staticmethod
    def _answer(
        *,
        content: str,
        answer_type: str,
        plan: ResourceQueryPlan,
        rows: List[Dict[str, Any]],
        summary: str,
        extra: Optional[Dict[str, Any]] = None,
        requires_clarification: bool = False,
    ) -> ResourceAnalysisAnswer:
        extra = dict(extra or {})
        mode = extra.pop("analysis_mode", None)
        analysis_mode = (
            str(mode)
            if mode
            else (
                "llm_assisted"
                if plan.llm_assisted or answer_type.endswith("llm_summary")
                else "deterministic"
            )
        )
        payload = {
            "card_kind": "resource_analysis",
            "title": "Resource analysis",
            "summary": summary,
            "query_plan": plan.to_dict(),
            "analysis_mode": analysis_mode,
            "rows": rows,
            **extra,
        }
        metadata = {
            "analysis_mode": payload["analysis_mode"],
            "row_count": len(rows),
            "resource_type": plan.resource_type,
            "intent": plan.intent.value,
            "llm_assisted": payload["analysis_mode"] == "llm_assisted",
        }
        return ResourceAnalysisAnswer(
            content=content,
            answer_type=answer_type,
            query_plan=plan,
            structured_payload=payload,
            source_rows=rows,
            metadata=metadata,
            trace_steps=[
                {
                    "phase": "resource_analysis",
                    "label": "Answered from accessible resource data",
                    "intent": plan.intent.value,
                    "resource_type": plan.resource_type,
                    "row_count": len(rows),
                    "analysis_mode": payload["analysis_mode"],
                }
            ],
            requires_clarification=requires_clarification,
        )


def _sanitize_for_json(value: Any) -> Any:
    """Recursively coerce values so resource rows survive json.dumps (e.g. chat persistence, SSE)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return getattr(value, "value", str(value))
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return value


def _row(resource_type: str, item: Any) -> Dict[str, Any]:
    data = _to_dict(item)
    row = {"resource_type": resource_type, **data}
    row.setdefault(
        "id",
        _first_present(
            row,
            "id",
            "item_id",
            "board_id",
            "run_id",
            "agent_id",
            "credential_id",
            "behavior_id",
            "project_id",
        ),
    )
    row.setdefault(
        "name",
        _first_present(
            row,
            "name",
            "agent_name",
            "display_name",
            "title",
            "slug",
            "workflow_name",
            "template_name",
        ),
    )
    row.setdefault("status", getattr(row.get("status"), "value", row.get("status")))
    return _sanitize_for_json(row)


def _to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    data: Dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        try:
            attr = getattr(value, key)
        except Exception:
            continue
        if callable(attr):
            continue
        data[key] = attr
    return data


def _list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


async def _call_with_supported_context(method: Callable[..., Any], context: Mapping[str, Any]) -> Any:
    """Call service methods with common access context shapes."""

    call_attempts = [
        {"user_id": context.get("user_id"), "org_id": context.get("org_id"), "project_id": context.get("project_id")},
        {"user_id": context.get("user_id"), "org_id": context.get("org_id")},
        {"user_id": context.get("user_id"), "project_id": context.get("project_id")},
        {"org_id": context.get("org_id"), "project_id": context.get("project_id")},
        {"project_id": context.get("project_id")},
        {"org_id": context.get("org_id")},
        {"user_id": context.get("user_id")},
        {},
    ]
    last_type_error: Optional[TypeError] = None
    for kwargs in call_attempts:
        filtered_kwargs = {key: value for key, value in kwargs.items() if value is not None}
        try:
            result = method(**filtered_kwargs)
        except TypeError as exc:
            last_type_error = exc
            continue
        if hasattr(result, "__await__"):
            result = await result
        return result
    if last_type_error is not None:
        return None
    return None


def _first_present(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _alnum_compact(value: str) -> str:
    """Lowercase letters+digits only — matches across hyphen/spacing boundaries."""

    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _fields(*names: str) -> tuple[ResourceFieldSpec, ...]:
    return tuple(ResourceFieldSpec(name=name, label=name.replace("_", " ").title()) for name in names)


_DEFAULT_SPECS: tuple[ResourceSpec, ...] = (
    ResourceSpec("users", "Users", ("user", "users", "people", "members"), ("id", "user_id"), ("name", "email"), _fields("id", "name", "email", "role")),
    ResourceSpec("orgs", "Organizations", ("org", "orgs", "organization", "organizations"), ("id", "org_id"), ("name", "slug"), _fields("id", "name", "slug")),
    ResourceSpec("projects", "Projects", ("project", "projects"), ("id", "project_id"), ("name", "slug"), _fields("id", "project_id", "name", "slug", "status")),
    ResourceSpec("boards", "Boards", ("board", "boards"), ("id", "board_id"), ("name",), _fields("id", "board_id", "name", "project_id", "is_default")),
    ResourceSpec("work_items", "Work Items", ("work item", "work items", "board item", "board items", "task", "tasks", "bug", "bugs", "feature", "features", "goal", "goals", "ticket", "tickets"), ("id", "item_id"), ("title", "name"), _fields("id", "item_id", "title", "status", "item_type", "project_id", "board_id", "assignee")),
    ResourceSpec("agents", "Agents", ("agent", "agents", "agent assignment", "agent assignments"), ("id", "agent_id"), ("name", "slug"), _fields("id", "agent_id", "name", "slug", "project_id", "role")),
    ResourceSpec("runs", "Runs", ("run", "runs", "execution", "executions"), ("id", "run_id"), ("summary", "workflow_name"), _fields("id", "run_id", "status", "project_id", "workflow_name", "model_id")),
    ResourceSpec("behaviors", "Behaviors", ("behavior", "behaviors", "handbook"), ("id", "behavior_id", "name"), ("name",), _fields("id", "behavior_id", "name", "status", "role_focus")),
    ResourceSpec("wiki_pages", "Wiki Pages", ("wiki", "wiki page", "wiki pages", "doc", "docs", "guide", "guides"), ("id", "path", "slug"), ("title", "path"), _fields("id", "title", "path", "domain")),
    ResourceSpec("settings", "Settings", ("setting", "settings", "configuration", "config"), ("id", "name"), ("name",), _fields("id", "name", "value")),
    ResourceSpec("files", "Files", ("file", "files", "document", "documents", "asset", "assets"), ("id", "path"), ("name", "path"), _fields("id", "name", "path", "project_id", "mime_type", "created_at")),
    ResourceSpec("credentials", "Credentials", ("credential", "credentials", "secret", "secrets", "token", "tokens"), ("id", "credential_id", "name"), ("name",), _fields("id", "credential_id", "name", "scope", "project_id", "org_id", "status")),
    ResourceSpec("conversations", "Conversations", ("conversation", "conversations", "chat", "chats", "thread", "threads"), ("id", "conversation_id"), ("title", "summary"), _fields("id", "conversation_id", "title", "scope", "project_id", "created_at")),
    ResourceSpec("conversation_messages", "Conversation Messages", ("message", "messages", "chat message", "chat messages"), ("id", "message_id"), ("content", "summary"), _fields("id", "message_id", "conversation_id", "actor_type", "created_at")),
)


__all__ = [
    "ResourceAnalysisAnswer",
    "ResourceAnalysisIntent",
    "ResourceAnalysisService",
    "ResourceCatalog",
    "ResourceFieldSpec",
    "ServiceBackedResourceInventoryProvider",
    "ResourceQueryPlan",
    "ResourceSpec",
]
