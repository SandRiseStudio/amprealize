"""Workspace context providers for global/project chat grounding.

Following `behavior_harden_service_boundaries` (Student): this module uses
in-process services instead of loopback API calls so chat context is fast and
access checks stay aligned with the platform services.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from amprealize.context_composer import ContextComposer
from amprealize.wiki_service import WikiService

logger = logging.getLogger(__name__)


async def _timed(label: str, coro: Any) -> Any:
    """Await coro, logging its wall-clock duration for chat-context latency tracing."""
    start = time.perf_counter()
    try:
        return await coro
    finally:
        logger.info(
            "workspace_context.timing stage=%s elapsed_ms=%.1f",
            label,
            (time.perf_counter() - start) * 1000.0,
        )

# Work items loaded per project for the chat inventory snapshot.
# The formatted output is capped at _FORMAT_INVENTORY_WORK_ITEM_LINE_CAP lines, so
# fetching thousands of items is pure DB/serialization overhead. 50 is sufficient for
# the inventory digest; the targeted-fetch planner handles deeper queries when needed.
_DEFAULT_CHAT_WORK_ITEM_INVENTORY_LIMIT = 50
_MAX_CHAT_WORK_ITEM_INVENTORY_LIMIT = 500
_FORMAT_INVENTORY_WORK_ITEM_LINE_CAP = 40


def _resolved_chat_work_item_inventory_limit(explicit: Optional[int]) -> int:
    """Resolve max work items fetched per project for chat workspace inventory."""
    if explicit is not None:
        return max(1, min(int(explicit), _MAX_CHAT_WORK_ITEM_INVENTORY_LIMIT))
    raw = os.environ.get("AMPREALIZE_CHAT_WORK_ITEM_INVENTORY_LIMIT", "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), _MAX_CHAT_WORK_ITEM_INVENTORY_LIMIT))
    return _DEFAULT_CHAT_WORK_ITEM_INVENTORY_LIMIT


def _resolved_workspace_inventory_ttl() -> float:
    """Resolve inventory cache TTL seconds from env (default 120s)."""
    raw = os.environ.get("AMPREALIZE_WORKSPACE_INVENTORY_TTL_SECONDS", "120").strip()
    try:
        return max(10.0, min(float(raw), 3600.0))
    except ValueError:
        return 120.0


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _to_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
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


def _first_present(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _format_item_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return str(value.isoformat())
        except Exception:
            return str(value)
    return str(value)


class WorkspaceInventoryProvider:
    """Builds compact accessible workspace inventory fragments for chat."""

    def __init__(
        self,
        *,
        project_service: Optional[Any] = None,
        board_service: Optional[Any] = None,
        run_service: Optional[Any] = None,
        behavior_service: Optional[Any] = None,
        wiki_service: Optional[WikiService] = None,
        ttl_seconds: float = _resolved_workspace_inventory_ttl(),
        max_projects: int = 8,
        max_boards_per_project: int = 3,
        max_work_items_per_project: Optional[int] = None,
        max_runs: int = 8,
        max_behaviors: int = 4,
        max_wiki_hits: int = 4,
        workspace_rules: Optional[List[str]] = None,
        endorsed_project_ids: Optional[Iterable[str]] = None,
    ) -> None:
        self._project_service = project_service
        self._board_service = board_service
        self._run_service = run_service
        self._behavior_service = behavior_service
        self._wiki_service = wiki_service
        self._ttl_seconds = ttl_seconds
        self._max_projects = max_projects
        self._max_boards_per_project = max_boards_per_project
        self._max_work_items_per_project = _resolved_chat_work_item_inventory_limit(
            max_work_items_per_project
        )
        self._max_runs = max_runs
        self._max_behaviors = max_behaviors
        self._max_wiki_hits = max_wiki_hits
        self._workspace_rules = workspace_rules if workspace_rules is not None else self._load_workspace_rules_from_env()
        self._endorsed_project_ids = set(endorsed_project_ids or self._load_endorsed_project_ids_from_env())
        self._inventory_cache: Dict[Tuple[str, Optional[str], Optional[str], Optional[str]], Tuple[float, Dict[str, Any]]] = {}

    async def get_workspace_inventory(
        self,
        *,
        user_id: str,
        query: str,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
        conversation_scope: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch deterministic inventory plus query-specific behavior/wiki hints."""
        inventory_task = self._get_cached_inventory(
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
            conversation_scope=conversation_scope,
        )
        behavior_task = self._fetch_behaviors(query, conversation_id=conversation_id)
        wiki_task = self._fetch_wiki_hits(query)

        _overall_start = time.perf_counter()
        inventory, behaviors, wiki_hits = await asyncio.gather(
            _timed("inventory", inventory_task),
            _timed("behaviors", behavior_task),
            _timed("wiki_hits", wiki_task),
        )
        logger.info(
            "workspace_context.timing stage=get_workspace_inventory elapsed_ms=%.1f",
            (time.perf_counter() - _overall_start) * 1000.0,
        )

        content = self._format_inventory(
            inventory,
            behaviors=behaviors,
            wiki_hits=wiki_hits,
            conversation_scope=conversation_scope,
        )
        if not content:
            return []

        source_counts = {
            "projects": len(inventory.get("projects", [])),
            "agent_assignments": len(inventory.get("agent_assignments", [])),
            "boards": sum(len(v) for v in inventory.get("boards_by_project", {}).values()),
            "work_items": sum(len(v) for v in inventory.get("work_items_by_project", {}).values()),
            "runs": len(inventory.get("runs", [])),
            "behaviors": len(behaviors),
            "wiki_hits": len(wiki_hits),
            "workspace_rules": len(self._workspace_rules),
            "guides": len(self._guide_hits(wiki_hits)),
            "endorsed_resources": len(self._endorsed_project_ids),
        }
        context_sources = self._context_sources(
            inventory=inventory,
            behaviors=behaviors,
            wiki_hits=wiki_hits,
            source_counts=source_counts,
        )

        return [
            {
                "content": content,
                "entity_id": user_id,
                "entity_type": "workspace_inventory",
                "relevance_score": 0.95,
                "metadata": {
                    "source_counts": source_counts,
                    "conversation_scope": conversation_scope,
                    "org_id": org_id,
                    "project_id": project_id,
                    "inventory": inventory,
                    "workspace_rules": self._workspace_rules,
                    "retrieved_guides": self._guide_hits(wiki_hits),
                    "endorsed_project_ids": sorted(self._endorsed_project_ids),
                    "context_sources": context_sources,
                    "source_priority_policy": {
                        "always_on": ["workspace_rules"],
                        "prioritized": ["endorsed_projects", "workspace_inventory"],
                        "retrieved": ["guides", "wiki_hits", "behaviors"],
                    },
                },
            }
        ]

    async def _get_cached_inventory(
        self,
        *,
        user_id: str,
        org_id: Optional[str],
        project_id: Optional[str],
        conversation_scope: Optional[str],
    ) -> Dict[str, Any]:
        cache_key = (user_id, org_id, project_id, conversation_scope)
        cached = self._inventory_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < self._ttl_seconds:
            return cached[1]

        inventory = await self._fetch_inventory(
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
        )
        self._inventory_cache[cache_key] = (now, inventory)
        return inventory

    async def _fetch_inventory(
        self,
        *,
        user_id: str,
        org_id: Optional[str],
        project_id: Optional[str],
    ) -> Dict[str, Any]:
        projects = await _timed(
            "inventory.projects",
            self._fetch_projects(user_id=user_id, org_id=org_id, project_id=project_id),
        )
        project_ids = [
            str(_first_present(project, "id", "project_id"))
            for project in projects
            if _first_present(project, "id", "project_id")
        ][: self._max_projects]

        agent_task = self._fetch_agent_assignments(
            user_id=user_id,
            org_id=org_id,
            project_ids=project_ids,
        )
        runs_task = self._fetch_runs(user_id=user_id, org_id=org_id, project_ids=project_ids)
        boards_tasks = [
            self._fetch_boards_for_project(project_id=pid, org_id=org_id)
            for pid in project_ids
        ]
        work_item_tasks = [
            self._fetch_work_items_for_project(project_id=pid, org_id=org_id)
            for pid in project_ids
        ]

        agent_assignments, runs, boards_results, work_item_results = await asyncio.gather(
            _timed("inventory.agent_assignments", agent_task),
            _timed("inventory.runs", runs_task),
            _timed(
                "inventory.boards",
                asyncio.gather(*boards_tasks) if boards_tasks else asyncio.sleep(0, result=[]),
            ),
            _timed(
                "inventory.work_items",
                asyncio.gather(*work_item_tasks) if work_item_tasks else asyncio.sleep(0, result=[]),
            ),
        )

        boards_by_project = {
            project_ids[index]: boards_results[index]
            for index in range(len(project_ids))
        }
        work_items_by_project = {
            project_ids[index]: work_item_results[index]
            for index in range(len(project_ids))
        }

        return {
            "projects": projects,
            "agent_assignments": agent_assignments,
            "boards_by_project": boards_by_project,
            "work_items_by_project": work_items_by_project,
            "runs": runs,
        }

    async def _fetch_projects(
        self,
        *,
        user_id: str,
        org_id: Optional[str],
        project_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        service = self._project_service
        if service is None:
            return []

        def load() -> List[Any]:
            if hasattr(service, "list_projects"):
                try:
                    return service.list_projects(owner_id=user_id, org_id=org_id)
                except TypeError:
                    return service.list_projects(user_id, org_id)
            return []

        try:
            projects = [_to_dict(project) for project in await asyncio.to_thread(load)]
        except Exception as exc:
            logger.debug("workspace_context.projects_failed user_id=%s err=%s", user_id, exc)
            return []

        if project_id:
            projects = [
                project for project in projects
                if str(_first_present(project, "id", "project_id")) == project_id
            ]
        return projects[: self._max_projects]

    async def _fetch_agent_assignments(
        self,
        *,
        user_id: str,
        org_id: Optional[str],
        project_ids: Iterable[str],
    ) -> List[Dict[str, Any]]:
        service = self._project_service
        if service is None:
            return []

        def load() -> List[Any]:
            if hasattr(service, "list_user_project_agent_assignments"):
                try:
                    return service.list_user_project_agent_assignments(owner_id=user_id, org_id=org_id)
                except TypeError:
                    return service.list_user_project_agent_assignments(owner_id=user_id)
            if hasattr(service, "list_project_agent_assignments"):
                assignments: List[Any] = []
                for pid in project_ids:
                    assignments.extend(service.list_project_agent_assignments(pid))
                return assignments
            return []

        try:
            return [_to_dict(item) for item in await asyncio.to_thread(load)]
        except Exception as exc:
            logger.debug("workspace_context.agent_assignments_failed user_id=%s err=%s", user_id, exc)
            return []

    async def _fetch_boards_for_project(self, *, project_id: str, org_id: Optional[str]) -> List[Dict[str, Any]]:
        service = self._board_service
        if service is None or not hasattr(service, "list_boards"):
            return []

        def load() -> List[Any]:
            return service.list_boards(
                project_id=project_id,
                org_id=org_id,
                limit=self._max_boards_per_project,
                offset=0,
            )

        try:
            return [_to_dict(board) for board in await asyncio.to_thread(load)]
        except Exception as exc:
            logger.debug("workspace_context.boards_failed project_id=%s err=%s", project_id, exc)
            return []

    async def _fetch_work_items_for_project(self, *, project_id: str, org_id: Optional[str]) -> List[Dict[str, Any]]:
        service = self._board_service
        if service is None or not hasattr(service, "list_work_items"):
            return []

        max_total = self._max_work_items_per_project

        def load() -> List[Any]:
            try:
                batch = service.list_work_items(
                    project_id=project_id,
                    org_id=org_id,
                    sort_by="updated_at",
                    order="desc",
                    limit=max_total,
                    offset=0,
                )
            except TypeError:
                batch = service.list_work_items(
                    project_id=project_id,
                    org_id=org_id,
                    limit=max_total,
                    offset=0,
                )
            if isinstance(batch, tuple):
                batch = batch[0]
            return list(batch) if batch is not None else []

        try:
            return [_to_dict(item) for item in await asyncio.to_thread(load)]
        except Exception as exc:
            logger.debug("workspace_context.work_items_failed project_id=%s err=%s", project_id, exc)
            return []

    async def _fetch_runs(
        self,
        *,
        user_id: str,
        org_id: Optional[str],
        project_ids: Iterable[str],
    ) -> List[Dict[str, Any]]:
        service = self._run_service
        if service is None or not hasattr(service, "list_runs"):
            return []

        accessible_project_ids = set(project_ids)

        def load() -> List[Any]:
            return service.list_runs(limit=max(self._max_runs * 3, self._max_runs))

        try:
            raw_runs = [_to_dict(run) for run in await asyncio.to_thread(load)]
        except Exception as exc:
            logger.debug("workspace_context.runs_failed user_id=%s err=%s", user_id, exc)
            return []

        runs: List[Dict[str, Any]] = []
        for run in raw_runs:
            actor = _to_dict(run.get("actor"))
            metadata = run.get("metadata") or {}
            run_project_id = str(metadata.get("project_id") or metadata.get("projectId") or "")
            run_org_id = metadata.get("org_id") or metadata.get("orgId")
            actor_id = actor.get("id") or run.get("actor_id")
            triggering_user_id = run.get("triggering_user_id")
            user_can_see = actor_id == user_id or triggering_user_id == user_id
            project_can_see = bool(run_project_id and run_project_id in accessible_project_ids)
            org_can_see = bool(org_id and run_org_id == org_id and (user_can_see or project_can_see))
            if user_can_see or project_can_see or org_can_see:
                runs.append(run)
            if len(runs) >= self._max_runs:
                break
        return runs

    async def _fetch_behaviors(
        self,
        query: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        service = self._behavior_service
        if not query or service is None or not hasattr(service, "get_relevant_behaviors_for_task"):
            return []

        def load() -> Dict[str, Any]:
            return service.get_relevant_behaviors_for_task(
                task_description=query,
                role="Student",
                limit=self._max_behaviors,
                telemetry_session_id=conversation_id,
            )

        try:
            result = await asyncio.to_thread(load)
        except Exception as exc:
            logger.debug("workspace_context.behaviors_failed err=%s", exc)
            return []
        return list(result.get("recommended_behaviors", []))[: self._max_behaviors]

    async def _fetch_wiki_hits(self, query: str) -> List[Dict[str, Any]]:
        service = self._wiki_service
        if not query or service is None:
            return []

        def load() -> List[Dict[str, Any]]:
            hits: List[Dict[str, Any]] = []
            for domain in ("ai-learning", "platform"):
                result = service.query(domain, query, max_results=self._max_wiki_hits)
                if result.get("success"):
                    for item in result.get("results", []):
                        hits.append({"domain": domain, **item})
            hits.sort(key=lambda item: item.get("score", 0), reverse=True)
            return hits[: self._max_wiki_hits]

        try:
            return await asyncio.to_thread(load)
        except Exception as exc:
            logger.debug("workspace_context.wiki_failed err=%s", exc)
            return []

    def _format_inventory(
        self,
        inventory: Dict[str, Any],
        *,
        behaviors: List[Dict[str, Any]],
        wiki_hits: List[Dict[str, Any]],
        conversation_scope: Optional[str],
    ) -> str:
        lines = [
            "This fragment lists resources the user can access through Amprealize services.",
            "When the user asks about projects (names, counts, or \"what are they\"), answer from the "
            "Projects bullets below (name, slug, id). Do not infer project names only from work item titles.",
            f"Conversation scope: {conversation_scope or 'unknown'}",
        ]

        if self._workspace_rules:
            lines.append("Workspace rules (always included):")
            for rule in self._workspace_rules[:6]:
                lines.append(f"- {rule}")

        projects = inventory.get("projects", [])
        project_names_by_id: Dict[str, str] = {}
        if projects:
            lines.append("Projects:")
            for project in projects:
                pid = _first_present(project, "id", "project_id", default="unknown")
                name = _first_present(project, "name", "title", default="Untitled project")
                project_names_by_id[str(pid)] = str(name)
                slug = project.get("slug")
                description = project.get("description")
                endorsed = str(pid) in self._endorsed_project_ids
                suffix = f" ({slug})" if slug else ""
                line = f"- {name}{suffix} [{pid}]"
                if endorsed:
                    line += " [endorsed]"
                if description:
                    line += f": {description}"
                lines.append(line)

        agent_assignments = inventory.get("agent_assignments", [])
        if agent_assignments:
            lines.append("Assigned/available agents by project:")
            for assignment in agent_assignments[:8]:
                agent_id = _first_present(assignment, "agent_id", "id", default="unknown")
                agent_name = _first_present(assignment, "agent_name", "name", "display_name", default=None)
                agent_slug = assignment.get("agent_slug") or assignment.get("slug")
                project_id = str(assignment.get("project_id") or "unknown project")
                project_name = project_names_by_id.get(project_id)
                role = _enum_value(assignment.get("role") or assignment.get("agent_role"))
                agent_label = str(agent_name or agent_id)
                if agent_slug and agent_slug != agent_label:
                    agent_label += f" ({agent_slug})"
                project_label = f"{project_name} [{project_id}]" if project_name else project_id
                lines.append(f"- {agent_label} [{agent_id}] on {project_label} ({role or 'member'})")

        boards_by_project = inventory.get("boards_by_project", {})
        if boards_by_project:
            lines.append("Boards:")
            for pid, boards in boards_by_project.items():
                for board in boards:
                    board_id = _first_present(board, "board_id", "id", default="unknown")
                    name = _first_present(board, "name", "title", default="Untitled board")
                    lines.append(f"- {name} [{board_id}] in project {pid}")

        work_items_by_project = inventory.get("work_items_by_project", {})
        if work_items_by_project:
            lines.append("Recent/active work items:")
            wi_total = sum(len(v) for v in work_items_by_project.values() if isinstance(v, list))
            shown = 0
            cap = _FORMAT_INVENTORY_WORK_ITEM_LINE_CAP
            for pid, work_items in work_items_by_project.items():
                if not isinstance(work_items, list):
                    continue
                for item in work_items:
                    if shown >= cap:
                        omitted = wi_total - cap
                        if omitted > 0:
                            lines.append(
                                f"- … ({omitted} more work items omitted from this formatted list)"
                            )
                        break
                    item_id = _first_present(item, "item_id", "id", default="unknown")
                    title = _first_present(item, "title", "name", default="Untitled work item")
                    status = _enum_value(item.get("status"))
                    item_type = _enum_value(item.get("item_type"))
                    parent_raw = _first_present(item, "parent_id", "parentId", default=None)
                    updated = _format_item_timestamp(
                        _first_present(item, "updated_at", "updatedAt", default=None)
                    )
                    created = _format_item_timestamp(
                        _first_present(item, "created_at", "createdAt", default=None)
                    )
                    meta_parts: List[str] = []
                    if parent_raw is not None and str(parent_raw) != "":
                        meta_parts.append(f"parent={parent_raw}")
                    if updated:
                        meta_parts.append(f"updated={updated}")
                    if created:
                        meta_parts.append(f"created={created}")
                    meta_suffix = (" | " + "; ".join(meta_parts)) if meta_parts else ""
                    lines.append(
                        f"- {title} [{item_id}] ({item_type or 'item'}, {status or 'unknown'}) "
                        f"in project {pid}{meta_suffix}"
                    )
                    shown += 1
                if shown >= cap:
                    break

        runs = inventory.get("runs", [])
        if runs:
            lines.append("Recent runs:")
            for run in runs:
                run_id = _first_present(run, "run_id", "id", default="unknown")
                status = _enum_value(run.get("status"))
                message = run.get("message") or run.get("workflow_name") or run.get("template_name")
                line = f"- {run_id}: {status or 'unknown'}"
                if message:
                    line += f" — {message}"
                lines.append(line)

        if behaviors:
            lines.append("Relevant behaviors:")
            for behavior in behaviors:
                name = behavior.get("name", "unnamed")
                instruction = behavior.get("instruction", "")
                lines.append(f"- {name}: {instruction[:180]}")

        if wiki_hits:
            lines.append("Relevant wiki pages:")
            for hit in wiki_hits:
                lines.append(
                    f"- {hit.get('title', hit.get('page_path'))} "
                    f"({hit.get('domain')}/{hit.get('page_path')}): {hit.get('snippet', '')[:160]}"
                )

        guide_hits = self._guide_hits(wiki_hits)
        if guide_hits:
            lines.append("Retrieved guides:")
            for guide in guide_hits:
                lines.append(
                    f"- {guide.get('title', guide.get('page_path'))} "
                    f"({guide.get('domain')}/{guide.get('page_path')})"
                )

        return "\n".join(lines)

    @staticmethod
    def _load_workspace_rules_from_env() -> List[str]:
        raw_rules = os.environ.get("AMPREALIZE_CHAT_WORKSPACE_RULES", "")
        if not raw_rules:
            return []
        return [rule.strip() for rule in re.split(r"[\n;]+", raw_rules) if rule.strip()]

    @staticmethod
    def _load_endorsed_project_ids_from_env() -> List[str]:
        raw_ids = os.environ.get("AMPREALIZE_CHAT_ENDORSED_PROJECT_IDS", "")
        if not raw_ids:
            return []
        return [project_id.strip() for project_id in raw_ids.split(",") if project_id.strip()]

    @staticmethod
    def _guide_hits(wiki_hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        guides = [
            hit for hit in wiki_hits
            if "guide" in str(hit.get("type", "")).lower()
            or "guide" in str(hit.get("page_path", "")).lower()
        ]
        return guides[:4]

    def _context_sources(
        self,
        *,
        inventory: Dict[str, Any],
        behaviors: List[Dict[str, Any]],
        wiki_hits: List[Dict[str, Any]],
        source_counts: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        return [
            {"kind": "workspace_rules", "count": len(self._workspace_rules), "visibility": "admin"},
            {"kind": "workspace_inventory", "count": source_counts.get("projects", 0), "visibility": "admin"},
            {"kind": "endorsed_projects", "count": len(self._endorsed_project_ids), "visibility": "admin"},
            {"kind": "retrieved_guides", "count": len(self._guide_hits(wiki_hits)), "visibility": "admin"},
            {"kind": "behavior_guidance", "count": len(behaviors), "visibility": "admin"},
            {"kind": "runs", "count": len(inventory.get("runs", [])), "visibility": "admin"},
        ]


def build_chat_context_composer(
    *,
    project_service: Optional[Any] = None,
    board_service: Optional[Any] = None,
    run_service: Optional[Any] = None,
    behavior_service: Optional[Any] = None,
    wiki_service: Optional[WikiService] = None,
    telemetry: Optional[Any] = None,
) -> ContextComposer:
    """Create the context composer used by chat reply services."""
    resolved_wiki_service = wiki_service or WikiService(
        repo_root=os.environ.get("AMPREALIZE_REPO_ROOT") or os.getcwd()
    )
    workspace_provider = WorkspaceInventoryProvider(
        project_service=project_service,
        board_service=board_service,
        run_service=run_service,
        behavior_service=behavior_service,
        wiki_service=resolved_wiki_service,
    )
    return ContextComposer(
        workspace_provider=workspace_provider,
        telemetry=telemetry,
    )


__all__ = ["WorkspaceInventoryProvider", "build_chat_context_composer"]
