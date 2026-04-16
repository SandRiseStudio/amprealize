/**
 * Board Filtering & Sorting — URL-synced state + client-side filter logic
 *
 * Filters persist in URL search params so filtered board views are shareable.
 * Client-side filtering runs instantly (items already loaded); the same params
 * are also forwarded to the server for cross-surface parity.
 *
 * Hierarchy UX: matching items highlight, non-matching ancestors dim.
 */

import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type {
  BoardWorkItemQuery,
  BoardWorkItemSortField,
  BoardWorkItemSortOrder,
  WorkItem,
  WorkItemPriority,
  WorkItemType,
} from '../../api/boards';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SortField = BoardWorkItemSortField;
export type SortOrder = BoardWorkItemSortOrder;

export interface BoardFilters {
  /** Free-text search on title */
  query: string;
  /** Filter by work item type — null means all */
  types: WorkItemType[];
  /** Filter by priority — null means all */
  priorities: WorkItemPriority[];
  /** Filter by assignee ID */
  assigneeId: string | null;
  /** Filter by assignee type */
  assigneeType: 'user' | 'agent' | null;
  /** Filter by labels (any match) */
  labels: string[];
  /** Items due on or after this ISO date */
  dueAfter: string | null;
  /** Items due on or before this ISO date */
  dueBefore: string | null;
}

export interface SortConfig {
  field: SortField;
  order: SortOrder;
}

export interface BoardFilterState {
  filters: BoardFilters;
  sort: SortConfig;
  hasActiveFilters: boolean;
  activeFilterCount: number;
  setFilter: <K extends keyof BoardFilters>(key: K, value: BoardFilters[K]) => void;
  setSort: (field: SortField, order?: SortOrder) => void;
  toggleSort: (field: SortField) => void;
  clearFilters: () => void;
  clearAll: () => void;
}

// ---------------------------------------------------------------------------
// URL Param Constants
// ---------------------------------------------------------------------------

const PARAM_QUERY = 'q';
const PARAM_TYPE = 'type';
const PARAM_PRIORITY = 'priority';
const PARAM_ASSIGNEE = 'assignee';
const PARAM_ASSIGNEE_TYPE = 'assignee_type';
const PARAM_LABELS = 'labels';
const PARAM_DUE_AFTER = 'due_after';
const PARAM_DUE_BEFORE = 'due_before';
const PARAM_SORT = 'sort';
const PARAM_ORDER = 'order';

const VALID_TYPES = new Set<WorkItemType>(['goal', 'feature', 'task', 'bug']);
const VALID_PRIORITIES = new Set<WorkItemPriority>(['critical', 'high', 'medium', 'low']);
const VALID_SORT_FIELDS = new Set<SortField>([
  'position', 'priority', 'created_at', 'updated_at', 'due_date', 'title', 'points',
]);

const DEFAULT_SORT: SortConfig = { field: 'position', order: 'asc' };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseList<T extends string>(raw: string | null, validSet: Set<T>): T[] {
  if (!raw) return [];
  return raw.split(',').filter((v): v is T => validSet.has(v as T));
}

function parseStringList(raw: string | null): string[] {
  if (!raw) return [];
  return raw.split(',').map((s) => s.trim()).filter(Boolean);
}

// ---------------------------------------------------------------------------
// useBoardFilters — reads/writes URL search params
// ---------------------------------------------------------------------------

