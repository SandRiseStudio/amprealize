#!/usr/bin/env python3
"""
TaskService - Agent Task Tracking and Assignment

PostgreSQL-backed service for managing agent task assignments, status tracking,
and task analytics across the Amprealize platform.

Features:
- Task CRUD operations with UUID generation
- Status workflow (pending → in_progress → completed/failed/blocked/cancelled)
- Priority ordering (1=urgent, 2=high, 3=normal, 4=low)
- Task type categorization (behavior_review, compliance_audit, run_execution, code_review, documentation, testing)
- Filtering by agent_id, status, task_type, behavior_id, run_id
- Task analytics (counts by status, average completion time)
- JSONB metadata for flexible extensions
- Auto-schema initialization with indexes

Schema:
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        task_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        priority INTEGER NOT NULL DEFAULT 3,
        title TEXT NOT NULL,
        description TEXT,
        behavior_id TEXT,
        run_id TEXT,
        metadata JSONB,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMP,
        deadline TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_tasks_agent_id ON tasks(agent_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type);
    CREATE INDEX IF NOT EXISTS idx_tasks_behavior_id ON tasks(behavior_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id);
    CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);

Usage:
    from amprealize.services.task_service import TaskService, CreateTaskRequest

    task_service = TaskService(dsn="postgresql://user:pass@host:5432/db")

    # Create task
    request = CreateTaskRequest(
        agent_id="agent-engineering-01",
        task_type="code_review",
        priority=2,
        title="Review PR #123",
        description="Code review for authentication feature"
    )
    task = task_service.create_task(request)

    # List tasks
    tasks = task_service.list_tasks(ListTasksRequest(
        agent_id="agent-engineering-01",
        status="in_progress",
        limit=10
    ))

    # Update status
    updated = task_service.update_task(UpdateTaskRequest(
        task_id=task.task_id,
        status="completed"
    ))

    # Get analytics
    stats = task_service.get_task_stats(agent_id="agent-engineering-01")
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..storage.postgres_pool import PostgresPool


logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Task type categorization."""
    BEHAVIOR_REVIEW = "behavior_review"
    COMPLIANCE_AUDIT = "compliance_audit"
    RUN_EXECUTION = "run_execution"
    CODE_REVIEW = "code_review"
    DOCUMENTATION = "documentation"
    TESTING = "testing"


