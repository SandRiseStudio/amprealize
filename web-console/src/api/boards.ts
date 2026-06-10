/**
 * Boards + Work Items API (web console)
 *
 * Following:
 * - COLLAB_SAAS_REQUIREMENTS.md: optimistic updates, fast UI
 * - behavior_use_raze_for_logging (Student)
 */

import React from 'react';
import type { QueryClient } from '@tanstack/react-query';
import {
  keepPreviousData,
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { perfMark, razeLog } from '../telemetry/raze';

// ---------------------------------------------------------------------------
// Opt-in board load timing (baseline before/after perf work)
// Enable: localStorage.setItem('amprealize.boardLoadBench', '1') then reload.
// Disable: localStorage.removeItem('amprealize.boardLoadBench')
// Emits console [boardLoadBench] lines + performance.mark('perf:board:…').
// ---------------------------------------------------------------------------

const BOARD_LOAD_BENCH_LS_KEY = 'amprealize.boardLoadBench';

/** True when client-side board/work-item load benchmarking is enabled. */
export function isBoardLoadBenchEnabled(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(BOARD_LOAD_BENCH_LS_KEY) === '1';
  } catch {
    return false;
  }
}

function boardLoadBench(phase: string, detail: Record<string, unknown>): void {
  if (!isBoardLoadBenchEnabled()) return;
  console.info('[boardLoadBench]', { phase, ...detail });
}

function boardLoadBenchMark(name: string, detail: Record<string, unknown> = {}): void {
  if (!isBoardLoadBenchEnabled()) return;
  try {
    perfMark(`board:${name}`, detail);
  } catch {
    /* perf API missing in test env */
  }
}

// ---------------------------------------------------------------------------
// Types (mirrors amprealize.multi_tenant.board_contracts)
// ---------------------------------------------------------------------------

export type WorkItemType = 'goal' | 'feature' | 'task' | 'bug' | 'research';

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
export type BoardWorkItemSortField =
  | 'position'
  | 'priority'
  | 'created_at'
  | 'updated_at'
  | 'due_date'
  | 'title'
  | 'points';
export type BoardWorkItemSortOrder = 'asc' | 'desc';

export interface BoardWorkItemQuery {
  titleSearch?: string;
  itemTypes?: WorkItemType[];
  priorities?: WorkItemPriority[];
  assigneeId?: string | null;
  assigneeType?: 'user' | 'agent' | null;
  labels?: string[];
  dueAfter?: string | null;
  dueBefore?: string | null;
  sortBy?: BoardWorkItemSortField;
  order?: BoardWorkItemSortOrder;
}

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

export interface BoardBootstrapResponse {
  board: BoardWithColumns;
  items: WorkItem[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  rollups: WorkItemProgressRollup[];
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
  research_url?: string;
  metadata?: Record<string, unknown>;
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
  research_url?: string | null;
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
  bootstrap: (boardId?: string) => [...boardKeys.all, 'bootstrap', boardId] as const,
  items: (boardId?: string, query?: BoardWorkItemQuery) =>
    [...boardKeys.all, 'items', boardId, ...(query ? [query] : [])] as const,
  itemsMeta: (boardId?: string, query?: BoardWorkItemQuery) =>
    [...boardKeys.all, 'itemsMeta', boardId, ...(query ? [query] : [])] as const,
  item: (itemId?: string) => [...boardKeys.all, 'item', itemId] as const,
  comments: (itemId?: string) => [...boardKeys.all, 'comments', itemId] as const,
  rollups: (boardId?: string, itemType?: WorkItemType, includeIncomplete?: boolean) =>
    [...boardKeys.all, 'rollups', boardId, itemType ?? 'all', includeIncomplete ? 'with-incomplete' : 'summary'] as const,
  rollup: (itemId?: string, includeIncomplete?: boolean) =>
    [...boardKeys.all, 'rollup', itemId, includeIncomplete ? 'with-incomplete' : 'summary'] as const,
};

/** True when queryKey is boardKeys.items(boardId, anyQuery?) */
export function isBoardWorkItemsQueryKey(key: unknown, boardId: string): boolean {
  return (
    Array.isArray(key)
    && key[0] === boardKeys.all[0]
    && key[1] === 'items'
    && key[2] === boardId
  );
}

function boardWorkItemQueryFromKey(key: readonly unknown[]): BoardWorkItemQuery | undefined {
  const raw = key[3];
  if (raw && typeof raw === 'object') return raw as BoardWorkItemQuery;
  return undefined;
}

async function cancelAllBoardItemQueriesForBoard(queryClient: QueryClient, boardId: string) {
  await queryClient.cancelQueries({
    predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
  });
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useBoards(projectId?: string, options?: { enabled?: boolean }) {
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
    enabled: Boolean(projectId) && (options?.enabled ?? true),
    staleTime: 15_000,
  });
}

/**
 * Bulk-fetch boards for multiple projects via parallel per-project requests,
 * then seed per-project query caches so `useBoards(projectId)` picks them up
 * for free.  Returns a Map<projectId, Board[]> for direct consumption.
 */
export function useBoardsMultiProject(projectIds: string[]): {
  data: Map<string, Board[]>;
  isLoading: boolean;
} {
  const queryClient = useQueryClient();
  const stableKey = projectIds.slice().sort().join(',');

  const query = useQuery({
    queryKey: [...boardKeys.all, 'multi', stableKey],
    queryFn: async (): Promise<Board[]> => {
      if (projectIds.length === 0) return [];
      const results = await Promise.allSettled(
        projectIds.map(pid =>
          apiClient.get<{ boards: Board[] }>(
            `/v1/boards?project_id=${encodeURIComponent(pid)}`
          )
        )
      );
      return results.flatMap(r =>
        r.status === 'fulfilled' ? (r.value.boards ?? []) : []
      );
    },
    enabled: projectIds.length > 0,
    staleTime: 15_000,
  });

  const boardsByProject = React.useMemo(() => {
    const map = new Map<string, Board[]>();
    if (!query.data) return map;
    const wantedSet = new Set(projectIds);
    for (const board of query.data) {
      if (!wantedSet.has(board.project_id)) continue;
      const bucket = map.get(board.project_id);
      if (bucket) {
        bucket.push(board);
      } else {
        map.set(board.project_id, [board]);
      }
    }
    return map;
  }, [query.data, projectIds]);

  React.useEffect(() => {
    if (!query.data) return;
    boardsByProject.forEach((boards, projectId) => {
      queryClient.setQueryData(boardKeys.list(projectId), boards);
    });
  }, [boardsByProject, query.data, queryClient]);

  return { data: boardsByProject, isLoading: query.isLoading };
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

export function useBoard(boardId?: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: boardKeys.board(boardId),
    queryFn: async (): Promise<BoardWithColumns | null> => {
      if (!boardId) return null;
      const response = await apiClient.get<{ board: BoardWithColumns }>(`/v1/boards/${boardId}`);
      return response.board ?? null;
    },
    enabled: Boolean(boardId) && (options?.enabled ?? true),
    staleTime: 5_000,
  });
}

/* ─────────────────────────────────────────────────────────────────────────────
   Work Item Loading

   Loads the first page immediately, then hydrates later pages in the
   background so large boards reach first paint much sooner.
   ───────────────────────────────────────────────────────────────────────────── */

/** Must stay ≤ the deployed API's `GET /v1/work-items` `limit` max (see board_api_v2, le=250). */
/** Default list page size; board page uses {@link MAX_ITEMS_PAGE_SIZE} for fewer hydration round-trips. */
const DEFAULT_ITEMS_PAGE_SIZE = 100;
/** Matches `GET /v1/work-items` max `limit` (board_api_v2). */
export const MAX_ITEMS_PAGE_SIZE = 250;

