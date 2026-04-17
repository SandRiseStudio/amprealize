"""
Board Service - Unified WorkItem-based Agile Board management.

Uses a single work_items table with item_type discriminator for goals/features/tasks.
Provides CRUD for boards, columns, work items, and sprints.

Feature: 13.4.5 (Agent assignment) and 13.5.x (Agile Board System)
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from amprealize.boards.contracts import (
    AcceptanceCriterion,
    AssigneeType,
    AssignmentAction,
    AssignmentHistory,
    AssignWorkItemRequest,
    Board,
    BoardColumn,
    BoardEvent,
    BoardEventType,
    BoardSettings,
    BoardTemplate,
    BoardVisibility,
    BoardWithColumns,
    ChecklistItem,
    CreateBoardRequest,
    CreateColumnRequest,
    CreateLabelRequest,
    CreateWorkItemRequest,
    DeleteResult,
    Label,
    LabelColor,
    LabelListResponse,
    IncompleteWorkItemSummary,
    MoveWorkItemRequest,
    ProgressBucketCounts,
    ReorderBoardColumnsRequest,
    ReorderWorkItemsRequest,
    Sprint,
    SprintStory,
    SprintStatus,
    CreateSprintRequest,
    UpdateBoardRequest,
    UpdateColumnRequest,
    UpdateLabelRequest,
    UpdateSprintRequest,
    UpdateWorkItemRequest,
    WorkItem,
    WorkItemProgressRollup,
    WorkItemPriority,
    RemainingWorkSummary,
    WorkItemStatus,
    WorkItemType,
    is_valid_status_transition,
    normalize_item_type,
)
from amprealize.agents.work_item_planner.prompts import validate_title as _gws_validate_title
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.telemetry import TelemetryClient
from amprealize.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_BOARD_PG_DSN_ENV = "AMPREALIZE_BOARD_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://amprealize:amprealize_dev@localhost:5432/amprealize"

# Process-wide cache for the `board.work_items.parent_id` information_schema
# probe. Keyed by the id() of the PostgresPool so different pools (e.g. in
# tests) don't share state. The probe is cheap but costs a full Neon RTT
# on cold start, and the schema has been stable for months — caching the
# answer across BoardService instances saves one RTT per worker process on
# the first ancestor-hydration batch call.
_parent_id_probe_cache: Dict[int, bool] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _history_assignable_type(item_type: WorkItemType) -> str:
    """Value stored in assignment_history.assignable_type.

    Older DBs enforce CHECK (... 'epic','story',... ) without 'goal'. The work_items row uses
    unified types (goal/feature/...); for audit rows we map goal -> epic so assign/unassign
    succeeds before/whether migration 20260402_widen_assignment is applied.
    """
    v = item_type.value
    if v == "goal":
        return "epic"
    return v


def _parse_jsonb(value: Any, default: Any = None) -> Any:
    """Parse JSONB field that may already be decoded by psycopg2."""
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value) if value else (default if default is not None else {})
    return value


# Display-ID pattern: "{slug}-{number}" where slug is lowercase alphanumeric
# with hyphens (matching Project.slug pattern) and number is a positive integer.
# Internal IDs have hex suffixes (e.g. task-a1b2c3d4e5f6) or are full UUIDs,
# so we distinguish by checking that the trailing segment is purely decimal.
_DISPLAY_ID_RE = re.compile(r"^(?P<slug>[a-z][a-z0-9-]*)-(?P<number>[1-9]\d*)$")


def parse_display_id(value: str) -> tuple[str, int] | None:
    """Parse a display ID like 'myproject-42' into (slug, number).

    Returns None if *value* doesn't match the display-ID format.
    """
    m = _DISPLAY_ID_RE.match(value)
    if not m:
        return None
    slug = m.group("slug")
    number = int(m.group("number"))
    # Reject values that look like internal short-IDs (hex suffixes).
    # Internal IDs: "task-a1b2c3d4e5f6" — the suffix is 12 hex chars.
    # Display IDs: "myproject-42" — the suffix is purely decimal.
    # The regex already enforces digits-only for the number, so we just
    # need to reject known prefixes that are internal type tags.
    if slug in ("epic", "story", "task", "bug", "goal", "feature"):
        return None
    return slug, number


class Actor:
    """Represents the actor performing an operation."""
    def __init__(self, id: str, role: str = "user", surface: str = "api") -> None:
        self.id = id
        self.role = role
        self.surface = surface


def _actor_payload(actor: Actor) -> Dict[str, str]:
    return {"id": actor.id, "role": actor.role, "surface": actor.surface}


# Exceptions
class BoardServiceError(Exception):
    """Base exception for board service."""

class WorkItemTransitionError(BoardServiceError):
    """Invalid status transition."""

class BoardNotFoundError(BoardServiceError):
    """Board not found."""

class WorkItemNotFoundError(BoardServiceError):
    """Work item not found."""


# Backwards-compat exceptions (older API had type-specific not-found errors)
class EpicNotFoundError(WorkItemNotFoundError):
    """Epic/Goal not found."""


class StoryNotFoundError(WorkItemNotFoundError):
    """Story/Feature not found."""

# Aliases for new naming
GoalNotFoundError = EpicNotFoundError
FeatureNotFoundError = StoryNotFoundError


class TaskNotFoundError(WorkItemNotFoundError):
    """Task not found."""

class ColumnNotFoundError(BoardServiceError):
    """Column not found."""


class AuthorNotFoundError(BoardServiceError):
    """Author (user or agent) not found."""


class AssigneeNotFoundError(BoardServiceError):
    """Assignee (user or agent) not found during assignment validation."""


class ConcurrencyConflictError(BoardServiceError):
    """Optimistic concurrency conflict."""

class WorkItemValidationError(BoardServiceError):
    """Work item field validation failure (e.g. GWS title rules)."""


# Callback types
BoardEventHandler = Callable[[BoardEvent], None]
# Agent validator: (agent_id, org_id) -> bool (returns True if agent exists)
AgentValidator = Callable[[str, Optional[str]], bool]


class BoardService:
    """Service for managing boards and work items."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool: Optional[PostgresPool] = None,
        telemetry: Optional[TelemetryClient] = None,
        agent_validator: Optional[AgentValidator] = None,
    ) -> None:
        if pool is None:
            if dsn is None:
                dsn = resolve_postgres_dsn(
                    service="BOARD",
                    explicit_dsn=None,
                    env_var=_BOARD_PG_DSN_ENV,
                    default_dsn=_DEFAULT_PG_DSN,
                )
            pool = PostgresPool(dsn, schema="board")
        self._pool = pool
        self._telemetry = telemetry
        self._event_handlers: List[BoardEventHandler] = []
        self._agent_validator = agent_validator
        self._parent_id_exists: Optional[bool] = None

    def set_agent_validator(self, validator: AgentValidator) -> None:
        """Set the agent validator callback for verifying agent existence during assignment."""
        self._agent_validator = validator

    def register_event_handler(self, handler: BoardEventHandler) -> None:
        """Register a callback for board events."""
        self._event_handlers.append(handler)

    def _emit_event(self, event: BoardEvent) -> None:
        """Emit event to all registered handlers."""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.warning(f"Event handler error: {e}")

    def _ensure_parent_id_column(self, conn: Any) -> None:
        """Ensure board.work_items.parent_id exists for hierarchy support."""
        if self._parent_id_exists is True:
            return

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'board' AND table_name = 'work_items' AND column_name = 'parent_id'
                """
            )
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(
                    """
                    ALTER TABLE board.work_items
                    ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES board.work_items(id) ON DELETE SET NULL
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_work_items_parent_id
                    ON board.work_items(parent_id) WHERE parent_id IS NOT NULL
                    """
                )
                exists = True

        self._parent_id_exists = exists

    # =========================================================================
    # Display number helpers
    # =========================================================================

    def _next_display_number(self, cur: Any, project_id: str, entity_type: str) -> int:
        """Atomically allocate the next sequential display number for a project.

        Uses INSERT ... ON CONFLICT ... UPDATE ... RETURNING for race-safe
        counter increments within the current transaction.

        Args:
            cur: Database cursor (must be inside a transaction)
            project_id: The project scope for the counter
            entity_type: 'board' or 'work_item'

        Returns:
            The allocated display number (1-based)
        """
        cur.execute(
            """
            INSERT INTO project_counters (project_id, entity_type, next_number)
            VALUES (%s, %s, 1)
            ON CONFLICT (project_id, entity_type)
            DO UPDATE SET next_number = project_counters.next_number + 1
            RETURNING next_number
            """,
            (project_id, entity_type),
        )
        row = cur.fetchone()
        return int(row[0])

    # =========================================================================
    # Display-ID resolution
    # =========================================================================

    def resolve_work_item_id(
        self,
        identifier: str,
        *,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> str:
        """Resolve a display ID (e.g. 'myproject-42') or internal ID to a UUID.

        Auto-detects the format:
        - Full UUID (xxxxxxxx-xxxx-...) → returned as-is
        - Internal short ID (task-a1b2c3d4e5f6) → returned as-is
        - Display ID (slug-number, e.g. 'myproject-42') → looked up via project slug + display_number
        - Bare number ('42' or '#42') with project_id context → looked up via display_number

        Returns:
            The internal UUID string for the work item.

        Raises:
            WorkItemNotFoundError: If the display ID cannot be resolved.
        """
        if not identifier:
            raise WorkItemNotFoundError("Work item identifier is required")

        # Strip optional '#' prefix for bare numbers
        cleaned = identifier.lstrip("#")

        # 1. Full UUID — return as-is
        try:
            uuid.UUID(cleaned)
            return cleaned
        except ValueError:
            pass

        # 2. Internal short ID (type-hex12) — return as-is
        if re.match(r"^(goal|feature|epic|story|task|bug)-[a-f0-9]{12}$", cleaned.lower()):
            return cleaned

        # 3. Display ID: slug-number (case-insensitive, e.g. "AMPREALIZE-7" or "amprealize-7")
        parsed = parse_display_id(cleaned.lower())
        if parsed:
            slug, display_number = parsed
            return self._resolve_by_slug_and_number(slug, display_number, org_id=org_id)

        # 4. Bare number (with project_id context)
        if cleaned.isdigit() and int(cleaned) > 0:
            if not project_id:
                raise WorkItemNotFoundError(
                    f"Cannot resolve bare number '{identifier}' without project context. "
                    f"Use the full display ID (e.g. 'project-slug-{cleaned}') or provide project_id."
                )
            return self._resolve_by_project_and_number(
                project_id, int(cleaned), org_id=org_id
            )

        # 5. Not recognized — assume it's an internal ID and let downstream
        # queries fail naturally if it doesn't exist.
        return identifier

    def _resolve_by_slug_and_number(
        self,
        slug: str,
        display_number: int,
        *,
        org_id: Optional[str] = None,
    ) -> str:
        """Look up a work item UUID by project slug and display number."""
        def _query(conn: Any) -> Optional[str]:
            # Always set tenant context to configure search_path (handles None org_id)
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT wi.id
                    FROM work_items wi
                    JOIN projects p ON p.project_id = wi.project_id
                    WHERE p.slug = %s
                      AND wi.display_number = %s
                      AND p.archived_at IS NULL
                    """,
                    (slug, display_number),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None

        result = self._pool.run_query(
            operation="work_item.resolve_display_id",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        if not result:
            raise WorkItemNotFoundError(
                f"Work item '{slug}-{display_number}' not found"
            )
        return result

    def _resolve_by_project_and_number(
        self,
        project_id: str,
        display_number: int,
        *,
        org_id: Optional[str] = None,
    ) -> str:
        """Look up a work item UUID by project ID and display number."""
        def _query(conn: Any) -> Optional[str]:
            # Always set tenant context to configure search_path (handles None org_id)
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM work_items
                    WHERE project_id = %s AND display_number = %s
                    """,
                    (project_id, display_number),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None

        result = self._pool.run_query(
            operation="work_item.resolve_by_number",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        if not result:
            raise WorkItemNotFoundError(
                f"Work item #{display_number} not found in project {project_id}"
            )
        return result

    def _get_project_slug(self, project_id: str, *, org_id: Optional[str] = None) -> Optional[str]:
        """Look up the slug for a project by ID."""
        def _query(conn: Any) -> Optional[str]:
            # Always set tenant context to configure search_path (handles None org_id)
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug FROM projects WHERE project_id = %s AND archived_at IS NULL",
                    (project_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None

        return self._pool.run_query(
            operation="project.get_slug",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )

    # =========================================================================
    # Board CRUD
    # =========================================================================

    def create_board(
        self, request: CreateBoardRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Board:
        timestamp = _now()
        settings = request.settings or BoardSettings()
        board_id_holder: List[str] = []  # Capture generated UUID

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Allocate sequential display number for the project
                display_num = None
                if request.project_id:
                    display_num = self._next_display_number(cur, request.project_id, "board")

                # Let database generate UUID via gen_random_uuid()
                cur.execute(
                    """
                    INSERT INTO boards (project_id, name, description, settings,
                                       created_at, updated_at, created_by, org_id,
                                       display_number)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (request.project_id, request.name, request.description,
                     json.dumps(settings.model_dump()), timestamp, timestamp, actor.id, org_id,
                     display_num),
                )
                row = cur.fetchone()
                board_uuid = str(row[0]) if row else None
                if board_uuid:
                    board_id_holder.append(board_uuid)
                    if request.create_default_columns:
                        self._create_default_columns(cur, board_uuid, timestamp, request.template)

        self._pool.run_transaction(
            operation="board.create", service_prefix="board",
            actor=_actor_payload(actor), metadata={"board_id": board_id_holder[0] if board_id_holder else "pending"},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_board(board_id_holder[0], org_id=org_id)

    # Legacy fallback: column name → WorkItemStatus for columns created before
    # the status_mapping DB column was populated.  Only used by
    # _infer_status_from_column_name() when status_mapping is NULL.
    _COLUMN_NAME_TO_STATUS: Dict[str, WorkItemStatus] = {
        "backlog": WorkItemStatus.BACKLOG,
        "in progress": WorkItemStatus.IN_PROGRESS,
        "in review": WorkItemStatus.IN_REVIEW,
        "done": WorkItemStatus.DONE,
    }

    _STATUS_TO_PROGRESS_BUCKET: Dict[WorkItemStatus, str] = {
        WorkItemStatus.BACKLOG: "not_started",
        WorkItemStatus.IN_PROGRESS: "in_progress",
        WorkItemStatus.IN_REVIEW: "in_progress",
        WorkItemStatus.DONE: "completed",
    }

    @staticmethod
    def _infer_status_from_column_name(name: str) -> WorkItemStatus:
        """Infer a WorkItemStatus from a column's display name.

        Used as a fallback when status_mapping is NULL in the database (i.e.
        columns created before the status_mapping column was populated).
        """
        return BoardService._COLUMN_NAME_TO_STATUS.get(
            name.strip().lower(), WorkItemStatus.BACKLOG
        )

    # Column presets per template (name, position, color, status_mapping)
    _TEMPLATE_COLUMNS: Dict[BoardTemplate, list] = {
        BoardTemplate.MINIMAL: [
            ("Backlog", 0, "#6B7280", WorkItemStatus.BACKLOG),
            ("In Progress", 1, "#F59E0B", WorkItemStatus.IN_PROGRESS),
            ("Done", 2, "#10B981", WorkItemStatus.DONE),
        ],
        BoardTemplate.STANDARD: [
            ("Backlog", 0, "#6B7280", WorkItemStatus.BACKLOG),
            ("In Progress", 1, "#F59E0B", WorkItemStatus.IN_PROGRESS),
            ("In Review", 2, "#8B5CF6", WorkItemStatus.IN_REVIEW),
            ("Done", 3, "#10B981", WorkItemStatus.DONE),
        ],
        BoardTemplate.FULL: [
            ("Backlog", 0, "#6B7280", WorkItemStatus.BACKLOG),
            ("In Progress", 1, "#F59E0B", WorkItemStatus.IN_PROGRESS),
            ("In Review", 2, "#8B5CF6", WorkItemStatus.IN_REVIEW),
            ("Done", 3, "#10B981", WorkItemStatus.DONE),
        ],
    }

    def _create_default_columns(
        self, cur: Any, board_id: str, timestamp: datetime,
        template: BoardTemplate = BoardTemplate.MINIMAL,
    ) -> None:
        """Create default columns for a board based on the chosen template.

        Args:
            cur: Database cursor
            board_id: UUID string of the board
            timestamp: Creation timestamp
            template: Which column preset to use (minimal/standard/full)
        """
        defaults = self._TEMPLATE_COLUMNS.get(template, self._TEMPLATE_COLUMNS[BoardTemplate.MINIMAL])
        for name, pos, color, status_map in defaults:
            # Let database generate UUID via gen_random_uuid()
            cur.execute(
                """INSERT INTO columns (board_id, name, position, color, status_mapping, created_at, updated_at)
                   VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)""",
                (board_id, name, pos, color, status_map.value, timestamp, timestamp),
            )

    def get_board(
        self,
        board_id: str,
        include_columns: bool = False,
        *,
        org_id: Optional[str] = None,
    ) -> Board | BoardWithColumns:
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Use 'id' column (database schema uses UUID id, not board_id)
                cur.execute("SELECT * FROM boards WHERE id = %s::uuid", (board_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="board.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise BoardNotFoundError(f"Board {board_id} not found")
        # Map database 'id' to contract 'board_id'
        board = Board(
            board_id=str(result["id"]), project_id=result["project_id"],
            name=result["name"], description=result["description"],
            settings=BoardSettings(**_parse_jsonb(result["settings"])),
            created_at=result["created_at"], updated_at=result["updated_at"],
            created_by=result["created_by"], is_default=False,  # is_default not in schema, default to False
            org_id=result.get("org_id"),
            display_number=result.get("display_number"),
        )

        if include_columns:
            return self.get_board_with_columns(board_id, org_id=org_id)
        return board

    def get_board_with_columns(self, board_id: str, *, org_id: Optional[str] = None) -> BoardWithColumns:
        board = self.get_board(board_id, include_columns=False, org_id=org_id)
        if isinstance(board, BoardWithColumns):
            return board
        columns = self.list_columns(board_id, org_id=org_id)
        return BoardWithColumns(**board.model_dump(), columns=columns)

    def list_boards(
        self,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Board]:
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            conditions: list[str] = []
            values: list[Any] = []
            if project_id:
                conditions.append("project_id = %s")
                values.append(project_id)
            where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            values.extend([limit, offset])
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM boards {where_sql} ORDER BY created_at ASC LIMIT %s OFFSET %s",
                    values,
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="board.list", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        return [
            Board(
                board_id=str(r["id"]),  # Map database 'id' to contract 'board_id'
                project_id=r["project_id"],
                name=r["name"],
                description=r.get("description"),
                settings=BoardSettings(**_parse_jsonb(r.get("settings"))),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                created_by=r["created_by"],
                is_default=r.get("is_default", False),
                org_id=r.get("org_id"),
                display_number=r.get("display_number"),
            )
            for r in results
        ]

    def update_board(
        self, board_id: str, request: UpdateBoardRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Board:
        self.get_board(board_id, org_id=org_id)  # Verify exists
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates, values = [], []
            if request.name is not None:
                updates.append("name = %s"); values.append(request.name)
            if request.description is not None:
                updates.append("description = %s"); values.append(request.description)
            if request.settings is not None:
                updates.append("settings = %s"); values.append(json.dumps(request.settings.model_dump()))
            # Note: is_default not in database schema, skip
            if not updates:
                return
            updates.append("updated_at = %s"); values.append(timestamp)
            values.append(board_id)
            with conn.cursor() as cur:
                cur.execute(f"UPDATE boards SET {', '.join(updates)} WHERE id = %s::uuid", values)

        self._pool.run_transaction(
            operation="board.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"board_id": board_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_board(board_id, org_id=org_id)

    def delete_board(self, board_id: str, actor: Actor, *, org_id: Optional[str] = None) -> DeleteResult:
        self.get_board(board_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM boards WHERE id = %s::uuid", (board_id,))

        self._pool.run_transaction(
            operation="board.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"board_id": board_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=board_id, deleted_type="board")

    # =========================================================================
    # Column CRUD
    # =========================================================================

    def create_column(
        self, request: CreateColumnRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> BoardColumn:
        self.get_board(request.board_id, org_id=org_id)
        column_id_holder: List[str] = []  # Capture generated UUID
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Let database generate UUID, use 'columns' table
                cur.execute(
                    """INSERT INTO columns (board_id, name, position, status_mapping, wip_limit, created_at, updated_at)
                       VALUES (%s::uuid, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        request.board_id,
                        request.name,
                        request.position,
                        request.status_mapping.value,
                        request.wip_limit,
                        timestamp,
                        timestamp,
                    ),
                )
                row = cur.fetchone()
                if row:
                    column_id_holder.append(str(row[0]))

        self._pool.run_transaction(
            operation="column.create", service_prefix="board",
            actor=_actor_payload(actor), metadata={"column_id": column_id_holder[0] if column_id_holder else "pending"},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_column(column_id_holder[0], org_id=org_id)

    def get_column(self, column_id: str, *, org_id: Optional[str] = None) -> BoardColumn:
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Use 'columns' table and 'id' column
                cur.execute("SELECT * FROM columns WHERE id = %s::uuid", (column_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="column.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise ColumnNotFoundError(f"Column {column_id} not found")

        # Parse status_mapping from DB if present, infer from column name as fallback
        status_mapping_val = result.get("status_mapping")
        if status_mapping_val:
            try:
                status_mapping = WorkItemStatus(status_mapping_val)
            except ValueError:
                status_mapping = self._infer_status_from_column_name(result["name"])
        else:
            status_mapping = self._infer_status_from_column_name(result["name"])

        return BoardColumn(
            column_id=str(result["id"]), board_id=str(result["board_id"]),
            name=result["name"], position=result["position"],
            status_mapping=status_mapping,
            wip_limit=result.get("wip_limit"),
            settings={},  # settings not in schema
            created_at=result["created_at"],
            updated_at=result.get("updated_at") or result["created_at"],
        )

    def list_columns(self, board_id: str, *, org_id: Optional[str] = None) -> List[BoardColumn]:
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Use 'columns' table (database schema uses 'columns', not 'board_columns')
                cur.execute(
                    "SELECT * FROM columns WHERE board_id = %s::uuid ORDER BY position",
                    (board_id,)
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="column.list", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        return [
            BoardColumn(
                column_id=str(r["id"]), board_id=str(r["board_id"]),
                name=r["name"], position=r["position"],
                status_mapping=(
                    WorkItemStatus(r["status_mapping"])
                    if r.get("status_mapping")
                    else self._infer_status_from_column_name(r["name"])
                ),
                wip_limit=r.get("wip_limit"),
                settings={},  # settings not in schema
                created_at=r["created_at"],
                updated_at=r.get("updated_at") or r["created_at"],
            ) for r in results
        ]

    def update_column(
        self, column_id: str, request: UpdateColumnRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> BoardColumn:
        current_col = self.get_column(column_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Handle position change with proper reordering to maintain uniqueness
                if request.position is not None and request.position != current_col.position:
                    new_pos = request.position
                    old_pos = current_col.position
                    board_id = current_col.board_id

                    # To avoid unique constraint violations during reordering:
                    # 1. Add a large offset (1000) to all affected positions
                    # 2. Then set the final positions
                    # This ensures no intermediate duplicates

                    if new_pos < old_pos:
                        # Moving up: target gets new_pos, columns in [new_pos, old_pos) shift +1
                        # Step 1: Offset affected columns
                        cur.execute(
                            """UPDATE columns
                               SET position = position + 1000
                               WHERE board_id = %s::uuid AND (id = %s::uuid OR (position >= %s AND position < %s))""",
                            (board_id, column_id, new_pos, old_pos),
                        )
                        # Step 2: Set final positions
                        # Target column goes to new_pos
                        cur.execute(
                            "UPDATE columns SET position = %s, updated_at = %s WHERE id = %s::uuid",
                            (new_pos, timestamp, column_id),
                        )
                        # Shifted columns go to their new positions (original + 1)
                        cur.execute(
                            """UPDATE columns
                               SET position = position - 1000 + 1, updated_at = %s
                               WHERE board_id = %s::uuid AND position >= 1000""",
                            (timestamp, board_id),
                        )
                    else:
                        # Moving down: target gets new_pos, columns in (old_pos, new_pos] shift -1
                        # Step 1: Offset affected columns
                        cur.execute(
                            """UPDATE columns
                               SET position = position + 1000
                               WHERE board_id = %s::uuid AND (id = %s::uuid OR (position > %s AND position <= %s))""",
                            (board_id, column_id, old_pos, new_pos),
                        )
                        # Step 2: Set final positions
                        # Target column goes to new_pos
                        cur.execute(
                            "UPDATE columns SET position = %s, updated_at = %s WHERE id = %s::uuid",
                            (new_pos, timestamp, column_id),
                        )
                        # Shifted columns go to their new positions (original - 1)
                        cur.execute(
                            """UPDATE columns
                               SET position = position - 1000 - 1, updated_at = %s
                               WHERE board_id = %s::uuid AND position >= 1000""",
                            (timestamp, board_id),
                        )

                # Handle other updates (name, wip_limit - status_mapping not in schema)
                updates, values = [], []
                if request.name is not None:
                    updates.append("name = %s"); values.append(request.name)
                # Note: status_mapping not in database schema, skip
                if request.wip_limit is not None:
                    updates.append("wip_limit = %s"); values.append(request.wip_limit)

                if updates:
                    updates.append("updated_at = %s"); values.append(timestamp)
                    where_sql = "id = %s::uuid"
                    where_values: list[Any] = [column_id]
                    if request.expected_updated_at is not None:
                        where_sql += " AND updated_at = %s"
                        where_values.append(request.expected_updated_at)
                    cur.execute(
                        f"UPDATE columns SET {', '.join(updates)} WHERE {where_sql}",
                        values + where_values,
                    )
                    if request.expected_updated_at is not None and cur.rowcount == 0:
                        raise ConcurrencyConflictError(
                            f"Column {column_id} updated_at did not match expected_updated_at"
                        )

        self._pool.run_transaction(
            operation="column.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"column_id": column_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_column(column_id, org_id=org_id)

    # =========================================================================
    # Drag & drop (move / reorder)
    # =========================================================================

    def move_work_item(
        self, item_id: str, request: MoveWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Move a work item between columns and/or change its position.

        Bidirectional sync: when moving to a new column, the item's status is
        automatically updated to match the destination column's status_mapping.
        """
        item = self.get_work_item(item_id, org_id=org_id)
        if item.board_id is None:
            raise BoardServiceError(f"Work item {item_id} has no board_id")

        from_column_id = item.column_id
        to_column_id = request.column_id if request.column_id is not None else item.column_id
        if to_column_id is None:
            raise BoardServiceError(f"Work item {item_id} has no column_id")

        # Resolve the destination column's status_mapping for bidirectional sync
        new_status: Optional[WorkItemStatus] = None
        if to_column_id != from_column_id:
            dest_column = self.get_column(to_column_id, org_id=org_id)
            if dest_column.status_mapping and dest_column.status_mapping != item.status:
                if is_valid_status_transition(item.status, dest_column.status_mapping):
                    new_status = dest_column.status_mapping

        requested_position = max(0, int(request.position))
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Normalize target position to end-of-column
                cur.execute(
                    """SELECT COALESCE(MAX(position), -1) + 1
                       FROM work_items
                       WHERE board_id = %s AND column_id = %s AND id <> %s""",
                    (item.board_id, to_column_id, item_id),
                )
                (max_plus_one,) = cur.fetchone()
                target_position = min(requested_position, int(max_plus_one))

                if from_column_id == to_column_id:
                    # Close gap at old position
                    cur.execute(
                        """UPDATE work_items
                           SET position = position - 1
                           WHERE board_id = %s AND column_id = %s AND position > %s""",
                        (item.board_id, to_column_id, item.position),
                    )
                    # Make room at new position
                    cur.execute(
                        """UPDATE work_items
                           SET position = position + 1
                           WHERE board_id = %s AND column_id = %s AND position >= %s AND id <> %s""",
                        (item.board_id, to_column_id, target_position, item_id),
                    )
                    cur.execute(
                        """UPDATE work_items
                           SET position = %s, updated_at = %s
                           WHERE id = %s""",
                        (target_position, timestamp, item_id),
                    )
                else:
                    if from_column_id is not None:
                        # Close gap in source column
                        cur.execute(
                            """UPDATE work_items
                               SET position = position - 1
                               WHERE board_id = %s AND column_id = %s AND position > %s""",
                            (item.board_id, from_column_id, item.position),
                        )
                    # Make room in destination column
                    cur.execute(
                        """UPDATE work_items
                           SET position = position + 1
                           WHERE board_id = %s AND column_id = %s AND position >= %s""",
                        (item.board_id, to_column_id, target_position),
                    )
                    # Also sync status from destination column's status_mapping
                    if new_status is not None:
                        cur.execute(
                            """UPDATE work_items
                               SET column_id = %s, position = %s, status = %s, updated_at = %s
                               WHERE id = %s""",
                            (to_column_id, target_position, new_status.value, timestamp, item_id),
                        )
                    else:
                        cur.execute(
                            """UPDATE work_items
                               SET column_id = %s, position = %s, updated_at = %s
                               WHERE id = %s""",
                            (to_column_id, target_position, timestamp, item_id),
                        )

                # Update column versions last (optimistic concurrency guard)
                if from_column_id is not None:
                    if request.expected_from_column_updated_at is None:
                        cur.execute(
                            "UPDATE columns SET updated_at = %s WHERE id = %s",
                            (timestamp, from_column_id),
                        )
                    else:
                        cur.execute(
                            """UPDATE columns SET updated_at = %s
                               WHERE id = %s AND updated_at = %s""",
                            (timestamp, from_column_id, request.expected_from_column_updated_at),
                        )
                        if cur.rowcount == 0:
                            raise ConcurrencyConflictError(
                                f"Source column {from_column_id} updated_at did not match expected"
                            )

                if to_column_id is not None and to_column_id != from_column_id:
                    if request.expected_to_column_updated_at is None:
                        cur.execute(
                            "UPDATE columns SET updated_at = %s WHERE id = %s",
                            (timestamp, to_column_id),
                        )
                    else:
                        cur.execute(
                            """UPDATE columns SET updated_at = %s
                               WHERE id = %s AND updated_at = %s""",
                            (timestamp, to_column_id, request.expected_to_column_updated_at),
                        )
                        if cur.rowcount == 0:
                            raise ConcurrencyConflictError(
                                f"Destination column {to_column_id} updated_at did not match expected"
                            )

        self._pool.run_transaction(
            operation="work_item.move",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"item_id": item_id, "from_column_id": from_column_id, "to_column_id": to_column_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        moved = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_MOVED,
            board_id=moved.board_id, item_id=item_id, item_type=moved.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={"from_column_id": from_column_id, "to_column_id": to_column_id, "position": moved.position},
            org_id=org_id,
        ))
        return moved

    def reorder_work_items(
        self, request: ReorderWorkItemsRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> None:
        """Reorder all work items within a single column."""
        column = self.get_column(request.column_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM work_items
                       WHERE board_id = %s AND column_id = %s""",
                    (column.board_id, request.column_id),
                )
                existing_ids = [str(r[0]) for r in cur.fetchall()]
                if set(existing_ids) != set(request.ordered_item_ids):
                    raise BoardServiceError("ordered_item_ids must match items in the column")

                case_parts: list[str] = []
                values: list[Any] = []
                for idx, item_id in enumerate(request.ordered_item_ids):
                    case_parts.append("WHEN %s THEN %s")
                    values.extend([item_id, idx])

                values.extend([timestamp, column.board_id, request.column_id])
                cur.execute(
                    f"""UPDATE work_items
                        SET position = CASE id {' '.join(case_parts)} END,
                            updated_at = %s
                        WHERE board_id = %s AND column_id = %s""",
                    values,
                )

                if request.expected_column_updated_at is None:
                    cur.execute(
                        "UPDATE columns SET updated_at = %s WHERE id = %s",
                        (timestamp, request.column_id),
                    )
                else:
                    cur.execute(
                        """UPDATE columns SET updated_at = %s
                           WHERE id = %s AND updated_at = %s""",
                        (timestamp, request.column_id, request.expected_column_updated_at),
                    )
                    if cur.rowcount == 0:
                        raise ConcurrencyConflictError(
                            f"Column {request.column_id} updated_at did not match expected"
                        )

        self._pool.run_transaction(
            operation="work_item.reorder",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"column_id": request.column_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    def reorder_columns(
        self, board_id: str, request: ReorderBoardColumnsRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> None:
        """Reorder columns within a board."""
        self.get_board(board_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM columns WHERE board_id = %s",
                    (board_id,),
                )
                existing_ids = [str(r[0]) for r in cur.fetchall()]
                if set(existing_ids) != set(request.ordered_column_ids):
                    raise BoardServiceError("ordered_column_ids must match columns in the board")

                case_parts: list[str] = []
                values: list[Any] = []
                for idx, col_id in enumerate(request.ordered_column_ids):
                    case_parts.append("WHEN %s THEN %s")
                    values.extend([col_id, idx])

                # Postgres enforces UNIQUE constraints row-by-row during UPDATE.
                # Swapping positions in-place can raise UniqueViolation on
                # (board_id, position). Use a two-step update:
                # 1) shift all positions into a temporary range (preserves uniqueness)
                # 2) assign final positions.
                cur.execute(
                    "SELECT COALESCE(MAX(position), 0) FROM columns WHERE board_id = %s",
                    (board_id,),
                )
                max_position = int(cur.fetchone()[0] or 0)
                temp_offset = max_position + len(existing_ids) + 1
                cur.execute(
                    "UPDATE columns SET position = position + %s WHERE board_id = %s",
                    (temp_offset, board_id),
                )

                values.append(board_id)
                cur.execute(
                    f"""UPDATE columns
                        SET position = CASE id {' '.join(case_parts)} END
                        WHERE board_id = %s""",
                    values,
                )

                if request.expected_columns_updated_at:
                    for col_id, expected in request.expected_columns_updated_at.items():
                        cur.execute(
                            """UPDATE columns SET updated_at = %s
                               WHERE id = %s AND updated_at = %s""",
                            (timestamp, col_id, expected),
                        )
                        if cur.rowcount == 0:
                            raise ConcurrencyConflictError(
                                f"Column {col_id} updated_at did not match expected"
                            )
                else:
                    cur.execute(
                        "UPDATE columns SET updated_at = %s WHERE board_id = %s",
                        (timestamp, board_id),
                    )

        self._pool.run_transaction(
            operation="column.reorder",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"board_id": board_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    def delete_column(self, column_id: str, actor: Actor, *, org_id: Optional[str] = None) -> DeleteResult:
        self.get_column(column_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM columns WHERE id = %s", (column_id,))

        self._pool.run_transaction(
            operation="column.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"column_id": column_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=column_id, deleted_type="column")

    # =========================================================================
    # WorkItem CRUD (unified for goal/feature/task)
    # =========================================================================

    def create_work_item(
        self, request: CreateWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Create a work item (goal, feature, task, or bug)."""
        # GWS title validation at the service layer
        title_error = _gws_validate_title(request.item_type.value, request.title)
        if title_error:
            raise WorkItemValidationError(title_error)

        timestamp = _now()

        # Default status to preserve legacy expectations.
        initial_status = WorkItemStatus.BACKLOG

        # Default column_id: prefer board's first column (position-ordered).
        # Columns are user-managed; we don't assume any specific name.
        column_id = request.column_id
        if not column_id and request.board_id:
            columns = self.list_columns(request.board_id, org_id=org_id)
            if columns:
                # Prefer a column mapped to BACKLOG status, else first column
                default_col = next(
                    (c for c in columns if c.status_mapping == WorkItemStatus.BACKLOG),
                    columns[0],
                )
                column_id = default_col.column_id

        # Convert acceptance criteria strings to objects
        criteria = [
            AcceptanceCriterion(id=_short_id("ac"), description=c, is_met=False)
            for c in request.acceptance_criteria
        ]
        checklist = [
            ChecklistItem(id=_short_id("cl"), description=c, is_done=False)
            for c in request.checklist
        ]

        def _execute(conn: Any) -> str:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            self._ensure_parent_id_column(conn)
            # Map priority enum to integer (critical=4, high=3, medium=2, low=1)
            priority_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            priority_int = priority_map.get(request.priority.value, 2)

            # Resolve project_id for counter allocation
            project_id = None
            if request.board_id:
                with conn.cursor() as cur:
                    cur.execute("SELECT project_id FROM boards WHERE id = %s::uuid", (request.board_id,))
                    prow = cur.fetchone()
                    if prow:
                        project_id = prow[0]

            with conn.cursor() as cur:
                # Allocate sequential display number for the project
                display_num = None
                if project_id:
                    display_num = self._next_display_number(cur, project_id, "work_item")

                cur.execute(
                    """
                    INSERT INTO work_items (
                        item_type, project_id, board_id, column_id, parent_id,
                        title, description, status, priority, position,
                        labels, metadata,
                        created_at, updated_at, display_number
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        request.item_type.value,
                        request.project_id,
                        request.board_id, column_id, request.parent_id,
                        request.title, request.description,
                        initial_status.value, priority_int, 0,
                        request.labels,  # Postgres array, not JSON
                        json.dumps(request.metadata),
                        timestamp, timestamp,
                        display_num,
                    ),
                )
                row = cur.fetchone()
                return str(row[0]) if row else ""

        item_id = self._pool.run_transaction(
            operation="work_item.create", service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"item_type": request.item_type.value},
            executor=_execute, telemetry=self._telemetry,
        )

        item = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_CREATED,
            board_id=request.board_id, item_id=item_id, item_type=request.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={"title": request.title}, org_id=org_id,
        ))
        return item

    def get_work_item(self, item_id: str, *, org_id: Optional[str] = None) -> WorkItem:
        """Get a work item by ID."""
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM work_items WHERE id = %s", (item_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="work_item.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise WorkItemNotFoundError(f"Work item {item_id} not found")
        item = self._row_to_work_item(result)
        self._enrich_child_aggregation([item], org_id=org_id)
        self._enrich_display_ids([item], org_id=org_id)
        return item

    def get_work_items_batch(
        self, item_ids: List[str], *, org_id: Optional[str] = None
    ) -> List[WorkItem]:
        """Get multiple work items by IDs in a single query."""
        if not item_ids:
            return []

        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM work_items WHERE id = ANY(%s) ORDER BY created_at",
                    (item_ids,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="work_item.get_batch",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        items = [self._row_to_work_item(r) for r in results]
        self._enrich_child_aggregation(items, org_id=org_id)
        self._enrich_display_ids(items, org_id=org_id)
        return items

    def _row_to_work_item(self, row: Dict) -> WorkItem:
        """Convert a database row to a WorkItem."""
        # Map priority integer back to enum (4=critical, 3=high, 2=medium, 1=low)
        priority_int = row.get("priority", 2)
        priority_reverse_map = {4: "critical", 3: "high", 2: "medium", 1: "low"}
        priority_str = priority_reverse_map.get(priority_int, "medium")

        return WorkItem(
            item_id=str(row["id"]),  # Map UUID id to item_id for contract
            item_type=WorkItemType(normalize_item_type(row["item_type"])),
            project_id=str(row["project_id"]) if row.get("project_id") else None,
            board_id=str(row["board_id"]) if row.get("board_id") else None,
            column_id=str(row["column_id"]) if row.get("column_id") else None,
            parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
            title=row["title"],
            description=row.get("description"),
            status=WorkItemStatus(row["status"]),
            priority=WorkItemPriority(priority_str),
            position=row.get("position", 0),
            story_points=row.get("points") or row.get("story_points"),  # Works pre- and post-migration
            estimated_hours=row.get("estimated_hours"),
            actual_hours=row.get("actual_hours"),
            assignee_id=row.get("assignee_id"),
            assignee_type=AssigneeType(row["assignee_type"]) if row.get("assignee_type") else None,
            assigned_at=row.get("assigned_at"),
            assigned_by=row.get("assigned_by"),
            start_date=row.get("start_date"),
            target_date=row.get("target_date"),
            due_date=row.get("due_date"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            color=row.get("color"),
            labels=_parse_jsonb(row.get("labels"), []),
            acceptance_criteria=[
                AcceptanceCriterion(**c) for c in _parse_jsonb(row.get("acceptance_criteria"), [])
            ],
            checklist=[
                ChecklistItem(**c) for c in _parse_jsonb(row.get("checklist"), [])
            ],
            attachments=[],  # TODO: parse attachments
            behavior_id=row.get("behavior_id"),
            run_id=str(row["run_id"]) if row.get("run_id") else None,
            metadata=_parse_jsonb(row.get("metadata"), {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row.get("created_by") or "system",  # Default to system if not set
            org_id=row.get("org_id"),
            display_number=row.get("display_number"),
        )

    def _enrich_display_ids(
        self, items: List[WorkItem], *, org_id: Optional[str] = None
    ) -> List[WorkItem]:
        """Populate display_id (e.g. 'myproject-42') on items that have a display_number."""
        need = [i for i in items if i.display_number and i.project_id and not i.display_id]
        if not need:
            return items
        project_ids = list({i.project_id for i in need})

        def _query(conn: Any) -> List[tuple]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT project_id, slug FROM auth.projects WHERE project_id = ANY(%s) AND archived_at IS NULL",
                    (project_ids,),
                )
                return cur.fetchall()

        rows = self._pool.run_query(
            operation="project.slug_batch",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        slug_map = {str(r[0]): r[1] for r in rows} if rows else {}
        for item in need:
            slug = slug_map.get(item.project_id)
            if slug:
                item.display_id = f"{slug}-{item.display_number}"
        return items

    def _enrich_child_aggregation(
        self, items: List[WorkItem], *, org_id: Optional[str] = None
    ) -> List[WorkItem]:
        """Populate child_count, completed_child_count, and progress_percent for items.

        Note: Requires `parent_id` column in work_items table. If column doesn't exist,
        returns items unchanged (sub-task hierarchy feature not yet migrated).
        """
        if not items:
            return items

        # Fast path: check process-wide probe cache first so we skip the
        # information_schema round-trip on every batch call after the first
        # one per worker process.
        _pool_key = id(self._pool)
        _cached_exists = _parent_id_probe_cache.get(_pool_key)
        if _cached_exists is False:
            # Column genuinely missing — nothing to aggregate.
            self._parent_id_exists = False
            return items
        if _cached_exists is True:
            # Prime instance attr so downstream callers that read
            # `self._parent_id_exists` stay consistent with the cache.
            self._parent_id_exists = True

        parent_ids = [i.item_id for i in items]

        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Probe information_schema at most once per worker process.
                if _pool_key not in _parent_id_probe_cache:
                    cur.execute(
                        """SELECT column_name FROM information_schema.columns
                           WHERE table_schema = 'board' AND table_name = 'work_items' AND column_name = 'parent_id'"""
                    )
                    exists = bool(cur.fetchone())
                    _parent_id_probe_cache[_pool_key] = exists
                    self._parent_id_exists = exists
                    if not exists:
                        return []

                cur.execute(
                    """SELECT parent_id,
                              COUNT(*) AS child_count,
                              COUNT(*) FILTER (WHERE status IN ('done')) AS completed_child_count
                       FROM work_items
                       WHERE parent_id = ANY(%s::uuid[])
                       GROUP BY parent_id""",
                    (parent_ids,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        _t_child_agg_start = time.perf_counter()
        agg_rows = self._pool.run_query(
            operation="work_item.child_agg",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        _t_child_agg_ms = round((time.perf_counter() - _t_child_agg_start) * 1000, 1)
        logger.debug("_enrich_child_aggregation", extra={"item_count": len(items), "t_child_agg_ms": _t_child_agg_ms})
        if not agg_rows:
            return items  # No child aggregation data (column missing or no children)

        agg_map = {str(r["parent_id"]): r for r in agg_rows}

        for item in items:
            agg = agg_map.get(item.item_id)
            if agg:
                total = agg["child_count"]
                completed = agg["completed_child_count"]
                item.child_count = total
                item.completed_child_count = completed
                item.progress_percent = round((completed / total) * 100, 1) if total > 0 else 0.0
            else:
                item.child_count = 0
                item.completed_child_count = 0
                item.progress_percent = 0.0

        return items

    def update_work_item(
        self, item_id: str, request: UpdateWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Update a work item.

        Bidirectional sync: when status changes without an explicit column_id,
        the item is automatically moved to the column whose status_mapping
        matches the new status.
        """
        item = self.get_work_item(item_id, org_id=org_id)

        # GWS title validation at the service layer (if title is being changed)
        if request.title is not None:
            effective_type = request.item_type.value if request.item_type else item.item_type
            title_error = _gws_validate_title(effective_type, request.title)
            if title_error:
                raise WorkItemValidationError(title_error)

        # Validate status transition
        if request.status and not is_valid_status_transition(item.status, request.status):
            raise WorkItemTransitionError(
                f"Invalid status transition: {item.status} -> {request.status}"
            )

        # Bidirectional sync: status changed without explicit column_id → resolve column
        resolved_column_id = request.column_id
        if (
            request.status is not None
            and request.status != item.status
            and request.column_id is None
            and item.board_id is not None
        ):
            matched_col = self.get_column_by_status_mapping(
                item.board_id, request.status, org_id=org_id
            )
            if matched_col is not None:
                resolved_column_id = matched_col.column_id

        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            if request.parent_id is not None:
                self._ensure_parent_id_column(conn)
            updates, values = [], []

            if request.item_type is not None:
                updates.append("item_type = %s"); values.append(request.item_type.value)
            if request.title is not None:
                updates.append("title = %s"); values.append(request.title)
            if request.description is not None:
                updates.append("description = %s"); values.append(request.description)
            if request.status is not None:
                updates.append("status = %s"); values.append(request.status.value)
            if request.priority is not None:
                priority_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
                updates.append("priority = %s"); values.append(priority_map.get(request.priority.value, 2))
            if request.board_id is not None:
                updates.append("board_id = %s"); values.append(request.board_id)
            if resolved_column_id is not None:
                updates.append("column_id = %s"); values.append(resolved_column_id)
            if request.parent_id is not None:
                updates.append("parent_id = %s"); values.append(request.parent_id)
            if request.position is not None:
                updates.append("position = %s"); values.append(request.position)
            if request.points is not None:
                # Use story_points (pre-migration) or points (post-migration)
                updates.append("story_points = %s"); values.append(request.points)
            if request.estimated_hours is not None:
                updates.append("estimated_hours = %s"); values.append(float(request.estimated_hours))
            if request.actual_hours is not None:
                updates.append("actual_hours = %s"); values.append(float(request.actual_hours))
            if request.start_date is not None:
                updates.append("start_date = %s"); values.append(request.start_date)
            if request.target_date is not None:
                updates.append("target_date = %s"); values.append(request.target_date)
            if request.due_date is not None:
                updates.append("due_date = %s"); values.append(request.due_date)
            if request.color is not None:
                updates.append("color = %s"); values.append(request.color)
            if request.labels is not None:
                updates.append("labels = %s"); values.append(request.labels)
            if request.acceptance_criteria is not None:
                updates.append("acceptance_criteria = %s")
                values.append(json.dumps([c.model_dump() for c in request.acceptance_criteria]))
            if request.checklist is not None:
                updates.append("checklist = %s")
                values.append(json.dumps([c.model_dump() for c in request.checklist]))
            if request.behavior_id is not None:
                updates.append("behavior_id = %s"); values.append(request.behavior_id)
            if request.run_id is not None:
                updates.append("run_id = %s"); values.append(request.run_id)
            if request.metadata is not None:
                updates.append("metadata = %s"); values.append(json.dumps(request.metadata))

            if not updates:
                return
            updates.append("updated_at = %s"); values.append(timestamp)
            values.append(item_id)

            with conn.cursor() as cur:
                cur.execute(f"UPDATE work_items SET {', '.join(updates)} WHERE id = %s", values)

        self._pool.run_transaction(
            operation="work_item.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"item_id": item_id},
            executor=_execute, telemetry=self._telemetry,
        )

        updated = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_UPDATED,
            board_id=updated.board_id, item_id=item_id, item_type=updated.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={}, org_id=org_id,
        ))

        # Upward cascade: if item moved to a terminal status, check if parent should auto-complete
        if request.status in (WorkItemStatus.DONE,):
            try:
                self._cascade_parent_completion(item_id, actor, org_id=org_id)
            except Exception:
                pass  # cascade is best-effort; don't fail the primary update

        return updated

    def complete_with_descendants(
        self,
        item_id: str,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Complete a work item and all incomplete descendants.

        Sets status to 'done' for the target item and all its descendants
        that are not already 'done'.

        Args:
            item_id: Root work item to complete
            actor: Actor performing the operation
            org_id: Optional org scope

        Returns:
            Dict with updated_count (number of items updated) and updated_ids (list)
        """
        root = self.get_work_item(item_id, org_id=org_id)
        if not root.board_id:
            raise BoardServiceError(f"Work item {item_id} has no board_id")

        timestamp = _now()
        board_items = self.list_work_items(board_id=root.board_id, org_id=org_id, limit=10000, offset=0)
        descendants = self._collect_descendants(root.item_id, board_items)

        # Include root + incomplete descendants
        incomplete_statuses = {WorkItemStatus.BACKLOG, WorkItemStatus.IN_PROGRESS, WorkItemStatus.IN_REVIEW}
        items_to_complete: List[str] = []
        if root.status in incomplete_statuses:
            items_to_complete.append(root.item_id)
        for item in descendants:
            if item.status in incomplete_statuses:
                items_to_complete.append(item.item_id)

        if not items_to_complete:
            return {"updated_count": 0, "updated_ids": []}

        # Find "done" column for this board to sync column_id
        done_column_id: Optional[str] = None
        try:
            columns = self.list_columns(root.board_id, org_id=org_id)
            for col in columns:
                if col.status_mapping == WorkItemStatus.DONE:
                    done_column_id = col.column_id
                    break
        except Exception:
            pass  # Column sync is best-effort

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Batch update all items to done
                if done_column_id:
                    cur.execute(
                        "UPDATE work_items SET status = %s, column_id = %s, updated_at = %s WHERE id = ANY(%s::uuid[])",
                        (WorkItemStatus.DONE.value, done_column_id, timestamp, items_to_complete),
                    )
                else:
                    cur.execute(
                        "UPDATE work_items SET status = %s, updated_at = %s WHERE id = ANY(%s::uuid[])",
                        (WorkItemStatus.DONE.value, timestamp, items_to_complete),
                    )

        self._pool.run_transaction(
            operation="work_item.complete_with_descendants",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"root_item_id": item_id, "updated_count": len(items_to_complete)},
            executor=_execute,
            telemetry=self._telemetry,
        )

        # Emit events for all updated items
        for updated_id in items_to_complete:
            self._emit_event(BoardEvent(
                event_id=_short_id("evt"),
                event_type=BoardEventType.ITEM_UPDATED,
                board_id=root.board_id,
                item_id=updated_id,
                item_type=root.item_type,
                actor_id=actor.id,
                actor_type=actor.role,
                timestamp=timestamp,
                payload={"cascade_complete": True},
                org_id=org_id,
            ))

        # Upward cascade: the root itself is now done — check if its parent should auto-complete
        try:
            self._cascade_parent_completion(root.item_id, actor, org_id=org_id)
        except Exception:
            pass  # cascade is best-effort

        return {"updated_count": len(items_to_complete), "updated_ids": items_to_complete}

    def delete_work_item(
        self, item_id: str, actor: Actor, *, org_id: Optional[str] = None, cascade: bool = True
    ) -> DeleteResult:
        """Delete a work item and optionally cascade to children."""
        item = self.get_work_item(item_id, org_id=org_id)
        deleted_children: List[str] = []

        def _execute(conn: Any) -> None:
            nonlocal deleted_children
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if cascade:
                    # Find and delete children
                    cur.execute("SELECT id FROM work_items WHERE parent_id = %s", (item_id,))
                    deleted_children = [str(r[0]) for r in cur.fetchall()]
                    if deleted_children:
                        cur.execute("DELETE FROM work_items WHERE parent_id = %s", (item_id,))
                cur.execute("DELETE FROM work_items WHERE id = %s", (item_id,))

        self._pool.run_transaction(
            operation="work_item.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"item_id": item_id},
            executor=_execute, telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_DELETED,
            board_id=item.board_id, item_id=item_id, item_type=item.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=_now(),
            payload={"cascade_deleted": deleted_children}, org_id=org_id,
        ))
        return DeleteResult(deleted_id=item_id, deleted_type=item.item_type.value, cascade_deleted=deleted_children)

    def list_work_items(
        self,
        *,
        project_id: Optional[str] = None,
        board_id: Optional[str] = None,
        item_type: Optional[WorkItemType] = None,
        item_types: Optional[List[WorkItemType]] = None,
        parent_id: Optional[str] = None,
        status: Optional[WorkItemStatus] = None,
        priority: Optional[WorkItemPriority] = None,
        priorities: Optional[List[WorkItemPriority]] = None,
        assignee_id: Optional[str] = None,
        assignee_type: Optional[str] = None,
        labels: Optional[List[str]] = None,
        sprint_id: Optional[str] = None,
        title_search: Optional[str] = None,
        due_before: Optional[str] = None,
        due_after: Optional[str] = None,
        sort_by: Optional[str] = None,
        order: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_total: bool = False,
    ) -> Union[List[WorkItem], Tuple[List[WorkItem], int]]:
        """
        List work items with filters.

        Args:
            project_id: Filter by project (matches via boards.project_id since work_items
                       are linked to boards, which hold the project association).
            labels: Filter by labels (any of - items with at least one matching label).
                   Uses PostgreSQL JSONB ?| operator for efficient GIN index queries.
            sprint_id: Filter by sprint (items assigned to this sprint).
            priority: Filter by priority level (critical/high/medium/low).
            assignee_type: Filter by assignee type (user/agent).
            title_search: Case-insensitive substring search on title.
            due_before: ISO date — return items due on or before this date.
            due_after: ISO date — return items due on or after this date.
            sort_by: Sort column — one of position, priority, created_at, updated_at,
                     due_date, title, points (or story_points).
            order: Sort direction — asc or desc (default asc).
            include_total: When True, compute the total count of matching rows via
                          `COUNT(*) OVER()` in the same query and return
                          `(items, total)`. Saves a full round-trip vs. a separate
                          `count_work_items` call; the window count reuses the
                          outer query's scan so Neon only pays ~1-2ms extra.
        """
        # Allow-list for sort columns to prevent SQL injection
        SORT_COLUMNS = {
            "position": "w.position",
            "priority": "CASE w.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END",
            "created_at": "w.created_at",
            "updated_at": "w.updated_at",
            "due_date": "w.due_date",
            "title": "w.title",
            "story_points": "w.story_points",
            "points": "w.story_points",
        }

        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            conditions, values = [], []
            # We may need to join with boards table if filtering by project_id
            needs_board_join = project_id is not None

            if project_id:
                # Work items link to boards; boards have project_id
                conditions.append("b.project_id = %s"); values.append(project_id)
            if board_id:
                conditions.append("w.board_id = %s"); values.append(board_id)
            resolved_item_types = item_types if item_types else ([item_type] if item_type else [])
            if resolved_item_types:
                # Match both new and legacy DB values (pre-migration compat)
                _REVERSE_ALIASES = {"goal": "epic", "feature": "story"}
                accepted_values: list[str] = []
                for resolved_item_type in resolved_item_types:
                    accepted_values.append(resolved_item_type.value)
                    legacy = _REVERSE_ALIASES.get(resolved_item_type.value)
                    if legacy:
                        accepted_values.append(legacy)
                conditions.append("w.item_type = ANY(%s)")
                values.append(list(dict.fromkeys(accepted_values)))
            if parent_id:
                conditions.append("w.parent_id = %s"); values.append(parent_id)
            if status:
                conditions.append("w.status = %s"); values.append(status.value)
            resolved_priorities = priorities if priorities else ([priority] if priority else [])
            if resolved_priorities:
                conditions.append("w.priority = ANY(%s)")
                values.append([resolved_priority.value for resolved_priority in resolved_priorities])
            if assignee_id:
                if assignee_id == "__unassigned__":
                    conditions.append("w.assignee_id IS NULL")
                else:
                    conditions.append("w.assignee_id = %s"); values.append(assignee_id)
            if assignee_type:
                conditions.append("w.assignee_type = %s"); values.append(assignee_type)
            if labels:
                # Use && operator for array overlap (works with varchar[] columns)
                conditions.append("w.labels && %s::varchar[]"); values.append(labels)
            if sprint_id:
                conditions.append("w.sprint_id = %s"); values.append(sprint_id)
            if title_search:
                conditions.append("w.title ILIKE %s"); values.append(f"%{title_search}%")
            if due_before:
                conditions.append("w.due_date <= %s"); values.append(due_before)
            if due_after:
                conditions.append("w.due_date >= %s"); values.append(due_after)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            # Build ORDER BY clause
            sort_direction = "DESC" if order and order.lower() == "desc" else "ASC"
            sort_col_expr = SORT_COLUMNS.get(sort_by, None) if sort_by else None
            if sort_col_expr:
                # Add NULLS LAST for nullable columns so nulls don't dominate
                nulls_clause = "NULLS LAST" if sort_by in ("due_date", "story_points", "points") else ""  # sort maps to w.story_points
                order_clause = f"ORDER BY {sort_col_expr} {sort_direction} {nulls_clause}".strip()
            else:
                order_clause = "ORDER BY w.position, w.created_at"

            values.extend([limit, offset])

            # LATERAL subquery computes child aggregation inline — eliminates a
            # separate DB round-trip (~200-400ms Neon latency saved per page).
            _child_agg_lateral = """LEFT JOIN LATERAL (
                    SELECT COUNT(*)::int AS child_count,
                           COUNT(*) FILTER (WHERE status IN ('done'))::int AS completed_child_count
                    FROM work_items children
                    WHERE children.parent_id = w.id
                ) ca ON TRUE"""

            # When the caller asked for the total, compute it inline via a
            # window function over the filtered rowset. Postgres reuses the
            # outer scan so the extra cost is ~1-2ms; we save one full
            # connection checkout + SET LOCAL + Neon RTT chain.
            _total_col = ", COUNT(*) OVER()::bigint AS _total" if include_total else ""

            with conn.cursor() as cur:
                # Always join boards→projects to get the slug for display_id
                # in a single round-trip (eliminates _enrich_display_ids query).
                if needs_board_join:
                    cur.execute(
                        f"""SELECT w.*, p.slug AS _project_slug,
                                   ca.child_count AS _child_count,
                                   ca.completed_child_count AS _completed_child_count
                                   {_total_col}
                            FROM work_items w
                            JOIN boards b ON w.board_id = b.id
                            LEFT JOIN auth.projects p ON b.project_id = p.project_id AND p.archived_at IS NULL
                            {_child_agg_lateral}
                            {where} {order_clause} LIMIT %s OFFSET %s""",
                        values
                    )
                else:
                    cur.execute(
                        f"""SELECT w.*, p.slug AS _project_slug,
                                   ca.child_count AS _child_count,
                                   ca.completed_child_count AS _completed_child_count
                                   {_total_col}
                            FROM work_items w
                            LEFT JOIN boards b ON w.board_id = b.id
                            LEFT JOIN auth.projects p ON b.project_id = p.project_id AND p.archived_at IS NULL
                            {_child_agg_lateral}
                            {where} {order_clause} LIMIT %s OFFSET %s""",
                        values
                    )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="work_item.list", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        items = [self._row_to_work_item(r) for r in results]

        # Apply inline enrichment from the JOIN columns — no extra queries needed.
        for item, row in zip(items, results):
            slug = row.get("_project_slug")
            if slug and item.display_number and not item.display_id:
                item.display_id = f"{slug}-{item.display_number}"
            total = row.get("_child_count") or 0
            completed = row.get("_completed_child_count") or 0
            item.child_count = total
            item.completed_child_count = completed
            item.progress_percent = round((completed / total) * 100, 1) if total > 0 else 0.0

        if include_total:
            # _total is on every row (same value via COUNT(*) OVER()); an
            # empty result set means zero matches.
            total_count = int(results[0]["_total"]) if results else 0
            return items, total_count

        return items

    def count_work_items(
        self,
        *,
        project_id: Optional[str] = None,
        board_id: Optional[str] = None,
        item_type: Optional[WorkItemType] = None,
        item_types: Optional[List[WorkItemType]] = None,
        parent_id: Optional[str] = None,
        status: Optional[WorkItemStatus] = None,
        priority: Optional[WorkItemPriority] = None,
        priorities: Optional[List[WorkItemPriority]] = None,
        assignee_id: Optional[str] = None,
        assignee_type: Optional[str] = None,
        labels: Optional[List[str]] = None,
        sprint_id: Optional[str] = None,
        title_search: Optional[str] = None,
        due_before: Optional[str] = None,
        due_after: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> int:
        """Return the total count of work items matching the given filters."""

        def _query(conn: Any) -> int:
            self._pool.set_tenant_context(conn, org_id, None)
            conditions, values = [], []
            needs_board_join = project_id is not None

            if project_id:
                conditions.append("b.project_id = %s"); values.append(project_id)
            if board_id:
                conditions.append("w.board_id = %s"); values.append(board_id)
            resolved_item_types = item_types if item_types else ([item_type] if item_type else [])
            if resolved_item_types:
                _REVERSE_ALIASES = {"goal": "epic", "feature": "story"}
                accepted_values: list[str] = []
                for resolved_item_type in resolved_item_types:
                    accepted_values.append(resolved_item_type.value)
                    legacy = _REVERSE_ALIASES.get(resolved_item_type.value)
                    if legacy:
                        accepted_values.append(legacy)
                conditions.append("w.item_type = ANY(%s)")
                values.append(list(dict.fromkeys(accepted_values)))
            if parent_id:
                conditions.append("w.parent_id = %s"); values.append(parent_id)
            if status:
                conditions.append("w.status = %s"); values.append(status.value)
            resolved_priorities = priorities if priorities else ([priority] if priority else [])
            if resolved_priorities:
                conditions.append("w.priority = ANY(%s)")
                values.append([resolved_priority.value for resolved_priority in resolved_priorities])
            if assignee_id:
                if assignee_id == "__unassigned__":
                    conditions.append("w.assignee_id IS NULL")
                else:
                    conditions.append("w.assignee_id = %s"); values.append(assignee_id)
            if assignee_type:
                conditions.append("w.assignee_type = %s"); values.append(assignee_type)
            if labels:
                conditions.append("w.labels && %s::varchar[]"); values.append(labels)
            if sprint_id:
                conditions.append("w.sprint_id = %s"); values.append(sprint_id)
            if title_search:
                conditions.append("w.title ILIKE %s"); values.append(f"%{title_search}%")
            if due_before:
                conditions.append("w.due_date <= %s"); values.append(due_before)
            if due_after:
                conditions.append("w.due_date >= %s"); values.append(due_after)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            with conn.cursor() as cur:
                if needs_board_join:
                    cur.execute(
                        f"SELECT COUNT(*) FROM work_items w JOIN boards b ON w.board_id = b.id {where}",
                        values,
                    )
                else:
                    cur.execute(f"SELECT COUNT(*) FROM work_items w {where}", values)
                return cur.fetchone()[0]

        return self._pool.run_query(
            operation="work_item.count", service_prefix="board", executor=_query, telemetry=self._telemetry
        )

    # ------------------------------------------------------------------
    # Upward cascade: auto-promote parent when all children are complete
    # ------------------------------------------------------------------

    def _cascade_parent_completion(
        self,
        item_id: str,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
        _depth: int = 0,
    ) -> List[str]:
        """Walk up the parent chain and mark parents as done when all their children are done.

        Returns list of parent item_ids that were auto-promoted.
        """
        if _depth > 20:
            return []  # safety guard against cycles

        item = self.get_work_item(item_id, org_id=org_id)
        if not item.parent_id:
            return []

        parent = self.get_work_item(item.parent_id, org_id=org_id)

        # Parent already terminal — nothing to do
        terminal = {WorkItemStatus.DONE}
        if parent.status in terminal:
            return []

        # Check whether ALL children of this parent are done
        def _all_children_complete(conn: Any) -> bool:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE status IN ('done')) AS completed
                       FROM work_items
                       WHERE parent_id = %s""",
                    (parent.item_id,),
                )
                row = cur.fetchone()
                total, completed = row[0], row[1]
                return total > 0 and total == completed

        all_done: bool = self._pool.run_query(
            operation="work_item.check_sibling_completion",
            service_prefix="board",
            executor=_all_children_complete,
            telemetry=self._telemetry,
        )

        if not all_done:
            return []

        # All children are complete — promote parent to DONE
        done_column_id: Optional[str] = None
        if parent.board_id:
            matched = self.get_column_by_status_mapping(
                parent.board_id, WorkItemStatus.DONE, org_id=org_id
            )
            if matched:
                done_column_id = matched.column_id

        timestamp = _now()

        def _promote(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if done_column_id:
                    cur.execute(
                        "UPDATE work_items SET status = %s, column_id = %s, updated_at = %s WHERE id = %s",
                        (WorkItemStatus.DONE.value, done_column_id, timestamp, parent.item_id),
                    )
                else:
                    cur.execute(
                        "UPDATE work_items SET status = %s, updated_at = %s WHERE id = %s",
                        (WorkItemStatus.DONE.value, timestamp, parent.item_id),
                    )

        self._pool.run_transaction(
            operation="work_item.cascade_parent_complete",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"parent_id": parent.item_id, "trigger_item_id": item_id},
            executor=_promote,
            telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("evt"),
            event_type=BoardEventType.ITEM_UPDATED,
            board_id=parent.board_id,
            item_id=parent.item_id,
            item_type=parent.item_type,
            actor_id=actor.id,
            actor_type=actor.role,
            timestamp=timestamp,
            payload={"cascade_parent_complete": True, "trigger_item_id": item_id},
            org_id=org_id,
        ))

        promoted = [parent.item_id]
        # Recurse upward
        promoted.extend(
            self._cascade_parent_completion(parent.item_id, actor, org_id=org_id, _depth=_depth + 1)
        )
        return promoted

    def _collect_descendants(self, root_id: str, all_items: List[WorkItem]) -> List[WorkItem]:
        """Collect all descendants of a work item in board-local memory."""
        children_by_parent: Dict[str, List[WorkItem]] = {}
        for item in all_items:
            if not item.parent_id:
                continue
            bucket = children_by_parent.get(item.parent_id)
            if bucket is None:
                children_by_parent[item.parent_id] = [item]
            else:
                bucket.append(item)

        descendants: List[WorkItem] = []
        stack: List[str] = [root_id]
        visited: set[str] = set()

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for child in children_by_parent.get(current, []):
                descendants.append(child)
                stack.append(child.item_id)

        return descendants

    def _compute_rollup_from_items(
        self,
        root: "WorkItem",
        all_items: List["WorkItem"],
        *,
        include_incomplete_descendants: bool = False,
    ) -> WorkItemProgressRollup:
        """Pure computation: rollup stats from a pre-fetched item list (no DB calls)."""
        descendants = self._collect_descendants(root.item_id, all_items)

        counts = ProgressBucketCounts()
        incomplete_items: List[IncompleteWorkItemSummary] = []
        hours_remaining_total = 0.0
        hours_covered_count = 0
        points_remaining_total = 0
        points_covered_count = 0

        for item in descendants:
            counts.total += 1
            bucket = self._STATUS_TO_PROGRESS_BUCKET.get(item.status, "not_started")
            if bucket == "completed":
                counts.completed += 1
            elif bucket == "in_progress":
                counts.in_progress += 1
            else:
                counts.not_started += 1

            if bucket in ("not_started", "in_progress"):
                if include_incomplete_descendants:
                    incomplete_items.append(
                        IncompleteWorkItemSummary(
                            item_id=item.item_id,
                            item_type=item.item_type,
                            title=item.title,
                            status=item.status,
                            parent_id=item.parent_id,
                            assignee_id=item.assignee_id,
                            assignee_type=item.assignee_type,
                            story_points=item.points,
                            estimated_hours=float(item.estimated_hours) if item.estimated_hours is not None else None,
                            actual_hours=float(item.actual_hours) if item.actual_hours is not None else None,
                        )
                    )

                if item.estimated_hours is not None:
                    estimated = float(item.estimated_hours)
                    actual = float(item.actual_hours) if item.actual_hours is not None else 0.0
                    hours_remaining_total += max(estimated - actual, 0.0)
                    hours_covered_count += 1

                if item.points is not None:
                    points_remaining_total += int(item.points)
                    points_covered_count += 1

        actionable_total = counts.total
        completion_percent = 0.0
        if actionable_total > 0:
            completion_percent = round((counts.completed / actionable_total) * 100.0, 1)

        items_remaining = counts.not_started + counts.in_progress
        estimate_coverage_ratio = None
        if items_remaining > 0:
            estimate_coverage_ratio = round(hours_covered_count / items_remaining, 2)

        remaining = RemainingWorkSummary(
            items_remaining=items_remaining,
            estimated_hours_remaining=round(hours_remaining_total, 2) if hours_covered_count > 0 else None,
            points_remaining=points_remaining_total if points_covered_count > 0 else None,
            estimate_coverage_ratio=estimate_coverage_ratio,
        )

        return WorkItemProgressRollup(
            item_id=root.item_id,
            item_type=root.item_type,
            title=root.title,
            status=root.status,
            buckets=counts,
            remaining=remaining,
            completion_percent=completion_percent,
            incomplete_items=incomplete_items,
        )

    def get_work_item_progress_rollup(
        self,
        item_id: str,
        *,
        include_incomplete_descendants: bool = False,
        org_id: Optional[str] = None,
    ) -> WorkItemProgressRollup:
        """Compute a canonical progress rollup for a work item subtree."""
        root = self.get_work_item(item_id, org_id=org_id)
        if not root.board_id:
            raise BoardServiceError(f"Work item {item_id} has no board_id")

        board_items = self.list_work_items(board_id=root.board_id, org_id=org_id, limit=10000, offset=0)
        return self._compute_rollup_from_items(
            root, board_items, include_incomplete_descendants=include_incomplete_descendants,
        )

    def list_board_progress_rollups(
        self,
        board_id: str,
        *,
        item_type: Optional[WorkItemType] = None,
        include_incomplete_descendants: bool = False,
        org_id: Optional[str] = None,
    ) -> List[WorkItemProgressRollup]:
        """Compute progress rollups for top-level board items.

        Fetches all items once and computes rollups in-memory (O(1) DB calls
        regardless of root count).
        """
        self.get_board(board_id, include_columns=False, org_id=org_id)
        all_items = self.list_work_items(board_id=board_id, org_id=org_id, limit=10000, offset=0)
        if item_type is not None:
            roots = [i for i in all_items if i.item_type == item_type]
        else:
            roots = [i for i in all_items if i.parent_id is None]

        return [
            self._compute_rollup_from_items(
                root, all_items, include_incomplete_descendants=include_incomplete_descendants,
            )
            for root in roots
        ]

    # =========================================================================
    # Assignment
    # =========================================================================

    def assign_work_item(
        self, item_id: str, request: AssignWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Assign a work item to a user or agent."""
        item = self.get_work_item(item_id, org_id=org_id)

        # Validate agent exists before assignment
        if request.assignee_type == AssigneeType.AGENT and request.assignee_id:
            if self._agent_validator:
                if not self._agent_validator(request.assignee_id, org_id):
                    raise AssigneeNotFoundError(
                        f"Agent '{request.assignee_id}' not found. "
                        "The agent may have been deleted or is not accessible in this context."
                    )
            else:
                # No validator configured - log warning but allow (backward compatibility)
                import logging
                logging.getLogger(__name__).warning(
                    f"No agent validator configured - skipping validation for agent {request.assignee_id}"
                )

        timestamp = _now()
        previous_assignee = item.assignee_id
        previous_type = item.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE work_items SET assignee_id = %s, assignee_type = %s,
                       assigned_at = %s, assigned_by = %s, updated_at = %s WHERE id = %s""",
                    (request.assignee_id, request.assignee_type.value, timestamp, actor.id, timestamp, item_id),
                )
                # Record history
                cur.execute(
                    """INSERT INTO assignment_history
                       (history_id, project_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at, previous_assignee_id, previous_assignee_type, reason, org_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (_short_id("ahist"), item.project_id, item_id, _history_assignable_type(item.item_type),
                     request.assignee_id, request.assignee_type.value,
                     AssignmentAction.REASSIGNED.value if previous_assignee else AssignmentAction.ASSIGNED.value,
                     actor.id, timestamp, previous_assignee, previous_type.value if previous_type else None,
                     request.reason, org_id),
                )

        try:
            self._pool.run_transaction(
                operation="work_item.assign", service_prefix="board",
                actor=_actor_payload(actor), metadata={"item_id": item_id},
                executor=_execute, telemetry=self._telemetry,
            )
        except BoardServiceError:
            raise
        except Exception as exc:
            logger.exception("assign_work_item transaction failed item_id=%s", item_id)
            raise BoardServiceError(
                "Could not persist assignment. For OAuth-sized user IDs or widened columns, run: "
                f"`alembic upgrade head` (includes 20260402_widen_assignment). Database error: {exc}"
            ) from exc

        updated = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_ASSIGNED,
            board_id=updated.board_id, item_id=item_id, item_type=updated.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={"assignee_id": request.assignee_id, "assignee_type": request.assignee_type.value},
            org_id=org_id,
        ))
        return updated

    def unassign_work_item(
        self, item_id: str, actor: Actor, *, reason: Optional[str] = None, org_id: Optional[str] = None
    ) -> WorkItem:
        """Unassign a work item."""
        item = self.get_work_item(item_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE work_items SET assignee_id = NULL, assignee_type = NULL,
                       assigned_at = NULL, assigned_by = NULL, updated_at = %s WHERE id = %s""",
                    (timestamp, item_id),
                )
                if item.assignee_id:
                    cur.execute(
                        """INSERT INTO assignment_history
                           (history_id, project_id, assignable_id, assignable_type, assignee_id, assignee_type,
                            action, performed_by, performed_at, previous_assignee_id, previous_assignee_type, reason, org_id)
                           VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)""",
                        (_short_id("ahist"), item.project_id, item_id, _history_assignable_type(item.item_type),
                         AssignmentAction.UNASSIGNED.value, actor.id, timestamp,
                         item.assignee_id, item.assignee_type.value if item.assignee_type else None,
                         reason, org_id),
                    )

        try:
            self._pool.run_transaction(
                operation="work_item.unassign", service_prefix="board",
                actor=_actor_payload(actor), metadata={"item_id": item_id},
                executor=_execute, telemetry=self._telemetry,
            )
        except BoardServiceError:
            raise
        except Exception as exc:
            logger.exception("unassign_work_item transaction failed item_id=%s", item_id)
            raise BoardServiceError(
                "Could not persist unassignment. Run `alembic upgrade head` if you see varchar length errors. "
                f"Database error: {exc}"
            ) from exc

        updated = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_UNASSIGNED,
            board_id=updated.board_id, item_id=item_id, item_type=updated.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={}, org_id=org_id,
        ))
        return updated

    # =========================================================================
    # Sprint CRUD
    # =========================================================================

    def create_sprint(
        self, request: CreateSprintRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Sprint:
        timestamp = _now()
        sprint_id: Optional[str] = None

        def _execute(conn: Any) -> None:
            nonlocal sprint_id
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sprints (board_id, name, goal, status,
                       start_date, end_date, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (request.board_id, request.name,
                     request.goal, SprintStatus.PLANNING.value, request.start_date,
                     request.end_date, timestamp, timestamp),
                )
                result = cur.fetchone()
                if result:
                    sprint_id = str(result[0])

        self._pool.run_transaction(
            operation="sprint.create", service_prefix="board",
            actor=_actor_payload(actor), metadata={},
            executor=_execute, telemetry=self._telemetry,
        )
        if not sprint_id:
            raise BoardServiceError("Failed to create sprint")
        return self.get_sprint(sprint_id, org_id=org_id)

    def get_sprint(self, sprint_id: str, *, org_id: Optional[str] = None) -> Sprint:
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sprints WHERE id = %s", (sprint_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="sprint.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise BoardServiceError(f"Sprint {sprint_id} not found")
        return Sprint(
            sprint_id=str(result["id"]), project_id=None,
            board_id=str(result["board_id"]), name=result["name"], goal=result.get("goal"),
            status=SprintStatus(result["status"].strip("'") if result["status"] else "planning"),
            start_date=result.get("start_date"), end_date=result.get("end_date"),
            velocity_planned=None,
            velocity_completed=None,
            metadata={},
            created_at=result["created_at"], updated_at=result["updated_at"],
            created_by=None, org_id=org_id,
        )

    def update_sprint(
        self, sprint_id: str, request: UpdateSprintRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Sprint:
        self.get_sprint(sprint_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates, values = [], []
            if request.name is not None:
                updates.append("name = %s"); values.append(request.name)
            if request.goal is not None:
                updates.append("goal = %s"); values.append(request.goal)
            if request.status is not None:
                updates.append("status = %s"); values.append(request.status.value)
            if request.start_date is not None:
                updates.append("start_date = %s"); values.append(request.start_date)
            if request.end_date is not None:
                updates.append("end_date = %s"); values.append(request.end_date)
            # Note: velocity_planned not in current DB schema
            if not updates:
                return
            updates.append("updated_at = %s"); values.append(timestamp)
            values.append(sprint_id)
            with conn.cursor() as cur:
                cur.execute(f"UPDATE sprints SET {', '.join(updates)} WHERE id = %s", values)

        self._pool.run_transaction(
            operation="sprint.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"sprint_id": sprint_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_sprint(sprint_id, org_id=org_id)

    def delete_sprint(self, sprint_id: str, actor: Actor, *, org_id: Optional[str] = None) -> DeleteResult:
        self.get_sprint(sprint_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sprints WHERE id = %s", (sprint_id,))

        self._pool.run_transaction(
            operation="sprint.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"sprint_id": sprint_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=sprint_id, deleted_type="sprint")

    # =========================================================================
    # Sprint Membership
    # =========================================================================

    def add_story_to_sprint(
        self,
        sprint_id: str,
        story_id: str,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> None:
        """Add a work item (feature) to a sprint.

        Named add_story_to_sprint for backward compatibility with the
        sprint_stories DB table. Accepts any work item ID.
        """
        self.get_sprint(sprint_id, org_id=org_id)
        # Validate the work item exists
        self.get_work_item(story_id, org_id=org_id)

        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sprint_stories (sprint_id, story_id, added_at, added_by, org_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (sprint_id, story_id) DO NOTHING
                    """,
                    (sprint_id, story_id, timestamp, actor.id, org_id),
                )

        self._pool.run_transaction(
            operation="sprint_story.add",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"sprint_id": sprint_id, "story_id": story_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    def list_sprint_stories(self, sprint_id: str, *, org_id: Optional[str] = None) -> List[SprintStory]:
        """List work items in a sprint.

        Named list_sprint_stories for backward compatibility with the
        sprint_stories DB table.
        """
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sprint_id, story_id, added_at, added_by FROM sprint_stories WHERE sprint_id = %s ORDER BY added_at ASC",
                    (sprint_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="sprint_story.list",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        return [
            SprintStory(
                sprint_id=str(r["sprint_id"]),
                story_id=str(r["story_id"]),
                added_at=r.get("added_at"),
                added_by=r.get("added_by"),
            )
            for r in results
        ]

    # =========================================================================
    # Label CRUD Operations
    # =========================================================================

    def create_label(
        self,
        project_id: str,
        request: CreateLabelRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Label:
        """Create a new label for a project."""
        label_id = _short_id("lbl")
        timestamp = _now()

        def _execute(conn: Any) -> Dict:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO labels (label_id, project_id, name, color, description, created_at, updated_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING label_id, project_id, name, color, description, created_at, updated_at, created_by
                    """,
                    (
                        label_id,
                        project_id,
                        request.name,
                        request.color.value,
                        request.description,
                        timestamp,
                        timestamp,
                        actor.id,
                    ),
                )
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, cur.fetchone()))

        row = self._pool.run_transaction(
            operation="label.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"label_id": label_id, "project_id": project_id, "name": request.name},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return self._row_to_label(row)

    def get_label(self, label_id: str, *, org_id: Optional[str] = None) -> Label:
        """Get a label by ID."""
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT label_id, project_id, name, color, description, created_at, updated_at, created_by FROM labels WHERE label_id = %s",
                    (label_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))

        row = self._pool.run_query(
            operation="label.get",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        if not row:
            raise BoardServiceError(f"Label {label_id} not found")
        return self._row_to_label(row)

    def list_labels(
        self,
        project_id: str,
        *,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> LabelListResponse:
        """List all labels for a project."""
        def _query(conn: Any) -> tuple[List[Dict], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Get total count
                cur.execute("SELECT COUNT(*) FROM labels WHERE project_id = %s", (project_id,))
                total = cur.fetchone()[0]

                # Get labels
                cur.execute(
                    "SELECT label_id, project_id, name, color, description, created_at, updated_at, created_by FROM labels WHERE project_id = %s ORDER BY name ASC LIMIT %s OFFSET %s",
                    (project_id, limit, offset),
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                return rows, total

        rows, total = self._pool.run_query(
            operation="label.list",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        return LabelListResponse(
            labels=[self._row_to_label(r) for r in rows],
            total=total,
        )

    def update_label(
        self,
        label_id: str,
        request: UpdateLabelRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Label:
        """Update a label."""
        # First verify label exists
        self.get_label(label_id, org_id=org_id)

        def _execute(conn: Any) -> Dict:
            self._pool.set_tenant_context(conn, org_id, actor.id)

            # Build dynamic UPDATE
            updates, values = [], []
            if request.name is not None:
                updates.append("name = %s")
                values.append(request.name)
            if request.color is not None:
                updates.append("color = %s")
                values.append(request.color.value)
            if request.description is not None:
                updates.append("description = %s")
                values.append(request.description)

            if not updates:
                # No changes, return existing
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT label_id, project_id, name, color, description, created_at, updated_at, created_by FROM labels WHERE label_id = %s",
                        (label_id,),
                    )
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, cur.fetchone()))

            # updated_at is handled by trigger, but we set it explicitly for immediate response
            updates.append("updated_at = NOW()")
            values.append(label_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE labels SET {', '.join(updates)} WHERE label_id = %s RETURNING label_id, project_id, name, color, description, created_at, updated_at, created_by",
                    values,
                )
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, cur.fetchone()))

        row = self._pool.run_transaction(
            operation="label.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"label_id": label_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return self._row_to_label(row)

    def delete_label(
        self,
        label_id: str,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> DeleteResult:
        """Delete a label."""
        # First verify label exists
        label = self.get_label(label_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM labels WHERE label_id = %s", (label_id,))

        self._pool.run_transaction(
            operation="label.delete",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"label_id": label_id, "project_id": label.project_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=label_id, deleted_type="label")

    def _row_to_label(self, row: Dict) -> Label:
        """Convert a database row to a Label model."""
        return Label(
            label_id=row["label_id"],
            project_id=row["project_id"],
            name=row["name"],
            color=LabelColor(row["color"]) if row["color"] else LabelColor.GRAY,
            description=row.get("description"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row.get("created_by"),
        )

    # =========================================================================
    # Work Item Comments
    # =========================================================================

    def validate_author(
        self,
        author_id: str,
        author_type: str,
        *,
        org_id: Optional[str] = None,
    ) -> bool:
        """
        Validate that an author_id exists in the appropriate table.

        Args:
            author_id: The ID to validate
            author_type: Either "user" or "agent"
            org_id: Optional organization context

        Returns:
            True if author exists, raises AuthorNotFoundError otherwise.
        """
        if author_type not in ("user", "agent"):
            raise BoardServiceError(f"Invalid author_type '{author_type}', must be 'user' or 'agent'")

        def _query(conn: Any) -> bool:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                if author_type == "user":
                    cur.execute(
                        "SELECT 1 FROM auth.users WHERE user_id = %s",
                        (author_id,),
                    )
                else:  # agent
                    cur.execute(
                        "SELECT 1 FROM execution.agents WHERE agent_id = %s",
                        (author_id,),
                    )
                return cur.fetchone() is not None

        exists = self._pool.run_query(
            operation="author.validate",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        if not exists:
            raise AuthorNotFoundError(
                f"Author {author_id} not found in {author_type}s table"
            )
        return True

    def add_comment(
        self,
        work_item_id: str,
        author_id: str,
        author_type: str,
        content: str,
        actor: Actor,
        *,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add a comment to a work item.

        Args:
            work_item_id: The work item to comment on
            author_id: ID of the comment author (user or agent)
            author_type: "user" or "agent"
            content: Comment text
            actor: The actor performing the operation
            run_id: Optional link to an execution run
            metadata: Optional extra data
            org_id: Organization context

        Returns:
            Dict with comment data including comment_id
        """
        # Validate work item exists
        self.get_work_item(work_item_id, org_id=org_id)

        # Validate author exists
        self.validate_author(author_id, author_type, org_id=org_id)

        comment_id = str(uuid.uuid4())  # Use UUID instead of short ID
        timestamp = _now()
        meta_json = json.dumps(metadata or {})

        result_holder: List[Dict] = []

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO board.work_item_comments
                        (id, work_item_id, author_id, author_type, content, run_id, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    RETURNING id, work_item_id, author_id, author_type, content, run_id, metadata, created_at, updated_at
                    """,
                    (comment_id, work_item_id, author_id, author_type, content, run_id, meta_json, timestamp, timestamp),
                )
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if row:
                    result_holder.append(dict(zip(cols, row)))

        self._pool.run_transaction(
            operation="comment.add",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"work_item_id": work_item_id, "comment_id": comment_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        if not result_holder:
            raise BoardServiceError(f"Failed to create comment for work item {work_item_id}")

        result = result_holder[0]
        return {
            "comment_id": str(result["id"]),
            "work_item_id": str(result["work_item_id"]),
            "author_id": result["author_id"],
            "author_type": result["author_type"],
            "content": result["content"],
            "run_id": result.get("run_id"),
            "metadata": _parse_jsonb(result.get("metadata"), {}),
            "created_at": result["created_at"].isoformat() if result.get("created_at") else None,
            "updated_at": result["updated_at"].isoformat() if result.get("updated_at") else None,
        }

    def list_comments(
        self,
        work_item_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        org_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List comments on a work item.

        Args:
            work_item_id: The work item to get comments for
            limit: Maximum number of comments to return
            offset: Number of comments to skip
            org_id: Organization context

        Returns:
            List of comment dicts, ordered by created_at ascending (oldest first)
        """
        # Validate work item exists
        self.get_work_item(work_item_id, org_id=org_id)

        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, work_item_id, author_id, author_type, content, run_id, metadata, created_at, updated_at
                    FROM board.work_item_comments
                    WHERE work_item_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s OFFSET %s
                    """,
                    (work_item_id, limit, offset),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        rows = self._pool.run_query(
            operation="comment.list",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )

        return [
            {
                "comment_id": str(row["id"]),
                "work_item_id": str(row["work_item_id"]),
                "author_id": row["author_id"],
                "author_type": row["author_type"],
                "content": row["content"],
                "run_id": str(row["run_id"]) if row.get("run_id") else None,
                "metadata": _parse_jsonb(row.get("metadata"), {}),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            }
            for row in rows
        ]

    def get_column_by_status_mapping(
        self,
        board_id: str,
        status_mapping: WorkItemStatus,
        *,
        org_id: Optional[str] = None,
    ) -> Optional[BoardColumn]:
        """
        Get a column by its status mapping.

        Args:
            board_id: The board to search
            status_mapping: The WorkItemStatus to find
            org_id: Organization context

        Returns:
            BoardColumn if found, None otherwise
        """
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # First try exact status_mapping match
                cur.execute(
                    """
                    SELECT * FROM columns
                    WHERE board_id = %s::uuid AND status_mapping = %s
                    ORDER BY position ASC
                    LIMIT 1
                    """,
                    (board_id, status_mapping.value),
                )
                row = cur.fetchone()
                if not row:
                    # Fallback: infer from column name for columns with NULL status_mapping
                    name_candidates = [
                        name for name, st in BoardService._COLUMN_NAME_TO_STATUS.items()
                        if st == status_mapping
                    ]
                    if name_candidates:
                        placeholders = ",".join(["%s"] * len(name_candidates))
                        cur.execute(
                            f"""
                            SELECT * FROM columns
                            WHERE board_id = %s::uuid
                              AND status_mapping IS NULL
                              AND LOWER(TRIM(name)) IN ({placeholders})
                            ORDER BY position ASC
                            LIMIT 1
                            """,
                            (board_id, *name_candidates),
                        )
                        row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="column.get_by_status",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )

        if not result:
            return None

        return BoardColumn(
            column_id=str(result["id"]),
            board_id=str(result["board_id"]),
            name=result["name"],
            position=result["position"],
            status_mapping=WorkItemStatus(result["status_mapping"]) if result.get("status_mapping") else WorkItemStatus.BACKLOG,
            wip_limit=result.get("wip_limit"),
            settings={},
            created_at=result["created_at"],
            updated_at=result.get("updated_at") or result["created_at"],
        )
