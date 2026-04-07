"""Work item migration between Amprealize contexts.

This module implements migration of work items (goals, features, tasks) between
different storage backends (e.g., SQLite to PostgreSQL, or between PostgreSQL
instances).

Features:
- Filter expression support (by type, status, project, labels)
- Dry-run mode for preview without changes
- Conflict detection and resolution strategies
- Parent-child relationship preservation
- Migration report with ID mapping
- Progress indicator

Usage:
    amprealize items migrate local-pg production \
        --filter "type=goal,status=in_progress" \
        --dry-run

    amprealize items migrate staging production \
        --project proj-123 \
        --on-conflict skip \
        --yes
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from amprealize.multi_tenant.board_contracts import (
    Board,
    BoardSettings,
    CreateBoardRequest,
    CreateWorkItemRequest,
    WorkItem,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)
from amprealize.services.board_service import BoardService, Actor
from amprealize.storage.postgres_pool import PostgresPool
from amprealize.storage.sqlite_pool import SQLitePool
from amprealize.context import (
    get_current_context,
    list_contexts,
    validate_context_connection,
    _context_to_config,
    _load_raw_config,
    _is_v2_config,
)

logger = logging.getLogger(__name__)


def _parse_dt(val: object, default: datetime) -> datetime:
    """Parse a datetime value from SQLite TEXT or return *default*."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return default


# ==============================================================================
# Enums and Constants
# ==============================================================================

class ConflictResolution(str, Enum):
    """How to handle conflicts during migration."""
    SKIP = "skip"           # Skip items that conflict
    OVERWRITE = "overwrite" # Replace existing items
    RENAME = "rename"       # Add suffix to conflicting titles
    FAIL = "fail"          # Abort migration on first conflict


class MigrationStatus(str, Enum):
    """Status of an individual item migration."""
    PENDING = "pending"
    SUCCESS = "success"
    SKIPPED = "skipped"
    CONFLICT = "conflict"
    FAILED = "failed"


# ==============================================================================
# Data Classes
# ==============================================================================

@dataclass
class FilterExpression:
    """Parsed filter expression for work items."""
    item_type: Optional[WorkItemType] = None
    status: Optional[WorkItemStatus] = None
    priority: Optional[WorkItemPriority] = None
    project_id: Optional[str] = None
    board_id: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    title_search: Optional[str] = None
    parent_id: Optional[str] = None

    @classmethod
    def parse(cls, expr: Optional[str]) -> "FilterExpression":
        """Parse a filter expression string.

        Format: key=value,key=value,...
        Supported keys: type, status, priority, project, board, labels, title, parent

        Examples:
            type=goal
            type=feature,status=in_progress
            labels=bug,priority=high
            project=proj-123,type=task
        """
        result = cls()
        if not expr:
            return result

        for part in expr.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()

            if key == "type":
                try:
                    result.item_type = WorkItemType(value.lower())
                except ValueError:
                    logger.warning(f"Unknown item type: {value}")
            elif key == "status":
                try:
                    result.status = WorkItemStatus(value.lower().replace("-", "_"))
                except ValueError:
                    logger.warning(f"Unknown status: {value}")
            elif key == "priority":
                try:
                    result.priority = WorkItemPriority(value.lower())
                except ValueError:
                    logger.warning(f"Unknown priority: {value}")
            elif key == "project":
                result.project_id = value
            elif key == "board":
                result.board_id = value
            elif key in ("labels", "label"):
                result.labels.extend(v.strip() for v in value.split("|") if v.strip())
            elif key == "title":
                result.title_search = value
            elif key == "parent":
                result.parent_id = value

        return result


@dataclass
class ItemMigrationResult:
    """Result of migrating a single item."""
    source_id: str
    source_title: str
    item_type: WorkItemType
    status: MigrationStatus
    target_id: Optional[str] = None
    error: Optional[str] = None
    parent_source_id: Optional[str] = None
    parent_target_id: Optional[str] = None
    children_count: int = 0