class TaskStatus(str, Enum):
    """Task status workflow states."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskPriority(int, Enum):
    """Task priority levels (lower = higher priority)."""
    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


@dataclass
class Task:
    """Task model with full metadata."""
    task_id: str
    agent_id: str
    task_type: str
    status: str
    priority: int
    title: str
    description: Optional[str] = None
    behavior_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    deadline: Optional[datetime] = None


@dataclass
class CreateTaskRequest:
    """Request model for task creation."""
    agent_id: str
    task_type: str
    title: str
    priority: int = 3
    description: Optional[str] = None
    behavior_id: Optional[str] = None
    run_id: Optional[str] = None
    deadline: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class UpdateTaskRequest:
    """Request model for task updates."""
    task_id: str
    status: Optional[str] = None
    priority: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None


@dataclass
class ListTasksRequest:
    """Request model for task listing with filters."""
    agent_id: Optional[str] = None
    status: Optional[str] = None
    task_type: Optional[str] = None
    behavior_id: Optional[str] = None
    run_id: Optional[str] = None
    limit: int = 50


@dataclass
class TaskStats:
    """Task analytics aggregation."""
    total: int = 0
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    cancelled: int = 0
    avg_completion_time_hours: Optional[float] = None


class TaskService:
    """PostgreSQL-backed task tracking service."""

    def __init__(self, dsn: str) -> None:
        """
        Initialize TaskService with PostgreSQL connection.

        Args:
            dsn: PostgreSQL connection string
        """
        self._pool = PostgresPool(dsn=dsn)
        self._logger = logging.getLogger("amprealize.services.task_service")
        self._ensure_schema()
        self._logger.info("TaskService initialized")

    def _ensure_schema(self) -> None:
        """Create tasks table and indexes if they don't exist."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                # Create table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        priority INTEGER NOT NULL DEFAULT 3,
                        title TEXT NOT NULL,
                        description TEXT,
                        behavior_id TEXT,
                        run_id TEXT,
                        metadata JSONB,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        completed_at TIMESTAMP,
                        deadline TIMESTAMP
                    )
                """)

                # Create indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_agent_id ON tasks(agent_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_behavior_id ON tasks(behavior_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)")

                conn.commit()
                self._logger.info("Tasks schema validated")

    def create_task(self, request: CreateTaskRequest) -> Task:
        """
        Create a new task assignment.

        Args:
            request: Task creation parameters

        Returns:
            Created Task instance
        """
        task_id = str(uuid.uuid4())
        now = datetime.utcnow()

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tasks (
                        task_id, agent_id, task_type, status, priority, title,
                        description, behavior_id, run_id, metadata, created_at, updated_at, deadline
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        task_id,
                        request.agent_id,
                        request.task_type,
                        TaskStatus.PENDING.value,
                        request.priority,
                        request.title,
                        request.description,
                        request.behavior_id,
                        request.run_id,
                        json.dumps(request.metadata) if request.metadata else None,
                        now,
                        now,
                        request.deadline,
                    ),
                )
                row = cur.fetchone()
                conn.commit()

                self._logger.info(f"Created task {task_id} for agent {request.agent_id}")
                return self._row_to_task(row)

    def update_task(self, request: UpdateTaskRequest) -> Task:
        """
        Update an existing task.

        Args:
            request: Update parameters

        Returns:
            Updated Task instance

        Raises:
            ValueError: If task not found
        """
        updates = []
        params = []

        if request.status is not None:
            updates.append("status = %s")
            params.append(request.status)

        if request.priority is not None:
            updates.append("priority = %s")
            params.append(request.priority)

        if request.metadata is not None:
            updates.append("metadata = %s")
            params.append(json.dumps(request.metadata))

        if request.completed_at is not None:
            updates.append("completed_at = %s")
            params.append(request.completed_at)

        if not updates:
            # No updates, just return current task
            return self.get_task(request.task_id)

        updates.append("updated_at = %s")
        params.append(datetime.utcnow())
        params.append(request.task_id)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                query = f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = %s RETURNING *"
                cur.execute(query, params)
                row = cur.fetchone()

                if not row:
                    raise ValueError(f"Task not found: {request.task_id}")

                conn.commit()
                self._logger.info(f"Updated task {request.task_id}")
                return self._row_to_task(row)

    def list_tasks(self, request: ListTasksRequest) -> List[Task]:
        """
        List tasks with optional filters.

        Args:
            request: Filter and pagination parameters

        Returns:
            List of Task instances
        """
        conditions = []
        params = []

        if request.agent_id:
            conditions.append("agent_id = %s")
            params.append(request.agent_id)

        if request.status:
            conditions.append("status = %s")
            params.append(request.status)

        if request.task_type:
            conditions.append("task_type = %s")
            params.append(request.task_type)

        if request.behavior_id:
            conditions.append("behavior_id = %s")
            params.append(request.behavior_id)

        if request.run_id:
            conditions.append("run_id = %s")
            params.append(request.run_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(request.limit)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                query = f"""
                    SELECT * FROM tasks
                    {where_clause}
                    ORDER BY priority ASC, created_at DESC
                    LIMIT %s
                """
                cur.execute(query, params)
                rows = cur.fetchall()
                return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str) -> Task:
        """
        Get task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task instance

        Raises:
            ValueError: If task not found
        """
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tasks WHERE task_id = %s", (task_id,))
                row = cur.fetchone()

                if not row:
                    raise ValueError(f"Task not found: {task_id}")

                return self._row_to_task(row)

    def get_task_stats(
        self,
        agent_id: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> TaskStats:
        """
        Get task analytics aggregations.

        Args:
            agent_id: Optional agent filter
            task_type: Optional task type filter

        Returns:
            TaskStats with counts and averages
        """
        conditions = []
        params = []

        if agent_id:
            conditions.append("agent_id = %s")
            params.append(agent_id)

        if task_type:
            conditions.append("task_type = %s")
            params.append(task_type)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                query = f"""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                        SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                        SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked,
                        SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                        AVG(EXTRACT(EPOCH FROM (completed_at - created_at)) / 3600.0) as avg_hours
                    FROM tasks
                    {where_clause}
                """
                cur.execute(query, params)
                row = cur.fetchone()

                return TaskStats(
                    total=int(row[0]) if row[0] else 0,
                    pending=int(row[1]) if row[1] else 0,
                    in_progress=int(row[2]) if row[2] else 0,
                    completed=int(row[3]) if row[3] else 0,
                    failed=int(row[4]) if row[4] else 0,
                    blocked=int(row[5]) if row[5] else 0,
                    cancelled=int(row[6]) if row[6] else 0,
                    avg_completion_time_hours=float(row[7]) if row[7] else None,
                )

    def _row_to_task(self, row: tuple) -> Task:
        """Convert database row to Task model."""
        metadata = json.loads(row[9]) if row[9] else None

        return Task(
            task_id=row[0],
            agent_id=row[1],
            task_type=row[2],
            status=row[3],
            priority=row[4],
            title=row[5],
            description=row[6],
            behavior_id=row[7],
            run_id=row[8],
            metadata=metadata,
            created_at=row[10],
            updated_at=row[11],
            completed_at=row[12],
            deadline=row[13],
        )