/** Stable empty array to avoid reference changes when data is null */
const EMPTY_ITEMS: WorkItem[] = [];
interface WorkItemsMeta {
  total: number;
  loadedCount: number;
  isPartial: boolean;
  /**
   * When true, `useBoardBootstrap` just seeded items + meta; `useWorkItems`
   * must not treat warm partial cache as an invalidation merge (avoids serial
   * `fetchAllWorkItemsPaged`). Cleared on first `useWorkItems` queryFn run.
   */
  seededFromBootstrap?: boolean;
}

const EMPTY_WORK_ITEMS_META: WorkItemsMeta = {
  total: 0,
  loadedCount: 0,
  isPartial: false,
};

/**
 * Exported for unit tests. True when warm cache should run `fetchAllWorkItemsPaged`
 * (invalidate / resync path), not the bootstrap first-paint path.
 */
export function shouldResyncAllWorkItemPages(prevItemsLength: number, prevMeta: WorkItemsMeta): boolean {
  const warmItems = prevItemsLength > 0;
  const isFreshManualReset =
    prevMeta.total === 0 && !prevMeta.isPartial && prevMeta.loadedCount === 0;
  return (
    warmItems
    && !isFreshManualReset
    && !prevMeta.seededFromBootstrap
    && (prevMeta.isPartial || (prevMeta.total > 0 && !prevMeta.isPartial))
  );
}

interface WorkItemsResult {
  /** All work items for the board */
  data: WorkItem[];
  /** True only during first fetch (shows skeleton) */
  isInitialLoading: boolean;
  /** True while later pages are hydrating in the background */
  isBackgroundHydrating: boolean;
  /** Total number of server-matched items for the current board query */
  total: number;
  /** Number of server-matched items loaded so far */
  loadedCount: number;
  /** Whether the current board query is still partially hydrated */
  isPartial: boolean;
  /** Timestamp of last successful sync */
  lastSyncedAt: Date | null;
  /** True only during user-initiated refetch (not background polls) */
  isRefreshing: boolean;
  /** Error state */
  error: Error | null;
  /** Manual refetch trigger */
  refetch: () => Promise<void>;
  /** Manual fetch of the next page for the current board query */
  loadMore: () => Promise<void>;
}

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
  includeTotal: boolean,
  query?: BoardWorkItemQuery,
): string {
  const qs = new URLSearchParams({
    board_id: boardId,
    limit: String(limit),
    offset: String(offset),
    include_total: includeTotal ? 'true' : 'false',
  });
  if (query?.titleSearch) qs.set('title_search', query.titleSearch);
  query?.itemTypes?.forEach((itemType) => qs.append('item_type', itemType));
  query?.priorities?.forEach((priority) => qs.append('priority', priority));
  if (query?.assigneeId) qs.set('assignee_id', query.assigneeId);
  if (query?.assigneeType) qs.set('assignee_type', query.assigneeType);
  query?.labels?.forEach((label) => qs.append('labels', label));
  if (query?.dueAfter) qs.set('due_after', query.dueAfter);
  if (query?.dueBefore) qs.set('due_before', query.dueBefore);
  if (query?.sortBy && query.sortBy !== 'position') qs.set('sort_by', query.sortBy);
  if (query?.order && query.order !== 'asc') qs.set('order', query.order);
  return qs.toString();
}

function normalizeWorkItemQuery(query?: BoardWorkItemQuery): BoardWorkItemQuery | undefined {
  if (!query) return undefined;

  const normalized: BoardWorkItemQuery = {};

  if (query.titleSearch?.trim()) normalized.titleSearch = query.titleSearch.trim();
  if (query.itemTypes?.length) {
    // Mirror BoardService: when narrowing by type, include research in the fetch/filter key.
    const merged: WorkItemType[] = [...query.itemTypes, 'research'];
    normalized.itemTypes = [...new Set(merged)];
  }
  if (query.priorities?.length) normalized.priorities = [...new Set(query.priorities)];
  if (query.assigneeId) normalized.assigneeId = query.assigneeId;
  if (query.assigneeType) normalized.assigneeType = query.assigneeType;
  if (query.labels?.length) normalized.labels = [...new Set(query.labels.filter(Boolean))];
  if (query.dueAfter) normalized.dueAfter = query.dueAfter;
  if (query.dueBefore) normalized.dueBefore = query.dueBefore;
  if (query.sortBy) normalized.sortBy = query.sortBy;
  if (query.order) normalized.order = query.order;

  return Object.keys(normalized).length > 0 ? normalized : undefined;
}

function hasActiveBoardFilters(query?: BoardWorkItemQuery): boolean {
  return Boolean(
    query?.titleSearch
      || query?.itemTypes?.length
      || query?.priorities?.length
      || query?.assigneeId
      || query?.assigneeType
      || query?.labels?.length
      || query?.dueAfter
      || query?.dueBefore
  );
}

function matchesBoardWorkItemQuery(item: WorkItem, query?: BoardWorkItemQuery): boolean {
  if (!query) return true;

  if (query.titleSearch) {
    const normalizedQuery = query.titleSearch.toLowerCase();
    if (!item.title.toLowerCase().includes(normalizedQuery)) return false;
  }

  if (query.itemTypes?.length && !query.itemTypes.includes(item.item_type)) {
    return false;
  }

  if (query.priorities?.length && !query.priorities.includes(item.priority)) {
    return false;
  }

  if (query.assigneeId) {
    if (query.assigneeId === '__unassigned__') {
      if (item.assignee_id) return false;
    } else if (item.assignee_id !== query.assigneeId) {
      return false;
    }
  }

  if (query.assigneeType && item.assignee_type !== query.assigneeType) {
    return false;
  }

  if (query.labels?.length) {
    const itemLabels = new Set(item.labels ?? []);
    if (!query.labels.some((label) => itemLabels.has(label))) return false;
  }

  if (query.dueAfter) {
    if (!item.due_date || item.due_date < query.dueAfter) return false;
  }

  if (query.dueBefore) {
    if (!item.due_date || item.due_date > query.dueBefore) return false;
  }

  return true;
}

function mergeUniqueWorkItems(items: WorkItem[]): WorkItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.item_id)) return false;
    seen.add(item.item_id);
    return true;
  });
}

interface WorkItemsPageResponse {
  items: WorkItem[];
  total: number;
  hasMore: boolean;
  /** Set for batch / parallel fetches (stable merge / logging). */
  offset?: number;
}

async function fetchWorkItemsPage(
  boardId: string,
  limit: number,
  offset: number,
  includeTotal: boolean,
  query?: BoardWorkItemQuery,
): Promise<WorkItemsPageResponse> {
  for (let attempt = 0; attempt <= WORK_ITEMS_429_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      const response = await apiClient.get<{
        items: WorkItem[];
        total?: number;
        has_more?: boolean;
      }>(`/v1/work-items?${buildWorkItemsQs(boardId, limit, offset, includeTotal, query)}`);
      const pageItems = normalizePageItems(response.items ?? []);
      return {
        items: pageItems,
        total: response.total ?? pageItems.length,
        hasMore: response.has_more === true,
      };
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 429 || attempt === WORK_ITEMS_429_RETRY_DELAYS_MS.length) {
        throw error;
      }
      await sleep(WORK_ITEMS_429_RETRY_DELAYS_MS[attempt]);
    }
  }

  return {
    items: [],
    total: 0,
    hasMore: false,
  };
}

