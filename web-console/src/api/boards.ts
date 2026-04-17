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

   Loads the first page immediately, then hydrates later pages in the
   background so large boards reach first paint much sooner.
   ───────────────────────────────────────────────────────────────────────────── */

/** Must stay ≤ the deployed API's `GET /v1/work-items` `limit` max (see board_api_v2, le=250). */
const DEFAULT_ITEMS_PAGE_SIZE = 100;
const MAX_ITEMS_PAGE_SIZE = 250;

/** Stable empty array to avoid reference changes when data is null */
const EMPTY_ITEMS: WorkItem[] = [];
interface WorkItemsMeta {
  total: number;
  loadedCount: number;
  isPartial: boolean;
}

const EMPTY_WORK_ITEMS_META: WorkItemsMeta = {
  total: 0,
  loadedCount: 0,
  isPartial: false,
};

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
  if (query.itemTypes?.length) normalized.itemTypes = [...new Set(query.itemTypes)];
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

function normalizePageItems(items: WorkItem[]): WorkItem[] {
  return items.map((item) => ({
    ...item,
    item_type: normalizeItemType(item.item_type),
    points: item.points ?? item.story_points ?? null,
  }));
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
  let offset = 0;
  let serverMerged: WorkItem[] = [];
  let total = 0;
  for (let guard = 0; guard < 500; guard += 1) {
    const includeTotal = guard === 0;
    const page = await fetchWorkItemsPage(boardId, pageSize, offset, includeTotal, query);
    if (includeTotal || total === 0) {
      total = page.total;
    }
    serverMerged = mergeUniqueWorkItems([...serverMerged, ...page.items]);
    if (!page.hasMore || serverMerged.length >= total || page.items.length === 0) {
      break;
    }
    offset += page.items.length;
  }
  return { serverMerged, total };
}

