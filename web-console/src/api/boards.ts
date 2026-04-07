/**
 * Boards + Work Items API (web console)
 *
 * Following:
 * - COLLAB_SAAS_REQUIREMENTS.md: optimistic updates, fast UI
 * - behavior_use_raze_for_logging (Student)
 */

import React from 'react';
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { razeLog } from '../telemetry/raze';

// ---------------------------------------------------------------------------
// Types (mirrors amprealize.multi_tenant.board_contracts)
// ---------------------------------------------------------------------------

export type WorkItemType = 'goal' | 'feature' | 'task' | 'bug';

/** Map legacy API type names to current names (pre-migration compat). */
const ITEM_TYPE_ALIASES: Record<string, WorkItemType> = {
  epic: 'goal',
  story: 'feature',
};
function normalizeItemType(raw: string): WorkItemType {
  return (ITEM_TYPE_ALIASES[raw] ?? raw) as WorkItemType;
}

export type WorkItemStatus =
  | 'backlog'
  | 'in_progress'
  | 'in_review'
  | 'done';

export type WorkItemPriority = 'critical' | 'high' | 'medium' | 'low';

export interface Board {
  board_id: string;
  project_id: string;
  name: string;
  description?: string | null;
  is_default: boolean;
  display_number?: number | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  org_id?: string | null;
}

export interface BoardColumn {
  column_id: string;
  board_id: string;
  name: string;
  position: number;
  status_mapping: WorkItemStatus;
  wip_limit?: number | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  org_id?: string | null;
}

export interface BoardWithColumns extends Board {
  columns: BoardColumn[];
}

export interface WorkItem {
  item_id: string;
  item_type: WorkItemType;
  project_id: string;
  board_id?: string | null;
  column_id?: string | null;
  parent_id?: string | null;
  title: string;
  description?: string | null;
  status: WorkItemStatus;
  priority: WorkItemPriority;
  position: number;
  labels: string[];
  points?: number | null;
  /** @deprecated Use points instead */
  story_points?: number | null;
  estimated_hours?: string | number | null;
  actual_hours?: string | number | null;
  assignee_id?: string | null;
  assignee_type?: 'user' | 'agent' | null;
  start_date?: string | null;
  target_date?: string | null;
  due_date?: string | null;
  completed_at?: string | null;
  behavior_id?: string | null;
  run_id?: string | null;
  display_number?: number | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  org_id?: string | null;
}

export interface ProgressBucketCounts {
  not_started: number;
  in_progress: number;
  completed: number;
  total: number;
}

export interface RemainingWorkSummary {
  items_remaining: number;
  estimated_hours_remaining?: number | null;
  points_remaining?: number | null;
  /** @deprecated Use points_remaining instead */
  story_points_remaining?: number | null;
  estimate_coverage_ratio?: number | null;
}

export interface IncompleteWorkItemSummary {
  item_id: string;
  item_type: WorkItemType;
  title: string;
  status: WorkItemStatus;
  parent_id?: string | null;
  assignee_id?: string | null;
  assignee_type?: 'user' | 'agent' | null;
  points?: number | null;
  /** @deprecated Use points instead */
  story_points?: number | null;
  estimated_hours?: number | null;
  actual_hours?: number | null;
}

export interface WorkItemProgressRollup {
  item_id: string;
  item_type: WorkItemType;
  title: string;
  status: WorkItemStatus;
  buckets: ProgressBucketCounts;
  remaining: RemainingWorkSummary;
  completion_percent: number;
  incomplete_items: IncompleteWorkItemSummary[];
}

export type WorkItemCommentAuthorType = 'user' | 'agent';

