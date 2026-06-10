/**
 * Work Item Execution API (web console)
 *
 * Following:
 * - COLLAB_SAAS_REQUIREMENTS.md: optimistic updates, fast UI
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ConnectionState,
  ExecutionStreamClient,
  type ExecutionListItem,
  type ExecutionListResponse,
  type ExecutionSnapshotEventPayload,
  type ExecutionState,
  type ExecutionStatus,
  type ExecutionStatusEventPayload,
  type ExecutionStatusSnapshotPayload,
  type ExecutionStep,
  type ExecutionStepEventPayload,
  type ExecutionStepSnapshotPayload,
  type ExecutionStepsResponse,
} from '../lib/collab-client';
import { getApiCapabilities } from './capabilities';
import { apiClient, ApiError, API_ORIGIN } from './client';
import { razeLog } from '../telemetry/raze';
import { getPreferredExecutionWorkspaceKind } from '../utils/executionWorkspacePreference';

interface ExecuteResponse {
  success: boolean;
  run_id?: string | null;
  task_cycle_id?: string | null;
  status?: string | null;
  message?: string | null;
}

interface CancelResponse {
  success: boolean;
  message: string;
}

interface ClarifyResponse {
  success: boolean;
  message: string;
}

interface ExecutionStatusResponse {
  has_execution: boolean;
  run_id?: string | null;
  task_cycle_id?: string | null;
  work_item_id?: string | null;
  agent_id?: string | null;
  project_id?: string | null;
  org_id?: string | null;
  state?: string | null;
  phase?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  progress_pct?: number | null;
  current_step?: string | null;
  total_tokens?: number | null;
  total_cost_usd?: number | null;
  tool_count?: number | null;
  step_count?: number | null;
  error?: string | null;
  last_error?: string | null;
  model_id?: string | null;
  surface?: string | null;
  source_type?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  request_id?: string | null;
  execution_mode?: string | null;
  queue_job_id?: string | null;
  queue_metadata?: Record<string, unknown> | null;
  phase_timings?: Record<string, unknown> | null;
  trace_summary?: Record<string, unknown> | null;
  pending_clarifications?: Array<Record<string, unknown>> | null;
}

interface ExecutionListApiResponse {
  executions: Array<{
    run_id: string;
    work_item_id: string;
    work_item_title?: string | null;
    agent_id: string;
    state: string;
    phase?: string | null;
    started_at: string;
    completed_at?: string | null;
    progress_pct: number;
    project_id?: string | null;
    org_id?: string | null;
    model_id?: string | null;
    surface?: string | null;
    source_type?: string | null;
    conversation_id?: string | null;
    message_id?: string | null;
    request_id?: string | null;
    execution_mode?: string | null;
    queue_job_id?: string | null;
    queue_metadata?: Record<string, unknown> | null;
    phase_timings?: Record<string, unknown> | null;
    trace_summary?: Record<string, unknown> | null;
    total_tokens?: number | null;
    total_cost_usd?: number | null;
    tool_count?: number | null;
    step_count?: number | null;
    last_error?: string | null;
  }>;
  total: number;
  offset: number;
  limit: number;
}

interface ExecutionStepsApiResponse {
  steps: Array<{
    step_id: string;
    phase: string;
    step_type: string;
    started_at: string;
    completed_at?: string | null;
    name?: string | null;
    status?: string | null;
    progress_pct?: number | null;
    duration_ms?: number | null;
    input_tokens: number;
    output_tokens: number;
    cost_usd?: number | null;
    tool_calls: number;
    content_preview?: string | null;
    content_full?: string | null;
    tool_names?: string[] | null;
    model_id?: string | null;
    error?: string | null;
    metadata?: Record<string, unknown> | null;
  }>;
  total: number;
}

export const executionKeys = {
  all: ['executions'] as const,
  status: (itemId?: string, orgId?: string | null, projectId?: string | null) =>
    [...executionKeys.all, 'status', itemId, orgId, projectId] as const,
  list: (orgId?: string | null, projectId?: string | null, status?: string | null, limit?: number, offset?: number) =>
    [...executionKeys.all, 'list', orgId, projectId, status ?? 'all', limit ?? 20, offset ?? 0] as const,
  steps: (runId?: string | null) => [...executionKeys.all, 'steps', runId] as const,
};

function mapExecutionStatus(response: ExecutionStatusResponse): ExecutionStatus {
  // Validate state is a valid ExecutionState
  const validStates = ['pending', 'running', 'paused', 'completed', 'failed', 'cancelled'];
  const state = response.state && validStates.includes(response.state) ? response.state as ExecutionState : null;

  return {
    hasExecution: response.has_execution,
    runId: response.run_id ?? null,
    taskCycleId: response.task_cycle_id ?? null,
    workItemId: response.work_item_id ?? null,
    agentId: response.agent_id ?? null,
    projectId: response.project_id ?? null,
    orgId: response.org_id ?? null,
    state,
    phase: response.phase ?? null,
    startedAt: response.started_at ?? null,
    completedAt: response.completed_at ?? null,
    progressPct: response.progress_pct ?? null,
    currentStep: response.current_step ?? null,
    totalTokens: response.total_tokens ?? null,
    totalCostUsd: response.total_cost_usd ?? null,
    toolCount: response.tool_count ?? null,
    stepCount: response.step_count ?? null,
    error: response.error ?? null,
    lastError: response.last_error ?? null,
    modelId: response.model_id ?? null,
    surface: response.surface ?? null,
    sourceType: response.source_type ?? null,
    conversationId: response.conversation_id ?? null,
    messageId: response.message_id ?? null,
    requestId: response.request_id ?? null,
    executionMode: response.execution_mode ?? null,
    queueJobId: response.queue_job_id ?? null,
    queueMetadata: response.queue_metadata ?? null,
    phaseTimings: response.phase_timings ?? null,
    traceSummary: response.trace_summary ?? null,
    pendingClarifications: response.pending_clarifications ?? null,
  };
}

function mapExecutionList(response: ExecutionListApiResponse): ExecutionListResponse {
  return {
    executions: response.executions.map((item): ExecutionListItem => ({
      runId: item.run_id,
      workItemId: item.work_item_id,
      workItemTitle: item.work_item_title ?? null,
      agentId: item.agent_id,
      state: item.state,
      phase: item.phase ?? null,
      startedAt: item.started_at,
      completedAt: item.completed_at ?? null,
      progressPct: item.progress_pct,
      projectId: item.project_id ?? null,
      orgId: item.org_id ?? null,
      modelId: item.model_id ?? null,
      surface: item.surface ?? null,
      sourceType: item.source_type ?? null,
      conversationId: item.conversation_id ?? null,
      messageId: item.message_id ?? null,
      requestId: item.request_id ?? null,
      executionMode: item.execution_mode ?? null,
      queueJobId: item.queue_job_id ?? null,
      queueMetadata: item.queue_metadata ?? null,
      phaseTimings: item.phase_timings ?? null,
      traceSummary: item.trace_summary ?? null,
      totalTokens: item.total_tokens ?? null,
      totalCostUsd: item.total_cost_usd ?? null,
      toolCount: item.tool_count ?? null,
      stepCount: item.step_count ?? null,
      lastError: item.last_error ?? null,
    })),
    total: response.total,
    offset: response.offset,
    limit: response.limit,
  };
}

/** Single-item execution GET — shared by React Query and mutation cache patches (guideai-1156). */
async function fetchExecutionStatusSnapshot(
  itemId: string,
  orgId: string | null,
  projectId: string
): Promise<ExecutionStatus | null> {
  const capabilities = await getApiCapabilities();
  if (!capabilities.routes.executions) {
    return null;
  }
  const params = new URLSearchParams({
    project_id: projectId,
  });
  if (orgId) {
    params.set('org_id', orgId);
  }
  const response = await apiClient.get<ExecutionStatusResponse>(
    `/v1/work-items/${encodeURIComponent(itemId)}/execution?${params.toString()}`
  );
  return mapExecutionStatus(response);
}