/** One window from POST /v1/work-items/batch-pages (snake_case from API). */
interface WorkItemsBatchPageRaw {
  offset: number;
  items: WorkItem[];
  has_more?: boolean;
}

/**
 * Fetch several board pages in one HTTP request when there are no active board
 * filters (server batch-pages matches unfiltered list_work_items).
 *
 * @param knownTotal When > 0 (e.g. from bootstrap), omit `include_total` on the batch
 *   request so the lead query skips `COUNT(*) OVER()`; per-chunk `hasMore` is derived
 *   as `offset + itemCount < knownTotal`.
 */
async function fetchWorkItemsPagesBatch(
  boardId: string,
  pageSize: number,
  offsets: number[],
  query?: BoardWorkItemQuery,
  knownTotal?: number,
): Promise<WorkItemsPageResponse[]> {
  if (hasActiveBoardFilters(query)) {
    return Promise.all(
      offsets.map((off) =>
        fetchWorkItemsPage(boardId, pageSize, off, false, query).then((page) => ({
          ...page,
          offset: off,
        })),
      ),
    );
  }
  const useKnownTotal = typeof knownTotal === 'number' && knownTotal > 0;
  // When total is unknown, ask the batch handler for COUNT(*) OVER() on the smallest
  // offset so has_more is exact for windows like [100,200,300,400].
  const includeTotal = !useKnownTotal;
  for (let attempt = 0; attempt <= WORK_ITEMS_429_RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      const response = await apiClient.post<{
        pages?: WorkItemsBatchPageRaw[];
        total?: number;
      }>('/v1/work-items/batch-pages', {
        board_id: boardId,
        page_size: pageSize,
        offsets,
        include_total: includeTotal,
      });
      const sharedTotal = useKnownTotal ? knownTotal : (response.total ?? 0);
      return (response.pages ?? []).map((p) => {
        const items = normalizePageItems(p.items ?? []);
        const off = typeof p.offset === 'number' ? p.offset : 0;
        const hasMore =
          useKnownTotal && knownTotal > 0
            ? off + items.length < knownTotal
            : p.has_more === true;
        return {
          items,
          total: sharedTotal,
          hasMore,
          offset: off,
        };
      });
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 429 || attempt === WORK_ITEMS_429_RETRY_DELAYS_MS.length) {
        throw error;
      }
      await sleep(WORK_ITEMS_429_RETRY_DELAYS_MS[attempt]);
    }
  }
  return offsets.map((off) => ({ items: [], total: 0, hasMore: false, offset: off }));
}

function normalizePageItems(items: WorkItem[]): WorkItem[] {
  return items.map((item) => ({
    ...item,
    item_type: normalizeItemType(item.item_type),
    points: item.points ?? item.story_points ?? null,
  }));
}

function workItemHasAssignee(item: WorkItem): boolean {
  return Boolean(item.assignee_id && item.assignee_type);
}

/**
 * Prefer the work item row with the newer `updated_at` when reconciling list cache
 * with freshly fetched pages. Avoids brief UI flicker (e.g. assignee snapping back
 * to unassigned) when list reads hit a lagging read replica right after a mutation
 * applied on the primary.
 *
 * When timestamps tie, prefer the row that still has an assignee pair — optimistic
 * assign patches do not bump `updated_at`, so a stale list row can otherwise win.
 */
function preferNewerWorkItem(previous: WorkItem, incoming: WorkItem): WorkItem {
  const prevTs = Date.parse(previous.updated_at);
  const nextTs = Date.parse(incoming.updated_at);
  if (Number.isFinite(prevTs) && Number.isFinite(nextTs)) {
    if (prevTs > nextTs) return previous;
    if (prevTs < nextTs) return incoming;
  }
  const prevA = workItemHasAssignee(previous);
  const incA = workItemHasAssignee(incoming);
  if (prevA && !incA) return previous;
  if (!prevA && incA) return incoming;
  return incoming;
}

/** If assign response omits assignee fields, merge from the mutation input (assign-only). */
function mergeAssignResponseWithVariables(
  updated: WorkItem,
  variables: { assigneeId: string; assigneeType: 'user' | 'agent' },
): WorkItem {
  if (workItemHasAssignee(updated)) return updated;
  return { ...updated, assignee_id: variables.assigneeId, assignee_type: variables.assigneeType };
}

/** Per-item merge following {@link preferNewerWorkItem}; order follows `incoming`. */
function reconcileVisibleWorkItems(
  previous: WorkItem[] | undefined,
  incoming: WorkItem[],
): WorkItem[] {
  const prevById = new Map((previous ?? []).map((item) => [item.item_id, item]));
  return incoming.map((inc) => {
    const prev = prevById.get(inc.item_id);
    if (!prev) return inc;
    return preferNewerWorkItem(prev, inc);
  });
}

export function useBoardBootstrap(
  boardId?: string,
  options?: { enabled?: boolean; pageSize?: number },
) {
  const queryClient = useQueryClient();
  const pageSize = Math.min(options?.pageSize ?? DEFAULT_ITEMS_PAGE_SIZE, MAX_ITEMS_PAGE_SIZE);

  return useQuery({
    queryKey: boardKeys.bootstrap(boardId),
    queryFn: async (): Promise<BoardBootstrapResponse | null> => {
      if (!boardId) return null;
      const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
      const response = await apiClient.get<BoardBootstrapResponse>(
        `/v1/boards/${boardId}/bootstrap?limit=${pageSize}&offset=0&include_rollups=false`
      );
      const items = normalizePageItems(response.items ?? []);
      const payload: BoardBootstrapResponse = {
        ...response,
        items,
        rollups: response.rollups ?? [],
      };

      const elapsedMs =
        typeof performance !== 'undefined' ? Math.round(performance.now() - t0) : 0;
      boardLoadBench('bootstrap_complete', {
        board_id: boardId,
        duration_ms: elapsedMs,
        page_size: pageSize,
        item_count: items.length,
        total: payload.total,
        has_more: payload.has_more,
        rollup_count: payload.rollups?.length ?? 0,
      });
      boardLoadBenchMark('bootstrap_complete', {
        board_id: boardId,
        duration_ms: elapsedMs,
        item_count: items.length,
        total: payload.total,
      });

      queryClient.setQueryData(boardKeys.board(boardId), payload.board);
      queryClient.setQueryData<WorkItem[]>(boardKeys.items(boardId, undefined), items);
      queryClient.setQueryData<WorkItemsMeta>(boardKeys.itemsMeta(boardId, undefined), {
        total: payload.total,
        loadedCount: items.length,
        isPartial: payload.has_more && items.length < payload.total,
        seededFromBootstrap: true,
      });
      // Never seed rollups as []: that satisfies useBoardAllRollups with staleTime and
      // suppresses GET /progress-rollups (goal/feature chips lose progress coloring).
      queryClient.removeQueries({ queryKey: [...boardKeys.all, 'rollups', boardId] });
      return payload;
    },
    enabled: Boolean(boardId) && (options?.enabled ?? true),
    staleTime: 5_000,
  });
}

const WORK_ITEMS_429_RETRY_DELAYS_MS = [250, 750, 1500] as const;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWorkItemsBatch(itemIds: string[]): Promise<WorkItem[]> {
  if (itemIds.length === 0) return EMPTY_ITEMS;

  const batches: WorkItem[] = [];
  for (let offset = 0; offset < itemIds.length; offset += 100) {
    const chunk = itemIds.slice(offset, offset + 100);
    const response = await apiClient.post<{ items?: WorkItem[] }>(
      '/v1/work-items/batch',
      { item_ids: chunk },
    );
    batches.push(...normalizePageItems(response.items ?? []));
  }
  return batches;
}