export interface WorkItemComment {
  comment_id: string;
  work_item_id: string;
  author_id: string;
  author_type: WorkItemCommentAuthorType;
  content: string;
  run_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CreateWorkItemCommentRequest {
  body: string;
  author_type?: WorkItemCommentAuthorType;
  run_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateBoardRequest {
  project_id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  create_default_columns?: boolean;
}

export interface CreateWorkItemRequest {
  item_type: WorkItemType;
  project_id: string;
  board_id: string;
  column_id?: string;
  title: string;
  description?: string;
  priority?: WorkItemPriority;
}

export interface UpdateWorkItemRequest {
  title?: string;
  description?: string | null;
  status?: WorkItemStatus;
  priority?: WorkItemPriority;
  labels?: string[];
  parent_id?: string | null;
  points?: number | null;
  /** @deprecated Use points instead */
  story_points?: number | null;
  estimated_hours?: string | number | null;
  actual_hours?: string | number | null;
  start_date?: string | null;
  target_date?: string | null;
  due_date?: string | null;
  behavior_id?: string | null;
  run_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface MoveWorkItemRequest {
  column_id: string | null;
  position: number;
  expected_from_column_updated_at?: string | null;
  expected_to_column_updated_at?: string | null;
}

export interface AssignWorkItemRequest {
  assignee_id: string;
  assignee_type: 'user' | 'agent';
  reason?: string;
}

interface AssignmentResponse {
  item: WorkItem;
  message?: string;
}

interface DeleteResult {
  deleted_id: string;
  deleted_type: string;
  cascade_deleted?: string[];
}

interface DeleteResponse {
  result: DeleteResult;
}

// ---------------------------------------------------------------------------
// Query Keys
// ---------------------------------------------------------------------------

export const boardKeys = {
  all: ['boards'] as const,
  list: (projectId?: string) => [...boardKeys.all, 'list', projectId] as const,
  board: (boardId?: string) => [...boardKeys.all, 'board', boardId] as const,
  items: (boardId?: string, serverParams?: Record<string, string>) =>
    [...boardKeys.all, 'items', boardId, ...(serverParams && Object.keys(serverParams).length ? [serverParams] : [])] as const,
  item: (itemId?: string) => [...boardKeys.all, 'item', itemId] as const,
  comments: (itemId?: string) => [...boardKeys.all, 'comments', itemId] as const,
  rollups: (boardId?: string, itemType?: WorkItemType, includeIncomplete?: boolean) =>
    [...boardKeys.all, 'rollups', boardId, itemType ?? 'all', includeIncomplete ? 'with-incomplete' : 'summary'] as const,
  rollup: (itemId?: string, includeIncomplete?: boolean) =>
    [...boardKeys.all, 'rollup', itemId, includeIncomplete ? 'with-incomplete' : 'summary'] as const,
};

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useBoards(projectId?: string) {
  return useQuery({
    queryKey: boardKeys.list(projectId),
    queryFn: async (): Promise<Board[]> => {
      if (!projectId) return [];
      try {
        const response = await apiClient.get<{ boards: Board[] }>(
          `/v1/boards?project_id=${encodeURIComponent(projectId)}`
        );
        return response.boards ?? [];
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return [];
        throw error;
      }
    },
    enabled: Boolean(projectId),
    staleTime: 15_000,
  });
}

export function useCreateBoard() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateBoardRequest): Promise<Board> => {
      await razeLog('INFO', 'Board create requested', {
        project_id: payload.project_id,
        name: payload.name,
      });

      const response = await apiClient.post<{ board: Board }>('/v1/boards', payload);
      await razeLog('INFO', 'Board created', {
        project_id: payload.project_id,
        board_id: response.board.board_id,
      });
      return response.board;
    },
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.list(payload.project_id) });

      const previous = queryClient.getQueryData<Board[]>(boardKeys.list(payload.project_id)) ?? [];
      const optimisticId = `temp-board-${Date.now()}`;

      const now = new Date().toISOString();
      const optimistic: Board = {
        board_id: optimisticId,
        project_id: payload.project_id,
        name: payload.name,
        description: payload.description ?? null,
        is_default: Boolean(payload.is_default),
        created_at: now,
        updated_at: now,
        created_by: 'me',
        org_id: null,
      };

      queryClient.setQueryData<Board[]>(boardKeys.list(payload.project_id), [optimistic, ...previous]);
      return { previous, optimisticId };
    },
    onError: async (error, payload, context) => {
      queryClient.setQueryData(boardKeys.list(payload.project_id), context?.previous ?? []);
      await razeLog('ERROR', 'Board create failed', {
        project_id: payload.project_id,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (created, payload, context) => {
      queryClient.setQueryData<Board[]>(boardKeys.list(payload.project_id), (current) => {
        const list = current ?? [];
        const replaced = list.map((b) => (b.board_id === context?.optimisticId ? created : b));
        return replaced.some((b) => b.board_id === created.board_id) ? replaced : [created, ...replaced];
      });
    },
  });
}

