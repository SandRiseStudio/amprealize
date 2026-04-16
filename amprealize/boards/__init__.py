"""Board and work-item contracts for Amprealize.

This package defines the core data models for boards, work items, and
related entities used throughout the execution pipeline, CLI, MCP tools,
and API.

Hierarchy:
  - Goal (type=goal, parent_id=None)
    - Feature (type=feature, parent_id=goal_id)
      - Task (type=task, parent_id=feature_id)
"""

from .contracts import (
    AcceptanceCriterion,
    AssigneeType,
    AssignmentAction,
    Attachment,
    Board,
    BoardColumn,
    BoardSettings,
    BoardTemplate,
    BoardVisibility,
    BoardWithColumns,
    ChecklistItem,
    CreateBoardRequest,
    CreateColumnRequest,
    CreateWorkItemRequest,
    EpicStatus,
    IncompleteWorkItemSummary,
    LabelColor,
    MoveWorkItemRequest,
    ProgressBucketCounts,
    RemainingWorkSummary,
    SprintStatus,
    SuggestAgentRequest,
    TaskType,
    UpdateBoardRequest,
    UpdateColumnRequest,
    UpdateWorkItemRequest,
    WorkItem,
    WorkItemPriority,
    WorkItemProgressRollup,
    WorkItemStatus,
    WorkItemType,
    WorkItemWithChildren,
    normalize_item_type,
)

__all__ = [
    "AcceptanceCriterion",
    "AssigneeType",
    "AssignmentAction",
    "Attachment",
    "Board",
    "BoardColumn",
    "BoardSettings",
    "BoardTemplate",
    "BoardVisibility",
    "BoardWithColumns",
    "ChecklistItem",
    "CreateBoardRequest",
    "CreateColumnRequest",
    "CreateWorkItemRequest",
    "EpicStatus",
    "IncompleteWorkItemSummary",
    "LabelColor",
    "MoveWorkItemRequest",
    "ProgressBucketCounts",
    "RemainingWorkSummary",
    "SprintStatus",
    "SuggestAgentRequest",
    "TaskType",
    "UpdateBoardRequest",
    "UpdateColumnRequest",
    "UpdateWorkItemRequest",
    "WorkItem",
    "WorkItemPriority",
    "WorkItemProgressRollup",
    "WorkItemStatus",
    "WorkItemType",
    "WorkItemWithChildren",
    "normalize_item_type",
]
