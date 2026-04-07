"""MCP tool handlers for BoardService.

Provides handlers for board and work item management.
Following `behavior_prefer_mcp_tools` - MCP provides consistent schemas and automatic telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ...services.board_service import BoardService, Actor, BoardNotFoundError, WorkItemNotFoundError, WorkItemValidationError, ColumnNotFoundError, AuthorNotFoundError
from ...multi_tenant.board_contracts import (
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
    normalize_item_type,
)


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


def _get_actor(arguments: Dict[str, Any]) -> Actor:
    """Extract actor from arguments or create default."""
    user_id = arguments.get("user_id", "mcp-user")
    role = arguments.get("actor_role", "user")
    surface = arguments.get("actor_surface", "mcp")
    return Actor(id=user_id, role=role, surface=surface)


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

    if not project_id:
        return {
            "success": False,
            "error": "project_id is required",
        }

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

    if not project_id:
        return {"success": False, "error": "project_id is required"}
    if not name:
        return {"success": False, "error": "name is required"}

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

    if not board_id:
        return {"success": False, "error": "board_id is required"}

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

    if not board_id:
        return {"success": False, "error": "board_id is required"}

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

    if not board_id:
        return {"success": False, "error": "board_id is required"}

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
    limit = arguments.get("limit", 100)
    offset = arguments.get("offset", 0)

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

    items = service.list_work_items(
        project_id=project_id,
        board_id=board_id,
        item_type=item_type,
        status=status,
        parent_id=parent_id,
        org_id=org_id,
        limit=limit,
        offset=offset,
    )

    return {
        "success": True,
        "items": [_work_item_to_dict(i) for i in items],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }


def handle_create_work_item(
    service: BoardService,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new work item (goal, feature, task, or bug).

    MCP Tool: workItems.create
    """
    item_type = arguments.get("item_type")
    project_id = arguments.get("project_id")
    title = arguments.get("title")
    org_id = arguments.get("org_id")

    if not item_type:
        return {"success": False, "error": "item_type is required (goal, feature, task, or bug)"}
    if not project_id:
        return {"success": False, "error": "project_id is required"}
    if not title:
        return {"success": False, "error": "title is required"}

    actor = _get_actor(arguments)

    # Parse item_type enum — accept legacy 'epic'/'story' via normalize
    try:
        item_type_enum = WorkItemType(normalize_item_type(item_type))
    except ValueError:
        return {"success": False, "error": f"Invalid item_type: {item_type}. Must be goal, feature, task, or bug."}

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
        story_points=arguments.get("points") or arguments.get("story_points"),
        estimated_hours=arguments.get("estimated_hours"),
        start_date=arguments.get("start_date"),
        target_date=arguments.get("target_date"),
        due_date=arguments.get("due_date"),
        behavior_id=arguments.get("behavior_id"),
        run_id=arguments.get("run_id"),
        metadata=arguments.get("metadata", {}),
    )

    item = service.create_work_item(request, actor, org_id=org_id)

    return {
        "success": True,
        "item": _work_item_to_dict(item),
        "message": f"{item_type.capitalize()} '{title}' created successfully",
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

    if not raw_id:
        return {"success": False, "error": "item_id is required"}

    try:
        item_id = _resolve_id(service, raw_id, arguments)
        item = service.get_work_item(item_id, org_id=org_id)
        return {
            "success": True,
            "item": _work_item_to_dict(item),
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

    if not raw_ids:
        return {"success": False, "error": "item_ids is required and must be non-empty"}

    if len(raw_ids) > 100:
        return {"success": False, "error": "Maximum 100 item_ids per batch request"}

    item_ids = [_resolve_id(service, rid, arguments) for rid in raw_ids]
    items = service.get_work_items_batch(item_ids, org_id=org_id)
    found_ids = {i.item_id for i in items}
    missing_ids = [iid for iid in item_ids if iid not in found_ids]

    return {
        "success": True,
        "items": [_work_item_to_dict(i) for i in items],
        "total": len(items),
        "missing_ids": missing_ids,
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

    if not raw_id:
        return {"success": False, "error": "item_id is required"}

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
            return {"success": False, "error": f"Invalid item_type: {arguments['item_type']}. Must be goal, feature, task, or bug."}

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
        story_points=arguments.get("points") or arguments.get("story_points"),
        estimated_hours=arguments.get("estimated_hours"),
        actual_hours=arguments.get("actual_hours"),
        start_date=arguments.get("start_date"),
        target_date=arguments.get("target_date"),
        due_date=arguments.get("due_date"),
        behavior_id=arguments.get("behavior_id"),
        run_id=arguments.get("run_id"),
        metadata=arguments.get("metadata"),
        parent_id=_resolve_parent_id,
    )

    try:
        item = service.update_work_item(item_id, request, actor, org_id=org_id)
        return {
            "success": True,
            "item": _work_item_to_dict(item),
            "message": "Work item updated successfully",
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

    if not raw_id:
        return {"success": False, "error": "item_id is required"}

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
        author_id: ID of the comment author (user or agent)
        author_type: "user" or "agent" (default: "user")
        run_id: Optional link to an execution run
        metadata: Optional JSON metadata
        org_id: Organization context
    """
    raw_id = arguments.get("work_item_id")
    body = arguments.get("body")
    author_id = arguments.get("author_id")
    author_type = arguments.get("author_type", "user")
    run_id = arguments.get("run_id")
    metadata = arguments.get("metadata")
    org_id = arguments.get("org_id")

    # Validate required fields
    if not raw_id:
        return {"success": False, "error": "work_item_id is required"}
    if not body:
        return {"success": False, "error": "body is required"}
    if not author_id:
        return {"success": False, "error": "author_id is required"}
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

    if not raw_id:
        return {"success": False, "error": "work_item_id is required"}

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

    if not raw_id:
        return {"success": False, "error": "work_item_id is required"}
    if not column_id and not status_mapping:
        return {"success": False, "error": "Either column_id or status_mapping is required"}

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

    if not board_id:
        return {"success": False, "error": "board_id is required"}
    if not name:
        return {"success": False, "error": "name is required"}

    status_mapping = arguments.get("status_mapping")
    if not status_mapping:
        return {"success": False, "error": "status_mapping is required"}

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

    if not board_id:
        return {"success": False, "error": "board_id is required"}

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

    if not board_id:
        return {"success": False, "error": "board_id is required"}

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