export function useBoard(boardId?: string) {
  return useQuery({
    queryKey: boardKeys.board(boardId),
    queryFn: async (): Promise<BoardWithColumns | null> => {
      if (!boardId) return null;
      const response = await apiClient.get<{ board: BoardWithColumns }>(`/v1/boards/${boardId}`);
      return response.board ?? null;
    },
    enabled: Boolean(boardId),
    staleTime: 5_000,
  });
}

/* ─────────────────────────────────────────────────────────────────────────────
   Work Item Loading

   Fetches all work items for a board in a single query (paginating internally
   so the UI never sees a partial set). Background polling silently refreshes
   the data every few seconds without any visual loading indicators.
   ───────────────────────────────────────────────────────────────────────────── */

/**
 * Must stay ≤ the deployed API's `GET /v1/work-items` `limit` max (see board_api_v2).
 * Use 100 so older gateways/builds that still cap at le=100 do not return 422 and break the board.
 * After every surface allows 250+, you can raise this to reduce pagination on very large boards.
 */
const ITEMS_PAGE_SIZE = 100;

/** Stable empty array to avoid reference changes when data is null */
const EMPTY_ITEMS: WorkItem[] = [];

interface WorkItemsResult {
  /** All work items for the board */
  data: WorkItem[];
  /** True only during first fetch (shows skeleton) */
  isInitialLoading: boolean;
  /** Timestamp of last successful sync */
  lastSyncedAt: Date | null;
  /** True only during user-initiated refetch (not background polls) */
  isRefreshing: boolean;
  /** Error state */
  error: Error | null;
  /** Manual refetch trigger */
  refetch: () => Promise<void>;
}

/** Background polling interval when tab is visible (ms) */
const BACKGROUND_POLL_INTERVAL = 15_000;

/** Hook to track document visibility for smart polling */
function useDocumentVisible(): boolean {
  const [isVisible, setIsVisible] = React.useState(() =>
    typeof document !== 'undefined' ? !document.hidden : true
  );

  React.useEffect(() => {
    const handleVisibility = () => setIsVisible(!document.hidden);
    document.addEventListener('visibilitychange', handleVisibility);
    return () => document.removeEventListener('visibilitychange', handleVisibility);
  }, []);

  return isVisible;
}

function buildWorkItemsQs(
  boardId: string,
  limit: number,
  offset: number,
  serverParams?: Record<string, string>,
): string {
  const qs = new URLSearchParams({
    board_id: boardId,
    limit: String(limit),
    offset: String(offset),
  });
  if (serverParams) {
    for (const [key, value] of Object.entries(serverParams)) {
      if (value) qs.set(key, value);
    }
  }
  return qs.toString();
}

function normalizePageItems(items: WorkItem[]): WorkItem[] {
  return items.map((item) => ({
    ...item,
    item_type: normalizeItemType(item.item_type),
    points: item.points ?? item.story_points ?? null,
  }));
}

/**
 * Fetch all work items for a board.
 *
 * Large boards can trip API rate limits if we burst too many paginated
 * requests too quickly, so after the first page we continue sequentially and
 * retry 429 responses with small backoff.
 */
const MAX_PARALLEL_PAGES = 0;
const WORK_ITEMS_429_RETRY_DELAYS_MS = [250, 750, 1500] as const;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchAllWorkItems(
  boardId: string,
  serverParams?: Record<string, string>,
): Promise<WorkItem[]> {
  const fetchPage = async (offset: number) => {
    for (let attempt = 0; attempt <= WORK_ITEMS_429_RETRY_DELAYS_MS.length; attempt += 1) {
      try {
        const r = await apiClient.get<{ items: WorkItem[]; has_more?: boolean }>(
          `/v1/work-items?${buildWorkItemsQs(boardId, ITEMS_PAGE_SIZE, offset, serverParams)}`
        );
        return { items: normalizePageItems(r.items ?? []), hasMore: r.has_more === true };
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 429 || attempt === WORK_ITEMS_429_RETRY_DELAYS_MS.length) {
          throw error;
        }
        await sleep(WORK_ITEMS_429_RETRY_DELAYS_MS[attempt]);
      }
    }

    return { items: [], hasMore: false };
  };

  const first = await fetchPage(0);
  if (!first.hasMore || first.items.length < ITEMS_PAGE_SIZE) {
    return first.items;
  }

  const parallelResults = await Promise.all(
    Array.from({ length: MAX_PARALLEL_PAGES }, (_, i) => fetchPage((i + 1) * ITEMS_PAGE_SIZE))
  );

  let all = first.items;
  let exhausted = false;
  for (const page of parallelResults) {
    if (page.items.length === 0) { exhausted = true; break; }
    all = all.concat(page.items);
    if (!page.hasMore) { exhausted = true; break; }
  }

  if (!exhausted) {
    let offset = (MAX_PARALLEL_PAGES + 1) * ITEMS_PAGE_SIZE;
    let more = true;
    while (more) {
      // Small pause between pages to avoid tripping API rate limits on large boards.
      await sleep(120);
      const page = await fetchPage(offset);
      if (page.items.length === 0) break;
      all = all.concat(page.items);
      more = page.hasMore;
      offset += ITEMS_PAGE_SIZE;
    }
  }

  return all;
}