function executionStatusToListItem(st: ExecutionStatus): ExecutionListItem | null {
  const runId = st.runId;
  const workItemId = st.workItemId;
  if (!runId || !workItemId) {
    return null;
  }
  return {
    runId,
    workItemId,
    workItemTitle: null,
    agentId: st.agentId ?? 'unknown',
    state: st.state ?? 'unknown',
    phase: st.phase ?? null,
    startedAt: st.startedAt ?? new Date().toISOString(),
    completedAt: st.completedAt ?? null,
    progressPct: st.progressPct ?? 0,
    projectId: st.projectId ?? null,
    orgId: st.orgId ?? null,
    modelId: st.modelId ?? null,
    surface: st.surface ?? null,
    sourceType: st.sourceType ?? null,
    conversationId: st.conversationId ?? null,
    messageId: st.messageId ?? null,
    requestId: st.requestId ?? null,
    executionMode: st.executionMode ?? null,
    queueJobId: st.queueJobId ?? null,
    queueMetadata: st.queueMetadata ?? null,
    phaseTimings: st.phaseTimings ?? null,
    traceSummary: st.traceSummary ?? null,
    totalTokens: st.totalTokens ?? null,
    totalCostUsd: st.totalCostUsd ?? null,
    toolCount: st.toolCount ?? null,
    stepCount: st.stepCount ?? null,
    lastError: st.lastError ?? st.error ?? null,
  };
}

