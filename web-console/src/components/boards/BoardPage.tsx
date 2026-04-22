/**
 * Board Page
 *
 * Fast, optimistic Kanban-style board with:
 * - Create tasks instantly per column
 * - Drag + drop between columns (plus keyboard-friendly Move control)
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student): optimistic updates, 60fps transforms.
 */

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useElementVirtualizer } from '../../hooks/useElementVirtualizer';
import { ExecutionStatusBadge, type ExecutionListItem } from '../../lib/collab-client';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useShellTitle, useShellMode } from '../workspace/useShell';
import { useApiCapabilities } from '../../api/capabilities';
import { type Agent, type AgentStatus, useProject } from '../../api/dashboard';
import { useProjectAgents } from '../../api/agentRegistry';
import { useProjectParticipants, type ProjectParticipant } from '../../api/projects';
import {
  type BoardColumn,
  type WorkItemProgressRollup,
  type WorkItem,
  type WorkItemPriority,
  type WorkItemType,
  useAssignWorkItem,
  useUnassignWorkItem,
  useBoard,
  useBoardProgressRollups,
  useCreateWorkItem,
  useDeleteWorkItem,
  useMoveWorkItem,
  useReorderWorkItems,
  useUpdateWorkItem,
  useWorkItems,
} from '../../api/boards';
import {
  useCancelWorkItemExecution,
  useExecuteWorkItem,
  useExecutionList,
  useExecutionStream,
} from '../../api/executions';
import { useAuth } from '../../auth';
import { ActorAvatar } from '../actors/ActorAvatar';
import { toActorViewModel } from '../../utils/actorViewModel';
import { WorkItemDrawer, type AssigneeProfile } from './WorkItemDrawer';
import { copyTextToClipboard, formatWorkItemDisplayId } from './workItemId';
import { filtersToQueryParams, useBoardFilters, useFilteredItems, sortItems } from './useBoardFilters';
import { BoardFilterBar } from './BoardFilterBar';
import { ColumnSummaryStrip } from './ColumnSummaryStrip';
import { AgentPresenceDrawer } from './AgentPresenceDrawer';
import { ChatHub } from './ChatHub';
import { AgentAssignmentDrawer } from './AgentAssignmentDrawer';
import { useAgentPresence } from '../../hooks/useAgentPresence';
import { type BoardParticipant } from './boardParticipants';
// import { useCollabStore } from '../../store/collabStore';
import { InlineAssigneePopover } from './InlineAssigneePopover';
import {
  UnifiedConversationWindow,
  type UnifiedConversationInitialTarget,
} from '../conversations/UnifiedConversationWindow';
import { useGetOrCreateDirectConversation } from '../../api/conversations';
import { razeLog, perfMark } from '../../telemetry/raze';
import './BoardPage.css';

function getColumnAccentIndex(index: number): number {
  const accentCount = 6;
  const next = index % accentCount;
  return next < 0 ? next + accentCount : next;
}

function getRelativeTime(dateString?: string): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function shortenId(id: string): string {
  if (id.length <= 8) return id;
  return id.slice(0, 8);
}

function getInitials(label: string): string {
  const parts = label.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const second = parts[1]?.[0] ?? '';
  const initials = `${first}${second}`.toUpperCase();
  return initials || '?';
}

function assigneeKey(type: 'user' | 'agent', id: string): string {
  return `${type}:${id}`;
}

type QuickDueDateOption = 'today' | 'tomorrow' | 'next-week';

function quickDueDateLabel(option: QuickDueDateOption): string {
  if (option === 'today') return 'Today';
  if (option === 'tomorrow') return 'Tomorrow';
  return 'Next week';
}

function quickDueDateValue(option: QuickDueDateOption): string {
  const date = new Date();
  date.setHours(17, 0, 0, 0);
  if (option === 'tomorrow') {
    date.setDate(date.getDate() + 1);
  } else if (option === 'next-week') {
    date.setDate(date.getDate() + 7);
  }
  return date.toISOString();
}

function joinNatural(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? '';
  if (parts.length === 2) return `${parts[0]} and ${parts[1]}`;
  return `${parts.slice(0, -1).join(', ')}, and ${parts.at(-1)}`;
}

function sortByPosition<T extends { position?: number; updated_at?: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const posA = a.position ?? 0;
    const posB = b.position ?? 0;
    if (posA !== posB) return posA - posB;
    return (b.updated_at ?? '').localeCompare(a.updated_at ?? '');
  });
}

type DragPayload = { itemId: string };

function parseDragPayload(event: React.DragEvent): DragPayload | null {
  try {
    const raw = event.dataTransfer.getData('application/json');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { itemId?: unknown };
    if (typeof parsed.itemId === 'string' && parsed.itemId) return { itemId: parsed.itemId };
    return null;
  } catch {
    return null;
  }
}

function typeIcon(itemType: WorkItemType): string {
  if (itemType === 'goal') return '◆';
  if (itemType === 'feature') return '◇';
  if (itemType === 'bug') return '🐛';
  return '•';
}

function formatProgressPercent(value: number): string {
  if (!Number.isFinite(value)) return '0%';
  return `${Math.round(value)}%`;
}

function getRollupProgressFillWidth(progressPercentValue: number): string {
  // Keep a visible seed fill for empty rollups without implying meaningful progress.
  return progressPercentValue <= 0 ? '4px' : `${progressPercentValue}%`;
}

function formatRemainingSummary(rollup: WorkItemProgressRollup): string {
  const parts: string[] = [`${rollup.remaining.items_remaining} left`];
  if (rollup.remaining.estimated_hours_remaining != null) {
    parts.push(`${rollup.remaining.estimated_hours_remaining.toFixed(1)}h`);
  }
  if (rollup.remaining.points_remaining != null) {
    parts.push(`${rollup.remaining.points_remaining} pts`);
  }
  return parts.join(' • ');
}

function isAvatarImage(value?: string | null): boolean {
  if (!value) return false;
  if (value.startsWith('data:image/')) return true;
  return /^https?:\/\//i.test(value);
}

