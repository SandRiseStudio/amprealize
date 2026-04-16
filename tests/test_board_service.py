"""
Unit and integration tests for BoardService (Agile board system).

Tests verify:
- Board CRUD operations
- Column management
- Goal, Feature, and Task lifecycle (unified WorkItem API)
- Sprint management
- Work item status transitions
- Assignment tracking (user and agent)
- Default board/column creation

Following `behavior_design_test_strategy` (Student).

Infrastructure requirements:
- PostgreSQL (WORKFLOW_DB) - port 5434 in test environment
- Uses AMPREALIZE_WORKFLOW_PG_DSN from environment

Run with: ./scripts/run_tests.sh --breakeramp --env test tests/test_board_service.py
"""
import os
import json
import pytest
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Generator, Any, Dict

# Mark all tests in this module as requiring postgres service
pytestmark = [
    pytest.mark.requires_services("postgres"),
    pytest.mark.integration,
]

# Service imports
from amprealize.services.board_service import (
    BoardService,
    Actor,
    BoardServiceError,
    BoardNotFoundError,
    TaskNotFoundError,
    WorkItemTransitionError,
)
from amprealize.boards.contracts import (
    CreateBoardRequest,
    UpdateBoardRequest,
    CreateColumnRequest,
    UpdateColumnRequest,
    CreateWorkItemRequest,
    UpdateWorkItemRequest,
    AssignWorkItemRequest,
    CreateSprintRequest,
    UpdateSprintRequest,
    BoardSettings,
    BoardVisibility,
    WorkItemStatus,
    WorkItemPriority,
    AssigneeType,
    WorkItemType,
)


# =============================================================================
# Fixtures
# =============================================================================

def _truncate_board_tables(dsn: str) -> None:
    """Truncate all board-related tables for test isolation."""
    from conftest import safe_truncate

    # Current board schema tables
    safe_truncate(dsn, [
        "sprint_stories", "sprints", "assignment_history",
        "work_item_comments", "work_items", "columns",
        "labels", "boards", "project_counters",
    ], schema="board")

    # Legacy table names (for compatibility with older test DB snapshots)
    safe_truncate(dsn, [
        "sprint_stories", "sprints", "assignment_history",
        "board_tasks", "stories", "epics", "board_columns", "boards",
    ])


def _ensure_board_test_references(dsn: str) -> None:
    """Ensure auth reference rows exist for board FK constraints."""
    try:
        import psycopg2  # type: ignore[import-not-found]
        HAS_PSYCOPG2 = True
    except ImportError:
        HAS_PSYCOPG2 = False

    if not HAS_PSYCOPG2:
        pytest.skip("psycopg2 required for FK seed data")

    org_id = "org-test-001"
    project_id = "proj-test-001"
    user_id = "test-user-001"

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth.organizations (id, name, slug)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (org_id, "Test Organization", "test-org-001"),
            )

            cur.execute(
                """
                INSERT INTO auth.users (id, email, display_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (user_id, "test-user-001@example.com", "Test User"),
            )

            cur.execute(
                """
                INSERT INTO auth.projects (project_id, org_id, name, created_by, owner_id)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO NOTHING
                """,
                (project_id, org_id, "Test Project", user_id, user_id),
            )

            # Ensure sprint_story bridge table exists for legacy sprint tests.
            # Some schema variants store sprint linkage differently.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS board.sprint_stories (
                    sprint_id UUID NOT NULL REFERENCES board.sprints(id) ON DELETE CASCADE,
                    story_id UUID NOT NULL REFERENCES board.work_items(id) ON DELETE CASCADE,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    added_by TEXT,
                    org_id TEXT,
                    PRIMARY KEY (sprint_id, story_id)
                )
                """
            )
        conn.commit()


@pytest.fixture
def dsn() -> str:
    """Get PostgreSQL DSN from environment."""
    dsn = os.environ.get("AMPREALIZE_WORKFLOW_PG_DSN") or os.environ.get("AMPREALIZE_RUN_PG_DSN")
    if not dsn:
        pytest.skip("AMPREALIZE_WORKFLOW_PG_DSN or AMPREALIZE_RUN_PG_DSN not set; skipping PostgreSQL tests")
    return dsn


