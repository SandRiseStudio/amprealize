import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WorkItemDrawer } from '../components/boards/WorkItemDrawer';
import type { ExecutionStatus, ExecutionStep } from '../lib/collab-client';
import type { BoardColumn, WorkItem } from '../api/boards';

const mockWorkItem: WorkItem = {
  item_id: 'item-1',
  item_type: 'task',
  project_id: 'project-1',
  board_id: 'board-1',
  column_id: 'column-1',
  parent_id: null,
  title: 'Render execution trace',
  description: 'Show trace summary in drawer',
  status: 'in_progress',
  priority: 'high',
  position: 1,
  labels: ['observability'],
  assignee_id: 'agent-1',
  assignee_type: 'agent',
  display_number: 1136,
  metadata: {},
  created_at: '2026-04-28T18:00:00Z',
  updated_at: '2026-04-28T19:00:00Z',
  created_by: 'user-1',
};

const columns: BoardColumn[] = [
  {
    column_id: 'column-1',
    board_id: 'board-1',
    name: 'In progress',
    position: 1,
    status_mapping: 'in_progress',
    wip_limit: null,
    created_at: '2026-04-28T18:00:00Z',
    updated_at: '2026-04-28T19:00:00Z',
    created_by: 'user-1',
  },
];

const mockMutation = {
  mutate: vi.fn(),
  mutateAsync: vi.fn(),
  isPending: false,
  isError: false,
};

let executionStatus: ExecutionStatus | null = null;
let executionSteps: ExecutionStep[] = [];

vi.mock('../auth', () => ({
  useAuth: () => ({
    actor: { id: 'user-1', displayName: 'Nick Sanders', role: 'owner' },
  }),
}));