function listEntryMatchesStatusFilter(listStatusFilter: string | undefined, executionState: string): boolean {
  const s = executionState.toLowerCase();
  if (!listStatusFilter || listStatusFilter === 'all') {
    return true;
  }
  if (listStatusFilter === 'running') {
    return s === 'running' || s === 'pending' || s === 'paused';
  }
  return s === listStatusFilter.toLowerCase();
}

/** Patch execution list caches from one status payload — avoids invalidate(executionKeys.all) full list refetch. */
function applyExecutionStatusToProjectListCaches(
  queryClient: QueryClient,
  orgId: string | null,
  projectId: string,
  workItemId: string,
  st: ExecutionStatus | null
) {
  const listQueries = queryClient.getQueryCache().findAll({
    predicate: (q) => {
      const key = q.queryKey;
      return (
        Array.isArray(key) &&
        key[0] === executionKeys.all[0] &&
        key[1] === 'list' &&
        key[3] === projectId &&
        (key[2] ?? null) === (orgId ?? null)
      );
    },
  });

  for (const query of listQueries) {
    const queryKey = query.queryKey;
    const listStatusFilter = queryKey[4] as string | undefined;
    queryClient.setQueryData<ExecutionListResponse | null>(queryKey, (prev) => {
      if (!prev) return prev;

      if (!st?.hasExecution) {
        const next = prev.executions.filter((e) => e.workItemId !== workItemId);
        if (next.length === prev.executions.length) return prev;
        return { ...prev, executions: next, total: Math.max(0, prev.total - 1) };
      }

      const listItem = executionStatusToListItem(st);
      if (!listItem) return prev;

      const stateStr = String(listItem.state).toLowerCase();
      if (!listEntryMatchesStatusFilter(listStatusFilter, stateStr)) {
        const next = prev.executions.filter(
          (e) => e.runId !== listItem.runId && e.workItemId !== workItemId
        );
        if (next.length === prev.executions.length) return prev;
        return { ...prev, executions: next, total: Math.max(0, prev.total - 1) };
      }

      const idx = prev.executions.findIndex(
        (e) => e.runId === listItem.runId || e.workItemId === workItemId
      );
      if (idx >= 0) {
        const next = [...prev.executions];
        next[idx] = { ...next[idx], ...listItem };
        return { ...prev, executions: next };
      }

      const nextExecutions = [listItem, ...prev.executions];
      return {
        ...prev,
        executions: nextExecutions.slice(0, prev.limit),
        total: Math.max(prev.total + 1, nextExecutions.length),
      };
    });
  }
}

function mapExecutionSteps(response: ExecutionStepsApiResponse): ExecutionStepsResponse {
  return {
    steps: response.steps.map((step): ExecutionStep => ({
      stepId: step.step_id,
      phase: step.phase,
      stepType: step.step_type,
      startedAt: step.started_at,
      completedAt: step.completed_at ?? null,
      name: step.name ?? null,
      status: step.status ?? null,
      progressPct: step.progress_pct ?? null,
      durationMs: step.duration_ms ?? null,
      inputTokens: step.input_tokens,
      outputTokens: step.output_tokens,
      costUsd: step.cost_usd ?? null,
      toolCalls: step.tool_calls,
      contentPreview: step.content_preview ?? null,
      contentFull: step.content_full ?? null,
      toolNames: step.tool_names ?? null,
      modelId: step.model_id ?? null,
      error: step.error ?? null,
      metadata: step.metadata ?? null,
    })),
    total: response.total,
  };
}

type ExecutionStatusPayload = ExecutionStatusEventPayload | ExecutionStatusSnapshotPayload;

function normalizeExecutionState(state?: string | null): ExecutionStatus['state'] {
  if (!state) return null;
  return state.toLowerCase() as ExecutionStatus['state'];
}