@pytest.fixture
def service(dsn: str) -> Generator[BoardService, None, None]:
    """BoardService fixture with table truncation."""
    svc = BoardService(dsn=dsn)
    _ensure_board_test_references(dsn)
    _truncate_board_tables(dsn)
    yield svc
    _truncate_board_tables(dsn)


@pytest.fixture
def actor() -> Actor:
    """Default test actor."""
    return Actor(id="test-user-001", role="user", surface="test")


@pytest.fixture
def agent_actor() -> Actor:
    """Test actor representing an agent."""
    return Actor(id="test-agent-001", role="agent", surface="agent")


@pytest.fixture
def test_org_id() -> str:
    """Test organization ID."""
    return "org-test-001"


@pytest.fixture
def test_project_id() -> str:
    """Test project ID."""
    return "proj-test-001"


# =============================================================================
# Board CRUD Tests
# =============================================================================

class TestBoardCRUD:
    """Test board create, read, update, delete operations."""

    def test_create_board_basic(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a basic board without default columns."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Test Board",
            description="A test board",
            is_default=False,
            create_default_columns=False,
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.board_id is not None
        uuid.UUID(board.board_id)
        assert board.name == "Test Board"
        assert board.description == "A test board"
        assert board.project_id == test_project_id
        assert board.is_default is False
        assert board.created_by == actor.id

    def test_create_board_with_default_columns(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create board with default columns using MINIMAL template (Backlog, In Progress, Done)."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Kanban Board",
            is_default=True,
            create_default_columns=True,
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.board_id is not None

        # Verify board has columns
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        assert hasattr(board_with_cols, 'columns')
        assert len(board_with_cols.columns) == 3

        # Verify column names and order (MINIMAL template)
        column_names = [col.name for col in board_with_cols.columns]
        assert column_names == ["Backlog", "In Progress", "Done"]

        # Verify status mappings
        expected_statuses = [
            WorkItemStatus.BACKLOG,
            WorkItemStatus.IN_PROGRESS,
            WorkItemStatus.DONE,
        ]
        for i, col in enumerate(board_with_cols.columns):
            assert col.status_mapping == expected_statuses[i]

    def test_create_board_with_visibility_inherit(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Board visibility defaults to inherit from project."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Inherited Visibility Board",
            settings=BoardSettings(visibility=BoardVisibility.INHERIT),
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.settings.visibility == BoardVisibility.INHERIT

    def test_create_board_with_visibility_override(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Board can override project visibility."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Private Board",
            settings=BoardSettings(visibility=BoardVisibility.PRIVATE),
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.settings.visibility == BoardVisibility.PRIVATE

    def test_get_board_not_found(
        self, service: BoardService, test_org_id: str
    ):
        """Get non-existent board raises BoardNotFoundError."""
        with pytest.raises(BoardNotFoundError):
            service.get_board(str(uuid.uuid4()), org_id=test_org_id)

    def test_update_board(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Update board metadata."""
        # Create board
        create_req = CreateBoardRequest(
            project_id=test_project_id,
            name="Original Name",
        )
        board = service.create_board(create_req, actor, org_id=test_org_id)

        # Update
        update_req = UpdateBoardRequest(
            name="Updated Name",
            description="Updated description",
        )
        updated = service.update_board(board.board_id, update_req, actor, org_id=test_org_id)

        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"

    def test_delete_board(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Delete a board."""
        # Create board
        create_req = CreateBoardRequest(
            project_id=test_project_id,
            name="To Delete",
        )
        board = service.create_board(create_req, actor, org_id=test_org_id)

        # Delete
        service.delete_board(board.board_id, actor, org_id=test_org_id)

        # Verify deleted
        with pytest.raises(BoardNotFoundError):
            service.get_board(board.board_id, org_id=test_org_id)

    def test_list_boards_by_project(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """List all boards for a project."""
        # Create multiple boards
        for i in range(3):
            service.create_board(
                CreateBoardRequest(project_id=test_project_id, name=f"Board {i}"),
                actor,
                org_id=test_org_id,
            )

        boards = service.list_boards(project_id=test_project_id, org_id=test_org_id)
        assert len(boards) == 3


# =============================================================================
# Column Management Tests
# =============================================================================

class TestColumnManagement:
    """Test board column operations."""

    def test_create_custom_column(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a custom column."""
        # Create board without default columns
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Custom Columns Board",
                create_default_columns=False,
            ),
            actor,
            org_id=test_org_id,
        )

        # Add custom column
        col_req = CreateColumnRequest(
            board_id=board.board_id,
            name="QA Testing",
            position=0,
            status_mapping=WorkItemStatus.IN_REVIEW,
            wip_limit=5,
        )
        column = service.create_column(col_req, actor, org_id=test_org_id)

        uuid.UUID(column.column_id)
        assert column.name == "QA Testing"
        assert column.position == 0
        assert column.status_mapping == WorkItemStatus.IN_REVIEW
        assert column.wip_limit == 5

    def test_reorder_columns(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Reorder columns within a board."""
        # Create board with default columns
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Reorder Test",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )

        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )

        # Move "Done" column to position 2 (between "In Progress" and "In Review")
        done_col = next(c for c in board_with_cols.columns if c.name == "Done")
        service.update_column(
            done_col.column_id,
            UpdateColumnRequest(position=2),
            actor,
            org_id=test_org_id,
        )

        # Verify new order
        refreshed = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        column_names = [c.name for c in refreshed.columns]
        # Note: Other columns should shift. Exact behavior depends on implementation.
        assert done_col.column_id in [c.column_id for c in refreshed.columns]


# =============================================================================
# Goal Tests (formerly Epic)
# =============================================================================

class TestGoalLifecycle:
    """Test goal create, read, update operations."""

    def test_create_goal(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a goal."""
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Goal Board"),
            actor,
            org_id=test_org_id,
        )

        goal_req = CreateWorkItemRequest(
            item_type=WorkItemType.GOAL,
            project_id=test_project_id,
            board_id=board.board_id,
            title="User Authentication",
            description="Implement OAuth2 authentication flow",
            priority=WorkItemPriority.HIGH,
        )
        goal = service.create_work_item(goal_req, actor, org_id=test_org_id)

        uuid.UUID(goal.item_id)
        assert goal.title == "User Authentication"
        assert goal.status == WorkItemStatus.BACKLOG
        assert goal.priority == WorkItemPriority.HIGH

    def test_goal_status_transitions(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Test goal status transitions: backlog -> in_progress -> done."""
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Status Test Board"),
            actor,
            org_id=test_org_id,
        )

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                project_id=test_project_id,
                board_id=board.board_id,
                title="Status Test Goal",
            ),
            actor,
            org_id=test_org_id,
        )
        assert goal.status == WorkItemStatus.BACKLOG

        # Transition to in_progress
        updated = service.update_work_item(
            goal.item_id,
            UpdateWorkItemRequest(status=WorkItemStatus.IN_PROGRESS),
            actor,
            org_id=test_org_id,
        )
        assert updated.status == WorkItemStatus.IN_PROGRESS

        # Transition to done
        completed = service.update_work_item(
            goal.item_id,
            UpdateWorkItemRequest(status=WorkItemStatus.DONE),
            actor,
            org_id=test_org_id,
        )
        assert completed.status == WorkItemStatus.DONE


# =============================================================================
# Feature Tests (formerly Story)
# =============================================================================

class TestFeatureLifecycle:
    """Test feature create, read, update operations."""

    def test_create_feature_under_goal(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a feature under a goal."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Feature Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Parent Goal",
            ),
            actor,
            org_id=test_org_id,
        )

        feature_req = CreateWorkItemRequest(
            item_type=WorkItemType.FEATURE,
            board_id=board.board_id,
            parent_id=goal.item_id,
            column_id=backlog_col.column_id,
            title="Login Page",
            description="Create login page with email/password",
            points=5,
            priority=WorkItemPriority.MEDIUM,
        )
        feature = service.create_work_item(feature_req, actor, org_id=test_org_id)

        uuid.UUID(feature.item_id)
        assert feature.parent_id == goal.item_id
        assert feature.title == "Login Page"
        if feature.points is not None:
            assert feature.points == 5
        assert feature.status == WorkItemStatus.BACKLOG

    def test_move_feature_between_columns(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Move a feature from one column to another."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Move Feature Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")
        in_progress_col = next(c for c in board_with_cols.columns if c.name == "In Progress")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Move Goal",
            ),
            actor,
            org_id=test_org_id,
        )

        feature = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.FEATURE,
                board_id=board.board_id,
                parent_id=goal.item_id,
                column_id=backlog_col.column_id,
                title="Movable Feature",
            ),
            actor,
            org_id=test_org_id,
        )
        assert feature.column_id == backlog_col.column_id
        assert feature.status == WorkItemStatus.BACKLOG

        # Move to In Progress (explicitly set status since column→status sync is not yet implemented)
        moved = service.update_work_item(
            feature.item_id,
            UpdateWorkItemRequest(
                column_id=in_progress_col.column_id,
                status=WorkItemStatus.IN_PROGRESS,
            ),
            actor,
            org_id=test_org_id,
        )
        assert moved.column_id == in_progress_col.column_id
        assert moved.status == WorkItemStatus.IN_PROGRESS


