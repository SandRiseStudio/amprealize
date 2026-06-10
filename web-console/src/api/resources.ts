import { apiClient } from './client';

export interface ResourceAnalyzeRequest {
  query: string;
  project_id?: string | null;
  org_id?: string | null;
  conversation_scope?: string | null;
}

export interface ResourceAnalyzeResponse {
  success: boolean;
  content: string;
  answer_type: string;
  query_plan: Record<string, unknown>;
  structured_payload: Record<string, unknown>;
  rows: Array<Record<string, unknown>>;
  trace_steps: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
}

export function analyzeResources(payload: ResourceAnalyzeRequest): Promise<ResourceAnalyzeResponse> {
  return apiClient.post<ResourceAnalyzeResponse>('/v1/resources:analyze', payload);
}