function mergeExecutionStatus(
  previous: ExecutionStatus | null | undefined,
  payload: ExecutionStatusPayload
): ExecutionStatus {
  const taskCycleId = ('task_cycle_id' in payload ? payload.task_cycle_id : undefined)
    ?? ('cycle_id' in payload ? payload.cycle_id : undefined)
    ?? previous?.taskCycleId
    ?? null;

  return {
    hasExecution: previous?.hasExecution ?? Boolean(payload.run_id),
    runId: payload.run_id ?? previous?.runId ?? null,
    taskCycleId,
    workItemId: payload.work_item_id ?? previous?.workItemId ?? null,
    agentId: payload.agent_id ?? previous?.agentId ?? null,
    projectId: payload.project_id ?? previous?.projectId ?? null,
    orgId: payload.org_id ?? previous?.orgId ?? null,
    state: normalizeExecutionState(payload.status ?? null) ?? previous?.state ?? null,
    phase: payload.phase ?? previous?.phase ?? null,
    startedAt: payload.started_at ?? previous?.startedAt ?? null,
    completedAt: payload.completed_at ?? previous?.completedAt ?? null,
    progressPct: payload.progress_pct ?? previous?.progressPct ?? null,
    currentStep: payload.current_step ?? previous?.currentStep ?? null,
    totalTokens: previous?.totalTokens ?? null,
    totalCostUsd: previous?.totalCostUsd ?? null,
    toolCount: previous?.toolCount ?? null,
    stepCount: payload.step_count ?? previous?.stepCount ?? null,
    error: payload.error ?? previous?.error ?? null,
    lastError: payload.error ?? previous?.lastError ?? null,
    modelId: payload.model_id ?? previous?.modelId ?? null,
    surface: payload.surface ?? previous?.surface ?? null,
    sourceType: payload.source_type ?? previous?.sourceType ?? null,
    conversationId: payload.conversation_id ?? previous?.conversationId ?? null,
    messageId: payload.message_id ?? previous?.messageId ?? null,
    requestId: payload.request_id ?? previous?.requestId ?? null,
    executionMode: payload.execution_mode ?? previous?.executionMode ?? null,
    queueJobId: payload.queue_job_id ?? previous?.queueJobId ?? null,
    queueMetadata: payload.queue_metadata ?? previous?.queueMetadata ?? null,
    phaseTimings: payload.phase_timings ?? previous?.phaseTimings ?? null,
    traceSummary: payload.trace_summary ?? previous?.traceSummary ?? null,
    pendingClarifications: previous?.pendingClarifications ?? null,
  };
}

function mapStepFromEvent(
  payload: ExecutionStepEventPayload,
  existing?: ExecutionStep | null
): ExecutionStep {
  const metadata = (payload.step.metadata ?? {}) as Record<string, unknown>;
  const stepType = String((metadata.step_type as string | undefined) ?? payload.step.name ?? 'step');
  const phase = String((metadata.phase as string | undefined) ?? existing?.phase ?? 'unknown');
  const inputTokens = Number(metadata.input_tokens ?? existing?.inputTokens ?? 0);
  const outputTokens = Number(metadata.output_tokens ?? existing?.outputTokens ?? 0);
  const toolCallsValue = metadata.tool_calls;
  const toolCalls = Array.isArray(toolCallsValue)
    ? toolCallsValue.length
    : typeof toolCallsValue === 'number'
      ? toolCallsValue
      : existing?.toolCalls ?? 0;
  const contentPreview = (metadata.content_preview as string | undefined) ?? existing?.contentPreview ?? null;

  return {
    stepId: payload.step.step_id,
    name: payload.step.name,
    status: payload.step.status,
    phase,
    stepType,
    startedAt: payload.step.started_at ?? existing?.startedAt ?? new Date().toISOString(),
    completedAt: payload.step.completed_at ?? existing?.completedAt ?? null,
    progressPct: payload.step.progress_pct ?? existing?.progressPct ?? null,
    durationMs: (metadata.duration_ms as number | undefined) ?? existing?.durationMs ?? null,
    inputTokens,
    outputTokens,
    costUsd: (metadata.cost_usd as number | undefined) ?? existing?.costUsd ?? null,
    toolCalls,
    contentPreview,
    contentFull: (metadata.content_full as string | undefined) ?? existing?.contentFull ?? null,
    toolNames: Array.isArray(metadata.tool_names) ? (metadata.tool_names as string[]) : existing?.toolNames ?? null,
    modelId: (metadata.model_id as string | undefined) ?? existing?.modelId ?? null,
    error: (metadata.error as string | undefined) ?? existing?.error ?? null,
    metadata,
  };
}