function CopyIcon({ className }: { className?: string }): React.JSX.Element {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function TrashIcon({ className }: { className?: string }): React.JSX.Element {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M4 7H20" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M9 4H15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M7 7L8 19C8.08 19.88 8.82 20.56 9.7 20.56H14.3C15.18 20.56 15.92 19.88 16 19L17 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 11V17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M14 11V17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Skeleton Components — Phase 1: Fast shell rendering
   ───────────────────────────────────────────────────────────────────────────── */

/** Skeleton card that mimics work item card structure */
function WorkItemSkeleton(): React.JSX.Element {
  return (
    <div className="work-item-skeleton" aria-hidden="true">
      <div className="skeleton-type" />
      <div className="skeleton-line skeleton-line-full" />
      <div className="skeleton-line skeleton-line-short" />
    </div>
  );
}

/** Skeleton column with header and placeholder cards */
function ColumnSkeleton({ accentIndex }: { accentIndex: number }): React.JSX.Element {
  return (
    <div className={`board-column-skeleton board-column-accent-${accentIndex}`}>
      <div className="board-column-skeleton-header">
        <div className="skeleton-title" />
      </div>
      <div className="board-column-skeleton-items">
        <WorkItemSkeleton />
        <WorkItemSkeleton />
        <WorkItemSkeleton />
      </div>
    </div>
  );
}

/** Full board skeleton with multiple columns */
function BoardSkeleton({ columnCount = 4 }: { columnCount?: number }): React.JSX.Element {
  return (
    <div className="board-loading-shell" role="status" aria-label="Loading board">
      <div className="column-summary-skeleton" aria-hidden="true">
        <div className="column-summary-pill-skeleton" />
        <div className="column-summary-pill-skeleton" />
        <div className="column-summary-pill-skeleton" />
        <div className="column-summary-pill-skeleton" />
      </div>
      <div className="board-columns-skeleton">
        {Array.from({ length: columnCount }, (_, i) => (
          <ColumnSkeleton key={i} accentIndex={getColumnAccentIndex(i)} />
        ))}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   Item Diff Tracking — Phase 4: Premium animations for data changes
   Tracks added/updated/moved items and auto-clears state after animation.
   ───────────────────────────────────────────────────────────────────────────── */

type ItemDiffState = 'added' | 'updated' | 'moved' | null;
type ItemDiffMap = Map<string, ItemDiffState>;

/** Animation duration before clearing diff state (ms) */
const DIFF_ANIMATION_DURATION = 400;

/** Stable empty map to avoid unnecessary re-renders when diff state clears */
const EMPTY_DIFF_MAP: ItemDiffMap = new Map();

/** Stable empty array to avoid new references when a column has no items */
const EMPTY_ITEMS: WorkItem[] = [];

/** Stable empty arrays for assignee defaults — prevents memo-breaking re-renders */
const EMPTY_AGENTS: Agent[] = [];
const EMPTY_PARTICIPANTS: ProjectParticipant[] = [];

interface ItemSnapshot {
  columnId?: string | null;
  updatedAt?: string;
}

/**
 * Hook that tracks work item changes and returns a map of diff states.
 * States auto-clear after DIFF_ANIMATION_DURATION to allow re-animation on next change.
 */
function useItemDiffState(items: WorkItem[]): ItemDiffMap {
  // Store previous item state for comparison
  const prevItemsRef = useRef<Map<string, ItemSnapshot>>(new Map());
  // Track which items have active diff states
  const [diffMap, setDiffMap] = useState<ItemDiffMap>(EMPTY_DIFF_MAP);
  // Track if this is the initial load (skip animation on first render)
  const isInitialLoadRef = useRef(true);

  useEffect(() => {
    // Skip diff tracking on initial load
    if (isInitialLoadRef.current && items.length > 0) {
      // Populate initial snapshot without triggering animations
      const snapshot = new Map<string, ItemSnapshot>();
      for (const item of items) {
        snapshot.set(item.item_id, {
          columnId: item.column_id,
          updatedAt: item.updated_at,
        });
      }
      prevItemsRef.current = snapshot;
      isInitialLoadRef.current = false;
      return;
    }

    // Only compute diffs when we have previous data
    if (prevItemsRef.current.size === 0) return;

    const prev = prevItemsRef.current;
    const newDiffs = new Map<string, ItemDiffState>();

    for (const item of items) {
      const prevItem = prev.get(item.item_id);

      if (!prevItem) {
        // New item that wasn't in previous snapshot
        newDiffs.set(item.item_id, 'added');
      } else if (prevItem.columnId !== item.column_id) {
        // Item moved to different column
        newDiffs.set(item.item_id, 'moved');
      } else if (prevItem.updatedAt !== item.updated_at) {
        // Item was updated
        newDiffs.set(item.item_id, 'updated');
      }
    }

    // Update snapshot for next comparison
    const newSnapshot = new Map<string, ItemSnapshot>();
    for (const item of items) {
      newSnapshot.set(item.item_id, {
        columnId: item.column_id,
        updatedAt: item.updated_at,
      });
    }
    prevItemsRef.current = newSnapshot;

    // Apply new diff states only if actual changes detected
    if (newDiffs.size > 0) {
      queueMicrotask(() => setDiffMap(newDiffs));

      // Clear diff states after animation completes
      const timer = window.setTimeout(() => {
        setDiffMap(EMPTY_DIFF_MAP);
      }, DIFF_ANIMATION_DURATION);

      return () => window.clearTimeout(timer);
    }
  }, [items]);

  return diffMap;
}

interface WorkItemCardProps {
  item: WorkItem;
  projectSlug?: string | null;
  assigneeIndex: Map<string, AssigneeProfile>;
  childTaskCount: number;
  execution?: ExecutionListItem | null;
  onOpen: (itemId: string) => void;
  onStartExecution: (itemId: string) => void;
  onCancelExecution: (itemId: string) => void;
  onCopyId: (itemId: string, displayId: string) => void;
  onRequestDelete: (itemId: string, source: 'keyboard') => void;
  isStartPending: boolean;
  isCancelPending: boolean;
  onDragStart: (event: React.DragEvent, itemId: string) => void;
  onDragEnd: () => void;
  selected: boolean;
  hierarchyHint?: string;
  isExpandable?: boolean;
  isCollapsed?: boolean;
  hierarchyCountLabel?: string;
  onToggleCollapse?: (itemId: string) => void;
  executionAvailable?: boolean;
  /** When true, card renders with reduced opacity (filter non-match / ancestor) */
  isDimmed?: boolean;
  progressRollup?: WorkItemProgressRollup | null;
  /** When true, goal card renders in summarized (compact chip) layout */
  summarized?: boolean;
  /** Phase 4: Diff state for premium animations */
  diffState?: ItemDiffState;
  /** When true, this card is currently being dragged */
  isBeingDragged?: boolean;
  /** When true, this card just landed after drop */
  isJustDropped?: boolean;
  /** Inline assignment: all assignable humans */
  assignableHumans?: AssigneeProfile[];
  /** Inline assignment: all assignable agents */
  assignableAgents?: AssigneeProfile[];
  /** Inline assignment: callback to assign */
  onAssign?: (itemId: string, profile: AssigneeProfile) => void;
  /** Inline assignment: callback to unassign */
  onUnassign?: (itemId: string) => void;
  /** Inline assignment: whether mutation is in flight */
  isAssignPending?: boolean;
}

const WorkItemCard = memo(function WorkItemCard({
  item,
  projectSlug,
  assigneeIndex,
  childTaskCount,
  execution,
  onOpen,
  onStartExecution,
  onCancelExecution,
  onCopyId,
  onRequestDelete,
  isStartPending,
  isCancelPending,
  onDragStart,
  onDragEnd,
  selected,
  hierarchyHint,
  isExpandable,
  isCollapsed,
  hierarchyCountLabel,
  onToggleCollapse,
  executionAvailable = false,
  isDimmed,
  progressRollup,
  summarized,
  diffState,
  isBeingDragged,
  isJustDropped,
  assignableHumans: cardAssignableHumans,
  assignableAgents: cardAssignableAgents,
  onAssign,
  onUnassign,
  isAssignPending,
}: WorkItemCardProps) {
  const label = item.item_type === 'task' ? 'Task' : item.item_type === 'feature' ? 'Feature' : item.item_type === 'bug' ? 'Bug' : 'Goal';
  const labelIcon = typeIcon(item.item_type);
  const draggingRef = React.useRef(false);
  const [compactIdCopied, setCompactIdCopied] = React.useState(false);
  const compactCopyResetRef = React.useRef<number | null>(null);

  // ── Inline assignment popover state ──────────────────────────────────
  const [assignPopoverOpen, setAssignPopoverOpen] = useState(false);
  const [justAssigned, setJustAssigned] = useState(false);
  const justAssignedTimerRef = useRef<number | null>(null);

  const handleAssignPillClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!onAssign) return;
      setAssignPopoverOpen((prev) => !prev);
    },
    [onAssign],
  );

  const handleAssignPillMouseDown = useCallback((e: React.MouseEvent) => {
    // Prevent drag from starting on the pill
    e.stopPropagation();
  }, []);

  const handleInlineAssign = useCallback(
    (profile: AssigneeProfile) => {
      if (!onAssign) return;
      onAssign(item.item_id, profile);
      // Flash animation
      if (justAssignedTimerRef.current) window.clearTimeout(justAssignedTimerRef.current);
      setJustAssigned(true);
      justAssignedTimerRef.current = window.setTimeout(() => {
        setJustAssigned(false);
        justAssignedTimerRef.current = null;
      }, 600);
    },
    [item.item_id, onAssign],
  );

  const handleInlineUnassign = useCallback(() => {
    if (!onUnassign) return;
    onUnassign(item.item_id);
  }, [item.item_id, onUnassign]);

  const handlePopoverClose = useCallback(() => {
    setAssignPopoverOpen(false);
  }, []);

  useEffect(() => {
    return () => {
      if (justAssignedTimerRef.current) window.clearTimeout(justAssignedTimerRef.current);
    };
  }, []);
  const assignee = useMemo(() => {
    if (!item.assignee_id || !item.assignee_type) return null;
    const key = assigneeKey(item.assignee_type, item.assignee_id);
    return assigneeIndex.get(key) ?? null;
  }, [assigneeIndex, item.assignee_id, item.assignee_type]);

  const assigneeLabel = useMemo(() => {
    if (assignee) return assignee.label;
    if (item.assignee_id && item.assignee_type) {
      return item.assignee_type === 'agent'
        ? `Agent ${shortenId(item.assignee_id)}`
        : `Member ${shortenId(item.assignee_id)}`;
    }
    return 'Unassigned';
  }, [assignee, item.assignee_id, item.assignee_type]);

  const assigneeAvatar = useMemo(() => {
    if (!item.assignee_id) return '+';
    if (assignee?.avatar) return assignee.avatar;
    return getInitials(assigneeLabel);
  }, [assignee, assigneeLabel, item.assignee_id]);
  const assigneeActor = useMemo(() => {
    if (assignee?.actor) return assignee.actor;
    if (!item.assignee_id) return null;
    return toActorViewModel(
      { user_id: item.assignee_id, display_name: assigneeLabel, status: item.assignee_type === 'agent' ? 'active' : 'idle' },
      {
        id: item.assignee_id,
        kind: item.assignee_type === 'agent' ? 'agent' : 'human',
        subtitle: item.assignee_type === 'agent' ? 'Agent' : 'Human',
        presenceState: item.assignee_type === 'agent' ? 'working' : 'available',
      },
    );
  }, [assignee, assigneeLabel, item.assignee_id, item.assignee_type]);

  const executionState = useMemo(() => {
    if (!execution?.state) return null;
    return String(execution.state).toLowerCase();
  }, [execution]);
  const showExecutionBadge = executionState === 'running';
  const isActiveExecution =
    executionState === 'running' || executionState === 'paused' || executionState === 'pending';
  const hasAgentAssignment = Boolean(item.assignee_id && item.assignee_type === 'agent');
  // Orphaned assignment: work item references an agent that no longer exists
  const isOrphanedAssignment = hasAgentAssignment && !assignee;
  const canStartExecution = Boolean(executionAvailable && hasAgentAssignment && !isActiveExecution && !isOrphanedAssignment);
  const canCancelExecution = Boolean(executionAvailable && isActiveExecution);
  const showExecutionRow = showExecutionBadge || hasAgentAssignment || isActiveExecution;
  const startButtonTitle = isOrphanedAssignment
    ? 'Assigned agent no longer exists. Please re-assign.'
    : !executionAvailable
      ? 'Execution is unavailable in this deployment'
    : !hasAgentAssignment
      ? 'Assign an agent to enable execution'
      : isActiveExecution
        ? 'Execution already running'
        : 'Start execution';
  const showChildCount = item.item_type === 'feature' && childTaskCount > 0;
  const childCountLabel = `${childTaskCount} task${childTaskCount === 1 ? '' : 's'}`;
  const countLabel = hierarchyCountLabel ?? (showChildCount ? childCountLabel : undefined);
  const countSegments = useMemo(() => (countLabel ? countLabel.split(' · ').filter(Boolean) : []), [countLabel]);
  const hasRolledUpChildren = Boolean(progressRollup && progressRollup.buckets.total > 0);
  const hasProgressRollup =
    Boolean(progressRollup && hasRolledUpChildren && (item.item_type === 'goal' || item.item_type === 'feature'));
  const showRollupChip = Boolean(countLabel || hasProgressRollup);
  const progressPercentValue = hasProgressRollup && progressRollup
    ? Math.min(100, Math.max(0, progressRollup.completion_percent))
    : 0;
  const progressFillWidth = hasProgressRollup
    ? getRollupProgressFillWidth(progressPercentValue)
    : undefined;
  const displayItemId = useMemo(() => formatWorkItemDisplayId(item, projectSlug), [item, projectSlug]);

  const handleOpen = useCallback(() => {
    if (draggingRef.current) return;
    onOpen(item.item_id);
  }, [item.item_id, onOpen]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        e.stopPropagation();
        onRequestDelete(item.item_id, 'keyboard');
        return;
      }
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleOpen();
      }
    },
    [handleOpen, item.item_id, onRequestDelete]
  );

  const handleDragStartInternal = useCallback(
    (e: React.DragEvent) => {
      draggingRef.current = true;
      onDragStart(e, item.item_id);
    },
    [item.item_id, onDragStart]
  );

  const handleDragEndInternal = useCallback(() => {
    window.setTimeout(() => {
      draggingRef.current = false;
    }, 0);
    onDragEnd();
  }, [onDragEnd]);

  const handleStartClick = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      if (!canStartExecution) return;
      onStartExecution(item.item_id);
    },
    [canStartExecution, item.item_id, onStartExecution]
  );

  const handleCancelClick = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      if (!canCancelExecution) return;
      onCancelExecution(item.item_id);
    },
    [canCancelExecution, item.item_id, onCancelExecution]
  );

  const handleToggleCollapse = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      if (!isExpandable || !onToggleCollapse) return;
      onToggleCollapse(item.item_id);
    },
    [isExpandable, item.item_id, onToggleCollapse]
  );

  const handleCopyIdClick = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      onCopyId(item.item_id, displayItemId);
    },
    [item.item_id, displayItemId, onCopyId]
  );

  useEffect(() => {
    return () => {
      if (compactCopyResetRef.current !== null) {
        window.clearTimeout(compactCopyResetRef.current);
      }
    };
  }, []);

  const handleCompactIdCopy = useCallback(
    (event: React.MouseEvent) => {
      event.stopPropagation();
      onCopyId(item.item_id, displayItemId);
      if (compactCopyResetRef.current !== null) {
        window.clearTimeout(compactCopyResetRef.current);
      }
      setCompactIdCopied(false);
      window.requestAnimationFrame(() => {
        setCompactIdCopied(true);
        compactCopyResetRef.current = window.setTimeout(() => {
          setCompactIdCopied(false);
          compactCopyResetRef.current = null;
        }, 1500);
      });
    },
    [item.item_id, displayItemId, onCopyId]
  );

  // Build diff class for premium animations.
  // Suppress diff animations on the card the user just dropped — the
  // optimistic column_id change would otherwise trigger the "moved"
  // animation (translateY + opacity fade) which looks like a stutter on
  // a card the user already placed intentionally.
  const diffClass = diffState && !isJustDropped ? `work-item-card-${diffState}` : '';

  return (
    <div
      className={`work-item-card work-item-card-${item.item_type} ${selected ? 'work-item-card-selected' : ''} ${isDimmed ? 'work-item-dimmed' : ''} ${summarized ? 'work-item-card-summarized' : ''} ${isBeingDragged ? 'work-item-card-dragging' : ''} ${isJustDropped ? 'work-item-card-drop-impact' : ''} ${diffClass} pressable${isJustDropped ? '' : ' animate-fade-in-up'}`}
      draggable
      onDragStart={handleDragStartInternal}
      onDragEnd={handleDragEndInternal}
      onClick={handleOpen}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={`Open ${label}: ${item.title}`}
      aria-current={selected ? 'true' : undefined}
      data-item-id={item.item_id}
      data-position={item.position}
    >
      <div className="work-item-top">
        <div className="work-item-top-left">
          <span className={`work-item-type work-item-type-${item.item_type}`}>
            <span className="work-item-type-icon" aria-hidden="true">
              {labelIcon}
            </span>
            {label}
          </span>
          {showRollupChip && (
            <span
              className={`work-item-rollup-chip-inline${hasProgressRollup ? ' work-item-rollup-chip-inline-progress' : ''}`}
              style={
                hasProgressRollup && progressRollup
                  ? ({
                    ['--rollup-progress' as string]: `${progressPercentValue}%`,
                    ['--rollup-progress-visual' as string]: progressFillWidth,
                  } as React.CSSProperties)
                  : undefined
              }
              aria-label={
                hasProgressRollup && progressRollup
                  ? `${countLabel ? `${countLabel}. ` : ''}${formatProgressPercent(progressRollup.completion_percent)} complete. ${formatRemainingSummary(progressRollup)}`
                  : countLabel
                    ? `${countLabel} roll up under this ${label.toLowerCase()}`
                    : undefined
              }
            >
              {countSegments.length > 0 && (
                <span className="work-item-rollup-chip-inline-count">
                  {countSegments.map((segment) => (
                    <span
                      key={segment}
                      className={`work-item-rollup-chip-inline-segment ${
                        segment.includes('feature')
                          ? 'work-item-rollup-chip-inline-segment-feature'
                          : segment.includes('task')
                            ? 'work-item-rollup-chip-inline-segment-task'
                            : ''
                      }`}
                    >
                      {segment}
                    </span>
                  ))}
                </span>
              )}
              {hasProgressRollup && progressRollup && (
                <span className="work-item-rollup-chip-inline-percent">{formatProgressPercent(progressRollup.completion_percent)}</span>
              )}
            </span>
          )}
        </div>
        {isExpandable && (
          <button
            type="button"
            className={`work-item-hierarchy-toggle pressable ${isCollapsed ? 'work-item-hierarchy-toggle-collapsed' : ''}`}
            onMouseDown={(event) => event.stopPropagation()}
            onClick={handleToggleCollapse}
            aria-expanded={!isCollapsed}
            aria-label={isCollapsed ? `Expand ${label}: ${item.title}` : `Collapse ${label}: ${item.title}`}
            data-haptic="light"
          >
            <span className="work-item-hierarchy-toggle-icon" aria-hidden="true">▾</span>
          </button>
        )}
      </div>
      <div className="work-item-title">{item.title}</div>
      {hierarchyHint && <div className="work-item-hierarchy-hint">{hierarchyHint}</div>}
      {showExecutionRow && (
        <div className="work-item-execution">
          {showExecutionBadge && (
            <ExecutionStatusBadge
              state={executionState ?? 'unknown'}
              phase={execution?.phase ?? null}
              statusLabel={execution ? undefined : isOrphanedAssignment ? 'Invalid' : hasAgentAssignment ? 'Ready' : undefined}
              showPhase={Boolean(execution?.phase)}
              showProgress={false}
              progressPct={execution?.progressPct ?? null}
            />
          )}
          <div className="work-item-execution-actions">
            {hasAgentAssignment && (
              <button
                type="button"
                className="work-item-execution-button pressable"
                onMouseDown={(event) => event.stopPropagation()}
                onClick={handleStartClick}
                disabled={!canStartExecution || isStartPending}
                title={startButtonTitle}
                data-haptic="light"
              >
                {isStartPending ? 'Starting...' : 'Start'}
              </button>
            )}
            {isActiveExecution && (
              <button
                type="button"
                className="work-item-execution-button work-item-execution-cancel pressable"
                onMouseDown={(event) => event.stopPropagation()}
                onClick={handleCancelClick}
                disabled={!canCancelExecution || isCancelPending}
                data-haptic="light"
              >
                {isCancelPending ? 'Cancelling...' : 'Cancel'}
              </button>
            )}
          </div>
        </div>
      )}
      <div className="work-item-assignment" aria-label={`Assignee: ${assigneeLabel}`}>
        <div
          data-inline-assignee-control
          className={`work-item-assignee-pill ${
            item.assignee_type ? `assignee-pill-${item.assignee_type}` : 'assignee-pill-unassigned'
          }${isOrphanedAssignment ? ' assignee-pill-orphaned' : ''}${onAssign ? ' assignee-pill-interactive' : ''}${assignPopoverOpen ? ' assignee-pill-open' : ''}${justAssigned ? ' assignee-pill-just-assigned' : ''}`}
          title={isOrphanedAssignment ? 'Agent no longer exists. Please re-assign.' : onAssign ? 'Click to assign' : undefined}
          role={onAssign ? 'button' : undefined}
          tabIndex={onAssign ? 0 : undefined}
          aria-haspopup={onAssign ? 'dialog' : undefined}
          aria-expanded={onAssign ? assignPopoverOpen : undefined}
          onMouseDown={onAssign ? handleAssignPillMouseDown : undefined}
          onClick={onAssign ? handleAssignPillClick : undefined}
          onKeyDown={onAssign ? (e: React.KeyboardEvent) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              e.stopPropagation();
              setAssignPopoverOpen((prev) => !prev);
            }
          } : undefined}
        >
          <span className="assignee-pill-avatar">
            {assigneeActor ? (
              <ActorAvatar actor={assigneeActor} size="sm" surfaceType="chip" decorative />
            ) : isAvatarImage(assigneeAvatar) ? (
              <img className="assignee-pill-avatar-image" src={assigneeAvatar} alt="" aria-hidden="true" />
            ) : (
              assigneeAvatar
            )}
          </span>
          <span className="assignee-pill-name">{assigneeLabel}</span>
          {/* Only show type label when assigned (avoid duplicate "Unassigned" text) */}
          {item.assignee_type && (
            <span className="assignee-pill-type">
              {isOrphanedAssignment ? '⚠ Missing' : item.assignee_type === 'agent' ? 'Agent' : 'Human'}
            </span>
          )}
        </div>
      </div>
      <div className="work-item-meta">
        <span className="work-item-id-group">
          <span
            className="work-item-id"
            title={item.item_id}
            onMouseDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
          >
            {displayItemId}
          </span>
          <button
            type="button"
            className="work-item-id-copy pressable"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={handleCopyIdClick}
            aria-label={`Copy work item ID ${item.item_id}`}
            title="Copy work item ID"
            data-haptic="light"
          >
            <CopyIcon className="work-item-id-copy-icon" />
          </button>
        </span>
        <span className="work-item-time">{getRelativeTime(item.updated_at)}</span>
      </div>
      {/* Always-visible compact metadata row — exempt from summarized hide rules */}
      <div className="work-item-compact-meta" aria-label={`${displayItemId} · ${assigneeLabel}`}>
        <button
          type="button"
          className={`compact-meta-id-btn pressable${compactIdCopied ? ' compact-meta-id-copied' : ''}`}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={handleCompactIdCopy}
          aria-label={`Copy ${displayItemId}`}
          title="Copy work item ID"
          data-haptic="light"
        >
          <span className="compact-meta-id-content">
            <span className="compact-meta-id-label">
              {displayItemId}
              <CopyIcon className="compact-meta-id-icon" />
            </span>
            <span className="compact-meta-id-status" aria-hidden="true">
              <span className="compact-meta-id-status-dot" />
              Copied
            </span>
          </span>
        </button>
        <span
          data-inline-assignee-control
          className={`compact-meta-assignee ${
            item.assignee_type ? `compact-meta-assignee-${item.assignee_type}` : 'compact-meta-assignee-unassigned'
          }${isOrphanedAssignment ? ' compact-meta-assignee-orphaned' : ''}${onAssign ? ' compact-meta-assignee-interactive' : ''}${assignPopoverOpen ? ' compact-meta-assignee-open' : ''}${justAssigned ? ' compact-meta-assignee-just-assigned' : ''}`}
          title={isOrphanedAssignment ? 'Agent no longer exists' : assigneeLabel}
          role={onAssign ? 'button' : undefined}
          tabIndex={onAssign ? 0 : undefined}
          onMouseDown={onAssign ? handleAssignPillMouseDown : undefined}
          onClick={onAssign ? handleAssignPillClick : undefined}
          onKeyDown={onAssign ? (e: React.KeyboardEvent) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              e.stopPropagation();
              setAssignPopoverOpen((prev) => !prev);
            }
          } : undefined}
        >
          <span className="compact-meta-avatar">
            {assigneeActor ? (
              <ActorAvatar actor={assigneeActor} size="sm" surfaceType="chip" decorative />
            ) : isAvatarImage(assigneeAvatar) ? (
              <img className="compact-meta-avatar-img" src={assigneeAvatar} alt="" aria-hidden="true" />
            ) : (
              assigneeAvatar
            )}
          </span>
          <span className="compact-meta-name">{assigneeLabel}</span>
        </span>
      </div>
      {/* Popover lives here (not inside .work-item-assignment) so it stays visible when
          compact density or summarized goals hide the assignment row via CSS. */}
      {assignPopoverOpen && onAssign ? (
        <div className="work-item-inline-assignee-popover">
          <InlineAssigneePopover
            assignableHumans={cardAssignableHumans ?? []}
            assignableAgents={cardAssignableAgents ?? []}
            currentAssignee={assignee}
            onAssign={handleInlineAssign}
            onUnassign={handleInlineUnassign}
            onClose={handlePopoverClose}
            isPending={isAssignPending}
          />
        </div>
      ) : null}
    </div>
  );
});

// ---------------------------------------------------------------------------
// ColumnLaneHeader — Memoised header with compose form, isolated from
// card-rendering so execution-polling / diff-map updates cannot block typing.
// ---------------------------------------------------------------------------

interface ColumnLaneHeaderProps {
  column: BoardColumn;
  onCreate: (
    columnId: string,
    title: string,
    itemType: WorkItemType,
    options?: { priority?: WorkItemPriority },
    onCreated?: (itemId: string) => void,
  ) => void;
  hasExpandableItems: boolean;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  boardId?: string;
  assignableHumans: AssigneeProfile[];
  assignableAgents: AssigneeProfile[];
  currentUserId: string | null;
  onOpen: (itemId: string) => void;
}

