"""
Board Service - PostgreSQL-backed Agile Board management.

Provides CRUD for boards, columns, epics, stories, tasks, and sprints.
Supports polymorphic assignment (user/agent) and multi-tenant RLS.
Includes delete operations (soft/hard), assignment with event emission,
acceptance criteria management, and checklist operations.

Feature scope: 13.4.5 (Agent assignment to tasks) and 13.5.x Agile Board.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from amprealize.multi_tenant.board_contracts import (
    AcceptanceCriterion,
    AddAcceptanceCriterionRequest,
    AddAttachmentRequest,
    AddChecklistItemRequest,
    AssignAgentRequest,
    AssigneeType,
    AssignmentAction,
    AssignmentHistory,
    AssignUserRequest,
    Attachment,
    Board,
    BoardColumn,
    BoardEvent,
    BoardEventType,
    BoardWithColumns,
    ChecklistItem,
    CreateBoardRequest,
    CreateColumnRequest,
    CreateEpicRequest,
    CreateSprintRequest,
    CreateStoryRequest,
    CreateTaskRequest,
    DeleteAcceptanceCriterionRequest,
    DeleteChecklistItemRequest,
    DeleteEpicRequest,
    DeleteResult,
    DeleteStoryRequest,
    DeleteTaskRequest,
    Epic,
    EpicStatus,
    ListAssignmentHistoryRequest,
    ListAssignmentHistoryResponse,
    ListBoardsRequest,
    ListBoardsResponse,
    ListEpicsRequest,
    ListEpicsResponse,
    ListStoriesRequest,
    ListStoriesResponse,
    ListTasksRequest,
    ListTasksResponse,
    MoveStoryRequest,
    ReassignRequest,
    RemoveAttachmentRequest,
    Sprint,
    SprintStatus,
    Story,
    StoryWithTasks,
    Task,
    TaskType,
    ToggleChecklistItemRequest,
    ToggleCriterionCompleteRequest,
    UnassignRequest,
    UpdateAcceptanceCriterionRequest,
    UpdateBoardRequest,
    UpdateEpicRequest,
    UpdateSprintRequest,
    UpdateStoryRequest,
    UpdateTaskRequest,
    WorkItemPriority,
    WorkItemStatus,
    is_valid_epic_transition,
    is_valid_work_item_transition,
)
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.telemetry import TelemetryClient
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_BOARD_PG_DSN_ENV = "AMPREALIZE_BOARD_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"


def _now() -> datetime:
    """UTC now helper."""
    return datetime.now(timezone.utc)


def _short_id(prefix: str) -> str:
    """Generate short deterministic-looking IDs with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _parse_jsonb(value: Any, default: Any = None) -> Any:
    """Parse JSONB field that may already be decoded by psycopg2.

    Args:
        value: The JSONB value (may be str, dict, list, or None)
        default: Default value if value is None/empty

    Returns:
        Parsed JSON value or default
    """
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value  # Already parsed by psycopg2
    if isinstance(value, str):
        return json.loads(value) if value else (default if default is not None else {})
    return value


def _actor_payload(actor: "Actor") -> Dict[str, str]:
    return {"id": actor.id, "role": actor.role, "surface": actor.surface}


class Actor:
    """Represents the actor performing an operation."""

    def __init__(self, id: str, role: str = "user", surface: str = "api") -> None:
        self.id = id
        self.role = role
        self.surface = surface


class BoardServiceError(Exception):
    """Base exception for board service."""


class WorkItemTransitionError(BoardServiceError):
    """Raised for invalid status transitions."""


class BoardNotFoundError(BoardServiceError):
    """Raised when a board is not found."""


class EpicNotFoundError(BoardServiceError):
    """Raised when an epic is not found."""


class StoryNotFoundError(BoardServiceError):
    """Raised when a story is not found."""


class TaskNotFoundError(BoardServiceError):
    """Raised when a task is not found."""


class ColumnNotFoundError(BoardServiceError):
    """Raised when a board column is not found."""


class SprintNotFoundError(BoardServiceError):
    """Raised when a sprint is not found."""


class AssignmentHistoryNotFoundError(BoardServiceError):
    """Raised when assignment history is not found."""


class AcceptanceCriterionNotFoundError(BoardServiceError):
    """Raised when an acceptance criterion is not found."""


class ChecklistItemNotFoundError(BoardServiceError):
    """Raised when a checklist item is not found."""


class AttachmentNotFoundError(BoardServiceError):
    """Raised when an attachment is not found."""


# Event handler type for webhooks/notifications
BoardEventHandler = Callable[[BoardEvent], None]


