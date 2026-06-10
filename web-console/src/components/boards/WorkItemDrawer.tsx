/**
 * Work item detail panel (full layout)
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student):
 * - Fast, optimistic edits
 * - 60fps transforms for motion (no layout animations)
 * - Accessible keyboard interactions (Escape to close, focus-visible)
 */

import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { type ExecutionStatus, type ExecutionStep } from '../../lib/collab-client';
import {
  type BoardColumn,
  type UpdateWorkItemRequest,
  type WorkItem,
  type WorkItemComment,
  type WorkItemCommentAuthorType,
  type WorkItemPriority,
  useWorkItems,
  useAssignWorkItem,
  useCompleteWithDescendants,
  usePostWorkItemComment,
  useUnassignWorkItem,
  useUpdateWorkItem,
  useWorkItemComments,
  useWorkItem,
  useWorkItemProgressRollup,
} from '../../api/boards';
import { useProject } from '../../api/dashboard';
import { type AvailableLLMModel, useProjectModels } from '../../api/conversations';
import {
  useApproveGate,
  useCancelWorkItemExecution,
  useExecuteWorkItem,
  useExecutionSteps,
  useExecutionStream,
  useProvideClarification,
  useWorkItemExecutionStatus,
} from '../../api/executions';
import { useAuth } from '../../auth';
import { ActorAvatar } from '../actors/ActorAvatar';
import type { ActorViewModel } from '../../types/actor';
import { buildExecutionControlModel } from '../../lib/executionControls';
import { toActorViewModel } from '../../utils/actorViewModel';
import { copyTextToClipboard, formatWorkItemDisplayId } from './workItemId';
import type { PresenceState } from '../../hooks/useAgentPresence';
import { InlineAssigneePopover } from './InlineAssigneePopover';
import { RollupProgressInline } from './RollupProgressInline';
import { formatRemainingSummary } from './rollupProgressDisplay';
import { ExecutionProgress } from './execution/ExecutionProgress';
import { researchIngestFailureSuggestsBodyPaste } from './researchIngestHints';
import { CompactLoadingShimmer, WorkItemDrawerBodySkeleton } from '../loading';
import './WorkItemDrawer.css';

const EMPTY_EXECUTION_STEPS: readonly ExecutionStep[] = [];
const EMPTY_LLM_MODELS: readonly AvailableLLMModel[] = [];

type DrawerPhase = 'entering' | 'open' | 'closing';
type SaveState = 'idle' | 'saving' | 'saved' | 'copied' | 'error';
type WorkItemActivityFilter = 'all' | 'humans' | 'agents' | 'system';
type NumberField = 'points' | 'estimated_hours' | 'actual_hours';
type DateField = 'due_date' | 'start_date' | 'target_date';

interface WorkItemActivityEntry {
  id: string;
  kind: 'comment';
  actorType: 'user' | 'agent' | 'system';
  timestamp: string | null;
  sortTime: number;
  title: string;
  body: string;
  meta?: string;
  comment?: WorkItemComment;
}

function labelForType(itemType: WorkItem['item_type']): string {
  if (itemType === 'task') return 'Task';
  if (itemType === 'feature') return 'Feature';
  if (itemType === 'bug') return 'Bug';
  if (itemType === 'research') return 'Research';
  return 'Goal';
}

function getResearchUrl(item?: WorkItem | null): string {
  const value = item?.metadata?.research_url;
  return typeof value === 'string' ? value : '';
}

function getResearchBodyMarkdown(item?: WorkItem | null): string {
  const value = item?.metadata?.research_body_markdown;
  return typeof value === 'string' ? value : '';
}

function shortId(itemOrId: string | { item_id: string; display_number?: number | null }, projectSlug?: string | null): string {
  return formatWorkItemDisplayId(itemOrId, projectSlug);
}

