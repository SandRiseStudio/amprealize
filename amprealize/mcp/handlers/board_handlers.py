"""MCP tool handlers for BoardService.

Provides handlers for board and work item management.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ...services.board_service import BoardService, Actor, BoardNotFoundError, WorkItemNotFoundError, WorkItemValidationError, ColumnNotFoundError, AuthorNotFoundError
from ...boards.contracts import (
    Board,
    BoardTemplate,
    BoardWithColumns,
    BoardColumn,
    WorkItem,
    WorkItemType,
    WorkItemStatus,
    WorkItemPriority,
    CreateBoardRequest,
    CreateColumnRequest,
    UpdateBoardRequest,
    CreateWorkItemRequest,
    UpdateWorkItemRequest,
    MoveWorkItemRequest,
    CreateLabelRequest,
    LabelColor,
    UpdateLabelRequest,
    SuggestAgentRequest,
    normalize_item_type,
)
from ...services.assignment_service import AssignmentService


class BoardToolValidationError(ValueError):
    """Raised when a board/work item MCP tool is missing required runtime arguments."""


# ==============================================================================
# Serialization Helpers
# ==============================================================================


def _serialize_value(value: Any) -> Any:
    """Recursively serialize values for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, 'value'):  # Enum
        return value.value
    if hasattr(value, 'model_dump'):  # Pydantic model
        return {k: _serialize_value(v) for k, v in value.model_dump().items()}
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _board_to_dict(board: Board) -> Dict[str, Any]:
    """Convert Board Pydantic model to dict with serialized timestamps."""
    result = board.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _board_with_columns_to_dict(board: BoardWithColumns) -> Dict[str, Any]:
    """Convert BoardWithColumns Pydantic model to dict."""
    result = board.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _work_item_to_dict(item: WorkItem) -> Dict[str, Any]:
    """Convert WorkItem Pydantic model to dict with serialized timestamps."""
    result = item.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def _work_item_summary_to_dict(item: WorkItem) -> Dict[str, Any]:
    """Compact work item shape for list responses.

    `workItems.list` is frequently called from agent chat. Returning full
    descriptions, metadata, checklists, and attachments for every row can make
    the MCP response hundreds of KB. Keep list responses scan-friendly; callers
    can use `workItems.get` for full details.
    """
    return {
        "item_id": item.item_id,
        "display_id": item.display_id,
        "item_type": item.item_type.value if hasattr(item.item_type, "value") else item.item_type,
        "title": item.title,
        "status": item.status.value if hasattr(item.status, "value") else item.status,
        "priority": item.priority.value if hasattr(item.priority, "value") else item.priority,
        "project_id": item.project_id,
        "board_id": item.board_id,
        "parent_id": item.parent_id,
        "assignee_id": item.assignee_id,
        "assignee_type": item.assignee_type,
        "labels": item.labels,
        "points": item.points,
        "updated_at": _serialize_value(item.updated_at),
        "display_number": item.display_number,
        "child_count": item.child_count,
        "completed_child_count": item.completed_child_count,
        "progress_percent": item.progress_percent,
    }


def _get_actor(arguments: Dict[str, Any]) -> Actor:
    """Extract actor from arguments or create default."""
    session = arguments.get("_session", {})
    user_id = arguments.get("user_id") or session.get("user_id") or "mcp-user"
    role = arguments.get("actor_role", "user")
    surface = arguments.get("actor_surface", "mcp")
    return Actor(id=user_id, role=role, surface=surface)


def _mcp_coalesce_points(arguments: Dict[str, Any]) -> Optional[int]:
    """Resolve MCP `points` / legacy `story_points`; preserve 0 (avoid truthiness bugs)."""
    if arguments.get("points") is not None:
        return arguments["points"]
    if arguments.get("story_points") is not None:
        return arguments["story_points"]
    return None


def _require(arguments: Dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not arguments.get(field)]
    if not missing:
        return
    label = "parameter" if len(missing) == 1 else "parameters"
    raise BoardToolValidationError(f"Missing required {label}: {', '.join(missing)}")