const ColumnLaneHeader = memo(function ColumnLaneHeader({
  column,
  onCreate,
  hasExpandableItems,
  onExpandAll,
  onCollapseAll,
  boardId,
  assignableHumans,
  assignableAgents,
  currentUserId,
  onOpen,
}: ColumnLaneHeaderProps) {
  const [draft, setDraft] = useState('');
  const [itemType, setItemType] = useState<WorkItemType>('task');
  const [priorityDraft, setPriorityDraft] = useState<WorkItemPriority>('medium');
  const [composing, setComposing] = useState(false);
  const [autoOpenAfterCreate, setAutoOpenAfterCreate] = useState(false);
  const [pendingDueDate, setPendingDueDate] = useState<QuickDueDateOption | null>(null);
  const composeInputRef = useRef<HTMLInputElement>(null);

  // Pre-create assignment: user picks assignee before submitting
  const [pendingAssignment, setPendingAssignment] = useState<{ id: string; type: 'user' | 'agent'; label: string } | null>(null);

  // Post-create quick-action state
  const [lastCreatedItemId, setLastCreatedItemId] = useState<string | null>(null);
  const [showAssigneePicker, setShowAssigneePicker] = useState(false);
  const [assigneeSearch, setAssigneeSearch] = useState('');
  const assignSearchRef = useRef<HTMLInputElement>(null);
  const quickActionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const assignItem = useAssignWorkItem(boardId);
  const updateItem = useUpdateWorkItem(boardId);

  const dismissQuickActions = useCallback(() => {
    setLastCreatedItemId(null);
    setShowAssigneePicker(false);
    setAssigneeSearch('');
    if (quickActionTimerRef.current) {
      clearTimeout(quickActionTimerRef.current);
      quickActionTimerRef.current = null;
    }
  }, []);

  const clearPendingAssignment = useCallback(() => {
    setPendingAssignment(null);
    setShowAssigneePicker(false);
    setAssigneeSearch('');
  }, []);

  const handleSubmit = useCallback(() => {
    const title = draft.trim();
    if (!title) return;
    dismissQuickActions();
    const preAssignment = pendingAssignment;
    const preDueDate = pendingDueDate;
    const shouldAutoOpen = autoOpenAfterCreate;
    onCreate(column.column_id, title, itemType, { priority: priorityDraft }, (createdId) => {
      // Auto-assign if user pre-selected an assignee
      if (preAssignment) {
        assignItem.mutate({
          itemId: createdId,
          assigneeId: preAssignment.id,
          assigneeType: preAssignment.type,
        });
      }

      if (preDueDate) {
        updateItem.mutate({
          itemId: createdId,
          patch: { due_date: quickDueDateValue(preDueDate) },
        });
      }

      if (shouldAutoOpen) {
        onOpen(createdId);
      }

      setLastCreatedItemId(createdId);
      // Auto-dismiss post-create actions after 12 seconds if user doesn't interact
      quickActionTimerRef.current = setTimeout(() => {
        setLastCreatedItemId(null);
        setShowAssigneePicker(false);
        setAssigneeSearch('');
      }, 12_000);
    });
    setDraft('');
    setPriorityDraft('medium');
    setPendingDueDate(null);
    setAutoOpenAfterCreate(false);
  }, [
    assignItem,
    autoOpenAfterCreate,
    column.column_id,
    dismissQuickActions,
    draft,
    itemType,
    onCreate,
    onOpen,
    pendingAssignment,
    pendingDueDate,
    priorityDraft,
    updateItem,
  ]);

  const handleAssignToMe = useCallback(() => {
    if (!currentUserId) return;
    if (lastCreatedItemId) {
      // Post-create: immediate assign
      assignItem.mutate({
        itemId: lastCreatedItemId,
        assigneeId: currentUserId,
        assigneeType: 'user',
      });
      dismissQuickActions();
    } else {
      // Pre-create: toggle pending assignment
      if (pendingAssignment?.id === currentUserId) {
        setPendingAssignment(null);
      } else {
        const me = assignableHumans.find((p) => p.id === currentUserId);
        setPendingAssignment({ id: currentUserId, type: 'user', label: me?.label ?? 'Me' });
        setShowAssigneePicker(false);
        setAssigneeSearch('');
      }
    }
  }, [assignItem, assignableHumans, currentUserId, dismissQuickActions, lastCreatedItemId, pendingAssignment]);

  const handleAssignTo = useCallback(
    (profile: AssigneeProfile) => {
      if (lastCreatedItemId) {
        // Post-create: immediate assign
        assignItem.mutate({
          itemId: lastCreatedItemId,
          assigneeId: profile.id,
          assigneeType: profile.type,
        });
        dismissQuickActions();
      } else {
        // Pre-create: set pending assignment
        setPendingAssignment({ id: profile.id, type: profile.type, label: profile.label });
        setShowAssigneePicker(false);
        setAssigneeSearch('');
      }
    },
    [assignItem, dismissQuickActions, lastCreatedItemId]
  );

  const handleOpenDetails = useCallback(() => {
    if (!lastCreatedItemId) return;
    onOpen(lastCreatedItemId);
    dismissQuickActions();
  }, [dismissQuickActions, lastCreatedItemId, onOpen]);

  const magicSummary = useMemo(() => {
    const details: string[] = [];
    details.push(`${priorityDraft} priority`);
    if (pendingAssignment?.label) details.push(`assigned to ${pendingAssignment.label}`);
    if (pendingDueDate) details.push(`due ${quickDueDateLabel(pendingDueDate).toLowerCase()}`);
    if (autoOpenAfterCreate) details.push('opening instantly');
    return `Shape a ${itemType} with ${joinNatural(details)}.`;
  }, [autoOpenAfterCreate, itemType, pendingAssignment, pendingDueDate, priorityDraft]);

  const hasMagicSummary = useMemo(
    () =>
      itemType !== 'task' ||
      priorityDraft !== 'medium' ||
      Boolean(pendingAssignment) ||
      Boolean(pendingDueDate) ||
      autoOpenAfterCreate,
    [autoOpenAfterCreate, itemType, pendingAssignment, pendingDueDate, priorityDraft],
  );

  const handleToggleCompose = useCallback(() => {
    setComposing((current) => {
      const next = !current;
      if (!next) {
        dismissQuickActions();
        setDraft('');
        setPendingAssignment(null);
        setPendingDueDate(null);
        setPriorityDraft('medium');
        setAutoOpenAfterCreate(false);
      }
      return next;
    });
  }, [dismissQuickActions]);

  const filteredHumans = useMemo(() => {
    if (!assigneeSearch.trim()) return assignableHumans;
    const q = assigneeSearch.toLowerCase();
    return assignableHumans.filter(
      (p) => p.label.toLowerCase().includes(q) || p.subtitle?.toLowerCase().includes(q)
    );
  }, [assignableHumans, assigneeSearch]);

  const filteredAgents = useMemo(() => {
    if (!assigneeSearch.trim()) return assignableAgents;
    const q = assigneeSearch.toLowerCase();
    return assignableAgents.filter(
      (p) => p.label.toLowerCase().includes(q) || p.subtitle?.toLowerCase().includes(q)
    );
  }, [assignableAgents, assigneeSearch]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSubmit();
      }
      if (e.key === 'Escape') {
        if (showAssigneePicker) {
          setShowAssigneePicker(false);
          setAssigneeSearch('');
        } else if (lastCreatedItemId) {
          dismissQuickActions();
        } else {
          setComposing(false);
          setDraft('');
          setPendingAssignment(null);
          setPendingDueDate(null);
          setPriorityDraft('medium');
          setAutoOpenAfterCreate(false);
        }
      }
    },
    [dismissQuickActions, handleSubmit, lastCreatedItemId, showAssigneePicker]
  );

  useEffect(() => {
    if (composing) {
      requestAnimationFrame(() => composeInputRef.current?.focus());
    }
  }, [composing]);

  useEffect(() => {
    if (showAssigneePicker) {
      requestAnimationFrame(() => assignSearchRef.current?.focus());
    }
  }, [showAssigneePicker]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (quickActionTimerRef.current) clearTimeout(quickActionTimerRef.current);
    };
  }, []);

  return (
    <header className="board-column-header">
      <div className="board-column-title-row">
        <h2 className="board-column-title">{column.name}</h2>
        <div className="board-column-title-actions">
          {hasExpandableItems && (
            <>
              <button
                type="button"
                className="board-column-hierarchy-action pressable"
                onClick={onExpandAll}
                aria-label={`Expand all in ${column.name}`}
                title="Expand all"
              >
                ⊞
              </button>
              <button
                type="button"
                className="board-column-hierarchy-action pressable"
                onClick={onCollapseAll}
                aria-label={`Collapse all in ${column.name}`}
                title="Collapse all"
              >
                ⊟
              </button>
            </>
          )}
          <button
            type="button"
            className={`board-column-add-trigger pressable ${composing ? 'active' : ''}`}
            onClick={handleToggleCompose}
            data-haptic="light"
            aria-label={`Add item to ${column.name}`}
            aria-expanded={composing}
            title="Add item"
          >
            +
          </button>
        </div>
      </div>
      <div className="board-column-hierarchy-legend" aria-label="Hierarchy legend">
        <span className="hierarchy-legend-chip hierarchy-legend-goal">◆ Goal</span>
        <span className="hierarchy-legend-chip hierarchy-legend-feature">◇ Feature</span>
        <span className="hierarchy-legend-chip hierarchy-legend-task">• Task</span>
      </div>
      {composing && (
      <div className={`board-column-compose board-column-compose-${itemType}`} onKeyDown={onKeyDown}>
        <div className="board-compose-shell">
        {hasMagicSummary && <div className="board-compose-summary">{magicSummary}</div>}
        <div className="board-compose-row">
          <select
            className="board-compose-type"
            value={itemType}
            onChange={(e) => setItemType(e.target.value as WorkItemType)}
            aria-label="Work item type"
          >
            <option value="task">Task</option>
            <option value="feature">Feature</option>
            <option value="goal">Goal</option>
            <option value="bug">Bug</option>
          </select>
          <input
            ref={composeInputRef}
            className="board-compose-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Work item title (e.g. Improve onboarding flow)"
            aria-label={`Add item to ${column.name}`}
            autoComplete="off"
          />
        </div>
        <div className="board-compose-hint">⌘/Ctrl + Enter to launch · Esc to close</div>

        {/* Quick-action strip — always visible when composing */}
        <div className="board-compose-quick-actions" aria-label="Quick actions">
          <div className="board-compose-qa-meta" aria-live="polite">
            {pendingAssignment && !lastCreatedItemId && (
              <div className="board-compose-pending-chip" aria-label={`Will assign to ${pendingAssignment.label}`}>
                <span className="board-compose-pending-label">Assigned → {pendingAssignment.label}</span>
                <button
                  type="button"
                  className="board-compose-pending-clear pressable"
                  onClick={clearPendingAssignment}
                  aria-label="Clear assignment"
                  data-haptic="light"
                >
                  ✕
                </button>
              </div>
            )}
            {pendingDueDate && !lastCreatedItemId && (
              <div className="board-compose-pending-chip" aria-label={`Will set due date to ${quickDueDateLabel(pendingDueDate)}`}>
                <span className="board-compose-pending-label">Due → {quickDueDateLabel(pendingDueDate)}</span>
                <button
                  type="button"
                  className="board-compose-pending-clear pressable"
                  onClick={() => setPendingDueDate(null)}
                  aria-label="Clear due date"
                  data-haptic="light"
                >
                  ✕
                </button>
              </div>
            )}
            {autoOpenAfterCreate && !lastCreatedItemId && (
              <div className="board-compose-pending-chip" aria-label="Will open the item after creating it">
                <span className="board-compose-pending-label">Open drawer after create</span>
                <button
                  type="button"
                  className="board-compose-pending-clear pressable"
                  onClick={() => setAutoOpenAfterCreate(false)}
                  aria-label="Disable open after create"
                  data-haptic="light"
                >
                  ✕
                </button>
              </div>
            )}
          </div>
          <div className="board-compose-qa-row">
            <button
              type="button"
              className="board-compose-add pressable"
              onClick={handleSubmit}
              disabled={!draft.trim()}
              data-haptic="light"
              aria-label={`Create in ${column.name}`}
            >
              <span className="board-compose-add-text">Add</span>
            </button>
            {currentUserId && (
              <button
                type="button"
                className={`board-compose-qa-btn board-compose-qa-assign-me pressable${pendingAssignment?.id === currentUserId ? ' active' : ''}`}
                onClick={handleAssignToMe}
                data-haptic="light"
                aria-label="Assign to me"
              >
                <span className="board-compose-qa-icon">◎</span> Me
              </button>
            )}
            <button
              type="button"
              className={`board-compose-qa-btn board-compose-qa-assign pressable${showAssigneePicker ? ' active' : ''}`}
              onClick={() => setShowAssigneePicker((v) => !v)}
              data-haptic="light"
              aria-label="Pick assignee"
              aria-expanded={showAssigneePicker}
            >
              <span className="board-compose-qa-icon">＋</span> Assign
            </button>
            {!lastCreatedItemId && (
              <button
                type="button"
                className={`board-compose-qa-btn pressable${autoOpenAfterCreate ? ' active' : ''}`}
                onClick={() => setAutoOpenAfterCreate((current) => !current)}
                data-haptic="light"
                aria-pressed={autoOpenAfterCreate}
                aria-label="Open drawer after creating item"
              >
                <span className="board-compose-qa-icon">↗</span> Open after
              </button>
            )}
            {lastCreatedItemId && (
              <button
                type="button"
                className="board-compose-qa-btn board-compose-qa-open pressable"
                onClick={handleOpenDetails}
                data-haptic="light"
                aria-label="Open item details"
              >
                <span className="board-compose-qa-icon">↗</span> Open
              </button>
            )}
            {lastCreatedItemId && (
              <button
                type="button"
                className="board-compose-qa-dismiss pressable"
                onClick={dismissQuickActions}
                aria-label="Dismiss quick actions"
                data-haptic="light"
              >
                ✕
              </button>
            )}
          </div>

          {!lastCreatedItemId && (
            <div className="board-compose-qa-section" aria-label="Priority quick actions">
              <span className="board-compose-qa-section-label">Priority</span>
              <div className="board-compose-qa-pill-row">
                {(['low', 'medium', 'high', 'critical'] as WorkItemPriority[]).map((priority) => (
                  <button
                    key={priority}
                    type="button"
                    className={`board-compose-qa-pill board-compose-qa-pill-${priority} pressable${priorityDraft === priority ? ' active' : ''}`}
                    onClick={() => setPriorityDraft(priority)}
                    data-haptic="light"
                    aria-pressed={priorityDraft === priority}
                  >
                    {priority}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!lastCreatedItemId && (
            <div className="board-compose-qa-section" aria-label="Due date quick actions">
              <span className="board-compose-qa-section-label">Due</span>
              <div className="board-compose-qa-pill-row">
                {(['today', 'tomorrow', 'next-week'] as QuickDueDateOption[]).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`board-compose-qa-pill pressable${pendingDueDate === option ? ' active' : ''}`}
                    onClick={() => setPendingDueDate((current) => (current === option ? null : option))}
                    data-haptic="light"
                    aria-pressed={pendingDueDate === option}
                  >
                    {quickDueDateLabel(option)}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Mini assignee picker dropdown */}
          {showAssigneePicker && (
              <div className="board-compose-assignee-picker" role="listbox" aria-label="Pick assignee">
                <input
                  ref={assignSearchRef}
                  className="board-compose-assignee-search"
                  value={assigneeSearch}
                  onChange={(e) => setAssigneeSearch(e.target.value)}
                  placeholder="Search…"
                  aria-label="Search assignees"
                  autoComplete="off"
                />
                {filteredHumans.length > 0 && (
                  <div className="board-compose-assignee-group">
                    <div className="board-compose-assignee-group-title">People</div>
                    {filteredHumans.map((profile) => (
                      <button
                        key={`user-${profile.id}`}
                        type="button"
                        className="board-compose-assignee-option pressable"
                        onClick={() => handleAssignTo(profile)}
                        role="option"
                        aria-label={`Assign to ${profile.label}`}
                        data-haptic="light"
                      >
                        <span className="board-compose-assignee-avatar">
                          {profile.actor ? (
                            <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                          ) : (
                            profile.avatar ?? getInitials(profile.label)
                          )}
                        </span>
                        <span className="board-compose-assignee-text">
                          <span className="board-compose-assignee-name">{profile.label}</span>
                          <span className="board-compose-assignee-sub">{profile.subtitle ?? 'Human'}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {filteredAgents.length > 0 && (
                  <div className="board-compose-assignee-group">
                    <div className="board-compose-assignee-group-title">Agents</div>
                    {filteredAgents.map((profile) => (
                      <button
                        key={`agent-${profile.id}`}
                        type="button"
                        className="board-compose-assignee-option pressable"
                        onClick={() => handleAssignTo(profile)}
                        role="option"
                        aria-label={`Assign to ${profile.label}`}
                        data-haptic="light"
                      >
                        <span className="board-compose-assignee-avatar">
                          {profile.actor ? (
                            <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                          ) : (
                            profile.avatar ?? getInitials(profile.label)
                          )}
                        </span>
                        <span className="board-compose-assignee-text">
                          <span className="board-compose-assignee-name">{profile.label}</span>
                          <span className="board-compose-assignee-sub">{profile.subtitle ?? 'Agent'}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {filteredHumans.length === 0 && filteredAgents.length === 0 && (
                  <div className="board-compose-assignee-empty">
                    {assigneeSearch.trim() ? 'No matches.' : 'No assignees available.'}
                  </div>
                )}
              </div>
            )}

            <div className="sr-only" aria-live="polite">
              Quick create actions available
            </div>
          </div>
        </div>
      </div>
      )}
    </header>
  );
});

// ---------------------------------------------------------------------------
// ColumnLane
// ---------------------------------------------------------------------------

interface ColumnLaneProps {
  column: BoardColumn;
  accentIndex: number;
  items: WorkItem[];
  assigneeIndex: Map<string, AssigneeProfile>;
  executionByItemId: Map<string, ExecutionListItem>;
  executionAvailable: boolean;
  childTaskCountByParent: Map<string, number>;
  featureCountByGoal: Map<string, number>;
  taskCountByGoal: Map<string, number>;
  progressByItemId: Map<string, WorkItemProgressRollup>;
  onCreate: (
    columnId: string,
    title: string,
    itemType: WorkItemType,
    options?: { priority?: WorkItemPriority },
    onCreated?: (itemId: string) => void,
  ) => void;
  onOpen: (itemId: string) => void;
  onStartExecution: (itemId: string) => void;
  onCancelExecution: (itemId: string) => void;
  onCopyWorkItemId: (itemId: string, displayId: string) => void;
  onRequestDelete: (itemId: string, source: 'keyboard' | 'drag') => void;
  isStartPending: boolean;
  isCancelPending: boolean;
  onDropToColumn: (columnId: string, itemId: string) => void;
  onDragStart: (event: React.DragEvent, itemId: string) => void;
  onDragEnd: () => void;
  onMoveToPosition: (itemId: string, columnId: string, position: number) => void;
  onReorderColumn: (columnId: string, orderedItemIds: string[]) => void;
  draggedItemId?: string | null;
  justDroppedItemId?: string | null;
  selectedItemId?: string;
  projectSlug?: string | null;
  boardId?: string;
  assignableHumans: AssigneeProfile[];
  assignableAgents: AssigneeProfile[];
  currentUserId: string | null;
  /** Set of item IDs that match the active filter */
  matchingIds?: Set<string>;
  /** Set of ancestor IDs that should be dimmed but visible */
  ancestorIds?: Set<string>;
  /** Whether any filter is currently active */
  isFiltered?: boolean;
  /** Phase 1: Show skeleton cards while items are loading */
  itemsLoading?: boolean;
  /** Phase 4: Map of item IDs to diff states for premium animations */
  itemDiffMap?: ItemDiffMap;
  /** When true, skip column virtualization until full hydration to avoid layout gaps */
  deferColumnVirtualization?: boolean;
}

function loadCollapsedSet(boardColumnId: string): Set<string> | null {
  try {
    const primaryKey = `amprealize:collapsed:${boardColumnId}`;
    const legacyKey = `amprealize:collapsed:${boardColumnId}`;
    const raw =
      localStorage.getItem(primaryKey) ?? localStorage.getItem(legacyKey);
    if (!raw) return null; // No user preference yet — caller decides defaults
    const arr = JSON.parse(raw) as unknown;
    return Array.isArray(arr) ? new Set(arr.filter((v): v is string => typeof v === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

function saveCollapsedSet(boardColumnId: string, collapsed: Set<string>) {
  try {
    const key = `amprealize:collapsed:${boardColumnId}`;
    localStorage.setItem(key, JSON.stringify([...collapsed]));
    localStorage.removeItem(`amprealize:collapsed:${boardColumnId}`);
  } catch { /* quota exceeded — ignore */ }
}

type ViewMode = 'board' | 'outline';

interface PendingBoardDelete {
  rootItemId: string;
  rootTitle: string;
  rootType: WorkItemType;
  hiddenIds: string[];
  source: 'drag' | 'keyboard';
}

// ColumnSummaryStrip extracted to ./ColumnSummaryStrip.tsx

const ColumnLane = memo(function ColumnLane({
  column,
  accentIndex,
  items,
  assigneeIndex,
  executionByItemId,
  executionAvailable,
  childTaskCountByParent,
  featureCountByGoal,
  taskCountByGoal,
  progressByItemId,
  onCreate,
  onOpen,
  onStartExecution,
  onCancelExecution,
  onCopyWorkItemId,
  onRequestDelete,
  isStartPending,
  isCancelPending,
  onDropToColumn,
  onDragStart,
  onDragEnd,
  onMoveToPosition,
  onReorderColumn,
  draggedItemId,
  justDroppedItemId,
  selectedItemId,
  projectSlug,
  boardId,
  assignableHumans,
  assignableAgents,
  currentUserId,
  matchingIds,
  ancestorIds,
  isFiltered,
  itemsLoading,
  itemDiffMap,
  deferColumnVirtualization = false,
}: ColumnLaneProps) {
  // ── Inline assignment hooks ──────────────────────────────────────────
  const assignItemMutation = useAssignWorkItem(boardId);
  const unassignItemMutation = useUnassignWorkItem(boardId);
  const renderItems = useMemo(
    () => Array.from(new Map(items.map((item) => [item.item_id, item])).values()),
    [items],
  );

  const handleCardAssign = useCallback(
    (itemId: string, profile: AssigneeProfile) => {
      assignItemMutation.mutate({
        itemId,
        assigneeId: profile.id,
        assigneeType: profile.type as 'user' | 'agent',
      });
    },
    [assignItemMutation],
  );

  const handleCardUnassign = useCallback(
    (itemId: string) => {
      unassignItemMutation.mutate({ itemId });
    },
    [unassignItemMutation],
  );

  const isAssignPending = assignItemMutation.isPending || unassignItemMutation.isPending;

  const [isOver, setIsOver] = useState(false);
  const isOverRef = useRef(false);
  const dragDepthRef = useRef(0);
  const dropIndexRef = useRef<number | null>(null);
  const columnItemsRef = useRef<HTMLDivElement>(null);
  const shiftedCardIdsRef = useRef<Set<string>>(new Set());
  const rafRef = useRef<number | null>(null);
  const lastClientYRef = useRef(0);
  const lastPointerYRef = useRef(0);
  const lastFrameTsRef = useRef(0);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    const stored = loadCollapsedSet(column.column_id);
    if (stored !== null) return stored;
    // First visit: default-collapse expandable items
    const defaultCollapsed = new Set<string>();
    for (const item of renderItems) {
      const hasChildren = renderItems.some((child) => child.parent_id === item.item_id);
      if (!hasChildren) continue;
      // Always collapse goals with children
      if (item.item_type === 'goal') defaultCollapsed.add(item.item_id);
      // Also collapse features with children
      if (item.item_type === 'feature') defaultCollapsed.add(item.item_id);
      // Auto-collapse completed branches
      if (item.status === 'done') defaultCollapsed.add(item.item_id);
    }
    return defaultCollapsed;
  });

  const clearShiftedCards = useCallback(() => {
    const container = columnItemsRef.current;
    if (!container) {
      shiftedCardIdsRef.current.clear();
      return;
    }
    if (shiftedCardIdsRef.current.size === 0) return;
    shiftedCardIdsRef.current.forEach((slotId) => {
      const slot = container.querySelector<HTMLElement>(`[data-dnd-slot="true"][data-item-id="${slotId}"]`);
      if (slot) {
        slot.classList.remove('dnd-slot-shifted', 'dnd-slot-shifted-up', 'dnd-slot-shifted-down');
        slot.style.removeProperty('--slot-shift-boost');
      }
    });
    shiftedCardIdsRef.current.clear();
  }, []);

  useEffect(() => {
    if (draggedItemId) return;
    dragDepthRef.current = 0;
    isOverRef.current = false;
    queueMicrotask(() => setIsOver(false));
    dropIndexRef.current = null;
    lastPointerYRef.current = 0;
    lastFrameTsRef.current = 0;
    clearShiftedCards();
  }, [draggedItemId, clearShiftedCards]);

  const toggleCollapse = useCallback((itemId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      saveCollapsedSet(column.column_id, next);
      return next;
    });
  }, [column.column_id]);

  // Set of item IDs that have children (i.e. are expandable/collapsible)
  const expandableIds = useMemo(() => {
    const ids = new Set<string>();
    for (const item of renderItems) {
      if (item.parent_id && renderItems.some((p) => p.item_id === item.parent_id)) {
        ids.add(item.parent_id);
      }
    }
    return ids;
  }, [renderItems]);

  const collapseAll = useCallback(() => {
    setCollapsed(() => {
      const next = new Set(expandableIds);
      saveCollapsedSet(column.column_id, next);
      return next;
    });
  }, [column.column_id, expandableIds]);

  const expandAll = useCallback(() => {
    setCollapsed(() => {
      const next = new Set<string>();
      saveCollapsedSet(column.column_id, next);
      return next;
    });
  }, [column.column_id]);

  // Auto-collapse items when they transition to done
  const prevDoneRef = useRef<Set<string> | null>(null);
  useEffect(() => {
    const currentDone = new Set(
      renderItems.filter((i) => (i.status === 'done') && expandableIds.has(i.item_id)).map((i) => i.item_id)
    );
    if (prevDoneRef.current !== null) {
      const newlyDone: string[] = [];
      currentDone.forEach((id) => {
        if (!prevDoneRef.current!.has(id)) newlyDone.push(id);
      });
      if (newlyDone.length > 0) {
        queueMicrotask(() =>
          setCollapsed((prev) => {
            const next = new Set(prev);
            for (const id of newlyDone) next.add(id);
            saveCollapsedSet(column.column_id, next);
            return next;
          }),
        );
      }
    }
    prevDoneRef.current = currentDone;
  }, [renderItems, expandableIds, column.column_id]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (!isOverRef.current) {
      isOverRef.current = true;
      setIsOver(true);
    }

    // Always capture the latest cursor position so the RAF reads the
    // most recent value, not the one from the event that scheduled it.
    lastClientYRef.current = e.clientY;

    // Throttle hit-testing to animation frames for 60fps
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const container = columnItemsRef.current;
      if (!container) return;

      // ── Top-level slots: each is a .hierarchy-group or root .hierarchy-node ──
      // These are the direct children of the column that have data-item-id.
      // Shifting at the slot level moves entire groups (goal + children) as a unit.
      const allSlots = container.querySelectorAll<HTMLElement>('[data-dnd-slot="true"][data-item-id]');
      const slots: HTMLElement[] = [];
      for (let i = 0; i < allSlots.length; i++) {
        if (allSlots[i].offsetHeight > 0) slots.push(allSlots[i]);
      }

      if (slots.length === 0) {
        // Empty column — drop at position 0 (top)
        dropIndexRef.current = 0;
        return;
      }

      const mouseY = lastClientYRef.current;
      const nowTs = performance.now();
      if (lastPointerYRef.current === 0) {
        lastPointerYRef.current = mouseY;
      }
      const dt = lastFrameTsRef.current > 0 ? Math.max(1, nowTs - lastFrameTsRef.current) : 16;
      const dy = mouseY - lastPointerYRef.current;
      const pointerVelocity = Math.abs(dy) / dt;
      lastPointerYRef.current = mouseY;
      lastFrameTsRef.current = nowTs;

      // ── Hit-test against slot midpoints ──
      let slotInsertIdx = slots.length;
      for (let i = 0; i < slots.length; i++) {
        const rect = slots[i].getBoundingClientRect();
        const midY = rect.top + rect.height / 2;
        if (mouseY < midY) {
          slotInsertIdx = i;
          break;
        }
      }

      // ── Convert slot index → flat item index for handleDrop ──
      const allNodes = container.querySelectorAll<HTMLElement>('.hierarchy-node[data-item-id]');
      const flatIds: string[] = [];
      for (let i = 0; i < allNodes.length; i++) {
        if (allNodes[i].offsetHeight > 0) {
          const id = allNodes[i].getAttribute('data-item-id');
          if (id) flatIds.push(id);
        }
      }
      if (slotInsertIdx < slots.length) {
        const slotId = slots[slotInsertIdx].getAttribute('data-item-id');
        const itemIdx = slotId ? flatIds.indexOf(slotId) : flatIds.length;
        dropIndexRef.current = itemIdx >= 0 ? itemIdx : flatIds.length;
      } else {
        dropIndexRef.current = flatIds.length;
      }

      // ── Group-level displacement ──
      const draggedId = draggedItemId;
      const shiftBoostPx = Math.min(8, Math.max(0, pointerVelocity * 14));

      // Find the dragged item's top-level slot (to exclude from shifting)
      let draggedSlotId: string | null = null;
      let draggedSlotIdx = -1;
      if (draggedId) {
        const draggedNode = container.querySelector<HTMLElement>(`.hierarchy-node[data-item-id="${draggedId}"]`);
        if (draggedNode) {
          let el: HTMLElement = draggedNode;
          while (el.parentElement && el.parentElement !== container) {
            el = el.parentElement;
          }
          if (el.parentElement === container) {
            draggedSlotId = el.getAttribute('data-item-id');
          }
        }
      }

      const slotIds = slots
        .map((s) => s.getAttribute('data-item-id'))
        .filter((id): id is string => Boolean(id));

      if (draggedSlotId) {
        draggedSlotIdx = slotIds.indexOf(draggedSlotId);
      }

      let slotShiftStart = slotInsertIdx;
      if (draggedSlotId) {
        if (draggedSlotIdx >= 0 && slotInsertIdx > draggedSlotIdx) {
          slotShiftStart = slotInsertIdx - 1;
        }
      }

      const nextShifted = new Set<string>();
      for (let i = 0; i < slots.length; i++) {
        const id = slots[i].getAttribute('data-item-id');
        if (!id || id === draggedSlotId) continue;
        if (i >= slotShiftStart) nextShifted.add(id);
      }

      // Remove slots no longer shifted.
      shiftedCardIdsRef.current.forEach((slotId) => {
        if (!nextShifted.has(slotId)) {
          const slot = container.querySelector<HTMLElement>(`[data-dnd-slot="true"][data-item-id="${slotId}"]`);
          if (slot) {
            slot.classList.remove('dnd-slot-shifted', 'dnd-slot-shifted-up', 'dnd-slot-shifted-down');
            slot.style.removeProperty('--slot-shift-boost');
          }
        }
      });

      // Add newly shifted slots.
      // Direction: each slot shifts toward the dragged item's original
      // position (i.e. into the gap it left). Slots below the origin
      // shift up; slots above the origin shift down.
      nextShifted.forEach((slotId) => {
        const slot = container.querySelector<HTMLElement>(`[data-dnd-slot="true"][data-item-id="${slotId}"]`);
        if (!slot) return;

        const slotIdx = slotIds.indexOf(slotId);
        const shiftDir = (draggedSlotIdx >= 0 && slotIdx < draggedSlotIdx) ? 'down' : 'up';
        const dirClass = shiftDir === 'down' ? 'dnd-slot-shifted-down' : 'dnd-slot-shifted-up';
        const oppClass = shiftDir === 'down' ? 'dnd-slot-shifted-up' : 'dnd-slot-shifted-down';

        if (!shiftedCardIdsRef.current.has(slotId)) {
          slot.classList.add('dnd-slot-shifted');
        }
        slot.classList.remove(oppClass);
        slot.classList.add(dirClass);
        slot.style.setProperty('--slot-shift-boost', `${shiftBoostPx.toFixed(2)}px`);
      });

      shiftedCardIdsRef.current = nextShifted;
    });
  }, [draggedItemId]);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragDepthRef.current += 1;
    if (!isOverRef.current) {
      isOverRef.current = true;
      setIsOver(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    const related = e.relatedTarget as Node | null;
    const section = e.currentTarget as HTMLElement;

    // Leaving to a descendant: ignore.
    if (related && section.contains(related)) return;

    // Track nested dragenter/dragleave transitions to avoid flicker
    // when crossing child nodes inside the same lane.
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current > 0) return;

    // Some browsers report relatedTarget as null while still inside the
    // element during drag. Fall back to pointer bounds check.
    const rect = section.getBoundingClientRect();
    const isPointerInside =
      e.clientX >= rect.left &&
      e.clientX <= rect.right &&
      e.clientY >= rect.top &&
      e.clientY <= rect.bottom;
    if (isPointerInside) return;

    isOverRef.current = false;
    setIsOver(false);
    dropIndexRef.current = null;
    clearShiftedCards();
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, [clearShiftedCards]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      dragDepthRef.current = 0;
      isOverRef.current = false;
      setIsOver(false);
      // Read from ref — the state value in the closure may be stale because
      // the last RAF may still be pending.
      const currentDropIndex = dropIndexRef.current;
      dropIndexRef.current = null;
      clearShiftedCards();
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }

      const payload = parseDragPayload(e);
      if (!payload) return;

      const container = columnItemsRef.current;
      if (!container) {
        onDropToColumn(column.column_id, payload.itemId);
        return;
      }

      // Collect visible item IDs in DOM (visual) order
      const allCards = container.querySelectorAll<HTMLElement>('.hierarchy-node[data-item-id]');
      const visibleIds: string[] = [];
      for (let i = 0; i < allCards.length; i++) {
        if (allCards[i].offsetHeight > 0) {
          const id = allCards[i].getAttribute('data-item-id');
          if (id) visibleIds.push(id);
        }
      }

      if (visibleIds.length === 0) {
        onMoveToPosition(payload.itemId, column.column_id, 0);
        return;
      }

      const dropIdx = currentDropIndex ?? visibleIds.length;

      // Build desired order: remove dragged item, insert at drop index
      const draggedVisIdx = visibleIds.indexOf(payload.itemId);
      const withoutDragged = visibleIds.filter((id) => id !== payload.itemId);

      // Adjust the insertion index since removing the dragged card shifts
      // indices after its original position.
      let insertAt = dropIdx;
      if (draggedVisIdx >= 0 && dropIdx > draggedVisIdx) {
        insertAt = dropIdx - 1;
      }
      insertAt = Math.max(0, Math.min(insertAt, withoutDragged.length));

      // No-op guard: item dropped back in its original visual slot
      if (draggedVisIdx >= 0 && draggedVisIdx === insertAt) {
        return;
      }

      // Determine same-column vs cross-column
      const isSameColumn = draggedVisIdx >= 0;

      if (isSameColumn) {
        // Same-column: use the reorder endpoint for reliable positioning.
        // This handles degenerate positions (all items at 0) correctly by
        // assigning sequential 0-based positions to the full ordered list.
        //
        // When dragging a parent item (goal/feature), we move the entire
        // subtree (the item + all its descendants) as a group.  This keeps
        // the flat position-sorted order aligned with the hierarchical DOM
        // order so that subsequent drag-and-drop operations compute the
        // correct insertion point.

        // Collect all descendant IDs of the dragged item (children,
        // grandchildren, etc.) that live in this column.
        const draggedGroupIds = new Set<string>();
        draggedGroupIds.add(payload.itemId);
        let changed = true;
        while (changed) {
          changed = false;
          for (const it of items) {
            if (!draggedGroupIds.has(it.item_id) && it.parent_id && draggedGroupIds.has(it.parent_id)) {
              draggedGroupIds.add(it.item_id);
              changed = true;
            }
          }
        }

        const itemIds = items.map((i) => i.item_id);
        // Extract the group in their current relative order
        const groupItems = itemIds.filter((id) => draggedGroupIds.has(id));
        const remaining = itemIds.filter((id) => !draggedGroupIds.has(id));

        if (remaining.length === 0) return; // only group items in column, nothing to do

        // Also remove the group from withoutDragged for the visual mapping.
        const withoutDraggedGroup = visibleIds.filter((id) => !draggedGroupIds.has(id));

        // Map the visual insertion point to the remaining items array.
        // Re-compute insertAt against the group-removed visible list.
        let groupInsertAt = dropIdx;
        // Adjust for group size: all visible group items before dropIdx
        // shift the index down when removed.
        let visGroupBefore = 0;
        for (let g = 0; g < visibleIds.length && g < dropIdx; g++) {
          if (draggedGroupIds.has(visibleIds[g])) visGroupBefore++;
        }
        groupInsertAt = dropIdx - visGroupBefore;
        groupInsertAt = Math.max(0, Math.min(groupInsertAt, withoutDraggedGroup.length));

        let toIdx: number;
        if (groupInsertAt === 0) {
          // Insert before the first visible non-group item
          const firstVisId = withoutDraggedGroup[0];
          const firstIdx = remaining.indexOf(firstVisId);
          toIdx = firstIdx >= 0 ? firstIdx : 0;
        } else {
          // Insert after the item visually above the drop point
          const aboveId = withoutDraggedGroup[groupInsertAt - 1];
          const aboveIdx = remaining.indexOf(aboveId);
          toIdx = aboveIdx >= 0 ? aboveIdx + 1 : remaining.length;
        }

        // Splice the entire group at the target position
        remaining.splice(toIdx, 0, ...groupItems);

        // No-op guard: if the resulting order is the same as the current
        // position-sorted order, skip the mutation.
        const originalOrder = items.map((i) => i.item_id);
        if (remaining.length === originalOrder.length && remaining.every((id, i) => id === originalOrder[i])) {
          return;
        }

        onReorderColumn(column.column_id, remaining);
      } else {
        // Cross-column: use the move endpoint to change column_id.
        // Position = insertAt so the item lands near the drop point.
        onMoveToPosition(payload.itemId, column.column_id, insertAt);
      }
    },
    [clearShiftedCards, column.column_id, items, onDropToColumn, onMoveToPosition, onReorderColumn]
  );

  const hierarchyView = useMemo(() => {
    const goalRoots: WorkItem[] = [];
    const rootFeatures: WorkItem[] = [];
    const rootTasks: WorkItem[] = [];
    const featuresByGoal = new Map<string, WorkItem[]>();
    const tasksByFeature = new Map<string, WorkItem[]>();
    const itemById = new Map(renderItems.map((item) => [item.item_id, item]));

    for (const item of renderItems) {
      if (item.parent_id && !itemById.has(item.parent_id)) {
        continue;
      }

      if (item.item_type === 'goal') {
        goalRoots.push(item);
        continue;
      }

      if (item.item_type === 'feature') {
        const parent = item.parent_id ? itemById.get(item.parent_id) : undefined;
        if (parent?.item_type === 'goal') {
          const bucket = featuresByGoal.get(parent.item_id) ?? [];
          bucket.push(item);
          featuresByGoal.set(parent.item_id, bucket);
          continue;
        }
        rootFeatures.push(item);
        continue;
      }

      const parent = item.parent_id ? itemById.get(item.parent_id) : undefined;
      if (parent?.item_type === 'feature') {
        const bucket = tasksByFeature.get(parent.item_id) ?? [];
        bucket.push(item);
        tasksByFeature.set(parent.item_id, bucket);
        continue;
      }
      rootTasks.push(item);
    }

    const sortBucketMap = (source: Map<string, WorkItem[]>) => {
      const sorted = new Map<string, WorkItem[]>();
      source.forEach((bucket, key) => {
        sorted.set(key, sortByPosition(bucket));
      });
      return sorted;
    };

    return {
      goalRoots: sortByPosition(goalRoots),
      rootFeatures: sortByPosition(rootFeatures),
      rootTasks: sortByPosition(rootTasks),
      featuresByGoal: sortBucketMap(featuresByGoal),
      tasksByFeature: sortBucketMap(tasksByFeature),
    };
  }, [renderItems]);

  type FlattenedHierarchyRow = {
    item: WorkItem;
    depth: 0 | 1 | 2;
    hint?: string;
    options?: {
      isExpandable?: boolean;
      isCollapsed?: boolean;
      hierarchyCountLabel?: string;
      summarized?: boolean;
    };
  };

  const visibleRows = useMemo<FlattenedHierarchyRow[]>(() => {
    const rows: FlattenedHierarchyRow[] = [];

    for (const goal of hierarchyView.goalRoots) {
      const features = hierarchyView.featuresByGoal.get(goal.item_id) ?? [];
      const goalCollapsed = collapsed.has(goal.item_id);
      const globalFeatureCount = featureCountByGoal.get(goal.item_id) ?? 0;
      const globalTaskCount = (taskCountByGoal.get(goal.item_id) ?? 0) + (childTaskCountByParent.get(goal.item_id) ?? 0);
      const goalCountParts: string[] = [];
      if (globalFeatureCount > 0) goalCountParts.push(`${globalFeatureCount} ${globalFeatureCount === 1 ? 'feature' : 'features'}`);
      if (globalTaskCount > 0) goalCountParts.push(`${globalTaskCount} ${globalTaskCount === 1 ? 'task' : 'tasks'}`);

      rows.push({
        item: goal,
        depth: 0,
        options: {
          isExpandable: features.length > 0,
          isCollapsed: goalCollapsed,
          hierarchyCountLabel: goalCountParts.length > 0 ? goalCountParts.join(' · ') : undefined,
          summarized: true,
        },
      });

      if (goalCollapsed) continue;

      for (const feature of features) {
        const tasks = hierarchyView.tasksByFeature.get(feature.item_id) ?? [];
        const featureCollapsed = collapsed.has(feature.item_id);
        const globalTaskCount = childTaskCountByParent.get(feature.item_id) ?? 0;

        rows.push({
          item: feature,
          depth: 1,
          hint: `Rolls up to goal: ${goal.title}`,
          options: {
            isExpandable: tasks.length > 0,
            isCollapsed: featureCollapsed,
            hierarchyCountLabel: globalTaskCount > 0 ? `${globalTaskCount} ${globalTaskCount === 1 ? 'task' : 'tasks'}` : undefined,
          },
        });

        if (featureCollapsed) continue;

        for (const task of tasks) {
          rows.push({
            item: task,
            depth: 2,
            hint: `Rolls up to feature: ${feature.title}`,
          });
        }
      }
    }

    for (const feature of hierarchyView.rootFeatures) {
      const tasks = hierarchyView.tasksByFeature.get(feature.item_id) ?? [];
      const featureCollapsed = collapsed.has(feature.item_id);
      const globalTaskCount = childTaskCountByParent.get(feature.item_id) ?? 0;

      rows.push({
        item: feature,
        depth: 0,
        hint: feature.parent_id ? 'Parent goal is in another column' : undefined,
        options: {
          isExpandable: tasks.length > 0,
          isCollapsed: featureCollapsed,
          hierarchyCountLabel: globalTaskCount > 0 ? `${globalTaskCount} ${globalTaskCount === 1 ? 'task' : 'tasks'}` : undefined,
        },
      });

      if (featureCollapsed) continue;

      for (const task of tasks) {
        rows.push({
          item: task,
          depth: 1,
          hint: `Rolls up to feature: ${feature.title}`,
        });
      }
    }

    for (const task of hierarchyView.rootTasks) {
      rows.push({
        item: task,
        depth: 0,
        hint: task.parent_id ? 'Parent feature is in another column' : undefined,
      });
    }

    const seenIds = new Set<string>();
    return rows.filter((row) => {
      if (seenIds.has(row.item.item_id)) return false;
      seenIds.add(row.item.item_id);
      return true;
    });
  }, [
    childTaskCountByParent,
    collapsed,
    featureCountByGoal,
    hierarchyView,
    taskCountByGoal,
  ]);

  const useVirtualList =
    !deferColumnVirtualization && visibleRows.length > 80;

  const rowVirtualizer = useElementVirtualizer({
    count: useVirtualList ? visibleRows.length : 0,
    getScrollElement: () => columnItemsRef.current,
    estimateSize: (index) => {
      const row = visibleRows[index];
      if (!row) return 108;
      if (row.depth === 2) return 98;
      if (row.depth === 1) return 104;
      return 112;
    },
    overscan: 8,
  });

  const isItemDimmed = useCallback(
    (itemId: string): boolean => {
      if (!isFiltered) return false;
      if (matchingIds?.has(itemId)) return false;
      if (ancestorIds?.has(itemId)) return true;
      return true; // neither match nor ancestor → dim
    },
    [isFiltered, matchingIds, ancestorIds]
  );

  const renderCard = useCallback(
    (
      item: WorkItem,
      depth: 0 | 1 | 2,
      hint?: string,
      options?: {
        isExpandable?: boolean;
        isCollapsed?: boolean;
        hierarchyCountLabel?: string;
        summarized?: boolean;
      }
    ) => (
      <div
        className={`hierarchy-node hierarchy-depth-${depth} hierarchy-node-${item.item_type}`}
        data-item-id={item.item_id}
        role="listitem"
        aria-level={depth + 1}
      >
        <WorkItemCard
          item={item}
          projectSlug={projectSlug}
          assigneeIndex={assigneeIndex}
          childTaskCount={childTaskCountByParent.get(item.item_id) ?? 0}
          execution={executionByItemId.get(item.item_id) ?? null}
          onOpen={onOpen}
          onStartExecution={onStartExecution}
          onCancelExecution={onCancelExecution}
          onCopyId={onCopyWorkItemId}
          onRequestDelete={onRequestDelete}
          isStartPending={isStartPending}
          isCancelPending={isCancelPending}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          selected={item.item_id === selectedItemId}
          hierarchyHint={hint}
          isExpandable={options?.isExpandable}
          isCollapsed={options?.isCollapsed}
          hierarchyCountLabel={options?.hierarchyCountLabel}
          onToggleCollapse={toggleCollapse}
          executionAvailable={executionAvailable}
          isDimmed={isItemDimmed(item.item_id)}
          progressRollup={progressByItemId.get(item.item_id) ?? null}
          summarized={options?.summarized}
          diffState={itemDiffMap?.get(item.item_id)}
          isBeingDragged={item.item_id === draggedItemId}
          isJustDropped={item.item_id === justDroppedItemId}
          assignableHumans={assignableHumans}
          assignableAgents={assignableAgents}
          onAssign={handleCardAssign}
          onUnassign={handleCardUnassign}
          isAssignPending={isAssignPending}
        />
      </div>
    ),
    [
      assignableAgents,
      assignableHumans,
      assigneeIndex,
      childTaskCountByParent,
      draggedItemId,
      justDroppedItemId,
      executionByItemId,
      executionAvailable,
      handleCardAssign,
      handleCardUnassign,
      isAssignPending,
      isCancelPending,
      isItemDimmed,
      isStartPending,
      itemDiffMap,
      onCancelExecution,
      onCopyWorkItemId,
      onRequestDelete,
      onDragEnd,
      onDragStart,
      onOpen,
      onStartExecution,
      progressByItemId,
      projectSlug,
      selectedItemId,
      toggleCollapse,
    ]
  );

  return (
    <section
      className={`board-column board-column-accent-${accentIndex} ${isOver ? 'drop-target' : ''}`}
      data-column-id={column.column_id}
      onDragOver={handleDragOver}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      aria-label={`Column ${column.name}`}
    >
      <ColumnLaneHeader
        column={column}
        onCreate={onCreate}
        hasExpandableItems={expandableIds.size > 0}
        onExpandAll={expandAll}
        onCollapseAll={collapseAll}
        boardId={boardId}
        assignableHumans={assignableHumans}
        assignableAgents={assignableAgents}
        currentUserId={currentUserId}
        onOpen={onOpen}
      />

      <div ref={columnItemsRef} className="board-column-items board-column-items-hierarchy" role="list" aria-label={`${column.name} hierarchy`}>
        {/* Phase 1: Show skeleton cards while items are loading */}
        {itemsLoading && items.length === 0 && (
          <>
            <WorkItemSkeleton />
            <WorkItemSkeleton />
            <WorkItemSkeleton />
          </>
        )}
        {visibleRows.length > 0 && !useVirtualList && (
          <>
            {visibleRows.map((row) => (
              <div key={row.item.item_id} data-dnd-slot="true" data-item-id={row.item.item_id}>
                {renderCard(row.item, row.depth, row.hint, row.options)}
              </div>
            ))}
          </>
        )}
        {visibleRows.length > 0 && useVirtualList && (
          <div
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              position: 'relative',
              width: '100%',
            }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const row = visibleRows[virtualRow.index];
              if (!row) return null;

              return (
                <div
                  key={row.item.item_id}
                  ref={rowVirtualizer.measureElement}
                  data-index={virtualRow.index}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  <div data-dnd-slot="true" data-item-id={row.item.item_id}>
                    {renderCard(row.item, row.depth, row.hint, row.options)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
});

// ---------------------------------------------------------------------------
// Outline View — table-based alternate for scanning many items quickly
// ---------------------------------------------------------------------------

interface OutlineViewProps {
  items: WorkItem[];
  columns: BoardColumn[];
  itemsByColumnId: Record<string, WorkItem[]>;
  assigneeIndex: Map<string, AssigneeProfile>;
  filterResult: { matchingIds: Set<string>; ancestorIds: Set<string>; isFiltered: boolean; matchCount: number };
  projectSlug?: string;
  onOpen: (itemId: string) => void;
  onCopyWorkItemId: (itemId: string, displayId: string) => void;
}

const TYPE_ICON: Record<WorkItemType, string> = {
  goal: '◆',
  feature: '📖',
  task: '☑',
  bug: '🐛',
};

const PRIORITY_LABEL: Record<string, string> = {
  critical: '🔴 Critical',
  high: '🟠 High',
  medium: '🟡 Medium',
  low: '🟢 Low',
};

function formatDueDate(date?: string | null): string {
  if (!date) return '—';
  const d = new Date(date);
  const now = new Date();
  const diff = d.getTime() - now.getTime();
  const days = Math.ceil(diff / (1000 * 60 * 60 * 24));
  const formatted = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  if (days < 0) return `${formatted} (overdue)`;
  if (days === 0) return `${formatted} (today)`;
  if (days <= 3) return `${formatted} (${days}d)`;
  return formatted;
}

const OutlineView = memo(function OutlineView({
  items,
  columns,
  itemsByColumnId,
  assigneeIndex,
  filterResult,
  projectSlug,
  onOpen,
  onCopyWorkItemId,
}: OutlineViewProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    // Default: all parents collapsed
    const ids = new Set<string>();
    for (const item of items) {
      if (item.item_type === 'goal' || item.item_type === 'feature') ids.add(item.item_id);
    }
    return ids;
  });

  const toggleCollapse = useCallback((itemId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }, []);

  // Build a global itemById map for cross-column parent lookups
  const itemById = useMemo(() => new Map(items.map((it) => [it.item_id, it])), [items]);

  // Build per-column hierarchy, including reassigning null-column items to their parent's column
  const columnHierarchies = useMemo(() => {
    // Collect items by column, reassigning __none__ items to parent's column
    const byCol: Record<string, WorkItem[]> = {};
    for (const [colKey, colItems] of Object.entries(itemsByColumnId)) {
      if (colKey === '__none__') continue; // handle below
      byCol[colKey] = [...colItems];
    }

    // Reassign orphaned items (null column_id) to their parent's column
    const orphanItems = itemsByColumnId['__none__'] ?? [];
    const uncategorized: WorkItem[] = [];
    for (const item of orphanItems) {
      const parent = item.parent_id ? itemById.get(item.parent_id) : undefined;
      if (parent?.column_id) {
        if (!byCol[parent.column_id]) byCol[parent.column_id] = [];
        byCol[parent.column_id].push(item);
      } else {
        uncategorized.push(item);
      }
    }

    // Build hierarchy per column
    type ColHierarchy = {
      goalRoots: WorkItem[];
      rootFeatures: WorkItem[];
      rootTasks: WorkItem[];
      featuresByGoal: Map<string, WorkItem[]>;
      tasksByFeature: Map<string, WorkItem[]>;
      totalCount: number;
    };

    const buildHierarchy = (colItems: WorkItem[]): ColHierarchy => {
      const goalRoots: WorkItem[] = [];
      const rootFeatures: WorkItem[] = [];
      const rootTasks: WorkItem[] = [];
      const featuresByGoal = new Map<string, WorkItem[]>();
      const tasksByFeature = new Map<string, WorkItem[]>();

      for (const item of colItems) {
        if (item.item_type === 'goal') {
          goalRoots.push(item);
          continue;
        }
        if (item.item_type === 'feature') {
          const parent = item.parent_id ? itemById.get(item.parent_id) : undefined;
          if (parent?.item_type === 'goal') {
            const bucket = featuresByGoal.get(parent.item_id) ?? [];
            bucket.push(item);
            featuresByGoal.set(parent.item_id, bucket);
            continue;
          }
          rootFeatures.push(item);
          continue;
        }
        // task or bug
        const parent = item.parent_id ? itemById.get(item.parent_id) : undefined;
        if (parent?.item_type === 'feature') {
          const bucket = tasksByFeature.get(parent.item_id) ?? [];
          bucket.push(item);
          tasksByFeature.set(parent.item_id, bucket);
          continue;
        }
        rootTasks.push(item);
      }

      return {
        goalRoots: sortByPosition(goalRoots),
        rootFeatures: sortByPosition(rootFeatures),
        rootTasks: sortByPosition(rootTasks),
        featuresByGoal,
        tasksByFeature,
        totalCount: colItems.length,
      };
    };

    const result: { columnId: string; hierarchy: ColHierarchy }[] = [];
    for (const col of columns) {
      const colItems = byCol[col.column_id];
      if (!colItems || colItems.length === 0) continue;
      result.push({ columnId: col.column_id, hierarchy: buildHierarchy(colItems) });
    }

    // Uncategorized group
    if (uncategorized.length > 0) {
      result.push({ columnId: '__uncategorized__', hierarchy: buildHierarchy(uncategorized) });
    }

    return result;
  }, [columns, itemsByColumnId, itemById]);

  const columnNameMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const col of columns) map.set(col.column_id, col.name);
    map.set('__uncategorized__', 'Uncategorized');
    return map;
  }, [columns]);

  const renderRow = useCallback(
    (item: WorkItem, depth: number) => {
      const dimmed = filterResult.isFiltered && !filterResult.matchingIds.has(item.item_id);
      const assignee = item.assignee_id
        ? assigneeIndex.get(`${item.assignee_type ?? 'human'}:${item.assignee_id}`)
        : null;
      const displayId = formatWorkItemDisplayId(item, projectSlug);
      const dueDateClass = item.due_date
        ? new Date(item.due_date).getTime() < Date.now() ? ' outline-due-overdue' : ''
        : '';
      const hasChildren = item.item_type === 'goal' || item.item_type === 'feature';
      const isCollapsed = collapsed.has(item.item_id);

      return (
        <div
          key={item.item_id}
          className={`outline-row outline-depth-${depth}${dimmed ? ' outline-row-dimmed' : ''}`}
          role="row"
          tabIndex={0}
          onClick={() => onOpen(item.item_id)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onOpen(item.item_id);
            }
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            onCopyWorkItemId(item.item_id, displayId);
          }}
        >
          <span className="outline-cell outline-cell-id" role="cell">
            <code className="outline-id-code">{displayId}</code>
          </span>
          <span className="outline-cell outline-cell-title" role="cell" title={item.title}>
            {hasChildren && (
              <button
                className={`outline-hierarchy-toggle${isCollapsed ? '' : ' outline-hierarchy-toggle-expanded'}`}
                aria-label={isCollapsed ? 'Expand' : 'Collapse'}
                onClick={(e) => { e.stopPropagation(); toggleCollapse(item.item_id); }}
              >
                ▶
              </button>
            )}
            {item.title}
          </span>
          <span className={`outline-cell outline-cell-type outline-type-${item.item_type}`} role="cell">
            <span className="outline-type-icon" aria-hidden="true">{TYPE_ICON[item.item_type] ?? '?'}</span>
            {item.item_type}
          </span>
          <span className="outline-cell outline-cell-status" role="cell">
            {item.status}
          </span>
          <span className="outline-cell outline-cell-assignee" role="cell">
            {assignee ? assignee.label : '—'}
          </span>
          <span className={`outline-cell outline-cell-priority outline-priority-${item.priority ?? 'none'}`} role="cell">
            {item.priority ? (PRIORITY_LABEL[item.priority] ?? item.priority) : '—'}
          </span>
          <span className={`outline-cell outline-cell-due${dueDateClass}`} role="cell">
            {formatDueDate(item.due_date)}
          </span>
        </div>
      );
    },
    [filterResult, assigneeIndex, projectSlug, collapsed, onOpen, onCopyWorkItemId, toggleCollapse]
  );

  const renderHierarchy = useCallback(
    (h: { goalRoots: WorkItem[]; rootFeatures: WorkItem[]; rootTasks: WorkItem[]; featuresByGoal: Map<string, WorkItem[]>; tasksByFeature: Map<string, WorkItem[]> }) => {
      const rows: React.ReactNode[] = [];

      for (const goal of h.goalRoots) {
        rows.push(renderRow(goal, 0));
        if (!collapsed.has(goal.item_id)) {
          const features = h.featuresByGoal.get(goal.item_id) ?? [];
          for (const feature of features) {
            rows.push(renderRow(feature, 1));
            if (!collapsed.has(feature.item_id)) {
              const tasks = h.tasksByFeature.get(feature.item_id) ?? [];
              for (const task of tasks) {
                rows.push(renderRow(task, 2));
              }
            }
          }
        }
      }

      // Orphan features (no goal parent in this column)
      for (const feature of h.rootFeatures) {
        rows.push(renderRow(feature, 0));
        if (!collapsed.has(feature.item_id)) {
          const tasks = h.tasksByFeature.get(feature.item_id) ?? [];
          for (const task of tasks) {
            rows.push(renderRow(task, 1));
          }
        }
      }

      // Orphan tasks/bugs (no parent feature in this column)
      for (const task of h.rootTasks) {
        rows.push(renderRow(task, 0));
      }

      return rows;
    },
    [collapsed, renderRow]
  );

  return (
    <div className="board-outline-view" role="table" aria-label="Work items outline">
      {/* Sticky header row */}
      <div className="outline-header" role="row">
        <span className="outline-cell outline-cell-id" role="columnheader">ID</span>
        <span className="outline-cell outline-cell-title" role="columnheader">Title</span>
        <span className="outline-cell outline-cell-type" role="columnheader">Type</span>
        <span className="outline-cell outline-cell-status" role="columnheader">Status</span>
        <span className="outline-cell outline-cell-assignee" role="columnheader">Assignee</span>
        <span className="outline-cell outline-cell-priority" role="columnheader">Priority</span>
        <span className="outline-cell outline-cell-due" role="columnheader">Due</span>
      </div>

      {columnHierarchies.map(({ columnId, hierarchy }) => (
        <div key={columnId} className="outline-group" role="rowgroup">
          <div className="outline-group-header" role="row">
            <span className="outline-group-label">{columnNameMap.get(columnId) ?? columnId}</span>
            <span className="outline-group-count">{hierarchy.totalCount}</span>
          </div>
          {renderHierarchy(hierarchy)}
        </div>
      ))}

      {items.length === 0 && (
        <div className="outline-empty">No items on this board.</div>
      )}
    </div>
  );
});

export function BoardPage(): React.JSX.Element {
  const navigate = useNavigate();
  const { projectId, boardId, itemId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { actor } = useAuth();
  // const { connectionState } = useCollabStore(); // removed: always 'disconnected', showing misleading "Offline" chip

  // View mode synced to URL ?view=board|outline
  const viewMode: ViewMode = searchParams.get('view') === 'outline' ? 'outline' : 'board';
  const [copyToast, setCopyToast] = useState<{ message: string; variant: 'success' | 'error' } | null>(null);
  const copyToastTimerRef = React.useRef<number | null>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const boardColumnsRef = useRef<HTMLDivElement>(null);
  const boardPerfStartedAtRef = useRef<number | null>(null);
  const boardPerfFlagsRef = useRef<{ shell?: string; firstPage?: string; full?: string }>({});
  const [scrolled, setScrolled] = useState(false);
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [visibleColumnIds, setVisibleColumnIds] = useState<Set<string>>(new Set());
  const pendingFocusItemIdRef = useRef<string | null>(null);
  const filterState = useBoardFilters();
  const { filters, sort, hasActiveFilters } = filterState;
  const workItemQuery = useMemo(() => filtersToQueryParams(filters, sort), [filters, sort]);

  // Collapse header chrome after scrolling past threshold
  useEffect(() => {
    const el = pageRef.current;
    if (!el) return;
    const scrollParent = el.closest('.workspace-main') as HTMLElement | null;
    if (!scrollParent) return;
    let ticking = false;
    const onScroll = () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(() => {
          setScrolled(scrollParent.scrollTop > 48);
          ticking = false;
        });
      }
    };
    scrollParent.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => scrollParent.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    boardPerfStartedAtRef.current = typeof performance !== 'undefined' ? performance.now() : Date.now();
    boardPerfFlagsRef.current = {};
  }, [boardId]);

  const { data: project } = useProject(projectId);
  const { data: board, isLoading: boardLoading } = useBoard(boardId);
  const {
    data: workItems,
    isInitialLoading: itemsLoading,
    isBackgroundHydrating,
    loadedCount,
    total: totalItemCount,
    isPartial,
    isRefreshing,
    error: itemsError,
    refetch: refetchItems,
    loadMore,
    lastSyncedAt,
  } = useWorkItems(boardId, {
    query: workItemQuery,
    pageSize: 100,
    progressive: true,
  });

  const deleteItem = useDeleteWorkItem(boardId);
  const deleteCommitTimerRef = useRef<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingBoardDelete | null>(null);
  const [isDeleteDockHovered, setIsDeleteDockHovered] = useState(false);
  const capabilitiesQuery = useApiCapabilities();
  const items = useMemo(() => {
    if (!pendingDelete) return workItems;
    const hidden = new Set(pendingDelete.hiddenIds);
    return workItems.filter((item) => !hidden.has(item.item_id));
  }, [pendingDelete, workItems]);

  // Phase 4: Track item diff states for premium animations
  const itemDiffMap = useItemDiffState(items);

  const [assignmentDrawerOpen, setAssignmentDrawerOpen] = useState(false);
  const participantsQuery = useProjectParticipants(projectId ?? null);
  const projectAgentsQuery = useProjectAgents(projectId ?? null, {
    enabled: Boolean(projectId) && assignmentDrawerOpen,
  });
  const executionAvailable = capabilitiesQuery.data?.routes.executions ?? false;
  const participantRecords = useMemo(
    () => participantsQuery.data?.items ?? EMPTY_PARTICIPANTS,
    [participantsQuery.data],
  );
  const projectAgents = projectAgentsQuery.data ?? EMPTY_AGENTS;
  const participantsError = participantsQuery.error;
  const projectAgentsError = assignmentDrawerOpen ? projectAgentsQuery.error : null;

  // Agent presence rail state
  const [membersSheetOpen, setMembersSheetOpen] = useState(false);
  const { presences: agentPresences } = useAgentPresence(projectAgents, projectId ?? undefined);

  const collabDockLauncherRef = useRef<HTMLButtonElement>(null);

  const [unifiedChat, setUnifiedChat] = useState<{
    initialTarget: UnifiedConversationInitialTarget;
    key: number;
    dmParticipantId?: string;
  } | null>(null);
  const getOrCreateDM = useGetOrCreateDirectConversation();

  const [hydrationNoticeDismissed, setHydrationNoticeDismissed] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      setHydrationNoticeDismissed(false);
      if (typeof sessionStorage !== 'undefined' && boardId) {
        setHydrationNoticeDismissed(sessionStorage.getItem(`board-hydration-dismiss:${boardId}`) === '1');
      }
    });
  }, [boardId]);

  const dismissHydrationNotice = useCallback(() => {
    if (boardId && typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem(`board-hydration-dismiss:${boardId}`, '1');
    }
    setHydrationNoticeDismissed(true);
  }, [boardId]);

  useEffect(() => {
    queueMicrotask(() => {
      setMembersSheetOpen(false);
      setUnifiedChat(null);
    });
  }, [boardId, projectId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey || !e.shiftKey) return;
      if (e.key.toLowerCase() !== 'm') return;
      e.preventDefault();
      setUnifiedChat((prev) =>
        prev
          ? null
          : {
              initialTarget: { mode: 'firstProjectRoom' },
              key: Date.now(),
            },
      );
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const createItem = useCreateWorkItem();
  const moveItem = useMoveWorkItem(boardId);
  const reorderItems = useReorderWorkItems(boardId);
  const executionStream = useExecutionStream({
    orgId: project?.org_id ?? null,
    projectId: projectId ?? null,
    enabled: Boolean(project?.org_id && projectId),
  });
  const executionListQuery = useExecutionList(project?.org_id ?? null, projectId ?? null, {
    status: 'running',
    limit: 25,
    refetchInterval: executionStream.isConnected ? false : 30_000,
  });
  const executeWorkItem = useExecuteWorkItem();
  const cancelExecution = useCancelWorkItemExecution();
  const shouldLoadRollups = Boolean(boardId) && !itemsLoading && loadedCount > 0;
  const goalRollupsQuery = useBoardProgressRollups(boardId, {
    itemType: 'goal',
    enabled: shouldLoadRollups,
    staleTimeMs: 30_000,
  });
  const featureRollupsQuery = useBoardProgressRollups(boardId, {
    itemType: 'feature',
    enabled: shouldLoadRollups,
    staleTimeMs: 30_000,
  });

  const assignableHumans = useMemo<AssigneeProfile[]>(() => {
    const currentUserId = actor?.type === 'human' ? actor.id : null;
    const actorEmail = actor?.type === 'human' ? actor.email?.trim().toLowerCase() : undefined;

    const humans: AssigneeProfile[] = participantRecords.flatMap((participant) => {
      if (participant.kind !== 'human') return [];
      const uid = (participant.user_id ?? participant.id)?.trim();
      if (!uid) return [];
      const pEmail = participant.email?.trim().toLowerCase();
      const isCurrentUser =
        (currentUserId != null && (participant.user_id === currentUserId || participant.id === currentUserId)) ||
        Boolean(actorEmail && pEmail && actorEmail === pEmail);
      const baseLabel = participant.display_name?.trim()
        || participant.email?.trim()
        || `Member ${shortenId(uid)}`;
      const role = participant.role ? participant.role.toLowerCase().replace(/_/g, ' ') : 'member';
      const profile: AssigneeProfile = {
        id: uid,
        type: 'user',
        label: baseLabel,
        subtitle: isCurrentUser ? `${role} • you` : role,
        avatar: getInitials(baseLabel),
        actor: toActorViewModel(
          {
            user_id: uid,
            display_name: baseLabel,
            status: 'idle',
          },
          {
            subtitle: role,
            presenceState: 'available',
            isCurrentUser,
          },
        ),
      };
      return [profile];
    });

    if (currentUserId && !humans.some((human) => human.actor?.isCurrentUser)) {
      const fallbackLabel = actor?.displayName?.trim() || 'You';
      humans.unshift({
        id: currentUserId,
        type: 'user',
        label: fallbackLabel,
        subtitle: 'owner • you',
        avatar: getInitials(fallbackLabel),
        actor: actor
          ? toActorViewModel(actor, { isCurrentUser: true, presenceState: 'available', subtitle: 'owner' })
          : toActorViewModel(
              { user_id: currentUserId, display_name: fallbackLabel, status: 'idle' },
              { subtitle: 'owner', presenceState: 'available', isCurrentUser: true },
            ),
      });
    }

    return humans;
  }, [actor, participantRecords]);

  const assignableAgents = useMemo<AssigneeProfile[]>(() => {
    return participantRecords.flatMap((participant) => {
      if (participant.kind !== 'agent') return [];
      const actualAgentId = (participant.agent_id ?? participant.id)?.trim();
      if (!actualAgentId) return [];
      const label = participant.display_name?.trim() || `Agent ${shortenId(actualAgentId)}`;
      const roleLabel = participant.role ? participant.role.toLowerCase().replace(/_/g, ' ') : 'agent';
      const typeLabel = `${roleLabel} agent`;
      const presence = participant.presence ?? 'available';

      return [{
        id: actualAgentId,
        type: 'agent' as const,
        label,
        subtitle: typeLabel,
        status: participant.assignment_status ?? 'active',
        avatar: getInitials(label),
        actor: toActorViewModel(
          {
            id: actualAgentId,
            name: label,
            agent_type: typeLabel,
            status: 'active' as AgentStatus,
            config: {},
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          {
            id: actualAgentId,
            subtitle: typeLabel,
            presenceState: presence,
            presenceLabel: participant.description ?? typeLabel,
          },
        ),
        presence,
        presenceLabel: participant.description ?? typeLabel,
      }];
    });
  }, [participantRecords]);

  const boardParticipants = useMemo<BoardParticipant[]>(() => {
    const humans: BoardParticipant[] = assignableHumans.map((profile) => ({
      id: assigneeKey(profile.type, profile.id),
      kind: 'human',
      actor: profile.actor ?? toActorViewModel(
        {
          user_id: profile.id,
          display_name: profile.label,
          status: 'idle',
        },
        {
          subtitle: profile.subtitle,
          presenceState: 'available',
          isCurrentUser: false,
        },
      ),
      subtitle: profile.subtitle,
      roleLabel: profile.subtitle,
      statusLine: profile.subtitle,
      isCurrentUser: Boolean(profile.actor?.isCurrentUser),
    }));

    const agents: BoardParticipant[] = assignableAgents.map((profile) => ({
      id: assigneeKey(profile.type, profile.id),
      kind: 'agent',
      actor: profile.actor ?? toActorViewModel(
        {
          id: profile.id,
          name: profile.label,
          agent_type: profile.subtitle ?? 'Agent',
          status: (profile.status ?? 'active') as AgentStatus,
          config: {},
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          presenceState: profile.presence ?? 'available',
          subtitle: profile.subtitle,
        },
      ),
      subtitle: profile.subtitle,
      roleLabel: profile.subtitle,
      statusLine: profile.presenceLabel ?? profile.subtitle,
    }));

    return [...humans, ...agents];
  }, [assignableAgents, assignableHumans]);

  const assigneeIndex = useMemo(() => {
    const index = new Map<string, AssigneeProfile>();
    assignableHumans.forEach((profile) => {
      index.set(assigneeKey(profile.type, profile.id), profile);
    });
    assignableAgents.forEach((profile) => {
      index.set(assigneeKey(profile.type, profile.id), profile);
    });
    return index;
  }, [assignableAgents, assignableHumans]);

  const assignmentHint = useMemo(() => 'Project members + assigned agents', []);

  const filterResult = useFilteredItems(items, filters, hasActiveFilters);

  const allLabels = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.labels) {
        for (const label of item.labels) set.add(label);
      }
    }
    return [...set].sort();
  }, [items]);

  const columns = useMemo(() => {
    const cols = board?.columns ?? [];
    return sortByPosition(cols);
  }, [board?.columns]);

  const itemsByColumnId = useMemo(() => {
    const next: Record<string, WorkItem[]> = {};
    for (const item of items) {
      const columnKey = item.column_id ?? '__none__';
      if (!next[columnKey]) next[columnKey] = [];
      next[columnKey].push(item);
    }
    for (const k of Object.keys(next)) {
      next[k] = sort.field !== 'position' ? sortItems(next[k], sort) : sortByPosition(next[k]);
    }
    return next;
  }, [items, sort]);

  // ── IntersectionObserver for column visibility tracking ────────────────
  useEffect(() => {
    const container = boardColumnsRef.current;
    if (!container || viewMode !== 'board') return;

    const observer = new IntersectionObserver(
      (entries) => {
        setVisibleColumnIds((prev) => {
          const next = new Set(prev);
          for (const entry of entries) {
            const colId = (entry.target as HTMLElement).dataset.columnId;
            if (!colId) continue;
            if (entry.isIntersecting) {
              next.add(colId);
            } else {
              next.delete(colId);
            }
          }
          if (next.size === prev.size && [...next].every((id) => prev.has(id))) return prev;
          return next;
        });
      },
      { root: container, threshold: 0.3 }
    );

    const colElements = container.querySelectorAll<HTMLElement>('[data-column-id]');
    colElements.forEach((col) => observer.observe(col));

    return () => observer.disconnect();
  }, [viewMode, columns.length]);

  const childTaskCountByParent = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      if (!item.parent_id || item.item_type !== 'task') continue;
      counts.set(item.parent_id, (counts.get(item.parent_id) ?? 0) + 1);
    }
    return counts;
  }, [items]);

  const featureCountByGoal = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      if (item.item_type !== 'feature' || !item.parent_id) continue;
      const goalId = item.parent_id;
      counts.set(goalId, (counts.get(goalId) ?? 0) + 1);
    }
    return counts;
  }, [items]);

  const taskCountByGoal = useMemo(() => {
    const featureToGoal = new Map<string, string>();
    for (const item of items) {
      if (item.item_type === 'feature' && item.parent_id) {
        featureToGoal.set(item.item_id, item.parent_id);
      }
    }

    const counts = new Map<string, number>();
    for (const item of items) {
      if (item.item_type !== 'task' || !item.parent_id) continue;
      const goalId = featureToGoal.get(item.parent_id);
      if (!goalId) continue;
      counts.set(goalId, (counts.get(goalId) ?? 0) + 1);
    }
    return counts;
  }, [items]);

  const targetPositions = useMemo(() => {
    const positions: Record<string, number> = {};
    for (const c of columns) {
      positions[c.column_id] = (itemsByColumnId[c.column_id]?.length ?? 0) + 1;
    }
    return positions;
  }, [columns, itemsByColumnId]);

  const executionByItemId = useMemo(() => {
    const map = new Map<string, ExecutionListItem>();
    const executions = executionListQuery.data?.executions ?? [];
    executions.forEach((execution) => {
      const current = map.get(execution.workItemId);
      if (!current) {
        map.set(execution.workItemId, execution);
        return;
      }
      const currentStarted = new Date(current.startedAt).getTime();
      const nextStarted = new Date(execution.startedAt).getTime();
      if (Number.isNaN(currentStarted) || nextStarted > currentStarted) {
        map.set(execution.workItemId, execution);
      }
    });
    return map;
  }, [executionListQuery.data?.executions]);

  const progressByItemId = useMemo(() => {
    const map = new Map<string, WorkItemProgressRollup>();
    (goalRollupsQuery.data ?? []).forEach((rollup) => map.set(rollup.item_id, rollup));
    (featureRollupsQuery.data ?? []).forEach((rollup) => map.set(rollup.item_id, rollup));
    return map;
  }, [goalRollupsQuery.data, featureRollupsQuery.data]);

  const clearDeleteTimer = useCallback(() => {
    if (deleteCommitTimerRef.current != null) {
      window.clearTimeout(deleteCommitTimerRef.current);
      deleteCommitTimerRef.current = null;
    }
  }, []);

  const collectCascadeDeleteIds = useCallback((rootItemId: string) => {
    const ids = new Set<string>([rootItemId]);
    let added = true;
    while (added) {
      added = false;
      workItems.forEach((item) => {
        if (item.parent_id && ids.has(item.parent_id) && !ids.has(item.item_id)) {
          ids.add(item.item_id);
          added = true;
        }
      });
    }
    return [...ids];
  }, [workItems]);

  const handleStartExecution = useCallback(
    (itemIdValue: string) => {
      if (!projectId) return;
      executeWorkItem.mutate({
        itemId: itemIdValue,
        orgId: project?.org_id ?? null,
        projectId,
      });
    },
    [executeWorkItem, project?.org_id, projectId]
  );

  const handleCancelExecution = useCallback(
    (itemIdValue: string) => {
      if (!projectId) return;
      cancelExecution.mutate({
        itemId: itemIdValue,
        orgId: project?.org_id ?? null,
        projectId,
        reason: 'User requested cancellation',
      });
    },
    [cancelExecution, project?.org_id, projectId]
  );

  const [draggedItemId, setDraggedItemId] = useState<string | null>(null);
  const draggedItemIdRef = useRef<string | null>(null);
  const [justDroppedItemId, setJustDroppedItemId] = useState<string | null>(null);
  const [dropSettling, setDropSettling] = useState(false);
  const dropSettleTimerRef = useRef<number | null>(null);
  const justDroppedTimerRef = useRef<number | null>(null);

  const onDragStart = useCallback((event: React.DragEvent, itemId: string) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/json', JSON.stringify({ itemId }));
    draggedItemIdRef.current = itemId;
    setDraggedItemId(itemId);
    setIsDeleteDockHovered(false);
  }, []);

  const onDragEnd = useCallback(() => {
    const droppedId = draggedItemIdRef.current;
    draggedItemIdRef.current = null;
    setDraggedItemId(null);
    setIsDeleteDockHovered(false);
    if (droppedId) {
      setJustDroppedItemId(droppedId);
      if (justDroppedTimerRef.current != null) {
        window.clearTimeout(justDroppedTimerRef.current);
        justDroppedTimerRef.current = null;
      }
      justDroppedTimerRef.current = window.setTimeout(() => {
        setJustDroppedItemId(null);
        justDroppedTimerRef.current = null;
      }, 220);
    }
    setDropSettling(true);
    if (dropSettleTimerRef.current != null) {
      window.clearTimeout(dropSettleTimerRef.current);
      dropSettleTimerRef.current = null;
    }
    dropSettleTimerRef.current = window.setTimeout(() => {
      setDropSettling(false);
      dropSettleTimerRef.current = null;
    }, 180);
  }, []);

  useEffect(
    () => () => {
      clearDeleteTimer();
      if (dropSettleTimerRef.current != null) {
        window.clearTimeout(dropSettleTimerRef.current);
      }
      if (justDroppedTimerRef.current != null) {
        window.clearTimeout(justDroppedTimerRef.current);
      }
    },
    [clearDeleteTimer]
  );

  const onDropToColumn = useCallback(
    (columnId: string, itemId: string) => {
      const position = (itemsByColumnId[columnId]?.length ?? 0) + 1;
      moveItem.mutate({
        itemId,
        move: {
          column_id: columnId,
          position,
          expected_from_column_updated_at: null,
          expected_to_column_updated_at: null,
        },
      });
    },
    [itemsByColumnId, moveItem]
  );

  const onMoveToPosition = useCallback(
    (itemId: string, columnId: string, position: number) => {
      moveItem.mutate({
        itemId,
        move: {
          column_id: columnId,
          position,
          expected_from_column_updated_at: null,
          expected_to_column_updated_at: null,
        },
      });
      // Announce for screen readers
      const liveEl = document.getElementById('board-dnd-live');
      if (liveEl) {
        const colName = columns.find((c) => c.column_id === columnId)?.name ?? 'column';
        liveEl.textContent = `Moved to ${colName}, position ${position}`;
      }
    },
    [moveItem, columns]
  );

  const onReorderColumn = useCallback(
    (columnId: string, orderedItemIds: string[]) => {
      reorderItems.mutate({ columnId, orderedItemIds });
      // Announce for screen readers
      const liveEl = document.getElementById('board-dnd-live');
      if (liveEl) {
        const colName = columns.find((c) => c.column_id === columnId)?.name ?? 'column';
        liveEl.textContent = `Reordered items in ${colName}`;
      }
    },
    [reorderItems, columns]
  );

  const onMove = useCallback(
    (itemId: string, toColumnId: string | null, position: number) => {
      moveItem.mutate({
        itemId,
        move: {
          column_id: toColumnId,
          position,
          expected_from_column_updated_at: null,
          expected_to_column_updated_at: null,
        },
      });
    },
    [moveItem]
  );

  const onOpen = useCallback(
    (openItemId: string) => {
      if (!projectId || !boardId) return;
      navigate(`/projects/${projectId}/boards/${boardId}/items/${openItemId}`);
    },
    [boardId, navigate, projectId]
  );

  const onCloseDrawer = useCallback(() => {
    if (!projectId || !boardId) return;
    pendingFocusItemIdRef.current = itemId ?? null;
    navigate(`/projects/${projectId}/boards/${boardId}`);
  }, [boardId, itemId, navigate, projectId]);

  const showCopyToast = useCallback((message: string, variant: 'success' | 'error' = 'success') => {
    if (copyToastTimerRef.current != null) {
      window.clearTimeout(copyToastTimerRef.current);
      copyToastTimerRef.current = null;
    }
    setCopyToast({ message, variant });
    copyToastTimerRef.current = window.setTimeout(() => {
      setCopyToast(null);
      copyToastTimerRef.current = null;
    }, 1700);
  }, []);

  useEffect(
    () => () => {
      if (copyToastTimerRef.current != null) {
        window.clearTimeout(copyToastTimerRef.current);
      }
    },
    []
  );

  useEffect(() => {
    if (itemId || !pendingFocusItemIdRef.current) return;
    const targetItemId = pendingFocusItemIdRef.current;
    pendingFocusItemIdRef.current = null;
    window.requestAnimationFrame(() => {
      const target = document.querySelector<HTMLElement>(`[data-item-id="${targetItemId}"]`);
      target?.focus();
    });
  }, [itemId]);

  const handleCopyWorkItemId = useCallback(
    async (value: string, displayId?: string) => {
      const textToCopy = displayId || value;
      const copied = await copyTextToClipboard(textToCopy);
      if (copied) {
        showCopyToast('Work item ID copied');
        return;
      }
      showCopyToast('Could not copy work item ID', 'error');
    },
    [showCopyToast]
  );

  const finalizePendingDelete = useCallback(
    async (request: PendingBoardDelete) => {
      clearDeleteTimer();
      setPendingDelete((current) => (current?.rootItemId === request.rootItemId ? null : current));
      try {
        await deleteItem.mutateAsync({ itemId: request.rootItemId, cascade: true });
        const linkedCount = Math.max(0, request.hiddenIds.length - 1);
        showCopyToast(
          linkedCount > 0
            ? `${request.rootType === 'goal' ? 'Goal' : request.rootType === 'feature' ? 'Feature' : 'Work item'} deleted with ${linkedCount} linked item${linkedCount === 1 ? '' : 's'}`
            : 'Work item deleted'
        );
      } catch {
        showCopyToast('Could not delete work item', 'error');
      }
    },
    [clearDeleteTimer, deleteItem, showCopyToast]
  );

  const requestDelete = useCallback(
    (targetItemId: string, source: 'drag' | 'keyboard') => {
      const target = workItems.find((item) => item.item_id === targetItemId);
      if (!target) return;

      if (pendingDelete && pendingDelete.rootItemId !== targetItemId) {
        void finalizePendingDelete(pendingDelete);
      }

      const nextDelete: PendingBoardDelete = {
        rootItemId: target.item_id,
        rootTitle: target.title,
        rootType: target.item_type,
        hiddenIds: collectCascadeDeleteIds(target.item_id),
        source,
      };

      clearDeleteTimer();
      setPendingDelete(nextDelete);
      setIsDeleteDockHovered(false);

      if (itemId && nextDelete.hiddenIds.includes(itemId)) {
        pendingFocusItemIdRef.current = target.item_id;
        navigate(`/projects/${projectId}/boards/${boardId}`);
      }

      deleteCommitTimerRef.current = window.setTimeout(() => {
        void finalizePendingDelete(nextDelete);
      }, 4200);
    },
    [boardId, clearDeleteTimer, collectCascadeDeleteIds, finalizePendingDelete, itemId, navigate, pendingDelete, projectId, workItems]
  );

  const undoPendingDelete = useCallback(() => {
    clearDeleteTimer();
    setPendingDelete(null);
    setIsDeleteDockHovered(false);
  }, [clearDeleteTimer]);

  const handleDeleteDockDragOver = useCallback((event: React.DragEvent<HTMLElement>) => {
    if (!draggedItemIdRef.current) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    if (!isDeleteDockHovered) {
      setIsDeleteDockHovered(true);
    }
  }, [isDeleteDockHovered]);

  const handleDeleteDockDragLeave = useCallback((event: React.DragEvent<HTMLElement>) => {
    const related = event.relatedTarget as Node | null;
    if (related && event.currentTarget.contains(related)) return;
    setIsDeleteDockHovered(false);
  }, []);

  const handleDeleteDockDrop = useCallback((event: React.DragEvent<HTMLElement>) => {
    event.preventDefault();
    draggedItemIdRef.current = null;
    setDraggedItemId(null);
    setIsDeleteDockHovered(false);
    setDropSettling(false);
    if (dropSettleTimerRef.current != null) {
      window.clearTimeout(dropSettleTimerRef.current);
      dropSettleTimerRef.current = null;
    }
    if (justDroppedTimerRef.current != null) {
      window.clearTimeout(justDroppedTimerRef.current);
      justDroppedTimerRef.current = null;
    }
    setJustDroppedItemId(null);
    const payload = parseDragPayload(event);
    if (!payload) return;
    requestDelete(payload.itemId, 'drag');
  }, [requestDelete]);

  const selectedItem = useMemo(() => {
    if (!itemId) return undefined;
    return items.find((i) => i.item_id === itemId);
  }, [itemId, items]);

  const onCreate = useCallback(
    (
      columnId: string,
      title: string,
      itemType: WorkItemType,
      options?: { priority?: WorkItemPriority },
      onCreated?: (itemId: string) => void,
    ) => {
      if (!projectId || !boardId) return;
      createItem.mutate(
        {
          item_type: itemType,
          project_id: projectId,
          board_id: boardId,
          column_id: columnId,
          title,
          priority: options?.priority ?? 'medium',
        },
        {
          onSuccess: (created) => {
            onCreated?.(created.item_id);
          },
        }
      );
    },
    [boardId, createItem, projectId]
  );

  const pageTitle = useMemo(() => {
    if (boardLoading) return 'Board';
    return board?.name ? board.name : 'Board';
  }, [board, boardLoading]);

  const projectTitle = useMemo(() => project?.name ?? 'Project', [project?.name]);
  const supplementarySettled = !participantsQuery.isFetching && !projectAgentsQuery.isFetching;
  const hasSupplementaryDataError = supplementarySettled && Boolean(participantsError || projectAgentsError);
  const hasWorkItemsLoadError = Boolean(itemsError);
  const showBlockingItemsError = hasWorkItemsLoadError && !itemsLoading && items.length === 0;
  const showPartialHydrationNotice = !showBlockingItemsError && (isPartial || isBackgroundHydrating) && totalItemCount > 0;
  const showHydrationAttention = showPartialHydrationNotice && !hydrationNoticeDismissed;

  useEffect(() => {
    if (!boardId || boardLoading || !board) return;
    if (boardPerfFlagsRef.current.shell === boardId) return;
    boardPerfFlagsRef.current.shell = boardId;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const elapsed_ms = Math.round(now - (boardPerfStartedAtRef.current ?? now));
    const payload = {
      board_id: boardId,
      project_id: projectId ?? null,
      elapsed_ms,
      filters_active: hasActiveFilters,
    };
    perfMark('board.shell_ready', payload);
    void razeLog('INFO', 'board.shell_ready', payload);
  }, [board, boardId, boardLoading, hasActiveFilters, projectId]);

  useEffect(() => {
    if (!boardId || itemsLoading || items.length === 0) return;
    if (boardPerfFlagsRef.current.firstPage === boardId) return;
    boardPerfFlagsRef.current.firstPage = boardId;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const elapsed_ms = Math.round(now - (boardPerfStartedAtRef.current ?? now));
    const payload = {
      board_id: boardId,
      project_id: projectId ?? null,
      elapsed_ms,
      loaded_count: loadedCount,
      total_count: totalItemCount,
      filters_active: hasActiveFilters,
      is_partial: isPartial,
    };
    perfMark('board.first_items_page_ready', payload);
    void razeLog('INFO', 'board.first_items_page_ready', payload);
  }, [boardId, hasActiveFilters, isPartial, items.length, itemsLoading, loadedCount, projectId, totalItemCount]);

  useEffect(() => {
    if (!boardId || items.length === 0 || isPartial || isBackgroundHydrating) return;
    if (boardPerfFlagsRef.current.full === boardId) return;
    boardPerfFlagsRef.current.full = boardId;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const elapsed_ms = Math.round(now - (boardPerfStartedAtRef.current ?? now));
    const payload = {
      board_id: boardId,
      project_id: projectId ?? null,
      elapsed_ms,
      loaded_count: loadedCount,
      total_count: totalItemCount,
      filters_active: hasActiveFilters,
    };
    perfMark('board.full_hydration_ready', payload);
    void razeLog('INFO', 'board.full_hydration_ready', payload);
  }, [boardId, hasActiveFilters, isBackgroundHydrating, isPartial, items.length, loadedCount, projectId, totalItemCount]);

  const setViewModeValue = useCallback((nextMode: ViewMode) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (nextMode === 'board') {
        next.delete('view');
      } else {
        next.set('view', nextMode);
      }
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  // ── Column Summary Strip helpers ──────────────────────────────────────────
  const currentUserId = useMemo(() => (actor?.type === 'human' ? actor.id : null), [actor?.id, actor?.type]);

  // ── Unified messages — DM from avatar / members sheet ─────────────────────
  const handleParticipantClick = useCallback(
    (participant: BoardParticipant) => {
      if (!projectId) return;
      if (unifiedChat?.dmParticipantId === participant.id) {
        return;
      }
      getOrCreateDM.mutate(
        {
          projectId,
          targetParticipantId: participant.id,
          actorType: participant.kind === 'agent' ? 'agent' : 'user',
        },
        {
          onSuccess: (result) => {
            setUnifiedChat({
              initialTarget: { mode: 'conversation', conversationId: result.conversation.id },
              key: Date.now(),
              dmParticipantId: participant.id,
            });
          },
        },
      );
    },
    [projectId, unifiedChat?.dmParticipantId, getOrCreateDM],
  );

  const openProjectRoomChat = useCallback(() => {
    setUnifiedChat({
      initialTarget: { mode: 'firstProjectRoom' },
      key: Date.now(),
    });
  }, []);

  const isMyWorkActive = useMemo(
    () => Boolean(currentUserId && filters.assigneeId === currentUserId && filters.assigneeType === 'user'),
    [currentUserId, filters.assigneeId, filters.assigneeType]
  );

  const handleToggleMyWork = useCallback(() => {
    if (isMyWorkActive) {
      filterState.setFilter('assigneeId', null);
      filterState.setFilter('assigneeType', null);
    } else if (currentUserId) {
      filterState.setFilter('assigneeId', currentUserId);
      filterState.setFilter('assigneeType', 'user');
    }
  }, [currentUserId, filterState, isMyWorkActive]);

  const handleJumpToColumn = useCallback((columnId: string) => {
    const container = boardColumnsRef.current;
    if (!container) return;
    const target = container.querySelector<HTMLElement>(`[data-column-id="${columnId}"]`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
    }
  }, []);

  useShellTitle(pageTitle);
  useShellMode('board');

  if (!projectId || !boardId) {
    return (
        <div className="board-page">
          <div className="board-error animate-fade-in-up">Missing project or board ID.</div>
        </div>
    );
  }

  return (
      <div
        ref={pageRef}
        className={`board-page board-page-density-compact${draggedItemId || dropSettling ? ' board-page-dragging' : ''}`}
      >
        <div className="board-sticky-chrome">

        {/* Unified toolbar: title + filters + density + settings */}
        {!boardLoading && board && columns.length > 0 && (
          <BoardFilterBar
            filterState={filterState}
            assignableHumans={assignableHumans}
            assignableAgents={assignableAgents}
            allLabels={allLabels}
            totalCount={items.length}
            matchCount={filterResult.matchCount}
            collapsed={scrolled && !filtersExpanded}
            onToggleExpand={() => setFiltersExpanded((prev) => !prev)}
            boardTitle={pageTitle}
            projectTitle={projectTitle}
            onBack={() => navigate(`/projects/${projectId}`)}
            viewMode={viewMode}
            onViewChange={setViewModeValue}
            onSettings={() => navigate(`/projects/${projectId}/settings`)}
            isMyWorkActive={isMyWorkActive}
            onToggleMyWork={currentUserId ? handleToggleMyWork : undefined}
            onRefresh={refetchItems}
            isRefreshing={isRefreshing}
            lastSyncedAt={lastSyncedAt}
          />
        )}
        </div>{/* end board-sticky-chrome */}

        {/* Collaboration dock — fixed bottom-center */}
        {boardParticipants && boardParticipants.length > 0 && (
          <div
            className={`board-collab-dock-wrap${draggedItemId ? ' board-collab-dock-wrap--passive' : ''}`}
          >
            <div
              className={`board-chathub-card${draggedItemId ? '' : ' board-chathub-card--floaty'}${membersSheetOpen || Boolean(unifiedChat) ? ' board-chathub-card--active' : ''}`}
            >
              <ChatHub
                participants={boardParticipants ?? []}
                memberCount={boardParticipants.length}
                onOpenMembersSheet={() => setMembersSheetOpen(true)}
                onParticipantClick={handleParticipantClick}
                membersLauncherRef={collabDockLauncherRef}
                active={membersSheetOpen || Boolean(unifiedChat)}
              />
            </div>
          </div>
        )}

        {!boardLoading && board && columns.length > 0 && hasSupplementaryDataError && (
          <div className="board-warning animate-fade-in-up" role="status" aria-live="polite">
            Some project-side data is unavailable right now. Work items can still load, but agent assignments or member details may be incomplete.
          </div>
        )}

        {!boardLoading && board && columns.length > 0 && showHydrationAttention && (
          <div className="board-hydration-hint" role="status" aria-live="polite">
            <span className="board-hydration-hint-text">
              Loading board… {loadedCount} / {totalItemCount} items
            </span>
            {isPartial && (
              <button
                type="button"
                className="board-hydration-hint-action pressable"
                onClick={() => void loadMore()}
                data-haptic="light"
              >
                Load more
              </button>
            )}
            <button
              type="button"
              className="board-hydration-hint-dismiss pressable"
              aria-label="Dismiss loading notice"
              onClick={dismissHydrationNotice}
              data-haptic="light"
            >
              ×
            </button>
          </div>
        )}

        {/* Phase 1: Show skeleton immediately while board structure loads */}
        {boardLoading && (
          <BoardSkeleton columnCount={5} />
        )}

        {!boardLoading && board && columns.length === 0 && (
          <div className="board-empty animate-fade-in-up" role="status">
            <h2 className="board-empty-title">No columns</h2>
            <p className="board-empty-description">Create the board with default columns to get the full flow.</p>
            <button type="button" className="board-empty-action pressable" onClick={() => navigate(`/projects/${projectId}`)} data-haptic="light">
              Back to project
            </button>
          </div>
        )}

        {!boardLoading && board && columns.length > 0 && showBlockingItemsError && (
          <div className="board-error animate-fade-in-up" role="alert">
            <h2 className="board-error-title">Could not load work items</h2>
            <p className="board-error-description">
              The board shell loaded, but the work-item request failed. This is likely a session or backend data issue, not an empty board.
            </p>
            <button
              type="button"
              className="board-error-action pressable"
              onClick={() => void refetchItems()}
              data-haptic="light"
            >
              Retry work items
            </button>
          </div>
        )}

        {!boardLoading && board && columns.length > 0 && !showBlockingItemsError && viewMode === 'board' && (
          <>
          <ColumnSummaryStrip
            columns={columns}
            itemsByColumnId={itemsByColumnId}
            filterResult={filterResult}
            visibleColumnIds={visibleColumnIds}
            onJumpToColumn={handleJumpToColumn}
          />
          <div ref={boardColumnsRef} className="board-columns" aria-label="Board columns">
            {columns.map((col, index) => (
              <ColumnLane
                key={col.column_id}
                column={col}
                accentIndex={getColumnAccentIndex(index)}
                items={itemsByColumnId[col.column_id] ?? EMPTY_ITEMS}
                assigneeIndex={assigneeIndex}
                executionByItemId={executionByItemId}
                executionAvailable={executionAvailable}
                childTaskCountByParent={childTaskCountByParent}
                featureCountByGoal={featureCountByGoal}
                taskCountByGoal={taskCountByGoal}
                progressByItemId={progressByItemId}
                onCreate={onCreate}
                onOpen={onOpen}
                onStartExecution={handleStartExecution}
                onCancelExecution={handleCancelExecution}
                onCopyWorkItemId={handleCopyWorkItemId}
                onRequestDelete={requestDelete}
                isStartPending={executeWorkItem.isPending}
                isCancelPending={cancelExecution.isPending}
                onDropToColumn={onDropToColumn}
                onMoveToPosition={onMoveToPosition}
                onReorderColumn={onReorderColumn}
                draggedItemId={draggedItemId}
                justDroppedItemId={justDroppedItemId}
                onDragStart={onDragStart}
                onDragEnd={onDragEnd}
                selectedItemId={itemId}
                projectSlug={project?.slug}
                boardId={boardId}
                assignableHumans={assignableHumans}
                assignableAgents={assignableAgents}
                currentUserId={currentUserId}
                matchingIds={filterResult.matchingIds}
                ancestorIds={filterResult.ancestorIds}
                isFiltered={filterResult.isFiltered}
                itemsLoading={itemsLoading}
                itemDiffMap={itemDiffMap}
                deferColumnVirtualization={isPartial || isBackgroundHydrating}
              />
            ))}
          </div>
          {/* Screen-reader announcements for drag-and-drop */}
          <div className="sr-only" aria-live="assertive" aria-atomic="true" id="board-dnd-live" />
          </>
        )}

        {!boardLoading && board && columns.length > 0 && !showBlockingItemsError && viewMode === 'outline' && (
          <OutlineView
            items={items}
            columns={columns}
            itemsByColumnId={itemsByColumnId}
            assigneeIndex={assigneeIndex}
            filterResult={filterResult}
            projectSlug={project?.slug}
            onOpen={onOpen}
            onCopyWorkItemId={handleCopyWorkItemId}
          />
        )}

        {viewMode === 'board' && draggedItemId && (
          <div
            className={`board-delete-dock${isDeleteDockHovered ? ' board-delete-dock-active' : ''}`}
            onDragOver={handleDeleteDockDragOver}
            onDragLeave={handleDeleteDockDragLeave}
            onDrop={handleDeleteDockDrop}
            aria-label="Drop here to delete work item"
          >
            <div className="board-delete-dock-icon-shell" aria-hidden="true">
              <TrashIcon className="board-delete-dock-icon" />
            </div>
            <div className="board-delete-dock-copy">
              <div className="board-delete-dock-title">
                {isDeleteDockHovered ? 'Release to delete' : 'Drop here to delete'}
              </div>
              <div className="board-delete-dock-subtitle">Nothing is permanent right away. You can undo.</div>
            </div>
          </div>
        )}

        {pendingDelete && (
          <div className="board-delete-undo-bar" role="status" aria-live="polite">
            <div className="board-delete-undo-copy">
              <div className="board-delete-undo-title">
                {pendingDelete.rootType === 'goal'
                  ? 'Goal moved to trash'
                  : pendingDelete.rootType === 'feature'
                    ? 'Feature moved to trash'
                    : 'Work item moved to trash'}
              </div>
              <div className="board-delete-undo-subtitle">
                {pendingDelete.hiddenIds.length > 1
                  ? `${pendingDelete.hiddenIds.length - 1} linked item${pendingDelete.hiddenIds.length === 2 ? '' : 's'} will be deleted too.`
                  : 'This will disappear after a short grace period.'}
              </div>
            </div>
            <button
              type="button"
              className="board-delete-undo-action pressable"
              onClick={undoPendingDelete}
              data-haptic="light"
            >
              Undo
            </button>
          </div>
        )}

        {itemId && (
          <WorkItemDrawer
            projectId={projectId}
            orgId={project?.org_id ?? null}
            boardId={boardId}
            itemId={itemId}
            projectSlug={project?.slug}
            columns={columns}
            targetPositions={targetPositions}
            initialItem={selectedItem}
            assigneeIndex={assigneeIndex}
            assignableHumans={assignableHumans}
            assignableAgents={assignableAgents}
            assignmentHint={assignmentHint}
            onMove={onMove}
            onCopyWorkItemId={handleCopyWorkItemId}
            onNotify={showCopyToast}
            onRequestClose={onCloseDrawer}
          />
        )}

        {/* ChatHub presence card rendered above, after board-sticky-chrome */}

        <AgentPresenceDrawer
          participants={boardParticipants}
          open={membersSheetOpen}
          onClose={() => setMembersSheetOpen(false)}
          onProjectRoom={openProjectRoomChat}
          onParticipantClick={(p) => {
            setMembersSheetOpen(false);
            handleParticipantClick(p);
          }}
          onManage={() => {
            setMembersSheetOpen(false);
            setAssignmentDrawerOpen(true);
          }}
        />

        <AgentAssignmentDrawer
          presences={agentPresences}
          projectAgents={projectAgents}
          projectId={projectId ?? ''}
          open={assignmentDrawerOpen}
          onClose={() => setAssignmentDrawerOpen(false)}
        />

        {unifiedChat && (
          <div
            className={`board-collab-chat-anchor${draggedItemId ? ' board-collab-chat-anchor--passive' : ''}`}
          >
            <UnifiedConversationWindow
              projectId={projectId ?? ''}
              orgId={project?.org_id ?? null}
              currentUserId={currentUserId ?? undefined}
              initialTarget={unifiedChat.initialTarget}
              initialTargetKey={unifiedChat.key}
              onClose={() => setUnifiedChat(null)}
            />
          </div>
        )}

        {copyToast && (
          <div className={`board-copy-toast board-copy-toast-${copyToast.variant}`} role="status" aria-live="polite">
            {copyToast.message}
          </div>
        )}
      </div>
  );
}
