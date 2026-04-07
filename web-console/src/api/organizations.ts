/**
 * Organizations API
 *
 * Following:
 * - behavior_use_raze_for_logging (Student)
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiError } from './client';
import { dashboardKeys, type Organization } from './dashboard';
import { razeLog } from '../telemetry/raze';

export interface OrgMember {
  id: string;
  org_id: string;
  user_id: string;
  role: string;
  invited_by?: string | null;
  invited_at?: string | null;
  created_at: string;
  updated_at: string;
}

interface MemberListResponse {
  members: OrgMember[];
  total: number;
  page_info?: {
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
  };
}

export const organizationKeys = {
  members: (orgId?: string | null) => ['organizations', 'members', orgId] as const,
};

export interface CreateOrganizationRequest {
  name: string;
  slug: string;
  display_name?: string;
}

function normalizeApiError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Failed to create organization';
}

export async function createOrganization(payload: CreateOrganizationRequest): Promise<Organization> {
  const endpoints = ['/v1/orgs', '/v1/organizations'];

  await razeLog('INFO', 'Organization create requested', {
    name: payload.name,
    slug: payload.slug,
  });

  let lastError: unknown = null;
  for (const endpoint of endpoints) {
    try {
      const created = await apiClient.post<Organization>(endpoint, payload);
      await razeLog('INFO', 'Organization created', {
        org_id: created.id,
        org_slug: created.slug,
      });
      return created;
    } catch (error) {
      lastError = error;
    }
  }

  await razeLog('ERROR', 'Organization create failed', {
    error: normalizeApiError(lastError),
  });

  throw lastError instanceof Error ? lastError : new Error(normalizeApiError(lastError));
}

export function useCreateOrganization() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createOrganization,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.organizations() });
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.stats() });
    },
  });
}

export function useOrgMembers(orgId?: string | null) {
  return useQuery({
    queryKey: organizationKeys.members(orgId),
    queryFn: async (): Promise<OrgMember[]> => {
      if (!orgId) return [];
      const endpoints = [`/v1/orgs/${orgId}/members`, `/v1/organizations/${orgId}/members`];
      let lastError: unknown = null;
      for (const endpoint of endpoints) {
        try {
          const response = await apiClient.get<MemberListResponse>(`${endpoint}?limit=200`);
          return response.members ?? [];
        } catch (error) {
          if (error instanceof ApiError && (error.status === 404 || error.status === 403)) {
            continue;
          }
          lastError = error;
        }
      }
      if (lastError) throw lastError;
      return [];
    },
    enabled: Boolean(orgId),
    staleTime: 30_000,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status < 500) return false;
      return failureCount < 2;
    },
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  });
}