def _resolve_id(
    service: BoardService,
    identifier: str,
    arguments: Dict[str, Any],
) -> str:
    """Resolve a display ID (e.g. 'myproject-42') or pass through a UUID/short-ID."""
    org_id = arguments.get("org_id")
    project_id = arguments.get("project_id")
    return service.resolve_work_item_id(
        identifier, org_id=org_id, project_id=project_id,
    )


def _looks_like_agent_author(arguments: Dict[str, Any], author_id: Optional[str]) -> bool:
    """Infer agent comments when MCP agent role/surface metadata is present."""
    actor_role = str(arguments.get("actor_role", "")).lower()
    actor_surface = str(arguments.get("actor_surface", "")).lower()
    user_id = str(author_id or arguments.get("user_id", "")).lower()
    return (
        actor_role in {"agent", "student", "teacher", "metacognitive strategist", "strategist"}
        or actor_surface in {"agent", "mcp-agent"}
        or user_id.endswith("-agent")
        or user_id.startswith("agent_")
    )


# ==============================================================================
# Board Label, Filter, and Assignment Helpers
# ==============================================================================


def handle_list_labels(service: BoardService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """List labels for a project."""
    _require(arguments, "project_id")
    response = service.list_labels(
        project_id=arguments["project_id"],
        org_id=arguments.get("org_id"),
        limit=arguments.get("limit", 100),
        offset=arguments.get("offset", 0),
    )
    return {
        "success": True,
        "labels": [label.model_dump(mode="json") for label in response.labels],
        "total": response.total,
    }


def handle_create_label(service: BoardService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Create a project label."""
    _require(arguments, "project_id", "name")
    request = CreateLabelRequest(
        name=arguments["name"],
        color=LabelColor(arguments.get("color", "gray")),
        description=arguments.get("description"),
    )
    label = service.create_label(arguments["project_id"], request, _get_actor(arguments), org_id=arguments.get("org_id"))
    return {"success": True, "label": label.model_dump(mode="json")}


def handle_update_label(service: BoardService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Update a label."""
    _require(arguments, "label_id")
    color = arguments.get("color")
    request = UpdateLabelRequest(
        name=arguments.get("name"),
        color=LabelColor(color) if color is not None else None,
        description=arguments.get("description"),
    )
    label = service.update_label(arguments["label_id"], request, _get_actor(arguments), org_id=arguments.get("org_id"))
    return {"success": True, "label": label.model_dump(mode="json")}


def handle_delete_label(service: BoardService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a label."""
    _require(arguments, "label_id")
    result = service.delete_label(arguments["label_id"], _get_actor(arguments), org_id=arguments.get("org_id"))
    return {"success": True, "deleted_id": result.deleted_id}


def handle_filter_items(service: BoardService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Filter work items using BoardService's canonical list query."""
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)
    item_type = WorkItemType(normalize_item_type(arguments["item_type"])) if arguments.get("item_type") else None
    status = WorkItemStatus(arguments["status"]) if arguments.get("status") else None
    parent_id = arguments.get("parent_id")
    if parent_id:
        parent_id = _resolve_id(service, parent_id, arguments)
    items, total = service.list_work_items(
        project_id=arguments.get("project_id"),
        board_id=arguments.get("board_id"),
        item_type=item_type,
        status=status,
        parent_id=parent_id,
        assignee_id=arguments.get("assignee_id"),
        labels=arguments.get("labels"),
        sprint_id=arguments.get("sprint_id"),
        title_search=arguments.get("title_search") or None,
        text_search=arguments.get("text_search") or None,
        org_id=arguments.get("org_id"),
        limit=limit,
        offset=offset,
        include_total=True,
    )
    return {
        "success": True,
        "items": [_work_item_to_dict(item) for item in items],
        "total": total,
        "has_more": offset + len(items) < total,
        "limit": limit,
        "offset": offset,
    }


def handle_suggest_agent(service: BoardService, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest agents for a feature or task."""
    _require(arguments, "assignable_id", "assignable_type")
    request = SuggestAgentRequest(
        assignable_id=arguments["assignable_id"],
        assignable_type=arguments["assignable_type"],
        required_behaviors=arguments.get("required_behaviors", []),
        exclude_agent_ids=arguments.get("exclude_agent_ids"),
        max_suggestions=arguments.get("max_suggestions", 3),
    )
    assignment_service = AssignmentService(dsn=getattr(service, "_dsn", None), board_service=service)
    response = assignment_service.suggest_agent(request, actor=_get_actor(arguments), org_id=arguments.get("org_id"))
    return response.model_dump(mode="json") if hasattr(response, "model_dump") else response.dict()


# ==============================================================================
# Board CRUD Handlers
# ==============================================================================


def handle_list_boards(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List boards for a project.

    MCP Tool: boards.list
    """
    project_id = arguments.get("project_id")
    org_id = arguments.get("org_id")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)

    _require(arguments, "project_id")

    boards = service.list_boards(
        project_id=project_id,
        org_id=org_id,
        limit=limit,
        offset=offset,
    )

    return {
        "success": True,
        "boards": [_board_to_dict(b) for b in boards],
        "total": len(boards),
        "project_id": project_id,
        "limit": limit,
        "offset": offset,
    }


def handle_create_board(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new board.

    MCP Tool: boards.create
    """
    project_id = arguments.get("project_id")
    name = arguments.get("name")
    org_id = arguments.get("org_id")

    _require(arguments, "project_id", "name")

    actor = _get_actor(arguments)

    request = CreateBoardRequest(
        project_id=project_id,
        name=name,
        description=arguments.get("description"),
        is_default=arguments.get("is_default", False),
        create_default_columns=arguments.get("create_default_columns", True),
        template=arguments.get("template", "minimal"),
    )

    board = service.create_board(request, actor, org_id=org_id)

    return {
        "success": True,
        "board": _board_to_dict(board),
        "message": f"Board '{name}' created successfully",
    }


def handle_get_board(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get board details by ID.

    MCP Tool: boards.get
    """
    board_id = arguments.get("board_id")
    org_id = arguments.get("org_id")
    include_columns = arguments.get("include_columns", True)

    _require(arguments, "board_id")

    try:
        if include_columns:
            board = service.get_board_with_columns(board_id, org_id=org_id)
            return {
                "success": True,
                "board": _board_with_columns_to_dict(board),
            }
        else:
            board = service.get_board(board_id, org_id=org_id)
            return {
                "success": True,
                "board": _board_to_dict(board),
            }
    except BoardNotFoundError:
        return {
            "success": False,
            "error": f"Board {board_id} not found",
        }


def handle_update_board(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update board settings.

    MCP Tool: boards.update
    """
    board_id = arguments.get("board_id")
    org_id = arguments.get("org_id")

    _require(arguments, "board_id")

    actor = _get_actor(arguments)

    # Build update request
    request = UpdateBoardRequest(
        name=arguments.get("name"),
        description=arguments.get("description"),
        settings=arguments.get("settings"),
    )

    try:
        board = service.update_board(board_id, request, actor, org_id=org_id)
        return {
            "success": True,
            "board": _board_to_dict(board),
            "message": "Board updated successfully",
        }
    except BoardNotFoundError:
        return {
            "success": False,
            "error": f"Board {board_id} not found",
        }


def handle_delete_board(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete a board.

    MCP Tool: boards.delete
    """
    board_id = arguments.get("board_id")
    org_id = arguments.get("org_id")

    _require(arguments, "board_id")

    actor = _get_actor(arguments)

    try:
        result = service.delete_board(board_id, actor, org_id=org_id)
        return {
            "success": True,
            "board_id": board_id,
            "message": "Board deleted successfully",
        }
    except BoardNotFoundError:
        return {
            "success": False,
            "error": f"Board {board_id} not found",
        }


# ==============================================================================
# Work Item CRUD Handlers
# ==============================================================================


def handle_list_work_items(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List work items with filters.

    MCP Tool: workItems.list
    """
    board_id = arguments.get("board_id")
    project_id = arguments.get("project_id")
    org_id = arguments.get("org_id")
    limit = min(int(arguments.get("limit", 25)), 100)
    offset = arguments.get("offset", 0)
    brief = arguments.get("brief", True)

    # Parse optional filters
    item_type = None
    if arguments.get("item_type"):
        try:
            item_type = WorkItemType(arguments["item_type"])
        except ValueError:
            pass

    status = None
    if arguments.get("status"):
        try:
            status = WorkItemStatus(arguments["status"])
        except ValueError:
            pass

    parent_id = arguments.get("parent_id")
    if parent_id:
        try:
            parent_id = _resolve_id(service, parent_id, arguments)
        except WorkItemNotFoundError:
            return {
                "success": False,
                "error": f"Parent work item '{arguments.get('parent_id')}' not found",
            }

    title_search = arguments.get("title_search") or None
    text_search = arguments.get("text_search") or None

    items, total = service.list_work_items(
        project_id=project_id,
        board_id=board_id,
        item_type=item_type,
        status=status,
        parent_id=parent_id,
        title_search=title_search,
        text_search=text_search,
        org_id=org_id,
        limit=limit,
        offset=offset,
        include_total=True,
    )

    serializer = _work_item_summary_to_dict if brief else _work_item_to_dict

    return {
        "success": True,
        "items": [serializer(i) for i in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "brief": brief,
    }


def handle_create_work_item(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new work item (goal, feature, task, bug, or research).

    MCP Tool: workItems.create
    """
    item_type = arguments.get("item_type")
    project_id = arguments.get("project_id")
    title = arguments.get("title")
    org_id = arguments.get("org_id")

    _require(arguments, "item_type", "project_id", "title")

    actor = _get_actor(arguments)

    # Parse item_type enum — accept legacy 'epic'/'story' via normalize
    try:
        item_type_enum = WorkItemType(normalize_item_type(item_type))
    except ValueError:
        return {"success": False, "error": f"Invalid item_type: {item_type}. Must be goal, feature, task, bug, or research."}

    # GWS title validation is enforced by BoardService.create_work_item()

    # Parse priority
    priority = WorkItemPriority.MEDIUM
    if arguments.get("priority"):
        try:
            priority = WorkItemPriority(arguments["priority"])
        except ValueError:
            pass

    raw_parent_id = arguments.get("parent_id")
    parent_id = None
    if raw_parent_id:
        try:
            parent_id = _resolve_id(service, raw_parent_id, arguments)
        except WorkItemNotFoundError:
            return {
                "success": False,
                "error": f"Parent work item '{raw_parent_id}' not found",
            }

    request = CreateWorkItemRequest(
        item_type=item_type_enum,
        project_id=project_id,
        board_id=arguments.get("board_id"),
        column_id=arguments.get("column_id"),
        parent_id=parent_id,
        title=title,
        description=arguments.get("description"),
        priority=priority,
        labels=arguments.get("labels", []),
        story_points=_mcp_coalesce_points(arguments),
        estimated_hours=arguments.get("estimated_hours"),
        start_date=arguments.get("start_date"),
        target_date=arguments.get("target_date"),
        due_date=arguments.get("due_date"),
        behavior_id=arguments.get("behavior_id"),
        run_id=arguments.get("run_id"),
        research_url=arguments.get("research_url") or arguments.get("Research URL"),
        metadata=arguments.get("metadata", {}),
    )

    item = service.create_work_item(request, actor, org_id=org_id)
    brief = arguments.get("brief", True)

    return {
        "success": True,
        "item": _work_item_summary_to_dict(item) if brief else _work_item_to_dict(item),
        "message": f"{item_type.capitalize()} '{title}' created successfully",
        "brief": brief,
    }


def handle_get_work_item(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get work item details by ID.

    MCP Tool: workItems.get
    """
    raw_id = arguments.get("item_id")
    org_id = arguments.get("org_id")
    brief = arguments.get("brief", False)

    _require(arguments, "item_id")

    try:
        item_id = _resolve_id(service, raw_id, arguments)
        item = service.get_work_item(item_id, org_id=org_id)
        return {
            "success": True,
            "item": _work_item_summary_to_dict(item) if brief else _work_item_to_dict(item),
            "brief": brief,
        }
    except WorkItemNotFoundError:
        return {
            "success": False,
            "error": f"Work item {raw_id} not found",
        }


def handle_get_work_items_batch(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get multiple work items by IDs in a single call.

    MCP Tool: workItems.getBatch
    """
    raw_ids = arguments.get("item_ids", [])
    org_id = arguments.get("org_id")
    brief = arguments.get("brief", True)

    _require(arguments, "item_ids")

    if len(raw_ids) > 100:
        return {"success": False, "error": "Maximum 100 item_ids per batch request"}

    item_ids = [_resolve_id(service, rid, arguments) for rid in raw_ids]
    items = service.get_work_items_batch(item_ids, org_id=org_id)
    found_ids = {i.item_id for i in items}
    missing_ids = [iid for iid in item_ids if iid not in found_ids]

    return {
        "success": True,
        "items": [
            _work_item_summary_to_dict(i) if brief else _work_item_to_dict(i)
            for i in items
        ],
        "total": len(items),
        "missing_ids": missing_ids,
        "brief": brief,
    }


def handle_update_work_item(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update a work item.

    MCP Tool: workItems.update
    """
    raw_id = arguments.get("item_id")
    org_id = arguments.get("org_id")
    brief = arguments.get("brief", True)

    _require(arguments, "item_id")

    item_id = _resolve_id(service, raw_id, arguments)
    actor = _get_actor(arguments)

    # Parse optional status
    status = None
    if arguments.get("status"):
        try:
            status = WorkItemStatus(arguments["status"])
        except ValueError:
            pass

    # Parse optional priority
    priority = None
    if arguments.get("priority"):
        try:
            priority = WorkItemPriority(arguments["priority"])
        except ValueError:
            pass

    # cascade_to_children is accepted for API compatibility but ignored: mass-completing
    # descendants from MCP is too easy to misuse (e.g. accidental closure of full goal trees).
    _ = arguments.get("cascade_to_children", False)

    # Parse optional item_type
    item_type_enum = None
    if arguments.get("item_type"):
        try:
            item_type_enum = WorkItemType(normalize_item_type(arguments["item_type"]))
        except ValueError:
            return {"success": False, "error": f"Invalid item_type: {arguments['item_type']}. Must be goal, feature, task, bug, or research."}

    # GWS title validation is enforced by BoardService.update_work_item()

    # Resolve parent_id (supports display IDs like 'AMPREALIZE-42')
    _resolve_parent_id = None
    raw_parent_id = arguments.get("parent_id")
    if raw_parent_id:
        try:
            _resolve_parent_id = _resolve_id(service, raw_parent_id, arguments)
        except WorkItemNotFoundError:
            return {
                "success": False,
                "error": f"Parent work item '{raw_parent_id}' not found",
            }

    request = UpdateWorkItemRequest(
        item_type=item_type_enum,
        title=arguments.get("title"),
        description=arguments.get("description"),
        status=status,
        priority=priority,
        labels=arguments.get("labels"),
        story_points=_mcp_coalesce_points(arguments),
        estimated_hours=arguments.get("estimated_hours"),
        actual_hours=arguments.get("actual_hours"),
        start_date=arguments.get("start_date"),
        target_date=arguments.get("target_date"),
        due_date=arguments.get("due_date"),
        behavior_id=arguments.get("behavior_id"),
        run_id=arguments.get("run_id"),
        research_url=arguments.get("research_url") or arguments.get("Research URL"),
        metadata=arguments.get("metadata"),
        parent_id=_resolve_parent_id,
    )

    try:
        item = service.update_work_item(item_id, request, actor, org_id=org_id)
        return {
            "success": True,
            "item": _work_item_summary_to_dict(item) if brief else _work_item_to_dict(item),
            "message": "Work item updated successfully",
            "brief": brief,
        }
    except WorkItemNotFoundError:
        return {
            "success": False,
            "error": f"Work item {raw_id} not found",
        }


def handle_move_work_item(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    DEPRECATED: Adapter that delegates to handle_move_to_column.

    MCP Tool: workItems.move → workItems.moveToColumn

    Maps the legacy ``item_id`` parameter to ``work_item_id`` and forwards
    to the canonical handler.  Kept for backwards compatibility during the
    deprecation period.
    """
    # Adapt legacy param name: item_id → work_item_id
    adapted = dict(arguments)
    if "item_id" in adapted and "work_item_id" not in adapted:
        adapted["work_item_id"] = adapted.pop("item_id")
    return handle_move_to_column(service, adapted)


def handle_delete_work_item(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete a work item.

    MCP Tool: workItems.delete
    """
    raw_id = arguments.get("item_id")
    org_id = arguments.get("org_id")

    _require(arguments, "item_id")

    item_id = _resolve_id(service, raw_id, arguments)
    actor = _get_actor(arguments)

    try:
        result = service.delete_work_item(item_id, actor, org_id=org_id)
        return {
            "success": True,
            "deleted_id": result.deleted_id,
            "deleted_type": result.deleted_type,
            "cascade_deleted": result.cascade_deleted,
            "message": "Work item deleted successfully",
        }
    except WorkItemNotFoundError:
        return {
            "success": False,
            "error": f"Work item {raw_id} not found",
        }


# ==============================================================================
# Work Item Comment Handlers
# ==============================================================================


def handle_post_comment(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Post a comment on a work item.

    MCP Tool: workItems.postComment

    Arguments:
        work_item_id: ID of the work item to comment on
        body: Comment text content
        author_id: ID of the comment author (user or agent). Defaults from
            user_id or session user_id when omitted.
        author_type: "user" or "agent" (default: "user")
        run_id: Optional link to an execution run
        metadata: Optional JSON metadata
        org_id: Organization context
    """
    raw_id = arguments.get("work_item_id")
    body = arguments.get("body")
    session = arguments.get("_session", {})
    author_id = arguments.get("author_id") or arguments.get("user_id") or session.get("user_id")
    explicit_author_type = arguments.get("author_type")
    author_type = explicit_author_type or ("agent" if _looks_like_agent_author(arguments, author_id) else "user")
    run_id = arguments.get("run_id")
    metadata = arguments.get("metadata")
    org_id = arguments.get("org_id")

    # Validate required fields
    _require({"work_item_id": raw_id, "body": body, "author_id": author_id}, "work_item_id", "body", "author_id")
    if author_type not in ("user", "agent"):
        return {"success": False, "error": "author_type must be 'user' or 'agent'"}

    work_item_id = _resolve_id(service, raw_id, arguments)
    actor = _get_actor(arguments)

    try:
        comment = service.add_comment(
            work_item_id=work_item_id,
            author_id=author_id,
            author_type=author_type,
            content=body,
            actor=actor,
            run_id=run_id,
            metadata=metadata,
            org_id=org_id,
        )
        return {
            "success": True,
            "comment": comment,
            "message": "Comment posted successfully",
        }
    except WorkItemNotFoundError:
        return {
            "success": False,
            "error": f"Work item {raw_id} not found",
        }
    except AuthorNotFoundError as e:
        if not explicit_author_type and author_type == "user":
            try:
                comment = service.add_comment(
                    work_item_id=work_item_id,
                    author_id=author_id,
                    author_type="agent",
                    content=body,
                    actor=actor,
                    run_id=run_id,
                    metadata=metadata,
                    org_id=org_id,
                )
                return {
                    "success": True,
                    "comment": comment,
                    "message": "Comment posted successfully",
                }
            except AuthorNotFoundError as fallback_error:
                e = fallback_error
        return {
            "success": False,
            "error": str(e),
        }


def handle_list_comments(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List comments on a work item.

    MCP Tool: workItems.listComments

    Arguments:
        work_item_id: ID of the work item
        limit: Maximum number of comments to return (default: 50)
        offset: Number of comments to skip (default: 0)
        org_id: Organization context
    """
    raw_id = arguments.get("work_item_id")
    limit = arguments.get("limit", 50)
    offset = arguments.get("offset", 0)
    org_id = arguments.get("org_id")

    _require(arguments, "work_item_id")

    work_item_id = _resolve_id(service, raw_id, arguments)

    try:
        comments = service.list_comments(
            work_item_id=work_item_id,
            limit=limit,
            offset=offset,
            org_id=org_id,
        )
        return {
            "success": True,
            "comments": comments,
            "count": len(comments),
        }
    except WorkItemNotFoundError:
        return {
            "success": False,
            "error": f"Work item {raw_id} not found",
        }


def handle_move_to_column(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Move a work item to a column by column_id or status_mapping.

    MCP Tool: workItems.moveToColumn

    Arguments:
        work_item_id: ID of the work item to move
        column_id: Target column ID (optional if status_mapping provided)
        status_mapping: Target status (e.g., "backlog", "in_progress", "done") -
                       will find column with matching status_mapping
        position: Position in the target column (default: 0, top of column)
        org_id: Organization context

    Either column_id or status_mapping must be provided.
    If both provided, column_id takes precedence.
    """
    raw_id = arguments.get("work_item_id")
    column_id = arguments.get("column_id")
    status_mapping = arguments.get("status_mapping")
    position = arguments.get("position", 0)
    org_id = arguments.get("org_id")

    _require(arguments, "work_item_id")
    if not column_id and not status_mapping:
        raise BoardToolValidationError("Missing required parameter: column_id or status_mapping")

    work_item_id = _resolve_id(service, raw_id, arguments)
    actor = _get_actor(arguments)

    try:
        # If status_mapping provided and no column_id, resolve to column_id
        if status_mapping and not column_id:
            # Get the work item to find its board_id
            item = service.get_work_item(work_item_id, org_id=org_id)
            if not item.board_id:
                return {
                    "success": False,
                    "error": f"Work item {raw_id} has no board_id",
                }

            # Parse status_mapping to WorkItemStatus enum
            try:
                status_enum = WorkItemStatus(status_mapping)
            except ValueError:
                valid_statuses = [s.value for s in WorkItemStatus]
                return {
                    "success": False,
                    "error": f"Invalid status_mapping '{status_mapping}'. Valid values: {valid_statuses}",
                }

            # Find column with matching status_mapping
            column = service.get_column_by_status_mapping(
                board_id=item.board_id,
                status_mapping=status_enum,
                org_id=org_id,
            )
            if not column:
                return {
                    "success": False,
                    "error": f"No column found with status_mapping '{status_mapping}' on board {item.board_id}",
                }
            column_id = column.column_id

        # Move the work item
        request = MoveWorkItemRequest(
            column_id=column_id,
            position=position,
        )
        item = service.move_work_item(work_item_id, request, actor, org_id=org_id)
        return {
            "success": True,
            "item": _work_item_to_dict(item),
            "message": f"Work item moved to column {column_id}",
        }
    except WorkItemNotFoundError:
        return {
            "success": False,
            "error": f"Work item {raw_id} not found",
        }
    except ColumnNotFoundError as e:
        return {
            "success": False,
            "error": str(e),
        }


# ==============================================================================
# Column Handlers (progressive disclosure)
# ==============================================================================


def _column_to_dict(col: BoardColumn) -> Dict[str, Any]:
    """Convert BoardColumn Pydantic model to dict with serialized timestamps."""
    result = col.model_dump()
    return {k: _serialize_value(v) for k, v in result.items()}


def handle_create_column(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a column to an existing board (progressive disclosure).

    MCP Tool: columns.create
    """
    board_id = arguments.get("board_id")
    name = arguments.get("name")
    org_id = arguments.get("org_id")

    _require(arguments, "board_id", "name")

    status_mapping = arguments.get("status_mapping")
    _require(arguments, "status_mapping")

    try:
        status_enum = WorkItemStatus(status_mapping)
    except ValueError:
        valid = [s.value for s in WorkItemStatus]
        return {"success": False, "error": f"Invalid status_mapping '{status_mapping}'. Valid: {valid}"}

    actor = _get_actor(arguments)

    request = CreateColumnRequest(
        board_id=board_id,
        name=name,
        position=arguments.get("position", 0),
        status_mapping=status_enum,
        wip_limit=arguments.get("wip_limit"),
    )

    column = service.create_column(request, actor, org_id=org_id)

    return {
        "success": True,
        "column": _column_to_dict(column),
        "message": f"Column '{name}' added to board",
    }


def handle_list_columns(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List columns on a board.

    MCP Tool: columns.list
    """
    board_id = arguments.get("board_id")
    org_id = arguments.get("org_id")

    _require(arguments, "board_id")

    columns = service.list_columns(board_id, org_id=org_id)

    return {
        "success": True,
        "columns": [_column_to_dict(c) for c in columns],
        "total": len(columns),
    }


def handle_available_columns(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Show which columns/statuses can still be added to a board.

    MCP Tool: columns.available
    """
    board_id = arguments.get("board_id")
    org_id = arguments.get("org_id")

    _require(arguments, "board_id")

    columns = service.list_columns(board_id, org_id=org_id)
    existing_statuses = {c.status_mapping for c in columns if c.status_mapping}

    # All possible columns with suggested names and colors
    all_columns = {
        WorkItemStatus.BACKLOG: ("Backlog", "#6B7280"),
        WorkItemStatus.IN_PROGRESS: ("In Progress", "#F59E0B"),
        WorkItemStatus.IN_REVIEW: ("In Review", "#8B5CF6"),
        WorkItemStatus.DONE: ("Done", "#10B981"),
    }

    available = []
    for status, (name, color) in all_columns.items():
        if status not in existing_statuses:
            available.append({
                "status_mapping": status.value,
                "suggested_name": name,
                "suggested_color": color,
            })

    return {
        "success": True,
        "existing_columns": [_column_to_dict(c) for c in columns],
        "available_columns": available,
        "message": f"{len(available)} column(s) available to add" if available else "All columns already present",
    }


# ==============================================================================
# Handler Registry
# ==============================================================================


BOARD_HANDLERS = {
    "board.listLabels": handle_list_labels,
    "board.createLabel": handle_create_label,
    "board.updateLabel": handle_update_label,
    "board.deleteLabel": handle_delete_label,
    "board.filterItems": handle_filter_items,
    "board.suggestAgent": handle_suggest_agent,
    "boards.list": handle_list_boards,
    "boards.create": handle_create_board,
    "boards.get": handle_get_board,
    "boards.update": handle_update_board,
    "boards.delete": handle_delete_board,
}

COLUMN_HANDLERS = {
    "columns.create": handle_create_column,
    "columns.list": handle_list_columns,
    "columns.available": handle_available_columns,
}

WORK_ITEM_HANDLERS = {
    "workItems.list": handle_list_work_items,
    "workItems.create": handle_create_work_item,
    "workItems.get": handle_get_work_item,
    "workItems.getBatch": handle_get_work_items_batch,
    "workItems.update": handle_update_work_item,
    "workItems.move": handle_move_work_item,
    "workItems.delete": handle_delete_work_item,
    "workItems.postComment": handle_post_comment,
    "workItems.listComments": handle_list_comments,
    "workItems.moveToColumn": handle_move_to_column,
}