export function useWorkItems(
  boardId?: string,
  options?: {
    query?: BoardWorkItemQuery;
    pageSize?: number;
    progressive?: boolean;
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

      const prevItems = queryClient.getQueryData<WorkItem[]>(itemsKey) ?? EMPTY_ITEMS;
      const prevMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;

      const warmItems = prevItems.length > 0;
      const isFreshManualReset =
        prevMeta.total === 0 && !prevMeta.isPartial && prevMeta.loadedCount === 0;
      const shouldResyncAllPages =
        warmItems
        && !isFreshManualReset
        && (prevMeta.isPartial || (prevMeta.total > 0 && !prevMeta.isPartial));

      if (shouldResyncAllPages) {
        const { serverMerged, total } = await fetchAllWorkItemsPaged(boardId, pageSize, normalizedQuery);
        const visibleItems = await buildVisibleWorkItems(serverMerged, normalizedQuery);
        queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
          total,
          loadedCount: serverMerged.length,
          isPartial: false,
        });
        return visibleItems;
      }

      const firstPage = await fetchWorkItemsPage(boardId, pageSize, 0, true, normalizedQuery);
      queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
        total: firstPage.total,
        loadedCount: firstPage.items.length,
        isPartial: firstPage.hasMore && firstPage.items.length < firstPage.total,
      });
      return buildVisibleWorkItems(firstPage.items, normalizedQuery);
    },
    enabled: Boolean(boardId),
    staleTime: 5 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchInterval: false,
    placeholderData: keepPreviousData,
  });

  const appendNextPage = React.useCallback(async () => {
    if (!boardId) return;

    const currentMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;
    if (!currentMeta.isPartial) return;

    const currentItems = queryClient.getQueryData<WorkItem[]>(itemsKey) ?? EMPTY_ITEMS;
    const currentServerItems = hasActiveBoardFilters(normalizedQuery)
      ? currentItems.filter((item) => matchesBoardWorkItemQuery(item, normalizedQuery))
      : currentItems;

    const nextPage = await fetchWorkItemsPage(boardId, pageSize, currentMeta.loadedCount, false, normalizedQuery);
    const mergedServerItems = mergeUniqueWorkItems([...currentServerItems, ...nextPage.items]);
    const visibleItems = await buildVisibleWorkItems(mergedServerItems, normalizedQuery);

    queryClient.setQueryData<WorkItem[]>(itemsKey, visibleItems);
    queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
      total: currentMeta.total > 0 ? currentMeta.total : nextPage.total,
      loadedCount: mergedServerItems.length,
      isPartial: nextPage.hasMore
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
      // Background hydration: after the first page lands, fan out the
      // remaining pages in waves so we overlap handler time across API
      // workers instead of walking one-page-at-a-time. With workers=4 and
      // ~500-700ms per handler on Neon, a serial walk of 9 pages took
      // ~5-7s of pure request time; four in parallel collapses that to
      // ceil(9/4)=3 waves.
      const PARALLELISM = 4;
      // Read per-wave backoff from localStorage (kept for the perf harness
      // A/B). Default is 0 now that the sleep's only purpose — letting
      // a single worker drain before the next page — is obsolete under
      // workers>=2.
      const readHydrateSleepMs = (): number => {
        try {
          const raw = window.localStorage?.getItem('amprealize.hydrateSleepMs');
          if (raw === null || raw === undefined) return 0;
          const n = Number(raw);
          return Number.isFinite(n) && n >= 0 ? n : 0;
        } catch {
          return 0;
        }
      };

      try {
        while (!cancelled) {
          const currentMeta = queryClient.getQueryData<WorkItemsMeta>(itemsMetaKey) ?? EMPTY_WORK_ITEMS_META;
          if (!currentMeta.isPartial) break;

          // Precompute up to PARALLELISM offsets for this wave. We rely on
          // `total` being populated by the first page (includeTotal:true);
          // if something went wrong and total is 0, fall back to a single
          // serial append so we can't spin on an unknown page count.
          const offsets: number[] = [];
          if (currentMeta.total > 0) {
            let cursor = currentMeta.loadedCount;
            for (let i = 0; i < PARALLELISM && cursor < currentMeta.total; i += 1) {
              offsets.push(cursor);
              cursor += pageSize;
            }
          }

          // Tight cancellation gate right before any network work: if the
          // effect was cancelled during the last wave's state merge we want
          // to bail out HERE, not after firing another wave of fetches.
          if (cancelled) break;

          if (offsets.length <= 1) {
            await appendNextPage();
          } else {
            const currentItems = queryClient.getQueryData<WorkItem[]>(itemsKey) ?? EMPTY_ITEMS;
            const currentServerItems = hasActiveBoardFilters(normalizedQuery)
              ? currentItems.filter((item) => matchesBoardWorkItemQuery(item, normalizedQuery))
              : currentItems;

            const pages = await Promise.all(
              offsets.map((off) =>
                fetchWorkItemsPage(boardId, pageSize, off, false, normalizedQuery),
              ),
            );
            if (cancelled) break;

            const newServerItems = pages.flatMap((p) => p.items);
            const mergedServerItems = mergeUniqueWorkItems([
              ...currentServerItems,
              ...newServerItems,
            ]);
            const visibleItems = await buildVisibleWorkItems(mergedServerItems, normalizedQuery);
            if (cancelled) break;

            const resolvedTotal = currentMeta.total > 0
              ? currentMeta.total
              : (pages[pages.length - 1]?.total ?? 0);
            const anyPageHasMore = pages.some((p) => p.hasMore);

            queryClient.setQueryData<WorkItem[]>(itemsKey, visibleItems);
            queryClient.setQueryData<WorkItemsMeta>(itemsMetaKey, {
              total: resolvedTotal,
              loadedCount: mergedServerItems.length,
              isPartial: anyPageHasMore && mergedServerItems.length < resolvedTotal,
            });
          }

          const hydrateSleepMs = readHydrateSleepMs();
          if (hydrateSleepMs > 0) await sleep(hydrateSleepMs);
        }
      } finally {
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
    appendNextPage,
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
        metadata: {},
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

      const itemCaches = queryClient.getQueriesData<WorkItem[]>({
        predicate: (q) => isBoardWorkItemsQueryKey(q.queryKey, payload.board_id),
      });
      for (const [key] of itemCaches) {
        queryClient.setQueryData<WorkItem[]>(key, (old) => {
          const list = old ?? [];
          const subq = boardWorkItemQueryFromKey(key as readonly unknown[]);
          if (subq && !matchesBoardWorkItemQuery(optimistic, subq)) return list;
          return [optimistic, ...list];
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
            return list.map((i) => (i.item_id === context?.optimisticId ? created : i));
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