export function useWorkItems(boardId?: string, serverParams?: Record<string, string>): WorkItemsResult {
  const isTabVisible = useDocumentVisible();

  // Track manual (user-initiated) refreshes separately from background polls
  const isManualRefreshRef = React.useRef(false);
  const [isManualRefreshing, setIsManualRefreshing] = React.useState(false);

  // Suppress background polling while a board mutation (move/reorder) is
  // in-flight.  The poll can fire right after a drop if its timer was already
  // partway through, replacing the optimistic cache and causing a visible
  // column stutter.  useIsMutating returns > 0 while any matching mutation
  // is pending.
  const activeBoardMutations = useIsMutating({
    mutationKey: ['board-item-mutate', boardId],
  });
  const pollActive = isTabVisible && activeBoardMutations === 0;

  const query = useQuery({
    queryKey: boardKeys.items(boardId, serverParams),
    queryFn: () => fetchAllWorkItems(boardId!, serverParams),
    enabled: Boolean(boardId),
    staleTime: 3_000,
    refetchInterval: pollActive ? BACKGROUND_POLL_INTERVAL : false,
    refetchIntervalInBackground: false,
  });

  // Clear manual refresh flag when fetch completes
  React.useEffect(() => {
    if (!query.isFetching && isManualRefreshRef.current) {
      isManualRefreshRef.current = false;
      setIsManualRefreshing(false);
    }
  }, [query.isFetching]);

  // Derive lastSyncedAt from React Query's internal timestamp
  const lastSyncedAt = React.useMemo(() => {
    const ts = query.dataUpdatedAt;
    return ts ? new Date(ts) : null;
  }, [query.dataUpdatedAt]);

  const refetch = React.useCallback(async () => {
    isManualRefreshRef.current = true;
    setIsManualRefreshing(true);
    await query.refetch();
  }, [query]);

  return {
    data: query.data ?? EMPTY_ITEMS,
    isInitialLoading: query.isLoading && !query.data,
    lastSyncedAt,
    isRefreshing: isManualRefreshing,
    error: query.error,
    refetch,
  };
}

/**
 * Fetch all rollups for a board in a single request (no item_type filter),
 * then derive per-type subsets client-side. This replaces two separate
 * network calls (goals + features) with one.
 */
export function useBoardAllRollups(
  boardId?: string,
  options?: { includeIncompleteDescendants?: boolean }
) {
  const includeIncompleteDescendants = options?.includeIncompleteDescendants ?? false;

  const query = useQuery({
    queryKey: boardKeys.rollups(boardId, undefined, includeIncompleteDescendants),
    queryFn: async (): Promise<WorkItemProgressRollup[]> => {
      if (!boardId) return [];
      const qs = new URLSearchParams();
      if (includeIncompleteDescendants) qs.set('include_incomplete_descendants', 'true');
      const suffix = qs.toString();
      const response = await apiClient.get<{ rollups: WorkItemProgressRollup[] }>(
        `/v1/boards/${boardId}/progress-rollups${suffix ? `?${suffix}` : ''}`
      );
      return response.rollups ?? [];
    },
    enabled: Boolean(boardId),
    staleTime: 5_000,
  });

  return query;
}

/**
 * Derive rollups for a specific item type from the combined query.
 * Returns the same shape as the old per-type hook so callers don't change.
 */
export function useBoardProgressRollups(
  boardId?: string,
  options?: { itemType?: WorkItemType; includeIncompleteDescendants?: boolean }
) {
  const itemType = options?.itemType;
  const includeIncompleteDescendants = options?.includeIncompleteDescendants ?? false;

  const allRollups = useBoardAllRollups(boardId, { includeIncompleteDescendants });

  const data = React.useMemo(() => {
    if (!allRollups.data) return undefined;
    if (!itemType) return allRollups.data;
    return allRollups.data.filter((r) => r.item_type === itemType);
  }, [allRollups.data, itemType]);

  return {
    ...allRollups,
    data,
  };
}