async function hydrateAncestorItems(
  serverItems: WorkItem[],
  query?: BoardWorkItemQuery,
): Promise<WorkItem[]> {
  if (!hasActiveBoardFilters(query)) {
    return mergeUniqueWorkItems(serverItems);
  }

  let hydrated = mergeUniqueWorkItems(serverItems);

  while (true) {
    const existingIds = new Set(hydrated.map((item) => item.item_id));
    const missingParentIds = [...new Set(
      hydrated
        .map((item) => item.parent_id)
        .filter((parentId): parentId is string => typeof parentId === 'string' && parentId.length > 0)
        .filter((parentId) => !existingIds.has(parentId))
    )];

    if (missingParentIds.length === 0) {
      return hydrated;
    }

    const parents = await fetchWorkItemsBatch(missingParentIds);
    if (parents.length === 0) {
      return hydrated;
    }

    hydrated = mergeUniqueWorkItems([...hydrated, ...parents]);
  }
}

async function buildVisibleWorkItems(
  serverItems: WorkItem[],
  query?: BoardWorkItemQuery,
): Promise<WorkItem[]> {
  return hydrateAncestorItems(mergeUniqueWorkItems(serverItems), query);
}

/** Walk every offset page until the server reports completion (refetch / invalidation path). */
async function fetchAllWorkItemsPaged(
  boardId: string,
  pageSize: number,
  query?: BoardWorkItemQuery,
): Promise<{ serverMerged: WorkItem[]; total: number }> {
  const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
  let offset = 0;
  let serverMerged: WorkItem[] = [];
  let total = 0;
  let pageFetches = 0;
  for (let guard = 0; guard < 500; guard += 1) {
    const includeTotal = guard === 0;
    const page = await fetchWorkItemsPage(boardId, pageSize, offset, includeTotal, query);
    pageFetches += 1;
    if (includeTotal || total === 0) {
      total = page.total;
    }
    serverMerged = mergeUniqueWorkItems([...serverMerged, ...page.items]);
    if (!page.hasMore || serverMerged.length >= total || page.items.length === 0) {
      break;
    }
    offset += page.items.length;
  }
  const elapsedMs = typeof performance !== 'undefined' ? Math.round(performance.now() - t0) : 0;
  boardLoadBench('fetch_all_work_items_paged', {
    board_id: boardId,
    duration_ms: elapsedMs,
    page_fetches: pageFetches,
    item_count: serverMerged.length,
    total,
  });
  boardLoadBenchMark('fetch_all_pages', {
    board_id: boardId,
    duration_ms: elapsedMs,
    page_fetches: pageFetches,
  });
  return { serverMerged, total };
}

/** Matches batch-pages fan-out in `useWorkItems` background hydration. */
const BOARD_HYDRATION_PARALLELISM = 8;

type HydrationWaveState = {
  serverMerged: WorkItem[];
  total: number;
  isPartial: boolean;
  /** Next server `offset` for GET / batch-pages (matches `WorkItemsMeta.loadedCount` for normal boards). */
  nextOffset: number;
};

function readBoardHydrateSleepMs(): number {
  try {
    const raw = typeof window !== 'undefined' ? window.localStorage?.getItem('amprealize.hydrateSleepMs') : null;
    if (raw === null || raw === undefined) return 0;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : 0;
  } catch {
    return 0;
  }
}

/**
 * One hydration wave: either one serial page or up to BOARD_HYDRATION_PARALLELISM
 * parallel windows (batch or parallel GET when filtered).
 */
async function runSingleHydrationWave(
  boardId: string,
  pageSize: number,
  normalizedQuery: BoardWorkItemQuery | undefined,
  state: HydrationWaveState,
): Promise<HydrationWaveState> {
  if (!state.isPartial) return state;

  const offsets: number[] = [];
  if (state.total > 0) {
    let cursor = state.nextOffset;
    for (let i = 0; i < BOARD_HYDRATION_PARALLELISM && cursor < state.total; i += 1) {
      offsets.push(cursor);
      cursor += pageSize;
    }
  }

  if (offsets.length <= 1) {
    const nextPage = await fetchWorkItemsPage(boardId, pageSize, state.nextOffset, false, normalizedQuery);
    const mergedServerItems = mergeUniqueWorkItems([...state.serverMerged, ...nextPage.items]);
    const total = state.total > 0 ? state.total : nextPage.total;
    const isPartial = nextPage.hasMore && mergedServerItems.length < total;
    return { serverMerged: mergedServerItems, total, isPartial, nextOffset: mergedServerItems.length };
  }

  const pages = await fetchWorkItemsPagesBatch(
    boardId,
    pageSize,
    offsets,
    normalizedQuery,
    state.total > 0 ? state.total : undefined,
  );

  const newServerItems = pages.flatMap((p) => p.items);
  const mergedServerItems = mergeUniqueWorkItems([...state.serverMerged, ...newServerItems]);
  const resolvedTotal = state.total > 0 ? state.total : (pages[pages.length - 1]?.total ?? 0);
  const anyPageHasMore = pages.some((p) => p.hasMore);
  const isPartial = anyPageHasMore && mergedServerItems.length < resolvedTotal;

  return { serverMerged: mergedServerItems, total: resolvedTotal, isPartial, nextOffset: mergedServerItems.length };
}

/** Full in-memory hydration (no React Query writes); used for optional `progressive: false`. */
async function hydrateAllRemainingWorkItemsInMemory(
  boardId: string,
  pageSize: number,
  normalizedQuery: BoardWorkItemQuery | undefined,
  initial: HydrationWaveState,
): Promise<HydrationWaveState> {
  let state = initial;
  while (state.isPartial) {
    state = await runSingleHydrationWave(boardId, pageSize, normalizedQuery, state);
    const hydrateSleepMs = readBoardHydrateSleepMs();
    if (hydrateSleepMs > 0) await sleep(hydrateSleepMs);
  }
  return state;
}

/**
 * `useWorkItems` `placeholderData` while the items `queryKey` changes (filters / sort).
 * Regression-tested (GuideAI-1256); do not swap without re-validating progressive hydration.
 */
export const WORK_ITEMS_LIST_PLACEHOLDER_DATA = keepPreviousData;