function mapStepFromSnapshot(step: ExecutionStepEventPayload['step'] | ExecutionStepSnapshotPayload): ExecutionStep {
  if ('step_type' in step || 'phase' in step || 'input_tokens' in step) {
    return {
      stepId: step.step_id,
      phase: step.phase ?? 'unknown',
      stepType: step.step_type ?? step.name ?? 'step',
      startedAt: step.started_at ?? new Date().toISOString(),
      completedAt: step.completed_at ?? null,
      name: step.name ?? null,
      status: step.status ?? null,
      progressPct: step.progress_pct ?? null,
      inputTokens: step.input_tokens ?? 0,
      outputTokens: step.output_tokens ?? 0,
      toolCalls: step.tool_calls ?? 0,
      contentPreview: step.content_preview ?? null,
      metadata: step.metadata ?? null,
    };
  }

  // Convert to event payload with required name field
  const payload: ExecutionStepEventPayload = {
    run_id: '',
    step: {
      step_id: step.step_id,
      name: step.name ?? 'step',
      status: step.status ?? 'unknown',
      started_at: step.started_at ?? undefined,
      completed_at: step.completed_at ?? undefined,
      progress_pct: step.progress_pct ?? undefined,
      metadata: step.metadata ?? undefined,
    },
  };
  return mapStepFromEvent(payload);
}