@dataclass
class MigrationReport:
    """Complete migration report."""
    source_context: str
    target_context: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    dry_run: bool = False
    filter_expression: Optional[str] = None
    conflict_resolution: ConflictResolution = ConflictResolution.SKIP

    # Statistics
    total_items: int = 0
    successful: int = 0
    skipped: int = 0
    conflicts: int = 0
    failed: int = 0

    # Detailed results
    items: List[ItemMigrationResult] = field(default_factory=list)
    id_mapping: Dict[str, str] = field(default_factory=dict)  # source_id -> target_id

    # Boards/projects mapping
    board_mapping: Dict[str, str] = field(default_factory=dict)
    project_mapping: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "source_context": self.source_context,
            "target_context": self.target_context,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "dry_run": self.dry_run,
            "filter_expression": self.filter_expression,
            "conflict_resolution": self.conflict_resolution.value,
            "statistics": {
                "total_items": self.total_items,
                "successful": self.successful,
                "skipped": self.skipped,
                "conflicts": self.conflicts,
                "failed": self.failed,
            },
            "id_mapping": self.id_mapping,
            "board_mapping": self.board_mapping,
            "project_mapping": self.project_mapping,
            "items": [
                {
                    "source_id": item.source_id,
                    "source_title": item.source_title,
                    "item_type": item.item_type.value,
                    "status": item.status.value,
                    "target_id": item.target_id,
                    "error": item.error,
                }
                for item in self.items
            ],
        }


# ==============================================================================
# Progress Callback
# ==============================================================================

ProgressCallback = Callable[[int, int, str], None]