export function useWorkItems(
  boardId?: string,
  options?: {
    query?: BoardWorkItemQuery;
    pageSize?: number;
    progressive?: boolean;
    enabled?: boolean;
  },
): WorkItemsResult {
  const isTabVisible = useDocumentVisible();
  const queryClient = useQueryClient();
  const normalizedQuery = React.useMemo(
    () => normalizeWorkItemQuery(options?.query),
    [options?.query],
  );
  const pageSize = Math.min(options?.pageSize ?? DEFAULT_ITEMS_PAGE_SIZE, MAX_ITEMS_PAGE_SIZE);
  const progressive = options?.progressive ?? true;
  const enabled = options?.enabled ?? true;
  const itemsKey = React.useMemo(() => boardKeys.items(boardId, normalizedQuery), [boardId, normalizedQuery]);
  const itemsMetaKey = React.useMemo(() => boardKeys.itemsMeta(boardId, normalizedQuery), [boardId, normalizedQuery]);

  // Track manual (user-initiated) refreshes separately from background polls
  const isManualRefreshRef = React.useRef(false);
  const [isManualRefreshing, setIsManualRefreshing] = React.useState(false);
  const [isBackgroundHydrating, setIsBackgroundHydrating] = React.useState(false);
  const backgroundHydrationRunRef = React.useRef(0);

  // Suppress background polling while a board mutation (move/reorder) is
  // in-flight.  The poll can fire right after a drop if its timer was already
  // partway through, replacing the optimistic cache and causing a visible
  // column stutter.  useIsMutating returns > 0 while any matching mutation
  // is pending.
  const activeBoardMutations = useIsMutating({
    mutationKey: ['board-item-mutate', boardId],
  });
  const hydrationAllowed = isTabVisible && activeBoardMutations === 0;

  const itemsMetaQuery = useQuery({
    queryKey: itemsMetaKey,
    queryFn: async (): Promise<WorkItemsMeta> => EMPTY_WORK_ITEMS_META,
    enabled: false,
    initialData: EMPTY_WORK_ITEMS_META,
  });

  const query = useQuery({
    queryKey: itemsKey,
    queryFn: async (): Promise<WorkItem[]> => {
      if (!boardId) return EMPTY_ITEMS;

      const queryT0 = typeof performance !== 'undefined' ? performance.now() : 0;
      const prevItems = queryClient.getQueryData<WorkItem[]>(itemsKey) ?? EMPTY_ITEMS;
      const prevMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;

      // Bootstrap already fetched the first page; avoid duplicate GET and
      // skip shouldResyncAllPages (warm partial would otherwise serial-fetch every page).
      if (prevMeta.seededFromBootstrap && prevItems.length > 0) {
        const baseServerItems = hasActiveBoardFilters(normalizedQuery)
          ? prevItems.filter((item) => matchesBoardWorkItemQuery(item, normalizedQuery))
          : [...prevItems];

        if (!progressive && prevMeta.isPartial) {
          const tAtomic0 = typeof performance !== 'undefined' ? performance.now() : 0;
          const finalState = await hydrateAllRemainingWorkItemsInMemory(boardId, pageSize, normalizedQuery, {
            serverMerged: mergeUniqueWorkItems(baseServerItems),
            total: prevMeta.total,
            isPartial: prevMeta.isPartial,
            nextOffset: prevMeta.loadedCount,
          });
          const visibleItems = await buildVisibleWorkItems(finalState.serverMerged, normalizedQuery);
          queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
            total: finalState.total,
            loadedCount: finalState.serverMerged.length,
            isPartial: false,
            seededFromBootstrap: false,
          });
          const totalMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tAtomic0) : 0;
          boardLoadBench('work_items_query_bootstrap_atomic', {
            board_id: boardId,
            path: 'bootstrap_atomic',
            duration_ms: totalMs,
            item_count: finalState.serverMerged.length,
            total: finalState.total,
          });
          boardLoadBenchMark('work_items_bootstrap_atomic', {
            board_id: boardId,
            duration_ms: totalMs,
            item_count: finalState.serverMerged.length,
          });
          return reconcileVisibleWorkItems(prevItems, visibleItems);
        }

        const tBuild0 = typeof performance !== 'undefined' ? performance.now() : 0;
        const visibleItems = await buildVisibleWorkItems(prevItems, normalizedQuery);
        const buildMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tBuild0) : 0;
        queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
          total: prevMeta.total,
          loadedCount: prevMeta.loadedCount,
          isPartial: prevMeta.isPartial,
        });
        const totalMs = typeof performance !== 'undefined' ? Math.round(performance.now() - queryT0) : 0;
        boardLoadBench('work_items_query_bootstrap_seed', {
          board_id: boardId,
          path: 'bootstrap_seed',
          duration_ms: totalMs,
          build_visible_ms: buildMs,
          loaded: prevMeta.loadedCount,
          total: prevMeta.total,
          is_partial: prevMeta.isPartial,
        });
        boardLoadBenchMark('work_items_bootstrap_seed', {
          board_id: boardId,
          duration_ms: totalMs,
          loaded: prevMeta.loadedCount,
        });
        return visibleItems;
      }

      const shouldResyncAllPages = shouldResyncAllWorkItemPages(prevItems.length, prevMeta);

      if (shouldResyncAllPages) {
        const tFetch0 = typeof performance !== 'undefined' ? performance.now() : 0;
        const { serverMerged, total } = await fetchAllWorkItemsPaged(boardId, pageSize, normalizedQuery);
        const fetchMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tFetch0) : 0;
        const tBuild0 = typeof performance !== 'undefined' ? performance.now() : 0;
        const visibleItems = await buildVisibleWorkItems(serverMerged, normalizedQuery);
        const buildMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tBuild0) : 0;
        queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
          total,
          loadedCount: serverMerged.length,
          isPartial: false,
        });
        const totalMs = typeof performance !== 'undefined' ? Math.round(performance.now() - queryT0) : 0;
        boardLoadBench('work_items_query_full_resync', {
          board_id: boardId,
          path: 'full_resync',
          duration_ms: totalMs,
          fetch_all_pages_ms: fetchMs,
          build_visible_ms: buildMs,
          item_count: serverMerged.length,
          total,
        });
        boardLoadBenchMark('work_items_full_resync', {
          board_id: boardId,
          duration_ms: totalMs,
          item_count: serverMerged.length,
        });
        return reconcileVisibleWorkItems(prevItems, visibleItems);
      }

      const tFirst0 = typeof performance !== 'undefined' ? performance.now() : 0;
      const firstPage = await fetchWorkItemsPage(boardId, pageSize, 0, true, normalizedQuery);
      const firstFetchMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tFirst0) : 0;
      const tBuild0 = typeof performance !== 'undefined' ? performance.now() : 0;
      const visibleFirst = await buildVisibleWorkItems(firstPage.items, normalizedQuery);
      const buildMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tBuild0) : 0;
      queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
        total: firstPage.total,
        loadedCount: firstPage.items.length,
        isPartial: firstPage.hasMore && firstPage.items.length < firstPage.total,
      });
      const totalMs = typeof performance !== 'undefined' ? Math.round(performance.now() - queryT0) : 0;
      boardLoadBench('work_items_query_first_page', {
        board_id: boardId,
        path: 'first_page',
        duration_ms: totalMs,
        first_page_fetch_ms: firstFetchMs,
        build_visible_ms: buildMs,
        item_count: firstPage.items.length,
        total: firstPage.total,
        has_more: firstPage.hasMore,
      });
      boardLoadBenchMark('work_items_first_page', {
        board_id: boardId,
        duration_ms: totalMs,
        item_count: firstPage.items.length,
      });

      if (
        !progressive
        && firstPage.hasMore
        && firstPage.items.length < firstPage.total
      ) {
        const tAtomic0 = typeof performance !== 'undefined' ? performance.now() : 0;
        const finalState = await hydrateAllRemainingWorkItemsInMemory(boardId, pageSize, normalizedQuery, {
          serverMerged: mergeUniqueWorkItems(firstPage.items),
          total: firstPage.total,
          isPartial: true,
          nextOffset: firstPage.items.length,
        });
        const visibleAll = await buildVisibleWorkItems(finalState.serverMerged, normalizedQuery);
        queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
          total: finalState.total,
          loadedCount: finalState.serverMerged.length,
          isPartial: false,
        });
        const atomicMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tAtomic0) : 0;
        boardLoadBench('work_items_query_first_page_atomic', {
          board_id: boardId,
          path: 'first_page_atomic',
          duration_ms: atomicMs,
          item_count: finalState.serverMerged.length,
          total: finalState.total,
        });
        boardLoadBenchMark('work_items_first_page_atomic', {
          board_id: boardId,
          duration_ms: atomicMs,
          item_count: finalState.serverMerged.length,
        });
        return reconcileVisibleWorkItems(prevItems, visibleAll);
      }

      return reconcileVisibleWorkItems(prevItems, visibleFirst);
    },
    enabled: Boolean(boardId) && enabled,
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    // Filter / sort changes use a new `queryKey` (`boardKeys.items` embeds `normalizedQuery`).
    // `keepPreviousData` shows the *previous key's* cached list as placeholder while the new
    // key fetches, avoiding an empty board flash. It does not bypass `queryFn` — bootstrap
    // seeding, meta (`itemsMetaKey`), and progressive hydration still run per key; do not remove
    // without retesting filter transitions and `useWorkItems` background hydration (GuideAI-1256).
    placeholderData: WORK_ITEMS_LIST_PLACEHOLDER_DATA,
  });

  const appendNextPage = React.useCallback(async () => {
    if (!boardId) return;

    const currentMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;
    if (!currentMeta.isPartial) return;

    const currentItems = queryClient.getQueryData<WorkItem[]>(itemsKey) ?? EMPTY_ITEMS;
    const currentServerItems = hasActiveBoardFilters(normalizedQuery)
      ? currentItems.filter((item) => matchesBoardWorkItemQuery(item, normalizedQuery))
      : currentItems;

    const t0 = typeof performance !== 'undefined' ? performance.now() : 0;
    const nextPage = await fetchWorkItemsPage(boardId, pageSize, currentMeta.loadedCount, false, normalizedQuery);
    const fetchMs = typeof performance !== 'undefined' ? Math.round(performance.now() - t0) : 0;
    const tBuild = typeof performance !== 'undefined' ? performance.now() : 0;
    const mergedServerItems = mergeUniqueWorkItems([...currentServerItems, ...nextPage.items]);
    const visibleItems = await buildVisibleWorkItems(mergedServerItems, normalizedQuery);
    const buildMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tBuild) : 0;

    React.startTransition(() => {
      queryClient.setQueryData<WorkItem[]>(itemsKey, (current) =>
        reconcileVisibleWorkItems(current ?? EMPTY_ITEMS, visibleItems),
      );
      queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
        total: currentMeta.total > 0 ? currentMeta.total : nextPage.total,
        loadedCount: mergedServerItems.length,
        isPartial: nextPage.hasMore
          && mergedServerItems.length < (currentMeta.total > 0 ? currentMeta.total : nextPage.total),
      });
    });
    boardLoadBench('hydrate_append_page', {
      board_id: boardId,
      path: 'serial_single',
      offset: currentMeta.loadedCount,
      fetch_ms: fetchMs,
      build_visible_ms: buildMs,
      duration_ms: typeof performance !== 'undefined' ? Math.round(performance.now() - t0) : 0,
      page_item_count: nextPage.items.length,
      loaded_after: mergedServerItems.length,
      total: currentMeta.total > 0 ? currentMeta.total : nextPage.total,
      still_partial: nextPage.hasMore
        && mergedServerItems.length < (currentMeta.total > 0 ? currentMeta.total : nextPage.total),
    });
  }, [boardId, itemsKey, itemsMetaKey, normalizedQuery, pageSize, queryClient]);

  React.useEffect(() => {
    if (!progressive || !boardId) return;
    // Read fetch-in-flight and data presence straight from the cache so
    // we don't have to put `query.data` / `query.isFetching` in the dep
    // array. If they were deps, every wave's `setQueryData` would retrigger
    // this effect and spawn a second concurrent hydration loop.
    const itemsState = queryClient.getQueryState<WorkItem[]>(itemsKey);
    const hasData = (itemsState?.data?.length ?? 0) > 0;
    const isFetching = itemsState?.fetchStatus === 'fetching';
    if (!hasData || isFetching) return;
    if (!hydrationAllowed) return;
    if (!(itemsMetaQuery.data?.isPartial ?? false)) {
      setIsBackgroundHydrating(false);
      return;
    }

    let cancelled = false;
    const runId = backgroundHydrationRunRef.current + 1;
    backgroundHydrationRunRef.current = runId;
    setIsBackgroundHydrating(true);

    void (async () => {
      const loopT0 = typeof performance !== 'undefined' ? performance.now() : 0;
      let hydrateWave = 0;
      boardLoadBench('hydrate_loop_start', { board_id: boardId, page_size: pageSize });
      boardLoadBenchMark('hydrate_loop_start', { board_id: boardId });

      try {
        while (!cancelled) {
          hydrateWave += 1;
          const waveT0 = typeof performance !== 'undefined' ? performance.now() : 0;
          const currentMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;
          if (!currentMeta.isPartial) break;

          if (cancelled) break;

          const currentItems = queryClient.getQueryData<WorkItem[]>(itemsKey) ?? EMPTY_ITEMS;
          const currentServerItems = hasActiveBoardFilters(normalizedQuery)
            ? currentItems.filter((item) => matchesBoardWorkItemQuery(item, normalizedQuery))
            : currentItems;

          const waveOffsets: number[] = [];
          if (currentMeta.total > 0) {
            let cursor = currentMeta.loadedCount;
            for (let i = 0; i < BOARD_HYDRATION_PARALLELISM && cursor < currentMeta.total; i += 1) {
              waveOffsets.push(cursor);
              cursor += pageSize;
            }
          }
          const path = waveOffsets.length <= 1 ? 'serial' : hasActiveBoardFilters(normalizedQuery) ? 'parallel_get' : 'batch_pages';
          const transport = waveOffsets.length <= 1 ? 'get' : hasActiveBoardFilters(normalizedQuery) ? 'parallel_get' : 'batch_post';

          const state: HydrationWaveState = {
            serverMerged: mergeUniqueWorkItems(currentServerItems),
            total: currentMeta.total,
            isPartial: currentMeta.isPartial,
            nextOffset: currentMeta.loadedCount,
          };

          const tFetch = typeof performance !== 'undefined' ? performance.now() : 0;
          const nextState = await runSingleHydrationWave(boardId, pageSize, normalizedQuery, state);
          const fetchMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tFetch) : 0;
          if (cancelled) break;

          const tBuild = typeof performance !== 'undefined' ? performance.now() : 0;
          const visibleItems = await buildVisibleWorkItems(nextState.serverMerged, normalizedQuery);
          const buildMs = typeof performance !== 'undefined' ? Math.round(performance.now() - tBuild) : 0;
          if (cancelled) break;

          React.startTransition(() => {
            queryClient.setQueryData<WorkItem[]>(itemsKey, (current) =>
              reconcileVisibleWorkItems(current ?? EMPTY_ITEMS, visibleItems),
            );
            queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
              total: nextState.total,
              loadedCount: nextState.serverMerged.length,
              isPartial: nextState.isPartial,
            });
          });

          const waveMs = typeof performance !== 'undefined' ? Math.round(performance.now() - waveT0) : 0;
          const newItemsThisWave = nextState.serverMerged.length - state.serverMerged.length;
          boardLoadBench('hydrate_wave', {
            board_id: boardId,
            wave: hydrateWave,
            path,
            transport,
            parallel_offsets: waveOffsets.length,
            offsets: waveOffsets,
            duration_ms: waveMs,
            fetch_parallel_ms: fetchMs,
            build_visible_ms: buildMs,
            new_items_this_wave: newItemsThisWave,
            loaded_after: nextState.serverMerged.length,
            total: nextState.total,
            is_partial: nextState.isPartial,
          });
          if (path === 'serial') {
            boardLoadBenchMark('hydrate_wave_serial', { board_id: boardId, wave: hydrateWave, duration_ms: waveMs });
          } else {
            boardLoadBenchMark('hydrate_wave_parallel', {
              board_id: boardId,
              wave: hydrateWave,
              duration_ms: waveMs,
              parallel_requests: waveOffsets.length,
            });
          }

          const hydrateSleepMs = readBoardHydrateSleepMs();
          if (hydrateSleepMs > 0) await sleep(hydrateSleepMs);
        }
      } finally {
        if (isBoardLoadBenchEnabled()) {
          const loopMs = typeof performance !== 'undefined' ? Math.round(performance.now() - loopT0) : 0;
          const finalMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;
          boardLoadBench('hydrate_loop_done', {
            board_id: boardId,
            cancelled,
            waves: hydrateWave,
            duration_ms: loopMs,
            loaded: finalMeta.loadedCount,
            total: finalMeta.total,
            is_partial: finalMeta.isPartial,
          });
          boardLoadBenchMark('hydrate_loop_done', { board_id: boardId, duration_ms: loopMs, waves: hydrateWave });
        }
        if (!cancelled && backgroundHydrationRunRef.current === runId) {
          setIsBackgroundHydrating(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      if (backgroundHydrationRunRef.current === runId) {
        setIsBackgroundHydrating(false);
      }
    };
  }, [
    // Intentionally EXCLUDE `query.data` from deps. Every hydration wave
    // calls `queryClient.setQueryData(itemsKey, ...)`, which updates
    // `query.data` to a new reference. If `query.data` were a dep, every
    // wave would retrigger this effect, spawning a second async hydration
    // loop that reads the same `loadedCount` and re-fires the SAME page
    // offsets in parallel with the first loop — we observed this in the
    // gateway logs (each of offsets 500-1000 issued twice). The effect
    // still triggers correctly on the first page landing because
    // `itemsMetaQuery.data?.isPartial` transitions false→true in the same
    // commit that `query.data` first appears. Similarly drop
    // `query.isFetching`: manual refetch resets itemsMeta to
    // EMPTY_WORK_ITEMS_META (isPartial=false), and first-page completion
    // flips isPartial back to true — the isPartial toggle is the real
    // trigger we care about, not fetch-boundary churn.
    boardId,
    itemsKey,
    itemsMetaKey,
    itemsMetaQuery.data?.isPartial,
    hydrationAllowed,
    normalizedQuery,
    pageSize,
    progressive,
    queryClient,
  ]);

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
    setIsBackgroundHydrating(false);
    queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, EMPTY_WORK_ITEMS_META);
    await query.refetch();
  }, [itemsMetaKey, query, queryClient]);

  const loadMore = React.useCallback(async () => {
    setIsBackgroundHydrating(true);
    try {
      await appendNextPage();
    } finally {
      setIsBackgroundHydrating(false);
    }
  }, [appendNextPage]);

  const meta = itemsMetaQuery.data ?? EMPTY_WORK_ITEMS_META;

  return {
    data: query.data ?? EMPTY_ITEMS,
    isInitialLoading: query.isLoading && !query.data,
    isBackgroundHydrating,
    total: meta.total,
    loadedCount: meta.loadedCount,
    isPartial: meta.isPartial,
    lastSyncedAt,
    isRefreshing: isManualRefreshing,
    error: query.error,
    refetch,
    loadMore,
  };
}