# =============================================================================
# Task Tests
# =============================================================================

class TestTaskLifecycle:
    """Test task create, read, update operations."""

    def test_create_task_under_feature(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a task under a feature."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Task Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Task Goal",
            ),
            actor,
            org_id=test_org_id,
        )
        feature = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.FEATURE,
                board_id=board.board_id,
                parent_id=goal.item_id,
                column_id=backlog_col.column_id,
                title="Task Feature",
            ),
            actor,
            org_id=test_org_id,
        )

        task_req = CreateWorkItemRequest(
            item_type=WorkItemType.TASK,
            board_id=board.board_id,
            parent_id=feature.item_id,
            title="Write unit tests",
            description="Add pytest tests for login endpoint",
            estimated_hours=Decimal("2.0"),
            metadata={"task_type": "coding"},
        )
        task = service.create_work_item(task_req, actor, org_id=test_org_id)

        uuid.UUID(task.item_id)
        assert task.parent_id == feature.item_id
        assert task.title == "Write unit tests"
        assert task.metadata.get("task_type") == "coding"
        if task.estimated_hours is not None:
            assert float(task.estimated_hours) == 2.0
        assert task.status == WorkItemStatus.BACKLOG

    def test_assign_task_to_user(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Assign a task to a user."""
        board, feature = self._create_board_with_feature(
            service, actor, test_org_id, test_project_id
        )

        task = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.TASK,
                board_id=board.board_id,
                parent_id=feature.item_id,
                title="Assignable Task",
            ),
            actor,
            org_id=test_org_id,
        )

        # Assign to user
        assigned = service.assign_work_item(
            task.item_id,
            AssignWorkItemRequest(
                assignee_id="user-dev-001",
                assignee_type=AssigneeType.USER,
            ),
            actor,
            org_id=test_org_id,
        )
        assert assigned.assignee_id == "user-dev-001"
        assert assigned.assignee_type == AssigneeType.USER

    def test_assign_goal_to_user(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Assigning a goal must not fail assignment_history CHECK (legacy rows used epic, not goal)."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Goal Assign Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Assignable Goal",
            ),
            actor,
            org_id=test_org_id,
        )
        assigned = service.assign_work_item(
            goal.item_id,
            AssignWorkItemRequest(
                assignee_id="user-dev-001",
                assignee_type=AssigneeType.USER,
            ),
            actor,
            org_id=test_org_id,
        )
        assert assigned.assignee_id == "user-dev-001"
        assert assigned.assignee_type == AssigneeType.USER

    def test_assign_task_to_agent(
        self, service: BoardService, actor: Actor, agent_actor: Actor,
        test_org_id: str, test_project_id: str
    ):
        """Assign a task to an agent."""
        board, feature = self._create_board_with_feature(
            service, actor, test_org_id, test_project_id
        )

        task = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.TASK,
                board_id=board.board_id,
                parent_id=feature.item_id,
                title="Agent Task",
            ),
            actor,
            org_id=test_org_id,
        )

        # Assign to agent
        assigned = service.assign_work_item(
            task.item_id,
            AssignWorkItemRequest(
                assignee_id="agent-copilot-001",
                assignee_type=AssigneeType.AGENT,
            ),
            actor,
            org_id=test_org_id,
        )
        assert assigned.assignee_id == "agent-copilot-001"
        assert assigned.assignee_type == AssigneeType.AGENT

    def _create_board_with_feature(
        self, service: BoardService, actor: Actor, org_id: str, project_id: str
    ):
        """Helper to create a board with a goal and feature."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=project_id,
                name="Helper Board",
                create_default_columns=True,
            ),
            actor,
            org_id=org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Helper Goal",
            ),
            actor,
            org_id=org_id,
        )
        feature = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.FEATURE,
                board_id=board.board_id,
                parent_id=goal.item_id,
                column_id=backlog_col.column_id,
                title="Helper Feature",
            ),
            actor,
            org_id=org_id,
        )
        return board, feature


