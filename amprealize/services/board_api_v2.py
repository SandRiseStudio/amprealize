"""FastAPI router for Unified Agile Board management.

Uses a single WorkItem model for goals, features, and tasks.
Hierarchy is managed via item_type and parent_id.

Endpoints:
    # Boards
    POST   /v1/boards                           - Create board
    GET    /v1/boards                           - List boards
    GET    /v1/boards/{board_id}                - Get board with columns
    PATCH  /v1/boards/{board_id}                - Update board
    DELETE /v1/boards/{board_id}                - Delete board

    # Columns
    POST   /v1/boards/{board_id}/columns        - Create column
    GET    /v1/boards/{board_id}/columns        - List columns
    PATCH  /v1/columns/{column_id}              - Update column
    DELETE /v1/columns/{column_id}              - Delete column

    # Work Items (unified goal/feature/task)
    POST   /v1/work-items                       - Create work item
    GET    /v1/work-items                       - List work items (with filters)
    GET    /v1/work-items/{item_id}             - Get work item details
    GET    /v1/work-items/{item_id}/children    - Get child items
    PATCH  /v1/work-items/{item_id}             - Update work item
    DELETE /v1/work-items/{item_id}             - Delete work item (cascade optional)
    POST   /v1/work-items/{item_id}:complete-with-descendants
                                                - Complete item and all descendants

    # Assignment
    POST   /v1/work-items/{item_id}:assign      - Assign to user/agent
    POST   /v1/work-items/{item_id}:unassign    - Unassign

    # Comments
    GET    /v1/work-items/{item_id}/comments    - List comments on a work item
    POST   /v1/work-items/{item_id}/comments    - Add a comment to a work item

    # Sprints
    POST   /v1/sprints                          - Create sprint
    GET    /v1/sprints                          - List sprints
    GET    /v1/sprints/{sprint_id}              - Get sprint
    PATCH  /v1/sprints/{sprint_id}              - Update sprint
    DELETE /v1/sprints/{sprint_id}              - Delete sprint

    # Labels
    POST   /v1/projects/{project_id}/labels     - Create label
    GET    /v1/projects/{project_id}/labels     - List labels
    GET    /v1/labels/{label_id}                - Get label
    PATCH  /v1/labels/{label_id}                - Update label
    DELETE /v1/labels/{label_id}                - Delete label
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from amprealize.perf_log import perf_log, perf_span
from amprealize.boards.contracts import (
    # Board models
    Board,
    BoardColumn,
    BoardWithColumns,
    CreateBoardRequest,
    UpdateBoardRequest,
    CreateColumnRequest,
    UpdateColumnRequest,
    # Work item models
    WorkItem,
    WorkItemProgressRollup,
    WorkItemType,
    WorkItemStatus,
    WorkItemPriority,
    CreateWorkItemRequest,
    UpdateWorkItemRequest,
    MoveWorkItemRequest,
    ReorderWorkItemsRequest,
    ReorderBoardColumnsRequest,
    AssignWorkItemRequest,
    DeleteResult,
    # Sprint models
    Sprint,
    SprintStatus,
    CreateSprintRequest,
    UpdateSprintRequest,
    # Assignment
    AssigneeType,
    # Label models
    Label,
    LabelColor,
    CreateLabelRequest,
    UpdateLabelRequest,
    LabelListResponse,
)
from amprealize.services.board_service import (
    BoardService,
    BoardServiceError,
    ConcurrencyConflictError,
    BoardNotFoundError,
    ColumnNotFoundError,
    WorkItemNotFoundError,
    WorkItemTransitionError,
    WorkItemValidationError,
    AssigneeNotFoundError,
    AuthorNotFoundError,
    Actor,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Response Models
# =============================================================================

class BoardResponse(BaseModel):
    """Response for board operations."""
    board: Board


class BoardWithColumnsResponse(BaseModel):
    """Response for board with columns."""
    board: BoardWithColumns


class BoardListResponse(BaseModel):
    """Response for listing boards."""
    boards: List[Board]
    total: int


class ColumnResponse(BaseModel):
    """Response for column operations."""
    column: BoardColumn


class ColumnListResponse(BaseModel):
    """Response for listing columns."""
    columns: List[BoardColumn]


class WorkItemResponse(BaseModel):
    """Response for work item operations."""
    item: WorkItem


class WorkItemListResponse(BaseModel):
    """Response for listing work items."""
    items: List[WorkItem]
    total: int
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class WorkItemBatchRequest(BaseModel):
    """Batch request for work item hydration."""
    item_ids: List[str] = Field(..., min_length=1, max_length=100)


class WorkItemBatchResponse(BaseModel):
    """Response for batch work item lookup."""
    items: List[WorkItem]
    total: int
    missing_ids: List[str] = Field(default_factory=list)


class SprintResponse(BaseModel):
    """Response for sprint operations."""
    sprint: Sprint


class SprintListResponse(BaseModel):
    """Response for listing sprints."""
    sprints: List[Sprint]
    total: int


class DeleteResponse(BaseModel):
    """Response for delete operations."""
    result: DeleteResult


class LabelResponse(BaseModel):
    """Response for label operations."""
    label: Label


class AssignmentResponse(BaseModel):
    """Response for assignment operations."""
    item: WorkItem
    message: str


class WorkItemComment(BaseModel):
    """Comment attached to a work item."""
    comment_id: str
    work_item_id: str
    author_id: str
    author_type: str
    content: str
    run_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WorkItemCommentResponse(BaseModel):
    """Response for comment operations."""
    comment: WorkItemComment


class WorkItemCommentListResponse(BaseModel):
    """Response for listing comments."""
    comments: List[WorkItemComment]
    total: int


class CreateWorkItemCommentRequest(BaseModel):
    """Request to add a comment to a work item."""
    body: str = Field(..., min_length=1, max_length=4000)
    author_type: Optional[Literal["user", "agent"]] = None
    run_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkItemProgressRollupResponse(BaseModel):
    """Response for single work item progress rollup."""
    rollup: WorkItemProgressRollup


class WorkItemProgressRollupListResponse(BaseModel):
    """Response for board-level progress rollup list."""
    rollups: List[WorkItemProgressRollup]
    total: int


class BoardBootstrapResponse(BaseModel):
    """Bundled board load payload for reducing first-render request fanout."""
    board: BoardWithColumns
    items: List[WorkItem]
    total: int
    page: int = 1
    page_size: int = 100
    has_more: bool = False
    rollups: List[WorkItemProgressRollup] = Field(default_factory=list)


class CompleteWithDescendantsResponse(BaseModel):
    """Response for completing a work item with all descendants."""
    updated_count: int
    updated_ids: List[str]


# =============================================================================
# Router Factory
# =============================================================================

def create_board_routes(
    board_service: BoardService,
    tags: Optional[List[str | Enum]] = None,
) -> APIRouter:
    """Create FastAPI router for unified board management.

    Args:
        board_service: BoardService instance.
        tags: Optional tags for OpenAPI documentation.

    Returns:
        FastAPI APIRouter with all board endpoints.
    """
    router_tags: List[str | Enum] = list(tags) if tags else ["boards"]
    router = APIRouter(tags=router_tags)

    def _get_actor(request: Request) -> Actor:
        """Extract actor from request state or create default."""
        user_id = getattr(request.state, "user_id", None) or "anonymous"
        return Actor(
            id=user_id,
            role=getattr(request.state, "user_role", "user"),
            surface="api",
        )

    def _get_org_id(request: Request) -> Optional[str]:
        """Extract org_id from request state."""
        return getattr(request.state, "org_id", None)

    def _resolve_item_id(item_id: str, request: Request) -> str:
        """Resolve a work item identifier (UUID, short ID, or display ID like 'myproject-42')."""
        org_id = _get_org_id(request)
        project_id = getattr(request.state, "project_id", None)
        return board_service.resolve_work_item_id(
            item_id, org_id=org_id, project_id=project_id,
        )

    def _post_comment_with_author_type(
        *,
        work_item_id: str,
        author_id: str,
        requested_type: Optional[str],
        body: CreateWorkItemCommentRequest,
        actor: Actor,
        org_id: Optional[str],
    ) -> Dict[str, Any]:
        preferred_type = requested_type or "user"
        try:
            return board_service.add_comment(
                work_item_id=work_item_id,
                author_id=author_id,
                author_type=preferred_type,
                content=body.body,
                actor=actor,
                run_id=body.run_id,
                metadata=body.metadata,
                org_id=org_id,
            )
        except AuthorNotFoundError as exc:
            if requested_type:
                raise exc
            return board_service.add_comment(
                work_item_id=work_item_id,
                author_id=author_id,
                author_type="agent",
                content=body.body,
                actor=actor,
                run_id=body.run_id,
                metadata=body.metadata,
                org_id=org_id,
            )

    # =========================================================================
    # Board CRUD
    # =========================================================================

    @router.post(
        "/v1/boards",
        response_model=BoardResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create board",
        description="Create a new board with optional default columns.",
    )
    async def create_board(
        request: Request,
        body: CreateBoardRequest,
    ) -> BoardResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            board = board_service.create_board(body, actor, org_id=org_id)
            return BoardResponse(board=board)
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except Exception as e:
            logger.exception("Board create failed", extra={"project_id": body.project_id, "org_id": org_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Board service unavailable. Ensure the board database is running and CORS is configured for your web origin.",
            ) from e

    @router.get(
        "/v1/boards",
        response_model=BoardListResponse,
        summary="List boards",
        description="List all boards for a project.",
    )
    async def list_boards(
        request: Request,
        project_id: str = Query(..., description="Project ID to filter by"),
        limit: int = Query(100, ge=1, le=200, description="Max boards to return"),
        offset: int = Query(0, ge=0, description="Boards to skip"),
    ) -> BoardListResponse:
        org_id = _get_org_id(request)

        try:
            with perf_span("boards.list", project_id=project_id) as span:
                boards = await run_in_threadpool(
                    board_service.list_boards,
                    project_id=project_id,
                    org_id=org_id,
                    limit=limit,
                    offset=offset,
                )
                span["item_count"] = len(boards)
            return BoardListResponse(boards=boards, total=len(boards))
        except Exception as e:
            logger.exception("Board list failed", extra={"project_id": project_id, "org_id": org_id})
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Board service unavailable. Ensure the board database is running and CORS is configured for your web origin.",
            ) from e

    @router.get(
        "/v1/boards/{board_id}",
        response_model=BoardWithColumnsResponse,
        summary="Get board",
        description="Get board details with columns.",
    )
    async def get_board(
        request: Request,
        board_id: str,
    ) -> BoardWithColumnsResponse:
        org_id = _get_org_id(request)

        try:
            with perf_span("boards.get", board_id=board_id) as span:
                board = await run_in_threadpool(
                    board_service.get_board_with_columns, board_id, org_id=org_id
                )
                span["column_count"] = len(board.columns) if getattr(board, "columns", None) else 0
            return BoardWithColumnsResponse(board=board)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/boards/{board_id}/bootstrap",
        response_model=BoardBootstrapResponse,
        summary="Bootstrap board page",
        description="Fetch board metadata, first work-item page, and rollups in one request.",
    )
    async def get_board_bootstrap(
        request: Request,
        board_id: str,
        limit: int = Query(100, ge=1, le=250, description="Max first-page work items to return"),
        offset: int = Query(0, ge=0, description="Work items to skip"),
        include_rollups: bool = Query(True, description="Include board progress rollups"),
    ) -> BoardBootstrapResponse:
        org_id = _get_org_id(request)
        _t0 = time.perf_counter()

        try:
            _t_board = time.perf_counter()
            board = await run_in_threadpool(board_service.get_board_with_columns, board_id, org_id=org_id)
            t_board_ms = round((time.perf_counter() - _t_board) * 1000, 1)

            _t_items = time.perf_counter()
            maybe_items = await run_in_threadpool(
                board_service.list_work_items,
                board_id=board_id,
                org_id=org_id,
                limit=limit,
                offset=offset,
                include_total=True,
            )
            if isinstance(maybe_items, tuple):
                items, total = maybe_items
            else:
                items = maybe_items
                total = len(items)
            t_items_ms = round((time.perf_counter() - _t_items) * 1000, 1)

            rollups: List[WorkItemProgressRollup] = []
            t_rollups_ms = 0.0
            if include_rollups:
                _t_rollups = time.perf_counter()
                rollups = await run_in_threadpool(
                    board_service.list_board_progress_rollups,
                    board_id,
                    org_id=org_id,
                )
                t_rollups_ms = round((time.perf_counter() - _t_rollups) * 1000, 1)

            has_more = offset + len(items) < total
            perf_log(
                "boards.bootstrap",
                round((time.perf_counter() - _t0) * 1000, 1),
                board_id=board_id,
                t_board_ms=t_board_ms,
                t_items_ms=t_items_ms,
                t_rollups_ms=t_rollups_ms,
                item_count=len(items),
                rollup_count=len(rollups),
                limit=limit,
                offset=offset,
                has_more=has_more,
            )

            return BoardBootstrapResponse(
                board=board,
                items=items,
                total=total,
                page=offset // limit + 1 if limit else 1,
                page_size=limit,
                has_more=has_more,
                rollups=rollups,
            )
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/boards/{board_id}",
        response_model=BoardResponse,
        summary="Update board",
        description="Update board fields.",
    )
    async def update_board(
        request: Request,
        board_id: str,
        body: UpdateBoardRequest,
    ) -> BoardResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            board = board_service.update_board(board_id, body, actor, org_id=org_id)
            return BoardResponse(board=board)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.delete(
        "/v1/boards/{board_id}",
        response_model=DeleteResponse,
        summary="Delete board",
        description="Delete a board and all its contents.",
    )
    async def delete_board(
        request: Request,
        board_id: str,
    ) -> DeleteResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            result = board_service.delete_board(board_id, actor, org_id=org_id)
            return DeleteResponse(result=result)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # =========================================================================
    # Column CRUD
    # =========================================================================

    @router.post(
        "/v1/boards/{board_id}/columns",
        response_model=ColumnResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create column",
        description="Create a new column on a board.",
    )
    async def create_column(
        request: Request,
        board_id: str,
        body: CreateColumnRequest,
    ) -> ColumnResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        # Ensure board_id matches
        body_dict = body.model_dump()
        body_dict["board_id"] = board_id
        req = CreateColumnRequest(**body_dict)

        try:
            column = board_service.create_column(req, actor, org_id=org_id)
            return ColumnResponse(column=column)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get(
        "/v1/boards/{board_id}/columns",
        response_model=ColumnListResponse,
        summary="List columns",
        description="List all columns for a board.",
    )
    async def list_columns(
        request: Request,
        board_id: str,
    ) -> ColumnListResponse:
        org_id = _get_org_id(request)

        try:
            columns = board_service.list_columns(board_id, org_id=org_id)
            return ColumnListResponse(columns=columns)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/columns/{column_id}",
        response_model=ColumnResponse,
        summary="Update column",
        description="Update column fields.",
    )
    async def update_column(
        request: Request,
        column_id: str,
        body: UpdateColumnRequest,
    ) -> ColumnResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            column = board_service.update_column(column_id, body, actor, org_id=org_id)
            return ColumnResponse(column=column)
        except ColumnNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.delete(
        "/v1/columns/{column_id}",
        response_model=DeleteResponse,
        summary="Delete column",
        description="Delete a column.",
    )
    async def delete_column(
        request: Request,
        column_id: str,
    ) -> DeleteResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            result = board_service.delete_column(column_id, actor, org_id=org_id)
            return DeleteResponse(result=result)
        except ColumnNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # =========================================================================
    # Work Item CRUD (unified goal/feature/task)
    # =========================================================================

    @router.post(
        "/v1/work-items",
        response_model=WorkItemResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create work item",
        description="Create a work item (goal, feature, task, or bug). Use item_type to specify.",
    )
    async def create_work_item(
        request: Request,
        body: CreateWorkItemRequest,
    ) -> WorkItemResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        # GWS title validation is enforced by BoardService.create_work_item()
        try:
            item = board_service.create_work_item(body, actor, org_id=org_id)
            return WorkItemResponse(item=item)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get(
        "/v1/work-items",
        response_model=WorkItemListResponse,
        summary="List work items",
        description="List work items with optional filters for type, status, parent, assignee, priority, labels, sprint, text search, due-date range, and custom sorting.",
    )
    async def list_work_items(
        request: Request,
        project_id: Optional[str] = Query(None, description="Filter by project"),
        board_id: Optional[str] = Query(None, description="Filter by board"),
        item_type: Optional[List[WorkItemType]] = Query(None, description="Filter by type (goal/feature/task/bug). Repeat the query param for multiple values."),
        parent_id: Optional[str] = Query(None, description="Filter by parent item"),
        status_filter: Optional[WorkItemStatus] = Query(None, alias="status", description="Filter by status"),
        priority: Optional[List[WorkItemPriority]] = Query(None, description="Filter by priority. Repeat the query param for multiple values."),
        assignee_id: Optional[str] = Query(None, description="Filter by assignee"),
        assignee_type: Optional[str] = Query(None, description="Filter by assignee type (user/agent)"),
        sprint_id: Optional[str] = Query(None, description="Filter by sprint"),
        labels: Optional[List[str]] = Query(None, description="Filter by labels (any match)"),
        title_search: Optional[str] = Query(None, description="Case-insensitive substring search on title"),
        due_before: Optional[str] = Query(None, description="Items due on or before this ISO date"),
        due_after: Optional[str] = Query(None, description="Items due on or after this ISO date"),
        sort_by: Optional[str] = Query(None, description="Sort field: position, priority, created_at, updated_at, due_date, title, points"),
        order: Optional[str] = Query(None, description="Sort order: asc or desc (default asc)"),
        include_total: bool = Query(
            True,
            description=(
                "When true, compute exact total count (extra COUNT query). "
                "Set false for subsequent pages to reduce DB latency on cloud PostgreSQL."
            ),
        ),
        limit: int = Query(50, ge=1, le=250, description="Max items to return"),
        offset: int = Query(0, ge=0, description="Items to skip"),
    ) -> WorkItemListResponse:
        org_id = _get_org_id(request)
        _t0 = time.perf_counter()

        if include_total:
            # Single query path: `list_work_items(include_total=True)` returns
            # `(items, total)` using `COUNT(*) OVER()` so we avoid a separate
            # `count_work_items` round-trip (~200-400ms on cold Neon).
            _t_query_start = time.perf_counter()
            items, total = await run_in_threadpool(
                board_service.list_work_items,
                project_id=project_id,
                board_id=board_id,
                item_types=item_type,
                parent_id=parent_id,
                status=status_filter,
                priorities=priority,
                assignee_id=assignee_id,
                assignee_type=assignee_type,
                sprint_id=sprint_id,
                labels=labels,
                title_search=title_search,
                due_before=due_before,
                due_after=due_after,
                sort_by=sort_by,
                order=order,
                org_id=org_id,
                limit=limit,
                offset=offset,
                include_total=True,
            )
            _t_query_ms = round((time.perf_counter() - _t_query_start) * 1000, 1)
            has_more = offset + len(items) < total
        else:
            # Over-fetch by one row so has_more can be derived without a COUNT(*)
            # query on every subsequent page.
            _t_query_start = time.perf_counter()
            items_plus_one = await run_in_threadpool(
                board_service.list_work_items,
                project_id=project_id,
                board_id=board_id,
                item_types=item_type,
                parent_id=parent_id,
                status=status_filter,
                priorities=priority,
                assignee_id=assignee_id,
                assignee_type=assignee_type,
                sprint_id=sprint_id,
                labels=labels,
                title_search=title_search,
                due_before=due_before,
                due_after=due_after,
                sort_by=sort_by,
                order=order,
                org_id=org_id,
                limit=limit + 1,
                offset=offset,
            )
            _t_query_ms = round((time.perf_counter() - _t_query_start) * 1000, 1)
            has_more = len(items_plus_one) > limit
            items = items_plus_one[:limit]
            # Preserve response shape; this is a lower-bound estimate when total
            # is intentionally skipped for latency reasons.
            total = offset + len(items) + (1 if has_more else 0)

        _t_shape_start = time.perf_counter()
        response = WorkItemListResponse(
            items=items,
            total=total,
            page=offset // limit + 1 if limit else 1,
            page_size=limit,
            has_more=has_more,
        )
        _t_shape_ms = round((time.perf_counter() - _t_shape_start) * 1000, 1)
        _t_total_ms = round((time.perf_counter() - _t0) * 1000, 1)

        perf_log(
            "work_items.list",
            _t_total_ms,
            t_query_ms=_t_query_ms,
            t_shape_ms=_t_shape_ms,
            item_count=len(items),
            payload_est_kb=round(len(items) * 1.45, 1),
            offset=offset,
            limit=limit,
            board_id=board_id,
            include_total=include_total,
        )

        return response

    @router.post(
        "/v1/work-items/batch",
        response_model=WorkItemBatchResponse,
        summary="Batch get work items",
        description="Fetch multiple work items in one request. Intended for hierarchy hydration on filtered board views.",
    )
    async def get_work_items_batch(
        request: Request,
        body: WorkItemBatchRequest,
    ) -> WorkItemBatchResponse:
        org_id = _get_org_id(request)

        with perf_span("work_items.batch", requested=len(body.item_ids)) as span:
            items = await run_in_threadpool(
                board_service.get_work_items_batch, body.item_ids, org_id=org_id
            )
            span["item_count"] = len(items)
        found_ids = {item.item_id for item in items}
        missing_ids = [item_id for item_id in body.item_ids if item_id not in found_ids]

        return WorkItemBatchResponse(
            items=items,
            total=len(items),
            missing_ids=missing_ids,
        )

    @router.get(
        "/v1/work-items/{item_id}",
        response_model=WorkItemResponse,
        summary="Get work item",
        description="Get work item details by ID.",
    )
    async def get_work_item(
        request: Request,
        item_id: str,
    ) -> WorkItemResponse:
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            item = board_service.get_work_item(item_id, org_id=org_id)
            return WorkItemResponse(item=item)
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/work-items/{item_id}/children",
        response_model=WorkItemListResponse,
        summary="Get child items",
        description="Get all child work items (features under goal, tasks under feature).",
    )
    async def get_children(
        request: Request,
        item_id: str,
        limit: int = Query(50, ge=1, le=250),
        offset: int = Query(0, ge=0),
    ) -> WorkItemListResponse:
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            # Verify parent exists
            await run_in_threadpool(board_service.get_work_item, item_id, org_id=org_id)

            items = await run_in_threadpool(
                board_service.list_work_items,
                parent_id=item_id,
                org_id=org_id,
                limit=limit,
                offset=offset,
            )
            return WorkItemListResponse(
                items=items,
                total=len(items),
                page=offset // limit + 1 if limit else 1,
                page_size=limit,
                has_more=len(items) == limit,
            )
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.get(
        "/v1/work-items/{item_id}/progress-rollup",
        response_model=WorkItemProgressRollupResponse,
        summary="Get work item progress rollup",
        description="Get status bucket and remaining-work rollup for a work item subtree.",
    )
    async def get_work_item_progress_rollup(
        request: Request,
        item_id: str,
        include_incomplete_descendants: bool = Query(
            False,
            description="Include incomplete descendant rows for drill-down UIs",
        ),
    ) -> WorkItemProgressRollupResponse:
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            rollup = board_service.get_work_item_progress_rollup(
                item_id,
                include_incomplete_descendants=include_incomplete_descendants,
                org_id=org_id,
            )
            return WorkItemProgressRollupResponse(rollup=rollup)
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get(
        "/v1/boards/{board_id}/progress-rollups",
        response_model=WorkItemProgressRollupListResponse,
        summary="List board progress rollups",
        description="List top-level rollups (goals/features/tasks) for a board.",
    )
    async def list_board_progress_rollups(
        request: Request,
        board_id: str,
        item_type: Optional[WorkItemType] = Query(None, description="Filter root rollups by item type"),
        include_incomplete_descendants: bool = Query(
            False,
            description="Include incomplete descendant rows for drill-down UIs",
        ),
    ) -> WorkItemProgressRollupListResponse:
        org_id = _get_org_id(request)
        _t0 = time.perf_counter()

        try:
            rollups = await run_in_threadpool(
                board_service.list_board_progress_rollups,
                board_id,
                item_type=item_type,
                include_incomplete_descendants=include_incomplete_descendants,
                org_id=org_id,
            )
            perf_log(
                "progress_rollups.list",
                round((time.perf_counter() - _t0) * 1000, 1),
                board_id=board_id,
                item_type=item_type.value if item_type else None,
                rollup_count=len(rollups),
                include_incomplete_descendants=include_incomplete_descendants,
            )
            return WorkItemProgressRollupListResponse(rollups=rollups, total=len(rollups))
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.patch(
        "/v1/work-items/{item_id}",
        response_model=WorkItemResponse,
        summary="Update work item",
        description="Update work item fields. Status transitions are validated.",
    )
    async def update_work_item(
        request: Request,
        item_id: str,
        body: UpdateWorkItemRequest,
    ) -> WorkItemResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        # GWS title validation is enforced by BoardService.update_work_item()
        try:
            item = board_service.update_work_item(item_id, body, actor, org_id=org_id)
            return WorkItemResponse(item=item)
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except WorkItemTransitionError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.post(
        "/v1/work-items/{item_id}:complete-with-descendants",
        response_model=CompleteWithDescendantsResponse,
        summary="Complete work item with descendants",
        description="Set status to 'done' for a work item and all its incomplete descendants. Use when marking a parent done and cascading to children.",
    )
    async def complete_with_descendants(
        request: Request,
        item_id: str,
    ) -> CompleteWithDescendantsResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            result = board_service.complete_with_descendants(item_id, actor, org_id=org_id)
            return CompleteWithDescendantsResponse(
                updated_count=result["updated_count"],
                updated_ids=result["updated_ids"],
            )
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # =========================================================================
    # Drag & drop (move / reorder)
    # =========================================================================

    @router.post(
        "/v1/work-items/{item_id}:move",
        response_model=WorkItemResponse,
        summary="Move work item",
        description="Move a work item to another column and/or position. Maintains per-column ordering and supports optimistic concurrency via column updated_at.",
    )
    async def move_work_item(
        request: Request,
        item_id: str,
        body: MoveWorkItemRequest,
    ) -> WorkItemResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            item = board_service.move_work_item(item_id, body, actor, org_id=org_id)
            return WorkItemResponse(item=item)
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except ColumnNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except ConcurrencyConflictError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.post(
        "/v1/work-items:reorder",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Reorder work items",
        description="Reorder all work items within a single column by providing the full ordered list.",
    )
    async def reorder_work_items(
        request: Request,
        body: ReorderWorkItemsRequest,
    ) -> None:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            board_service.reorder_work_items(body, actor, org_id=org_id)
            return None
        except ColumnNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except ConcurrencyConflictError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.post(
        "/v1/boards/{board_id}/columns:reorder",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Reorder board columns",
        description="Reorder all columns within a board by providing the full ordered list.",
    )
    async def reorder_board_columns(
        request: Request,
        board_id: str,
        body: ReorderBoardColumnsRequest,
    ) -> None:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            board_service.reorder_columns(board_id, body, actor, org_id=org_id)
            return None
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except ConcurrencyConflictError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.delete(
        "/v1/work-items/{item_id}",
        response_model=DeleteResponse,
        summary="Delete work item",
        description="Delete a work item. By default cascades to children.",
    )
    async def delete_work_item(
        request: Request,
        item_id: str,
        cascade: bool = Query(True, description="Also delete child items"),
    ) -> DeleteResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            result = board_service.delete_work_item(item_id, actor, org_id=org_id, cascade=cascade)
            return DeleteResponse(result=result)
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    # =========================================================================
    # Assignment
    # =========================================================================

    @router.post(
        "/v1/work-items/{item_id}:assign",
        response_model=AssignmentResponse,
        summary="Assign work item",
        description="Assign a work item to a user or agent.",
    )
    async def assign_work_item(
        request: Request,
        item_id: str,
        body: AssignWorkItemRequest,
    ) -> AssignmentResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            item = board_service.assign_work_item(item_id, body, actor, org_id=org_id)
            return AssignmentResponse(
                item=item,
                message=f"Assigned to {body.assignee_type.value} {body.assignee_id}",
            )
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except AssigneeNotFoundError as e:
            # Agent or user not found - return 400 with helpful message
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.post(
        "/v1/work-items/{item_id}:unassign",
        response_model=AssignmentResponse,
        summary="Unassign work item",
        description="Remove assignment from a work item.",
    )
    async def unassign_work_item(
        request: Request,
        item_id: str,
        reason: Optional[str] = Query(None, description="Reason for unassignment"),
    ) -> AssignmentResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            item = board_service.unassign_work_item(item_id, actor, reason=reason, org_id=org_id)
            return AssignmentResponse(item=item, message="Work item unassigned")
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # =========================================================================
    # Comments
    # =========================================================================

    @router.get(
        "/v1/work-items/{item_id}/comments",
        response_model=WorkItemCommentListResponse,
        summary="List work item comments",
        description="List comments on a work item, ordered oldest first.",
    )
    async def list_work_item_comments(
        request: Request,
        item_id: str,
        limit: int = Query(50, ge=1, le=200, description="Max comments to return"),
        offset: int = Query(0, ge=0, description="Comments to skip"),
    ) -> WorkItemCommentListResponse:
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            comments = board_service.list_comments(
                work_item_id=item_id,
                limit=limit,
                offset=offset,
                org_id=org_id,
            )
            return WorkItemCommentListResponse(comments=comments, total=len(comments))
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.post(
        "/v1/work-items/{item_id}/comments",
        response_model=WorkItemCommentResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Add work item comment",
        description="Add a comment to a work item.",
    )
    async def add_work_item_comment(
        request: Request,
        item_id: str,
        body: CreateWorkItemCommentRequest,
    ) -> WorkItemCommentResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)
        item_id = _resolve_item_id(item_id, request)

        try:
            comment = _post_comment_with_author_type(
                work_item_id=item_id,
                author_id=actor.id,
                requested_type=body.author_type,
                body=body,
                actor=actor,
                org_id=org_id,
            )
            return WorkItemCommentResponse(comment=comment)
        except WorkItemNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except AuthorNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # =========================================================================
    # Sprint CRUD
    # =========================================================================

    @router.post(
        "/v1/sprints",
        response_model=SprintResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create sprint",
        description="Create a new sprint for a board.",
    )
    async def create_sprint(
        request: Request,
        body: CreateSprintRequest,
    ) -> SprintResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            sprint = board_service.create_sprint(body, actor, org_id=org_id)
            return SprintResponse(sprint=sprint)
        except BoardNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get(
        "/v1/sprints/{sprint_id}",
        response_model=SprintResponse,
        summary="Get sprint",
        description="Get sprint details.",
    )
    async def get_sprint(
        request: Request,
        sprint_id: str,
    ) -> SprintResponse:
        org_id = _get_org_id(request)

        try:
            sprint = board_service.get_sprint(sprint_id, org_id=org_id)
            return SprintResponse(sprint=sprint)
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/sprints/{sprint_id}",
        response_model=SprintResponse,
        summary="Update sprint",
        description="Update sprint fields.",
    )
    async def update_sprint(
        request: Request,
        sprint_id: str,
        body: UpdateSprintRequest,
    ) -> SprintResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            sprint = board_service.update_sprint(sprint_id, body, actor, org_id=org_id)
            return SprintResponse(sprint=sprint)
        except BoardServiceError as e:
            if "not found" in str(e).lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.delete(
        "/v1/sprints/{sprint_id}",
        response_model=DeleteResponse,
        summary="Delete sprint",
        description="Delete a sprint.",
    )
    async def delete_sprint(
        request: Request,
        sprint_id: str,
    ) -> DeleteResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            result = board_service.delete_sprint(sprint_id, actor, org_id=org_id)
            return DeleteResponse(result=result)
        except BoardServiceError as e:
            if "not found" in str(e).lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # =========================================================================
    # Labels
    # =========================================================================

    @router.post(
        "/v1/projects/{project_id}/labels",
        response_model=LabelResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create label",
        description="Create a new label for a project.",
    )
    async def create_label(
        request: Request,
        project_id: str,
        body: CreateLabelRequest,
    ) -> LabelResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            label = board_service.create_label(project_id, body, actor, org_id=org_id)
            return LabelResponse(label=label)
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.get(
        "/v1/projects/{project_id}/labels",
        response_model=LabelListResponse,
        summary="List labels",
        description="List all labels for a project.",
    )
    async def list_labels(
        request: Request,
        project_id: str,
    ) -> LabelListResponse:
        org_id = _get_org_id(request)

        return board_service.list_labels(project_id, org_id=org_id)

    @router.get(
        "/v1/labels/{label_id}",
        response_model=LabelResponse,
        summary="Get label",
        description="Get a label by ID.",
    )
    async def get_label(
        request: Request,
        label_id: str,
    ) -> LabelResponse:
        org_id = _get_org_id(request)

        try:
            label = board_service.get_label(label_id, org_id=org_id)
            return LabelResponse(label=label)
        except BoardServiceError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    @router.patch(
        "/v1/labels/{label_id}",
        response_model=LabelResponse,
        summary="Update label",
        description="Update a label's name or color.",
    )
    async def update_label(
        request: Request,
        label_id: str,
        body: UpdateLabelRequest,
    ) -> LabelResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            label = board_service.update_label(label_id, body, actor, org_id=org_id)
            return LabelResponse(label=label)
        except BoardServiceError as e:
            if "not found" in str(e).lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    @router.delete(
        "/v1/labels/{label_id}",
        response_model=DeleteResponse,
        summary="Delete label",
        description="Delete a label. Removes it from all work items.",
    )
    async def delete_label(
        request: Request,
        label_id: str,
    ) -> DeleteResponse:
        actor = _get_actor(request)
        org_id = _get_org_id(request)

        try:
            result = board_service.delete_label(label_id, actor, org_id=org_id)
            return DeleteResponse(result=result)
        except BoardServiceError as e:
            if "not found" in str(e).lower():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return router