function formatRelativeTime(dateString?: string | null): string {
  if (!dateString) return 'Unknown';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return 'Unknown';
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

function formatAbsoluteDate(dateString?: string | null): string {
  if (!dateString) return 'No date';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return 'No date';
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function normalizeLabel(input: string): string {
  return input.trim().replace(/\s+/g, '-').toLowerCase();
}

function shortenAssigneeId(id: string): string {
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

function toStatusLabel(status?: string | null): string {
  if (!status) return 'Unknown';
  return status.replace(/_/g, ' ');
}

function toTitleCase(input: string): string {
  return input.replace(/\b\w/g, (char) => char.toUpperCase());
}

function toDateInputValue(value?: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function toIsoDateValue(nextDate: string, existing?: string | null): string | null {
  if (!nextDate) return null;
  const existingDate = existing ? new Date(existing) : new Date();
  const base = Number.isNaN(existingDate.getTime()) ? new Date() : existingDate;
  const [yearRaw, monthRaw, dayRaw] = nextDate.split('-');
  const year = Number(yearRaw);
  const month = Number(monthRaw);
  const day = Number(dayRaw);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
  base.setFullYear(year, month - 1, day);
  if (!existing) {
    base.setHours(17, 0, 0, 0);
  }
  return base.toISOString();
}

function toNumberDraft(value?: string | number | null): string {
  if (value == null) return '';
  return String(value);
}

function parseNumberDraft(value: string, kind: NumberField): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = kind === 'points' ? Number.parseInt(trimmed, 10) : Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

function getProjectDefaultModelId(settings?: Record<string, unknown> | null): string {
  const raw = settings?.agent_model_preferences;
  if (!raw || typeof raw !== 'object') return '';
  const value = (raw as { default_model_id?: unknown }).default_model_id;
  return typeof value === 'string' ? value : '';
}

/** Maps a child work item to a coarse progress bucket for drawer UI. */
export type ChildProgressBucket = 'not_started' | 'in_progress' | 'done';

export function bucketForChild(child: WorkItem, boardColumns: BoardColumn[]): ChildProgressBucket {
  const column = boardColumns.find((c) => c.column_id === child.column_id);
  const mapping = column?.status_mapping;
  if (mapping === 'in_progress' || mapping === 'in_review') return 'in_progress';
  if (mapping === 'done') return 'done';
  if (mapping === 'backlog') return 'not_started';
  if (child.status === 'done') return 'done';
  if (child.status === 'in_progress' || child.status === 'in_review') return 'in_progress';
  return 'not_started';
}

const CHILD_BUCKET_ORDER: Record<ChildProgressBucket, number> = {
  in_progress: 0,
  not_started: 1,
  done: 2,
};

export function compareChildrenByStatus(a: WorkItem, b: WorkItem, boardColumns: BoardColumn[]): number {
  const bucketA = bucketForChild(a, boardColumns);
  const bucketB = bucketForChild(b, boardColumns);
  const diff = CHILD_BUCKET_ORDER[bucketA] - CHILD_BUCKET_ORDER[bucketB];
  if (diff !== 0) return diff;
  return (a.position ?? 0) - (b.position ?? 0);
}

const HERO_DESCRIPTION_COLLAPSE_MAX = 2000;

function heroDescriptionCollapsePreview(text: string): string {
  const t = text.trim();
  if (t.length <= HERO_DESCRIPTION_COLLAPSE_MAX) return t;
  return `${t.slice(0, HERO_DESCRIPTION_COLLAPSE_MAX - 1)}…`;
}

function priorityHeroChipClass(priority: WorkItemPriority): string {
  switch (priority) {
    case 'critical':
      return 'hero-chip-priority--critical';
    case 'high':
      return 'hero-chip-priority--high';
    case 'low':
      return 'hero-chip-priority--low';
    case 'medium':
    default:
      return 'hero-chip-priority--medium';
  }
}

/** Visual urgency for the due-date chip from YYYY-MM-DD (local calendar days). */
function dueDateHeroChipClass(ymd: string): string {
  const raw = ymd?.trim();
  if (!raw) return 'hero-chip-due--empty';
  const parts = raw.split('-');
  if (parts.length !== 3) return 'hero-chip-due--empty';
  const y = Number(parts[0]);
  const m = Number(parts[1]);
  const d = Number(parts[2]);
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return 'hero-chip-due--empty';
  const due = new Date(y, m - 1, d);
  const today = new Date();
  const startOfDue = new Date(due.getFullYear(), due.getMonth(), due.getDate()).getTime();
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const diffDays = Math.round((startOfDue - startOfToday) / 86400000);
  if (diffDays < 0) return 'hero-chip-due--overdue';
  if (diffDays === 0) return 'hero-chip-due--today';
  if (diffDays <= 7) return 'hero-chip-due--soon';
  return 'hero-chip-due--later';
}

function bucketCssClass(bucket: ChildProgressBucket): string {
  return bucket.replace(/_/g, '-');
}

/** Short progress label for child rows (from bucket, not raw work item status strings). */
export function labelForChildBucket(bucket: ChildProgressBucket): string {
  if (bucket === 'in_progress') return 'In progress';
  if (bucket === 'done') return 'Done';
  return 'Backlog';
}

function summarizeExecution(status: ExecutionStatus | null, hasAgentAssignment: boolean): string {
  return buildExecutionControlModel({
    rawState: status?.state ?? null,
    hasExecution: status?.hasExecution,
    hasAgentAssignment,
    pendingClarificationCount: status?.pendingClarifications?.length ?? 0,
  }).summary;
}

function useDebouncedCallback(callback: () => void, delayMs: number) {
  const timerRef = useRef<number | null>(null);

  const cancel = useCallback(() => {
    if (timerRef.current == null) return;
    window.clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const schedule = useCallback(() => {
    cancel();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      callback();
    }, delayMs);
  }, [callback, cancel, delayMs]);

  useEffect(() => cancel, [cancel]);

  return useMemo(() => ({ schedule, cancel }), [cancel, schedule]);
}

export interface AssigneeProfile {
  id: string;
  type: 'user' | 'agent';
  label: string;
  subtitle?: string;
  status?: string;
  avatar?: string;
  actor?: ActorViewModel;
  presence?: PresenceState;
  presenceLabel?: string;
  activeItemCount?: number;
}

export interface WorkItemDrawerProps {
  projectId: string;
  projectSlug?: string | null;
  orgId?: string | null;
  boardId: string;
  itemId: string;
  columns: BoardColumn[];
  targetPositions: Record<string, number>;
  initialItem?: WorkItem;
  assigneeIndex: Map<string, AssigneeProfile>;
  assignableHumans: AssigneeProfile[];
  assignableAgents: AssigneeProfile[];
  assignmentHint?: string;
  onMove: (itemId: string, toColumnId: string | null, position: number) => void;
  onCopyWorkItemId: (itemId: string, displayId?: string) => void;
  onNotify: (message: string, variant?: 'success' | 'error') => void;
  onRequestClose: () => void;
  onOpenItem?: (itemId: string) => void;
}

export function WorkItemDrawer({
  projectId,
  projectSlug,
  orgId,
  boardId,
  itemId,
  columns,
  targetPositions,
  initialItem,
  assigneeIndex,
  assignableHumans,
  assignableAgents,
  assignmentHint,
  onMove,
  onCopyWorkItemId,
  onNotify,
  onRequestClose,
  onOpenItem,
}: WorkItemDrawerProps): React.JSX.Element {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const titleRef = useRef<HTMLInputElement | null>(null);
  const heroDescriptionTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);
  const commentEndRef = useRef<HTMLDivElement | null>(null);
  const lastHydratedItemIdRef = useRef<string | null>(null);

  const { actor } = useAuth();

  const [phase, setPhase] = useState<DrawerPhase>('entering');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [titleDraft, setTitleDraft] = useState(initialItem?.title ?? '');
  const [descriptionDraft, setDescriptionDraft] = useState(initialItem?.description ?? '');
  const [priorityDraft, setPriorityDraft] = useState<WorkItemPriority>(initialItem?.priority ?? 'medium');
  const [labels, setLabels] = useState<string[]>(initialItem?.labels ?? []);
  const [newLabelDraft, setNewLabelDraft] = useState('');
  const [commentDraft, setCommentDraft] = useState('');
  const [activityFilter, setActivityFilter] = useState<WorkItemActivityFilter>('all');
  const [showAssigneePicker, setShowAssigneePicker] = useState(false);
  const [showAdvancedDetails, setShowAdvancedDetails] = useState(false);
  const [showCascadeModal, setShowCascadeModal] = useState(false);
  const [heroDescriptionInlineOpen, setHeroDescriptionInlineOpen] = useState(false);
  const [pendingColumnChange, setPendingColumnChange] = useState<{ toColumnId: string | null; position: number } | null>(null);
  const [dueDateDraft, setDueDateDraft] = useState(toDateInputValue(initialItem?.due_date));
  const [startDateDraft, setStartDateDraft] = useState(toDateInputValue(initialItem?.start_date));
  const [targetDateDraft, setTargetDateDraft] = useState(toDateInputValue(initialItem?.target_date));
  const [pointsDraft, setPointsDraft] = useState(toNumberDraft(initialItem?.points ?? initialItem?.story_points ?? null));
  const [estimatedHoursDraft, setEstimatedHoursDraft] = useState(toNumberDraft(initialItem?.estimated_hours ?? null));
  const [actualHoursDraft, setActualHoursDraft] = useState(toNumberDraft(initialItem?.actual_hours ?? null));
  const [researchUrlDraft, setResearchUrlDraft] = useState(getResearchUrl(initialItem));
  const [researchBodyDraft, setResearchBodyDraft] = useState(getResearchBodyMarkdown(initialItem));
  const [executionModelOverride, setExecutionModelOverride] = useState('');

  const updateItem = useUpdateWorkItem(boardId);
  const assignItem = useAssignWorkItem(boardId);
  const unassignItem = useUnassignWorkItem(boardId);
  const completeWithDescendants = useCompleteWithDescendants(boardId);
  const { data: item, isLoading, isError } = useWorkItem(itemId, initialItem);
  const { data: project } = useProject(projectId);
  const projectDefaultModelId = getProjectDefaultModelId(project?.settings ?? null);
  const { data: projectModels, isLoading: modelsLoading } = useProjectModels(projectId, {
    orgId: project?.org_id ?? orgId ?? null,
    userId: actor?.id,
    preferUser: true,
  });
  const progressRollupQuery = useWorkItemProgressRollup(itemId, {
    includeIncompleteDescendants: true,
    enabled: Boolean(itemId),
  });
  const { data: boardItems = [] } = useWorkItems(boardId);
  const commentsQuery = useWorkItemComments(itemId, { limit: 200 });
  const postComment = usePostWorkItemComment(itemId);
  const executeWorkItem = useExecuteWorkItem();
  const cancelExecution = useCancelWorkItemExecution();
  const provideClarification = useProvideClarification();
  const approveGate = useApproveGate();

  const executionStatusQuery = useWorkItemExecutionStatus(itemId, orgId, projectId);
  const executionStatus = executionStatusQuery.data ?? null;
  const executionState = executionStatus?.state ? String(executionStatus.state).toLowerCase() : null;
  const activeExecution =
    executionState === 'running' ||
    executionState === 'paused' ||
    executionState === 'pending' ||
    executionState === 'queued' ||
    Boolean(executionStatus?.pendingClarifications?.length);
  const { isConnected: executionStreamConnected, connectionState: executionConnectionState } = useExecutionStream({
    runId: executionStatus?.runId ?? null,
    orgId: orgId ?? null,
    projectId,
    enabled: Boolean(orgId && projectId),
  });
  const executionStepsQuery = useExecutionSteps(executionStatus?.runId ?? null, orgId, projectId, {
    enabled: Boolean(executionStatus?.runId && projectId),
    refetchInterval: executionStreamConnected ? false : activeExecution ? 2000 : false,
  });
  const executionSteps = useMemo(
    () => executionStepsQuery.data?.steps ?? EMPTY_EXECUTION_STEPS,
    [executionStepsQuery.data],
  );
  const availableModels = useMemo(
    () => projectModels?.models ?? EMPTY_LLM_MODELS,
    [projectModels?.models],
  );
  const effectiveExecutionModelId = executionModelOverride || projectDefaultModelId;
  const effectiveExecutionModel = useMemo(
    () => availableModels.find((model) => model.model_id === effectiveExecutionModelId) ?? null,
    [availableModels, effectiveExecutionModelId],
  );

  const showResearchBodyPasteHint = useMemo(
    () => researchIngestFailureSuggestsBodyPaste(executionStatus),
    [executionStatus],
  );

  const isOpen = phase === 'open' || phase === 'entering';
  const typeLabel = useMemo(() => (item ? labelForType(item.item_type) : 'Work item'), [item]);
  const parentLabel = useMemo(() => (item?.item_type === 'task' || item?.item_type === 'bug' ? 'Feature' : 'Goal'), [item?.item_type]);

  const parentCandidates = useMemo(() => {
    if (!item) return [];
    const targetType = item.item_type === 'task' || item.item_type === 'bug'
      ? 'feature'
      : item.item_type === 'feature'
        ? 'goal'
        : null;
    if (!targetType) return [];
    return boardItems.filter((candidate) => candidate.item_type === targetType && candidate.item_id !== item.item_id);
  }, [boardItems, item]);

  const parentItem = useMemo(() => {
    if (!item?.parent_id) return null;
    return boardItems.find((candidate) => candidate.item_id === item.parent_id) ?? null;
  }, [boardItems, item]);

  const childItems = useMemo(() => {
    if (!item) return [];
    if (item.item_type === 'feature') {
      return boardItems.filter((candidate) => candidate.parent_id === item.item_id && candidate.item_type === 'task');
    }
    if (item.item_type === 'goal') {
      return boardItems.filter((candidate) => candidate.parent_id === item.item_id && candidate.item_type === 'feature');
    }
    return [];
  }, [boardItems, item]);

  const columnNameById = useMemo(() => new Map(columns.map((c) => [c.column_id, c.name])), [columns]);

  const sortedStudioChildren = useMemo(
    () => [...childItems].sort((a, b) => compareChildrenByStatus(a, b, columns)),
    [childItems, columns],
  );

  useEffect(() => {
    prevFocusRef.current = document.activeElement as HTMLElement | null;
    const id = window.requestAnimationFrame(() => setPhase('open'));
    return () => window.cancelAnimationFrame(id);
  }, [itemId]);

  useEffect(() => {
    if (!isOpen) return;
    const id = window.requestAnimationFrame(() => {
      titleRef.current?.focus();
      titleRef.current?.select();
    });
    return () => window.cancelAnimationFrame(id);
  }, [isOpen]);

  useEffect(() => {
    return () => {
      prevFocusRef.current?.focus?.();
    };
  }, []);

  useEffect(() => {
    if (!item) return;
    if (item.item_id === lastHydratedItemIdRef.current) return;
    lastHydratedItemIdRef.current = item.item_id;
    queueMicrotask(() => {
      setTitleDraft(item.title);
      setDescriptionDraft(item.description ?? '');
      setPriorityDraft(item.priority);
      setLabels(item.labels ?? []);
      setDueDateDraft(toDateInputValue(item.due_date));
      setStartDateDraft(toDateInputValue(item.start_date));
      setTargetDateDraft(toDateInputValue(item.target_date));
      setPointsDraft(toNumberDraft(item.points ?? item.story_points ?? null));
      setEstimatedHoursDraft(toNumberDraft(item.estimated_hours ?? null));
      setActualHoursDraft(toNumberDraft(item.actual_hours ?? null));
      setResearchUrlDraft(getResearchUrl(item));
      setResearchBodyDraft(getResearchBodyMarkdown(item));
      setShowAssigneePicker(false);
      setShowAdvancedDetails(false);
      setSaveState('idle');
      setHeroDescriptionInlineOpen(false);
    });
  }, [item]);

  useLayoutEffect(() => {
    if (!heroDescriptionInlineOpen) return;
    heroDescriptionTextareaRef.current?.focus({ preventScroll: true });
  }, [heroDescriptionInlineOpen]);

  useEffect(() => {
    queueMicrotask(() => {
      setCommentDraft('');
      setActivityFilter('all');
      setHeroDescriptionInlineOpen(false);
    });
  }, [itemId]);

  const requestClose = useCallback(() => {
    if (phase === 'closing') return;
    setPhase('closing');
    window.setTimeout(() => onRequestClose(), 220);
  }, [onRequestClose, phase]);

  useEffect(() => {
    if (!isOpen || !overlayRef.current) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        requestClose();
        return;
      }

      if (event.key !== 'Tab' || !overlayRef.current) return;

      const focusable = overlayRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable.length) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;

      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
        return;
      }

      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, requestClose]);

  const doPatch = useCallback(
    (patch: UpdateWorkItemRequest) => {
      if (!itemId) return;
      setSaveState('saving');
      updateItem.mutate(
        { itemId, patch },
        {
          onSuccess: () => {
            setSaveState('saved');
            window.setTimeout(() => setSaveState('idle'), 1100);
          },
          onError: () => setSaveState('error'),
        }
      );
    },
    [itemId, updateItem]
  );

  const debouncedSave = useDebouncedCallback(() => {
    if (!item) return;
    const nextTitle = titleDraft.trim();
    if (!nextTitle) return;

    const patch: UpdateWorkItemRequest = {};
    if (nextTitle !== item.title) patch.title = nextTitle;
    if ((descriptionDraft ?? '') !== (item.description ?? '')) patch.description = descriptionDraft;

    if (Object.keys(patch).length > 0) doPatch(patch);
  }, 350);

  const handleOverlayMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (event.target === overlayRef.current) {
        requestClose();
      }
    },
    [requestClose]
  );

  const incompleteDescendantsCount = useMemo(() => {
    const rollup = progressRollupQuery.data;
    if (!rollup?.incomplete_items) return 0;
    return rollup.incomplete_items.length;
  }, [progressRollupQuery.data]);

  const handleColumnChange = useCallback(
    (event: React.ChangeEvent<HTMLSelectElement>) => {
      const value = event.target.value;
      const toColumnId = value === '__none__' ? null : value;
      const position = toColumnId ? (targetPositions[toColumnId] ?? 0) : 0;

      if (toColumnId) {
        const targetColumn = columns.find((column) => column.column_id === toColumnId);
        const isMovingToDone = targetColumn?.status_mapping === 'done';
        if (isMovingToDone && incompleteDescendantsCount > 0) {
          setPendingColumnChange({ toColumnId, position });
          setShowCascadeModal(true);
          return;
        }
      }

      onMove(itemId, toColumnId, position);
    },
    [columns, incompleteDescendantsCount, itemId, onMove, targetPositions]
  );

  const handleCascadeConfirm = useCallback(async () => {
    if (!pendingColumnChange) return;
    setShowCascadeModal(false);

    try {
      await completeWithDescendants.mutateAsync(itemId);
    } catch {
      onNotify('Failed to update child items', 'error');
    }

    onMove(itemId, pendingColumnChange.toColumnId, pendingColumnChange.position);
    setPendingColumnChange(null);
  }, [completeWithDescendants, itemId, onMove, onNotify, pendingColumnChange]);

  const handleCascadeCancel = useCallback(() => {
    if (!pendingColumnChange) return;
    setShowCascadeModal(false);
    onMove(itemId, pendingColumnChange.toColumnId, pendingColumnChange.position);
    setPendingColumnChange(null);
  }, [itemId, onMove, pendingColumnChange]);

  const handleCascadeModalClose = useCallback(() => {
    setShowCascadeModal(false);
    setPendingColumnChange(null);
  }, []);

  const handlePriorityChange = useCallback(
    (event: React.ChangeEvent<HTMLSelectElement>) => {
      const next = event.target.value as WorkItemPriority;
      setPriorityDraft(next);
      doPatch({ priority: next });
    },
    [doPatch]
  );

  const handleParentChange = useCallback(
    (event: React.ChangeEvent<HTMLSelectElement>) => {
      if (!item) return;
      const value = event.target.value;
      const nextParent = value === '__none__' ? null : value;
      if (nextParent === item.parent_id) return;
      doPatch({ parent_id: nextParent });
    },
    [doPatch, item]
  );

  const handleTitleChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setTitleDraft(event.target.value);
      debouncedSave.schedule();
    },
    [debouncedSave]
  );

  const handleDescriptionChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      setDescriptionDraft(event.target.value);
      debouncedSave.schedule();
    },
    [debouncedSave]
  );

  const handleResearchUrlBlur = useCallback(() => {
    if (!item || item.item_type !== 'research') return;
    const nextUrl = researchUrlDraft.trim();
    if (nextUrl === getResearchUrl(item)) return;
    doPatch({
      metadata: {
        ...(item.metadata ?? {}),
        research_url: nextUrl,
      },
    });
  }, [doPatch, item, researchUrlDraft]);

  const handleResearchBodyBlur = useCallback(() => {
    if (!item || item.item_type !== 'research') return;
    const nextBody = researchBodyDraft;
    const prev = getResearchBodyMarkdown(item);
    if (nextBody === prev) return;
    doPatch({
      metadata: {
        ...(item.metadata ?? {}),
        research_body_markdown: nextBody.trim() === '' ? null : nextBody,
      },
    });
  }, [doPatch, item, researchBodyDraft]);

  const handleDateChange = useCallback(
    (field: DateField, nextValue: string) => {
      if (!item) return;
      const storedValue = toIsoDateValue(nextValue, item[field] ?? null);
      if (field === 'due_date') setDueDateDraft(nextValue);
      if (field === 'start_date') setStartDateDraft(nextValue);
      if (field === 'target_date') setTargetDateDraft(nextValue);
      doPatch({ [field]: storedValue } as UpdateWorkItemRequest);
    },
    [doPatch, item]
  );

  const handleNumberBlur = useCallback(
    (field: NumberField, draft: string) => {
      if (!item) return;
      const nextValue = parseNumberDraft(draft, field);
      const currentRaw = field === 'points'
        ? (item.points ?? item.story_points ?? null)
        : item[field];
      const currentValue = currentRaw == null ? null : Number(currentRaw);
      if (nextValue === currentValue) return;
      doPatch({ [field]: nextValue } as UpdateWorkItemRequest);
    },
    [doPatch, item]
  );

  const handleLabelsRemove = useCallback(
    (label: string) => {
      setLabels((current) => {
        const next = current.filter((entry) => entry !== label);
        doPatch({ labels: next });
        return next;
      });
    },
    [doPatch]
  );

  const handleNewLabelCommit = useCallback(() => {
    const normalized = normalizeLabel(newLabelDraft);
    if (!normalized) return;
    if (labels.includes(normalized)) {
      setNewLabelDraft('');
      return;
    }
    const next = [...labels, normalized];
    setLabels(next);
    setNewLabelDraft('');
    doPatch({ labels: next });
  }, [doPatch, labels, newLabelDraft]);

  const handleNewLabelKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        handleNewLabelCommit();
      }
    },
    [handleNewLabelCommit]
  );

  const itemUrl = useMemo(() => {
    return `${window.location.origin}/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}/items/${encodeURIComponent(itemId)}`;
  }, [boardId, itemId, projectId]);

  const assigneeKey = item?.assignee_id && item?.assignee_type ? `${item.assignee_type}:${item.assignee_id}` : null;
  const currentAssignee = useMemo(() => {
    if (!assigneeKey) return null;
    return assigneeIndex.get(assigneeKey) ?? null;
  }, [assigneeIndex, assigneeKey]);

  const fallbackAssignee = useMemo(() => {
    if (!item?.assignee_id || !item.assignee_type || currentAssignee) return null;
    const label = item.assignee_type === 'agent'
      ? `Agent ${shortenAssigneeId(item.assignee_id)}`
      : `Member ${shortenAssigneeId(item.assignee_id)}`;
    return {
      id: item.assignee_id,
      type: item.assignee_type,
      label,
      subtitle: item.assignee_type === 'agent' ? 'Agent' : 'Human',
      avatar: getInitials(label),
      actor: toActorViewModel(
        { user_id: item.assignee_id, display_name: label, status: item.assignee_type === 'agent' ? 'active' : 'idle' },
        {
          id: item.assignee_id,
          kind: item.assignee_type === 'agent' ? 'agent' : 'human',
          subtitle: item.assignee_type === 'agent' ? 'Agent' : 'Human',
          presenceState: item.assignee_type === 'agent' ? 'working' : 'available',
        }
      ),
    } satisfies AssigneeProfile;
  }, [currentAssignee, item]);

  const assignmentProfile = currentAssignee ?? fallbackAssignee;

  const handleCopyLink = useCallback(async () => {
    const copied = await copyTextToClipboard(itemUrl);
    if (copied) {
      setSaveState('copied');
      onNotify('Link copied');
      window.setTimeout(() => setSaveState('idle'), 900);
      return;
    }
    setSaveState('error');
    onNotify('Could not copy link', 'error');
  }, [itemUrl, onNotify]);

  const handleCopyCurrentItemId = useCallback(() => {
    if (!item?.item_id) return;
    const displayId = shortId(item, projectSlug);
    onCopyWorkItemId(item.item_id, displayId);
  }, [item, projectSlug, onCopyWorkItemId]);

  const saveLabel = useMemo(() => {
    if (saveState === 'saving') return 'Saving...';
    if (saveState === 'saved') return 'Saved';
    if (saveState === 'copied') return 'Copied';
    if (saveState === 'error') return "Couldn't save";
    return '';
  }, [saveState]);

  const assignmentBusy = assignItem.isPending || unassignItem.isPending;
  const hasAgentAssignment = Boolean(item?.assignee_id && item?.assignee_type === 'agent');
  const isOrphanedAssignment = hasAgentAssignment && !currentAssignee;
  const pendingClarificationCount = executionStatus?.pendingClarifications?.length ?? 0;
  const executionControls = useMemo(
    () => buildExecutionControlModel({
      rawState: executionStatus?.state ?? null,
      hasExecution: executionStatus?.hasExecution,
      hasAgentAssignment,
      isOrphanedAssignment,
      pendingClarificationCount,
    }),
    [
      executionStatus?.hasExecution,
      executionStatus?.state,
      hasAgentAssignment,
      isOrphanedAssignment,
      pendingClarificationCount,
    ]
  );
  const canStartExecution = executionControls.canStart;
  const canCancelExecution = executionControls.canCancel;
  const startLabel = executionControls.startLabel;
  const executionHint = executionControls.startTitle;

  const clarificationRequests = useMemo(() => {
    const raw = executionStatus?.pendingClarifications ?? [];
    return raw
      .map((entry, index) => {
        if (!entry || typeof entry !== 'object') return null;
        const record = entry as Record<string, unknown>;
        const id = String(record.clarification_id ?? record.id ?? record.request_id ?? `clarification-${index}`);
        const question = String(record.prompt ?? record.question ?? record.message ?? record.reason ?? '');
        const context = record.context != null ? String(record.context) : undefined;
        return {
          id,
          question: question || 'Clarification requested',
          context,
          required: record.required === true,
        };
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null);
  }, [executionStatus?.pendingClarifications]);

  const commentAuthorType = useMemo<WorkItemCommentAuthorType | null>(() => {
    if (!actor?.type) return null;
    return actor.type === 'human' ? 'user' : 'agent';
  }, [actor]);

  const comments = useMemo(() => commentsQuery.data ?? [], [commentsQuery.data]);
  const commentDraftValue = commentDraft.trim();
  const canPostComment =
    Boolean(commentDraftValue) && Boolean(actor?.id) && Boolean(commentAuthorType) && !postComment.isPending;

  const resolveCommentProfile = useCallback(
    (comment: WorkItemComment) => {
      const isYou = actor?.id === comment.author_id;
      const key = `${comment.author_type}:${comment.author_id}`;
      const profile = assigneeIndex.get(key);
      if (profile) {
        return {
          label: isYou ? 'You' : profile.label,
          avatar: profile.avatar ?? getInitials(profile.label),
          actor: profile.actor,
        };
      }
      if (isYou && actor) {
        const avatarLabel = actor.displayName ?? 'You';
        return {
          label: 'You',
          avatar: getInitials(avatarLabel),
          actor: toActorViewModel(actor, { isCurrentUser: true, presenceState: 'available' }),
        };
      }
      const fallbackLabel =
        comment.author_type === 'agent'
          ? `Agent ${shortenAssigneeId(comment.author_id)}`
          : `Member ${shortenAssigneeId(comment.author_id)}`;
      return {
        label: fallbackLabel,
        avatar: getInitials(fallbackLabel),
        actor: toActorViewModel(
          { user_id: comment.author_id, display_name: fallbackLabel, status: comment.author_type === 'agent' ? 'active' : 'idle' },
          {
            id: comment.author_id,
            kind: comment.author_type === 'agent' ? 'agent' : 'human',
            subtitle: comment.author_type === 'agent' ? 'Agent' : 'Human',
            presenceState: comment.author_type === 'agent' ? 'working' : 'available',
          }
        ),
      };
    },
    [actor, assigneeIndex]
  );

  const activityEntries = useMemo<WorkItemActivityEntry[]>(() => {
    const next: WorkItemActivityEntry[] = [];

    comments.forEach((comment) => {
      const profile = resolveCommentProfile(comment);
      const timestamp = comment.updated_at ?? comment.created_at ?? null;
      next.push({
        id: `comment-${comment.comment_id}`,
        kind: 'comment',
        actorType: comment.author_type,
        timestamp,
        sortTime: timestamp ? new Date(timestamp).getTime() : 0,
        title: profile.label,
        body: comment.content,
        meta: [
          comment.author_type === 'agent' ? 'Agent' : 'Human',
          comment.run_id ? `Run ${shortenAssigneeId(comment.run_id)}` : null,
        ].filter(Boolean).join(' • ') || undefined,
        comment,
      });
    });

    return next.sort((left, right) => right.sortTime - left.sortTime);
  }, [comments, resolveCommentProfile]);

  const filteredActivityEntries = useMemo(() => {
    if (activityFilter === 'all') return activityEntries;
    if (activityFilter === 'humans') return activityEntries.filter((entry) => entry.actorType === 'user');
    if (activityFilter === 'agents') return activityEntries.filter((entry) => entry.actorType === 'agent');
    return activityEntries.filter((entry) => entry.actorType === 'system');
  }, [activityEntries, activityFilter]);

  const handleCommentSend = useCallback(() => {
    if (!itemId || !actor?.id || !commentAuthorType || !commentDraftValue) return;
    postComment.mutate(
      {
        body: commentDraftValue,
        authorId: actor.id,
        authorType: commentAuthorType,
        metadata: { source: 'web-console' },
      },
      {
        onSuccess: () => {
          setCommentDraft('');
          window.requestAnimationFrame(() => {
            commentEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
          });
        },
      }
    );
  }, [actor, commentAuthorType, commentDraftValue, itemId, postComment]);

  const handleCommentKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        handleCommentSend();
      }
    },
    [handleCommentSend]
  );

  const handleStartExecution = useCallback(() => {
    if (!itemId || !projectId || !canStartExecution) return;
    executeWorkItem.mutate({
      itemId,
      orgId: orgId ?? null,
      projectId,
      modelOverride: effectiveExecutionModelId || undefined,
    });
  }, [canStartExecution, effectiveExecutionModelId, executeWorkItem, itemId, orgId, projectId]);

  const handleCancelExecution = useCallback(() => {
    if (!itemId || !projectId || !canCancelExecution) return;
    cancelExecution.mutate({ itemId, orgId: orgId ?? null, projectId, reason: 'User requested cancellation' });
  }, [cancelExecution, canCancelExecution, itemId, orgId, projectId]);

  const handleClarificationSubmit = useCallback(
    (questionId: string, response: string) => {
      if (!itemId || !projectId || !response.trim()) return;
      provideClarification.mutate({
        itemId,
        orgId: orgId ?? null,
        projectId,
        clarificationId: questionId,
        response: response.trim(),
      });
    },
    [itemId, orgId, projectId, provideClarification]
  );

  const handleApproveGate = useCallback(() => {
    if (!itemId || !projectId) return;
    approveGate.mutate({
      itemId,
      orgId: orgId ?? null,
      projectId,
      phase: executionStatus?.phase ?? null,
    });
  }, [approveGate, executionStatus, itemId, orgId, projectId]);

  const handleRefreshExecution = useCallback(() => {
    executionStatusQuery.refetch();
    if (executionStatus?.runId) {
      executionStepsQuery.refetch();
    }
  }, [executionStatus?.runId, executionStatusQuery, executionStepsQuery]);

  const handleAssign = useCallback(
    (profile: AssigneeProfile) => {
      if (!itemId) return;
      if (item?.assignee_id === profile.id && item?.assignee_type === profile.type) return;
      setSaveState('saving');
      assignItem.mutate(
        {
          itemId,
          assigneeId: profile.id,
          assigneeType: profile.type,
        },
        {
          onSuccess: () => {
            setSaveState('saved');
            setShowAssigneePicker(false);
            window.setTimeout(() => setSaveState('idle'), 1100);
          },
          onError: () => setSaveState('error'),
        }
      );
    },
    [assignItem, item?.assignee_id, item?.assignee_type, itemId]
  );

  const handleUnassign = useCallback(() => {
    if (!itemId || !item?.assignee_id) return;
    setSaveState('saving');
    unassignItem.mutate(
      { itemId },
      {
        onSuccess: () => {
          setSaveState('saved');
          setShowAssigneePicker(false);
          window.setTimeout(() => setSaveState('idle'), 1100);
        },
        onError: () => setSaveState('error'),
      }
    );
  }, [item?.assignee_id, itemId, unassignItem]);

  const progressRollup = progressRollupQuery.data;
  const completionPercent = Math.round(progressRollup?.completion_percent ?? 0);
  const showParentSection = Boolean(item?.item_type !== 'goal' && (item?.parent_id || parentCandidates.length));
  const showChildrenSection = Boolean((item?.item_type === 'feature' || item?.item_type === 'goal') && childItems.length > 0);
  const showProgressSection = Boolean(
    (item?.item_type === 'feature' || item?.item_type === 'goal') &&
      progressRollup &&
      (completionPercent > 0 || progressRollup.incomplete_items.length > 0 || childItems.length > 0)
  );
  const executionSummary = summarizeExecution(executionStatus, hasAgentAssignment);
  const executionRawRunHref = useMemo(() => {
    if (!projectId || !executionStatus?.runId) return null;
    return `/projects/${encodeURIComponent(projectId)}/traces/${encodeURIComponent(executionStatus.runId)}`;
  }, [executionStatus?.runId, projectId]);

  const commentHint = actor?.id ? 'Cmd+Enter to send' : 'Sign in to comment.';
  const commentPlaceholder = actor?.id
    ? 'Share context for humans and agents...'
    : 'Sign in to leave a comment.';

  const renderAssigneeIdentity = useCallback(
    (opts?: { embedInHero?: boolean }) => {
      const embedInHero = opts?.embedInHero ?? false;
      const chipClass = `assignee-chip ${
        assignmentProfile ? `assignee-${assignmentProfile.type}` : 'assignee-unassigned'
      }${isOrphanedAssignment ? ' assignee-orphaned' : ''}${showAssigneePicker ? ' assignee-chip-open' : ''}`;
      const label = assignmentProfile ? `Assigned to ${assignmentProfile.label}` : 'Unassigned — choose assignee';
      const inner = (
        <>
          <span className="assignee-avatar">
            {assignmentProfile?.actor ? (
              <ActorAvatar actor={assignmentProfile.actor} size="sm" surfaceType="chip" decorative />
            ) : (
              assignmentProfile?.avatar ?? (assignmentProfile ? getInitials(assignmentProfile.label) : '+')
            )}
          </span>
          <span className="assignee-name">{assignmentProfile?.label ?? 'Unassigned'}</span>
          <span className="assignee-type-label">
            {isOrphanedAssignment ? 'Missing' : assignmentProfile?.type === 'agent' ? 'Agent' : assignmentProfile?.type === 'user' ? 'Human' : 'Unassigned'}
          </span>
        </>
      );
      if (embedInHero) {
        return (
          <button
            type="button"
            className={chipClass}
            aria-label={label}
            aria-haspopup="dialog"
            aria-expanded={showAssigneePicker}
            data-inline-assignee-control
            onClick={() => setShowAssigneePicker((current) => !current)}
            data-haptic="light"
          >
            {inner}
            <span className="assignee-chip-chevron" aria-hidden="true" />
          </button>
        );
      }
      return (
        <div className={chipClass} aria-label={label}>
          {inner}
        </div>
      );
    },
    [assignmentProfile, isOrphanedAssignment, showAssigneePicker]
  );

  const renderAssigneePicker = useCallback(
    (opts?: { compact?: boolean; embedInHero?: boolean }) => {
      const compact = opts?.compact ?? false;
      const embedInHero = opts?.embedInHero ?? false;

      const expandedPicker = showAssigneePicker ? (
        <div
          className={
            embedInHero
              ? 'assignee-picker-dropdown work-item-drawer-assignee-iap'
              : 'work-item-stack work-item-drawer-assignee-iap'
          }
        >
          <InlineAssigneePopover
            assignableHumans={assignableHumans}
            assignableAgents={assignableAgents}
            currentAssignee={assignmentProfile}
            onAssign={handleAssign}
            onUnassign={handleUnassign}
            onClose={() => setShowAssigneePicker(false)}
            isPending={assignmentBusy}
            showOptionSubtitle={false}
          />
        </div>
      ) : null;

      if (embedInHero) {
        return (
          <div className="work-item-hero-assignee">
            <div className="work-item-hero-assignee-toolbar">
              <div className="work-item-hero-assignee-identity">{renderAssigneeIdentity({ embedInHero: true })}</div>
            </div>
            {expandedPicker}
          </div>
        );
      }

      return (
        <div className={`work-item-card-surface${compact ? ' work-item-card-surface-compact' : ''}`}>
        <div className="work-item-card-header">
          <div>
            <div className="work-item-card-eyebrow">Assignee</div>
            <div className="work-item-card-title-small">
              {assignmentProfile ? `${assignmentProfile.label} • ${assignmentProfile.type === 'agent' ? 'Agent' : 'Human'}` : 'Unassigned'}
            </div>
          </div>
          <div className="work-item-card-header-actions">
            {item?.assignee_id && (
              <button
                type="button"
                className="drawer-inline-button pressable"
                onClick={handleUnassign}
                disabled={assignmentBusy}
                data-haptic="light"
              >
                Unassign
              </button>
            )}
            <button
              type="button"
              className="drawer-inline-button pressable"
              onClick={() => setShowAssigneePicker((current) => !current)}
              aria-expanded={showAssigneePicker}
              data-haptic="light"
            >
              {showAssigneePicker ? 'Done' : assignmentProfile ? 'Change' : 'Assign'}
            </button>
          </div>
        </div>
        <div className="assignee-current">
          {renderAssigneeIdentity({ embedInHero: false })}
          <span className="field-support-text">{assignmentHint ?? 'Project collaborators'}</span>
        </div>
        {expandedPicker}
      </div>
      );
    },
    [
      assignableAgents,
      assignableHumans,
      assignmentBusy,
      assignmentHint,
      assignmentProfile,
      handleAssign,
      handleUnassign,
      item?.assignee_id,
      renderAssigneeIdentity,
      showAssigneePicker,
    ]
  );

  const renderExecutionCard = useCallback(
    (opts?: { compact?: boolean; embedInHero?: boolean }) => {
      const compact = opts?.compact ?? false;
      const embedInHero = opts?.embedInHero ?? false;
      const stateAttr = executionStatus?.state ? String(executionStatus.state).toLowerCase() : 'none';
      const stateLabel = executionStatus?.state ? toTitleCase(toStatusLabel(executionStatus.state)) : null;

      const startButton = !embedInHero ? (
        <button
          type="button"
          className="execution-action-button pressable"
          onClick={handleStartExecution}
          disabled={!canStartExecution || executeWorkItem.isPending}
          title={executionControls.startTitle}
          data-haptic="light"
          aria-label={executeWorkItem.isPending ? 'Starting execution' : executionControls.startTitle}
        >
          {executeWorkItem.isPending ? 'Starting...' : startLabel}
        </button>
      ) : null;

      return (
        <div
          className={
            embedInHero
              ? 'work-item-hero-execution'
              : `work-item-card-surface work-item-card-execution${compact ? ' work-item-card-surface-compact' : ''}`
          }
          data-execution-state={stateAttr}
        >
          <div className={embedInHero ? 'work-item-stack work-item-hero-exec-inner' : 'work-item-stack'}>
            <ExecutionProgress
              variant={embedInHero ? 'embedded' : 'default'}
              embedInHero={embedInHero}
              status={executionStatus}
              steps={executionSteps}
              connectionState={executionConnectionState}
              streamConnected={executionStreamConnected}
              isStatusPolling={activeExecution}
              isStatusLoading={executionStatusQuery.isLoading}
              summary={executionSummary}
              hint={executionHint}
              hasExecution={Boolean(executionStatus?.hasExecution)}
              stateLabel={stateLabel}
              clarificationCount={clarificationRequests.length}
              clarificationQuestions={clarificationRequests}
              onClarifySubmit={handleClarificationSubmit}
              clarifySubmitting={provideClarification.isPending}
              onApproveGate={handleApproveGate}
              approveGatePending={approveGate.isPending}
              onCancel={handleCancelExecution}
              onRefresh={handleRefreshExecution}
              onRetry={handleStartExecution}
              cancelPending={cancelExecution.isPending}
              refreshPending={executionStatusQuery.isFetching}
              retryPending={executeWorkItem.isPending}
              canCancel={canCancelExecution}
              cancelLabel={executionControls.cancelLabel}
              refreshLabel={executionControls.refreshLabel}
              startSlot={startButton}
              rawRunHref={executionRawRunHref}
              workItemType={item?.item_type ?? null}
            />
          </div>
        </div>
      );
    },
    [
      activeExecution,
      approveGate.isPending,
      canCancelExecution,
      canStartExecution,
      cancelExecution.isPending,
      clarificationRequests,
      executeWorkItem.isPending,
      executionConnectionState,
      executionHint,
      executionRawRunHref,
      executionStatus,
      executionStatusQuery.isFetching,
      executionStatusQuery.isLoading,
      executionSteps,
      executionStreamConnected,
      executionSummary,
      item?.item_type,
      executionControls.cancelLabel,
      executionControls.refreshLabel,
      executionControls.startTitle,
      handleApproveGate,
      handleCancelExecution,
      handleClarificationSubmit,
      handleRefreshExecution,
      handleStartExecution,
      provideClarification.isPending,
      startLabel,
    ]
  );

  const renderChildrenCard = useCallback(() => {
    if (!showChildrenSection || !item) return null;
    const childrenLabel = item.item_type === 'feature' ? 'Tasks' : 'Features';
    const linkedCountLabel = `${sortedStudioChildren.length} linked`;
    const hasRolledUpChildren = Boolean(progressRollup && progressRollup.buckets.total > 0);
    const showProgressOnChip = Boolean(
      hasRolledUpChildren && (item.item_type === 'goal' || item.item_type === 'feature'),
    );
    return (
      <section
        className="work-item-card-surface work-item-card-surface-main work-item-card-children"
        aria-label={`${childrenLabel} under this work item`}
      >
        <div className="work-item-card-header work-item-card-header-tight work-item-card-header-children">
          <div className="work-item-card-eyebrow">{childrenLabel}</div>
          <div className="children-card-rollup-slot">
            {progressRollup ? (
              <RollupProgressInline
                progressRollup={progressRollup}
                countLabel={linkedCountLabel}
                showProgress={showProgressOnChip}
                rollupContextNoun={item.item_type === 'goal' ? 'goal' : 'feature'}
              />
            ) : (
              <span className="activity-badge activity-badge-system">{linkedCountLabel}</span>
            )}
          </div>
        </div>
        {progressRollup ? (
          <div className="drawer-progress-remaining children-rollup-remaining">{formatRemainingSummary(progressRollup)}</div>
        ) : null}
        <div className="children-rows">
          {sortedStudioChildren.map((child) => {
            const bucket = bucketForChild(child, columns);
            const css = bucketCssClass(bucket);
            const colName = columnNameById.get(child.column_id ?? '') ?? '—';
            const statusLabel = labelForChildBucket(bucket);
            const showColumn =
              colName !== '—' && colName.toLowerCase() !== statusLabel.toLowerCase();
            const childDisplayId = shortId(child, projectSlug);
            return (
              <div key={child.item_id} className={`children-row children-row-${css}`}>
                <button
                  type="button"
                  className="children-row-id-chip pressable"
                  onClick={(event) => {
                    event.stopPropagation();
                    onCopyWorkItemId(child.item_id, childDisplayId);
                  }}
                  aria-label={`Copy display ID ${childDisplayId}`}
                  title={`Click to copy ${childDisplayId}`}
                >
                  {childDisplayId}
                </button>
                <button
                  type="button"
                  className="children-row-title children-row-title-button pressable"
                  onClick={() => onOpenItem?.(child.item_id)}
                  disabled={!onOpenItem}
                  aria-label={
                    onOpenItem ? `Open linked item ${childDisplayId}: ${child.title}` : undefined
                  }
                  title={onOpenItem ? `Open "${child.title}" (${childDisplayId})` : undefined}
                >
                  <span className="children-row-title-text">{child.title}</span>
                </button>
                <span className={`children-status-pill children-status-${css}`}>{statusLabel}</span>
                {showColumn ? (
                  <span className="children-row-column" title="Board column">
                    {colName}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>
    );
  }, [
    columnNameById,
    item,
    onCopyWorkItemId,
    onOpenItem,
    progressRollup,
    projectSlug,
    showChildrenSection,
    sortedStudioChildren,
  ]);

  const renderDetailsCard = useCallback(
    () => (
      <div className="work-item-card-surface">
        <div className="work-item-card-header work-item-card-header-tight">
          <div className="work-item-card-eyebrow">Details</div>
          <button
            type="button"
            className="drawer-inline-button pressable"
            onClick={() => setShowAdvancedDetails((current) => !current)}
          >
            {showAdvancedDetails ? 'Hide system' : 'Show system'}
          </button>
        </div>

        <div className="work-item-stack">
          {showParentSection && (
            <div className="work-item-field">
              <label className="drawer-label">Rolls up to {parentLabel}</label>
              <select
                className="drawer-select"
                value={item?.parent_id ?? '__none__'}
                onChange={handleParentChange}
                disabled={!parentCandidates.length}
              >
                <option value="__none__">No {parentLabel.toLowerCase()} selected</option>
                {parentCandidates.map((candidate) => (
                  <option key={candidate.item_id} value={candidate.item_id}>
                    {candidate.title} • {shortId(candidate, projectSlug)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {parentItem && (
            <div className="hierarchy-pill hierarchy-pill-inline hierarchy-pill-summary">
              {parentLabel}: {parentItem.title}
            </div>
          )}

          {showProgressSection && progressRollup && !showChildrenSection && (
            <div className="drawer-progress-panel work-item-card-soft">
              <RollupProgressInline
                progressRollup={progressRollup}
                showProgress={Boolean(progressRollup.buckets.total > 0)}
                rollupContextNoun={item?.item_type === 'goal' ? 'goal' : 'feature'}
                className="work-item-rollup-chip-inline--drawer"
              />
              <div className="drawer-progress-remaining">{formatRemainingSummary(progressRollup)}</div>
            </div>
          )}

          {item?.item_type === 'research' && (
            <>
              <div className="work-item-field">
                <label className="drawer-label" htmlFor="work-item-research-url">Research URL</label>
                <input
                  id="work-item-research-url"
                  className="drawer-input"
                  type="url"
                  value={researchUrlDraft}
                  onChange={(event) => setResearchUrlDraft(event.target.value)}
                  onBlur={handleResearchUrlBlur}
                  placeholder="https://arxiv.org/abs/..."
                  autoComplete="url"
                />
                <span className="field-support-text">
                  Required. Used for attribution; the AI Research agent fetches this page unless you paste a body below.
                </span>
              </div>
              <div className="work-item-field">
                <label className="drawer-label" htmlFor="work-item-research-body">Article body (optional)</label>
                {showResearchBodyPasteHint ? (
                  <div className="research-ingest-hint" role="note">
                    <strong>Automated fetch failed from the server.</strong>{' '}
                    Paste the article text below so ingest does not need to download the page (the research URL
                    above is still used for attribution). If this keeps happening, an operator can enable the
                    Jina Reader proxy on the API with{' '}
                    <code className="research-ingest-hint-code">AMPREALIZE_RESEARCH_READER_PROXY=jina</code>.
                  </div>
                ) : null}
                <textarea
                  id="work-item-research-body"
                  className="drawer-input drawer-textarea"
                  value={researchBodyDraft}
                  onChange={(event) => setResearchBodyDraft(event.target.value)}
                  onBlur={handleResearchBodyBlur}
                  placeholder="Paste markdown or plain text if automated URL fetch returns no usable content."
                  rows={8}
                  spellCheck={false}
                />
                <span className="field-support-text">
                  When non-empty, ingest uses this text instead of downloading the URL (the URL is still stored for citation).
                </span>
              </div>
            </>
          )}

          <div className="work-item-field-grid">
            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-start-date">Start date</label>
              <input
                id="work-item-start-date"
                type="date"
                className="drawer-input"
                value={startDateDraft}
                onChange={(event) => handleDateChange('start_date', event.target.value)}
              />
            </div>
            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-target-date">Target date</label>
              <input
                id="work-item-target-date"
                type="date"
                className="drawer-input"
                value={targetDateDraft}
                onChange={(event) => handleDateChange('target_date', event.target.value)}
              />
            </div>
          </div>

          <div className="work-item-field-grid">
            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-points">Points</label>
              <input
                id="work-item-points"
                className="drawer-input"
                inputMode="numeric"
                value={pointsDraft}
                onChange={(event) => setPointsDraft(event.target.value)}
                onBlur={() => handleNumberBlur('points', pointsDraft)}
                placeholder="No estimate"
              />
            </div>
            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-estimated-hours">Estimated hours</label>
              <input
                id="work-item-estimated-hours"
                className="drawer-input"
                inputMode="decimal"
                value={estimatedHoursDraft}
                onChange={(event) => setEstimatedHoursDraft(event.target.value)}
                onBlur={() => handleNumberBlur('estimated_hours', estimatedHoursDraft)}
                placeholder="Optional"
              />
            </div>
          </div>

          <div className="work-item-field">
            <label className="drawer-label" htmlFor="work-item-actual-hours">Actual hours</label>
            <input
              id="work-item-actual-hours"
              className="drawer-input"
              inputMode="decimal"
              value={actualHoursDraft}
              onChange={(event) => setActualHoursDraft(event.target.value)}
              onBlur={() => handleNumberBlur('actual_hours', actualHoursDraft)}
              placeholder="Optional"
            />
          </div>

          <div className="work-item-field">
            <div className="drawer-label-row">
              <label className="drawer-label">Labels</label>
              <span className="drawer-assignee-hint">{labels.length} applied</span>
            </div>
            <div className="drawer-labels work-item-card-soft">
              <div className="drawer-label-chips" aria-label="Labels">
                {labels.map((label) => (
                  <button
                    key={label}
                    type="button"
                    className="drawer-chip pressable"
                    onClick={() => handleLabelsRemove(label)}
                    aria-label={`Remove label ${label}`}
                    title="Remove"
                  >
                    <span className="drawer-chip-text">{label}</span>
                    <span className="drawer-chip-x">x</span>
                  </button>
                ))}
                {!labels.length && <span className="field-support-text">No labels yet.</span>}
              </div>
              <input
                className="drawer-input drawer-input-label"
                value={newLabelDraft}
                onChange={(event) => setNewLabelDraft(event.target.value)}
                onKeyDown={handleNewLabelKeyDown}
                placeholder="Add label and press Enter"
                autoComplete="off"
              />
            </div>
          </div>

          {showAdvancedDetails && (
            <div className="work-item-card-soft work-item-stack">
              <div className="drawer-label-row">
                <label className="drawer-label">System</label>
                <span className="drawer-assignee-hint">Read-only metadata</span>
              </div>
              <div className="metadata-list">
                <div className="metadata-row">
                  <span className="metadata-key">Created</span>
                  <span className="metadata-value">{formatAbsoluteDate(item?.created_at)}</span>
                </div>
                <div className="metadata-row">
                  <span className="metadata-key">Updated</span>
                  <span className="metadata-value">{formatRelativeTime(item?.updated_at)}</span>
                </div>
                {item?.behavior_id && (
                  <div className="metadata-row">
                    <span className="metadata-key">Behavior</span>
                    <span className="metadata-value metadata-mono">{item.behavior_id}</span>
                  </div>
                )}
                {item?.run_id && (
                  <div className="metadata-row">
                    <span className="metadata-key">Run</span>
                    <span className="metadata-value metadata-mono">{item.run_id}</span>
                  </div>
                )}
                <div className="metadata-row metadata-row-block">
                  <span className="metadata-key">Metadata</span>
                  <pre className="metadata-json">{JSON.stringify(item?.metadata ?? {}, null, 2)}</pre>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    ),
    [
      actualHoursDraft,
      completionPercent,
      estimatedHoursDraft,
      handleDateChange,
      handleLabelsRemove,
      handleNewLabelKeyDown,
      handleNumberBlur,
      handleParentChange,
      handleResearchBodyBlur,
      handleResearchUrlBlur,
      item,
      labels,
      newLabelDraft,
      parentCandidates,
      parentItem,
      parentLabel,
      pointsDraft,
      progressRollup,
      projectSlug,
      researchBodyDraft,
      researchUrlDraft,
      showAdvancedDetails,
      showChildrenSection,
      showParentSection,
      showProgressSection,
      startDateDraft,
      targetDateDraft,
    ]
  );

  const renderStudioActivity = useCallback(
    () => (
      <section className="work-item-card-surface work-item-card-surface-main">
        <div className="work-item-card-header work-item-card-header-tight">
          <div className="work-item-card-eyebrow">Activity</div>
          <button
            type="button"
            className="drawer-inline-button pressable"
            onClick={() => commentsQuery.refetch()}
            disabled={commentsQuery.isFetching}
          >
            {commentsQuery.isFetching ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        <div className="work-item-stack">
          <div className="comment-filters" role="tablist" aria-label="Filter activity">
            {(['all', 'humans', 'agents', 'system'] as WorkItemActivityFilter[]).map((filter) => (
              <button
                key={filter}
                type="button"
                className={`comment-filter ${activityFilter === filter ? 'comment-filter-active' : ''}`}
                onClick={() => setActivityFilter(filter)}
                aria-pressed={activityFilter === filter}
                data-haptic="light"
              >
                {filter === 'all' ? 'All' : filter === 'humans' ? 'Humans' : filter === 'agents' ? 'Agents' : 'System'}
              </button>
            ))}
          </div>

          <div className="comment-compose">
            <textarea
              className="comment-compose-input"
              rows={3}
              value={commentDraft}
              onChange={(event) => setCommentDraft(event.target.value)}
              onKeyDown={handleCommentKeyDown}
              placeholder={commentPlaceholder}
              disabled={!actor?.id}
            />
            <div className="comment-compose-actions">
              <span className="comment-compose-hint">{commentHint}</span>
              <button
                type="button"
                className="comment-send-button pressable"
                onClick={handleCommentSend}
                disabled={!canPostComment}
                data-haptic="light"
              >
                {postComment.isPending ? 'Sending...' : 'Send comment'}
              </button>
            </div>
            {postComment.isError && (
              <div className="comment-error" role="status">
                Couldn't post this comment.
              </div>
            )}
          </div>

          <div className="activity-feed">
            {commentsQuery.isLoading && activityEntries.length === 0 && (
              <div className="activity-empty">
                <CompactLoadingShimmer label="Loading activity" />
              </div>
            )}
            {!commentsQuery.isLoading && filteredActivityEntries.length === 0 && (
              <div className="activity-empty" role="status">
                No activity yet. Start the thread or run this work item.
              </div>
            )}

            {filteredActivityEntries.map((entry) => (
              <div key={entry.id} className="activity-entry">
                <div className="activity-entry-topline">
                  <div className="activity-entry-identity">
                    <span className={`activity-badge activity-badge-${entry.actorType}`}>
                      {entry.actorType === 'system' ? 'System' : entry.actorType === 'agent' ? 'Agent' : 'Human'}
                    </span>
                    <span className="activity-title">{entry.title}</span>
                  </div>
                  <span className="activity-time">{formatRelativeTime(entry.timestamp)}</span>
                </div>
                <div className="activity-body">{entry.body}</div>
                {entry.meta && <div className="activity-meta">{entry.meta}</div>}
              </div>
            ))}
            <div ref={commentEndRef} />
          </div>
        </div>
      </section>
    ),
    [
      activityEntries.length,
      activityFilter,
      actor?.id,
      canPostComment,
      commentDraft,
      commentHint,
      commentPlaceholder,
      commentsQuery,
      filteredActivityEntries,
      handleCommentKeyDown,
      handleCommentSend,
      postComment.isError,
      postComment.isPending,
    ]
  );

  const renderStudio = useCallback(() => {
    const trimmedDescription = descriptionDraft.trim();
    const hasDescription = trimmedDescription.length > 0;
    const descriptionPreviewCollapsed = heroDescriptionCollapsePreview(descriptionDraft);
    const childrenBlock = showChildrenSection ? renderChildrenCard() : null;

    return (
    <div className="work-item-studio-layout">
      <div className="work-item-studio-main">
        <section className="work-item-card-surface work-item-card-surface-main work-item-hero-surface" aria-label="Work item header">
          <div className="work-item-hero work-item-hero-studio">
            <div className="work-item-hero-title-slot">
              <span className="work-item-hero-description-kicker">Title</span>
              <input
                id="work-item-title"
                ref={titleRef}
                className="drawer-input work-item-title-input work-item-title-input-studio"
                value={titleDraft}
                onChange={handleTitleChange}
                onBlur={() => debouncedSave.schedule()}
                placeholder="What needs to happen?"
                autoComplete="off"
                aria-label="Title"
              />
            </div>
            <div className="work-item-hero-description-slot">
              {heroDescriptionInlineOpen ? (
                <div className="work-item-hero-description-inline" aria-label="Description editor">
                  <div className="work-item-hero-description-inline-header">
                    <span className="work-item-hero-description-kicker">Description</span>
                    <button
                      type="button"
                      className="drawer-inline-button pressable"
                      onClick={() => setHeroDescriptionInlineOpen(false)}
                    >
                      Done
                    </button>
                  </div>
                  <textarea
                    id="work-item-description"
                    ref={heroDescriptionTextareaRef}
                    className="drawer-textarea work-item-description-input work-item-hero-description-textarea"
                    value={descriptionDraft}
                    onChange={handleDescriptionChange}
                    onBlur={() => debouncedSave.schedule()}
                    placeholder="Add context, links, acceptance criteria, risks, or blockers..."
                    rows={8}
                    aria-label="Description"
                  />
                </div>
              ) : hasDescription ? (
                <button
                  type="button"
                  className="work-item-hero-description-strip pressable"
                  onClick={() => setHeroDescriptionInlineOpen(true)}
                  aria-expanded={false}
                  aria-controls="work-item-description"
                  title="Edit description"
                >
                  <span className="work-item-hero-description-kicker">Description</span>
                  <span className="work-item-hero-description-line">{descriptionPreviewCollapsed}</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="work-item-hero-description-add pressable"
                  onClick={() => setHeroDescriptionInlineOpen(true)}
                >
                  Add description…
                </button>
              )}
            </div>
            <div className="work-item-hero-controls work-item-hero-controls--chips" role="group" aria-label="Priority and due date">
              <div className={`hero-chip-field ${priorityHeroChipClass(priorityDraft)}`}>
                <span className="hero-chip-kicker" id="work-item-priority-hero-k">Priority</span>
                <select
                  id="work-item-priority-hero"
                  className="hero-chip-select"
                  aria-labelledby="work-item-priority-hero-k"
                  value={priorityDraft}
                  onChange={handlePriorityChange}
                >
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
              <div className={`hero-chip-field hero-chip-field-date ${dueDateHeroChipClass(dueDateDraft)}`}>
                <span className="hero-chip-kicker" id="work-item-due-date-hero-k">Due</span>
                <input
                  id="work-item-due-date-hero"
                  type="date"
                  className="hero-chip-date"
                  aria-labelledby="work-item-due-date-hero-k"
                  value={dueDateDraft}
                  onChange={(event) => handleDateChange('due_date', event.target.value)}
                />
              </div>
            </div>
            <div className="work-item-hero-work">
              <div className="work-item-hero-assignee-start-row">
                {renderAssigneePicker({ embedInHero: true })}
                <label className="work-item-execution-model-field">
                  <span className="work-item-execution-model-label">Model</span>
                  <select
                    className="work-item-execution-model-select"
                    value={executionModelOverride}
                    onChange={(event) => setExecutionModelOverride(event.target.value)}
                    disabled={modelsLoading || activeExecution}
                  >
                    <option value="">
                      {projectDefaultModelId ? 'Project default' : 'Agent default'}
                    </option>
                    {availableModels.map((model) => (
                      <option key={model.model_id} value={model.model_id}>
                        {model.display_name} ({model.provider})
                      </option>
                    ))}
                  </select>
                  <span className="work-item-execution-model-hint">
                    {effectiveExecutionModel
                      ? `${effectiveExecutionModel.provider}/${effectiveExecutionModel.credential_source}`
                      : projectDefaultModelId
                        ? projectDefaultModelId
                        : 'Agent policy'}
                  </span>
                </label>
                <button
                  type="button"
                  className="execution-action-button work-item-hero-start-chip pressable"
                  onClick={handleStartExecution}
                  disabled={!canStartExecution || executeWorkItem.isPending}
                  title={executionControls.startTitle}
                  data-haptic="light"
                >
                  {executeWorkItem.isPending ? 'Starting...' : startLabel}
                </button>
              </div>
              {renderExecutionCard({ embedInHero: true })}
            </div>
          </div>
        </section>

        {childrenBlock}

        {renderStudioActivity()}
      </div>

      <aside className="work-item-studio-rail">
        {renderDetailsCard()}
      </aside>
    </div>
    );
  }, [
    canStartExecution,
    activeExecution,
    availableModels,
    debouncedSave,
    descriptionDraft,
    dueDateDraft,
    effectiveExecutionModel,
    executeWorkItem.isPending,
    executionControls.startTitle,
    executionModelOverride,
    handleDateChange,
    handleDescriptionChange,
    handlePriorityChange,
    handleStartExecution,
    handleTitleChange,
    heroDescriptionInlineOpen,
    modelsLoading,
    priorityDraft,
    projectDefaultModelId,
    renderAssigneePicker,
    renderChildrenCard,
    renderDetailsCard,
    renderExecutionCard,
    renderStudioActivity,
    showChildrenSection,
    startLabel,
    titleDraft,
  ]);

  return (
    <div
      ref={overlayRef}
      className={`work-item-drawer-overlay ${phase === 'open' ? 'open' : ''} ${phase === 'closing' ? 'closing' : ''} presentation-studio`}
      onMouseDown={handleOverlayMouseDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="work-item-title"
    >
      <aside
        className="work-item-drawer work-item-drawer-studio"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="work-item-drawer-header">
          <div className="work-item-drawer-header-left">
            <div className="work-item-drawer-meta">
              {saveLabel ? <div className="work-item-drawer-save">{saveLabel}</div> : null}
            </div>
            {item ? (
              <div className="work-item-drawer-header-chips" aria-label="Work item summary">
                <span className={`work-item-type-pill work-item-type-pill-${item.item_type ?? 'goal'}`}>{typeLabel}</span>
                <span className="work-item-hero-id-cluster">
                  <span className="work-item-hero-id" title={item.item_id}>
                    {shortId(item, projectSlug)}
                  </span>
                  <button
                    type="button"
                    className="work-item-inline-copy work-item-hero-id-copy pressable"
                    onClick={handleCopyCurrentItemId}
                    aria-label={`Copy work item ID ${item.item_id}`}
                    title="Copy work item ID"
                  >
                    Copy ID
                  </button>
                </span>
                <span className="summary-chip">{toTitleCase(toStatusLabel(item.status ?? 'backlog'))}</span>
                <div className="hero-chip-field hero-chip-field--header">
                  <span className="hero-chip-kicker" id="work-item-column-header-k">
                    Column
                  </span>
                  <select
                    id="work-item-column-header"
                    className="hero-chip-select"
                    aria-labelledby="work-item-column-header-k"
                    value={item.column_id ?? '__none__'}
                    onChange={handleColumnChange}
                  >
                    <option value="__none__">Unsorted</option>
                    {columns.map((column) => (
                      <option key={column.column_id} value={column.column_id}>
                        {column.name}
                      </option>
                    ))}
                  </select>
                </div>
                <span className="summary-chip">Updated {formatRelativeTime(item.updated_at)}</span>
              </div>
            ) : null}
          </div>
          <div className="work-item-drawer-header-right">
            <button
              type="button"
              className="work-item-drawer-action work-item-drawer-action-label pressable"
              onClick={handleCopyLink}
              aria-label="Copy link"
              title="Copy link"
            >
              Copy link
            </button>
            <button
              type="button"
              className="work-item-drawer-action pressable"
              onClick={requestClose}
              aria-label="Close"
              title="Close"
            >
              x
            </button>
          </div>
        </header>

        <div className="work-item-drawer-body">
          {isLoading && <WorkItemDrawerBodySkeleton />}

          {isError && (
            <div className="work-item-drawer-error animate-fade-in-up" role="status">
              Couldn't load this work item.
            </div>
          )}

          {!isLoading && item && (
            <div className="work-item-surface work-item-surface-studio">
              {renderStudio()}
            </div>
          )}
        </div>
      </aside>

      {showCascadeModal && (
        <div
          className="cascade-modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="cascade-modal-title"
          onClick={(event) => {
            if (event.target === event.currentTarget) handleCascadeModalClose();
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') handleCascadeModalClose();
          }}
        >
          <div className="cascade-modal">
            <h2 id="cascade-modal-title" className="cascade-modal-title">
              Mark items as done?
            </h2>
            <p className="cascade-modal-body">
              This {typeLabel.toLowerCase()} has{' '}
              <strong>{incompleteDescendantsCount} incomplete {incompleteDescendantsCount === 1 ? 'child' : 'children'}</strong>.
              Would you like to mark them all as done?
            </p>
            <div className="cascade-modal-actions">
              <button
                type="button"
                className="cascade-modal-btn cascade-modal-btn-secondary"
                onClick={handleCascadeCancel}
              >
                This item only
              </button>
              <button
                type="button"
                className="cascade-modal-btn cascade-modal-btn-primary"
                onClick={handleCascadeConfirm}
                disabled={completeWithDescendants.isPending}
              >
                {completeWithDescendants.isPending
                  ? 'Updating...'
                  : `Mark all ${incompleteDescendantsCount + 1} items as done`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
