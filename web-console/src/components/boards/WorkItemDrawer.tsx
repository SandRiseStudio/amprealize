/**
 * Work Item Drawer / Studio
 *
 * Following COLLAB_SAAS_REQUIREMENTS.md (Student):
 * - Fast, optimistic edits
 * - 60fps transforms for motion (no layout animations)
 * - Accessible keyboard interactions (Escape to close, focus-visible)
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ClarificationPanel,
  ExecutionStatusCard,
  type ExecutionStatus,
} from '../../lib/collab-client';
import {
  type BoardColumn,
  type WorkItemProgressRollup,
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
import {
  useCancelWorkItemExecution,
  useExecuteWorkItem,
  useExecutionSteps,
  useExecutionStream,
  useProvideClarification,
  useWorkItemExecutionStatus,
} from '../../api/executions';
import { useAuth } from '../../contexts/AuthContext';
import { ActorAvatar } from '../actors/ActorAvatar';
import type { ActorViewModel } from '../../types/actor';
import { toActorViewModel } from '../../utils/actorViewModel';
import { copyTextToClipboard, formatWorkItemDisplayId } from './workItemId';
import type { PresenceState } from '../../hooks/useAgentPresence';
import './WorkItemDrawer.css';

type DrawerPhase = 'entering' | 'open' | 'closing';
type SaveState = 'idle' | 'saving' | 'saved' | 'copied' | 'error';
export type WorkItemPresentationMode = 'peek' | 'studio';
type WorkItemActivityFilter = 'all' | 'humans' | 'agents' | 'system';
type NumberField = 'points' | 'estimated_hours' | 'actual_hours';
type DateField = 'due_date' | 'start_date' | 'target_date';

interface WorkItemActivityEntry {
  id: string;
  kind: 'comment' | 'execution-status' | 'execution-step';
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
  return 'Goal';
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

function formatCompactDate(dateString?: string | null): string {
  if (!dateString) return 'No due date';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return 'No due date';
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (sameDay(date, today)) return 'Today';
  if (sameDay(date, tomorrow)) return 'Tomorrow';
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
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

function formatRollupRemaining(rollup: WorkItemProgressRollup): string {
  const chunks: string[] = [`${rollup.remaining.items_remaining} items left`];
  if (rollup.remaining.estimated_hours_remaining != null) {
    chunks.push(`${rollup.remaining.estimated_hours_remaining.toFixed(1)}h`);
  }
  if (rollup.remaining.points_remaining != null) {
    chunks.push(`${rollup.remaining.points_remaining} pts`);
  }
  return chunks.join(' • ');
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

function shouldHighlightPriority(priority?: WorkItemPriority | null): boolean {
  return priority === 'critical' || priority === 'high';
}

function summarizeDescription(description?: string | null): string {
  if (!description?.trim()) return 'Add context, acceptance criteria, or links in the full studio.';
  const normalized = description.trim().replace(/\s+/g, ' ');
  return normalized.length > 220 ? `${normalized.slice(0, 217)}...` : normalized;
}

function summarizeStructure(
  parentItem: WorkItem | null,
  childItems: WorkItem[],
  progressRollup: WorkItemProgressRollup | null | undefined
): string {
  const parts: string[] = [];
  if (parentItem) {
    parts.push(`Linked to ${labelForType(parentItem.item_type).toLowerCase()} ${shortId(parentItem)}`);
  }
  if (childItems.length > 0) {
    parts.push(`${childItems.length} linked ${childItems.length === 1 ? 'item' : 'items'}`);
  }
  if (progressRollup) {
    parts.push(`${Math.round(progressRollup.completion_percent)}% complete`);
  }
  return parts.length > 0 ? parts.join(' • ') : 'No rollup or linked work yet.';
}

function summarizeExecution(status: ExecutionStatus | null, hasAgentAssignment: boolean): string {
  if (status?.state === 'running') return 'Running now';
  if (status?.pendingClarifications?.length) return 'Needs your input';
  if (status?.state === 'failed') return 'Last run failed';
  if (status?.state === 'completed') return 'Last run completed';
  if (status?.hasExecution) return 'Run history available';
  if (hasAgentAssignment) return 'Ready to run';
  return 'Assign an agent to run';
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
  presentationMode: WorkItemPresentationMode;
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
  onPresentationModeChange: (mode: WorkItemPresentationMode) => void;
}

export function WorkItemDrawer({
  projectId,
  projectSlug,
  orgId,
  boardId,
  itemId,
  presentationMode,
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
  onPresentationModeChange,
}: WorkItemDrawerProps): React.JSX.Element {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const titleRef = useRef<HTMLInputElement | null>(null);
  const prevFocusRef = useRef<HTMLElement | null>(null);
  const commentEndRef = useRef<HTMLDivElement | null>(null);

  const { actor } = useAuth();

  const [phase, setPhase] = useState<DrawerPhase>('entering');
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const [titleDraft, setTitleDraft] = useState(initialItem?.title ?? '');
  const [descriptionDraft, setDescriptionDraft] = useState(initialItem?.description ?? '');
  const [priorityDraft, setPriorityDraft] = useState<WorkItemPriority>(initialItem?.priority ?? 'medium');
  const [labels, setLabels] = useState<string[]>(initialItem?.labels ?? []);
  const [newLabelDraft, setNewLabelDraft] = useState('');
  const [assigneeSearch, setAssigneeSearch] = useState('');
  const [commentDraft, setCommentDraft] = useState('');
  const [activityFilter, setActivityFilter] = useState<WorkItemActivityFilter>('all');
  const [showAssigneePicker, setShowAssigneePicker] = useState(false);
  const [showAdvancedDetails, setShowAdvancedDetails] = useState(false);
  const [showCascadeModal, setShowCascadeModal] = useState(false);
  const [pendingColumnChange, setPendingColumnChange] = useState<{ toColumnId: string | null; position: number } | null>(null);
  const [dueDateDraft, setDueDateDraft] = useState(toDateInputValue(initialItem?.due_date));
  const [startDateDraft, setStartDateDraft] = useState(toDateInputValue(initialItem?.start_date));
  const [targetDateDraft, setTargetDateDraft] = useState(toDateInputValue(initialItem?.target_date));
  const [pointsDraft, setPointsDraft] = useState(toNumberDraft(initialItem?.points ?? initialItem?.story_points ?? null));
  const [estimatedHoursDraft, setEstimatedHoursDraft] = useState(toNumberDraft(initialItem?.estimated_hours ?? null));
  const [actualHoursDraft, setActualHoursDraft] = useState(toNumberDraft(initialItem?.actual_hours ?? null));

  const updateItem = useUpdateWorkItem(boardId);
  const assignItem = useAssignWorkItem(boardId);
  const unassignItem = useUnassignWorkItem(boardId);
  const completeWithDescendants = useCompleteWithDescendants(boardId);
  const { data: item, isLoading, isError } = useWorkItem(itemId, initialItem);
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

  const executionStatusQuery = useWorkItemExecutionStatus(itemId, orgId, projectId);
  const executionStatus = executionStatusQuery.data ?? null;
  const executionState = executionStatus?.state ? String(executionStatus.state).toLowerCase() : null;
  const activeExecution = executionState === 'running' || executionState === 'paused' || executionState === 'pending';
  const executionStream = useExecutionStream({
    runId: executionStatus?.runId ?? null,
    orgId: orgId ?? null,
    projectId,
    enabled: Boolean(orgId && projectId),
  });
  const executionStepsQuery = useExecutionSteps(executionStatus?.runId ?? null, orgId, projectId, {
    enabled: Boolean(executionStatus?.runId && projectId),
    refetchInterval: executionStream.isConnected ? false : activeExecution ? 2000 : false,
  });
  const executionSteps = executionStepsQuery.data?.steps ?? [];

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
  }, [boardItems, item?.parent_id]);

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
  }, [isOpen, presentationMode]);

  useEffect(() => {
    return () => {
      prevFocusRef.current?.focus?.();
    };
  }, []);

  useEffect(() => {
    if (!item) return;
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
    setShowAssigneePicker(false);
    setShowAdvancedDetails(false);
    setSaveState('idle');
  }, [item?.item_id]);

  useEffect(() => {
    setAssigneeSearch('');
    setCommentDraft('');
    setActivityFilter('all');
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
  }, [currentAssignee, item?.assignee_id, item?.assignee_type]);

  const assignmentProfile = currentAssignee ?? fallbackAssignee;
  const assigneeSearchValue = assigneeSearch.trim().toLowerCase();
  const filteredHumans = useMemo(() => {
    if (!assigneeSearchValue) return assignableHumans;
    return assignableHumans.filter((profile) => {
      const haystack = `${profile.label} ${profile.subtitle ?? ''} ${profile.id}`.toLowerCase();
      return haystack.includes(assigneeSearchValue);
    });
  }, [assignableHumans, assigneeSearchValue]);

  const presencePriority = (presence: PresenceState | undefined): number => {
    switch (presence) {
      case 'available':
        return 1;
      case 'finished_recently':
        return 2;
      case 'working':
        return 3;
      case 'at_capacity':
        return 4;
      case 'paused':
        return 5;
      case 'offline':
        return 6;
      default:
        return 7;
    }
  };

  const filteredAgents = useMemo(() => {
    let agents = assignableAgents;
    if (assigneeSearchValue) {
      agents = agents.filter((profile) => {
        const haystack = `${profile.label} ${profile.subtitle ?? ''} ${profile.id}`.toLowerCase();
        return haystack.includes(assigneeSearchValue);
      });
    }
    return [...agents].sort((left, right) => presencePriority(left.presence) - presencePriority(right.presence));
  }, [assignableAgents, assigneeSearchValue]);

  const groupedAgents = useMemo(() => {
    const available: AssigneeProfile[] = [];
    const working: AssigneeProfile[] = [];
    const pausedOffline: AssigneeProfile[] = [];

    for (const agent of filteredAgents) {
      if (agent.presence === 'available' || agent.presence === 'finished_recently') {
        available.push(agent);
      } else if (agent.presence === 'working' || agent.presence === 'at_capacity') {
        working.push(agent);
      } else {
        pausedOffline.push(agent);
      }
    }

    return { available, working, pausedOffline };
  }, [filteredAgents]);

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
  const canStartExecution = hasAgentAssignment && !activeExecution && !isOrphanedAssignment;
  const canCancelExecution = Boolean(activeExecution);
  const startLabel = executionStatus?.hasExecution ? 'Run again' : 'Start execution';
  const executionHint = isOrphanedAssignment
    ? 'Assigned agent no longer exists. Please re-assign.'
    : !hasAgentAssignment
      ? 'Assign an agent to enable execution.'
      : 'Runs update in real time.';

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
  }, [actor?.type]);

  const comments = commentsQuery.data ?? [];
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

    if (executionStatus?.hasExecution && executionStatus.startedAt) {
      next.push({
        id: `execution-status-${executionStatus.runId ?? itemId}`,
        kind: 'execution-status',
        actorType: 'system',
        timestamp: executionStatus.startedAt,
        sortTime: new Date(executionStatus.startedAt).getTime(),
        title: executionStatus.state ? `Execution ${toTitleCase(toStatusLabel(executionStatus.state))}` : 'Execution started',
        body: executionStatus.currentStep
          ? executionStatus.currentStep
          : executionStatus.phase
            ? `Phase ${toTitleCase(toStatusLabel(executionStatus.phase))}`
            : executionHint,
        meta: executionStatus.runId ? `Run ${shortenAssigneeId(executionStatus.runId)}` : undefined,
      });
    }

    executionSteps.forEach((step) => {
      const timestamp = step.completedAt ?? step.startedAt ?? null;
      next.push({
        id: `execution-step-${step.stepId}`,
        kind: 'execution-step',
        actorType: 'system',
        timestamp,
        sortTime: timestamp ? new Date(timestamp).getTime() : 0,
        title: toTitleCase(toStatusLabel(step.stepType)),
        body: step.contentPreview ?? step.contentFull ?? `Phase ${toTitleCase(toStatusLabel(step.phase))}`,
        meta: [
          step.phase ? toTitleCase(toStatusLabel(step.phase)) : null,
          (step.toolCalls ?? 0) > 0 ? `${step.toolCalls ?? 0} tool ${(step.toolCalls ?? 0) === 1 ? 'call' : 'calls'}` : null,
          step.modelId ?? null,
        ].filter(Boolean).join(' • ') || undefined,
      });
    });

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
  }, [comments, executionHint, executionStatus, executionSteps, itemId, resolveCommentProfile]);

  const filteredActivityEntries = useMemo(() => {
    if (activityFilter === 'all') return activityEntries;
    if (activityFilter === 'humans') return activityEntries.filter((entry) => entry.actorType === 'user');
    if (activityFilter === 'agents') return activityEntries.filter((entry) => entry.actorType === 'agent');
    return activityEntries.filter((entry) => entry.actorType === 'system');
  }, [activityEntries, activityFilter]);

  const previewActivityEntries = useMemo(() => activityEntries.slice(0, 3), [activityEntries]);

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
  }, [actor?.id, commentAuthorType, commentDraftValue, itemId, postComment]);

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
    executeWorkItem.mutate({ itemId, orgId: orgId ?? null, projectId });
  }, [canStartExecution, executeWorkItem, itemId, orgId, projectId]);

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
            setAssigneeSearch('');
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
  const hasExecutionCard = Boolean(hasAgentAssignment || executionStatus?.hasExecution || clarificationRequests.length > 0);
  const structureSummary = item
    ? summarizeStructure(parentItem, childItems, progressRollup)
    : 'No rollup or linked work yet.';
  const executionSummary = summarizeExecution(executionStatus, hasAgentAssignment);
  const commentHint = actor?.id ? 'Cmd+Enter to send' : 'Sign in to comment.';
  const commentPlaceholder = actor?.id
    ? 'Share context for humans and agents...'
    : 'Sign in to leave a comment.';

  const renderAssigneeIdentity = useCallback(() => {
    return (
      <div
        className={`assignee-chip ${
          assignmentProfile ? `assignee-${assignmentProfile.type}` : 'assignee-unassigned'
        }${isOrphanedAssignment ? ' assignee-orphaned' : ''}`}
        aria-label={assignmentProfile ? `Assigned to ${assignmentProfile.label}` : 'Unassigned'}
      >
        <span className="assignee-avatar">
          {assignmentProfile?.actor ? (
            <ActorAvatar actor={assignmentProfile.actor} size="sm" surfaceType="chip" decorative />
          ) : (
            assignmentProfile?.avatar ?? (assignmentProfile ? getInitials(assignmentProfile.label) : '+')
          )}
        </span>
        <span className="assignee-name">
          {assignmentProfile?.label ?? 'Unassigned'}
        </span>
        <span className="assignee-type-label">
          {isOrphanedAssignment ? 'Missing' : assignmentProfile?.type === 'agent' ? 'Agent' : assignmentProfile?.type === 'user' ? 'Human' : 'Unassigned'}
        </span>
      </div>
    );
  }, [assignmentProfile, isOrphanedAssignment]);

  const renderAssigneePicker = useCallback(
    (compact = false) => (
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
          {renderAssigneeIdentity()}
          <span className="field-support-text">{assignmentHint ?? 'Project collaborators'}</span>
        </div>
        {showAssigneePicker && (
          <div className="work-item-stack">
            <input
              className="drawer-input assignee-search-input"
              value={assigneeSearch}
              onChange={(event) => setAssigneeSearch(event.target.value)}
              placeholder="Search people or agents"
              aria-label="Search assignees"
              autoComplete="off"
            />
            <div className="assignee-grid">
              <div className="assignee-group">
                <div className="assignee-group-title">People</div>
                <div className="assignee-options">
                  {filteredHumans.map((profile) => {
                    const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                    return (
                      <button
                        key={`user-${profile.id}`}
                        type="button"
                        className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                        onClick={() => handleAssign(profile)}
                        disabled={assignmentBusy}
                        aria-pressed={isSelected}
                        aria-label={`Assign to ${profile.label}`}
                        data-haptic="light"
                      >
                        <span className="assignee-option-meta">
                          <span className="assignee-avatar">
                            {profile.actor ? (
                              <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                            ) : (
                              profile.avatar ?? getInitials(profile.label)
                            )}
                          </span>
                          <span className="assignee-text">
                            <span className="assignee-name">{profile.label}</span>
                            <span className="assignee-subtitle">{profile.subtitle ?? 'Human'}</span>
                          </span>
                        </span>
                        <span className="assignee-status">Human</span>
                      </button>
                    );
                  })}
                  {!filteredHumans.length && (
                    <div className="assignee-empty">
                      {assigneeSearchValue ? 'No people match this search.' : 'No people available yet.'}
                    </div>
                  )}
                </div>
              </div>

              {groupedAgents.available.length > 0 && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Available now</div>
                  <div className="assignee-options">
                    {groupedAgents.available.map((profile) => {
                      const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                      return (
                        <button
                          key={`agent-${profile.id}`}
                          type="button"
                          className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                          onClick={() => handleAssign(profile)}
                          disabled={assignmentBusy}
                          aria-pressed={isSelected}
                          aria-label={`Assign to ${profile.label}`}
                          data-haptic="light"
                        >
                          <span className="assignee-option-meta">
                            <span className="assignee-avatar">
                              {profile.actor ? (
                                <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                              ) : (
                                profile.avatar ?? getInitials(profile.label)
                              )}
                            </span>
                            <span className="assignee-text">
                              <span className="assignee-name">{profile.label}</span>
                              <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                            </span>
                          </span>
                          <span className="assignee-status assignee-status-available">
                            {profile.presenceLabel ?? 'Available'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {groupedAgents.working.length > 0 && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Working</div>
                  <div className="assignee-options">
                    {groupedAgents.working.map((profile) => {
                      const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                      const contextLabel = profile.activeItemCount
                        ? `${profile.presenceLabel ?? 'Working'} • ${profile.activeItemCount} item${profile.activeItemCount > 1 ? 's' : ''}`
                        : profile.presenceLabel ?? toStatusLabel(profile.status);
                      return (
                        <button
                          key={`agent-${profile.id}`}
                          type="button"
                          className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                          onClick={() => handleAssign(profile)}
                          disabled={assignmentBusy}
                          aria-pressed={isSelected}
                          aria-label={`Assign to ${profile.label}`}
                          data-haptic="light"
                        >
                          <span className="assignee-option-meta">
                            <span className="assignee-avatar">
                              {profile.actor ? (
                                <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                              ) : (
                                profile.avatar ?? getInitials(profile.label)
                              )}
                            </span>
                            <span className="assignee-text">
                              <span className="assignee-name">{profile.label}</span>
                              <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                            </span>
                          </span>
                          <span className="assignee-status assignee-status-working">{contextLabel ?? 'Working'}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {groupedAgents.pausedOffline.length > 0 && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Paused / Offline</div>
                  <div className="assignee-options">
                    {groupedAgents.pausedOffline.map((profile) => {
                      const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                      return (
                        <button
                          key={`agent-${profile.id}`}
                          type="button"
                          className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                          onClick={() => handleAssign(profile)}
                          disabled={assignmentBusy}
                          aria-pressed={isSelected}
                          aria-label={`Assign to ${profile.label}`}
                          data-haptic="light"
                        >
                          <span className="assignee-option-meta">
                            <span className="assignee-avatar">
                              {profile.actor ? (
                                <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                              ) : (
                                profile.avatar ?? getInitials(profile.label)
                              )}
                            </span>
                            <span className="assignee-text">
                              <span className="assignee-name">{profile.label}</span>
                              <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                            </span>
                          </span>
                          <span className="assignee-status assignee-status-offline">
                            {profile.presenceLabel ?? 'Offline'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {!filteredAgents.length && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Agents</div>
                  <div className="assignee-options">
                    <div className="assignee-empty">
                      {assigneeSearchValue ? 'No agents match this search.' : 'No agents available yet.'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    ),
    [
      assigneeSearch,
      assigneeSearchValue,
      assignmentBusy,
      assignmentHint,
      assignmentProfile,
      filteredHumans,
      groupedAgents.available,
      groupedAgents.pausedOffline,
      groupedAgents.working,
      handleAssign,
      handleUnassign,
      item?.assignee_id,
      item?.assignee_type,
      renderAssigneeIdentity,
      showAssigneePicker,
      filteredAgents.length,
    ]
  );

  const renderExecutionCard = useCallback(
    (compact = false) => (
      <div className={`work-item-card-surface${compact ? ' work-item-card-surface-compact' : ''}`}>
        <div className="work-item-card-header">
          <div>
            <div className="work-item-card-eyebrow">Execution</div>
            <div className="work-item-card-title-small">{executionSummary}</div>
          </div>
          <div className="work-item-inline-badges">
            {executionStatus?.state && (
              <span className={`activity-badge activity-badge-system activity-badge-state-${executionStatus.state}`}>
                {toTitleCase(toStatusLabel(executionStatus.state))}
              </span>
            )}
            {clarificationRequests.length > 0 && (
              <span className="activity-badge activity-badge-warning">{clarificationRequests.length} needs input</span>
            )}
          </div>
        </div>
        <div className="work-item-stack">
          <ExecutionStatusCard
            title={executionStatus?.hasExecution ? 'Execution' : hasAgentAssignment ? 'Ready to run' : 'Execution'}
            status={executionStatus}
            isLoading={executionStatusQuery.isLoading}
            subtitle={executionHint}
            actions={
              <>
                <button
                  type="button"
                  className="execution-action-button pressable"
                  onClick={handleStartExecution}
                  disabled={!canStartExecution || executeWorkItem.isPending}
                  title={canStartExecution ? startLabel : executionHint}
                  data-haptic="light"
                >
                  {executeWorkItem.isPending ? 'Starting...' : startLabel}
                </button>
                <button
                  type="button"
                  className="execution-action-button execution-action-secondary pressable"
                  onClick={handleCancelExecution}
                  disabled={!canCancelExecution || cancelExecution.isPending}
                  data-haptic="light"
                >
                  {cancelExecution.isPending ? 'Cancelling...' : 'Cancel'}
                </button>
                <button
                  type="button"
                  className="execution-action-button execution-action-ghost pressable"
                  onClick={handleRefreshExecution}
                  disabled={executionStatusQuery.isFetching}
                >
                  {executionStatusQuery.isFetching ? 'Refreshing...' : 'Refresh'}
                </button>
              </>
            }
          />

          {clarificationRequests.length > 0 && (
            <ClarificationPanel
              questions={clarificationRequests}
              onSubmit={handleClarificationSubmit}
              isSubmitting={provideClarification.isPending}
              title="Agent needs your input"
            />
          )}
        </div>
      </div>
    ),
    [
      canCancelExecution,
      canStartExecution,
      cancelExecution.isPending,
      clarificationRequests,
      executeWorkItem.isPending,
      executionHint,
      executionStatus,
      executionStatusQuery.isFetching,
      executionStatusQuery.isLoading,
      executionSummary,
      handleCancelExecution,
      handleClarificationSubmit,
      handleRefreshExecution,
      handleStartExecution,
      hasAgentAssignment,
      provideClarification.isPending,
      startLabel,
    ]
  );

  const renderStructureCard = useCallback(
    (compact = false) => (
      <div className={`work-item-card-surface${compact ? ' work-item-card-surface-compact' : ''}`}>
        <div className="work-item-card-header">
          <div>
            <div className="work-item-card-eyebrow">Structure</div>
            <div className="work-item-card-title-small">{structureSummary}</div>
          </div>
          {(showProgressSection || showChildrenSection || showParentSection) && (
            <div className="work-item-inline-badges">
              {showChildrenSection && <span className="activity-badge activity-badge-system">{childItems.length} linked</span>}
              {showProgressSection && progressRollup && (
                <span className="activity-badge activity-badge-system">{Math.round(progressRollup.completion_percent)}% complete</span>
              )}
            </div>
          )}
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

          {showChildrenSection && (
            <div className="work-item-stack">
              <div className="drawer-label-row">
                <label className="drawer-label">{item?.item_type === 'feature' ? 'Tasks' : 'Features'}</label>
                <span className="drawer-assignee-hint">{childItems.length} linked</span>
              </div>
              <div className="hierarchy-children work-item-card-soft">
                {childItems.map((child) => (
                  <div key={child.item_id} className="hierarchy-child">
                    <span className={`hierarchy-chip hierarchy-chip-${child.item_type}`}>
                      {shortId(child, projectSlug)} • {child.title}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {showProgressSection && progressRollup && (
            <div className="drawer-progress-panel work-item-card-soft">
              <div className="drawer-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={completionPercent}>
                <div
                  className="drawer-progress-fill"
                  style={{ width: `${Math.min(100, Math.max(0, completionPercent))}%` }}
                />
              </div>
              <div className="drawer-progress-buckets">
                <span className="drawer-progress-chip drawer-progress-chip-not-started">
                  {progressRollup.buckets.not_started} not started
                </span>
                <span className="drawer-progress-chip drawer-progress-chip-in-progress">
                  {progressRollup.buckets.in_progress} in progress
                </span>
                <span className="drawer-progress-chip drawer-progress-chip-completed">
                  {progressRollup.buckets.completed} completed
                </span>
              </div>
              <div className="drawer-progress-remaining">{formatRollupRemaining(progressRollup)}</div>
            </div>
          )}
        </div>
      </div>
    ),
    [
      childItems,
      completionPercent,
      handleParentChange,
      item?.item_type,
      item?.parent_id,
      parentCandidates,
      parentItem,
      parentLabel,
      progressRollup,
      projectSlug,
      showChildrenSection,
      showParentSection,
      showProgressSection,
      structureSummary,
    ]
  );

  const renderDetailsCard = useCallback(
    () => (
      <div className="work-item-card-surface">
        <div className="work-item-card-header">
          <div>
            <div className="work-item-card-eyebrow">Details</div>
            <div className="work-item-card-title-small">Dates, estimates, labels, and system metadata</div>
          </div>
          <button
            type="button"
            className="drawer-inline-button pressable"
            onClick={() => setShowAdvancedDetails((current) => !current)}
          >
            {showAdvancedDetails ? 'Hide system' : 'Show system'}
          </button>
        </div>

        <div className="work-item-stack">
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
      estimatedHoursDraft,
      handleDateChange,
      handleLabelsRemove,
      handleNewLabelKeyDown,
      handleNumberBlur,
      item?.behavior_id,
      item?.created_at,
      item?.metadata,
      item?.run_id,
      item?.updated_at,
      labels,
      newLabelDraft,
      pointsDraft,
      showAdvancedDetails,
      startDateDraft,
      targetDateDraft,
    ]
  );

  const renderActivityPreview = useCallback(
    () => (
      <div className="work-item-card-surface work-item-card-surface-compact">
        <div className="work-item-card-header">
          <div>
            <div className="work-item-card-eyebrow">Recent activity</div>
            <div className="work-item-card-title-small">
              {activityEntries.length > 0 ? `${activityEntries.length} recent updates` : 'No recent updates'}
            </div>
          </div>
          <button
            type="button"
            className="drawer-inline-button pressable"
            onClick={() => onPresentationModeChange('studio')}
          >
            Open studio
          </button>
        </div>
        <div className="activity-feed-preview">
          {previewActivityEntries.length === 0 && (
            <div className="activity-empty">Comments and execution history will appear here.</div>
          )}
          {previewActivityEntries.map((entry) => (
            <div key={entry.id} className="activity-entry activity-entry-preview">
              <div className="activity-entry-topline">
                <span className={`activity-badge activity-badge-${entry.actorType}`}>
                  {entry.actorType === 'system' ? 'System' : entry.actorType === 'agent' ? 'Agent' : 'Human'}
                </span>
                <span className="activity-time">{formatRelativeTime(entry.timestamp)}</span>
              </div>
              <div className="activity-title">{entry.title}</div>
              <div className="activity-body">{entry.body}</div>
            </div>
          ))}
        </div>
      </div>
    ),
    [activityEntries.length, onPresentationModeChange, previewActivityEntries]
  );

  const renderStudioActivity = useCallback(
    () => (
      <section className="work-item-card-surface work-item-card-surface-main">
        <div className="work-item-card-header">
          <div>
            <div className="work-item-card-eyebrow">Activity</div>
            <div className="work-item-card-title-small">Comments, execution steps, and system updates in one feed</div>
          </div>
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
              <div className="activity-empty" role="status">
                Loading activity...
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

  const renderPeek = useCallback(() => (
    <div className="work-item-peek-layout">
      <section className="work-item-card-surface work-item-card-surface-main work-item-peek-hero-card">
        <div className="work-item-hero">
          <div className="work-item-hero-topline">
            <span className={`work-item-type-pill work-item-type-pill-${item?.item_type ?? 'goal'}`}>{typeLabel}</span>
            <span className="work-item-hero-id">{item ? shortId(item, projectSlug) : shortId(itemId, projectSlug)}</span>
            {shouldHighlightPriority(priorityDraft) && (
              <span className={`activity-badge activity-badge-priority-${priorityDraft}`}>{toTitleCase(priorityDraft)}</span>
            )}
          </div>
          <label className="drawer-label" htmlFor="work-item-title">Title</label>
          <input
            id="work-item-title"
            ref={titleRef}
            className="drawer-input work-item-title-input work-item-title-input-peek"
            value={titleDraft}
            onChange={handleTitleChange}
            onBlur={() => debouncedSave.schedule()}
            placeholder="What needs to happen?"
            autoComplete="off"
          />
          <div className="work-item-summary-chips">
            <span className="summary-chip">Updated {formatRelativeTime(item?.updated_at)}</span>
            <span className="summary-chip">{activityEntries.length} activities</span>
            {progressRollup && <span className="summary-chip">{completionPercent}% complete</span>}
          </div>
        </div>
      </section>

      <section className="work-item-card-surface work-item-card-surface-compact">
        <div className="work-item-card-header work-item-card-header-compact">
          <div>
            <div className="work-item-card-eyebrow">Quick controls</div>
          </div>
        </div>
        <div className="work-item-peek-controls-grid">
          <div className="work-item-field">
            <label className="drawer-label" htmlFor="work-item-column">Status / Column</label>
            <select
              id="work-item-column"
              className="drawer-select"
              value={item?.column_id ?? '__none__'}
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

          <div className="work-item-field">
            <label className="drawer-label" htmlFor="work-item-due-date">Due date</label>
            <input
              id="work-item-due-date"
              type="date"
              className="drawer-input"
              value={dueDateDraft}
              onChange={(event) => handleDateChange('due_date', event.target.value)}
            />
            <span className="field-support-text">{dueDateDraft ? formatCompactDate(item?.due_date) : 'Add a due date'}</span>
          </div>

          {shouldHighlightPriority(priorityDraft) && (
            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-priority">Priority</label>
              <select
                id="work-item-priority"
                className="drawer-select"
                value={priorityDraft}
                onChange={handlePriorityChange}
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
          )}

          <div className="work-item-field work-item-field-span-2">
            <div className="drawer-label-row">
              <label className="drawer-label">Assignee</label>
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
            <div className="work-item-inline-summary">
              {renderAssigneeIdentity()}
              <span className="field-support-text">{assignmentHint ?? 'Project collaborators'}</span>
            </div>
          </div>
        </div>

        {showAssigneePicker && (
          <div className="work-item-peek-picker-wrap">
            <input
              className="drawer-input assignee-search-input"
              value={assigneeSearch}
              onChange={(event) => setAssigneeSearch(event.target.value)}
              placeholder="Search people or agents"
              aria-label="Search assignees"
              autoComplete="off"
            />
            <div className="assignee-grid">
              <div className="assignee-group">
                <div className="assignee-group-title">People</div>
                <div className="assignee-options">
                  {filteredHumans.map((profile) => {
                    const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                    return (
                      <button
                        key={`user-${profile.id}`}
                        type="button"
                        className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                        onClick={() => handleAssign(profile)}
                        disabled={assignmentBusy}
                        aria-pressed={isSelected}
                        aria-label={`Assign to ${profile.label}`}
                        data-haptic="light"
                      >
                        <span className="assignee-option-meta">
                          <span className="assignee-avatar">
                            {profile.actor ? (
                              <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                            ) : (
                              profile.avatar ?? getInitials(profile.label)
                            )}
                          </span>
                          <span className="assignee-text">
                            <span className="assignee-name">{profile.label}</span>
                            <span className="assignee-subtitle">{profile.subtitle ?? 'Human'}</span>
                          </span>
                        </span>
                        <span className="assignee-status">Human</span>
                      </button>
                    );
                  })}
                  {!filteredHumans.length && (
                    <div className="assignee-empty">
                      {assigneeSearchValue ? 'No people match this search.' : 'No people available yet.'}
                    </div>
                  )}
                </div>
              </div>

              {groupedAgents.available.length > 0 && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Available now</div>
                  <div className="assignee-options">
                    {groupedAgents.available.map((profile) => {
                      const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                      return (
                        <button
                          key={`agent-${profile.id}`}
                          type="button"
                          className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                          onClick={() => handleAssign(profile)}
                          disabled={assignmentBusy}
                          aria-pressed={isSelected}
                          aria-label={`Assign to ${profile.label}`}
                          data-haptic="light"
                        >
                          <span className="assignee-option-meta">
                            <span className="assignee-avatar">
                              {profile.actor ? (
                                <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                              ) : (
                                profile.avatar ?? getInitials(profile.label)
                              )}
                            </span>
                            <span className="assignee-text">
                              <span className="assignee-name">{profile.label}</span>
                              <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                            </span>
                          </span>
                          <span className="assignee-status assignee-status-available">
                            {profile.presenceLabel ?? 'Available'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {groupedAgents.working.length > 0 && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Working</div>
                  <div className="assignee-options">
                    {groupedAgents.working.map((profile) => {
                      const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                      const contextLabel = profile.activeItemCount
                        ? `${profile.presenceLabel ?? 'Working'} • ${profile.activeItemCount} item${profile.activeItemCount > 1 ? 's' : ''}`
                        : profile.presenceLabel ?? toStatusLabel(profile.status);
                      return (
                        <button
                          key={`agent-${profile.id}`}
                          type="button"
                          className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                          onClick={() => handleAssign(profile)}
                          disabled={assignmentBusy}
                          aria-pressed={isSelected}
                          aria-label={`Assign to ${profile.label}`}
                          data-haptic="light"
                        >
                          <span className="assignee-option-meta">
                            <span className="assignee-avatar">
                              {profile.actor ? (
                                <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                              ) : (
                                profile.avatar ?? getInitials(profile.label)
                              )}
                            </span>
                            <span className="assignee-text">
                              <span className="assignee-name">{profile.label}</span>
                              <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                            </span>
                          </span>
                          <span className="assignee-status assignee-status-working">{contextLabel ?? 'Working'}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {groupedAgents.pausedOffline.length > 0 && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Paused / Offline</div>
                  <div className="assignee-options">
                    {groupedAgents.pausedOffline.map((profile) => {
                      const isSelected = item?.assignee_id === profile.id && item?.assignee_type === profile.type;
                      return (
                        <button
                          key={`agent-${profile.id}`}
                          type="button"
                          className={`assignee-option pressable ${isSelected ? 'assignee-option-selected' : ''}`}
                          onClick={() => handleAssign(profile)}
                          disabled={assignmentBusy}
                          aria-pressed={isSelected}
                          aria-label={`Assign to ${profile.label}`}
                          data-haptic="light"
                        >
                          <span className="assignee-option-meta">
                            <span className="assignee-avatar">
                              {profile.actor ? (
                                <ActorAvatar actor={profile.actor} size="sm" surfaceType="chip" decorative />
                              ) : (
                                profile.avatar ?? getInitials(profile.label)
                              )}
                            </span>
                            <span className="assignee-text">
                              <span className="assignee-name">{profile.label}</span>
                              <span className="assignee-subtitle">{profile.subtitle ?? 'Agent'}</span>
                            </span>
                          </span>
                          <span className="assignee-status assignee-status-offline">
                            {profile.presenceLabel ?? 'Offline'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {!filteredAgents.length && (
                <div className="assignee-group">
                  <div className="assignee-group-title">Agents</div>
                  <div className="assignee-options">
                    <div className="assignee-empty">
                      {assigneeSearchValue ? 'No agents match this search.' : 'No agents available yet.'}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {hasExecutionCard && renderExecutionCard(true)}

      <section className="work-item-card-surface work-item-card-surface-compact">
        <div className="work-item-card-header work-item-card-header-compact">
          <div>
            <div className="work-item-card-eyebrow">Context</div>
            <div className="work-item-card-title-small">Description, structure, and momentum at a glance</div>
          </div>
          <button
            type="button"
            className="drawer-inline-button pressable"
            onClick={() => onPresentationModeChange('studio')}
          >
            Edit in studio
          </button>
        </div>
        <div className="work-item-peek-context-grid">
          <div className="work-item-field">
            <div className="drawer-label-row">
              <label className="drawer-label">Description</label>
              <span className="drawer-assignee-hint">{descriptionDraft.trim() ? 'Context ready' : 'Needs detail'}</span>
            </div>
            <div className="description-preview">{summarizeDescription(descriptionDraft)}</div>
          </div>
          {(showParentSection || showChildrenSection || showProgressSection) && (
            <div className="work-item-field">
              <div className="drawer-label-row">
                <label className="drawer-label">Structure</label>
                <span className="drawer-assignee-hint">
                  {showChildrenSection ? `${childItems.length} linked` : showProgressSection && progressRollup ? `${completionPercent}% complete` : 'Linked work'}
                </span>
              </div>
              <div className="work-item-structure-preview">
                <span className="structure-preview-copy">{structureSummary}</span>
                {showProgressSection && progressRollup && (
                  <div className="drawer-progress-track work-item-peek-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={completionPercent}>
                    <div
                      className="drawer-progress-fill"
                      style={{ width: `${Math.min(100, Math.max(0, completionPercent))}%` }}
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      {renderActivityPreview()}
    </div>
  ), [
    activityEntries.length,
    columns,
    completionPercent,
    debouncedSave,
    descriptionDraft,
    dueDateDraft,
    handleColumnChange,
    handleDateChange,
    handlePriorityChange,
    handleTitleChange,
    hasExecutionCard,
    item,
    itemId,
    onPresentationModeChange,
    presentationMode,
    priorityDraft,
    progressRollup,
    projectSlug,
    renderActivityPreview,
    renderExecutionCard,
    shouldHighlightPriority(priorityDraft),
    showChildrenSection,
    showParentSection,
    showProgressSection,
    titleDraft,
    typeLabel,
  ]);

  const renderStudio = useCallback(() => (
    <div className="work-item-studio-layout">
      <div className="work-item-studio-main">
        <section className="work-item-card-surface work-item-card-surface-main">
          <div className="work-item-hero work-item-hero-studio">
            <div className="work-item-hero-topline">
              <span className={`work-item-type-pill work-item-type-pill-${item?.item_type ?? 'goal'}`}>{typeLabel}</span>
              <span className="work-item-hero-id">{item ? shortId(item, projectSlug) : shortId(itemId, projectSlug)}</span>
              <span className="summary-chip">{toTitleCase(toStatusLabel(item?.status ?? 'backlog'))}</span>
              <span className="summary-chip">Updated {formatRelativeTime(item?.updated_at)}</span>
            </div>
            <label className="drawer-label" htmlFor="work-item-title">Title</label>
            <input
              id="work-item-title"
              ref={titleRef}
              className="drawer-input work-item-title-input work-item-title-input-studio"
              value={titleDraft}
              onChange={handleTitleChange}
              onBlur={() => debouncedSave.schedule()}
              placeholder="What needs to happen?"
              autoComplete="off"
            />
            <div className="studio-subtitle-row">
              <div className="studio-subtitle-copy">
                {assignmentProfile ? `${assignmentProfile.label} owns this ${typeLabel.toLowerCase()}.` : `Assign an owner to move this ${typeLabel.toLowerCase()} forward.`}
              </div>
              {item?.due_date && <span className="summary-chip">Due {formatAbsoluteDate(item.due_date)}</span>}
              {shouldHighlightPriority(priorityDraft) && <span className={`activity-badge activity-badge-priority-${priorityDraft}`}>{toTitleCase(priorityDraft)}</span>}
            </div>
          </div>
        </section>

        <section className="work-item-card-surface work-item-card-surface-main">
          <div className="work-item-card-header">
            <div>
              <div className="work-item-card-eyebrow">Description</div>
              <div className="work-item-card-title-small">Long-form context, acceptance criteria, and links</div>
            </div>
            <span className="field-support-text">Autosaves after you pause typing</span>
          </div>
          <textarea
            id="work-item-description"
            className="drawer-textarea work-item-description-input"
            value={descriptionDraft}
            onChange={handleDescriptionChange}
            onBlur={() => debouncedSave.schedule()}
            placeholder="Add context, links, acceptance criteria, risks, or blockers..."
            rows={10}
          />
        </section>

        {renderStudioActivity()}
      </div>

      <aside className="work-item-studio-rail">
        <section className="work-item-card-surface">
          <div className="work-item-card-header">
            <div>
              <div className="work-item-card-eyebrow">Overview</div>
              <div className="work-item-card-title-small">Primary controls for this work item</div>
            </div>
          </div>

          <div className="work-item-stack">
            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-column-studio">Status / Column</label>
              <select
                id="work-item-column-studio"
                className="drawer-select"
                value={item?.column_id ?? '__none__'}
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

            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-priority-studio">Priority</label>
              <select
                id="work-item-priority-studio"
                className="drawer-select"
                value={priorityDraft}
                onChange={handlePriorityChange}
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>

            <div className="work-item-field">
              <label className="drawer-label" htmlFor="work-item-due-date-studio">Due date</label>
              <input
                id="work-item-due-date-studio"
                type="date"
                className="drawer-input"
                value={dueDateDraft}
                onChange={(event) => handleDateChange('due_date', event.target.value)}
              />
            </div>
          </div>
        </section>

        {renderAssigneePicker(false)}
        {(showParentSection || showChildrenSection || showProgressSection) && renderStructureCard(false)}
        {renderExecutionCard(false)}
        {renderDetailsCard()}
      </aside>
    </div>
  ), [
    assignmentProfile,
    columns,
    debouncedSave,
    descriptionDraft,
    dueDateDraft,
    handleColumnChange,
    handleDateChange,
    handleDescriptionChange,
    handlePriorityChange,
    handleTitleChange,
    item,
    itemId,
    priorityDraft,
    renderAssigneePicker,
    renderDetailsCard,
    renderExecutionCard,
    renderStructureCard,
    renderStudioActivity,
    showChildrenSection,
    showParentSection,
    showProgressSection,
    titleDraft,
    typeLabel,
  ]);

  return (
    <div
      ref={overlayRef}
      className={`work-item-drawer-overlay ${phase === 'open' ? 'open' : ''} ${phase === 'closing' ? 'closing' : ''} presentation-${presentationMode}`}
      onMouseDown={handleOverlayMouseDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="work-item-title"
    >
      <aside
        className={`work-item-drawer work-item-drawer-${presentationMode}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="work-item-drawer-header">
          <div className="work-item-drawer-header-left">
            <div className="work-item-drawer-meta">
              <div className="work-item-drawer-type">{typeLabel}</div>
              {item?.item_id && (
                <div className="work-item-drawer-id-group">
                  <div className="work-item-drawer-id" title={item.item_id}>{shortId(item, projectSlug)}</div>
                  <button
                    type="button"
                    className="work-item-inline-copy pressable"
                    onClick={handleCopyCurrentItemId}
                    aria-label={`Copy work item ID ${item.item_id}`}
                    title="Copy work item ID"
                  >
                    Copy ID
                  </button>
                </div>
              )}
              {saveLabel && <div className="work-item-drawer-save">{saveLabel}</div>}
            </div>
          </div>
          <div className="work-item-drawer-header-right">
            <button
              type="button"
              className="work-item-drawer-action work-item-drawer-action-label pressable"
              onClick={() => onPresentationModeChange(presentationMode === 'peek' ? 'studio' : 'peek')}
            >
              {presentationMode === 'peek' ? 'Open studio' : 'Back to peek'}
            </button>
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
          {isLoading && (
            <div className="work-item-drawer-skeleton" aria-label="Loading work item">
              <div className="skeleton-line animate-shimmer" />
              <div className="skeleton-line animate-shimmer" />
              <div className="skeleton-block animate-shimmer" />
            </div>
          )}

          {isError && (
            <div className="work-item-drawer-error animate-fade-in-up" role="status">
              Couldn't load this work item.
            </div>
          )}

          {!isLoading && item && (
            <div className={`work-item-surface work-item-surface-${presentationMode}`}>
              {presentationMode === 'peek' ? renderPeek() : renderStudio()}
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
