/**
 * Work Item Execution API (web console)
 *
 * Following:
 * - COLLAB_SAAS_REQUIREMENTS.md: optimistic updates, fast UI
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  state?: string | null;
  phase?: string | null;
  started_at?: string | null;
  progress_pct?: number | null;
  current_step?: string | null;
  total_tokens?: number | null;
  total_cost_usd?: number | null;
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
    input_tokens: number;
    output_tokens: number;
    tool_calls: number;
    content_preview?: string | null;
    content_full?: string | null;
    tool_names?: string[] | null;
    model_id?: string | null;
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
  const validStates = ['pending', 'running', 'completed', 'failed', 'cancelled'];
  const state = response.state && validStates.includes(response.state) ? response.state as ExecutionState : null;

  return {
    hasExecution: response.has_execution,
    runId: response.run_id ?? null,
    taskCycleId: response.task_cycle_id ?? null,
    state,
    phase: response.phase ?? null,
    startedAt: response.started_at ?? null,
    progressPct: response.progress_pct ?? null,
    currentStep: response.current_step ?? null,
    totalTokens: response.total_tokens ?? null,
    totalCostUsd: response.total_cost_usd ?? null,
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
    })),
    total: response.total,
    offset: response.offset,
    limit: response.limit,
  };
}

function mapExecutionSteps(response: ExecutionStepsApiResponse): ExecutionStepsResponse {
  return {
    steps: response.steps.map((step): ExecutionStep => ({
      stepId: step.step_id,
      phase: step.phase,
      stepType: step.step_type,
      startedAt: step.started_at,
      completedAt: step.completed_at ?? null,
      inputTokens: step.input_tokens,
      outputTokens: step.output_tokens,
      toolCalls: step.tool_calls,
      contentPreview: step.content_preview ?? null,
      contentFull: step.content_full ?? null,
      toolNames: step.tool_names ?? null,
      modelId: step.model_id ?? null,
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
    state: normalizeExecutionState(payload.status ?? null) ?? previous?.state ?? null,
    phase: payload.phase ?? previous?.phase ?? null,
    startedAt: payload.started_at ?? previous?.startedAt ?? null,
    progressPct: payload.progress_pct ?? previous?.progressPct ?? null,
    currentStep: payload.current_step ?? previous?.currentStep ?? null,
    totalTokens: previous?.totalTokens ?? null,
    totalCostUsd: previous?.totalCostUsd ?? null,
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
    phase,
    stepType,
    startedAt: payload.step.started_at ?? existing?.startedAt ?? new Date().toISOString(),
    completedAt: payload.step.completed_at ?? existing?.completedAt ?? null,
    inputTokens,
    outputTokens,
    toolCalls,
    contentPreview,
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
      inputTokens: step.input_tokens ?? 0,
      outputTokens: step.output_tokens ?? 0,
      toolCalls: step.tool_calls ?? 0,
      contentPreview: step.content_preview ?? null,
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
      setConnectionState(ConnectionState.Disconnected);
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
      const response = await apiClient.post<ExecuteResponse>(
        `/v1/work-items/${encodeURIComponent(payload.itemId)}:execute?${params.toString()}`,
        {
          model_override: payload.modelOverride ?? null,
          idempotency_key: payload.idempotencyKey ?? null,
        }
      );
      return response;
    },
    onSuccess: async (_response, payload) => {
      await queryClient.invalidateQueries({
        queryKey: executionKeys.status(payload.itemId, payload.orgId ?? null, payload.projectId),
      });
      await queryClient.invalidateQueries({ queryKey: executionKeys.all });
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
      await queryClient.invalidateQueries({
        queryKey: executionKeys.status(payload.itemId, payload.orgId ?? null, payload.projectId),
      });
      await queryClient.invalidateQueries({ queryKey: executionKeys.all });
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
