export type ExecutionControlState =
  | 'idle'
  | 'ready'
  | 'pending'
  | 'queued'
  | 'running'
  | 'paused'
  | 'needs_clarification'
  | 'failed'
  | 'completed'
  | 'cancelled'
  | 'missing_agent'
  | 'unavailable';

export interface ExecutionControlInput {
  rawState?: string | null;
  hasExecution?: boolean;
  hasAgentAssignment?: boolean;
  isOrphanedAssignment?: boolean;
  executionAvailable?: boolean;
  pendingClarificationCount?: number;
}

export interface ExecutionControlModel {
  state: ExecutionControlState;
  isActive: boolean;
  canStart: boolean;
  canCancel: boolean;
  canClarify: boolean;
  canOpenRun: boolean;
  summary: string;
  startLabel: string;
  cancelLabel: string;
  refreshLabel: string;
  openRunLabel: string;
  startTitle: string;
  statusLabel: string;
}

export function normalizeExecutionControlState(
  rawState?: string | null,
  pendingClarificationCount = 0
): ExecutionControlState {
  if (pendingClarificationCount > 0) return 'needs_clarification';
  if (!rawState) return 'idle';
  const state = rawState.toLowerCase().replace(/\s+/g, '_');
  if (state === 'pending' || state === 'queued' || state === 'running' || state === 'paused') return state;
  if (state === 'failed' || state === 'completed' || state === 'cancelled') return state;
  if (state === 'canceled') return 'cancelled';
  return 'idle';
}

export function isActiveExecutionState(state: ExecutionControlState): boolean {
  return state === 'pending' || state === 'queued' || state === 'running' || state === 'paused' || state === 'needs_clarification';
}

function titleCase(input: string): string {
  return input.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function buildExecutionControlModel(input: ExecutionControlInput): ExecutionControlModel {
  const hasExecution = input.hasExecution === true || Boolean(input.rawState);
  const hasAgentAssignment = input.hasAgentAssignment === true;
  const executionAvailable = input.executionAvailable !== false;
  const pendingClarificationCount = input.pendingClarificationCount ?? 0;

  let state = normalizeExecutionControlState(input.rawState, pendingClarificationCount);
  if (!executionAvailable) state = 'unavailable';
  if (input.isOrphanedAssignment) state = 'missing_agent';
  if (state === 'idle' && hasAgentAssignment) state = 'ready';

  const isActive = isActiveExecutionState(state);
  const canStart = executionAvailable && hasAgentAssignment && !input.isOrphanedAssignment && !isActive;
  const canCancel = executionAvailable && isActive;
  const canClarify = state === 'needs_clarification';

  const summaryByState: Record<ExecutionControlState, string> = {
    idle: 'Assign an agent to run',
    ready: 'Ready to run',
    pending: 'Pending start',
    queued: 'Queued',
    running: 'Running now',
    paused: 'Paused',
    needs_clarification: 'Needs your input',
    failed: 'Last run failed',
    completed: 'Last run completed',
    cancelled: 'Last run cancelled',
    missing_agent: 'Assigned agent is missing',
    unavailable: 'Execution unavailable',
  };

  const startTitle = !executionAvailable
    ? 'Execution is unavailable in this deployment'
    : input.isOrphanedAssignment
      ? 'Assigned agent no longer exists. Please re-assign.'
      : !hasAgentAssignment
        ? 'Assign an agent to enable execution'
        : isActive
          ? 'Execution already active'
          : hasExecution
            ? 'Start a new execution run'
            : 'Start execution';

  return {
    state,
    isActive,
    canStart,
    canCancel,
    canClarify,
    canOpenRun: hasExecution,
    summary: summaryByState[state],
    startLabel: hasExecution ? 'Run again' : 'Start execution',
    cancelLabel: 'Cancel',
    refreshLabel: 'Refresh',
    openRunLabel: 'Open run',
    startTitle,
    statusLabel: titleCase(state),
  };
}