export function useBoardFilters(): BoardFilterState {
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo<BoardFilters>(() => ({
    query: searchParams.get(PARAM_QUERY) ?? '',
    types: parseList(searchParams.get(PARAM_TYPE), VALID_TYPES),
    priorities: parseList(searchParams.get(PARAM_PRIORITY), VALID_PRIORITIES),
    assigneeId: searchParams.get(PARAM_ASSIGNEE),
    assigneeType: (() => {
      const raw = searchParams.get(PARAM_ASSIGNEE_TYPE);
      if (raw === 'user' || raw === 'agent') return raw;
      return null;
    })(),
    labels: parseStringList(searchParams.get(PARAM_LABELS)),
    dueAfter: searchParams.get(PARAM_DUE_AFTER),
    dueBefore: searchParams.get(PARAM_DUE_BEFORE),
  }), [searchParams]);

  const sort = useMemo<SortConfig>(() => {
    const rawField = searchParams.get(PARAM_SORT);
    const rawOrder = searchParams.get(PARAM_ORDER);
    const field = rawField && VALID_SORT_FIELDS.has(rawField as SortField)
      ? (rawField as SortField)
      : DEFAULT_SORT.field;
    const order = rawOrder === 'desc' ? 'desc' : 'asc';
    return { field, order };
  }, [searchParams]);

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (filters.query) count++;
    if (filters.types.length > 0) count++;
    if (filters.priorities.length > 0) count++;
    if (filters.assigneeId) count++;
    if (filters.assigneeType) count++;
    if (filters.labels.length > 0) count++;
    if (filters.dueAfter) count++;
    if (filters.dueBefore) count++;
    return count;
  }, [filters]);

  const hasActiveFilters = activeFilterCount > 0;

  const setFilter = useCallback(<K extends keyof BoardFilters>(key: K, value: BoardFilters[K]) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);

      const clear = (param: string) => next.delete(param);
      const set = (param: string, v: string) => { if (v) next.set(param, v); else next.delete(param); };

      switch (key) {
        case 'query':
          set(PARAM_QUERY, value as string);
          break;
        case 'types':
          { const arr = value as WorkItemType[];
            if (arr.length > 0) next.set(PARAM_TYPE, arr.join(','));
            else clear(PARAM_TYPE);
          }
          break;
        case 'priorities':
          { const arr = value as WorkItemPriority[];
            if (arr.length > 0) next.set(PARAM_PRIORITY, arr.join(','));
            else clear(PARAM_PRIORITY);
          }
          break;
        case 'assigneeId':
          set(PARAM_ASSIGNEE, (value as string | null) ?? '');
          break;
        case 'assigneeType':
          set(PARAM_ASSIGNEE_TYPE, (value as string | null) ?? '');
          break;
        case 'labels':
          { const arr = value as string[];
            if (arr.length > 0) next.set(PARAM_LABELS, arr.join(','));
            else clear(PARAM_LABELS);
          }
          break;
        case 'dueAfter':
          set(PARAM_DUE_AFTER, (value as string | null) ?? '');
          break;
        case 'dueBefore':
          set(PARAM_DUE_BEFORE, (value as string | null) ?? '');
          break;
      }

      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const setSort = useCallback((field: SortField, order?: SortOrder) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (field === DEFAULT_SORT.field && (order ?? 'asc') === DEFAULT_SORT.order) {
        next.delete(PARAM_SORT);
        next.delete(PARAM_ORDER);
      } else {
        next.set(PARAM_SORT, field);
        if (order && order !== 'asc') next.set(PARAM_ORDER, order);
        else next.delete(PARAM_ORDER);
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const toggleSort = useCallback((field: SortField) => {
    const newOrder = sort.field === field && sort.order === 'asc' ? 'desc' : 'asc';
    setSort(field, newOrder);
  }, [setSort, sort.field, sort.order]);

  const clearFilters = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      [PARAM_QUERY, PARAM_TYPE, PARAM_PRIORITY, PARAM_ASSIGNEE, PARAM_ASSIGNEE_TYPE,
       PARAM_LABELS, PARAM_DUE_AFTER, PARAM_DUE_BEFORE].forEach((p) => next.delete(p));
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  const clearAll = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      [PARAM_QUERY, PARAM_TYPE, PARAM_PRIORITY, PARAM_ASSIGNEE, PARAM_ASSIGNEE_TYPE,
       PARAM_LABELS, PARAM_DUE_AFTER, PARAM_DUE_BEFORE, PARAM_SORT, PARAM_ORDER,
      ].forEach((p) => next.delete(p));
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  return {
    filters,
    sort,
    hasActiveFilters,
    activeFilterCount,
    setFilter,
    setSort,
    toggleSort,
    clearFilters,
    clearAll,
  };
}

// ---------------------------------------------------------------------------
// Priority rank map for sorting
// ---------------------------------------------------------------------------

const PRIORITY_RANK: Record<WorkItemPriority, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

// ---------------------------------------------------------------------------
// useFilteredItems — client-side filter + hierarchy dimming
// ---------------------------------------------------------------------------

export interface FilterResult {
  /** IDs of items that directly match ALL active filters */
  matchingIds: Set<string>;
  /** IDs of ancestor items that don't match but are kept for hierarchy context */
  ancestorIds: Set<string>;
  /** Whether any filters are currently active */
  isFiltered: boolean;
  /** Number of items that match */
  matchCount: number;
}

export function useFilteredItems(
  items: WorkItem[],
  filters: BoardFilters,
  hasActiveFilters: boolean,
): FilterResult {
  return useMemo(() => {
    if (!hasActiveFilters) {
      return {
        matchingIds: new Set<string>(),
        ancestorIds: new Set<string>(),
        isFiltered: false,
        matchCount: items.length,
      };
    }

    const matchingIds = new Set<string>();
    const itemMap = new Map(items.map((item) => [item.item_id, item]));

    for (const item of items) {
      if (matchesFilters(item, filters)) {
        matchingIds.add(item.item_id);
      }
    }

    // Walk up parent chains to find ancestors of matching items
    const ancestorIds = new Set<string>();
    for (const matchId of matchingIds) {
      let current = itemMap.get(matchId);
      while (current?.parent_id) {
        const parent = itemMap.get(current.parent_id);
        if (parent && !matchingIds.has(parent.item_id)) {
          ancestorIds.add(parent.item_id);
        }
        current = parent;
      }
    }

    return {
      matchingIds,
      ancestorIds,
      isFiltered: true,
      matchCount: matchingIds.size,
    };
  }, [items, filters, hasActiveFilters]);
}

function matchesFilters(item: WorkItem, filters: BoardFilters): boolean {
  // Text search — case-insensitive substring
  if (filters.query) {
    const q = filters.query.toLowerCase();
    if (!item.title.toLowerCase().includes(q)) {
      return false;
    }
  }

  // Type filter — item must be one of selected types
  if (filters.types.length > 0) {
    if (!filters.types.includes(item.item_type)) {
      return false;
    }
  }

  // Priority filter — item must be one of selected priorities
  if (filters.priorities.length > 0) {
    if (!filters.priorities.includes(item.priority)) {
      return false;
    }
  }

  // Assignee filter
  if (filters.assigneeId) {
    if (filters.assigneeId === '__unassigned__') {
      if (item.assignee_id) return false;
    } else if (item.assignee_id !== filters.assigneeId) {
      return false;
    }
  }

  // Assignee type filter
  if (filters.assigneeType) {
    if (item.assignee_type !== filters.assigneeType) {
      return false;
    }
  }

  // Labels filter — any-match (OR within labels)
  if (filters.labels.length > 0) {
    const itemLabels = new Set(item.labels ?? []);
    if (!filters.labels.some((label) => itemLabels.has(label))) {
      return false;
    }
  }

  // Due date range
  if (filters.dueAfter && item.due_date) {
    if (item.due_date < filters.dueAfter) return false;
  }
  if (filters.dueAfter && !item.due_date) {
    return false; // no due date → doesn't satisfy "due after X"
  }
  if (filters.dueBefore && item.due_date) {
    if (item.due_date > filters.dueBefore) return false;
  }
  if (filters.dueBefore && !item.due_date) {
    return false; // no due date → doesn't satisfy "due before X"
  }

  return true;
}

// ---------------------------------------------------------------------------
// sortItems — dynamic sort for board items (client-side within columns)
// ---------------------------------------------------------------------------

export function sortItems<T extends WorkItem>(items: T[], sortConfig: SortConfig): T[] {
  if (sortConfig.field === 'position') {
    // Default: position + updated_at tiebreaker
    return [...items].sort((a, b) => {
      const posA = a.position ?? 0;
      const posB = b.position ?? 0;
      if (posA !== posB) return sortConfig.order === 'asc' ? posA - posB : posB - posA;
      return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
    });
  }

  const direction = sortConfig.order === 'asc' ? 1 : -1;

  return [...items].sort((a, b) => {
    let cmp = 0;

    switch (sortConfig.field) {
      case 'priority':
        cmp = PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
        break;
      case 'created_at':
        cmp = (a.created_at ?? '').localeCompare(b.created_at ?? '');
        break;
      case 'updated_at':
        cmp = (a.updated_at ?? '').localeCompare(b.updated_at ?? '');
        break;
      case 'due_date': {
        const da = a.due_date ?? '';
        const db = b.due_date ?? '';
        // Nulls sort last regardless of direction
        if (!da && db) return 1;
        if (da && !db) return -1;
        if (!da && !db) return 0;
        cmp = da.localeCompare(db);
        break;
      }
      case 'title':
        cmp = (a.title ?? '').localeCompare(b.title ?? '');
        break;
      case 'points': {
        const sa = (a.points ?? a.story_points) ?? -1;
        const sb = (b.points ?? b.story_points) ?? -1;
        // Nulls sort last
        if (sa === -1 && sb !== -1) return 1;
        if (sa !== -1 && sb === -1) return -1;
        cmp = sa - sb;
        break;
      }
    }

    return cmp * direction;
  });
}

// ---------------------------------------------------------------------------
// Utility: convert filters to API query params
// ---------------------------------------------------------------------------

export function filtersToQueryParams(filters: BoardFilters, sort: SortConfig): BoardWorkItemQuery {
  const query: BoardWorkItemQuery = {};

  if (filters.query) query.titleSearch = filters.query;
  if (filters.types.length > 0) query.itemTypes = filters.types;
  if (filters.priorities.length > 0) query.priorities = filters.priorities;
  if (filters.assigneeId) query.assigneeId = filters.assigneeId;
  if (filters.assigneeType) query.assigneeType = filters.assigneeType;
  if (filters.labels.length > 0) query.labels = filters.labels;
  if (filters.dueAfter) query.dueAfter = filters.dueAfter;
  if (filters.dueBefore) query.dueBefore = filters.dueBefore;
  if (sort.field !== 'position') query.sortBy = sort.field;
  if (sort.order !== 'asc') query.order = sort.order;

  return query;
}