vi.mock('../api/boards', () => ({
  useWorkItem: () => ({ data: mockWorkItem, isLoading: false, isError: false }),
  useWorkItems: () => ({ data: [], isLoading: false }),
  useWorkItemComments: () => ({
    data: [],
    isLoading: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
  useWorkItemProgressRollup: () => ({ data: null }),
  useUpdateWorkItem: () => mockMutation,
  useAssignWorkItem: () => mockMutation,
  useUnassignWorkItem: () => mockMutation,
  useCompleteWithDescendants: () => mockMutation,
  usePostWorkItemComment: () => mockMutation,
}));

vi.mock('../api/executions', () => ({
  useWorkItemExecutionStatus: () => ({
    data: executionStatus,
    isLoading: false,
    isFetching: false,
    refetch: vi.fn(),
  }),
  useExecutionSteps: () => ({
    data: { steps: executionSteps, total: executionSteps.length },
  }),
  useExecutionStream: () => ({ isConnected: false, connectionState: 'disconnected' }),
  useExecuteWorkItem: () => mockMutation,
  useCancelWorkItemExecution: () => mockMutation,
  useProvideClarification: () => mockMutation,
  useApproveGate: () => mockMutation,
}));

function renderDrawer() {
  return render(
    <WorkItemDrawer
      projectId="project-1"
      projectSlug="GUIDEAI"
      orgId="org-1"
      boardId="board-1"
      itemId="item-1"
      columns={columns}
      targetPositions={{ 'column-1': 1 }}
      initialItem={mockWorkItem}
      assigneeIndex={new Map()}
      assignableHumans={[]}
      assignableAgents={[]}
      onMove={vi.fn()}
      onCopyWorkItemId={vi.fn()}
      onNotify={vi.fn()}
      onRequestClose={vi.fn()}
    />
  );
}

function makeExecutionStatus(overrides: Partial<ExecutionStatus> = {}): ExecutionStatus {
  return {
    hasExecution: true,
    runId: 'run-chat-123456789',
    workItemId: 'item-1',
    agentId: 'agent-1',
    projectId: 'project-1',
    orgId: 'org-1',
    state: 'running',
    phase: 'executing',
    startedAt: '2026-04-28T18:30:00Z',
    completedAt: null,
    progressPct: 55,
    currentStep: 'Rendering trace panel',
    totalTokens: 900,
    totalCostUsd: 0.012,
    toolCount: 3,
    stepCount: 2,
    error: null,
    lastError: null,
    modelId: 'gpt-5.5',
    surface: 'chat',
    sourceType: 'conversation',
    conversationId: 'conversation-abc123456',
    messageId: 'message-def123456',
    requestId: 'request-ghi123456',
    executionMode: 'direct',
    queueJobId: null,
    queueMetadata: null,
    phaseTimings: {
      planning: { duration_ms: 900, input_tokens: 100, output_tokens: 75, tool_count: 1 },
      executing: { duration_ms: 3400, input_tokens: 600, output_tokens: 459, tool_count: 2 },
    },
    traceSummary: {
      origin: {
        surface: 'chat',
        source_type: 'conversation',
        conversation_id: 'conversation-abc123456',
        message_id: 'message-def123456',
        request_id: 'request-ghi123456',
      },
      execution: {
        run_id: 'run-chat-123456789',
        status: 'running',
        phase: 'executing',
        execution_mode: 'direct',
      },
      metrics: {
        step_count: 2,
        tool_count: 3,
        total_tokens: 1234,
        total_cost_usd: 0.018,
      },
      phase_timings: {
        planning: { duration_ms: 900, input_tokens: 100, output_tokens: 75, tool_count: 1 },
        executing: { duration_ms: 3400, input_tokens: 600, output_tokens: 459, tool_count: 2 },
      },
      last_error: null,
    },
    pendingClarifications: [],
    ...overrides,
  };
}

describe('WorkItemDrawer execution UX', () => {
  it('renders phase stepper and live strip for a running execution', () => {
    executionStatus = makeExecutionStatus();
    executionSteps = [];

    renderDrawer();

    expect(screen.getByLabelText('Execution phases')).toBeInTheDocument();
    expect(screen.getByText(/Executing:/)).toBeInTheDocument();
    expect(screen.getByText(/Polling 2s|Disconnected/)).toBeInTheDocument();
  });

  it('renders failure card when execution failed', () => {
    executionStatus = makeExecutionStatus({
      state: 'failed',
      phase: 'executing',
      lastError: 'Worker timed out',
    });
    executionSteps = [];

    renderDrawer();

    expect(screen.getByRole('alert', { name: /execution failed/i })).toBeInTheDocument();
    expect(screen.getByText('Worker timed out')).toBeInTheDocument();
  });

  it('renders strict gate approval when paused with no clarifications', () => {
    executionStatus = makeExecutionStatus({
      state: 'paused',
      phase: 'verifying',
      pendingClarifications: [],
    });
    executionSteps = [];

    renderDrawer();

    expect(screen.getByRole('button', { name: /approve strict gate/i })).toBeInTheDocument();
  });

  it('renders completed execution without failure card', () => {
    executionStatus = makeExecutionStatus({
      state: 'completed',
      phase: 'completing',
      completedAt: '2026-04-28T19:00:00Z',
    });
    executionSteps = [];

    renderDrawer();

    expect(screen.queryByRole('alert', { name: /execution failed/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Execution phases')).toBeInTheDocument();
  });

  it('shows idle hint when there is no execution', () => {
    executionStatus = {
      hasExecution: false,
      runId: null,
      workItemId: 'item-1',
      agentId: null,
      projectId: 'project-1',
      orgId: 'org-1',
      state: null,
      phase: null,
      startedAt: null,
      completedAt: null,
      progressPct: null,
      currentStep: null,
      totalTokens: null,
      totalCostUsd: null,
      toolCount: null,
      stepCount: null,
      error: null,
      lastError: null,
      modelId: null,
      surface: null,
      sourceType: null,
      conversationId: null,
      messageId: null,
      requestId: null,
      executionMode: null,
      queueJobId: null,
      queueMetadata: null,
      phaseTimings: null,
      traceSummary: null,
      pendingClarifications: [],
    };
    executionSteps = [];

    renderDrawer();

    expect(screen.getByText(/start execution|assign an agent/i)).toBeInTheDocument();
  });
});