/**
 * Fetch all rollups for a board in a single request (no item_type filter),
 * then derive per-type subsets client-side. This replaces two separate
 * network calls (goals + features) with one.
 */
export function useBoardAllRollups(
  boardId?: string,
  options?: { includeIncompleteDescendants?: boolean; enabled?: boolean; staleTimeMs?: number }
) {
  const includeIncompleteDescendants = options?.includeIncompleteDescendants ?? false;
  const enabled = options?.enabled ?? true;
  const staleTimeMs = options?.staleTimeMs ?? 30_000;

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
    enabled: Boolean(boardId) && enabled,
    staleTime: staleTimeMs,
  });

  return query;
}

/**
 * Derive rollups for a specific item type from the combined query.
 * Returns the same shape as the old per-type hook so callers don't change.
 */
export function useBoardProgressRollups(
  boardId?: string,
  options?: { itemType?: WorkItemType; includeIncompleteDescendants?: boolean; enabled?: boolean; staleTimeMs?: number }
) {
  const itemType = options?.itemType;
  const includeIncompleteDescendants = options?.includeIncompleteDescendants ?? false;
  const enabled = options?.enabled ?? true;
  const staleTimeMs = options?.staleTimeMs ?? 30_000;

  const allRollups = useBoardAllRollups(boardId, {
    includeIncompleteDescendants,
    enabled,
    staleTimeMs,
  });

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
        metadata: payload.metadata ?? {},
        labels: [],
        acceptance_criteria: [],
        checklist: [],
      });
      return response.item;
    },
    onMutate: async (payload) => {
      await cancelAllBoardItemQueriesForBoard(queryClient, payload.board_id);

      const previousEntries = queryClient.getQueriesData<WorkItem[]>({
        predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, payload.board_id),
      });
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

      const targetColumnId = payload.column_id ?? null;
      const bumpColumnPositions = (list: WorkItem[]): WorkItem[] => {
        if (!targetColumnId) return list;
        return list.map((item) =>
          item.column_id === targetColumnId
            ? { ...item, position: (item.position ?? 0) + 1 }
            : item,
        );
      };

      const itemCaches = queryClient.getQueriesData<WorkItem[]>({
        predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, payload.board_id),
      });
      for (const [key] of itemCaches) {
        queryClient.setQueryData<WorkItem[]>(key, (old) => {
          const list = old ?? [];
          const subq = boardWorkItemQueryFromKey(key as readonly unknown[]);
          const bumped = bumpColumnPositions(list);
          if (subq && !matchesBoardWorkItemQuery(optimistic, subq)) {
            return bumped;
          }
          return [optimistic, ...bumped];
        });
      }
      return { previousEntries, optimisticId };
    },
    onError: async (error, payload, context) => {
      const entries = (context as { previousEntries?: [readonly unknown[], WorkItem[]][] } | undefined)?.previousEntries;
      entries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
      await razeLog('ERROR', 'Work item create failed', {
        project_id: payload.project_id,
        board_id: payload.board_id,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (created, payload, context) => {
      const itemCachesAfterCreate = queryClient.getQueriesData<WorkItem[]>({
        predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, payload.board_id),
      });
      for (const [key] of itemCachesAfterCreate) {
        queryClient.setQueryData<WorkItem[]>(key, (old) => {
          const list = old ?? [];
          const subq = boardWorkItemQueryFromKey(key as readonly unknown[]);
          if (subq && !matchesBoardWorkItemQuery(created, subq)) {
            return list.filter((i) => i.item_id !== context?.optimisticId);
          }
          const replaced = list.map((i) => (i.item_id === context?.optimisticId ? created : i));
          return replaced.some((i) => i.item_id === created.item_id) ? replaced : [created, ...replaced];
        });
      }
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
      await cancelAllBoardItemQueriesForBoard(queryClient, boardId);
      await queryClient.cancelQueries({ queryKey: boardKeys.item(input.itemId) });

      const previousEntries = queryClient.getQueriesData<WorkItem[]>({
        predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
      });
      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;

      const applyMove = (list: WorkItem[]): WorkItem[] => {
        const targetCol = input.move.column_id;
        const targetPos = input.move.position;
        const movedId = input.itemId;
        const movedItem = list.find((i) => i.item_id === movedId);
        if (!movedItem) return list;
        const sourceCol = movedItem.column_id;
        const sourcePos = movedItem.position ?? 0;
        const sameColumn = sourceCol === targetCol;

        return list.map((item) => {
          if (item.item_id === movedId) {
            return { ...item, column_id: targetCol, position: targetPos };
          }

          let pos = item.position ?? 0;

          if (sameColumn && item.column_id === sourceCol && pos > sourcePos) {
            pos -= 1;
          }

          if (item.column_id === targetCol && pos >= targetPos) {
            pos += 1;
          }

          if (pos !== (item.position ?? 0)) {
            return { ...item, position: pos };
          }
          return item;
        });
      };

      queryClient.setQueriesData<WorkItem[]>(
        { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
        (current) => {
          const list = current ?? [];
          if (!list.some((i) => i.item_id === input.itemId)) return list;
          return applyMove(list);
        },
      );

      if (previousItem) {
        queryClient.setQueryData<WorkItem>(boardKeys.item(input.itemId), {
          ...previousItem,
          column_id: input.move.column_id,
          position: input.move.position,
        });
      }

      return { previousEntries, previousItem };
    },
    onError: async (error, input, context) => {
      if (!boardId) return;
      const ctx = context as { previousEntries?: [readonly unknown[], WorkItem[]][]; previousItem?: WorkItem | null } | undefined;
      ctx?.previousEntries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
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
      await cancelAllBoardItemQueriesForBoard(queryClient, boardId);

      const previousEntries = queryClient.getQueriesData<WorkItem[]>({
        predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
      });

      const positionMap = new Map<string, number>();
      input.orderedItemIds.forEach((id, idx) => positionMap.set(id, idx));

      queryClient.setQueriesData<WorkItem[]>(
        { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
        (current) => {
          const list = current ?? [];
          if (!input.orderedItemIds.some((id) => list.some((i) => i.item_id === id))) return list;
          return list.map((item) => {
            const newPos = positionMap.get(item.item_id);
            if (newPos !== undefined && item.position !== newPos) {
              return { ...item, position: newPos };
            }
            return item;
          });
        },
      );

      return { previousEntries };
    },
    onError: async (_error, _input, context) => {
      if (!boardId) return;
      const ctx = context as { previousEntries?: [readonly unknown[], WorkItem[]][] } | undefined;
      ctx?.previousEntries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
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
        await cancelAllBoardItemQueriesForBoard(queryClient, boardId);
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItemEntries = boardId
        ? queryClient.getQueriesData<WorkItem[]>({
            predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
          })
        : [];

      const applyPatch = (item: WorkItem): WorkItem => ({ ...item, ...input.patch });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            if (!list.some((item) => item.item_id === input.itemId)) return list;
            return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
          },
        );
      }

      return { previousItem, previousItemEntries };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      const ctx = context as { previousItemEntries?: [readonly unknown[], WorkItem[]][] } | undefined;
      ctx?.previousItemEntries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
      await razeLog('ERROR', 'Work item update failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            if (!list.some((item) => item.item_id === updated.item_id)) return list;
            return list.map((item) => (item.item_id === updated.item_id ? updated : item));
          },
        );
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
        await cancelAllBoardItemQueriesForBoard(queryClient, boardId);
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousEntries = boardId
        ? queryClient.getQueriesData<WorkItem[]>({
            predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
          })
        : [];

      const mergedForCascade = mergeUniqueWorkItems(
        previousEntries.flatMap(([, data]) => data ?? []),
      );

      const idsToRemove = new Set<string>([input.itemId]);
      if (input.cascade !== false && mergedForCascade.length > 0) {
        let added = true;
        while (added) {
          added = false;
          mergedForCascade.forEach((item) => {
            if (item.parent_id && idsToRemove.has(item.parent_id) && !idsToRemove.has(item.item_id)) {
              idsToRemove.add(item.item_id);
              added = true;
            }
          });
        }
      }

      queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), null);
      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            return list.filter((item) => !idsToRemove.has(item.item_id));
          },
        );
      }

      return { previousItem, previousEntries };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(
        boardKeys.item(input.itemId),
        (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null
      );
      const ctx = context as { previousEntries?: [readonly unknown[], WorkItem[]][] } | undefined;
      ctx?.previousEntries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
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
        await cancelAllBoardItemQueriesForBoard(queryClient, boardId);
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItemEntries = boardId
        ? queryClient.getQueriesData<WorkItem[]>({
            predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
          })
        : [];

      const applyPatch = (item: WorkItem): WorkItem => ({
        ...item,
        assignee_id: input.assigneeId,
        assignee_type: input.assigneeType,
      });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            if (!list.some((item) => item.item_id === input.itemId)) return list;
            return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
          },
        );
      }

      return { previousItem, previousItemEntries };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      const ctx = context as { previousItemEntries?: [readonly unknown[], WorkItem[]][] } | undefined;
      ctx?.previousItemEntries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
      await razeLog('ERROR', 'Work item assign failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated, variables) => {
      const merged = mergeAssignResponseWithVariables(updated, variables);
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(merged.item_id), merged);
      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            if (!list.some((item) => item.item_id === merged.item_id)) return list;
            return list.map((item) => (item.item_id === merged.item_id ? merged : item));
          },
        );
      }
      await razeLog('INFO', 'Work item assigned', {
        board_id: boardId ?? null,
        item_id: merged.item_id,
        assignee_id: merged.assignee_id ?? null,
        assignee_type: merged.assignee_type ?? null,
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
        await cancelAllBoardItemQueriesForBoard(queryClient, boardId);
      }

      const previousItem = queryClient.getQueryData<WorkItem | null>(boardKeys.item(input.itemId)) ?? null;
      const previousItemEntries = boardId
        ? queryClient.getQueriesData<WorkItem[]>({
            predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
          })
        : [];

      const applyPatch = (item: WorkItem): WorkItem => ({
        ...item,
        assignee_id: null,
        assignee_type: null,
      });

      if (previousItem) {
        queryClient.setQueryData<WorkItem | null>(boardKeys.item(input.itemId), applyPatch(previousItem));
      }

      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            if (!list.some((item) => item.item_id === input.itemId)) return list;
            return list.map((item) => (item.item_id === input.itemId ? applyPatch(item) : item));
          },
        );
      }

      return { previousItem, previousItemEntries };
    },
    onError: async (error, input, context) => {
      queryClient.setQueryData(boardKeys.item(input.itemId), (context as { previousItem?: WorkItem | null } | undefined)?.previousItem ?? null);
      const ctx = context as { previousItemEntries?: [readonly unknown[], WorkItem[]][] } | undefined;
      ctx?.previousItemEntries?.forEach(([key, data]) => {
        queryClient.setQueryData(key as readonly unknown[], data);
      });
      await razeLog('ERROR', 'Work item unassign failed', {
        board_id: boardId ?? null,
        item_id: input.itemId,
        error: error instanceof Error ? error.message : String(error),
      });
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<WorkItem | null>(boardKeys.item(updated.item_id), updated);
      if (boardId) {
        queryClient.setQueriesData<WorkItem[]>(
          { predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId) },
          (current) => {
            const list = current ?? [];
            if (!list.some((item) => item.item_id === updated.item_id)) return list;
            return list.map((item) => (item.item_id === updated.item_id ? updated : item));
          },
        );
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
        await queryClient.invalidateQueries({
          predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, boardId),
        });
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
