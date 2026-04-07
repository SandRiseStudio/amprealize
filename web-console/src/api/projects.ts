/**
 * Projects API
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { getApiCapabilities } from './capabilities';
import { dashboardKeys, type Project } from './dashboard';
import { razeLog } from '../telemetry/raze';

export interface CreateProjectRequest {
  name: string;
  description?: string;
  visibility: 'private' | 'internal' | 'public';
  slug?: string;
}

export type ProjectParticipantKind = 'human' | 'agent';
export type ProjectParticipantPresence =
  | 'available'
  | 'working'
  | 'finished_recently'
  | 'paused'
  | 'offline'
  | 'at_capacity';

export interface ProjectParticipant {
  id: string;
  kind: ProjectParticipantKind;
  role?: string | null;
  display_name?: string | null;
  email?: string | null;
  user_id?: string | null;
  membership_source?: 'owner' | 'project_membership' | 'project_collaborator' | null;
  agent_id?: string | null;
  agent_slug?: string | null;
  description?: string | null;
  assignment_status?: 'active' | 'inactive' | 'removed' | null;
  presence?: ProjectParticipantPresence | null;
}

export interface ProjectParticipantListResponse {
  items: ProjectParticipant[];
  totals: {
    total: number;
    humans: number;
    agents: number;
  };
}

export const projectKeys = {
  participants: (projectId?: string | null) => ['projects', 'participants', projectId] as const,
};

function normalizeApiError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Failed to create project';
}

export async function createProject(
  orgId: string | undefined,
  payload: CreateProjectRequest
): Promise<Project> {
  // Prefer unified `/v1/projects` (single project type; org optional).
  const endpoints = ['/v1/projects'];
  // Legacy org-scoped endpoints (may exist in some deployments).
  if (orgId) {
    endpoints.push(`/v1/orgs/${orgId}/projects`, `/v1/organizations/${orgId}/projects`);
  }

  await razeLog('INFO', 'Project create requested', {
    org_id: orgId ?? null,
    name: payload.name,
    visibility: payload.visibility,
  });

  let lastError: unknown = null;
  for (const endpoint of endpoints) {
    try {
      const body = endpoint === '/v1/projects' && orgId ? { ...payload, org_id: orgId } : payload;
      const created = await apiClient.post<Project>(endpoint, body);
      await razeLog('INFO', 'Project created', {
        org_id: orgId ?? null,
        project_id: created.id,
        project_slug: created.slug,
      });
      return created;
    } catch (error) {
      lastError = error;
    }
  }

  await razeLog('ERROR', 'Project create failed', {
    org_id: orgId ?? null,
    error: normalizeApiError(lastError),
  });

  throw lastError instanceof Error ? lastError : new Error(normalizeApiError(lastError));
}

export function useCreateProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: { orgId?: string; payload: CreateProjectRequest }) =>
      createProject(input.orgId, input.payload),
    onSuccess: async (_created, variables) => {
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.projects(variables.orgId) });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

export function useProjectParticipants(projectId?: string | null) {
  return useQuery({
    queryKey: projectKeys.participants(projectId),
    queryFn: async (): Promise<ProjectParticipantListResponse> => {
      if (!projectId) {
        return {
          items: [],
          totals: { total: 0, humans: 0, agents: 0 },
        };
      }
      const capabilities = await getApiCapabilities();
      if (!capabilities.routes.participants) {
        return {
          items: [],
          totals: { total: 0, humans: 0, agents: 0 },
        };
      }

      try {
        return await apiClient.get<ProjectParticipantListResponse>(`/v1/projects/${projectId}/participants`);
      } catch (error) {
        if (error instanceof ApiError && error.status < 500) {
          return {
            items: [],
            totals: { total: 0, humans: 0, agents: 0 },
          };
        }
        throw error;
      }
    },
    enabled: Boolean(projectId),
    staleTime: 30_000,
  });
}