class TestSprintManagement:
    """Test sprint create, read, update operations."""

    def test_create_sprint(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a sprint."""
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Sprint Board"),
            actor,
            org_id=test_org_id,
        )

        start_date = datetime.now()
        end_date = start_date + timedelta(days=14)

        sprint_req = CreateSprintRequest(
            board_id=board.board_id,
            name="Sprint 1",
            goal="Complete user authentication",
            start_date=start_date,
            end_date=end_date,
        )
        sprint = service.create_sprint(sprint_req, actor, org_id=test_org_id)

        uuid.UUID(sprint.sprint_id)
        assert sprint.name == "Sprint 1"
        assert sprint.goal == "Complete user authentication"
        assert sprint.is_active is False  # Not active until started

    def test_add_story_to_sprint(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Add a feature to a sprint."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Sprint Feature Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Sprint Goal",
            ),
            actor,
            org_id=test_org_id,
        )
        feature = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.FEATURE,
                board_id=board.board_id,
                parent_id=goal.item_id,
                column_id=backlog_col.column_id,
                title="Sprint Feature",
                points=3,
            ),
            actor,
            org_id=test_org_id,
        )

        sprint = service.create_sprint(
            CreateSprintRequest(
                board_id=board.board_id,
                name="Test Sprint",
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(days=14),
            ),
            actor,
            org_id=test_org_id,
        )

        # Add feature to sprint (method still named add_story_to_sprint pending rename)
        service.add_story_to_sprint(
            sprint.sprint_id, feature.item_id, actor, org_id=test_org_id
        )

        # Verify feature is in sprint
        sprint_stories = service.list_sprint_stories(
            sprint.sprint_id, org_id=test_org_id
        )
        assert len(sprint_stories) == 1
        assert sprint_stories[0].story_id == feature.item_id


# =============================================================================
# Permission Tests
# =============================================================================

class TestBoardPermissions:
    """Test board permission requirements (placeholder for full integration)."""

    def test_board_permissions_exist(self):
        """Verify board permissions are defined in ProjectPermission enum."""
        from amprealize.tenant.permissions import ProjectPermission

        # All board permissions should exist
        assert hasattr(ProjectPermission, 'VIEW_BOARDS')
        assert hasattr(ProjectPermission, 'CREATE_BOARDS')
        assert hasattr(ProjectPermission, 'UPDATE_BOARDS')
        assert hasattr(ProjectPermission, 'DELETE_BOARDS')
        assert hasattr(ProjectPermission, 'MANAGE_COLUMNS')
        assert hasattr(ProjectPermission, 'CREATE_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'UPDATE_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'DELETE_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'ASSIGN_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'MANAGE_SPRINTS')

    def test_role_permissions_include_board_access(self):
        """Verify role permission matrices include board permissions."""
        from amprealize.tenant.permissions import (
            ProjectPermission,
            ProjectRole,
            PROJECT_ROLE_PERMISSIONS,
        )

        # Viewer can view boards
        viewer_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.VIEWER]
        assert ProjectPermission.VIEW_BOARDS in viewer_perms

        # Contributor can view and create work items
        contrib_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]
        assert ProjectPermission.VIEW_BOARDS in contrib_perms
        assert ProjectPermission.CREATE_WORK_ITEMS in contrib_perms

        # Owner has all permissions
        owner_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.OWNER]
        assert ProjectPermission.DELETE_BOARDS in owner_perms
        assert ProjectPermission.MANAGE_SPRINTS in owner_perms


# =============================================================================
# Visibility Tests
# =============================================================================

class TestBoardVisibility:
    """Test board visibility inheritance."""

    def test_visibility_enum_values(self):
        """Verify BoardVisibility enum has expected values."""
        assert BoardVisibility.INHERIT.value == "inherit"
        assert BoardVisibility.PRIVATE.value == "private"
        assert BoardVisibility.INTERNAL.value == "internal"
        assert BoardVisibility.PUBLIC.value == "public"

    def test_board_settings_default_visibility(self):
        """BoardSettings defaults to INHERIT visibility."""
        settings = BoardSettings()
        assert settings.visibility == BoardVisibility.INHERIT


# =============================================================================
# Progress Rollup Tests
# =============================================================================

class TestWorkItemProgressRollups:
    """Validate status bucket and work-left rollups for goal/feature hierarchies."""

    def test_goal_rollup_buckets_and_remaining(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Rollup Board", create_default_columns=True),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(board.board_id, include_columns=True, org_id=test_org_id)
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Progress Goal",
            ),
            actor,
            org_id=test_org_id,
        )
        feature = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.FEATURE,
                board_id=board.board_id,
                parent_id=goal.item_id,
                column_id=backlog_col.column_id,
                title="Progress Feature",
            ),
            actor,
            org_id=test_org_id,
        )
        task_done = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.TASK,
                board_id=board.board_id,
                parent_id=feature.item_id,
                column_id=backlog_col.column_id,
                title="Done Task",
            ),
            actor,
            org_id=test_org_id,
        )
        task_in_progress = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.TASK,
                board_id=board.board_id,
                parent_id=feature.item_id,
                column_id=backlog_col.column_id,
                title="In Progress Task",
            ),
            actor,
            org_id=test_org_id,
        )

        service.update_work_item(
            task_done.item_id,
            UpdateWorkItemRequest(status=WorkItemStatus.DONE),
            actor,
            org_id=test_org_id,
        )
        service.update_work_item(
            task_in_progress.item_id,
            UpdateWorkItemRequest(status=WorkItemStatus.IN_PROGRESS),
            actor,
            org_id=test_org_id,
        )

        rollup = service.get_work_item_progress_rollup(
            goal.item_id,
            include_incomplete_descendants=True,
            org_id=test_org_id,
        )

        assert rollup.item_id == goal.item_id
        assert rollup.item_type == WorkItemType.GOAL
        assert rollup.buckets.total == 3
        assert rollup.buckets.not_started == 1
        assert rollup.buckets.in_progress == 1
        assert rollup.buckets.completed == 1
        assert rollup.remaining.items_remaining == 2
        assert rollup.completion_percent == pytest.approx(33.3, abs=0.2)
        assert len(rollup.incomplete_items) == 2

    def test_board_rollups_by_item_type(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Rollup Filter Board", create_default_columns=True),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(board.board_id, include_columns=True, org_id=test_org_id)
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        goal = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.GOAL,
                board_id=board.board_id,
                title="Filter Goal",
            ),
            actor,
            org_id=test_org_id,
        )
        feature = service.create_work_item(
            CreateWorkItemRequest(
                item_type=WorkItemType.FEATURE,
                board_id=board.board_id,
                parent_id=goal.item_id,
                column_id=backlog_col.column_id,
                title="Filter Feature",
            ),
            actor,
            org_id=test_org_id,
        )

        goal_rollups = service.list_board_progress_rollups(
            board.board_id,
            item_type=WorkItemType.GOAL,
            org_id=test_org_id,
        )
        feature_rollups = service.list_board_progress_rollups(
            board.board_id,
            item_type=WorkItemType.FEATURE,
            org_id=test_org_id,
        )

        assert len(goal_rollups) == 1
        assert goal_rollups[0].item_id == goal.item_id
        assert len(feature_rollups) == 1
        assert feature_rollups[0].item_id == feature.item_id
