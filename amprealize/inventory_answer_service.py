"""Deterministic answers for workspace inventory chat questions.

Following `behavior_instrument_metrics_pipeline` (Student): these handlers
produce structured metadata so reply routing can track fast-path coverage and
context misses without an LLM round-trip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from amprealize.resource_analysis import ResourceAnalysisAnswer, ResourceAnalysisService


@dataclass
class InventoryAnswer:
    """A deterministic answer built from accessible workspace inventory."""

    content: str
    answer_type: str
    structured_payload: Dict[str, Any] = field(default_factory=dict)
    source_rows: List[Dict[str, Any]] = field(default_factory=list)
    trace_steps: List[Dict[str, Any]] = field(default_factory=list)
    requires_clarification: bool = False


class InventoryAnswerService:
    """Answers simple workspace questions from the inventory fragment."""

    def __init__(
        self,
        *,
        resource_analysis_service: Optional[ResourceAnalysisService] = None,
    ) -> None:
        self._resource_analysis_service = resource_analysis_service or ResourceAnalysisService()

    def answer(
        self,
        *,
        query: str,
        inventory: Dict[str, Any],
        scope_hints: Optional[Dict[str, Any]] = None,
    ) -> Optional[InventoryAnswer]:
        analysis_answer = self._resource_analysis_service.answer_sync(
            query=query,
            inventory=inventory,
            scope_hints=scope_hints,
        )
        if analysis_answer is not None:
            return self._from_resource_analysis(analysis_answer)

        normalized_query = _normalize_lookup_text(query)
        projects = _list(inventory.get("projects"))
        assignments = _list(inventory.get("agent_assignments"))
        runs = _list(inventory.get("runs"))
        boards_by_project = _dict(inventory.get("boards_by_project"))
        work_items_by_project = _dict(inventory.get("work_items_by_project"))

        if self._is_board_query(normalized_query):
            return self._answer_boards(normalized_query, projects, boards_by_project)

        if self._is_project_list_query(normalized_query):
            return self._answer_projects(projects)

        if self._is_assignment_query(normalized_query):
            return self._answer_assignments(normalized_query, projects, assignments)

        if self._is_agent_list_query(normalized_query):
            return self._answer_available_agents(assignments)

        if self._is_run_query(normalized_query):
            return self._answer_runs(normalized_query, runs)

        if self._is_work_item_query(normalized_query):
            return self._answer_work_items(normalized_query, projects, work_items_by_project)

        return None

    @staticmethod
    def _from_resource_analysis(answer: ResourceAnalysisAnswer) -> InventoryAnswer:
        return InventoryAnswer(
            content=answer.content,
            answer_type=answer.answer_type,
            structured_payload=answer.structured_payload,
            source_rows=answer.source_rows,
            trace_steps=answer.trace_steps,
            requires_clarification=answer.requires_clarification,
        )

    @staticmethod
    def _is_project_list_query(query: str) -> bool:
        lowered = query.lower()
        if re.search(r"\bdo you have access\b", lowered):
            return False
        if re.search(r"\b(local\s+project|project\s+path|local\s+path)\b", lowered):
            return False
        return bool(
            re.search(r"\b(project|projects)\b", lowered)
            and re.search(r"\b(what|which|list|show|have|available)\b", lowered)
            and "agent" not in lowered
            and "run" not in lowered
            and "work item" not in lowered
            and "board" not in lowered
        )

    @staticmethod
    def _is_board_query(query: str) -> bool:
        return bool(re.search(r"\b(board|boards)\b", query))

    @staticmethod
    def _is_assignment_query(query: str) -> bool:
        return "agent" in query and any(word in query for word in ("assign", "assigned", "assignment"))

    @staticmethod
    def _is_agent_list_query(query: str) -> bool:
        return "agent" in query and any(word in query for word in ("available", "list", "show", "have"))

    @staticmethod
    def _is_run_query(query: str) -> bool:
        return bool(re.search(r"\b(run|runs|execution|executions)\b", query))

    @staticmethod
    def _is_work_item_query(query: str) -> bool:
        return bool(re.search(r"\b(work item|work items|task|tasks|bug|bugs|blocked|owned|assigned)\b", query))

    def _answer_projects(self, projects: Sequence[Dict[str, Any]]) -> InventoryAnswer:
        if not projects:
            return InventoryAnswer(
                content="I don't see any projects in your accessible workspace inventory.",
                answer_type="projects",
                structured_payload=self._payload("project_list", "Accessible projects", "No projects found."),
                trace_steps=self._trace("direct_lookup", "Checked accessible project inventory", 0),
            )

        rows = [self._project_row(project) for project in projects]
        lines = ["Based on the workspace inventory, you have access to these projects:"]
        lines.extend(f"- {row['label']} [{row['id']}]" for row in rows)
        return InventoryAnswer(
            content="\n".join(lines),
            answer_type="projects",
            structured_payload=self._payload(
                "project_list",
                "Accessible projects",
                f"{len(rows)} project{'s' if len(rows) != 1 else ''} found.",
                rows=rows,
            ),
            source_rows=rows,
            trace_steps=self._trace("direct_lookup", "Matched project list question", len(rows)),
        )

    def _answer_assignments(
        self,
        query: str,
        projects: Sequence[Dict[str, Any]],
        assignments: Sequence[Dict[str, Any]],
    ) -> InventoryAnswer:
        target_project = self._find_project_for_query(query, projects)
        if target_project is None:
            if len(projects) == 1:
                target_project = projects[0]
            else:
                project_names = ", ".join(
                    str(_first_present(project, "name", "title", "slug", default="Untitled project"))
                    for project in projects[:5]
                )
                return InventoryAnswer(
                    content=(
                        "Which project should I check for agent assignments?"
                        + (f" I can see: {project_names}." if project_names else "")
                    ),
                    answer_type="assignment_clarification",
                    structured_payload=self._payload(
                        "direct_answer",
                        "Clarification needed",
                        "Multiple projects are available, so I need the project name before answering.",
                        rows=[self._project_row(project) for project in projects[:5]],
                    ),
                    source_rows=[self._project_row(project) for project in projects[:5]],
                    trace_steps=self._trace("clarification", "No unique project was named", len(projects)),
                    requires_clarification=True,
                )

        project_id = str(_first_present(target_project, "id", "project_id", default=""))
        project_name = str(_first_present(target_project, "name", "title", default="the project"))
        matching_assignments = [
            item for item in assignments
            if str(_first_present(item, "project_id", default="")) == project_id
        ]
        rows = [self._assignment_row(item) for item in matching_assignments]

        if not rows:
            return InventoryAnswer(
                content=f"I don't see any agents assigned to {project_name} ({project_id}) in your accessible workspace inventory.",
                answer_type="assignments",
                structured_payload=self._payload(
                    "assignment",
                    f"Agents assigned to {project_name}",
                    "No assignments found in accessible inventory.",
                    rows=[],
                ),
                trace_steps=self._trace("direct_lookup", "Checked project-agent assignments", 0),
            )

        lines = [f"Based on the workspace inventory, these agents are assigned to {project_name} ({project_id}):"]
        for row in rows:
            slug = f" ({row['slug']})" if row.get("slug") else ""
            lines.append(f"- {row['name']}{slug} [{row['id']}] - {row.get('role') or 'member'}")
        return InventoryAnswer(
            content="\n".join(lines),
            answer_type="assignments",
            structured_payload=self._payload(
                "assignment",
                f"Agents assigned to {project_name}",
                f"{len(rows)} assignment{'s' if len(rows) != 1 else ''} found.",
                rows=rows,
                project_id=project_id,
            ),
            source_rows=rows,
            trace_steps=self._trace("direct_lookup", "Matched project-agent assignment question", len(rows)),
        )

    def _answer_available_agents(self, assignments: Sequence[Dict[str, Any]]) -> InventoryAnswer:
        rows_by_agent: Dict[str, Dict[str, Any]] = {}
        for assignment in assignments:
            row = self._assignment_row(assignment)
            rows_by_agent.setdefault(row["id"], row)

        rows = list(rows_by_agent.values())
        if not rows:
            return InventoryAnswer(
                content="I don't see any available or assigned agents in your accessible workspace inventory.",
                answer_type="agents",
                structured_payload=self._payload("agent_list", "Available agents", "No agents found."),
                trace_steps=self._trace("direct_lookup", "Checked accessible agent assignments", 0),
            )

        lines = ["Based on the workspace inventory, these agents are available through project assignments:"]
        for row in rows:
            slug = f" ({row['slug']})" if row.get("slug") else ""
            lines.append(f"- {row['name']}{slug} [{row['id']}]")
        return InventoryAnswer(
            content="\n".join(lines),
            answer_type="agents",
            structured_payload=self._payload(
                "agent_list",
                "Available agents",
                f"{len(rows)} agent{'s' if len(rows) != 1 else ''} found.",
                rows=rows,
            ),
            source_rows=rows,
            trace_steps=self._trace("direct_lookup", "Matched available-agent question", len(rows)),
        )

    def _answer_boards(
        self,
        query: str,
        projects: Sequence[Dict[str, Any]],
        boards_by_project: Dict[str, Any],
    ) -> InventoryAnswer:
        target_project = self._find_project_for_query(query, projects)
        selected_projects = [target_project] if target_project else list(projects)
        rows: List[Dict[str, Any]] = []
        for project in selected_projects:
            if not project:
                continue
            project_id = str(_first_present(project, "id", "project_id", default=""))
            project_name = str(_first_present(project, "name", "title", default=project_id))
            for board in _list(boards_by_project.get(project_id)):
                rows.append(self._board_row(board, project_id=project_id, project_name=project_name))

        title = (
            f"Boards on {str(_first_present(target_project, 'name', 'title', default='project'))}"
            if target_project
            else "Accessible boards"
        )
        if not rows:
            project_label = ""
            if target_project:
                project_label = f" for {str(_first_present(target_project, 'name', 'title', default='that project'))}"
            return InventoryAnswer(
                content=f"I don't see any boards{project_label} in your accessible workspace inventory.",
                answer_type="boards",
                structured_payload=self._payload("board_list", title, "No matching boards found."),
                trace_steps=self._trace("direct_lookup", "Checked accessible board inventory", 0),
            )

        lines = [f"Based on the workspace inventory, these boards are available{' on ' + rows[0]['project_name'] if target_project else ''}:"]
        lines.extend(f"- {row['name']} [{row['id']}] in {row['project_name']} [{row['project_id']}]" for row in rows)
        return InventoryAnswer(
            content="\n".join(lines),
            answer_type="boards",
            structured_payload=self._payload(
                "board_list",
                title,
                f"{len(rows)} board{'s' if len(rows) != 1 else ''} found.",
                rows=rows,
                project_id=str(_first_present(target_project, "id", "project_id", default="")) if target_project else None,
            ),
            source_rows=rows,
            trace_steps=self._trace("direct_lookup", "Matched board inventory question", len(rows)),
        )

    def _answer_runs(self, query: str, runs: Sequence[Dict[str, Any]]) -> InventoryAnswer:
        status_filter = self._status_filter(query, active_words=("active", "running", "in progress"))
        selected = [
            run for run in runs
            if status_filter is None or _normalize_lookup_text(str(run.get("status", ""))) in status_filter
        ]
        rows = [self._run_row(run) for run in selected]
        title = "Active runs" if status_filter else "Recent runs"
        if not rows:
            return InventoryAnswer(
                content=f"I don't see any {title.lower()} in your accessible workspace inventory.",
                answer_type="runs",
                structured_payload=self._payload("run_list", title, "No matching runs found."),
                trace_steps=self._trace("direct_lookup", f"Checked {title.lower()}", 0),
            )

        lines = [f"Based on the workspace inventory, these are the {title.lower()} I can see:"]
        lines.extend(f"- {row['id']}: {row.get('status') or 'unknown'}{_suffix(row.get('summary'))}" for row in rows)
        return InventoryAnswer(
            content="\n".join(lines),
            answer_type="runs",
            structured_payload=self._payload(
                "run_list",
                title,
                f"{len(rows)} run{'s' if len(rows) != 1 else ''} found.",
                rows=rows,
            ),
            source_rows=rows,
            trace_steps=self._trace("direct_lookup", f"Matched {title.lower()} question", len(rows)),
        )

    def _answer_work_items(
        self,
        query: str,
        projects: Sequence[Dict[str, Any]],
        work_items_by_project: Dict[str, Any],
    ) -> InventoryAnswer:
        target_project = self._find_project_for_query(query, projects)
        all_items: List[Dict[str, Any]] = []
        for project_id, items in work_items_by_project.items():
            if target_project is not None:
                target_project_id = str(_first_present(target_project, "id", "project_id", default=""))
                if str(project_id) != target_project_id:
                    continue
            for item in _list(items):
                item_copy = dict(item)
                item_copy.setdefault("project_id", project_id)
                all_items.append(item_copy)

        if "blocked" in query:
            all_items = [
                item for item in all_items
                if "blocked" in _normalize_lookup_text(str(item.get("status", "")))
                or "blocked" in _normalize_lookup_text(str(item.get("blocked_reason", "")))
            ]

        rows = [self._work_item_row(item) for item in all_items]
        title = "Blocked work items" if "blocked" in query else "Recent work items"
        if not rows:
            return InventoryAnswer(
                content=f"I don't see any {title.lower()} in your accessible workspace inventory.",
                answer_type="work_items",
                structured_payload=self._payload("work_item_list", title, "No matching work items found."),
                trace_steps=self._trace("direct_lookup", f"Checked {title.lower()}", 0),
            )

        lines = [f"Based on the workspace inventory, these are the {title.lower()} I can see:"]
        lines.extend(
            f"- {row['title']} [{row['id']}] - {row.get('status') or 'unknown'} in project {row.get('project_id')}"
            for row in rows
        )
        return InventoryAnswer(
            content="\n".join(lines),
            answer_type="work_items",
            structured_payload=self._payload(
                "work_item_list",
                title,
                f"{len(rows)} work item{'s' if len(rows) != 1 else ''} found.",
                rows=rows,
            ),
            source_rows=rows,
            trace_steps=self._trace("direct_lookup", f"Matched {title.lower()} question", len(rows)),
        )

    @staticmethod
    def _status_filter(query: str, *, active_words: Iterable[str]) -> Optional[set[str]]:
        if any(word in query for word in active_words):
            return {"running", "in progress", "active", "queued", "pending"}
        return None

    @staticmethod
    def _find_project_for_query(query: str, projects: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0
        for project in projects:
            candidates = [
                _first_present(project, "id", "project_id", default=""),
                _first_present(project, "slug", default=""),
                _first_present(project, "name", "title", default=""),
            ]
            for candidate in candidates:
                candidate_text = _normalize_lookup_text(str(candidate))
                if not candidate_text:
                    continue
                if re.search(rf"\b{re.escape(candidate_text)}\b", query):
                    score = len(candidate_text)
                    if score > best_score:
                        best_match = project
                        best_score = score
        return best_match

    @staticmethod
    def _project_row(project: Dict[str, Any]) -> Dict[str, Any]:
        project_id = str(_first_present(project, "id", "project_id", default="unknown"))
        name = str(_first_present(project, "name", "title", default="Untitled project"))
        slug = project.get("slug")
        return {
            "id": project_id,
            "name": name,
            "slug": slug,
            "label": f"{name} ({slug})" if slug else name,
            "description": project.get("description"),
        }

    @staticmethod
    def _assignment_row(assignment: Dict[str, Any]) -> Dict[str, Any]:
        agent_id = str(_first_present(assignment, "agent_id", "id", default="unknown"))
        name = str(_first_present(assignment, "agent_name", "name", "display_name", default=agent_id))
        return {
            "id": agent_id,
            "name": name,
            "slug": assignment.get("agent_slug") or assignment.get("slug"),
            "role": getattr(assignment.get("role") or assignment.get("agent_role"), "value", assignment.get("role") or assignment.get("agent_role")),
            "project_id": assignment.get("project_id"),
        }

    @staticmethod
    def _run_row(run: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(_first_present(run, "run_id", "id", default="unknown")),
            "status": getattr(run.get("status"), "value", run.get("status")),
            "summary": run.get("message") or run.get("workflow_name") or run.get("template_name"),
        }

    @staticmethod
    def _work_item_row(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(_first_present(item, "item_id", "id", default="unknown")),
            "title": str(_first_present(item, "title", "name", default="Untitled work item")),
            "status": getattr(item.get("status"), "value", item.get("status")),
            "item_type": getattr(item.get("item_type"), "value", item.get("item_type")),
            "project_id": item.get("project_id"),
            "assignee": item.get("assignee") or item.get("assignee_id") or item.get("owner_id"),
        }

    @staticmethod
    def _board_row(board: Dict[str, Any], *, project_id: str, project_name: str) -> Dict[str, Any]:
        return {
            "id": str(_first_present(board, "board_id", "id", default="unknown")),
            "name": str(_first_present(board, "name", "title", default="Untitled board")),
            "project_id": project_id,
            "project_name": project_name,
            "is_default": bool(board.get("is_default")),
            "description": board.get("description"),
        }

    @staticmethod
    def _payload(
        card_kind: str,
        title: str,
        summary: str,
        *,
        rows: Optional[List[Dict[str, Any]]] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        return {
            "card_kind": card_kind,
            "title": title,
            "summary": summary,
            "rows": rows or [],
            "cta_label": "Inspect sources",
            **extra,
        }

    @staticmethod
    def _trace(phase: str, label: str, row_count: int) -> List[Dict[str, Any]]:
        return [{"phase": phase, "label": label, "row_count": row_count}]


def _normalize_lookup_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _first_present(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _suffix(value: Any) -> str:
    return f" - {value}" if value else ""


__all__ = ["InventoryAnswer", "InventoryAnswerService"]