class BoardService:
    """PostgreSQL-backed board service."""

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        telemetry: Optional[TelemetryClient] = None,
        event_handlers: Optional[List[BoardEventHandler]] = None,
    ) -> None:
        self._dsn = self._resolve_dsn(dsn)
        self._telemetry = telemetry or TelemetryClient.noop()
        self._pool = PostgresPool(self._dsn)
        self._event_handlers: List[BoardEventHandler] = event_handlers or []

    def register_event_handler(self, handler: BoardEventHandler) -> None:
        """Register an event handler for board events (webhooks/notifications)."""
        self._event_handlers.append(handler)

    def _emit_event(self, event: BoardEvent) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.warning(f"Event handler failed for {event.event_type}: {e}")

    # ------------------------------------------------------------------
    # Public API - Boards
    # ------------------------------------------------------------------

    def create_board(
        self,
        request: CreateBoardRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Board | BoardWithColumns:
        """Create a board and optional default columns."""
        board_id = _short_id("brd")
        timestamp = _now()
        settings = request.settings.dict() if request.settings else {}

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO boards (
                        board_id, project_id, name, description, settings,
                        created_at, updated_at, created_by, is_default, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        board_id,
                        request.project_id,
                        request.name,
                        request.description,
                        json.dumps(settings),
                        timestamp,
                        timestamp,
                        actor.id,
                        request.is_default,
                        org_id,
                    ),
                )

                if request.create_default_columns:
                    default_columns: List[Tuple[str, WorkItemStatus]] = [
                        ("Backlog", WorkItemStatus.BACKLOG),
                        ("In Progress", WorkItemStatus.IN_PROGRESS),
                        ("In Review", WorkItemStatus.IN_REVIEW),
                        ("Done", WorkItemStatus.DONE),
                    ]
                    for position, (name, status) in enumerate(default_columns):
                        column_id = _short_id("col")
                        cur.execute(
                            """
                            INSERT INTO board_columns (
                                column_id, board_id, name, position,
                                status_mapping, settings, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                column_id,
                                board_id,
                                name,
                                position,
                                status.value,
                                json.dumps({}),
                                timestamp,
                            ),
                        )

        self._pool.run_transaction(
            operation="board.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"board_id": board_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_board(board_id, include_columns=True, org_id=org_id)

    def update_board(
        self,
        board_id: str,
        request: UpdateBoardRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Board:
        """Update board metadata."""
        board = self.get_board(board_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates: List[str] = []
            values: List[Any] = []

            if request.name is not None:
                updates.append("name = %s")
                values.append(request.name)
            if request.description is not None:
                updates.append("description = %s")
                values.append(request.description)
            if request.settings is not None:
                updates.append("settings = %s")
                values.append(json.dumps(request.settings.dict()))
            if request.is_default is not None:
                updates.append("is_default = %s")
                values.append(request.is_default)

            if not updates:
                return

            updates.append("updated_at = %s")
            values.append(timestamp)
            values.append(board_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE boards SET {', '.join(updates)} WHERE board_id = %s",
                    values,
                )

        self._pool.run_transaction(
            operation="board.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"board_id": board_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_board(board_id, include_columns=True, org_id=org_id)

    def list_boards(
        self,
        request: ListBoardsRequest,
        *,
        org_id: Optional[str] = None,
    ) -> ListBoardsResponse:
        """List boards, optionally with columns."""
        conditions: List[str] = []
        params: List[Any] = []
        if request.project_id:
            conditions.append("project_id = %s")
            params.append(request.project_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_offset = "LIMIT %s OFFSET %s"
        params.extend([request.limit, request.offset])

        def _fetch(conn: Any) -> Tuple[List[Board], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM boards {where_clause} ORDER BY created_at DESC {limit_offset}",
                    params,
                )
                rows = cur.fetchall()
                boards = [self._row_to_board(r) for r in rows]

                cur.execute(f"SELECT COUNT(*) FROM boards {where_clause}", params[:-2])
                total = cur.fetchone()[0]
            return boards, total

        boards, total = self._pool.run_transaction(
            operation="board.list",
            service_prefix="board",
            actor=None,
            metadata={"project_id": request.project_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        if request.include_columns:
            boards_with_cols: List[Board | BoardWithColumns] = []
            for b in boards:
                cols = self._get_columns_for_board(b.board_id, org_id=org_id)
                boards_with_cols.append(BoardWithColumns(**b.model_dump(), columns=cols))
            boards_out = boards_with_cols
        else:
            boards_out = boards

        return ListBoardsResponse(boards=boards_out, total=total, limit=request.limit, offset=request.offset)

    def get_board(
        self,
        board_id: str,
        *,
        include_columns: bool = False,
        org_id: Optional[str] = None,
    ) -> Board | BoardWithColumns:
        """Fetch a board by id."""
        def _fetch(conn: Any) -> Board:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM boards WHERE board_id = %s", (board_id,))
                row = cur.fetchone()
                if not row:
                    raise BoardNotFoundError(f"Board not found: {board_id}")
                return self._row_to_board(row)

        board = self._pool.run_transaction(
            operation="board.get",
            service_prefix="board",
            actor=None,
            metadata={"board_id": board_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        if include_columns:
            cols = self._get_columns_for_board(board_id, org_id=org_id)
            return BoardWithColumns(**board.model_dump(), columns=cols)
        return board

    def create_column(
        self,
        request: CreateColumnRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> BoardColumn:
        column_id = _short_id("col")
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO board_columns (
                        column_id, board_id, name, position, status_mapping, wip_limit, settings, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        column_id,
                        request.board_id,
                        request.name,
                        request.position,
                        request.status_mapping.value,
                        request.wip_limit,
                        json.dumps({}),
                        timestamp,
                    ),
                )

        self._pool.run_transaction(
            operation="board.column.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"board_id": request.board_id, "column_id": column_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self._get_column(column_id, org_id=org_id)

    # ------------------------------------------------------------------
    # Epics
    # ------------------------------------------------------------------

    def create_epic(
        self,
        request: CreateEpicRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Epic:
        epic_id = _short_id("epic")
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO epics (
                        epic_id, project_id, board_id, name, description, status, priority,
                        color, start_date, target_date, labels, metadata,
                        created_at, updated_at, created_by, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        epic_id,
                        request.project_id,
                        request.board_id,
                        request.name,
                        request.description,
                        EpicStatus.DRAFT.value,
                        request.priority.value,
                        request.color,
                        request.start_date,
                        request.target_date,
                        json.dumps(request.labels),
                        json.dumps({}),
                        timestamp,
                        timestamp,
                        actor.id,
                        org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="epic.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"epic_id": epic_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_epic(epic_id, org_id=org_id)

    def update_epic(
        self,
        epic_id: str,
        request: UpdateEpicRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Epic:
        epic = self.get_epic(epic_id, org_id=org_id)
        if request.status and not is_valid_epic_transition(epic.status, request.status):
            raise WorkItemTransitionError(
                f"Invalid epic status transition {epic.status} -> {request.status}"
            )

        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates: List[str] = []
            values: List[Any] = []

            if request.name is not None:
                updates.append("name = %s")
                values.append(request.name)
            if request.description is not None:
                updates.append("description = %s")
                values.append(request.description)
            if request.status is not None:
                updates.append("status = %s")
                values.append(request.status.value)
            if request.priority is not None:
                updates.append("priority = %s")
                values.append(request.priority.value)
            if request.color is not None:
                updates.append("color = %s")
                values.append(request.color)
            if request.start_date is not None:
                updates.append("start_date = %s")
                values.append(request.start_date)
            if request.target_date is not None:
                updates.append("target_date = %s")
                values.append(request.target_date)
            if request.labels is not None:
                updates.append("labels = %s")
                values.append(json.dumps(request.labels))

            if not updates:
                return

            updates.append("updated_at = %s")
            values.append(timestamp)
            values.append(epic_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE epics SET {', '.join(updates)} WHERE epic_id = %s",
                    values,
                )

        self._pool.run_transaction(
            operation="epic.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"epic_id": epic_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_epic(epic_id, org_id=org_id)

    def list_epics(
        self,
        request: ListEpicsRequest,
        *,
        org_id: Optional[str] = None,
    ) -> ListEpicsResponse:
        conditions: List[str] = []
        params: List[Any] = []

        if request.project_id:
            conditions.append("project_id = %s")
            params.append(request.project_id)
        if request.board_id:
            conditions.append("board_id = %s")
            params.append(request.board_id)
        if request.status:
            conditions.append("status = ANY(%s)")
            params.append([s.value for s in request.status])

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_offset = "LIMIT %s OFFSET %s"
        params.extend([request.limit, request.offset])

        def _fetch(conn: Any) -> Tuple[List[Epic], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM epics {where_clause} ORDER BY created_at DESC {limit_offset}",
                    params,
                )
                rows = cur.fetchall()
                epics = [self._row_to_epic(r) for r in rows]

                cur.execute(f"SELECT COUNT(*) FROM epics {where_clause}", params[:-2])
                total = cur.fetchone()[0]
            return epics, total

        epics, total = self._pool.run_transaction(
            operation="epic.list",
            service_prefix="board",
            actor=None,
            metadata={"project_id": request.project_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        return ListEpicsResponse(epics=epics, total=total, limit=request.limit, offset=request.offset)

    def get_epic(self, epic_id: str, *, org_id: Optional[str] = None) -> Epic:
        def _fetch(conn: Any) -> Epic:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM epics WHERE epic_id = %s", (epic_id,))
                row = cur.fetchone()
                if not row:
                    raise EpicNotFoundError(f"Epic not found: {epic_id}")
                return self._row_to_epic(row)

        return self._pool.run_transaction(
            operation="epic.get",
            service_prefix="board",
            actor=None,
            metadata={"epic_id": epic_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Stories
    # ------------------------------------------------------------------

    def create_story(
        self,
        request: CreateStoryRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        story_id = _short_id("story")
        timestamp = _now()
        acceptance_list = [
            AcceptanceCriterion(id=_short_id("ac"), description=desc)
            for desc in request.acceptance_criteria
        ]

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO stories (
                        story_id, project_id, board_id, epic_id, column_id,
                        title, description, status, priority, story_points, position,
                        assignee_id, assignee_type, assigned_at, assigned_by,
                        started_at, completed_at, due_date,
                        labels, acceptance_criteria, metadata,
                        created_at, updated_at, created_by, org_id
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        NULL, NULL, NULL, NULL,
                        NULL, NULL, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        story_id,
                        request.project_id,
                        request.board_id,
                        request.epic_id,
                        request.column_id,
                        request.title,
                        request.description,
                        WorkItemStatus.BACKLOG.value,
                        request.priority.value,
                        request.story_points,
                        0,
                        request.due_date,
                        json.dumps(request.labels),
                        json.dumps([c.model_dump() for c in acceptance_list]),
                        json.dumps({}),
                        timestamp,
                        timestamp,
                        actor.id,
                        org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="story.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": story_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_story(story_id, org_id=org_id)

    def update_story(
        self,
        story_id: str,
        request: UpdateStoryRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        story = self.get_story(story_id, org_id=org_id)
        if request.status and not is_valid_work_item_transition(story.status, request.status):
            raise WorkItemTransitionError(
                f"Invalid story status transition {story.status} -> {request.status}"
            )

        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates: List[str] = []
            values: List[Any] = []

            if request.title is not None:
                updates.append("title = %s")
                values.append(request.title)
            if request.description is not None:
                updates.append("description = %s")
                values.append(request.description)
            if request.status is not None:
                updates.append("status = %s")
                values.append(request.status.value)
            if request.priority is not None:
                updates.append("priority = %s")
                values.append(request.priority.value)
            if request.story_points is not None:
                updates.append("story_points = %s")
                values.append(request.story_points)
            if request.column_id is not None:
                updates.append("column_id = %s")
                values.append(request.column_id)
            if request.epic_id is not None:
                updates.append("epic_id = %s")
                values.append(request.epic_id)
            if request.position is not None:
                updates.append("position = %s")
                values.append(request.position)
            if request.due_date is not None:
                updates.append("due_date = %s")
                values.append(request.due_date)
            if request.labels is not None:
                updates.append("labels = %s")
                values.append(json.dumps(request.labels))
            if request.acceptance_criteria is not None:
                updates.append("acceptance_criteria = %s")
                values.append(json.dumps([c.model_dump() for c in request.acceptance_criteria]))

            if not updates:
                return

            updates.append("updated_at = %s")
            values.append(timestamp)
            values.append(story_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE stories SET {', '.join(updates)} WHERE story_id = %s",
                    values,
                )

        self._pool.run_transaction(
            operation="story.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": story_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_story(story_id, org_id=org_id)

    def move_story(
        self,
        story_id: str,
        request: MoveStoryRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stories
                    SET column_id = %s, position = %s, updated_at = %s
                    WHERE story_id = %s
                    """,
                    (request.column_id, request.position, timestamp, story_id),
                )

        self._pool.run_transaction(
            operation="story.move",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": story_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_story(story_id, org_id=org_id)

    def list_stories(
        self,
        request: ListStoriesRequest,
        *,
        org_id: Optional[str] = None,
    ) -> ListStoriesResponse:
        conditions: List[str] = []
        params: List[Any] = []

        if request.project_id:
            conditions.append("project_id = %s")
            params.append(request.project_id)
        if request.board_id:
            conditions.append("board_id = %s")
            params.append(request.board_id)
        if request.epic_id:
            conditions.append("epic_id = %s")
            params.append(request.epic_id)
        if request.column_id:
            conditions.append("column_id = %s")
            params.append(request.column_id)
        if request.sprint_id:
            conditions.append("story_id IN (SELECT story_id FROM sprint_stories WHERE sprint_id = %s)")
            params.append(request.sprint_id)
        if request.status:
            conditions.append("status = ANY(%s)")
            params.append([s.value for s in request.status])
        if request.assignee_id:
            conditions.append("assignee_id = %s")
            params.append(request.assignee_id)
        if request.assignee_type:
            conditions.append("assignee_type = %s")
            params.append(request.assignee_type.value)
        if request.unassigned_only:
            conditions.append("assignee_id IS NULL")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_offset = "LIMIT %s OFFSET %s"
        params.extend([request.limit, request.offset])

        def _fetch(conn: Any) -> Tuple[List[Story], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM stories {where_clause} ORDER BY created_at DESC {limit_offset}",
                    params,
                )
                rows = cur.fetchall()
                stories = [self._row_to_story(r) for r in rows]

                cur.execute(f"SELECT COUNT(*) FROM stories {where_clause}", params[:-2])
                total = cur.fetchone()[0]
            return stories, total

        stories, total = self._pool.run_transaction(
            operation="story.list",
            service_prefix="board",
            actor=None,
            metadata={"project_id": request.project_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        if request.include_tasks:
            stories_with_tasks: List[Story | StoryWithTasks] = []
            for story in stories:
                tasks = self.list_tasks(
                    ListTasksRequest(story_id=story.story_id, limit=200),
                    org_id=org_id,
                ).tasks
                stories_with_tasks.append(StoryWithTasks(**story.model_dump(), tasks=tasks))
            stories_out = stories_with_tasks
        else:
            stories_out = stories

        return ListStoriesResponse(stories=stories_out, total=total, limit=request.limit, offset=request.offset)

    def get_story(self, story_id: str, *, org_id: Optional[str] = None) -> Story:
        def _fetch(conn: Any) -> Story:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM stories WHERE story_id = %s", (story_id,))
                row = cur.fetchone()
                if not row:
                    raise StoryNotFoundError(f"Story not found: {story_id}")
                return self._row_to_story(row)

        return self._pool.run_transaction(
            operation="story.get",
            service_prefix="board",
            actor=None,
            metadata={"story_id": story_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def create_task(
        self,
        request: CreateTaskRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        task_id = _short_id("task")
        timestamp = _now()
        column_id = getattr(request, "column_id", None)
        position = getattr(request, "position", 0) or 0
        checklist_items = [
            {"id": _short_id("chk"), "description": desc, "is_done": False}
            for desc in request.checklist
        ]

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO board_tasks (
                        task_id, project_id, story_id, board_id, column_id,
                        title, description, task_type, status, priority,
                        estimated_hours, actual_hours, position,
                        assignee_id, assignee_type, assigned_at, assigned_by,
                        started_at, completed_at, due_date,
                        behavior_id, run_id,
                        labels, checklist, metadata,
                        created_at, updated_at, created_by, org_id
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        task_id,
                        request.project_id,
                        request.story_id,
                        request.board_id,
                        column_id,
                        request.title,
                        request.description,
                        request.task_type.value,
                        WorkItemStatus.BACKLOG.value,
                        request.priority.value,
                        request.estimated_hours,
                        None,  # actual_hours
                        position,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        request.due_date,
                        request.behavior_id,
                        None,
                        json.dumps(request.labels),
                        json.dumps(checklist_items),
                        json.dumps({}),
                        timestamp,
                        timestamp,
                        actor.id,
                        org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="task.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": task_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_task(task_id, org_id=org_id)

    def update_task(
        self,
        task_id: str,
        request: UpdateTaskRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        task = self.get_task(task_id, org_id=org_id)
        if request.status and not is_valid_work_item_transition(task.status, request.status):
            raise WorkItemTransitionError(
                f"Invalid task status transition {task.status} -> {request.status}"
            )

        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates: List[str] = []
            values: List[Any] = []

            if request.title is not None:
                updates.append("title = %s")
                values.append(request.title)
            if request.description is not None:
                updates.append("description = %s")
                values.append(request.description)
            if request.task_type is not None:
                updates.append("task_type = %s")
                values.append(request.task_type.value)
            if request.status is not None:
                updates.append("status = %s")
                values.append(request.status.value)
            if request.priority is not None:
                updates.append("priority = %s")
                values.append(request.priority.value)
            if request.estimated_hours is not None:
                updates.append("estimated_hours = %s")
                values.append(request.estimated_hours)
            if request.actual_hours is not None:
                updates.append("actual_hours = %s")
                values.append(request.actual_hours)
            if request.column_id is not None:
                updates.append("column_id = %s")
                values.append(request.column_id)
            if request.story_id is not None:
                updates.append("story_id = %s")
                values.append(request.story_id)
            if request.position is not None:
                updates.append("position = %s")
                values.append(request.position)
            if request.due_date is not None:
                updates.append("due_date = %s")
                values.append(request.due_date)
            if request.labels is not None:
                updates.append("labels = %s")
                values.append(json.dumps(request.labels))
            if request.checklist is not None:
                updates.append("checklist = %s")
                values.append(json.dumps([item if isinstance(item, dict) else item.model_dump() for item in request.checklist]))
            if request.behavior_id is not None:
                updates.append("behavior_id = %s")
                values.append(request.behavior_id)
            if request.run_id is not None:
                updates.append("run_id = %s")
                values.append(request.run_id)

            if not updates:
                return

            updates.append("updated_at = %s")
            values.append(timestamp)
            values.append(task_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE board_tasks SET {', '.join(updates)} WHERE task_id = %s",
                    values,
                )

        self._pool.run_transaction(
            operation="task.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": task_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_task(task_id, org_id=org_id)

    def list_tasks(
        self,
        request: ListTasksRequest,
        *,
        org_id: Optional[str] = None,
    ) -> ListTasksResponse:
        conditions: List[str] = []
        params: List[Any] = []

        if request.project_id:
            conditions.append("project_id = %s")
            params.append(request.project_id)
        if request.story_id:
            conditions.append("story_id = %s")
            params.append(request.story_id)
        if request.board_id:
            conditions.append("board_id = %s")
            params.append(request.board_id)
        if request.status:
            conditions.append("status = ANY(%s)")
            params.append([s.value for s in request.status])
        if request.task_type:
            conditions.append("task_type = ANY(%s)")
            params.append([t.value for t in request.task_type])
        if request.assignee_id:
            conditions.append("assignee_id = %s")
            params.append(request.assignee_id)
        if request.assignee_type:
            conditions.append("assignee_type = %s")
            params.append(request.assignee_type.value)
        if request.unassigned_only:
            conditions.append("assignee_id IS NULL")
        if request.behavior_id:
            conditions.append("behavior_id = %s")
            params.append(request.behavior_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_offset = "LIMIT %s OFFSET %s"
        params.extend([request.limit, request.offset])

        def _fetch(conn: Any) -> Tuple[List[Task], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM board_tasks {where_clause} ORDER BY created_at DESC {limit_offset}",
                    params,
                )
                rows = cur.fetchall()
                tasks = [self._row_to_task(r) for r in rows]

                cur.execute(f"SELECT COUNT(*) FROM board_tasks {where_clause}", params[:-2])
                total = cur.fetchone()[0]
            return tasks, total

        tasks, total = self._pool.run_transaction(
            operation="task.list",
            service_prefix="board",
            actor=None,
            metadata={"project_id": request.project_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        return ListTasksResponse(tasks=tasks, total=total, limit=request.limit, offset=request.offset)

    def get_task(self, task_id: str, *, org_id: Optional[str] = None) -> Task:
        def _fetch(conn: Any) -> Task:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM board_tasks WHERE task_id = %s", (task_id,))
                row = cur.fetchone()
                if not row:
                    raise TaskNotFoundError(f"Task not found: {task_id}")
                return self._row_to_task(row)

        return self._pool.run_transaction(
            operation="task.get",
            service_prefix="board",
            actor=None,
            metadata={"task_id": task_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Sprints (minimal support for listing)
    # ------------------------------------------------------------------

    def create_sprint(
        self,
        request: CreateSprintRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Sprint:
        sprint_id = _short_id("sprint")
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sprints (
                        sprint_id, project_id, board_id, name, goal, status,
                        start_date, end_date, velocity_planned, velocity_completed,
                        metadata, created_at, updated_at, created_by, org_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'planning',
                        %s, %s, %s, NULL,
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        sprint_id,
                        request.project_id,
                        request.board_id,
                        request.name,
                        request.goal,
                        request.start_date,
                        request.end_date,
                        request.velocity_planned,
                        json.dumps({}),
                        timestamp,
                        timestamp,
                        actor.id,
                        org_id,
                    ),
                )

                if request.story_ids:
                    for story_id in request.story_ids:
                        cur.execute(
                            """
                            INSERT INTO sprint_stories (sprint_id, story_id, added_at, added_by)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (sprint_id, story_id, timestamp, actor.id),
                        )

        self._pool.run_transaction(
            operation="sprint.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"sprint_id": sprint_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_sprint(sprint_id, org_id=org_id)

    def update_sprint(
        self,
        sprint_id: str,
        request: UpdateSprintRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Sprint:
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates: List[str] = []
            values: List[Any] = []

            if request.name is not None:
                updates.append("name = %s")
                values.append(request.name)
            if request.goal is not None:
                updates.append("goal = %s")
                values.append(request.goal)
            if request.status is not None:
                updates.append("status = %s")
                values.append(request.status.value)
            if request.start_date is not None:
                updates.append("start_date = %s")
                values.append(request.start_date)
            if request.end_date is not None:
                updates.append("end_date = %s")
                values.append(request.end_date)
            if request.velocity_planned is not None:
                updates.append("velocity_planned = %s")
                values.append(request.velocity_planned)
            if request.velocity_completed is not None:
                updates.append("velocity_completed = %s")
                values.append(request.velocity_completed)

            if not updates:
                return

            updates.append("updated_at = %s")
            values.append(timestamp)
            values.append(sprint_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE sprints SET {', '.join(updates)} WHERE sprint_id = %s",
                    values,
                )

        self._pool.run_transaction(
            operation="sprint.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"sprint_id": sprint_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_sprint(sprint_id, org_id=org_id)

    def get_sprint(self, sprint_id: str, *, org_id: Optional[str] = None) -> Sprint:
        def _fetch(conn: Any) -> Sprint:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sprints WHERE sprint_id = %s", (sprint_id,))
                row = cur.fetchone()
                if not row:
                    raise SprintNotFoundError(f"Sprint not found: {sprint_id}")
                return self._row_to_sprint(row)

        return self._pool.run_transaction(
            operation="sprint.get",
            service_prefix="board",
            actor=None,
            metadata={"sprint_id": sprint_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Delete Operations (soft-delete by default, hard-delete optional)
    # ------------------------------------------------------------------

    def delete_epic(
        self,
        epic_id: str,
        request: DeleteEpicRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> DeleteResult:
        """Delete an epic. Soft-delete (status→cancelled) by default."""
        epic = self.get_epic(epic_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if request.hard_delete:
                    cur.execute("DELETE FROM epics WHERE epic_id = %s", (epic_id,))
                else:
                    cur.execute(
                        "UPDATE epics SET status = %s, updated_at = %s WHERE epic_id = %s",
                        (EpicStatus.CANCELLED.value, timestamp, epic_id),
                    )

        self._pool.run_transaction(
            operation="epic.delete",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"epic_id": epic_id, "hard_delete": request.hard_delete},
            executor=_execute,
            telemetry=self._telemetry,
        )

        # Emit event
        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.EPIC_DELETED,
            entity_id=epic_id,
            entity_type="epic",
            project_id=epic.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={"hard_deleted": request.hard_delete, "reason": request.reason},
        ))

        return DeleteResult(
            id=epic_id,
            entity_type="epic",
            deleted=True,
            hard_deleted=request.hard_delete,
            deleted_at=timestamp,
            deleted_by=actor.id,
            reason=request.reason,
        )

    def delete_story(
        self,
        story_id: str,
        request: DeleteStoryRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> DeleteResult:
        """Delete a story. Soft-delete (status→done) by default."""
        story = self.get_story(story_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if request.hard_delete:
                    cur.execute("DELETE FROM stories WHERE story_id = %s", (story_id,))
                else:
                    cur.execute(
                        "UPDATE stories SET status = %s, updated_at = %s WHERE story_id = %s",
                        (WorkItemStatus.DONE.value, timestamp, story_id),
                    )

        self._pool.run_transaction(
            operation="story.delete",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": story_id, "hard_delete": request.hard_delete},
            executor=_execute,
            telemetry=self._telemetry,
        )

        # Emit event
        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.STORY_DELETED,
            entity_id=story_id,
            entity_type="story",
            project_id=story.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={"hard_deleted": request.hard_delete, "reason": request.reason},
        ))

        return DeleteResult(
            id=story_id,
            entity_type="story",
            deleted=True,
            hard_deleted=request.hard_delete,
            deleted_at=timestamp,
            deleted_by=actor.id,
            reason=request.reason,
        )

    def delete_task(
        self,
        task_id: str,
        request: DeleteTaskRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> DeleteResult:
        """Delete a task. Soft-delete (status→done) by default."""
        task = self.get_task(task_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if request.hard_delete:
                    cur.execute("DELETE FROM board_tasks WHERE task_id = %s", (task_id,))
                else:
                    cur.execute(
                        "UPDATE board_tasks SET status = %s, updated_at = %s WHERE task_id = %s",
                        (WorkItemStatus.DONE.value, timestamp, task_id),
                    )

        self._pool.run_transaction(
            operation="task.delete",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": task_id, "hard_delete": request.hard_delete},
            executor=_execute,
            telemetry=self._telemetry,
        )

        # Emit event
        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.TASK_DELETED,
            entity_id=task_id,
            entity_type="task",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={"hard_deleted": request.hard_delete, "reason": request.reason},
        ))

        return DeleteResult(
            id=task_id,
            entity_type="task",
            deleted=True,
            hard_deleted=request.hard_delete,
            deleted_at=timestamp,
            deleted_by=actor.id,
            reason=request.reason,
        )

    # ------------------------------------------------------------------
    # Assignment Operations
    # ------------------------------------------------------------------

    def assign_story_to_user(
        self,
        request: AssignUserRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Assign a story to a user. Emits STORY_ASSIGNED event."""
        story = self.get_story(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = story.assignee_id
        previous_assignee_type = story.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Update story
                cur.execute(
                    """
                    UPDATE stories
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE story_id = %s
                    """,
                    (request.user_id, AssigneeType.USER.value, timestamp, actor.id, timestamp, request.assignable_id),
                )
                # Record assignment history
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "story", request.user_id, AssigneeType.USER.value,
                        AssignmentAction.ASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="story.assign_user",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.assignable_id, "user_id": request.user_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        # Emit event
        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.STORY_ASSIGNED,
            entity_id=request.assignable_id,
            entity_type="story",
            project_id=story.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user",
            timestamp=timestamp,
            payload={
                "assignee_id": request.user_id,
                "assignee_type": "user",
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_story(request.assignable_id, org_id=org_id)

    def assign_story_to_agent(
        self,
        request: AssignAgentRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Assign a story to an agent. Emits STORY_ASSIGNED event."""
        story = self.get_story(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = story.assignee_id
        previous_assignee_type = story.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stories
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE story_id = %s
                    """,
                    (request.agent_id, AssigneeType.AGENT.value, timestamp, actor.id, timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "story", request.agent_id, AssigneeType.AGENT.value,
                        AssignmentAction.ASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="story.assign_agent",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.assignable_id, "agent_id": request.agent_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.STORY_ASSIGNED,
            entity_id=request.assignable_id,
            entity_type="story",
            project_id=story.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={
                "assignee_id": request.agent_id,
                "assignee_type": "agent",
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_story(request.assignable_id, org_id=org_id)

    def unassign_story(
        self,
        request: UnassignRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Unassign a story from its current assignee. Emits STORY_UNASSIGNED event."""
        story = self.get_story(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = story.assignee_id
        previous_assignee_type = story.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stories
                    SET assignee_id = NULL, assignee_type = NULL, assigned_at = NULL, assigned_by = NULL, updated_at = %s
                    WHERE story_id = %s
                    """,
                    (timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "story", None, None,
                        AssignmentAction.UNASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="story.unassign",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.assignable_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.STORY_UNASSIGNED,
            entity_id=request.assignable_id,
            entity_type="story",
            project_id=story.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_story(request.assignable_id, org_id=org_id)

    def reassign_story(
        self,
        request: ReassignRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Reassign a story to a different user/agent. Emits STORY_REASSIGNED event."""
        story = self.get_story(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = story.assignee_id
        previous_assignee_type = story.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stories
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE story_id = %s
                    """,
                    (request.new_assignee_id, request.new_assignee_type.value, timestamp, actor.id, timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "story", request.new_assignee_id, request.new_assignee_type.value,
                        AssignmentAction.REASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="story.reassign",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.assignable_id, "new_assignee_id": request.new_assignee_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.STORY_REASSIGNED,
            entity_id=request.assignable_id,
            entity_type="story",
            project_id=story.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={
                "assignee_id": request.new_assignee_id,
                "assignee_type": request.new_assignee_type.value,
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_story(request.assignable_id, org_id=org_id)

    def assign_task_to_user(
        self,
        request: AssignUserRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Assign a task to a user. Emits TASK_ASSIGNED event."""
        task = self.get_task(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = task.assignee_id
        previous_assignee_type = task.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE board_tasks
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE task_id = %s
                    """,
                    (request.user_id, AssigneeType.USER.value, timestamp, actor.id, timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "task", request.user_id, AssigneeType.USER.value,
                        AssignmentAction.ASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="task.assign_user",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.assignable_id, "user_id": request.user_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.TASK_ASSIGNED,
            entity_id=request.assignable_id,
            entity_type="task",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user",
            timestamp=timestamp,
            payload={
                "assignee_id": request.user_id,
                "assignee_type": "user",
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_task(request.assignable_id, org_id=org_id)

    def assign_task_to_agent(
        self,
        request: AssignAgentRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Assign a task to an agent. Emits TASK_ASSIGNED event."""
        task = self.get_task(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = task.assignee_id
        previous_assignee_type = task.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE board_tasks
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE task_id = %s
                    """,
                    (request.agent_id, AssigneeType.AGENT.value, timestamp, actor.id, timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "task", request.agent_id, AssigneeType.AGENT.value,
                        AssignmentAction.ASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="task.assign_agent",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.assignable_id, "agent_id": request.agent_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.TASK_ASSIGNED,
            entity_id=request.assignable_id,
            entity_type="task",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={
                "assignee_id": request.agent_id,
                "assignee_type": "agent",
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_task(request.assignable_id, org_id=org_id)

    def unassign_task(
        self,
        request: UnassignRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Unassign a task from its current assignee. Emits TASK_UNASSIGNED event."""
        task = self.get_task(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = task.assignee_id
        previous_assignee_type = task.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE board_tasks
                    SET assignee_id = NULL, assignee_type = NULL, assigned_at = NULL, assigned_by = NULL, updated_at = %s
                    WHERE task_id = %s
                    """,
                    (timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "task", None, None,
                        AssignmentAction.UNASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="task.unassign",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.assignable_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.TASK_UNASSIGNED,
            entity_id=request.assignable_id,
            entity_type="task",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_task(request.assignable_id, org_id=org_id)

    def reassign_task(
        self,
        request: ReassignRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Reassign a task to a different user/agent. Emits TASK_REASSIGNED event."""
        task = self.get_task(request.assignable_id, org_id=org_id)
        timestamp = _now()
        previous_assignee_id = task.assignee_id
        previous_assignee_type = task.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE board_tasks
                    SET assignee_id = %s, assignee_type = %s, assigned_at = %s, assigned_by = %s, updated_at = %s
                    WHERE task_id = %s
                    """,
                    (request.new_assignee_id, request.new_assignee_type.value, timestamp, actor.id, timestamp, request.assignable_id),
                )
                history_id = _short_id("ahist")
                cur.execute(
                    """
                    INSERT INTO assignment_history (
                        history_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at,
                        previous_assignee_id, previous_assignee_type, reason, metadata, org_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_id, request.assignable_id, "task", request.new_assignee_id, request.new_assignee_type.value,
                        AssignmentAction.REASSIGNED.value, actor.id, timestamp,
                        previous_assignee_id, previous_assignee_type.value if previous_assignee_type else None,
                        request.reason, json.dumps({}), org_id,
                    ),
                )

        self._pool.run_transaction(
            operation="task.reassign",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.assignable_id, "new_assignee_id": request.new_assignee_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.TASK_REASSIGNED,
            entity_id=request.assignable_id,
            entity_type="task",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={
                "assignee_id": request.new_assignee_id,
                "assignee_type": request.new_assignee_type.value,
                "previous_assignee_id": previous_assignee_id,
                "previous_assignee_type": previous_assignee_type.value if previous_assignee_type else None,
                "reason": request.reason,
            },
        ))

        return self.get_task(request.assignable_id, org_id=org_id)

    def list_assignment_history(
        self,
        request: ListAssignmentHistoryRequest,
        *,
        org_id: Optional[str] = None,
    ) -> ListAssignmentHistoryResponse:
        """List assignment history for a story or task."""
        def _fetch(conn: Any) -> Tuple[List[AssignmentHistory], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM assignment_history
                    WHERE assignable_id = %s AND assignable_type = %s
                    ORDER BY performed_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (request.assignable_id, request.assignable_type, request.limit, request.offset),
                )
                rows = cur.fetchall()
                history = [self._row_to_assignment_history(r) for r in rows]

                cur.execute(
                    "SELECT COUNT(*) FROM assignment_history WHERE assignable_id = %s AND assignable_type = %s",
                    (request.assignable_id, request.assignable_type),
                )
                total = cur.fetchone()[0]
            return history, total

        history, total = self._pool.run_transaction(
            operation="assignment_history.list",
            service_prefix="board",
            actor=None,
            metadata={"assignable_id": request.assignable_id},
            executor=_fetch,
            telemetry=self._telemetry,
        )

        return ListAssignmentHistoryResponse(history=history, total=total, limit=request.limit, offset=request.offset)

    # ------------------------------------------------------------------
    # Acceptance Criteria Operations
    # ------------------------------------------------------------------

    def add_acceptance_criterion(
        self,
        request: AddAcceptanceCriterionRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Add an acceptance criterion to a story."""
        story = self.get_story(request.story_id, org_id=org_id)
        timestamp = _now()
        criterion_id = _short_id("ac")
        new_criterion = AcceptanceCriterion(id=criterion_id, description=request.description)
        updated_criteria = story.acceptance_criteria + [new_criterion]

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE stories SET acceptance_criteria = %s, updated_at = %s WHERE story_id = %s",
                    (json.dumps([c.model_dump() for c in updated_criteria]), timestamp, request.story_id),
                )

        self._pool.run_transaction(
            operation="story.add_criterion",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.story_id, "criterion_id": criterion_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.CRITERION_ADDED,
            entity_id=criterion_id,
            entity_type="criterion",
            project_id=story.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={"story_id": request.story_id, "description": request.description},
        ))

        return self.get_story(request.story_id, org_id=org_id)

    def update_acceptance_criterion(
        self,
        request: UpdateAcceptanceCriterionRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Update an acceptance criterion."""
        story = self.get_story(request.story_id, org_id=org_id)
        timestamp = _now()

        updated_criteria = []
        found = False
        old_is_met = None
        for c in story.acceptance_criteria:
            if c.id == request.criterion_id:
                found = True
                old_is_met = c.is_met
                updated_c = AcceptanceCriterion(
                    id=c.id,
                    description=request.description if request.description is not None else c.description,
                    is_met=request.is_met if request.is_met is not None else c.is_met,
                    verified_by=actor.id if request.is_met else c.verified_by,
                    verified_at=timestamp if request.is_met else c.verified_at,
                )
                updated_criteria.append(updated_c)
            else:
                updated_criteria.append(c)

        if not found:
            raise AcceptanceCriterionNotFoundError(f"Criterion not found: {request.criterion_id}")

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE stories SET acceptance_criteria = %s, updated_at = %s WHERE story_id = %s",
                    (json.dumps([c.model_dump() for c in updated_criteria]), timestamp, request.story_id),
                )

        self._pool.run_transaction(
            operation="story.update_criterion",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.story_id, "criterion_id": request.criterion_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        # Emit event if is_met changed
        if request.is_met is not None and request.is_met != old_is_met:
            event_type = BoardEventType.CRITERION_MET if request.is_met else BoardEventType.CRITERION_UNMET
            self._emit_event(BoardEvent(
                event_id=_short_id("bevt"),
                event_type=event_type,
                entity_id=request.criterion_id,
                entity_type="criterion",
                project_id=story.project_id,
                org_id=org_id,
                actor_id=actor.id,
                actor_type="user" if actor.role == "user" else "agent",
                timestamp=timestamp,
                payload={"story_id": request.story_id},
            ))

        return self.get_story(request.story_id, org_id=org_id)

    def toggle_criterion_complete(
        self,
        request: ToggleCriterionCompleteRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Toggle an acceptance criterion's completion status."""
        story = self.get_story(request.story_id, org_id=org_id)
        criterion = next((c for c in story.acceptance_criteria if c.id == request.criterion_id), None)
        if not criterion:
            raise AcceptanceCriterionNotFoundError(f"Criterion not found: {request.criterion_id}")

        return self.update_acceptance_criterion(
            UpdateAcceptanceCriterionRequest(
                story_id=request.story_id,
                criterion_id=request.criterion_id,
                is_met=not criterion.is_met,
            ),
            actor,
            org_id=org_id,
        )

    def delete_acceptance_criterion(
        self,
        request: DeleteAcceptanceCriterionRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        """Delete an acceptance criterion from a story."""
        story = self.get_story(request.story_id, org_id=org_id)
        timestamp = _now()

        updated_criteria = [c for c in story.acceptance_criteria if c.id != request.criterion_id]
        if len(updated_criteria) == len(story.acceptance_criteria):
            raise AcceptanceCriterionNotFoundError(f"Criterion not found: {request.criterion_id}")

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE stories SET acceptance_criteria = %s, updated_at = %s WHERE story_id = %s",
                    (json.dumps([c.model_dump() for c in updated_criteria]), timestamp, request.story_id),
                )

        self._pool.run_transaction(
            operation="story.delete_criterion",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"story_id": request.story_id, "criterion_id": request.criterion_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_story(request.story_id, org_id=org_id)

    # ------------------------------------------------------------------
    # Checklist Operations
    # ------------------------------------------------------------------

    def add_checklist_item(
        self,
        request: AddChecklistItemRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Add a checklist item to a task."""
        task = self.get_task(request.task_id, org_id=org_id)
        timestamp = _now()
        item_id = _short_id("chk")
        new_item = ChecklistItem(id=item_id, description=request.description)
        # Convert existing checklist items to ChecklistItem if they're dicts
        existing_items = [
            ChecklistItem(**item) if isinstance(item, dict) else item
            for item in task.checklist
        ]
        updated_checklist = existing_items + [new_item]

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE board_tasks SET checklist = %s, updated_at = %s WHERE task_id = %s",
                    (json.dumps([item.model_dump() if hasattr(item, 'model_dump') else item for item in updated_checklist]), timestamp, request.task_id),
                )

        self._pool.run_transaction(
            operation="task.add_checklist_item",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.task_id, "item_id": item_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=BoardEventType.CHECKLIST_ITEM_ADDED,
            entity_id=item_id,
            entity_type="checklist_item",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={"task_id": request.task_id, "description": request.description},
        ))

        return self.get_task(request.task_id, org_id=org_id)

    def toggle_checklist_item(
        self,
        request: ToggleChecklistItemRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Toggle a checklist item's completion status."""
        task = self.get_task(request.task_id, org_id=org_id)
        timestamp = _now()

        updated_checklist = []
        found = False
        old_is_done = None
        for item in task.checklist:
            item_dict = item if isinstance(item, dict) else item.model_dump() if hasattr(item, 'model_dump') else item
            if item_dict.get("id") == request.item_id:
                found = True
                old_is_done = item_dict.get("is_done", False)
                updated_checklist.append({
                    **item_dict,
                    "is_done": not old_is_done,
                    "completed_by": actor.id if not old_is_done else None,
                    "completed_at": timestamp.isoformat() if not old_is_done else None,
                })
            else:
                updated_checklist.append(item_dict)

        if not found:
            raise ChecklistItemNotFoundError(f"Checklist item not found: {request.item_id}")

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE board_tasks SET checklist = %s, updated_at = %s WHERE task_id = %s",
                    (json.dumps(updated_checklist), timestamp, request.task_id),
                )

        self._pool.run_transaction(
            operation="task.toggle_checklist_item",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.task_id, "item_id": request.item_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        event_type = BoardEventType.CHECKLIST_ITEM_COMPLETED if not old_is_done else BoardEventType.CHECKLIST_ITEM_UNCOMPLETED
        self._emit_event(BoardEvent(
            event_id=_short_id("bevt"),
            event_type=event_type,
            entity_id=request.item_id,
            entity_type="checklist_item",
            project_id=task.project_id,
            org_id=org_id,
            actor_id=actor.id,
            actor_type="user" if actor.role == "user" else "agent",
            timestamp=timestamp,
            payload={"task_id": request.task_id},
        ))

        return self.get_task(request.task_id, org_id=org_id)

    def delete_checklist_item(
        self,
        request: DeleteChecklistItemRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        """Delete a checklist item from a task."""
        task = self.get_task(request.task_id, org_id=org_id)
        timestamp = _now()

        updated_checklist = []
        found = False
        for item in task.checklist:
            item_dict = item if isinstance(item, dict) else item.model_dump() if hasattr(item, 'model_dump') else item
            if item_dict.get("id") == request.item_id:
                found = True
            else:
                updated_checklist.append(item_dict)

        if not found:
            raise ChecklistItemNotFoundError(f"Checklist item not found: {request.item_id}")

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE board_tasks SET checklist = %s, updated_at = %s WHERE task_id = %s",
                    (json.dumps(updated_checklist), timestamp, request.task_id),
                )

        self._pool.run_transaction(
            operation="task.delete_checklist_item",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"task_id": request.task_id, "item_id": request.item_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        return self.get_task(request.task_id, org_id=org_id)

    # ------------------------------------------------------------------
    # Attachment Operations (URL placeholders - actual storage deferred)
    # ------------------------------------------------------------------

    def add_attachment(
        self,
        request: AddAttachmentRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story | Task:
        """Add an attachment to a story or task (URL placeholder only)."""
        timestamp = _now()
        attachment_id = _short_id("att")

        if request.entity_type == "story":
            entity = self.get_story(request.entity_id, org_id=org_id)
            metadata = entity.metadata or {}
        else:
            entity = self.get_task(request.entity_id, org_id=org_id)
            metadata = entity.metadata or {}

        attachments = metadata.get("attachments", [])
        new_attachment = Attachment(
            id=attachment_id,
            filename=request.filename,
            url=request.url,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            uploaded_by=actor.id,
            uploaded_at=timestamp,
        )
        attachments.append(new_attachment.model_dump())
        metadata["attachments"] = attachments

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if request.entity_type == "story":
                    cur.execute(
                        "UPDATE stories SET metadata = %s, updated_at = %s WHERE story_id = %s",
                        (json.dumps(metadata), timestamp, request.entity_id),
                    )
                else:
                    cur.execute(
                        "UPDATE board_tasks SET metadata = %s, updated_at = %s WHERE task_id = %s",
                        (json.dumps(metadata), timestamp, request.entity_id),
                    )

        self._pool.run_transaction(
            operation=f"{request.entity_type}.add_attachment",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"entity_id": request.entity_id, "attachment_id": attachment_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        if request.entity_type == "story":
            return self.get_story(request.entity_id, org_id=org_id)
        return self.get_task(request.entity_id, org_id=org_id)

    def remove_attachment(
        self,
        request: RemoveAttachmentRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story | Task:
        """Remove an attachment from a story or task."""
        timestamp = _now()

        if request.entity_type == "story":
            entity = self.get_story(request.entity_id, org_id=org_id)
            metadata = entity.metadata or {}
        else:
            entity = self.get_task(request.entity_id, org_id=org_id)
            metadata = entity.metadata or {}

        attachments = metadata.get("attachments", [])
        updated_attachments = [a for a in attachments if a.get("id") != request.attachment_id]

        if len(updated_attachments) == len(attachments):
            raise AttachmentNotFoundError(f"Attachment not found: {request.attachment_id}")

        metadata["attachments"] = updated_attachments

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if request.entity_type == "story":
                    cur.execute(
                        "UPDATE stories SET metadata = %s, updated_at = %s WHERE story_id = %s",
                        (json.dumps(metadata), timestamp, request.entity_id),
                    )
                else:
                    cur.execute(
                        "UPDATE board_tasks SET metadata = %s, updated_at = %s WHERE task_id = %s",
                        (json.dumps(metadata), timestamp, request.entity_id),
                    )

        self._pool.run_transaction(
            operation=f"{request.entity_type}.remove_attachment",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"entity_id": request.entity_id, "attachment_id": request.attachment_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_dsn(self, provided: Optional[str]) -> str:
        if provided:
            return provided
        return os.getenv(
            _BOARD_PG_DSN_ENV,
            resolve_postgres_dsn(
                service="board",
                explicit_dsn=None,
                env_var=_BOARD_PG_DSN_ENV,
                default_dsn=_DEFAULT_PG_DSN,
            ),
        )

    def _get_columns_for_board(self, board_id: str, *, org_id: Optional[str]) -> List[BoardColumn]:
        with self._pool.connection() as conn:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM board_columns WHERE board_id = %s ORDER BY position ASC",
                    (board_id,),
                )
                rows = cur.fetchall()
                return [self._row_to_column(r) for r in rows]

    def _get_column(self, column_id: str, *, org_id: Optional[str]) -> BoardColumn:
        with self._pool.connection() as conn:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM board_columns WHERE column_id = %s", (column_id,))
                row = cur.fetchone()
                if not row:
                    raise BoardServiceError(f"Column not found: {column_id}")
                return self._row_to_column(row)

    def _row_to_board(self, row: tuple) -> Board:
        return Board(
            board_id=row[0],
            project_id=row[1],
            name=row[2],
            description=row[3],
            settings=_parse_jsonb(row[4], {}),
            created_at=row[5],
            updated_at=row[6],
            created_by=row[7],
            is_default=row[8],
            org_id=row[9],
        )

    def _row_to_column(self, row: tuple) -> BoardColumn:
        return BoardColumn(
            column_id=row[0],
            board_id=row[1],
            name=row[2],
            position=row[3],
            status_mapping=WorkItemStatus(row[4]),
            wip_limit=row[5],
            settings=_parse_jsonb(row[6], {}),
            created_at=row[7],
        )

    def _row_to_epic(self, row: tuple) -> Epic:
        return Epic(
            epic_id=row[0],
            project_id=row[1],
            board_id=row[2],
            name=row[3],
            description=row[4],
            status=EpicStatus(row[5]),
            priority=WorkItemPriority(row[6]),
            color=row[7],
            start_date=row[8],
            target_date=row[9],
            completed_at=row[10],
            labels=_parse_jsonb(row[11], []),
            metadata=_parse_jsonb(row[12], {}),
            created_at=row[13],
            updated_at=row[14],
            created_by=row[15],
            org_id=row[16],
        )

    def _row_to_story(self, row: tuple) -> Story:
        return Story(
            story_id=row[0],
            project_id=row[1],
            board_id=row[2],
            epic_id=row[3],
            column_id=row[4],
            title=row[5],
            description=row[6],
            status=WorkItemStatus(row[7]),
            priority=WorkItemPriority(row[8]),
            story_points=row[9],
            position=row[10],
            assignee_id=row[11],
            assignee_type=AssigneeType(row[12]) if row[12] else None,
            assigned_at=row[13],
            assigned_by=row[14],
            started_at=row[15],
            completed_at=row[16],
            due_date=row[17],
            labels=_parse_jsonb(row[18], []),
            acceptance_criteria=[AcceptanceCriterion(**ac) for ac in _parse_jsonb(row[19], [])],
            metadata=_parse_jsonb(row[20], {}),
            created_at=row[21],
            updated_at=row[22],
            created_by=row[23],
            org_id=row[24],
        )

    def _row_to_task(self, row: tuple) -> Task:
        return Task(
            task_id=row[0],
            project_id=row[1],
            story_id=row[2],
            board_id=row[3],
            column_id=row[4],
            title=row[5],
            description=row[6],
            task_type=TaskType(row[7]),
            status=WorkItemStatus(row[8]),
            priority=WorkItemPriority(row[9]),
            estimated_hours=row[10],
            actual_hours=row[11],
            position=row[12],
            assignee_id=row[13],
            assignee_type=AssigneeType(row[14]) if row[14] else None,
            assigned_at=row[15],
            assigned_by=row[16],
            started_at=row[17],
            completed_at=row[18],
            due_date=row[19],
            behavior_id=row[20],
            run_id=row[21],
            labels=_parse_jsonb(row[22], []),
            checklist=[
                item if isinstance(item, dict) else item
                for item in _parse_jsonb(row[23], [])
            ],
            metadata=_parse_jsonb(row[24], {}),
            created_at=row[25],
            updated_at=row[26],
            created_by=row[27],
            org_id=row[28],
        )

    def _row_to_sprint(self, row: tuple) -> Sprint:
        return Sprint(
            sprint_id=row[0],
            project_id=row[1],
            board_id=row[2],
            name=row[3],
            goal=row[4],
            status=SprintStatus(row[5]),
            start_date=row[6],
            end_date=row[7],
            velocity_planned=row[8],
            velocity_completed=row[9],
            metadata=_parse_jsonb(row[10], {}),
            created_at=row[11],
            updated_at=row[12],
            created_by=row[13],
            org_id=row[14],
        )

    def _row_to_assignment_history(self, row: tuple) -> AssignmentHistory:
        return AssignmentHistory(
            history_id=row[0],
            assignable_id=row[1],
            assignable_type=row[2],
            assignee_id=row[3],
            assignee_type=AssigneeType(row[4]) if row[4] else None,
            action=AssignmentAction(row[5]),
            performed_by=row[6],
            performed_at=row[7],
            previous_assignee_id=row[8],
            previous_assignee_type=AssigneeType(row[9]) if row[9] else None,
            reason=row[10],
            metadata=_parse_jsonb(row[11], {}),
            org_id=row[12],
        )