export function useWorkItemProgressRollup(
  itemId?: string,
  options?: { includeIncompleteDescendants?: boolean; enabled?: boolean }
) {
  const includeIncompleteDescendants = options?.includeIncompleteDescendants ?? false;
  const enabled = options?.enabled ?? true;

  return useQuery({
    queryKey: boardKeys.rollup(itemId, includeIncompleteDescendants),
    queryFn: async (): Promise<WorkItemProgressRollup | null> => {
      if (!itemId) return null;
      const qs = new URLSearchParams();
      if (includeIncompleteDescendants) qs.set('include_incomplete_descendants', 'true');
      const suffix = qs.toString();
      const response = await apiClient.get<{ rollup: WorkItemProgressRollup }>(
        `/v1/work-items/${itemId}/progress-rollup${suffix ? `?${suffix}` : ''}`
      );
      return response.rollup ?? null;
    },
    enabled: Boolean(itemId) && enabled,
    staleTime: 2_000,
  });
}

export function useWorkItem(itemId?: string, initialData?: WorkItem) {
  return useQuery({
    queryKey: boardKeys.item(itemId),
    queryFn: async (): Promise<WorkItem | null> => {
      if (!itemId) return null;
      const response = await apiClient.get<{ item: WorkItem }>(`/v1/work-items/${itemId}`);
      return response.item ?? null;
    },
    enabled: Boolean(itemId),
    staleTime: 2_000,
    initialData: itemId && initialData ? initialData : undefined,
  });
}

export function useWorkItemComments(
  itemId?: string,
  options?: { limit?: number; offset?: number; enabled?: boolean }
) {
  const limit = options?.limit ?? 200;
  const offset = options?.offset ?? 0;

  return useQuery({
    queryKey: boardKeys.comments(itemId),
    queryFn: async (): Promise<WorkItemComment[]> => {
      if (!itemId) return [];
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('offset', String(offset));
      const suffix = params.toString();
      const response = await apiClient.get<{ comments: WorkItemComment[] }>(
        `/v1/work-items/${itemId}/comments${suffix ? `?${suffix}` : ''}`
      );
      return response.comments ?? [];
    },
    enabled: Boolean(itemId) && (options?.enabled ?? true),
    staleTime: 2_000,
  });
}

export function useCreateWorkItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: CreateWorkItemRequest): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item create requested', {
        project_id: payload.project_id,
        board_id: payload.board_id,
        column_id: payload.column_id ?? null,
        item_type: payload.item_type,
      });

      const response = await apiClient.post<{ item: WorkItem }>('/v1/work-items', {
        ...payload,
        priority: payload.priority ?? 'medium',
        metadata: {},
        labels: [],
        acceptance_criteria: [],
        checklist: [],
      });
      return response.item;
    },
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.items(payload.board_id) });

      const previous = queryClient.getQueryData<WorkItem[]>(boardKeys.items(payload.board_id)) ?? [];
      const optimisticId = `temp-item-${Date.now()}`;
      const now = new Date().toISOString();
      const optimistic: WorkItem = {
        item_id: optimisticId,
        item_type: payload.item_type,
        project_id: payload.project_id,
        board_id: payload.board_id,
        column_id: payload.column_id ?? null,
        parent_id: null,
        title: payload.title,
        description: payload.description ?? null,
        status: 'backlog',
        priority: payload.priority ?? 'medium',
        position: 0,
        labels: [],
        created_at: now,
        updated_at: now,
        created_by: 'me',
        org_id: null,
      };

      queryClient.setQueryData<WorkItem[]>(boardKeys.items(payload.board_id), [optimistic, ...previous]);
      return { previous, optimisticId };
    },
    onError: async (error, payload, context) => {
      queryClient.setQueryData(boardKeys.items(payload.board_id), context?.previous ?? []);
      await razeLog('ERROR', 'Work item create failed', {
        project_id: payload.project_id,
        board_id: payload.board_id,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (created, payload, context) => {
      queryClient.setQueryData<WorkItem[]>(boardKeys.items(payload.board_id), (current) => {
        const list = current ?? [];
        const replaced = list.map((i) => (i.item_id === context?.optimisticId ? created : i));
        return replaced.some((i) => i.item_id === created.item_id) ? replaced : [created, ...replaced];
      });
    },
  });
}