export function useExecutionStream(params: {
  runId?: string | null;
  orgId?: string | null;
  projectId?: string | null;
  enabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const clientRef = useRef<ExecutionStreamClient | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.Disconnected);

  const target = useMemo(() => {
    if (params.runId) {
      return { runId: params.runId };
    }
    if (params.orgId && params.projectId) {
      return { orgId: params.orgId, projectId: params.projectId };
    }
    return null;
  }, [params.orgId, params.projectId, params.runId]);

  useEffect(() => {
    const enabled = params.enabled ?? true;
    const client = clientRef.current;

    if (!enabled || !target) {
      if (client) {
        client.disconnect('stream_disabled');
      }
      queueMicrotask(() => setConnectionState(ConnectionState.Disconnected));
      return;
    }
    let isDisposed = false;
    let cleanup: (() => void) | undefined;

    const handleStatus = (payload: ExecutionStatusEventPayload) => {
      const orgId = payload.org_id ?? target.orgId ?? params.orgId ?? null;
      const projectId = payload.project_id ?? target.projectId ?? params.projectId ?? null;
      const workItemId = payload.work_item_id ?? null;

      if (workItemId && orgId && projectId) {
        queryClient.setQueryData<ExecutionStatus | null>(
          executionKeys.status(workItemId, orgId, projectId),
          (prev) => mergeExecutionStatus(prev ?? null, payload)
        );
      }

      queryClient.setQueriesData<ExecutionListResponse | null>(
        {
          predicate: (query) =>
            Array.isArray(query.queryKey) &&
            query.queryKey[0] === executionKeys.all[0] &&
            query.queryKey[1] === 'list',
        },
        (prev) => {
          if (!prev) return prev;
          const existingIndex = prev.executions.findIndex((execution) => execution.runId === payload.run_id);
          if (existingIndex >= 0) {
            const nextExecutions = prev.executions.map((execution) => {
              if (execution.runId !== payload.run_id) return execution;
              return {
                ...execution,
                state: normalizeExecutionState(payload.status) ?? execution.state,
                phase: payload.phase ?? execution.phase ?? null,
                startedAt: payload.started_at ?? execution.startedAt,
                completedAt: payload.completed_at ?? execution.completedAt ?? null,
                progressPct: payload.progress_pct ?? execution.progressPct,
                agentId: payload.agent_id ?? execution.agentId,
                projectId: payload.project_id ?? execution.projectId ?? null,
                orgId: payload.org_id ?? execution.orgId ?? null,
                modelId: payload.model_id ?? execution.modelId ?? null,
                surface: payload.surface ?? execution.surface ?? null,
                sourceType: payload.source_type ?? execution.sourceType ?? null,
                conversationId: payload.conversation_id ?? execution.conversationId ?? null,
                messageId: payload.message_id ?? execution.messageId ?? null,
                requestId: payload.request_id ?? execution.requestId ?? null,
                executionMode: payload.execution_mode ?? execution.executionMode ?? null,
                queueJobId: payload.queue_job_id ?? execution.queueJobId ?? null,
                queueMetadata: payload.queue_metadata ?? execution.queueMetadata ?? null,
                phaseTimings: payload.phase_timings ?? execution.phaseTimings ?? null,
                traceSummary: payload.trace_summary ?? execution.traceSummary ?? null,
                stepCount: payload.step_count ?? execution.stepCount ?? null,
                lastError: payload.error ?? execution.lastError ?? null,
              };
            });
            return { ...prev, executions: nextExecutions };
          }

          if (!payload.work_item_id || !payload.agent_id || !payload.started_at) {
            return prev;
          }

          const nextItem: ExecutionListItem = {
            runId: payload.run_id,
            workItemId: payload.work_item_id,
            workItemTitle: null,
            agentId: payload.agent_id,
            state: normalizeExecutionState(payload.status) ?? payload.status,
            phase: payload.phase ?? null,
            startedAt: payload.started_at,
            completedAt: payload.completed_at ?? null,
            progressPct: payload.progress_pct ?? 0,
            projectId: payload.project_id ?? null,
            orgId: payload.org_id ?? null,
            modelId: payload.model_id ?? null,
            surface: payload.surface ?? null,
            sourceType: payload.source_type ?? null,
            conversationId: payload.conversation_id ?? null,
            messageId: payload.message_id ?? null,
            requestId: payload.request_id ?? null,
            executionMode: payload.execution_mode ?? null,
            queueJobId: payload.queue_job_id ?? null,
            queueMetadata: payload.queue_metadata ?? null,
            phaseTimings: payload.phase_timings ?? null,
            traceSummary: payload.trace_summary ?? null,
            totalTokens: null,
            totalCostUsd: null,
            toolCount: null,
            stepCount: payload.step_count ?? null,
            lastError: payload.error ?? null,
          };

          const nextExecutions = [nextItem, ...prev.executions];
          return {
            ...prev,
            executions: nextExecutions.slice(0, prev.limit),
            total: Math.max(prev.total + 1, nextExecutions.length),
          };
        }
      );
    };

    const handleStep = (payload: ExecutionStepEventPayload) => {
      const runId = payload.run_id ?? target.runId ?? null;
      if (!runId) return;

      queryClient.setQueryData<ExecutionStepsResponse | null>(
        executionKeys.steps(runId),
        (prev) => {
          const existingSteps = prev?.steps ? [...prev.steps] : [];
          const index = existingSteps.findIndex((step) => step.stepId === payload.step.step_id);
          const mapped = mapStepFromEvent(payload, index >= 0 ? existingSteps[index] : null);
          if (index >= 0) {
            existingSteps[index] = mapped;
          } else {
            existingSteps.push(mapped);
          }
          existingSteps.sort((a, b) => a.startedAt.localeCompare(b.startedAt));
          return { steps: existingSteps, total: existingSteps.length };
        }
      );
    };

    const handleSnapshot = (payload: ExecutionSnapshotEventPayload) => {
      const statusPayload = payload.status ?? null;
      const runId = payload.run_id ?? statusPayload?.run_id ?? target.runId ?? null;

      if (statusPayload) {
        const orgId: string | null = ('org_id' in statusPayload ? statusPayload.org_id as string | undefined : undefined) ?? target.orgId ?? params.orgId ?? null;
        const projectId: string | null =
          ('project_id' in statusPayload ? statusPayload.project_id as string | undefined : undefined) ?? target.projectId ?? params.projectId ?? null;
        const workItemId: string | null =
          ('work_item_id' in statusPayload ? statusPayload.work_item_id as string | undefined : undefined) ?? null;

        if (workItemId && orgId && projectId) {
          queryClient.setQueryData<ExecutionStatus | null>(
            executionKeys.status(workItemId, orgId, projectId),
            (prev) => mergeExecutionStatus(prev ?? null, statusPayload as ExecutionStatusPayload)
          );
        }
      }

      if (runId && payload.steps) {
        const steps = payload.steps.map((step) => mapStepFromSnapshot(step));
        steps.sort((a, b) => a.startedAt.localeCompare(b.startedAt));
        queryClient.setQueryData<ExecutionStepsResponse | null>(executionKeys.steps(runId), {
          steps,
          total: steps.length,
        });
      }
    };

    void getApiCapabilities().then((capabilities) => {
      if (isDisposed || !capabilities.routes.executions) {
        client?.disconnect('stream_disabled');
        setConnectionState(ConnectionState.Disconnected);
        return;
      }

      const nextClient =
        client ??
        new ExecutionStreamClient({
          baseUrl: API_ORIGIN,
          authToken: apiClient.getToken() ?? undefined,
          getAuthToken: async () => apiClient.getToken(),
        });

      clientRef.current = nextClient;
      nextClient.setAuthToken(apiClient.getToken());

      const unsubscribeConnected = nextClient.on('connected', () => {
        setConnectionState(ConnectionState.Connected);
      });
      const unsubscribeDisconnected = nextClient.on('disconnected', () => {
        setConnectionState(ConnectionState.Disconnected);
      });
      const unsubscribeStatus = nextClient.on('status', handleStatus);
      const unsubscribeStep = nextClient.on('step', handleStep);
      const unsubscribeSnapshot = nextClient.on('snapshot', handleSnapshot);
      const unsubscribeReady = nextClient.on('ready', () => {
        setConnectionState(ConnectionState.Connected);
      });
      const unsubscribeError = nextClient.on('error', () => {
        setConnectionState(ConnectionState.Disconnected);
      });

      nextClient.connect(target);

      cleanup = () => {
        unsubscribeConnected();
        unsubscribeDisconnected();
        unsubscribeStatus();
        unsubscribeStep();
        unsubscribeSnapshot();
        unsubscribeReady();
        unsubscribeError();
        nextClient.disconnect('stream_cleanup');
      };
    });

    return () => {
      isDisposed = true;
      cleanup?.();
    };
  }, [params.enabled, params.orgId, params.projectId, queryClient, target]);

  return {
    connectionState,
    isConnected: connectionState === ConnectionState.Connected,
  };
}