def default_progress(current: int, total: int, message: str) -> None:
    """Default progress callback - prints to stdout."""
    width = 40
    filled = int(width * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    pct = (current / total * 100) if total > 0 else 0
    print(f"\r[{bar}] {pct:5.1f}% {message[:40]:<40}", end="", flush=True)
    if current == total:
        print()  # Newline when done


def quiet_progress(current: int, total: int, message: str) -> None:
    """Quiet progress callback - no output."""
    pass


# ==============================================================================
# SQLite Adapter
# ==============================================================================
# BoardService SQL is 100% PostgreSQL-specific (%s params, ::uuid casts,
# RETURNING clauses, ILIKE, && array operators).  This adapter provides the
# same operations using SQLite-compatible SQL so migration can read from and
# write to SQLite-backed contexts.

_PRIORITY_TO_INT: Dict[str, int] = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_INT_TO_PRIORITY: Dict[int, WorkItemPriority] = {
    4: WorkItemPriority.CRITICAL,
    3: WorkItemPriority.HIGH,
    2: WorkItemPriority.MEDIUM,
    1: WorkItemPriority.LOW,
}


class _SQLiteAdapter:
    """Provides BoardService-equivalent operations using SQLite-compatible SQL.

    Only implements the subset of methods needed by MigrationEngine:
    list_boards, get_board, create_board, list_work_items, create_work_item.
    """

    def __init__(self, pool: SQLitePool) -> None:
        self._pool = pool
        # Check if parent_id column exists (added by script, not in m001)
        self._has_parent_id = self._check_column_exists("work_items", "parent_id")

    def _check_column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in a SQLite table."""
        def _query(conn: Any) -> bool:
            with conn.cursor() as cur:
                cur.execute(f"PRAGMA table_info({table})")
                cols = [row[1] if isinstance(row, tuple) else row["name"] for row in cur.fetchall()]
                return column in cols
        return self._pool.run_query(
            operation=f"check_column.{table}.{column}",
            service_prefix="migration",
            executor=_query,
        )

    # ------------------------------------------------------------------
    # Row → model converters
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_board(row: Any) -> Board:
        """Convert a SQLite row to a Board model."""
        # Support both dict-like (sqlite3.Row) and tuple rows
        if isinstance(row, dict) or hasattr(row, "keys"):
            r = dict(row)
        else:
            # Shouldn't happen with row_factory=Row, but be safe
            now = datetime.now(timezone.utc)
            return Board(board_id=str(row[0]), name=str(row[3]), created_at=now, updated_at=now)

        settings = BoardSettings()
        if r.get("settings"):
            try:
                settings = BoardSettings(**json.loads(r["settings"]))
            except Exception:
                pass

        now = datetime.now(timezone.utc)
        return Board(
            board_id=str(r["id"]),
            project_id=r.get("project_id"),
            name=r["name"],
            description=r.get("description"),
            settings=settings,
            created_at=_parse_dt(r.get("created_at"), now),
            updated_at=_parse_dt(r.get("updated_at"), now),
            created_by=r.get("created_by"),
            is_default=False,
            org_id=r.get("org_id"),
            display_number=r.get("display_number"),
        )

    def _row_to_work_item(self, row: Any) -> WorkItem:
        """Convert a SQLite row to a WorkItem model."""
        if isinstance(row, dict) or hasattr(row, "keys"):
            r = dict(row)
        else:
            now = datetime.now(timezone.utc)
            return WorkItem(
                item_id=str(row[0]), title=str(row[3]), item_type=WorkItemType.TASK,
                story_points=None, estimated_hours=None, actual_hours=None,
                color=None, created_at=now, updated_at=now, created_by="unknown",
            )

        # Parse priority integer → enum
        priority_int = r.get("priority", 0)
        priority = _INT_TO_PRIORITY.get(priority_int, WorkItemPriority.MEDIUM)

        # Parse JSON labels
        labels: List[str] = []
        raw_labels = r.get("labels")
        if raw_labels:
            try:
                parsed = json.loads(raw_labels)
                if isinstance(parsed, list):
                    labels = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Parse JSON metadata
        metadata: Dict[str, Any] = {}
        raw_meta = r.get("metadata")
        if raw_meta:
            try:
                parsed = json.loads(raw_meta)
                if isinstance(parsed, dict):
                    metadata = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Map item_type string → enum
        try:
            item_type = WorkItemType(r.get("item_type", "task"))
        except ValueError:
            item_type = WorkItemType.TASK

        # Map status string → enum
        try:
            status = WorkItemStatus(r.get("status", "open"))
        except ValueError:
            status = WorkItemStatus.BACKLOG

        parent_id = r.get("parent_id") if self._has_parent_id else None

        now = datetime.now(timezone.utc)
        return WorkItem(
            item_id=str(r["id"]),
            item_type=item_type,
            project_id=r.get("project_id"),
            board_id=r.get("board_id"),
            column_id=r.get("column_id"),
            parent_id=parent_id,
            title=r.get("title", ""),
            description=r.get("description"),
            status=status,
            priority=priority,
            position=r.get("position", 0),
            story_points=None,
            estimated_hours=None,
            actual_hours=None,
            color=None,
            labels=labels,
            metadata=metadata,
            due_date=r.get("due_date"),
            assignee_id=r.get("assignee_id"),
            run_id=r.get("run_id"),
            org_id=r.get("org_id"),
            display_number=r.get("display_number"),
            created_at=_parse_dt(r.get("created_at"), now),
            updated_at=_parse_dt(r.get("updated_at"), now),
            created_by=r.get("created_by") or "unknown",
        )

    # ------------------------------------------------------------------
    # Board operations
    # ------------------------------------------------------------------

    def list_boards(self, *, org_id: Optional[str] = None) -> List[Board]:
        """List all boards, optionally filtered by org_id."""
        def _query(conn: Any) -> List[Board]:
            with conn.cursor() as cur:
                if org_id:
                    cur.execute(
                        "SELECT * FROM boards WHERE org_id = ? ORDER BY created_at DESC",
                        (org_id,),
                    )
                else:
                    cur.execute("SELECT * FROM boards ORDER BY created_at DESC")
                return [self._row_to_board(row) for row in cur.fetchall()]

        return self._pool.run_query(
            operation="board.list", service_prefix="migration", executor=_query,
        )

    def get_board(self, board_id: str, *, org_id: Optional[str] = None) -> Board:
        """Get a single board by ID."""
        def _query(conn: Any) -> Board:
            with conn.cursor() as cur:
                if org_id:
                    cur.execute(
                        "SELECT * FROM boards WHERE id = ? AND org_id = ?",
                        (board_id, org_id),
                    )
                else:
                    cur.execute("SELECT * FROM boards WHERE id = ?", (board_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Board '{board_id}' not found")
                return self._row_to_board(row)

        return self._pool.run_query(
            operation="board.get", service_prefix="migration", executor=_query,
        )

    def create_board(
        self,
        request: CreateBoardRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Board:
        """Create a new board."""
        board_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        settings = request.settings or BoardSettings()

        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                cur.execute("PRAGMA foreign_keys = OFF")
                # Allocate display number
                display_num = None
                if request.project_id:
                    display_num = self._next_display_number(cur, request.project_id, "board")

                cur.execute(
                    """INSERT INTO boards
                       (id, project_id, name, description, settings,
                        created_at, updated_at, created_by, org_id, display_number)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        board_id, request.project_id, request.name,
                        request.description, json.dumps(settings.model_dump()),
                        timestamp, timestamp, actor.id, org_id, display_num,
                    ),
                )

        self._pool.run_transaction(
            operation="board.create", service_prefix="migration",
            actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
            metadata={"board_id": board_id},
            executor=_execute,
        )
        return self.get_board(board_id, org_id=org_id)

    # ------------------------------------------------------------------
    # Work item operations
    # ------------------------------------------------------------------

    def list_work_items(
        self,
        *,
        project_id: Optional[str] = None,
        board_id: Optional[str] = None,
        item_type: Optional[WorkItemType] = None,
        status: Optional[WorkItemStatus] = None,
        priority: Optional[WorkItemPriority] = None,
        labels: Optional[List[str]] = None,
        title_search: Optional[str] = None,
        parent_id: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[WorkItem]:
        """List work items with optional filters."""
        def _query(conn: Any) -> List[WorkItem]:
            clauses: List[str] = []
            params: List[Any] = []

            if project_id:
                clauses.append("project_id = ?")
                params.append(project_id)
            if board_id:
                clauses.append("board_id = ?")
                params.append(board_id)
            if item_type:
                clauses.append("item_type = ?")
                params.append(item_type.value)
            if status:
                clauses.append("status = ?")
                params.append(status.value)
            if priority:
                clauses.append("priority = ?")
                params.append(_PRIORITY_TO_INT.get(priority.value, 2))
            if org_id:
                clauses.append("org_id = ?")
                params.append(org_id)
            if parent_id and self._has_parent_id:
                clauses.append("parent_id = ?")
                params.append(parent_id)
            if title_search:
                # SQLite LIKE is case-insensitive for ASCII by default
                clauses.append("title LIKE ?")
                params.append(f"%{title_search}%")
            if labels:
                # Labels stored as JSON array text; use LIKE for each label
                for label in labels:
                    clauses.append("labels LIKE ?")
                    params.append(f'%"{label}"%')

            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"SELECT * FROM work_items{where} ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return [self._row_to_work_item(row) for row in cur.fetchall()]

        return self._pool.run_query(
            operation="work_item.list", service_prefix="migration", executor=_query,
        )

    def create_work_item(
        self,
        request: CreateWorkItemRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> WorkItem:
        """Create a work item in SQLite."""
        item_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        # Default status by type
        initial_status = WorkItemStatus.BACKLOG

        priority_int = _PRIORITY_TO_INT.get(request.priority.value, 2)
        labels_json = json.dumps(request.labels) if request.labels else None
        metadata_json = json.dumps(request.metadata) if request.metadata else None

        # Resolve project_id from board if not set
        project_id = request.project_id

        def _execute(conn: Any) -> None:
            nonlocal project_id
            with conn.cursor() as cur:
                cur.execute("PRAGMA foreign_keys = OFF")
                if not project_id and request.board_id:
                    cur.execute("SELECT project_id FROM boards WHERE id = ?", (request.board_id,))
                    prow = cur.fetchone()
                    if prow:
                        project_id = prow[0] if isinstance(prow, tuple) else prow["project_id"]

                # Allocate display number
                display_num = None
                if project_id:
                    display_num = self._next_display_number(cur, project_id, "work_item")

                # Build INSERT dynamically based on available columns
                columns = [
                    "id", "item_type", "project_id", "board_id", "column_id",
                    "title", "description", "status", "priority", "position",
                    "labels", "metadata", "created_at", "updated_at",
                    "display_number", "org_id",
                ]
                values = [
                    item_id, request.item_type.value, project_id,
                    request.board_id, request.column_id,
                    request.title, request.description,
                    initial_status.value, priority_int, 0,
                    labels_json, metadata_json, timestamp, timestamp,
                    display_num, org_id,
                ]

                if self._has_parent_id:
                    columns.append("parent_id")
                    values.append(request.parent_id)

                placeholders = ", ".join("?" * len(columns))
                col_str = ", ".join(columns)
                cur.execute(
                    f"INSERT INTO work_items ({col_str}) VALUES ({placeholders})",
                    tuple(values),
                )

        self._pool.run_transaction(
            operation="work_item.create", service_prefix="migration",
            actor={"id": actor.id, "role": actor.role, "surface": actor.surface},
            metadata={"item_id": item_id},
            executor=_execute,
        )
        # Fetch the newly created item
        def _fetch(conn: Any) -> WorkItem:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM work_items WHERE id = ?", (item_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Created work item '{item_id}' not found")
                return self._row_to_work_item(row)

        return self._pool.run_query(
            operation="work_item.get", service_prefix="migration", executor=_fetch,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _next_display_number(cur: Any, project_id: str, entity_type: str) -> int:
        """Allocate next display number using INSERT OR REPLACE."""
        # Read current value
        cur.execute(
            "SELECT next_number FROM project_counters WHERE project_id = ? AND entity_type = ?",
            (project_id, entity_type),
        )
        row = cur.fetchone()
        if row:
            current = row[0] if isinstance(row, tuple) else row["next_number"]
            new_number = current + 1
            cur.execute(
                "UPDATE project_counters SET next_number = ? WHERE project_id = ? AND entity_type = ?",
                (new_number, project_id, entity_type),
            )
            return current
        else:
            cur.execute(
                "INSERT INTO project_counters (project_id, entity_type, next_number) VALUES (?, ?, ?)",
                (project_id, entity_type, 2),
            )
            return 1


# ==============================================================================
# Migration Engine
# ==============================================================================

class MigrationEngine:
    """Engine for migrating work items between contexts."""

    def __init__(
        self,
        source_context: str,
        target_context: str,
        *,
        dry_run: bool = False,
        conflict_resolution: ConflictResolution = ConflictResolution.SKIP,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self.source_context = source_context
        self.target_context = target_context
        self.dry_run = dry_run
        self.conflict_resolution = conflict_resolution
        self.progress = progress_callback or default_progress

        # Services (initialized on first use)
        _SvcType = Union[BoardService, "_SQLiteAdapter"]
        self._source_service: Optional[Union[BoardService, _SQLiteAdapter]] = None
        self._target_service: Optional[Union[BoardService, _SQLiteAdapter]] = None

    def _load_contexts(self) -> Dict[str, Dict[str, Any]]:
        """Load all contexts from config."""
        data = _load_raw_config()
        if not _is_v2_config(data):
            raise ValueError("Migration requires config v2 format with named contexts")
        return data.get("contexts", {})

    def _get_service_for_context(self, context_name: str) -> "Union[BoardService, _SQLiteAdapter]":
        """Create a service for the given context.

        Returns a BoardService for PostgreSQL backends and _SQLiteAdapter for SQLite.
        """
        contexts = self._load_contexts()
        if context_name not in contexts:
            raise ValueError(f"Context '{context_name}' not found")

        ctx_config = _context_to_config(contexts[context_name])
        backend = ctx_config.storage.backend

        if backend == "postgres":
            dsn = ctx_config.storage.postgres.dsn
            pool = PostgresPool(dsn, schema="board")
            return BoardService(pool=pool)
        elif backend == "sqlite":
            db_path = ctx_config.storage.sqlite.path
            pool = SQLitePool(dsn=db_path, schema="board")
            return _SQLiteAdapter(pool)
        else:
            raise ValueError(
                f"Context '{context_name}' uses '{backend}' backend. "
                "Migration supports 'postgres' and 'sqlite' backends."
            )

    @property
    def source_service(self) -> "Union[BoardService, _SQLiteAdapter]":
        """Get or create source service."""
        if self._source_service is None:
            self._source_service = self._get_service_for_context(self.source_context)
        return self._source_service

    @property
    def target_service(self) -> "Union[BoardService, _SQLiteAdapter]":
        """Get or create target service."""
        if self._target_service is None:
            self._target_service = self._get_service_for_context(self.target_context)
        return self._target_service

    def validate_contexts(self) -> Tuple[bool, List[str]]:
        """Validate both source and target contexts are accessible.

        Returns:
            Tuple of (all_valid, list_of_errors)
        """
        errors = []

        try:
            contexts = self._load_contexts()
        except ValueError as e:
            errors.append(str(e))
            return (False, errors)

        # Check source
        if self.source_context not in contexts:
            errors.append(f"Source context '{self.source_context}' not found")
        else:
            src_cfg = _context_to_config(contexts[self.source_context])
            is_valid, msg = validate_context_connection(src_cfg)
            if not is_valid:
                errors.append(f"Source context error: {msg}")

        # Check target
        if self.target_context not in contexts:
            errors.append(f"Target context '{self.target_context}' not found")
        else:
            tgt_cfg = _context_to_config(contexts[self.target_context])
            is_valid, msg = validate_context_connection(tgt_cfg)
            if not is_valid:
                errors.append(f"Target context error: {msg}")

        # Check same context
        if self.source_context == self.target_context:
            errors.append("Source and target contexts must be different")

        return (len(errors) == 0, errors)

    def list_source_items(
        self,
        filter_expr: Optional[FilterExpression] = None,
        *,
        org_id: Optional[str] = None,
    ) -> List[WorkItem]:
        """List items from source context with optional filtering."""
        filter_expr = filter_expr or FilterExpression()

        return self.source_service.list_work_items(
            project_id=filter_expr.project_id,
            board_id=filter_expr.board_id,
            item_type=filter_expr.item_type,
            status=filter_expr.status,
            priority=filter_expr.priority,
            labels=filter_expr.labels if filter_expr.labels else None,
            title_search=filter_expr.title_search,
            parent_id=filter_expr.parent_id,
            org_id=org_id,
            limit=10000,  # High limit for migration
        )

    def _sort_by_hierarchy(self, items: List[WorkItem]) -> List[WorkItem]:
        """Sort items so parents come before children.

        Order: goals -> features -> tasks
        Within each level, sort by parent_id to group children together.
        """
        epics = [i for i in items if i.item_type == WorkItemType.EPIC]  # EPIC alias = "goal"
        stories = [i for i in items if i.item_type == WorkItemType.STORY]  # STORY alias = "feature"
        tasks = [i for i in items if i.item_type == WorkItemType.TASK]
        bugs = [i for i in items if i.item_type == WorkItemType.BUG]

        # Sort features by parent_id (goal) - put orphans first
        stories.sort(key=lambda s: (s.parent_id or "", s.title))

        # Sort tasks by parent_id (feature) - put orphans first
        tasks.sort(key=lambda t: (t.parent_id or "", t.title))

        # Sort bugs by parent_id - put orphans first
        bugs.sort(key=lambda b: (b.parent_id or "", b.title))

        return epics + stories + tasks + bugs

    def _check_conflict(
        self,
        item: WorkItem,
        existing_items: List[WorkItem],
    ) -> Optional[WorkItem]:
        """Check if item conflicts with existing items in target.

        Conflict is defined as: same title AND same item_type AND same parent_id.
        """
        for existing in existing_items:
            if (
                existing.title == item.title
                and existing.item_type == item.item_type
                and existing.parent_id == item.parent_id
            ):
                return existing
        return None

    def _create_work_item_request(
        self,
        item: WorkItem,
        id_mapping: Dict[str, str],
        board_mapping: Dict[str, str],
    ) -> CreateWorkItemRequest:
        """Create a CreateWorkItemRequest from a source WorkItem.

        Remaps parent_id and board_id using the provided mappings.
        """
        # Remap parent_id if it was migrated
        parent_id = None
        if item.parent_id and item.parent_id in id_mapping:
            parent_id = id_mapping[item.parent_id]
        elif item.parent_id:
            # Parent wasn't migrated - could be filtered out
            parent_id = None  # Create as orphan

        # Remap board_id if available
        board_id = None
        if item.board_id and item.board_id in board_mapping:
            board_id = board_mapping[item.board_id]

        return CreateWorkItemRequest(
            item_type=item.item_type,
            board_id=board_id,
            parent_id=parent_id,
            title=item.title,
            description=item.description,
            priority=item.priority,
            story_points=item.story_points,
            estimated_hours=item.estimated_hours,
            start_date=item.start_date,
            target_date=item.target_date,
            due_date=item.due_date,
            color=item.color,
            labels=item.labels,
            acceptance_criteria=[ac.description for ac in item.acceptance_criteria],
            checklist=[cl.description for cl in item.checklist],
            behavior_id=item.behavior_id,
            metadata=item.metadata,
        )

    def migrate(
        self,
        filter_expr: Optional[FilterExpression] = None,
        *,
        org_id: Optional[str] = None,
        migrate_boards: bool = True,
    ) -> MigrationReport:
        """Execute the migration.

        Args:
            filter_expr: Optional filter to select items
            org_id: Organization ID for multi-tenant isolation
            migrate_boards: Whether to also migrate boards (default True)

        Returns:
            MigrationReport with results and ID mapping
        """
        report = MigrationReport(
            source_context=self.source_context,
            target_context=self.target_context,
            started_at=datetime.now(timezone.utc),
            dry_run=self.dry_run,
            filter_expression=str(filter_expr) if filter_expr else None,
            conflict_resolution=self.conflict_resolution,
        )

        # Validate contexts first
        valid, errors = self.validate_contexts()
        if not valid:
            for error in errors:
                report.items.append(ItemMigrationResult(
                    source_id="",
                    source_title="",
                    item_type=WorkItemType.TASK,
                    status=MigrationStatus.FAILED,
                    error=error,
                ))
                report.failed += 1
            report.completed_at = datetime.now(timezone.utc)
            return report

        # Get items from source
        self.progress(0, 1, "Fetching items from source...")
        source_items = self.list_source_items(filter_expr, org_id=org_id)
        report.total_items = len(source_items)

        if not source_items:
            self.progress(1, 1, "No items to migrate")
            report.completed_at = datetime.now(timezone.utc)
            return report

        # Sort by hierarchy (parents before children)
        sorted_items = self._sort_by_hierarchy(source_items)

        # Migrate boards first if requested
        if migrate_boards:
            self._migrate_boards(sorted_items, report, org_id)

        # Get existing items in target for conflict detection
        self.progress(0, 1, "Checking for conflicts...")
        target_items = self.target_service.list_work_items(org_id=org_id, limit=10000)

        # Migrate items
        actor = Actor(id="migration-cli", role="system", surface="cli")

        for i, item in enumerate(sorted_items):
            self.progress(i + 1, len(sorted_items), f"Migrating: {item.title[:30]}...")

            result = ItemMigrationResult(
                source_id=item.item_id,
                source_title=item.title,
                item_type=item.item_type,
                status=MigrationStatus.PENDING,
                parent_source_id=item.parent_id,
            )

            # Check for conflicts
            conflict = self._check_conflict(item, target_items)
            if conflict:
                result.status = MigrationStatus.CONFLICT

                if self.conflict_resolution == ConflictResolution.FAIL:
                    result.error = f"Conflict with existing item: {conflict.item_id}"
                    result.status = MigrationStatus.FAILED
                    report.items.append(result)
                    report.failed += 1
                    report.completed_at = datetime.now(timezone.utc)
                    return report

                elif self.conflict_resolution == ConflictResolution.SKIP:
                    result.error = f"Skipped: conflicts with {conflict.item_id}"
                    result.status = MigrationStatus.SKIPPED
                    result.target_id = conflict.item_id
                    # Still add to mapping so children can find parent
                    report.id_mapping[item.item_id] = conflict.item_id
                    report.items.append(result)
                    report.skipped += 1
                    report.conflicts += 1
                    continue

                elif self.conflict_resolution == ConflictResolution.RENAME:
                    # Will rename below when creating
                    pass

                elif self.conflict_resolution == ConflictResolution.OVERWRITE:
                    # TODO: Implement update logic
                    result.error = "Overwrite not yet implemented"
                    result.status = MigrationStatus.SKIPPED
                    report.items.append(result)
                    report.skipped += 1
                    continue

            # Create item in target
            if self.dry_run:
                result.status = MigrationStatus.SUCCESS
                result.target_id = f"dry-run-{item.item_id}"
                # Use a fake ID for parent mapping in dry run
                report.id_mapping[item.item_id] = result.target_id
            else:
                try:
                    request = self._create_work_item_request(
                        item,
                        report.id_mapping,
                        report.board_mapping,
                    )

                    # Rename if conflict and using rename strategy
                    if conflict and self.conflict_resolution == ConflictResolution.RENAME:
                        request.title = f"{item.title} (migrated)"

                    new_item = self.target_service.create_work_item(
                        request, actor, org_id=org_id
                    )
                    result.target_id = new_item.item_id
                    result.status = MigrationStatus.SUCCESS
                    report.id_mapping[item.item_id] = new_item.item_id

                    # Also add to target_items for future conflict checks
                    target_items.append(new_item)

                except Exception as e:
                    result.status = MigrationStatus.FAILED
                    result.error = str(e)
                    report.failed += 1
                    report.items.append(result)
                    continue

            # Update parent mapping
            if item.parent_id and item.parent_id in report.id_mapping:
                result.parent_target_id = report.id_mapping[item.parent_id]

            report.items.append(result)

            if result.status == MigrationStatus.SUCCESS:
                report.successful += 1
            elif result.status == MigrationStatus.SKIPPED:
                report.skipped += 1

        report.completed_at = datetime.now(timezone.utc)
        return report

    def _migrate_boards(
        self,
        items: List[WorkItem],
        report: MigrationReport,
        org_id: Optional[str],
    ) -> None:
        """Migrate boards that items belong to."""
        # Collect unique board IDs
        board_ids = set(item.board_id for item in items if item.board_id)
        if not board_ids:
            return

        self.progress(0, len(board_ids), "Migrating boards...")

        # Get existing boards in target
        target_boards = self.target_service.list_boards(org_id=org_id)
        target_board_names = {b.name: b for b in target_boards}

        actor = Actor(id="migration-cli", role="system", surface="cli")

        for i, board_id in enumerate(board_ids):
            try:
                source_board = self.source_service.get_board(board_id, org_id=org_id)

                # Skip boards without project_id (required for creation)
                if not source_board.project_id:
                    logger.warning(f"Skipping board {board_id}: no project_id")
                    continue

                # Check if board with same name exists
                if source_board.name in target_board_names:
                    # Use existing board
                    report.board_mapping[board_id] = target_board_names[source_board.name].board_id
                elif not self.dry_run:
                    # Create new board
                    new_board = self.target_service.create_board(
                        CreateBoardRequest(
                            name=source_board.name,
                            description=source_board.description,
                            project_id=source_board.project_id,
                        ),
                        actor,
                        org_id=org_id,
                    )
                    report.board_mapping[board_id] = new_board.board_id
                else:
                    report.board_mapping[board_id] = f"dry-run-board-{board_id}"

            except Exception as e:
                logger.warning(f"Failed to migrate board {board_id}: {e}")

            self.progress(i + 1, len(board_ids), f"Board: {board_id[:20]}...")


# ==============================================================================
# Helper Functions
# ==============================================================================

def format_migration_summary(report: MigrationReport) -> str:
    """Format a human-readable migration summary."""
    lines = [
        "",
        "═" * 60,
        "MIGRATION SUMMARY",
        "═" * 60,
        f"",
        f"  Source:     {report.source_context}",
        f"  Target:     {report.target_context}",
        f"  Dry Run:    {'Yes' if report.dry_run else 'No'}",
        f"  Started:    {report.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    if report.completed_at:
        duration = (report.completed_at - report.started_at).total_seconds()
        lines.append(f"  Duration:   {duration:.1f}s")

    if report.filter_expression:
        lines.append(f"  Filter:     {report.filter_expression}")

    lines.extend([
        "",
        "  RESULTS",
        "  ─" * 25,
        f"  Total Items:    {report.total_items:>6}",
        f"  ✓ Successful:   {report.successful:>6}",
        f"  ⊘ Skipped:      {report.skipped:>6}",
        f"  ⚡ Conflicts:    {report.conflicts:>6}",
        f"  ✗ Failed:       {report.failed:>6}",
        "",
    ])

    # Show ID mapping if not too large
    if report.id_mapping and len(report.id_mapping) <= 20:
        lines.append("  ID MAPPING")
        lines.append("  ─" * 25)
        for src, tgt in report.id_mapping.items():
            lines.append(f"  {src[:20]:<20} → {tgt[:20]}")
        lines.append("")
    elif report.id_mapping:
        lines.append(f"  ID mapping contains {len(report.id_mapping)} entries")
        lines.append("  Use --output to save full report to file")
        lines.append("")

    lines.append("═" * 60)

    return "\n".join(lines)


def format_items_table(items: List[WorkItem], max_items: int = 20) -> str:
    """Format items as a table for preview."""
    lines = [
        "",
        f"{'TYPE':<8} {'STATUS':<12} {'TITLE':<40} {'ID':<36}",
        "─" * 100,
    ]

    for item in items[:max_items]:
        title = item.title[:38] + ".." if len(item.title) > 40 else item.title
        lines.append(
            f"{item.item_type.value:<8} {item.status.value:<12} {title:<40} {item.item_id}"
        )

    if len(items) > max_items:
        lines.append(f"... and {len(items) - max_items} more items")

    return "\n".join(lines)
