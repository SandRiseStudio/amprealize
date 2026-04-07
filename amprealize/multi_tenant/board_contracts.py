"""
Board Contracts v2 - Unified WorkItem Model

Treats goals, features, and tasks as the same entity type (WorkItem)
with a discriminator field and parent_id for hierarchy.

Hierarchy:
  - Goal (type=goal, parent_id=None)
    - Feature (type=feature, parent_id=goal_id)
      - Task (type=task, parent_id=feature_id)

Feature: 13.4.5 (Agent assignment) + 13.5.x (Agile Board System)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# =============================================================================
# Enums
# =============================================================================

class WorkItemType(str, Enum):
    """Type of work item in the hierarchy."""
    GOAL = "goal"          # Top-level grouping (formerly 'epic')
    FEATURE = "feature"    # Features under goals (formerly 'story')
    TASK = "task"          # Subtasks under features
    BUG = "bug"            # Defects / issues to fix

    # Backward-compat aliases (1 release cycle)
    EPIC = "goal"          # Deprecated: use GOAL
    STORY = "feature"      # Deprecated: use FEATURE


# Backward-compat mapping: old item_type values → new values
_ITEM_TYPE_ALIASES: dict[str, str] = {
    "epic": "goal",
    "story": "feature",
}


def normalize_item_type(value: str) -> str:
    """Map legacy item_type strings to current values.

    Accepts 'epic' → 'goal', 'story' → 'feature'.
    Passes through 'goal', 'feature', 'task', 'bug' unchanged.
    """
    return _ITEM_TYPE_ALIASES.get(value, value)


class AssigneeType(str, Enum):
    """Type of assignee - user or agent."""
    USER = "user"
    AGENT = "agent"


class WorkItemStatus(str, Enum):
    """Unified status for all work items."""
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"


class EpicStatus(str, Enum):
    """Legacy epic status enum used by older APIs/tests."""
    ACTIVE = "active"
    COMPLETED = "completed"


class WorkItemPriority(str, Enum):
    """Priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskType(str, Enum):
    """Legacy task type enum used by older APIs/tests."""
    CODING = "coding"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    DESIGN = "design"
    RESEARCH = "research"


class SprintStatus(str, Enum):
    """Sprint lifecycle status."""
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AssignmentAction(str, Enum):
    """Assignment history action types."""
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    REASSIGNED = "reassigned"


class BoardVisibility(str, Enum):
    """Board visibility settings."""
    INHERIT = "inherit"
    PRIVATE = "private"
    INTERNAL = "internal"
    PUBLIC = "public"


class BoardTemplate(str, Enum):
    """Board column template — progressive disclosure.

    minimal:  Backlog, In Progress, Done  (solo / small teams)
    standard: Backlog, In Progress, In Review, Done  (typical team)
    full:     Backlog, In Progress, In Review, Done  (same as standard)
    """
    MINIMAL = "minimal"
    STANDARD = "standard"
    FULL = "full"


class LabelColor(str, Enum):
    """
    Predefined color palette for labels.

    Constrained to ensure UI consistency across surfaces.
    Maps to CSS color names for easy frontend implementation.
    """
    GRAY = "gray"        # Default/neutral
    RED = "red"          # High priority, blockers
    ORANGE = "orange"    # Warning, needs attention
    YELLOW = "yellow"    # Caution, review needed
    GREEN = "green"      # Success, approved, done
    TEAL = "teal"        # Technical, infrastructure
    BLUE = "blue"        # Information, documentation
    INDIGO = "indigo"    # Design, UX
    PURPLE = "purple"    # Feature, enhancement
    PINK = "pink"        # Customer-facing, external


# =============================================================================
# Status Transitions
# =============================================================================

