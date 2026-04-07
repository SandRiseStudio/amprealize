/**
 * Board Filter Bar
 *
 * A sleek, glassmorphic toolbar for filtering and sorting board work items.
 * Follows the filter-pill pattern from AgentsPage — pills, search, dropdowns.
 *
 * All filter state lives in URL search params via useBoardFilters().
 */

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw, Settings } from 'lucide-react';
import type { WorkItemPriority, WorkItemType } from '../../api/boards';
import { ActorAvatar } from '../actors/ActorAvatar';
import type { AssigneeProfile } from './WorkItemDrawer';
import type { SortField, BoardFilterState } from './useBoardFilters';

import './BoardFilterBar.css';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_OPTIONS: Array<{ label: string; value: WorkItemType; icon: string }> = [
  { label: 'Goal', value: 'goal', icon: '◆' },
  { label: 'Feature', value: 'feature', icon: '◇' },
  { label: 'Task', value: 'task', icon: '•' },
  { label: 'Bug', value: 'bug', icon: '🐛' },
];

const PRIORITY_OPTIONS: Array<{ label: string; value: WorkItemPriority; cssClass: string }> = [
  { label: 'Critical', value: 'critical', cssClass: 'priority-critical' },
  { label: 'High', value: 'high', cssClass: 'priority-high' },
  { label: 'Medium', value: 'medium', cssClass: 'priority-medium' },
  { label: 'Low', value: 'low', cssClass: 'priority-low' },
];

const SORT_OPTIONS: Array<{ label: string; value: SortField }> = [
  { label: 'Position', value: 'position' },
  { label: 'Priority', value: 'priority' },
  { label: 'Created', value: 'created_at' },
  { label: 'Updated', value: 'updated_at' },
  { label: 'Due Date', value: 'due_date' },
  { label: 'Title', value: 'title' },
  { label: 'Points', value: 'points' },
];