export function useMoveWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['board-item-mutate', boardId],
    mutationFn: async (input: { itemId: string; move: MoveWorkItemRequest }): Promise<WorkItem> => {
      if (!boardId) throw new Error('boardId is required');
      const response = await apiClient.post<{ item: WorkItem }>(`/v1/work-items/${input.itemId}:move`, input.move);
      return response.item;
    },
    onMutate: async (input) => {
      if (!boardId) return {};
      await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });

      const previous = queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? [];
      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;

      // Optimistically update the items list — simulate the backend's
      // remove-then-insert so positions are correct immediately.
      queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
        const list = current ?? [];
        const targetCol = input.move.column_id;
        const targetPos = input.move.position;
        const movedId = input.itemId;

        // Find the moved item's current state
        const movedItem = list.find((i) => i.item_id === movedId);
        const sourceCol = movedItem?.column_id;
        const sourcePos = movedItem?.position ?? 0;
        const sameColumn = sourceCol === targetCol;

        return list.map((item) => {
          if (item.item_id === movedId) {
            return { ...item, column_id: targetCol, position: targetPos };
          }

          let pos = item.position ?? 0;

          // Step 1: If same-column move, close the gap at the old position
          if (sameColumn && item.column_id === sourceCol && pos > sourcePos) {
            pos = pos - 1;
          }

          // Step 2: Open a gap at the target position
          if (item.column_id === targetCol && pos >= targetPos) {
            pos = pos + 1;
          }

          if (pos !== (item.position ?? 0)) {
            return { ...item, position: pos };
          }
          return item;
        });
      });

      // Optimistically update the individual item query (for the drawer)
      if (previousItem) {
        queryClient.setQueryData<WorkItem>(boardKeys.item(input.itemId), {
          ...previousItem,
          column_id: input.move.column_id,
          position: input.move.position,
        });
      }

      return { previous, previousItem };
    },
    onError: async (error, input, context) => {
      if (!boardId) return;
      const ctx = context as { previous?: WorkItem[]; previousItem?: WorkItem | null } | undefined;
      queryClient.setQueryData(boardKeys.items(boardId), ctx?.previous ?? []);
      if (ctx?.previousItem !== undefined) {
        queryClient.setQueryData(boardKeys.item(input.itemId), ctx.previousItem);
      }
      await razeLog('ERROR', 'Work item move failed', {
        board_id: boardId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      if (!boardId) return;
      // Only update the individual item query (for the drawer/detail view).
      // Skip the full items-list setQueryData — the optimistic positions from
      // onMutate are already correct and replacing the list creates a new array
      // reference that causes every column to re-render (visible stutter).
      // The background poll reconciles the list data shortly after.
      queryClient.setQueryData<WorkItem>(boardKeys.item(updated.item_id), updated);
    },
  });
}

export interface ReorderWorkItemsInput {
  columnId: string;
  orderedItemIds: string[];
}

export function useReorderWorkItems(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['board-item-mutate', boardId],
    mutationFn: async (input: ReorderWorkItemsInput): Promise<void> => {
      if (!boardId) throw new Error('boardId is required');
      await apiClient.post('/v1/work-items:reorder', {
        column_id: input.columnId,
        ordered_item_ids: input.orderedItemIds,
      });
    },
    onMutate: async (input) => {
      if (!boardId) return {};
      await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });

      const previous = queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? [];

      // Optimistically assign 0-based positions matching the ordered list
      const positionMap = new Map<string, number>();
      input.orderedItemIds.forEach((id, idx) => positionMap.set(id, idx));

      queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
        const list = current ?? [];
        return list.map((item) => {
          const newPos = positionMap.get(item.item_id);
          if (newPos !== undefined && item.position !== newPos) {
            return { ...item, position: newPos };
          }
          return item;
        });
      });

      return { previous };
    },
    onError: async (_error, _input, context) => {
      if (!boardId) return;
      const ctx = context as { previous?: WorkItem[] } | undefined;
      queryClient.setQueryData(boardKeys.items(boardId), ctx?.previous ?? []);
    },
    onSuccess: async () => {
      if (!boardId) return;
      // Keep the optimistic order as source-of-truth for immediate UX smoothness.
      // Background polling (useWorkItems) reconciles with server shortly after
      // without triggering an immediate whole-column visual refresh.
    },
  });
}