VALID_STATUS_TRANSITIONS: dict[WorkItemStatus, list[WorkItemStatus]] = {
    WorkItemStatus.BACKLOG: [WorkItemStatus.IN_PROGRESS, WorkItemStatus.IN_REVIEW, WorkItemStatus.DONE],
    WorkItemStatus.IN_PROGRESS: [WorkItemStatus.IN_REVIEW, WorkItemStatus.DONE, WorkItemStatus.BACKLOG],
    WorkItemStatus.IN_REVIEW: [WorkItemStatus.DONE, WorkItemStatus.IN_PROGRESS, WorkItemStatus.BACKLOG],
    WorkItemStatus.DONE: [WorkItemStatus.BACKLOG],  # Reopen
}


def is_valid_status_transition(from_status: WorkItemStatus, to_status: WorkItemStatus) -> bool:
    """Check if a status transition is valid.

    Note: All transitions are allowed - work items can be moved directly
    from any status to any other status (drag-and-drop across columns).
    """
    return True  # Allow all transitions


# =============================================================================
# Sub-Models
# =============================================================================

class BoardSettings(BaseModel):
    """Board configuration settings."""
    default_column_id: str | None = None
    auto_archive_after_days: int | None = None
    show_points: bool = True  # Formerly show_story_points
    show_due_dates: bool = True
    allow_subtasks: bool = True
    visibility: BoardVisibility = BoardVisibility.INHERIT


class AcceptanceCriterion(BaseModel):
    """Acceptance criterion for a work item."""
    id: str
    description: str
    is_met: bool = False
    verified_by: str | None = None
    verified_at: datetime | None = None


class ChecklistItem(BaseModel):
    """Checklist item for a work item."""
    id: str
    description: str
    is_done: bool = False
    completed_by: str | None = None
    completed_at: datetime | None = None


class Attachment(BaseModel):
    """File attachment reference."""
    id: str
    filename: str
    url: str
    content_type: str | None = None
    size_bytes: int | None = None
    uploaded_by: str
    uploaded_at: datetime


# =============================================================================
# Board Models
# =============================================================================

