/**
 * Governed trace warehouse reads (run / conversation summaries, span tree).
 *
 * Endpoints: POST /api/v1/observability/traces/*
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from './client';

export interface TraceSummaryRequest {
  project_id: string;
  run_id?: string;
  conversation_id?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export interface RunSummaryRow {
  run_id: string;
  started_at: string;
  last_event_at: string;
  record_count: number;
  failed_record_count: number;
  generation_count: number;
  tool_call_count: number;
  span_count: number;
  primary_trace_id: string | null;
  project_id: string | null;
  work_item_id: string | null;
  surface: string | null;
}

export interface ConversationSummaryRow {
  conversation_id: string;
  started_at: string;
  last_event_at: string;
  record_count: number;
  trace_count: number;
  generation_count: number;
  tool_call_count: number;
  project_id: string | null;
  surface: string | null;
}

export interface SpanTreeRow {
  record_id: string;
  record_timestamp: string;
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  status: string | null;
  kind: string;
  depth: number;
}

export interface TraceReadResponse<T> {
  access_tier: string;
  records: T[];
  count: number;
  truncated: boolean;
  query: Record<string, unknown>;
}

export async function fetchRunSummaries(
  body: TraceSummaryRequest
): Promise<TraceReadResponse<RunSummaryRow>> {
  return apiClient.post<TraceReadResponse<RunSummaryRow>>('/v1/observability/traces/runs', body);
}

export async function fetchConversationSummaries(
  body: TraceSummaryRequest
): Promise<TraceReadResponse<ConversationSummaryRow>> {
  return apiClient.post<TraceReadResponse<ConversationSummaryRow>>(
    '/v1/observability/traces/conversations',
    body
  );
}

export async function fetchSpanTree(project_id: string, trace_id: string, limit = 500) {
  return apiClient.post<{
    access_tier: string;
    trace_id: string;
    records: SpanTreeRow[];
    count: number;
    truncated: boolean;
    query: Record<string, unknown>;
  }>('/v1/observability/traces/spans', { project_id, trace_id, limit });
}

export function useRunTraceSummaries(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['observabilityTraces', 'runs', projectId],
    enabled: Boolean(projectId) && enabled,
    queryFn: () =>
      fetchRunSummaries({
        project_id: projectId as string,
        limit: 100,
        since: '30d',
      }),
  });
}

export function useConversationTraceSummaries(projectId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['observabilityTraces', 'conversations', projectId],
    enabled: Boolean(projectId) && enabled,
    queryFn: () =>
      fetchConversationSummaries({
        project_id: projectId as string,
        limit: 100,
        since: '30d',
      }),
  });
}

export function useSpanTree(projectId: string | undefined, traceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ['observabilityTraces', 'spans', projectId, traceId],
    enabled: Boolean(projectId && traceId) && enabled,
    queryFn: () => fetchSpanTree(projectId as string, traceId as string),
  });
}