export function useUpdateWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { itemId: string; patch: UpdateWorkItemRequest }): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item update requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        fields: Object.keys(input.patch),
      });
      const response = await apiClient.patch<{ item: WorkItem }>(`/v1/work-items/${input.itemId}`, input.patch);
      return response.item;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const applyPatch = (item: WorkItem): WorkItem => ({ ...item, ...input.patch });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      if (boardId) {
        queryClient.setQueryData(boardKeys.items(boardId), (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []);
      }
      await razeLog('ERROR', 'Work item update failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === updated.item_id ? updated : item));
        });
      }
      await razeLog('INFO', 'Work item updated', {
        board_id: boardId ?? null,
        item_id: updated.item_id,
      });
    },
  });
}

export function useDeleteWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { itemId: string; cascade?: boolean }): Promise<DeleteResult> => {
      const cascade = input.cascade !== false;
      await razeLog('INFO', 'Work item delete requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        cascade,
      });
      const response = await apiClient.delete<DeleteResponse>(
        `/v1/work-items/${input.itemId}?cascade=${cascade ? 'true' : 'false'}`
      );
      return response.result;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const idsToRemove = new Set<string>([input.itemId]);
      if (input.cascade !== false && previousItems) {
        let added = true;
        while (added) {
          added = false;
          previousItems.forEach((item) => {
            if (item.parent_id && idsToRemove.has(item.parent_id) && !idsToRemove.has(item.item_id)) {
              idsToRemove.add(item.item_id);
              added = true;
            }
          });
        }
      }

      queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), null);
      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.filter((item) => !idsToRemove.has(item.item_id));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(
        boardKeys.item(input.itemId),
        (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null
      );
      if (boardId) {
        queryClient.setQueryData(
          boardKeys.items(boardId),
          (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []
        );
      }
      await razeLog('ERROR', 'Work item delete failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (result) => {
      queryClient.removeQueries({ queryKey: boardKeys.item(result.deleted_id), exact: true });
      await razeLog('INFO', 'Work item deleted', {
        board_id: boardId ?? null,
        item_id: result.deleted_id,
        deleted_type: result.deleted_type,
        cascade_deleted_count: result.cascade_deleted?.length ?? 0,
      });
    },
  });
}

export function useAssignWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['board-item-mutate', boardId],
    mutationFn: async (input: { itemId: string; assigneeId: string; assigneeType: 'user' | 'agent'; reason?: string }): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item assign requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      });
      const payload: AssignWorkItemRequest = {
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      };
      if (input.reason) payload.reason = input.reason;
      const response = await apiClient.post<AssignmentResponse>(`/v1/work-items/${input.itemId}:assign`, payload);
      return response.item;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const applyPatch = (item: WorkItem): WorkItem => ({
        ...item,
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      if (boardId) {
        queryClient.setQueryData(boardKeys.items(boardId), (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []);
      }
      await razeLog('ERROR', 'Work item assign failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === updated.item_id ? updated : item));
        });
      }
      await razeLog('INFO', 'Work item assigned', {
        board_id: boardId ?? null,
        item_id: updated.item_id,
        assignee_id: updated.assignee_id ?? null,
        assignee_type: updated.assignee_type ?? null,
      });
    },
  });
}

export function useUnassignWorkItem(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ['board-item-mutate', boardId],
    mutationFn: async (input: { itemId: string; reason?: string }): Promise<WorkItem> => {
      await razeLog('INFO', 'Work item unassign requested', {
        board_id: boardId ?? null,
        item_id: input.itemId,
      });
      const reasonParam = input.reason ? `?reason=${encodeURIComponent(input.reason)}` : '';
      const response = await apiClient.post<AssignmentResponse>(`/v1/work-items/${input.itemId}:unassign${reasonParam}`, {});
      return response.item;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });
      if (boardId) {
        await queryClient.cancelQueries({ queryKey: boardKeys.items(boardId) });
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItems = boardId ? (queryClient.getQueryData<WorkItem[]>(boardKeys.items(boardId)) ?? []) : null;

      const applyPatch = (item: WorkItem): WorkItem => ({
        ...item,
        assignee_id: null,
        assignee_type: null,
      });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId && previousItems) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
        });
      }

      return { previousItem, previousItems };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      if (boardId) {
        queryClient.setQueryData(boardKeys.items(boardId), (context as { previousItems?: WorkItem[] } | undefined)?.previousItems ?? []);
      }
      await razeLog('ERROR', 'Work item unassign failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId), (current) => {
          const list = current ?? [];
          return list.map((item) => (item.item_id === updated.item_id ? updated : item));
        });
      }
      await razeLog('INFO', 'Work item unassigned', {
        board_id: boardId ?? null,
        item_id: updated.item_id,
      });
    },
  });
}