export function useWorkItemExecutionStatus(
  itemId?: string,
  orgId?: string | null,
  projectId?: string | null,
  options?: { enabled?: boolean; refetchInterval?: number | false }
) {
  return useQuery({
    queryKey: executionKeys.status(itemId, orgId, projectId),
    queryFn: async () => {
      if (!itemId || !projectId) {
        return null;
      }
      return fetchExecutionStatusSnapshot(itemId, orgId ?? null, projectId);
    },
    enabled: Boolean(itemId && projectId) && (options?.enabled ?? true),
    refetchInterval:
      options?.refetchInterval ??
      ((data) => {
        if (!data?.state) return false;
        const state = String(data.state).toLowerCase();
        if (state === 'running' || state === 'paused' || state === 'pending') return 2000;
        return false;
      }),
    staleTime: 1_500,
  });
}

export function useExecutionList(
  orgId?: string | null,
  projectId?: string | null,
  options?: { status?: string; limit?: number; offset?: number; enabled?: boolean; refetchInterval?: number | false }
) {
  return useQuery({
    queryKey: executionKeys.list(orgId, projectId, options?.status ?? null, options?.limit, options?.offset),
    queryFn: async () => {
      if (!projectId) return null;
      const capabilities = await getApiCapabilities();
      if (!capabilities.routes.executions) {
        return { executions: [], total: 0, offset: 0, limit: options?.limit ?? 50 };
      }
      const params = new URLSearchParams({
        project_id: projectId,
        limit: String(options?.limit ?? 50),
        offset: String(options?.offset ?? 0),
      });
      if (orgId) {
        params.set('org_id', orgId);
      }
      if (options?.status) params.set('status', options.status);
      try {
        const response = await apiClient.get<ExecutionListApiResponse>(`/v1/executions?${params.toString()}`);
        return mapExecutionList(response);
      } catch (error) {
        // Treat 404 as "no executions" — endpoint may not be deployed in this environment.
        if (error instanceof ApiError && error.status === 404) {
          return { executions: [], total: 0, offset: 0, limit: options?.limit ?? 50 };
        }
        throw error;
      }
    },
    enabled: Boolean(projectId) && (options?.enabled ?? true),
    refetchInterval: options?.refetchInterval,
    staleTime: 3_000,
    retry: (failureCount, error) => {
      // Don't retry 404s — endpoint is simply unavailable
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 3;
    },
  });
}

export function useExecutionSteps(
  runId?: string | null,
  orgId?: string | null,
  projectId?: string | null,
  options?: { enabled?: boolean; refetchInterval?: number | false }
) {
  return useQuery({
    queryKey: executionKeys.steps(runId),
    queryFn: async () => {
      if (!runId || !projectId) return null;
      const capabilities = await getApiCapabilities();
      if (!capabilities.routes.executions) {
        return null;
      }
      const params = new URLSearchParams();
      if (orgId) params.set('org_id', orgId);
      params.set('project_id', projectId);
      const response = await apiClient.get<ExecutionStepsApiResponse>(
        `/v1/executions/${encodeURIComponent(runId)}/steps?${params.toString()}`
      );
      return mapExecutionSteps(response);
    },
    enabled: Boolean(runId && projectId) && (options?.enabled ?? true),
    refetchInterval: options?.refetchInterval,
    staleTime: 2_000,
  });
}

