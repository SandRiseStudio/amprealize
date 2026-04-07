/**
 * Agent Registry API
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { apiClient as clientInstance } from './client';
import { razeLog } from '../telemetry/raze';
import { dashboardKeys, type Agent, type AgentStatus as DashboardAgentStatus } from './dashboard';

export type AgentVisibility = 'PRIVATE' | 'ORGANIZATION' | 'PUBLIC';
export type AgentStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
export type RoleAlignment = 'STRATEGIST' | 'TEACHER' | 'STUDENT' | 'MULTI_ROLE';

export interface AgentRegistryEntry {
  agent_id: string;
  name: string;
  slug: string;
  description: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  latest_version: string;
  status: AgentStatus;
  visibility: AgentVisibility;
  owner_id: string;
  org_id?: string | null;
  published_at?: string | null;
  is_builtin: boolean;
  service_principal_id?: string | null;
}

export interface AgentRegistryVersion {
  version_id?: string;
  agent_id: string;
  version: string;
  mission: string;
  role_alignment: RoleAlignment;
  capabilities: string[];
  default_behaviors: string[];
  playbook_content?: string;
  status: AgentStatus;
  created_at: string;
  created_by: string;
  effective_from: string;
  effective_to?: string | null;
  created_from?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentRegistryDetail {
  agent: AgentRegistryEntry;
  versions: AgentRegistryVersion[];
}

export interface AgentRegistrySearchResult {
  agent: AgentRegistryEntry;
  active_version?: AgentRegistryVersion | null;
  score: number;
}

export interface AgentRegistryListItem {
  agent: AgentRegistryEntry;
  active_version?: AgentRegistryVersion | null;
  score?: number;
}

type RawAgentListItem =
  | AgentRegistryEntry
  | {
      agent: AgentRegistryEntry;
      active_version?: AgentRegistryVersion | null;
      score?: number;
    };

export interface AgentRegistryQuery {
  query?: string;
  status?: AgentStatus;
  visibility?: AgentVisibility;
  roleAlignment?: RoleAlignment;
  includeBuiltin?: boolean;
  ownerId?: string;
  tags?: string[];
  limit?: number;
  offset?: number;
  orgId?: string;
}

export interface CreateAgentInput {
  name: string;
  slug?: string;
  description: string;
  mission: string;
  role_alignment: RoleAlignment;
  capabilities?: string[];
  default_behaviors?: string[];
  playbook_content?: string;
  tags?: string[];
  visibility?: AgentVisibility;
  request_api_credentials?: boolean;
  org_id?: string;
}

export interface CreateAgentResponse extends AgentRegistryEntry {
  credentials?: {
    client_id: string;
    client_secret: string;
  };
}

export interface UpdateAgentInput {
  name?: string;
  description?: string;
  tags?: string[];
  visibility?: AgentVisibility;
  latest_version?: string;
}

export interface CreateAgentVersionInput {
  base_version?: string;
  mission?: string;
  role_alignment?: RoleAlignment;
  capabilities?: string[];
  default_behaviors?: string[];
  playbook_content?: string;
  metadata?: Record<string, unknown>;
}

export interface PublishAgentInput {
  version?: string;
  visibility?: AgentVisibility;
  effective_from?: string;
}

export interface AgentAssignmentInput {
  agent: AgentRegistryEntry;
  projectId: string;
  roleAlignment?: RoleAlignment;
  capabilities?: string[];
}

export const agentRegistryKeys = {
  all: ['agentRegistry'] as const,
  list: (filters: AgentRegistryQuery) => [...agentRegistryKeys.all, 'list', filters] as const,
  detail: (agentId?: string | null) => [...agentRegistryKeys.all, 'detail', agentId] as const,
  projectAgents: () => [...agentRegistryKeys.all, 'projectAgents'] as const,
};

function normalizeApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

function normalizeListResponse(response: unknown): RawAgentListItem[] {
  if (!response) return [];
  if (Array.isArray(response)) return response as RawAgentListItem[];
  if (typeof response === 'object') {
    const payload = response as { agents?: RawAgentListItem[]; items?: RawAgentListItem[] };
    if (Array.isArray(payload.agents)) return payload.agents;
    if (Array.isArray(payload.items)) return payload.items;
  }
  return [];
}

function isProjectAgentAssignmentPayload(item: unknown): item is Record<string, unknown> {
  if (typeof item !== 'object' || item === null) return false;
  const o = item as Record<string, unknown>;
  return typeof o.agent_id === 'string' && typeof o.project_id === 'string' && !('agent_type' in o);
}

function mapProjectAgentAssignmentToAgent(o: Record<string, unknown>): Agent {
  const agentId = o.agent_id as string;
  const assignmentId = typeof o.id === 'string' ? o.id : `pa-${agentId}`;
  const name =
    (typeof o.name === 'string' && o.name)
      ? o.name
      : (typeof o.agent_name === 'string' && o.agent_name)
        ? o.agent_name
        : '';
  const role = typeof o.role === 'string' ? o.role : 'PRIMARY';
  const agentType = role.toLowerCase().replace(/_/g, ' ');
  const st = typeof o.status === 'string' ? o.status.toLowerCase() : 'active';
  let status: DashboardAgentStatus = 'active';
  if (st === 'inactive') status = 'idle';
  else if (st === 'removed') status = 'archived';
  else if (st === 'active') status = 'active';
  const baseConfig =
    typeof o.config === 'object' && o.config !== null && !Array.isArray(o.config)
      ? (o.config as Record<string, unknown>)
      : {};
  const config = { ...baseConfig, registry_agent_id: agentId };
  const assignedAt =
    typeof o.assigned_at === 'string' ? o.assigned_at : new Date().toISOString();
  const projectId = o.project_id as string;
  return {
    id: assignmentId,
    name: name || `Agent ${agentId.length > 8 ? agentId.slice(0, 8) : agentId}`,
    agent_type: agentType,
    status,
    config,
    project_id: projectId,
    created_at: assignedAt,
    updated_at: assignedAt,
  };
}

function mapAssignmentsToAgents(items: unknown[]): Agent[] {
  return items.map((item) => {
    if (isProjectAgentAssignmentPayload(item)) {
      return mapProjectAgentAssignmentToAgent(item);
    }
    return item as Agent;
  });
}

function normalizeAssignmentList(response: unknown): Agent[] {
  if (!response) return [];
  if (Array.isArray(response)) return mapAssignmentsToAgents(response);
  if (typeof response === 'object') {
    const payload = response as { agents?: unknown[]; items?: unknown[] };
    if (Array.isArray(payload.agents)) return mapAssignmentsToAgents(payload.agents);
    if (Array.isArray(payload.items)) return mapAssignmentsToAgents(payload.items);
  }
  return [];
}

async function listProjectAgents(): Promise<Agent[]> {
  try {
    const response = await apiClient.get<Agent[] | { agents?: Agent[]; items?: Agent[] }>(
      '/v1/projects/agents'
    );
    return normalizeAssignmentList(response);
  } catch (error) {
    if (error instanceof ApiError && error.status < 500) {
      return [];
    }
    throw error;
  }
}

async function listAgentRegistry(filters: AgentRegistryQuery): Promise<AgentRegistryListItem[]> {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.visibility) params.set('visibility', filters.visibility);
  if (filters.roleAlignment) params.set('role_alignment', filters.roleAlignment);
  if (filters.includeBuiltin !== undefined) params.set('builtin', String(filters.includeBuiltin));
  if (filters.ownerId) params.set('owner_id', filters.ownerId);
  if (filters.tags?.length) {
    filters.tags.forEach((tag) => params.append('tags', tag));
  }
  if (filters.limit) params.set('limit', String(filters.limit));
  if (filters.offset) params.set('offset', String(filters.offset));
  const query = params.toString();
  const path = query ? `/v1/agents?${query}` : '/v1/agents';
  const response = await apiClient.get<RawAgentListItem[] | { agents?: RawAgentListItem[] }>(path);
  const agents = normalizeListResponse(response);
  return agents.map((agent) => {
    if (typeof agent === 'object' && agent !== null && 'agent' in agent) {
      const payload = agent as { agent: AgentRegistryEntry; active_version?: AgentRegistryVersion | null };
      return { agent: payload.agent, active_version: payload.active_version ?? null };
    }
    return { agent: agent as AgentRegistryEntry };
  });
}

async function searchAgentRegistry(filters: AgentRegistryQuery): Promise<AgentRegistryListItem[]> {
  const response = await apiClient.post<{ results?: AgentRegistrySearchResult[] }>(
    '/v1/agents:search',
    {
      query: filters.query,
      tags: filters.tags,
      role_alignment: filters.roleAlignment,
      visibility: filters.visibility,
      status: filters.status,
      owner_id: filters.ownerId,
      include_builtin: filters.includeBuiltin ?? true,
      limit: filters.limit ?? 50,
      org_id: filters.orgId,
    }
  );
  const results = response?.results ?? [];
  return results.map((result) => ({
    agent: result.agent,
    active_version: result.active_version ?? null,
    score: result.score,
  }));
}

export function useAgentRegistry(filters: AgentRegistryQuery) {
  const shouldSearch = Boolean(filters.query && filters.query.trim().length > 0);
  return useQuery({
    queryKey: agentRegistryKeys.list(filters),
    queryFn: () => (shouldSearch ? searchAgentRegistry(filters) : listAgentRegistry(filters)),
    staleTime: 30_000,
  });
}

export function useAgentRegistryDetail(agentId?: string | null) {
  return useQuery({
    queryKey: agentRegistryKeys.detail(agentId),
    queryFn: async (): Promise<AgentRegistryDetail | null> => {
      if (!agentId) return null;
      return apiClient.get<AgentRegistryDetail>(`/v1/agents/${agentId}`);
    },
    enabled: Boolean(agentId),
    staleTime: 30_000,
  });
}

export function useProjectAgents(enabled = true) {
  const hasToken = clientInstance.hasToken();

  return useQuery({
    queryKey: agentRegistryKeys.projectAgents(),
    queryFn: listProjectAgents,
    staleTime: 30_000,
    enabled: enabled && hasToken,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status < 500) return false;
      return failureCount < 2;
    },
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  });
}

export async function createRegistryAgent(payload: CreateAgentInput): Promise<CreateAgentResponse> {
  await razeLog('INFO', 'Agent registry create requested', {
    name: payload.name,
    visibility: payload.visibility ?? 'PRIVATE',
  });
  try {
    const created = await apiClient.post<CreateAgentResponse>('/v1/agents', payload);
    await razeLog('INFO', 'Agent registry created', {
      agent_id: created.agent_id,
      visibility: created.visibility,
    });
    return created;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry create failed', {
      error: normalizeApiError(error, 'Failed to create agent'),
    });
    throw error;
  }
}

export async function updateRegistryAgent(agentId: string, payload: UpdateAgentInput): Promise<AgentRegistryEntry> {
  await razeLog('INFO', 'Agent registry update requested', {
    agent_id: agentId,
  });
  try {
    const updated = await apiClient.patch<AgentRegistryEntry>(`/v1/agents/${agentId}`, payload);
    await razeLog('INFO', 'Agent registry updated', {
      agent_id: agentId,
    });
    return updated;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry update failed', {
      agent_id: agentId,
      error: normalizeApiError(error, 'Failed to update agent'),
    });
    throw error;
  }
}

export async function createRegistryAgentVersion(
  agentId: string,
  payload: CreateAgentVersionInput
): Promise<AgentRegistryVersion> {
  await razeLog('INFO', 'Agent registry version create requested', {
    agent_id: agentId,
  });
  try {
    const created = await apiClient.post<AgentRegistryVersion>(`/v1/agents/${agentId}/versions`, payload);
    await razeLog('INFO', 'Agent registry version created', {
      agent_id: agentId,
      version: created.version,
    });
    return created;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry version create failed', {
      agent_id: agentId,
      error: normalizeApiError(error, 'Failed to create agent version'),
    });
    throw error;
  }
}

export async function publishRegistryAgent(agentId: string, payload: PublishAgentInput): Promise<AgentRegistryEntry> {
  await razeLog('INFO', 'Agent registry publish requested', {
    agent_id: agentId,
    version: payload.version ?? 'latest',
  });
  try {
    const updated = await apiClient.post<AgentRegistryEntry>(`/v1/agents/${agentId}:publish`, payload);
    await razeLog('INFO', 'Agent registry published', {
      agent_id: agentId,
      status: updated.status,
    });
    return updated;
  } catch (error) {
    await razeLog('ERROR', 'Agent registry publish failed', {
      agent_id: agentId,
      error: normalizeApiError(error, 'Failed to publish agent'),
    });
    throw error;
  }
}

export async function assignRegistryAgentToProject(
  payload: AgentAssignmentInput
): Promise<Agent> {
  await razeLog('INFO', 'Agent assignment requested', {
    agent_id: payload.agent.agent_id,
    org_id: null,
    project_id: payload.projectId,
  });
  const body = {
    name: payload.agent.name,
    project_id: payload.projectId,
    agent_type: 'custom',
    capabilities: payload.capabilities ?? payload.agent.tags ?? [],
    config: {
      registry_agent_id: payload.agent.agent_id,
      registry_agent_slug: payload.agent.slug,
      registry_agent_version: payload.agent.latest_version,
      registry_visibility: payload.agent.visibility,
      registry_role_alignment: payload.roleAlignment ?? null,
    },
  };
  try {
    const assigned = await apiClient.post<Agent>('/v1/projects/agents', body);
    await razeLog('INFO', 'Agent assigned to project', {
      agent_id: payload.agent.agent_id,
      assigned_id: assigned.id,
      project_id: payload.projectId,
    });
    return assigned;
  } catch (error) {
    await razeLog('ERROR', 'Agent assignment failed', {
      agent_id: payload.agent.agent_id,
      error: normalizeApiError(error, 'Failed to assign agent'),
    });
    throw error;
  }
}

export async function unassignAgentFromProject(assignmentId: string): Promise<void> {
  await razeLog('INFO', 'Agent unassign requested', {
    assignment_id: assignmentId,
  });
  try {
    await apiClient.delete<void>(`/v1/projects/agents/${assignmentId}`);
    await razeLog('INFO', 'Agent unassigned', {
      assignment_id: assignmentId,
    });
  } catch (error) {
    await razeLog('ERROR', 'Agent unassign failed', {
      assignment_id: assignmentId,
      error: normalizeApiError(error, 'Failed to unassign agent'),
    });
    throw error;
  }
}

export function useCreateRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createRegistryAgent,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

export function useUpdateRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: UpdateAgentInput }) =>
      updateRegistryAgent(agentId, payload),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.detail(variables.agentId) });
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
    },
  });
}

export function useCreateRegistryAgentVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: CreateAgentVersionInput }) =>
      createRegistryAgentVersion(agentId, payload),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.detail(variables.agentId) });
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
    },
  });
}

export function usePublishRegistryAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, payload }: { agentId: string; payload: PublishAgentInput }) =>
      publishRegistryAgent(agentId, payload),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.detail(variables.agentId) });
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.all });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

export function useAssignAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: assignRegistryAgentToProject,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.projectAgents() });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.agents() });
    },
  });
}

export function useUnassignAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ assignmentId }: { assignmentId: string }) =>
      unassignAgentFromProject(assignmentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: agentRegistryKeys.projectAgents() });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.agents() });
    },
  });
}