class Board(BaseModel):
    """Kanban/Scrum board."""
    # Accept both old short-id format (brd-xxx) and UUIDs from database
    board_id: str = Field(..., pattern=r"^(brd-[a-f0-9]{12}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
    project_id: str | None = None  # Nullable in database schema
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    settings: BoardSettings = Field(default_factory=BoardSettings)
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None  # Nullable in database schema
    is_default: bool = False
    org_id: str | None = None
    display_number: int | None = None  # Project-scoped sequential ID (e.g., 1, 2, 3)


class BoardColumn(BaseModel):
    """Board column representing a workflow stage."""
    # Accept both old short-id format (col-xxx) and UUIDs from database
    column_id: str = Field(..., pattern=r"^(col-[a-f0-9]{12}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
    board_id: str
    name: str = Field(..., min_length=1, max_length=100)
    position: int = 0
    status_mapping: WorkItemStatus | None = None  # Not in database schema
    wip_limit: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class BoardWithColumns(Board):
    """Board with its columns."""
    columns: list[BoardColumn] = Field(default_factory=list)


# =============================================================================
# Unified Work Item Model
# =============================================================================

class WorkItem(BaseModel):
    """
    Unified work item - can be goal, feature, task, or bug.

    Hierarchy via parent_id:
      - Goal: parent_id=None
      - Feature: parent_id=goal_id (optional, can be standalone)
      - Task: parent_id=feature_id (optional, can be standalone)
    """
    model_config = ConfigDict(populate_by_name=True)

    # Accept both old short-id format and UUIDs from database
    item_id: str = Field(..., pattern=r"^((goal|feature|epic|story|task|bug)-[a-f0-9]{12}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
    item_type: WorkItemType
    project_id: str | None = None  # Nullable in database schema
    board_id: str | None = None
    column_id: str | None = None
    parent_id: str | None = None  # epic_id for stories, story_id for tasks

    # Core fields
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    status: WorkItemStatus = WorkItemStatus.BACKLOG
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    position: int = 0

    # Estimation
    points: int | None = Field(None, ge=0, alias="story_points")  # Formerly story_points; alias kept for backward compat
    estimated_hours: Decimal | None = Field(None, ge=0)  # For tasks
    actual_hours: Decimal | None = Field(None, ge=0)  # For tasks

    # Assignment (polymorphic - user OR agent)
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    assigned_at: datetime | None = None
    assigned_by: str | None = None

    # Dates
    start_date: date | None = None
    target_date: date | None = None
    due_date: date | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Visual/organization
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    labels: list[str] = Field(default_factory=list)

    # Rich content
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)

    # Agent integration (for tasks)
    behavior_id: str | None = None
    run_id: str | None = None

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None

    # Computed fields (populated by service)
    display_number: int | None = None  # Project-scoped sequential ID (e.g., 1, 2, 3)
    display_id: str | None = None  # Human-friendly ID: "{project_slug}-{display_number}"
    child_count: int | None = None
    completed_child_count: int | None = None
    progress_percent: float | None = None

    @model_validator(mode="after")
    def validate_assignee(self) -> "WorkItem":
        """Ensure assignee fields are consistent."""
        if (self.assignee_id is None) != (self.assignee_type is None):
            raise ValueError("assignee_id and assignee_type must both be set or both be null")
        return self


class WorkItemWithChildren(WorkItem):
    """Work item with its child items."""
    children: list["WorkItem"] = Field(default_factory=list)


class ProgressBucketCounts(BaseModel):
    """Normalized status buckets for progress displays."""
    not_started: int = 0
    in_progress: int = 0
    completed: int = 0
    total: int = 0


class RemainingWorkSummary(BaseModel):
    """Remaining work metrics for PM-style rollups."""
    items_remaining: int = 0
    estimated_hours_remaining: float | None = None
    points_remaining: int | None = None  # Formerly story_points_remaining
    estimate_coverage_ratio: float | None = None


class IncompleteWorkItemSummary(BaseModel):
    """Compact descendant row for incomplete-work drilldowns."""
    model_config = ConfigDict(populate_by_name=True)

    item_id: str
    item_type: WorkItemType
    title: str
    status: WorkItemStatus
    parent_id: str | None = None
    assignee_id: str | None = None
    assignee_type: AssigneeType | None = None
    points: int | None = Field(None, alias="story_points")  # Formerly story_points
    estimated_hours: float | None = None
    actual_hours: float | None = None


class WorkItemProgressRollup(BaseModel):
    """Canonical rollup payload for epic/story/task progress UX."""
    item_id: str
    item_type: WorkItemType
    title: str
    status: WorkItemStatus
    buckets: ProgressBucketCounts
    remaining: RemainingWorkSummary
    completion_percent: float = 0.0
    incomplete_items: list[IncompleteWorkItemSummary] = Field(default_factory=list)


# =============================================================================
# Request Models
# =============================================================================

class CreateBoardRequest(BaseModel):
    """Request to create a board."""
    project_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    settings: BoardSettings | None = None
    is_default: bool = False
    create_default_columns: bool = True
    template: BoardTemplate = BoardTemplate.MINIMAL


class UpdateBoardRequest(BaseModel):
    """Request to update a board."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    settings: BoardSettings | None = None
    is_default: bool | None = None


class CreateColumnRequest(BaseModel):
    """Request to create a column."""
    board_id: str
    name: str = Field(..., min_length=1, max_length=100)
    position: int = Field(0, ge=0)
    status_mapping: WorkItemStatus
    wip_limit: int | None = Field(None, ge=1)


class UpdateColumnRequest(BaseModel):
    """Request to update a column."""
    name: str | None = Field(None, min_length=1, max_length=100)
    position: int | None = Field(None, ge=0)
    status_mapping: WorkItemStatus | None = None
    wip_limit: int | None = Field(None, ge=1)
    expected_updated_at: datetime | None = None


class CreateWorkItemRequest(BaseModel):
    """
    Unified request to create any work item (goal/feature/task/bug).

    The item_type determines the ID prefix and valid parent relationships.
    Accepts legacy values 'epic' and 'story' which are normalized automatically.
    """
    model_config = ConfigDict(populate_by_name=True)

    item_type: WorkItemType
    project_id: str | None = None  # Optional - board_id determines project context
    board_id: str | None = None
    column_id: str | None = None
    parent_id: str | None = None  # goal_id for features, feature_id for tasks

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    priority: WorkItemPriority = WorkItemPriority.MEDIUM

    # Optional fields
    points: int | None = Field(None, ge=0, alias="story_points")  # Formerly story_points
    estimated_hours: Decimal | None = Field(None, ge=0)
    start_date: date | None = None
    target_date: date | None = None
    due_date: date | None = None
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    labels: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)  # Converted to AcceptanceCriterion
    checklist: list[str] = Field(default_factory=list)  # Converted to ChecklistItem
    behavior_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, data: Any) -> Any:
        """Accept legacy item_type values ('epic'/'story') and 'story_points' field."""
        if isinstance(data, dict):
            if "item_type" in data and isinstance(data["item_type"], str):
                data["item_type"] = normalize_item_type(data["item_type"])
        return data

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "CreateWorkItemRequest":
        """Validate parent relationship based on item type."""
        if self.item_type == WorkItemType.GOAL and self.parent_id:
            raise ValueError("Goals cannot have a parent_id")
        return self


class UpdateWorkItemRequest(BaseModel):
    """Unified request to update any work item."""
    model_config = ConfigDict(populate_by_name=True)

    item_type: WorkItemType | None = None
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None

    board_id: str | None = None
    column_id: str | None = None
    parent_id: str | None = None
    position: int | None = None

    points: int | None = Field(None, ge=0, alias="story_points")  # Formerly story_points
    estimated_hours: Decimal | None = Field(None, ge=0)
    actual_hours: Decimal | None = Field(None, ge=0)

    start_date: date | None = None
    target_date: date | None = None
    due_date: date | None = None

    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    labels: list[str] | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None
    checklist: list[ChecklistItem] | None = None

    behavior_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] | None = None


# =============================================================================
# Legacy request/response models (compat for older API/tests)
# DEPRECATED: Prefer CreateWorkItemRequest / UpdateWorkItemRequest with
#   item_type='goal'/'feature'. These will be removed after 1 release cycle.
# =============================================================================


class CreateEpicRequest(BaseModel):
    project_id: str | None = None
    board_id: str | None = None
    name: str | None = Field(None, min_length=1, max_length=500)
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    story_points: int | None = Field(None, ge=0)
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateEpicRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=500)
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: EpicStatus | None = None
    priority: WorkItemPriority | None = None
    story_points: int | None = Field(None, ge=0)
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None


class CreateStoryRequest(BaseModel):
    project_id: str | None = None
    epic_id: str | None = None
    board_id: str | None = None
    column_id: str | None = None
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    story_points: int | None = Field(None, ge=0)
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateStoryRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    column_id: str | None = None
    status: WorkItemStatus | None = None
    story_points: int | None = Field(None, ge=0)
    priority: WorkItemPriority | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None


class CreateTaskRequest(BaseModel):
    project_id: str | None = None
    story_id: str | None = None
    board_id: str | None = None
    column_id: str | None = None
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    task_type: TaskType | None = None
    estimated_hours: Decimal | None = Field(None, ge=0)
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    labels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateTaskRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None
    column_id: str | None = None
    estimated_hours: Decimal | None = Field(None, ge=0)
    actual_hours: Decimal | None = Field(None, ge=0)
    task_type: TaskType | None = None
    assignee_user_id: str | None = None
    assignee_agent_id: str | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None


class Epic(BaseModel):
    epic_id: str
    project_id: str
    board_id: str | None = None
    name: str
    description: str | None = None
    status: EpicStatus
    priority: WorkItemPriority
    story_points: int | None = None
    color: str | None = None
    labels: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None


class Story(BaseModel):
    story_id: str
    project_id: str
    board_id: str | None = None
    epic_id: str | None = None
    column_id: str | None = None
    title: str
    description: str | None = None
    status: WorkItemStatus
    priority: WorkItemPriority
    story_points: int | None = None
    labels: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None


class Task(BaseModel):
    task_id: str
    project_id: str
    board_id: str | None = None
    story_id: str | None = None
    column_id: str | None = None
    title: str
    description: str | None = None
    status: WorkItemStatus
    priority: WorkItemPriority
    task_type: TaskType | None = None
    estimated_hours: Decimal | None = None
    actual_hours: Decimal | None = None
    assignee_user_id: str | None = None
    assignee_agent_id: str | None = None
    labels: list[str] = Field(default_factory=list)
    behavior_id: str | None = None
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str
    org_id: str | None = None


class MoveWorkItemRequest(BaseModel):
    """Request to move a work item."""
    column_id: str | None = None
    parent_id: str | None = None
    position: int = 0
    expected_from_column_updated_at: datetime | None = None
    expected_to_column_updated_at: datetime | None = None


class ReorderWorkItemsRequest(BaseModel):
    """Request to reorder work items within a column."""
    column_id: str
    ordered_item_ids: list[str]
    expected_column_updated_at: datetime | None = None


class ReorderBoardColumnsRequest(BaseModel):
    """Request to reorder columns within a board."""
    ordered_column_ids: list[str]
    expected_columns_updated_at: dict[str, datetime] | None = None


class AssignWorkItemRequest(BaseModel):
    """Request to assign a work item to a user or agent."""
    assignee_id: str
    assignee_type: AssigneeType
    reason: str | None = None


class UnassignWorkItemRequest(BaseModel):
    """Request to unassign a work item."""
    reason: str | None = None


# =============================================================================
# Sprint Models
# =============================================================================

class Sprint(BaseModel):
    """Sprint for time-boxed work."""
    # Accept both old short-id format and UUIDs from database
    sprint_id: str = Field(..., pattern=r"^(sprint-[a-f0-9]{12}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$")
    project_id: str | None = None  # Not in current database schema
    board_id: str
    name: str = Field(..., min_length=1, max_length=255)
    goal: str | None = None
    status: SprintStatus = SprintStatus.PLANNING
    is_active: bool = False
    start_date: date | None = None  # Nullable in database
    end_date: date | None = None  # Nullable in database
    velocity_planned: int | None = None  # Not in current database schema
    velocity_completed: int | None = None  # Not in current database schema
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None  # Not in current database schema
    org_id: str | None = None


class SprintStory(BaseModel):
    """Story membership in a sprint."""
    sprint_id: str
    story_id: str
    added_at: datetime | None = None
    added_by: str | None = None


class CreateSprintRequest(BaseModel):
    """Request to create a sprint."""
    project_id: str | None = None
    board_id: str
    name: str = Field(..., min_length=1, max_length=255)
    goal: str | None = None
    start_date: date | datetime
    end_date: date | datetime
    velocity_planned: int | None = Field(None, ge=0)


class UpdateSprintRequest(BaseModel):
    """Request to update a sprint."""
    name: str | None = Field(None, min_length=1, max_length=255)
    goal: str | None = None
    status: SprintStatus | None = None
    start_date: date | datetime | None = None
    end_date: date | datetime | None = None
    velocity_planned: int | None = Field(None, ge=0)


# =============================================================================
# Label Models
# =============================================================================

class Label(BaseModel):
    """
    Project-level label for categorizing work items.

    Labels are scoped to a project and can be applied to any work item type.
    Colors are constrained to a predefined palette for UI consistency.
    """
    label_id: str = Field(..., pattern=r"^lbl-[a-f0-9]{12}$")
    project_id: str
    name: str = Field(..., min_length=1, max_length=100)
    color: LabelColor = LabelColor.GRAY
    description: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None


class CreateLabelRequest(BaseModel):
    """Request to create a label."""
    name: str = Field(..., min_length=1, max_length=100)
    color: LabelColor = LabelColor.GRAY
    description: str | None = Field(None, max_length=500)


class UpdateLabelRequest(BaseModel):
    """Request to update a label."""
    name: str | None = Field(None, min_length=1, max_length=100)
    color: LabelColor | None = None
    description: str | None = Field(None, max_length=500)


class LabelListResponse(BaseModel):
    """List of labels for a project."""
    labels: list[Label]
    total: int


# =============================================================================
# Assignment History
# =============================================================================

class AssignmentHistory(BaseModel):
    """Audit trail for assignment changes."""
    history_id: str
    item_id: str  # Unified work item ID
    item_type: WorkItemType
    assignee_id: str | None
    assignee_type: AssigneeType | None
    action: AssignmentAction
    performed_by: str
    performed_at: datetime
    previous_assignee_id: str | None = None
    previous_assignee_type: AssigneeType | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    org_id: str | None = None


# =============================================================================
# Response/Result Models
# =============================================================================

class DeleteResult(BaseModel):
    """Result of a delete operation."""
    deleted_id: str
    deleted_type: str
    cascade_deleted: list[str] = Field(default_factory=list)


class WorkItemListResponse(BaseModel):
    """Paginated list of work items."""
    items: list[WorkItem]
    total: int
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# =============================================================================
# Event Models
# =============================================================================

class BoardEventType(str, Enum):
    """Board event types."""
    ITEM_CREATED = "item_created"
    ITEM_UPDATED = "item_updated"
    ITEM_DELETED = "item_deleted"
    ITEM_MOVED = "item_moved"
    ITEM_ASSIGNED = "item_assigned"
    ITEM_UNASSIGNED = "item_unassigned"
    SPRINT_CREATED = "sprint_created"
    SPRINT_STARTED = "sprint_started"
    SPRINT_COMPLETED = "sprint_completed"


class BoardEvent(BaseModel):
    """Event emitted on board changes."""
    event_id: str
    event_type: BoardEventType
    board_id: str | None
    item_id: str | None
    item_type: WorkItemType | None
    actor_id: str
    actor_type: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    org_id: str | None = None


# =============================================================================
# Agent Suggestion Models (for board.suggest_agent MCP tool)
# =============================================================================

class AgentWorkload(BaseModel):
    """Agent workload metrics for capacity planning."""
    model_config = ConfigDict(populate_by_name=True)

    agent_id: str
    agent_name: str
    active_items: int = 0  # Features + tasks in progress
    in_progress_count: int = 0
    completed_count: int = 0
    total_points: int = Field(default=0, alias="total_story_points")  # Formerly total_story_points
    allowed_behaviors: list[str] = Field(default_factory=list)

    # Capacity metrics
    max_concurrent_items: int | None = None  # From agent config
    utilization_percent: float | None = None  # active_items / max_concurrent_items


class SuggestAgentRequest(BaseModel):
    """Request to suggest best agent for a feature/task."""
    assignable_id: str
    assignable_type: Literal["feature", "task", "story"]  # 'story' accepted for backward compat
    required_behaviors: list[str] = Field(default_factory=list)  # Filter by allowed_behaviors
    max_suggestions: int = Field(3, ge=1, le=10)
    exclude_agent_ids: list[str] = Field(default_factory=list)


class AgentSuggestion(BaseModel):
    """Single agent suggestion with scoring."""
    agent_id: str
    agent_name: str
    score: float = Field(..., ge=0.0, le=1.0)  # 0-1 composite score
    behavior_match_score: float = Field(..., ge=0.0, le=1.0)
    workload_score: float = Field(..., ge=0.0, le=1.0)  # Lower workload = higher score
    current_workload: AgentWorkload
    matched_behaviors: list[str] = Field(default_factory=list)
    reason: str  # Human-readable explanation


class SuggestAgentResponse(BaseModel):
    """Response with agent suggestions."""
    suggestions: list[AgentSuggestion]
    assignable_id: str
    assignable_type: Literal["feature", "task", "story"]  # 'story' for backward compat
    required_behaviors: list[str]
    total_eligible_agents: int


# =============================================================================
# Type Aliases for Backwards Compatibility
# =============================================================================

# NOTE: Do not alias legacy models (Epic/Story/Task/CreateEpicRequest/etc.) to
# unified WorkItem models here. The legacy models are still used by the
# BoardService shims and by existing tests.

# If callers want unified types explicitly, prefer importing WorkItem/
# CreateWorkItemRequest/UpdateWorkItemRequest directly.