export function useExecuteWorkItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: {
      itemId: string;
      orgId?: string | null;
      projectId: string;
      modelOverride?: string;
      idempotencyKey?: string;
    }) => {
      await razeLog('INFO', 'Work item execution requested', {
        work_item_id: payload.itemId,
        org_id: payload.orgId ?? null,
        project_id: payload.projectId,
      });

      const params = new URLSearchParams({
        project_id: payload.projectId,
      });
      if (payload.orgId) {
        params.set('org_id', payload.orgId);
      }
      const body: Record<string, unknown> = {
        model_override: payload.modelOverride ?? null,
        idempotency_key: payload.idempotencyKey ?? null,
      };
      if (getPreferredExecutionWorkspaceKind() === 'local_connector') {
        body.execution_workspace_kind = 'local_connector';
      }
      const response = await apiClient.post<ExecuteResponse>(
        `/v1/work-items/${encodeURIComponent(payload.itemId)}:execute?${params.toString()}`,
        body
      );
      return response;
    },
    onSuccess: async (_response, payload) => {
      const itemId = payload.itemId;
      const orgId = payload.orgId ?? null;
      const projectId = payload.projectId;
      const statusKey = executionKeys.status(itemId, orgId, projectId);
      await queryClient.invalidateQueries({ queryKey: statusKey });
      const st = await queryClient.fetchQuery({
        queryKey: statusKey,
        queryFn: () => fetchExecutionStatusSnapshot(itemId, orgId, projectId),
      });
      applyExecutionStatusToProjectListCaches(queryClient, orgId, projectId, itemId, st);
    },
  });
}

export function useCancelWorkItemExecution() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: { itemId: string; orgId?: string | null; projectId: string; reason?: string }) => {
      await razeLog('INFO', 'Work item execution cancellation requested', {
        work_item_id: payload.itemId,
        org_id: payload.orgId ?? null,
        project_id: payload.projectId,
        reason: payload.reason ?? 'User requested cancellation',
      });

      const params = new URLSearchParams({
        project_id: payload.projectId,
      });
      if (payload.orgId) {
        params.set('org_id', payload.orgId);
      }
      const response = await apiClient.post<CancelResponse>(
        `/v1/work-items/${encodeURIComponent(payload.itemId)}:cancel?${params.toString()}`,
        {
          reason: payload.reason ?? 'User requested cancellation',
        }
      );
      return response;
    },
    onSuccess: async (_response, payload) => {
      const itemId = payload.itemId;
      const orgId = payload.orgId ?? null;
      const projectId = payload.projectId;
      const statusKey = executionKeys.status(itemId, orgId, projectId);
      await queryClient.invalidateQueries({ queryKey: statusKey });
      const st = await queryClient.fetchQuery({
        queryKey: statusKey,
        queryFn: () => fetchExecutionStatusSnapshot(itemId, orgId, projectId),
      });
      applyExecutionStatusToProjectListCaches(queryClient, orgId, projectId, itemId, st);
    },
  });
}

interface ApproveGateResponse {
  success: boolean;
  message: string;
  run_id?: string | null;
  resumed?: boolean;
}

export function useApproveGate() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: {
      itemId: string;
      orgId?: string | null;
      projectId: string;
      phase?: string | null;
      notes?: string | null;
    }) => {
      await razeLog('INFO', 'Strict gate approved', {
        work_item_id: payload.itemId,
        org_id: payload.orgId ?? null,
        project_id: payload.projectId,
        phase: payload.phase ?? null,
      });

      const params = new URLSearchParams({
        project_id: payload.projectId,
      });
      if (payload.orgId) {
        params.set('org_id', payload.orgId);
      }
      const body: { phase?: string; notes?: string } = {};
      if (payload.phase) body.phase = payload.phase;
      if (payload.notes) body.notes = payload.notes;
      const response = await apiClient.post<ApproveGateResponse>(
        `/v1/work-items/${encodeURIComponent(payload.itemId)}:approve-gate?${params.toString()}`,
        Object.keys(body).length ? body : {}
      );
      return response;
    },
    onSuccess: async (_response, payload) => {
      await queryClient.invalidateQueries({
        queryKey: executionKeys.status(payload.itemId, payload.orgId ?? null, payload.projectId),
      });
    },
  });
}

export function useProvideClarification() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: {
      itemId: string;
      orgId?: string | null;
      projectId: string;
      clarificationId: string;
      response: string;
    }) => {
      await razeLog('INFO', 'Clarification response submitted', {
        work_item_id: payload.itemId,
        org_id: payload.orgId ?? null,
        project_id: payload.projectId,
        clarification_id: payload.clarificationId,
      });

      const params = new URLSearchParams({
        project_id: payload.projectId,
      });
      if (payload.orgId) {
        params.set('org_id', payload.orgId);
      }
      const response = await apiClient.post<ClarifyResponse>(
        `/v1/work-items/${encodeURIComponent(payload.itemId)}:clarify?${params.toString()}`,
        {
          clarification_id: payload.clarificationId,
          response: payload.response,
        }
      );
      return response;
    },
    onSuccess: async (_response, payload) => {
      await queryClient.invalidateQueries({
        queryKey: executionKeys.status(payload.itemId, payload.orgId ?? null, payload.projectId),
      });
    },
  });
}