export function usePostWorkItemComment(itemId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      body: string;
      authorId: string;
      authorType: WorkItemCommentAuthorType;
      runId?: string | null;
      metadata?: Record<string, unknown>;
    }): Promise<WorkItemComment> => {
      if (!itemId) throw new Error('itemId is required');
      await razeLog('INFO', 'Work item comment post requested', {
        item_id: itemId,
        author_id: input.authorId,
        author_type: input.authorType,
      });
      const response = await apiClient.post<{ comment: WorkItemComment }>(
        `/v1/work-items/${itemId}/comments`,
        {
          body: input.body,
          author_type: input.authorType,
          run_id: input.runId ?? undefined,
          metadata: input.metadata ?? undefined,
        } satisfies CreateWorkItemCommentRequest
      );
      return response.comment;
    },
    onMutate: async (input) => {
      if (!itemId) return {};
      await queryClient.cancelQueries({ queryKey: boardKeys.comments(itemId) });

      const previous = queryClient.getQueryData<WorkItemComment[]>(boardKeys.comments(itemId)) ?? [];
      const optimisticId = `temp-comment-${Date.now()}`;
      const now = new Date().toISOString();
      const optimistic: WorkItemComment = {
        comment_id: optimisticId,
        work_item_id: itemId,
        author_id: input.authorId,
        author_type: input.authorType,
        content: input.body,
        run_id: input.runId ?? null,
        metadata: input.metadata ?? {},
        created_at: now,
        updated_at: now,
      };
      queryClient.setQueryData<WorkItemComment[]>(boardKeys.comments(itemId), [...previous, optimistic]);

      return { previous, optimisticId };
    },
    onError: async (error, _input, context) => {
      if (!itemId) return;
      const previous = (context as { previous?: WorkItemComment[] } | undefined)?.previous ?? [];
      queryClient.setQueryData(boardKeys.comments(itemId), previous);
      await razeLog('ERROR', 'Work item comment post failed', {
        item_id: itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (comment, _input, context) => {
      if (!itemId) return;
      const optimisticId = (context as { optimisticId?: string } | undefined)?.optimisticId ?? null;
      queryClient.setQueryData<WorkItemComment[]>(boardKeys.comments(itemId), (current) => {
        const list = current ?? [];
        if (!optimisticId) return [...list, comment];
        const replaced = list.map((entry) => (entry.comment_id === optimisticId ? comment : entry));
        return replaced.some((entry) => entry.comment_id === comment.comment_id) ? replaced : [...replaced, comment];
      });
      await razeLog('INFO', 'Work item comment posted', {
        item_id: itemId,
        comment_id: comment.comment_id,
      });
    },
  });
}

export interface CompleteWithDescendantsResponse {
  updated_count: number;
  updated_ids: string[];
}

export function useCompleteWithDescendants(boardId?: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (itemId: string): Promise<CompleteWithDescendantsResponse> => {
      await razeLog('INFO', 'Complete with descendants requested', {
        board_id: boardId ?? null,
        item_id: itemId,
      });
      const response = await apiClient.post<CompleteWithDescendantsResponse>(
        `/v1/work-items/${itemId}:complete-with-descendants`,
        {}
      );
      return response;
    },
    onSuccess: async (result, itemId) => {
      // Invalidate all affected items and rollups
      await queryClient.invalidateQueries({ queryKey: boardKeys.item(itemId) });
      if (boardId) {
        await queryClient.invalidateQueries({ queryKey: boardKeys.items(boardId) });
      }
      // Invalidate rollups that might be affected
      await queryClient.invalidateQueries({ queryKey: ['work-item-rollup'] });
      await razeLog('INFO', 'Complete with descendants succeeded', {
        board_id: boardId ?? null,
        item_id: itemId,
        updated_count: result.updated_count,
      });
    },
    onError: async (error, itemId) => {
      await razeLog('ERROR', 'Complete with descendants failed', {
        board_id: boardId ?? null,
        item_id: itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
  });
}