const DUE_PRESETS: Array<{ label: string; getRange: () => { after: string | null; before: string | null } }> = [
  {
    label: 'Overdue',
    getRange: () => ({ after: null, before: new Date().toISOString().slice(0, 10) }),
  },
  {
    label: 'This week',
    getRange: () => {
      const now = new Date();
      const day = now.getDay();
      const monday = new Date(now);
      monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
      const sunday = new Date(monday);
      sunday.setDate(monday.getDate() + 6);
      return {
        after: monday.toISOString().slice(0, 10),
        before: sunday.toISOString().slice(0, 10),
      };
    },
  },
  {
    label: 'This month',
    getRange: () => {
      const now = new Date();
      const first = new Date(now.getFullYear(), now.getMonth(), 1);
      const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      return {
        after: first.toISOString().slice(0, 10),
        before: last.toISOString().slice(0, 10),
      };
    },
  },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type ViewMode = 'board' | 'outline';

interface BoardFilterBarProps {
  filterState: BoardFilterState;
  assignableHumans: AssigneeProfile[];
  assignableAgents: AssigneeProfile[];
  allLabels: string[];
  totalCount: number;
  matchCount: number;
  collapsed?: boolean;
  onToggleExpand?: () => void;
  /* Unified-bar props (header elements folded in) */
  boardTitle: string;
  projectTitle: string;
  onBack: () => void;
  viewMode: ViewMode;
  onViewChange: (mode: ViewMode) => void;
  onSettings: () => void;
  /* My Work filter */
  isMyWorkActive?: boolean;
  onToggleMyWork?: () => void;
  /* Refresh props */
  onRefresh?: () => void;
  isRefreshing?: boolean;
  lastSyncedAt?: Date | null;

}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const BoardFilterBar = memo(function BoardFilterBar({
  filterState,
  assignableHumans,
  assignableAgents,
  allLabels,
  totalCount,
  matchCount,
  collapsed = false,
  onToggleExpand,
  boardTitle,
  projectTitle,
  onBack,
  viewMode,
  onViewChange,
  onSettings,
  isMyWorkActive = false,
  onToggleMyWork,
  onRefresh,
  isRefreshing = false,
  lastSyncedAt,

}: BoardFilterBarProps) {
  const { filters, sort, hasActiveFilters, activeFilterCount, setFilter, setSort, toggleSort, clearFilters } = filterState;
  const searchRef = useRef<HTMLInputElement>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const filtersRef = useRef<HTMLDivElement>(null);
  const sortRef = useRef<HTMLDivElement>(null);
  const filtersTriggerRef = useRef<HTMLButtonElement>(null);
  const sortTriggerRef = useRef<HTMLButtonElement>(null);

  const closeAllPopovers = useCallback((focusTarget?: HTMLElement | null) => {
    setFiltersOpen(false);
    setSortOpen(false);
    if (focusTarget) {
      window.requestAnimationFrame(() => focusTarget.focus());
    }
  }, []);

  // Close popover on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (filtersOpen && filtersRef.current && !filtersRef.current.contains(e.target as Node)) {
        setFiltersOpen(false);
      }
      if (sortOpen && sortRef.current && !sortRef.current.contains(e.target as Node)) {
        setSortOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [filtersOpen, sortOpen]);

  useEffect(() => {
    if (!filtersOpen && !sortOpen) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();

      if (sortOpen) {
        closeAllPopovers(sortTriggerRef.current);
        return;
      }
      if (filtersOpen) {
        closeAllPopovers(filtersTriggerRef.current);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [closeAllPopovers, filtersOpen, sortOpen]);

  // / to focus search (⌘K reserved for shell command palette)
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === '/' && !isInputFocused()) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);

  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setFilter('query', '');
      searchRef.current?.blur();
    }
  }, [setFilter]);

  // Type toggle
  const toggleType = useCallback((type: WorkItemType) => {
    const current = filters.types;
    const next = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    setFilter('types', next);
  }, [filters.types, setFilter]);

  // Priority toggle
  const togglePriority = useCallback((priority: WorkItemPriority) => {
    const current = filters.priorities;
    const next = current.includes(priority)
      ? current.filter((p) => p !== priority)
      : [...current, priority];
    setFilter('priorities', next);
  }, [filters.priorities, setFilter]);

  // Assignee toggle (no auto-close in combined popover)
  const toggleAssignee = useCallback((id: string) => {
    setFilter('assigneeId', filters.assigneeId === id ? null : id);
  }, [filters.assigneeId, setFilter]);

  // Label toggle
  const toggleLabel = useCallback((label: string) => {
    const current = filters.labels;
    const next = current.includes(label)
      ? current.filter((l) => l !== label)
      : [...current, label];
    setFilter('labels', next);
  }, [filters.labels, setFilter]);

  // Sort select
  const handleSortSelect = useCallback((field: SortField) => {
    if (sort.field === field) {
      toggleSort(field);
    } else {
      setSort(field, 'asc');
    }
    setSortOpen(false);
  }, [setSort, sort.field, toggleSort]);

  // Due date preset (no auto-close in combined popover)
  const handleDuePreset = useCallback((preset: typeof DUE_PRESETS[number]) => {
    const range = preset.getRange();
    setFilter('dueAfter', range.after);
    setFilter('dueBefore', range.before);
  }, [setFilter]);

  const clearDueDates = useCallback(() => {
    setFilter('dueAfter', null);
    setFilter('dueBefore', null);
  }, [setFilter]);

  const hasDueFilter = Boolean(filters.dueAfter || filters.dueBefore);

  // Combined filters count for the unified Filters chip
  const combinedFiltersCount = useMemo(() => {
    let count = 0;
    if (filters.assigneeId) count += 1;
    if (filters.labels.length > 0) count += filters.labels.length;
    if (hasDueFilter) count += 1;
    return count;
  }, [filters.assigneeId, filters.labels.length, hasDueFilter]);

  const currentSortLabel = SORT_OPTIONS.find((o) => o.value === sort.field)?.label ?? 'Position';

  return (
    <div className={`board-filter-bar animate-fade-in-up ${collapsed ? 'board-filter-bar-collapsed' : ''}`} role="toolbar" aria-label="Board toolbar">
      {/* ── Single command bar row ─────────────────────────────────────── */}
      <div className="board-toolbar-chrome">
        <div className="board-toolbar-left">
          <button
            type="button"
            className="board-back pressable"
            onClick={onBack}
            data-haptic="light"
          >
            ← {projectTitle}
          </button>
          <h1 className="board-title">{boardTitle}</h1>
        </div>

        <div className="board-toolbar-right">
          {/* Compact search */}
          <label className="board-filter-search-wrapper">
            <span className="board-filter-search-icon" aria-hidden="true">⌕</span>
            <input
              ref={searchRef}
              className="board-filter-search"
              value={filters.query}
              onChange={(e) => setFilter('query', e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search…"
              autoComplete="off"
              spellCheck={false}
              aria-label="Search work items"
            />
            {!filters.query && (
              <span className="board-filter-search-shortcut" aria-hidden="true">/</span>
            )}
            {filters.query && (
              <button
                type="button"
                className="board-filter-search-clear pressable"
                onClick={() => setFilter('query', '')}
                aria-label="Clear search"
              >
                ×
              </button>
            )}
          </label>

          {/* My Work quick-toggle */}
          {onToggleMyWork && (
            <button
              type="button"
              className={`board-mywork-chip pressable ${isMyWorkActive ? 'active' : ''}`}
              onClick={onToggleMyWork}
              data-haptic="light"
              aria-pressed={isMyWorkActive}
              title={isMyWorkActive ? 'Show all items' : 'Show only my items'}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <circle cx="8" cy="5" r="3" stroke="currentColor" strokeWidth="1.5" />
                <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <span className="board-mywork-label">My Work</span>
            </button>
          )}

          {/* View toggle */}
          <div
            className="board-view-segmented"
            role="group"
            aria-label="View mode"
            title="Switch view"
          >
            <button
              type="button"
              className={`board-view-option pressable ${viewMode === 'board' ? 'active' : ''}`}
              onClick={() => onViewChange('board')}
              data-haptic="light"
              aria-pressed={viewMode === 'board'}
              title="Board view"
            >
              <span className="board-view-option-icon" aria-hidden="true">▦</span>
              <span className="board-view-option-label">Board</span>
            </button>
            <button
              type="button"
              className={`board-view-option pressable ${viewMode === 'outline' ? 'active' : ''}`}
              onClick={() => onViewChange('outline')}
              data-haptic="light"
              aria-pressed={viewMode === 'outline'}
              title="Outline view"
            >
              <span className="board-view-option-icon" aria-hidden="true">☰</span>
              <span className="board-view-option-label">Outline</span>
            </button>
          </div>

          {/* Filter expand trigger */}
          <button
            type="button"
            className={`board-filter-expand-trigger pressable ${hasActiveFilters ? 'active' : ''}`}
            onClick={onToggleExpand}
            data-haptic="light"
            aria-label={`Toggle filters${activeFilterCount > 0 ? ` (${activeFilterCount} active)` : ''}`}
            aria-expanded={!collapsed}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M2 4h12M4 8h8M6 12h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            {activeFilterCount > 0 && (
              <span className="board-filter-expand-badge">{activeFilterCount}</span>
            )}
          </button>

          {onRefresh && (
            <button
              type="button"
              className={`board-refresh pressable ${isRefreshing ? 'refreshing' : ''}`}
              onClick={onRefresh}
              disabled={isRefreshing}
              data-haptic="light"
              aria-label={isRefreshing ? 'Refreshing…' : 'Refresh board'}
              title={lastSyncedAt ? `Last synced ${formatRelativeTime(lastSyncedAt)}` : 'Refresh board'}
            >
              <RefreshCw
                className="board-refresh-icon"
                size={15}
                strokeWidth={2.2}
                absoluteStrokeWidth
                aria-hidden="true"
              />
            </button>
          )}
          <button
            type="button"
            className="board-settings pressable"
            onClick={onSettings}
            data-haptic="light"
            aria-label="Open project settings"
            title="Open project settings"
          >
            <Settings className="board-settings-icon" size={16} strokeWidth={2.1} absoluteStrokeWidth aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* ── Expandable filter panel ────────────────────────────────────── */}
      <div className={`board-toolbar-filters ${collapsed ? 'board-toolbar-filters-hidden' : ''}`}>
      <div className="board-filter-advanced">

      {/* Type pills */}
      <div className="board-filter-group board-filter-group-emphasis board-filter-group-type" role="group" aria-label="Filter by type">
        <span className="board-filter-label">Type</span>
        <div className="board-filter-pills">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`board-filter-pill pressable ${filters.types.includes(opt.value) ? 'active' : ''}`}
              onClick={() => toggleType(opt.value)}
              data-haptic="light"
              aria-pressed={filters.types.includes(opt.value)}
            >
              <span className="board-filter-pill-icon" aria-hidden="true">{opt.icon}</span>
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Priority pills */}
      <div className="board-filter-group board-filter-group-emphasis board-filter-group-priority" role="group" aria-label="Filter by priority">
        <span className="board-filter-label">Priority</span>
        <div className="board-filter-pills">
          {PRIORITY_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`board-filter-pill pressable ${filters.priorities.includes(opt.value) ? 'active' : ''} ${opt.cssClass}`}
              onClick={() => togglePriority(opt.value)}
              data-haptic="light"
              aria-pressed={filters.priorities.includes(opt.value)}
            >
              <span className={`board-filter-priority-dot ${opt.cssClass}`} aria-hidden="true" />
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Combined Filters dropdown (Assignee + Labels + Due Date) */}
      <div className="board-filter-dropdown-wrapper board-filter-group-emphasis board-filter-group-filters" ref={filtersRef}>
        <button
          ref={filtersTriggerRef}
          type="button"
          className={`board-filter-dropdown-trigger pressable ${combinedFiltersCount > 0 ? 'active' : ''}`}
          onClick={() => setFiltersOpen((p) => !p)}
          data-haptic="light"
          aria-expanded={filtersOpen}
          aria-haspopup="dialog"
        >
          {combinedFiltersCount > 0 ? `Filters (${combinedFiltersCount})` : 'Filters'}
          <span className="board-filter-dropdown-arrow" aria-hidden="true">{filtersOpen ? '▴' : '▾'}</span>
        </button>
        {filtersOpen && (
          <div className="board-filter-popover board-filter-combined-popover" role="dialog" aria-label="Filter options">
            {/* Assignee section */}
            <div className="board-filter-section">
              <div className="board-filter-section-header">Assignee</div>
              <button
                type="button"
                className={`board-filter-popover-option pressable ${filters.assigneeId === '__unassigned__' ? 'selected' : ''}`}
                onClick={() => toggleAssignee('__unassigned__')}
              >
                <span className="board-filter-popover-avatar">—</span>
                <span>Unassigned</span>
              </button>
              {assignableHumans.length > 0 && (
                <div className="board-filter-popover-section-label">People</div>
              )}
              {assignableHumans.map((person) => (
                <button
                  key={person.id}
                  type="button"
                  className={`board-filter-popover-option pressable ${filters.assigneeId === person.id ? 'selected' : ''}`}
                  onClick={() => toggleAssignee(person.id)}
                >
                  <span className="board-filter-popover-avatar">
                    {person.actor ? (
                      <ActorAvatar actor={person.actor} size="sm" surfaceType="chip" decorative />
                    ) : (
                      person.avatar
                    )}
                  </span>
                  <span className="board-filter-popover-name">
                    {person.label}
                    {person.subtitle ? <span className="board-filter-popover-subtitle">{person.subtitle}</span> : null}
                  </span>
                </button>
              ))}
              {assignableAgents.length > 0 && (
                <div className="board-filter-popover-section-label">Agents</div>
              )}
              {assignableAgents.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  className={`board-filter-popover-option pressable ${filters.assigneeId === agent.id ? 'selected' : ''}`}
                  onClick={() => toggleAssignee(agent.id)}
                >
                  <span className="board-filter-popover-avatar">
                    {agent.actor ? (
                      <ActorAvatar actor={agent.actor} size="sm" surfaceType="chip" decorative />
                    ) : (
                      agent.avatar
                    )}
                  </span>
                  <span className="board-filter-popover-name">
                    {agent.label}
                    {agent.subtitle ? <span className="board-filter-popover-subtitle">{agent.subtitle}</span> : null}
                  </span>
                </button>
              ))}
              {filters.assigneeId && (
                <button
                  type="button"
                  className="board-filter-section-clear pressable"
                  onClick={() => setFilter('assigneeId', null)}
                >
                  Clear assignee
                </button>
              )}
            </div>

            {/* Due Date section */}
            <div className="board-filter-section">
              <div className="board-filter-section-header">Due Date</div>
              <div className="board-filter-due-presets">
                {DUE_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    className="board-filter-due-preset pressable"
                    onClick={() => handleDuePreset(preset)}
                    data-haptic="light"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              <div className="board-filter-due-inputs">
                <label className="board-filter-due-field">
                  <span className="board-filter-label">After</span>
                  <input
                    type="date"
                    className="board-filter-date-input"
                    value={filters.dueAfter ?? ''}
                    onChange={(e) => setFilter('dueAfter', e.target.value || null)}
                  />
                </label>
                <label className="board-filter-due-field">
                  <span className="board-filter-label">Before</span>
                  <input
                    type="date"
                    className="board-filter-date-input"
                    value={filters.dueBefore ?? ''}
                    onChange={(e) => setFilter('dueBefore', e.target.value || null)}
                  />
                </label>
              </div>
              {hasDueFilter && (
                <button
                  type="button"
                  className="board-filter-section-clear pressable"
                  onClick={clearDueDates}
                >
                  Clear dates
                </button>
              )}
            </div>

            {/* Labels section */}
            {allLabels.length > 0 && (
              <div className="board-filter-section">
                <div className="board-filter-section-header">Labels</div>
                {allLabels.map((label) => (
                  <button
                    key={label}
                    type="button"
                    className={`board-filter-popover-option pressable ${filters.labels.includes(label) ? 'selected' : ''}`}
                    onClick={() => toggleLabel(label)}
                  >
                    <span className="board-filter-check" aria-hidden="true">
                      {filters.labels.includes(label) ? '✓' : ''}
                    </span>
                    <span>{label}</span>
                  </button>
                ))}
                {filters.labels.length > 0 && (
                  <button
                    type="button"
                    className="board-filter-section-clear pressable"
                    onClick={() => setFilter('labels', [])}
                  >
                    Clear labels
                  </button>
                )}
              </div>
            )}

            {/* Clear all filters in popover */}
            {combinedFiltersCount > 0 && (
              <button
                type="button"
                className="board-filter-popover-clear pressable"
                onClick={() => {
                  setFilter('assigneeId', null);
                  setFilter('labels', []);
                  clearDueDates();
                }}
              >
                Clear all filters
              </button>
            )}
          </div>
        )}
      </div>

      {/* Sort control */}
      <div className="board-filter-sort-wrapper board-filter-group-emphasis board-filter-group-sort" ref={sortRef}>
        <button
          ref={sortTriggerRef}
          type="button"
          className={`board-filter-sort-trigger pressable ${sort.field !== 'position' ? 'active' : ''}`}
          onClick={() => setSortOpen((p) => !p)}
          data-haptic="light"
          aria-expanded={sortOpen}
          aria-haspopup="listbox"
        >
          <span className="board-filter-sort-label">Sort: {currentSortLabel}</span>
          <span
            className={`board-filter-sort-direction ${sort.order}`}
            aria-label={sort.order === 'asc' ? 'Ascending' : 'Descending'}
            onClick={(e) => { e.stopPropagation(); toggleSort(sort.field); }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                e.stopPropagation();
                toggleSort(sort.field);
              }
            }}
            role="button"
            tabIndex={0}
          >
            {sort.order === 'asc' ? '↑' : '↓'}
          </span>
        </button>
        {sortOpen && (
          <div className="board-filter-popover board-filter-sort-popover" role="listbox" aria-label="Sort options">
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`board-filter-popover-option pressable ${sort.field === opt.value ? 'selected' : ''}`}
                onClick={() => handleSortSelect(opt.value)}
              >
                <span className="board-filter-check" aria-hidden="true">
                  {sort.field === opt.value ? '✓' : ''}
                </span>
                {opt.label}
                {sort.field === opt.value && (
                  <span className="board-filter-sort-indicator">{sort.order === 'asc' ? '↑' : '↓'}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Active filter summary + clear */}
      {hasActiveFilters && (
        <div className="board-filter-summary" aria-live="polite">
          <span className="board-filter-count-badge">{activeFilterCount}</span>
          <span className="board-filter-match-text">
            {matchCount} of {totalCount}
          </span>
          <button
            type="button"
            className="board-filter-clear-all pressable"
            onClick={clearFilters}
            data-haptic="light"
          >
            Clear all
          </button>
        </div>
      )}
      </div>{/* end board-filter-advanced */}

      </div>{/* end board-toolbar-filters */}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || (el as HTMLElement).isContentEditable;
}

function formatRelativeTime(date: Date): string {
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);

  if (diffSecs < 10) return 'just now';
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  return date.toLocaleTimeString();
}
